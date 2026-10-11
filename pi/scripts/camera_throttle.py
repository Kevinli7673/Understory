#!/usr/bin/env python3
"""camera_throttle: republish every Nth camera frame for a machine on a weak link.

    python3 /fetch_ws/scripts/camera_throttle.py            # 15 Hz in -> about 3 Hz on /camera/image/throttled
    python3 /fetch_ws/scripts/camera_throttle.py --rate 5

Run it on the machine that has the camera (the Pi). The Jetson's AI then reads the slow topic:
CAMERA_TOPIC=/camera/image/throttled ~/start_understory.sh. Why: on a 2.4 GHz phone hotspot the full
15 Hz stream (about 8 Mbit/s, each frame about 50 IP fragments) pushed ping between the two machines past
1 s (Sun 1:45 AM). The Quest and the panorama node keep the full-rate topic. Headers are passed on unchanged.
"""
import argparse

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


class CameraThrottle(Node):
    def __init__(self, rate, source, target):
        super().__init__('camera_throttle')
        self.period = 1.0 / rate
        self.last = 0.0
        self.pub = self.create_publisher(CompressedImage, target, qos_profile_sensor_data)
        self.create_subscription(CompressedImage, source, self.on_image, qos_profile_sensor_data)
        self.get_logger().info(f'{source} -> {target} at up to {rate:g} Hz')

    def on_image(self, msg):
        now = self.get_clock().now().nanoseconds / 1e9
        if now - self.last >= self.period * 0.9:
            self.last = now
            self.pub.publish(msg)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--rate', type=float, default=3.0, help='frames per second to pass on (default 3)')
    ap.add_argument('--source', default='/camera/image/compressed')
    ap.add_argument('--target', default='/camera/image/throttled')
    args = ap.parse_args()
    rclpy.init()
    try:
        rclpy.spin(CameraThrottle(args.rate, args.source, args.target))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
