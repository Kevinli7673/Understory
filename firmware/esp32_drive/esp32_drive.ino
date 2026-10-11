// Understory ESP32 drive firmware: mecanum base on an Adafruit Motor Shield V2 / Motor FeatherWing (I2C).
//
// Pi -> ESP32 (USB serial, 115200, one command per line), sent by pi/scripts/esp32_bridge.py from /cmd_vel:
//   C <vx> <vy> <wz>     body velocity, ROS axes: vx forward m/s, vy left m/s, wz counter-clockwise rad/s
//   S                    stop now
//   T <0-3>              wiring test: spin one wheel forward briefly (0 FL, 1 FR, 2 RL, 3 RR)
// ESP32 -> Pi:
//   {"temp_c": 24.1, ...}  sensor JSON line -> /sensors (missing sensors are omitted, never null)
//   # text                 status / debug (logged by the bridge, not published)
//
// Safety:
//   - Motors stop if no command arrives for WATCHDOG_MS (AGENTS.md: 300 ms). The bridge also sends "S" on e-stop.
//   - The shield's PWM chip keeps its last output on its own, so "stop" is re-written to every motor every
//     IDLE_REFRESH_MS while stopped; a lost write can't leave a wheel spinning.
//   - Writes go to the shield only when a wheel's speed/direction changes (less I2C traffic and motor noise).
//   - If the shield stops answering on I2C, the bus is reset and the shield re-initialised and stopped, retried
//     every RECOVER_MS until it answers. Failures are reported ("# ERROR: I2C ...") and counted.
//   - The boot line reports why the ESP32 last reset (e.g. BROWNOUT when the motors drag the supply down).
//
// Test without the Pi: Arduino IDE Serial Monitor at 115200, "Newline" line ending, type  C 0.1 0 0
// (forward; it stops 300 ms after each line, so expect a short bump per line).
//
// Library: "Adafruit Motor Shield V2 Library" (Library Manager). Board: your ESP32 board.

#include <Wire.h>
#include <Adafruit_MotorShield.h>
#include <esp_system.h>

// ------------------------------------------------------------------------------------------------
// CONFIG: everything hardware-specific is here.
// ------------------------------------------------------------------------------------------------
const uint8_t SHIELD_ADDR = 0x60;      // default address (solder jumpers change it)

// Which shield port (M1..M4) drives each wheel, in order: front-left, front-right, rear-left, rear-right.
const uint8_t WHEEL_PORT[4] = {1, 2, 3, 4};
// Flip a wheel to -1 if it spins backwards when the robot is told to drive forward (C 0.1 0 0).
const int8_t WHEEL_DIR[4] = {1, 1, 1, 1};

const float MAX_WHEEL_SPEED = 0.35f;   // m/s a wheel rim reaches at full PWM (calibrate: drive 1 m, time it)
const float K = 0.20f;                 // half wheelbase + half track width, meters (rotation lever arm)
const float PWM_CAP = 0.85f;           // 6 V motors on ~7.2 V (6x AA): cap at 85% (AGENTS.md)
const uint8_t PWM_MIN = 45;            // below this the motors just hum; nudge small commands up to it
const uint32_t WATCHDOG_MS = 300;      // stop if no command for this long
const uint32_t IDLE_REFRESH_MS = 100;  // while stopped, re-write "stop" to every motor this often
const uint32_t RECOVER_MS = 250;       // while the shield is not answering, retry this often
const uint32_t STATUS_MS = 2000;       // "# ..." status line period (also pings the shield)
const uint32_t SENSOR_MS = 1000;       // sensor JSON period (only if readSensors() fills anything)
// ------------------------------------------------------------------------------------------------

Adafruit_MotorShield shield(SHIELD_ADDR);
Adafruit_DCMotor *wheels[4];
bool shieldOk = false;

uint32_t lastCmdMs = 0, lastStatusMs = 0, lastSensorMs = 0, lastRefreshMs = 0, lastRecoverMs = 0;
bool moving = false;
float cmdVx = 0, cmdVy = 0, cmdWz = 0;
char line[96];
uint8_t lineLen = 0;
uint32_t commands = 0, i2cErrors = 0, recoveries = 0;

// What each wheel was last told (-1 unknown), so unchanged wheels aren't re-written.
int16_t lastPwm[4] = {-1, -1, -1, -1};
int8_t lastRun[4] = {-1, -1, -1, -1};   // FORWARD / BACKWARD / RELEASE

// Milliseconds since t, safe against the clock being read before t was stamped (no unsigned wrap).
uint32_t since(uint32_t t) {
  int32_t d = (int32_t)(millis() - t);
  return d < 0 ? 0 : (uint32_t)d;
}

void writeWheel(int i, int pwm, uint8_t run, bool force) {
  if (!shieldOk) return;
  if (!force && lastPwm[i] == pwm && lastRun[i] == run) return;
  wheels[i]->setSpeed(pwm);
  wheels[i]->run(run);
  lastPwm[i] = pwm;
  lastRun[i] = run;
}

void setWheel(int i, float speed) {           // speed in m/s, signed
  float s = speed * WHEEL_DIR[i];
  int pwm = (int)(fabsf(s) / MAX_WHEEL_SPEED * 255.0f * PWM_CAP + 0.5f);
  if (pwm == 0) { writeWheel(i, 0, RELEASE, false); return; }
  if (pwm < PWM_MIN) pwm = PWM_MIN;
  if (pwm > 255) pwm = 255;
  writeWheel(i, pwm, s > 0 ? FORWARD : BACKWARD, false);
}

void stopAll(bool force) {
  for (int i = 0; i < 4; i++) writeWheel(i, 0, RELEASE, force);
  moving = false;
  cmdVx = cmdVy = cmdWz = 0;
}

// Mecanum inverse kinematics (rollers at 45 deg, "X" pattern seen from above), ROS axes.
void drive(float vx, float vy, float wz) {
  float w[4] = {
    vx - vy - K * wz,   // front-left
    vx + vy + K * wz,   // front-right
    vx + vy - K * wz,   // rear-left
    vx - vy + K * wz,   // rear-right
  };
  // Scale everything down together if any wheel would exceed its max, so the direction is kept.
  float biggest = 0;
  for (int i = 0; i < 4; i++) biggest = fmaxf(biggest, fabsf(w[i]));
  float scale = biggest > MAX_WHEEL_SPEED ? MAX_WHEEL_SPEED / biggest : 1.0f;
  bool any = false;
  for (int i = 0; i < 4; i++) {
    float s = w[i] * scale;
    if (fabsf(s) < 0.005f) s = 0;
    any |= s != 0;
    setWheel(i, s);
  }
  moving = any;
  cmdVx = vx; cmdVy = vy; cmdWz = wz;
}

// Parse "C vx vy wz" / "S". Returns false for anything else (reported as "# bad: ...").
bool handleLine(char *s) {
  while (*s == ' ') s++;
  if (s[0] == 'S' && (s[1] == 0 || s[1] == ' ')) { stopAll(true); lastCmdMs = millis(); return true; }
  if (s[0] == 'T') {   // wiring test: "T 0".."T 3" spins one wheel "forward" for ~0.3 s (watchdog stops it)
    int i = atoi(s + 1);
    if (i < 0 || i > 3) return false;
    stopAll(false);
    setWheel(i, 0.4f * MAX_WHEEL_SPEED);
    moving = true;
    lastCmdMs = millis();
    const char *names[4] = {"front-left", "front-right", "rear-left", "rear-right"};
    Serial.printf("# test: %s (shield port M%d) should roll the robot FORWARD; if it rolls backward set WHEEL_DIR[%d] = -1\n",
                  names[i], WHEEL_PORT[i], i);
    return true;
  }
  if (s[0] != 'C') return false;
  char *p = s + 1, *end;
  float v[3];
  for (int k = 0; k < 3; k++) {
    v[k] = strtof(p, &end);
    if (end == p) return false;
    p = end;
  }
  if (!isfinite(v[0]) || !isfinite(v[1]) || !isfinite(v[2])) return false;
  drive(v[0], v[1], v[2]);
  lastCmdMs = millis();
  commands++;
  return true;
}

// Grove sensor pod hook: append "key": value pairs for the sensors that are present and return true.
// Keys must match AGENTS.md /survey/readings: temp_c, pressure_hpa, soil_moisture, light, uv, air_quality, sound.
// Example once a sensor is wired:  out += "\"soil_moisture\": " + String(analogRead(34));
bool readSensors(String &out) {
  return false;  // no sensors yet; pi/scripts/fake_sensors.py stands in
}

const char *resetReason() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "power-on";
    case ESP_RST_BROWNOUT: return "BROWNOUT (supply dipped: motors sharing the ESP32's supply or ground?)";
    case ESP_RST_PANIC: return "crash (panic)";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT: return "watchdog (program hung)";
    case ESP_RST_SW: return "software reset";
    case ESP_RST_EXT: return "reset pin";
    default: return "other";
  }
}

bool shieldAnswers() {
  Wire.beginTransmission(SHIELD_ADDR);
  return Wire.endTransmission() == 0;
}

bool startShield() {
  if (!shield.begin(1600, &Wire)) return false;
  for (int i = 0; i < 4; i++) { wheels[i] = shield.getMotor(WHEEL_PORT[i]); lastPwm[i] = -1; lastRun[i] = -1; }
  shieldOk = true;
  stopAll(true);
  return true;
}

// Shield lost: reset the I2C bus (frees a stuck SDA line), re-initialise the shield and stop every motor.
void recoverShield() {
  Wire.end();
  delay(2);
  Wire.begin();
  Wire.setTimeOut(20);
  if (shieldAnswers() && startShield()) {
    recoveries++;
    Serial.print("# motor shield recovered after I2C failure, motors stopped (recoveries: ");
    Serial.print(recoveries);
    Serial.println(")");
  }
}

void markShieldLost(uint8_t err) {
  i2cErrors++;
  shieldOk = false;
  moving = false;
  Serial.print("# ERROR: I2C to motor shield failed (code ");
  Serial.print(err);
  Serial.print(", ");
  Serial.print(i2cErrors);
  Serial.println(" so far): loose SDA/SCL/GND wire, or motor noise on the I2C lines. Resetting I2C.");
}

void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setTimeOut(20);   // a glitchy I2C line can't freeze the loop
  if (startShield()) {
    Serial.print("# understory drive ready (motor shield ok), last reset: ");
  } else {
    Serial.print("# ERROR: motor shield not found on I2C (check SDA/SCL wiring, power, address 0x60), last reset: ");
  }
  Serial.println(resetReason());
}

void loop() {
  // Read commands; tolerate \r\n and overlong lines.
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen > 0) {
        line[lineLen] = 0;
        if (!handleLine(line)) { Serial.print("# bad: "); Serial.println(line); }
        lineLen = 0;
      }
    } else if (lineLen < sizeof(line) - 1) {
      line[lineLen++] = c;
    } else {
      lineLen = 0;  // overlong garbage: drop it
    }
  }

  // Watchdog: no command for WATCHDOG_MS -> stop. (since() can't wrap if a command just arrived.)
  if (moving && since(lastCmdMs) > WATCHDOG_MS) {
    stopAll(true);
    Serial.println("# watchdog: no command for 300 ms, motors stopped");
  }

  // While stopped, keep re-writing "stop" so a lost I2C write can't leave a wheel running.
  if (shieldOk && !moving && since(lastRefreshMs) >= IDLE_REFRESH_MS) {
    lastRefreshMs = millis();
    stopAll(true);
  }

  // Shield not answering: keep trying to get it back (and stopped).
  if (!shieldOk && since(lastRecoverMs) >= RECOVER_MS) {
    lastRecoverMs = millis();
    recoverShield();
  }

  if (since(lastSensorMs) >= SENSOR_MS) {
    lastSensorMs = millis();
    String fields;
    if (readSensors(fields)) Serial.println("{" + fields + "}");
  }

  if (since(lastStatusMs) >= STATUS_MS) {
    lastStatusMs = millis();
    if (shieldOk) {
      Wire.beginTransmission(SHIELD_ADDR);
      uint8_t err = Wire.endTransmission();
      if (err != 0) markShieldLost(err);
    }
    Serial.printf("# status shield=%s moving=%d cmd=(%.2f %.2f %.2f) cmds=%lu age=%lums i2c_errors=%lu\n",
                  shieldOk ? "ok" : "MISSING", moving, cmdVx, cmdVy, cmdWz,
                  (unsigned long)commands, (unsigned long)since(lastCmdMs), (unsigned long)i2cErrors);
  }
}
