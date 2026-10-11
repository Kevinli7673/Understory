"""logger_node: writes each mission to disk in the folder layout from AGENTS.md.

    ros2 run scout_perception logger_node --ros-args -p missions_dir:=/fetch_ws/missions

In:  /survey/bubbles, /survey/pins, /survey/readings   String (JSON)
     /survey/bubble_images                              CompressedImage, frame_id "<bubble_id>/<index>" or ".../pano"
     /map                                               OccupancyGrid
Out: missions/<mission_id>/ bubbles.jsonl, pins.jsonl, readings.jsonl, frames/, map.pgm + map.yaml

The folder is what goes to the cloud after a mission (splat/run.sh, amd/deep_pass.py, sync.py).
Pin crops are already written into the same folder by the localizer. The map is saved each time a
bubble arrives, so the folder is complete even if the stack is stopped without warning.
"""
import json

import rclpy
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from scout_perception.mission_log import MissionLog


class LoggerNode(Node):
    def __init__(self):
        super().__init__('logger_node')
        self.missions_dir = self.declare_parameter('missions_dir', '/fetch_ws/missions').value
        self.log = MissionLog(self.missions_dir)
        self.map = None
        self.frames = 0

        self.create_subscription(String, '/survey/bubbles', self.on_bubble, 20)
        self.create_subscription(String, '/survey/pins', self.on_pin, 50)
        self.create_subscription(String, '/survey/readings', self.on_reading, 50)
        # a bubble is 12 frames sent 150 ms apart; depth leaves room for two bubbles
        self.create_subscription(CompressedImage, '/survey/bubble_images', self.on_image, 30)
        # slam_toolbox latches /map; transient local gets the current map even if we start late
        latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(OccupancyGrid, '/map', self.on_map, latched)
        self.get_logger().info(f'logger node running, writing to {self.missions_dir}/<mission_id>/')

    def parse(self, msg, topic, key):
        try:
            row = json.loads(msg.data)
            row[key]
            return row
        except (ValueError, KeyError, TypeError):
            self.get_logger().warn(f'bad message on {topic}', throttle_duration_sec=5.0)
            return None

    def on_bubble(self, msg):
        row = self.parse(msg, '/survey/bubbles', 'bubble_id')
        if row is None:
            return
        mission_id, count = self.log.bubble(row)
        saved = ''
        if self.map is not None:
            m = self.map
            self.log.save_map(mission_id, m.data, m.info.width, m.info.height, m.info.resolution,
                              m.info.origin.position.x, m.info.origin.position.y)
            saved = f', map {m.info.width}x{m.info.height} saved'
        self.get_logger().info(f'{row["bubble_id"]}: bubble logged ({count} in {mission_id}, '
                               f'{self.frames} frames so far{saved})')

    def on_pin(self, msg):
        row = self.parse(msg, '/survey/pins', 'pin_id')
        if row is not None:
            mission_id, count = self.log.pin(row)
            self.get_logger().info(f'{row["pin_id"]}: pin logged ({count} in {mission_id})')

    def on_reading(self, msg):
        row = self.parse(msg, '/survey/readings', 'mission_id')
        if row is not None:
            self.log.reading(row)

    def on_image(self, msg):
        if self.log.frame(msg.header.frame_id, msg.data) is None:
            self.get_logger().warn(f'bubble image with frame_id "{msg.header.frame_id}" ignored',
                                   throttle_duration_sec=5.0)
        else:
            self.frames += 1

    def on_map(self, msg):
        self.map = msg


def main():
    rclpy.init()
    try:
        rclpy.spin(LoggerNode())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
