#!/usr/bin/env python3
"""ESP32 serial bridge: /cmd_vel -> wheels, ESP32 sensor JSON -> /sensors.

Run inside the container (~/scout_shell.sh on the host first), ESP32 plugged into the Pi by USB:
    python3 /fetch_ws/src/Understory/pi/scripts/esp32_bridge.py
    python3 /fetch_ws/src/Understory/pi/scripts/esp32_bridge.py --port /dev/ttyUSB1
    python3 /fetch_ws/src/Understory/pi/scripts/esp32_bridge.py --trim 0.8,1.15,1.15,0.8   # even out wheels
    python3 /fetch_ws/src/Understory/pi/scripts/esp32_bridge.py --strafe-fix 0.8      # strafe drifts back/forward
    python3 /fetch_ws/src/Understory/pi/scripts/esp32_bridge.py --no-strafe           # drive + turn only

Firmware and line protocol: firmware/esp32_drive/esp32_drive.ino
    to ESP32:   "C <vx> <vy> <wz>\\n"  (ROS axes, m/s and rad/s), sent for every /cmd_vel message
    from ESP32: "{...}" sensor JSON -> /sensors (std_msgs/String), "# ..." status -> log

/cmd_vel comes from twist_mux (e-stop > Quest teleop > autonomy). Over the hotspot (Quest -> Pi -> Jetson
twist_mux -> Pi) commands arrive in bursts with gaps > 300 ms, so the ESP32's watchdog kept stopping the
wheels. The bridge therefore re-sends the latest command at 20 Hz while it is < --hold seconds old (0.5 s,
twist_mux's own timeout). When commands stop, re-sending stops and the 300 ms watchdog stops the motors
(<= ~0.8 s); a dead bridge, Pi or cable also stops the robot. /estop true -> immediate "S" and no
re-sending until released (doesn't wait for twist_mux). Stop fake_sensors.py once the real sensor pod
publishes here.

Port: --port, else the first /dev/serial/by-id device that is NOT the LiDAR (its CP2102N id is in
scout_bringup.launch.py, and many ESP32 boards use the same chip), else /dev/ttyACM* (never ttyUSB*: the LiDAR).
A by-id --port that is unplugged is waited for, not swapped for another device.
"""
import argparse
import glob
import json
import os
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool, String

import serial

LIDAR_ID = '5839a1d8ce6ff01187f694301045c30f'  # from pi/scout_bringup.launch.py


def find_port():
    lidar_paths = {os.path.realpath(p) for p in glob.glob('/dev/serial/by-id/*') if LIDAR_ID in p}
    for p in sorted(glob.glob('/dev/serial/by-id/*')):
        if LIDAR_ID not in p:
            return p
    # Fallback: ttyACM only (the QT Py's native USB). Never ttyUSB*: that is the LiDAR's CP2102N, and right after
    # a USB re-enumeration its by-id link may not exist yet, so it can't be excluded by id (grabbed it once).
    for p in sorted(glob.glob('/dev/ttyACM*')):
        if os.path.realpath(p) not in lidar_paths:
            return p
    return None


class Esp32Bridge(Node):
    def __init__(self, port, baud, hold, trim, strafe_fix, no_strafe):
        super().__init__('esp32_bridge')
        self.port_arg, self.baud, self.hold = port, baud, hold
        self.strafe_fix, self.no_strafe = strafe_fix, no_strafe
        self.trim_line = 'W ' + ' '.join(f'{t:.3f}' for t in trim) + '\n'   # per-wheel speed trim FL FR RL RR
        self.ser = None
        self.buf = b''
        self.last_status = ''
        self.sent = 0
        self.last_cmd = None        # latest command line, re-sent while fresh
        self.last_cmd_t = 0.0
        self.estop = False
        self.pub = self.create_publisher(String, '/sensors', 10)
        self.create_subscription(Twist, '/cmd_vel', self.on_cmd, 10)
        self.create_subscription(Bool, '/estop', self.on_estop, 10)
        self.create_timer(0.05, self.resend)        # 20 Hz keep-alive of the latest command
        self.create_timer(0.02, self.poll)          # read ESP32 output at 50 Hz
        self.create_timer(2.0, self.ensure_open)    # (re)connect if unplugged
        self.ensure_open()

    def ensure_open(self):
        if self.ser is not None:
            self.write(self.trim_line)   # every 2 s, so an ESP32 reset gets the trim back
            return
        port = self.port_arg or find_port()
        if not port:
            self.get_logger().warn('no ESP32 serial port found (is it plugged in? try --port)', throttle_duration_sec=10.0)
            return
        try:
            self.ser = serial.Serial(port, self.baud, timeout=0, write_timeout=0.05)
            self.get_logger().info(f'ESP32 on {port} @ {self.baud}, trim {self.trim_line.strip()}')
            self.write(self.trim_line)
        except (serial.SerialException, OSError) as e:
            self.get_logger().warn(f'cannot open {port}: {e}', throttle_duration_sec=10.0)
            self.ser = None

    def drop(self, why):
        self.get_logger().error(f'ESP32 serial lost ({why}); reconnecting')
        try:
            self.ser.close()
        except Exception:
            pass
        self.ser = None
        self.buf = b''

    def write(self, line):
        if self.ser is None:
            return
        try:
            self.ser.write(line.encode('ascii'))
            self.sent += 1
        except (serial.SerialException, OSError) as e:
            self.drop(e)

    def on_cmd(self, msg):
        if self.estop:
            return
        vx, vy = msg.linear.x, msg.linear.y
        if self.no_strafe:
            vy = 0.0
        else:
            vx += self.strafe_fix * vy   # cancel the forward/back drift this robot has while strafing
        self.last_cmd = f'C {vx:.3f} {vy:.3f} {msg.angular.z:.3f}\n'
        self.last_cmd_t = time.monotonic()
        self.write(self.last_cmd)

    def resend(self):
        if self.estop or self.last_cmd is None:
            return
        if time.monotonic() - self.last_cmd_t < self.hold:
            self.write(self.last_cmd)
        else:
            self.last_cmd = None    # stale: stop re-sending; the ESP32 watchdog stops the motors

    def on_estop(self, msg):
        if msg.data and not self.estop:
            self.get_logger().warn('E-STOP: motors stopped')
        elif not msg.data and self.estop:
            self.get_logger().info('e-stop released')
        self.estop = msg.data
        if self.estop:
            self.last_cmd = None
            self.write('S\n')

    def poll(self):
        if self.ser is None:
            return
        try:
            self.buf += self.ser.read(4096)
        except (serial.SerialException, OSError) as e:
            self.drop(e)
            return
        while b'\n' in self.buf:
            raw, self.buf = self.buf.split(b'\n', 1)
            text = raw.decode('utf-8', 'replace').strip()
            if not text:
                continue
            if text.startswith('{'):
                try:
                    json.loads(text)
                except ValueError:
                    self.get_logger().warn(f'bad sensor JSON: {text}')
                    continue
                self.pub.publish(String(data=text))
            elif text.startswith('#'):
                # Status every 2 s: log only changes (plus errors / watchdog) so the log stays readable.
                status = text.split(' cmds=')[0]
                if 'ERROR' in text or 'watchdog' in text or 'bad' in text:
                    self.get_logger().warn(text)
                elif status != self.last_status:
                    self.get_logger().info(text)
                self.last_status = status
            else:
                self.get_logger().debug(f'esp32: {text}')
        if len(self.buf) > 8192:
            self.buf = b''


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', default='', help='serial device (default: auto, never the LiDAR)')
    ap.add_argument('--baud', type=int, default=115200)
    ap.add_argument('--hold', type=float, default=0.5,
                    help='re-send the latest /cmd_vel while it is younger than this (s); bridges Wi-Fi gaps')
    ap.add_argument('--trim', default='1,1,1,1',
                    help='per-wheel speed multipliers FL,FR,RL,RR (0.3-2.0), e.g. 0.8,1.15,1.15,0.8')
    ap.add_argument('--strafe-fix', type=float, default=0.0,
                    help='add this x vy to vx: strafe left drifts backward -> positive (try 0.5..1.0), forward -> negative')
    ap.add_argument('--no-strafe', action='store_true', help='ignore sideways commands (drive + turn only)')
    args = ap.parse_args()
    trim =[float(t) for t in args.trim.split(',')]
    if len(trim) != 4 or not all(0.3 <= t <= 2.0 for t in trim):
        ap.error('--trim needs 4 numbers between 0.3 and 2.0')
    rclpy.init()
    node = Esp32Bridge(args.port, args.baud, args.hold, trim, args.strafe_fix, args.no_strafe)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):  # Ctrl+C, or pkill / scout_down.sh
        pass
    finally:
        if node.ser is not None:
            try:
                node.ser.write(b'S\n')  # stop on the way out
            except Exception:
                pass
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
