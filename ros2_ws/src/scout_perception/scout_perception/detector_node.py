"""detector_node: /camera/image/compressed -> /detections (String JSON).

    ros2 run scout_perception detector_node --ros-args -p backend:=dummy
    ... -p backend:=owlvit_torch -p score_threshold:=0.15 -p "prompts:=['a plant', 'a leaf']"

/detections: {"t": 1791600000.12, "frame_id": "camera",
              "boxes": [{"label": "...", "score": 0.5, "xyxy": [x1, y1, x2, y2]}]}
"""
import json

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from scout_perception.backends import DEFAULT_PROMPTS, make_backend


class DetectorNode(Node):
    def __init__(self):
        super().__init__('detector_node')
        backend = self.declare_parameter('backend', 'dummy').value
        prompts = self.declare_parameter('prompts', DEFAULT_PROMPTS).value
        threshold = self.declare_parameter('score_threshold', 0.1).value
        self.backend = make_backend(backend, prompts, threshold)
        self.pub = self.create_publisher(String, '/detections', 10)
        # best-effort with depth 1: if the model is slower than the camera, drop old frames
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(CompressedImage, '/camera/image/compressed', self.on_image, qos)
        self.get_logger().info(f'detector running, backend={backend}, prompts={prompts}, threshold={threshold}')

    def on_image(self, msg):
        bgr = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            self.get_logger().warn('could not decode frame', throttle_duration_sec=5.0)
            return
        stamp = msg.header.stamp
        self.pub.publish(String(data=json.dumps({
            't': stamp.sec + stamp.nanosec * 1e-9,
            'frame_id': msg.header.frame_id,
            'boxes': self.backend.detect(bgr)})))


def main():
    rclpy.init()
    try:
        rclpy.spin(DetectorNode())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
