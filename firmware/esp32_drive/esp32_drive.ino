// Understory ESP32 drive firmware: mecanum base on an Adafruit Motor Shield V2 / Motor FeatherWing (I2C).
//
// Pi -> ESP32 (USB serial, 115200, one command per line), sent by pi/scripts/esp32_bridge.py from /cmd_vel:
//   C <vx> <vy> <wz>     body velocity, ROS axes: vx forward m/s, vy left m/s, wz counter-clockwise rad/s
//   S                    stop now
// ESP32 -> Pi:
//   {"temp_c": 24.1, ...}  sensor JSON line -> /sensors (missing sensors are omitted, never null)
//   # text                 status / debug (logged by the bridge, not published)
//
// Safety: motors stop if no command arrives for WATCHDOG_MS (AGENTS.md: 300 ms). The e-stop itself is
// handled upstream by twist_mux (it stops sending /cmd_vel), so the watchdog is what actually stops the wheels.
//
// Test without the Pi: Arduino IDE Serial Monitor at 115200, "Newline" line ending, type  C 0.1 0 0
// (forward, keeps going while you re-send it within 300 ms, so expect a short bump per line).
//
// Library: "Adafruit Motor Shield V2 Library" (Library Manager). Board: your ESP32 board.

#include <Wire.h>
#include <Adafruit_MotorShield.h>

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
const uint32_t STATUS_MS = 2000;       // "# ..." status line period
const uint32_t SENSOR_MS = 1000;       // sensor JSON period (only if readSensors() fills anything)
// ------------------------------------------------------------------------------------------------

Adafruit_MotorShield shield(SHIELD_ADDR);
Adafruit_DCMotor *wheels[4];
bool shieldOk = false;

uint32_t lastCmdMs = 0, lastStatusMs = 0, lastSensorMs = 0;
bool moving = false;
float cmdVx = 0, cmdVy = 0, cmdWz = 0;
char line[96];
uint8_t lineLen = 0;
uint32_t commands = 0;

void setWheel(int i, float speed) {           // speed in m/s, signed
  if (!shieldOk) return;
  float s = speed * WHEEL_DIR[i];
  int pwm = (int)(fabsf(s) / MAX_WHEEL_SPEED * 255.0f * PWM_CAP + 0.5f);
  if (pwm == 0) { wheels[i]->run(RELEASE); return; }
  if (pwm < PWM_MIN) pwm = PWM_MIN;
  if (pwm > 255) pwm = 255;
  wheels[i]->setSpeed(pwm);
  wheels[i]->run(s > 0 ? FORWARD : BACKWARD);
}

void stopAll() {
  if (shieldOk) for (int i = 0; i < 4; i++) wheels[i]->run(RELEASE);
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

// Parse "C vx vy wz" / "S". Returns false for anything else (reported once as "# bad: ...").
bool handleLine(char *s) {
  while (*s == ' ') s++;
  if (s[0] == 'S' && (s[1] == 0 || s[1] == ' ')) { stopAll(); lastCmdMs = millis(); return true; }
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

void setup() {
  Serial.begin(115200);
  Wire.begin();
  shieldOk = shield.begin(1600, &Wire);
  if (shieldOk) {
    for (int i = 0; i < 4; i++) wheels[i] = shield.getMotor(WHEEL_PORT[i]);
    stopAll();
    Serial.println("# understory drive ready (motor shield ok)");
  } else {
    Serial.println("# ERROR: motor shield not found on I2C (check SDA/SCL wiring, power, address 0x60)");
  }
}

void loop() {
  uint32_t now = millis();

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

  // Watchdog: no command for WATCHDOG_MS -> stop.
  if (moving && now - lastCmdMs > WATCHDOG_MS) {
    stopAll();
    Serial.println("# watchdog: no command for 300 ms, motors stopped");
  }

  if (now - lastSensorMs >= SENSOR_MS) {
    lastSensorMs = now;
    String fields;
    if (readSensors(fields)) Serial.println("{" + fields + "}");
  }

  if (now - lastStatusMs >= STATUS_MS) {
    lastStatusMs = now;
    Serial.printf("# status shield=%s moving=%d cmd=(%.2f %.2f %.2f) cmds=%lu age=%lums\n",
                  shieldOk ? "ok" : "MISSING", moving, cmdVx, cmdVy, cmdWz,
                  (unsigned long)commands, (unsigned long)(now - lastCmdMs));
  }
}
