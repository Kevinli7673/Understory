#!/usr/bin/env python3
"""Publish FAKE /sensors JSON, shaped like the ESP32 bridge will send it (no x/y, no mission_id),
so localizer_node's /survey/readings can be tested before the bridge exists.

Run inside the container (~/scout_shell.sh on the host first):
    python3 /fetch_ws/scripts/fake_sensors.py            # 1 Hz
    python3 /fetch_ws/scripts/fake_sensors.py --rate 2

Stop it as soon as the real bridge publishes /sensors. About one message in five leaves out the
soil probe, because a missing sensor must be omitted, never sent as null.
"""
import argparse
import json
import math
import random
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class FakeSensors(Node):
    def __init__(self, rate):
        super().__init__('fake_sensors')
        self.pub = self.create_publisher(String, '/sensors', 10)
        self.create_timer(1.0 / rate, self.tick)
        self.get_logger().info(f'publishing FAKE /sensors at {rate} Hz')

    def tick(self):
        t = time.time()
        reading = {
            't': round(t, 2),
            'temp_c': round(24 + 1.5 * math.sin(t / 60) + random.uniform(-0.1, 0.1), 1),
            'pressure_hpa': round(1013 + random.uniform(-0.3, 0.3), 1),
            'soil_moisture': random.randint(380, 450), 'light': random.randint(300, 380),
            'uv': round(random.uniform(0.0, 0.4), 1), 'air_quality': random.randint(95, 130),
            'sound': random.randint(40, 65)}
        if random.random() < 0.2:
            del reading['soil_moisture']
        self.pub.publish(String(data=json.dumps(reading)))


def main():
    ap = argparse.ArgumentParser(description='Publish fake /sensors readings.')
    ap.add_argument('--rate', type=float, default=1.0, help='messages per second (default 1)')
    args = ap.parse_args()
    rclpy.init()
    try:
        rclpy.spin(FakeSensors(args.rate))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
