"""Stand-in for Alvaro's panorama node: answers /survey/capture with /survey/capture_done
once frames_per_bubble captures have arrived for a bubble_id."""
from collections import Counter

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class FakePanorama(Node):
    def __init__(self):
        super().__init__('fake_panorama')
        self.n = self.declare_parameter('frames_per_bubble', 12).value
        self.counts = Counter()
        self.pub = self.create_publisher(String, '/survey/capture_done', 10)
        self.create_subscription(String, '/survey/capture', self._on_capture, 10)

    def _on_capture(self, msg):
        self.counts[msg.data] += 1
        self.get_logger().info(f'{msg.data} frame {self.counts[msg.data]}/{self.n}')
        if self.counts[msg.data] == self.n:
            self.pub.publish(String(data=msg.data))


def main():
    rclpy.init()
    node = FakePanorama()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
