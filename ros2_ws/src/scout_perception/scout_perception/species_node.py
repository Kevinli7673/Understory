"""species_node: names the plant in each /detections box -> /species (String JSON, one per box).

    ros2 run scout_perception species_node --ros-args -p backend:=bioclip

/species: {"t": 1791600000.12, "frame_id": "camera", "label": "Brazilian pepper", "invasive": true,
           "confidence": 0.81, "xyxy": [x1, y1, x2, y2], "embedding": [512 floats]}

`t` is the stamp of the camera frame the box came from; the crop is cut from that same frame,
not from the latest one. The species list lives in species_labels.py.
"""
import json
from collections import OrderedDict

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from scout_perception.species_backends import make_species_backend


class SpeciesNode(Node):
    def __init__(self):
        super().__init__('species_node')
        backend = self.declare_parameter('backend', 'dummy').value
        # below this the crop is "none of the listed plants" and nothing is published
        self.min_confidence = self.declare_parameter('min_confidence', 0.5).value
        self.max_boxes = self.declare_parameter('max_boxes', 3).value          # per frame, best first
        self.min_box_px = self.declare_parameter('min_box_px', 24).value
        self.backend = make_species_backend(backend)
        self.frames = OrderedDict()        # stamp in nanoseconds -> JPEG bytes, newest last

        self.pub = self.create_publisher(String, '/species', 10)
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(CompressedImage, '/camera/image/compressed', self.on_image, qos)
        # depth 1: if classifying is slower than the detector, skip to the newest detections
        self.create_subscription(String, '/detections', self.on_detections, 1)
        self.get_logger().info(f'species node running, backend={backend}')

    def on_image(self, msg):
        self.frames[msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec] = bytes(msg.data)
        while len(self.frames) > 60:                    # about 4 s at 15 Hz
            self.frames.popitem(last=False)

    def on_detections(self, msg):
        try:
            det = json.loads(msg.data)
            boxes = sorted(det['boxes'], key=lambda b: -b['score'])[:self.max_boxes]
            stamp = round(det['t'] * 1e9)
        except (ValueError, KeyError, TypeError):
            self.get_logger().warn('bad /detections message', throttle_duration_sec=5.0)
            return
        if not boxes:
            return
        # the detector sends t as a float, so allow for rounding when matching the frame
        key = min(self.frames, key=lambda k: abs(k - stamp), default=None)
        if key is None or abs(key - stamp) > 2_000_000:
            self.get_logger().warn('no camera frame for these detections (too old?)', throttle_duration_sec=5.0)
            return
        bgr = cv2.imdecode(np.frombuffer(self.frames[key], np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            return
        h, w = bgr.shape[:2]
        for box in boxes:
            x1, y1, x2, y2 = (int(round(v)) for v in box['xyxy'])
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
            if x2 - x1 < self.min_box_px or y2 - y1 < self.min_box_px:
                continue
            label, invasive, confidence, embedding = self.backend.classify(bgr[y1:y2, x1:x2])
            if label is None or confidence < self.min_confidence:
                continue
            self.pub.publish(String(data=json.dumps({
                't': det['t'], 'frame_id': det.get('frame_id', ''), 'label': label, 'invasive': invasive,
                'confidence': round(confidence, 3), 'xyxy': [x1, y1, x2, y2], 'embedding': embedding})))


def main():
    rclpy.init()
    try:
        rclpy.spin(SpeciesNode())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
