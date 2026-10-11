#!/usr/bin/env python3
"""ROS 2 node: /scan + TF (map -> laser, map -> base_link) -> map-frame points, POSTed to the dashboard relay.

Runs wherever mapping runs (Jetson or Pi container), next to pose_from_tf.py. Standard library only besides
rclpy/tf2_ros, so nothing to pip install in the container.

    python3 dashboard/scan_bridge.py --relay http://<laptop-ip>:8770
    python3 dashboard/scan_bridge.py --relay http://<laptop-ip>:8770 --rate 5 --max-points 720

The relay is dashboard/live_relay.py on the laptop. A dead relay only logs a warning; the robot is unaffected.
"""
import argparse
import json
import os
import sys
import threading
import time
import urllib.request

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformException, TransformListener

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_scan import scan_to_points, yaw_from_quaternion  # noqa: E402


def pose_of(t):
    q = t.transform.rotation
    return (t.transform.translation.x, t.transform.translation.y, yaw_from_quaternion(q.x, q.y, q.z, q.w))


class ScanBridge(Node):
    def __init__(self, relay, rate, max_points, map_frame, base_frame):
        super().__init__('scan_bridge')
        self.url = relay.rstrip('/') + '/scan'
        self.period = 1.0 / rate
        self.max_points = max_points
        self.map_frame, self.base_frame = map_frame, base_frame
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.create_subscription(LaserScan, '/scan', self.on_scan, qos_profile_sensor_data)
        self.last_sent = 0.0
        self.pending = None
        self.wake = threading.Event()
        self.relay_ok = None
        self.tf_ok = None
        threading.Thread(target=self.sender, daemon=True).start()
        self.get_logger().info(f'/scan -> {self.url} at <= {rate} Hz')

    def on_scan(self, msg):
        now = time.monotonic()
        if now - self.last_sent < self.period:
            return
        try:
            laser = pose_of(self.tf_buffer.lookup_transform(self.map_frame, msg.header.frame_id, Time()))
            base = pose_of(self.tf_buffer.lookup_transform(self.map_frame, self.base_frame, Time()))
        except TransformException as e:
            if self.tf_ok is not False:
                self.get_logger().warn(f'no TF {self.map_frame} -> {msg.header.frame_id} yet ({e}); is slam running?')
            self.tf_ok = False
            return
        if self.tf_ok is not True:
            self.get_logger().info('TF found, sending scans')
        self.tf_ok = True
        self.last_sent = now
        points = scan_to_points(msg.ranges, msg.angle_min, msg.angle_increment, msg.range_min, msg.range_max,
                                laser, self.max_points)
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        self.pending = {'t': stamp, 'pose': {'x': round(base[0], 3), 'y': round(base[1], 3),
                                             'yaw': round(base[2], 3)}, 'points': points}
        self.wake.set()

    def sender(self):
        """HTTP off the ROS callback thread, newest scan only."""
        while True:
            self.wake.wait()
            self.wake.clear()
            scan, self.pending = self.pending, None
            if scan is None:
                continue
            req = urllib.request.Request(self.url, data=json.dumps(scan).encode(), method='POST',
                                         headers={'Content-Type': 'application/json'})
            try:
                urllib.request.urlopen(req, timeout=1.0).read()
                if self.relay_ok is not True:
                    self.get_logger().info('relay reachable')
                self.relay_ok = True
            except Exception as e:
                if self.relay_ok is not False:
                    self.get_logger().warn(f'relay {self.url} unreachable ({e.__class__.__name__}); will keep trying')
                self.relay_ok = False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--relay', required=True, help='http://<laptop-ip>:8770')
    parser.add_argument('--rate', type=float, default=5.0)
    parser.add_argument('--max-points', type=int, default=720)
    parser.add_argument('--map-frame', default='map')
    parser.add_argument('--base-frame', default='base_link')
    args, ros_args = parser.parse_known_args()
    rclpy.init(args=ros_args)
    node = ScanBridge(args.relay, args.rate, args.max_points, args.map_frame, args.base_frame)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
