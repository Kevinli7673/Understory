#!/usr/bin/env python3
"""Stand-in robot for testing the plant AI with no robot and no plant in front of the camera.

Shows each photo in a folder to the detector as if it were the camera, with a fake LiDAR wall
`--wall` metres away and the robot parked at the map origin, then reports what came out of
/detections, /species and /survey/pins. Run it through ai_selftest.sh, which puts it and the three
AI nodes on their own ROS domain so the real robot and the Quest never see the fake data.
"""
import argparse
import glob
import json
import math
import os
import time

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, LaserScan
from std_msgs.msg import String
from tf2_ros import StaticTransformBroadcaster


class SelfTest(Node):
    def __init__(self, paths, hold, wall):
        super().__init__('ai_selftest')
        self.paths, self.hold, self.wall = paths, hold, wall
        self.start = time.time()
        self.counts = {'/detections': 0, '/species': 0}
        self.boxes = 0
        self.species = {}                  # photo -> {label: sightings}
        self.pins = []
        self.jpegs = [self.as_camera_frame(p) for p in paths]

        self.pub_image = self.create_publisher(CompressedImage, '/camera/image/compressed', qos_profile_sensor_data)
        self.pub_scan = self.create_publisher(LaserScan, '/scan', qos_profile_sensor_data)
        tf = StaticTransformBroadcaster(self)
        tf.sendTransform([self.transform('map', 'base_link'), self.transform('base_link', 'camera'),
                          self.transform('base_link', 'laser')])
        self.keep = tf
        self.create_subscription(String, '/detections', self.on_detections, 10)
        self.create_subscription(String, '/species', self.on_species, 10)
        self.create_subscription(String, '/survey/pins', self.on_pin, 10)
        self.create_timer(0.2, self.send_image)
        self.create_timer(0.1, self.send_scan)

    def transform(self, parent, child):
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id, t.child_frame_id = parent, child
        t.transform.rotation.w = 1.0
        return t

    @staticmethod
    def as_camera_frame(path):
        """The photo, fitted into the right half of a grey 640x480 frame."""
        photo = cv2.imread(path)
        canvas = np.full((480, 640, 3), 90, np.uint8)
        scale = min(300 / photo.shape[0], 300 / photo.shape[1])
        small = cv2.resize(photo, (int(photo.shape[1] * scale), int(photo.shape[0] * scale)))
        canvas[90:90 + small.shape[0], 320:320 + small.shape[1]] = small
        return cv2.imencode('.jpg', canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()

    def index(self):
        return int((time.time() - self.start) / self.hold)

    def done(self):
        return self.index() >= len(self.paths)

    def send_image(self):
        if self.done():
            return
        msg = CompressedImage(format='jpeg', data=self.jpegs[self.index()])
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'camera'
        self.pub_image.publish(msg)

    def send_scan(self):
        msg = LaserScan(angle_min=-math.pi, angle_max=math.pi, angle_increment=2 * math.pi / 720,
                        range_min=0.15, range_max=16.0, ranges=[self.wall] * 720)
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'laser'
        self.pub_scan.publish(msg)

    def on_detections(self, msg):
        self.counts['/detections'] += 1
        self.boxes += len(json.loads(msg.data)['boxes'])

    def on_species(self, msg):
        self.counts['/species'] += 1
        s = json.loads(msg.data)
        shown = int((s['t'] - self.start) / self.hold)      # which photo that frame was, not what is up now
        if 0 <= shown < len(self.paths):
            seen = self.species.setdefault(os.path.basename(self.paths[shown]), {})
            seen[s['label']] = seen.get(s['label'], 0) + 1
        self.embedding = len(s.get('embedding', []))

    def on_pin(self, msg):
        pin = json.loads(msg.data)
        self.pins.append(pin)
        print(f'  pin {pin["pin_id"]}: {pin["label"]} invasive={pin["invasive"]} conf={pin["confidence"]} '
              f'at ({pin["x"]}, {pin["y"]})', flush=True)


def main():
    ap = argparse.ArgumentParser(description='Feed plant photos to the AI nodes and report the result.')
    ap.add_argument('folder', help='folder of .jpg plant photos')
    ap.add_argument('--hold', type=float, default=20.0, help='seconds each photo stays in view (default 20)')
    ap.add_argument('--wall', type=float, default=2.0, help='fake LiDAR distance in metres (default 2)')
    args = ap.parse_args()
    paths = sorted(glob.glob(os.path.join(args.folder, '*.jpg')))
    if not paths:
        raise SystemExit(f'no .jpg files in {args.folder}')

    rclpy.init()
    node = SelfTest(paths, args.hold, args.wall)
    print(f'{len(paths)} photos, {args.hold:.0f} s each', flush=True)
    while rclpy.ok() and time.time() - node.start < len(paths) * args.hold + 8:
        rclpy.spin_once(node, timeout_sec=0.1)

    elapsed = time.time() - node.start
    print(f'\n/detections: {node.counts["/detections"]} messages ({node.counts["/detections"] / elapsed:.2f} Hz), '
          f'{node.boxes} boxes')
    print(f'/species: {node.counts["/species"]} messages, embedding length {getattr(node, "embedding", "n/a")}')
    for photo in map(os.path.basename, paths):
        print(f'  {photo}: {node.species.get(photo, "nothing")}')
    print(f'/survey/pins: {len({p["pin_id"] for p in node.pins})} pins')
    print('RESULT: ' + ('PASS' if node.pins else 'FAIL (no pins; read the three logs)'))


if __name__ == '__main__':
    main()
