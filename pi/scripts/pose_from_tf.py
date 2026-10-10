#!/usr/bin/env python3
"""Publish the robot pose from TF (map -> base_link) on /pose, for the Quest's tabletop robot marker.

slam_toolbox in this setup doesn't publish /pose, but the TF is there (scout_up.sh: "TF map -> base_link: ok").
The Quest (RosSurveySource) listens to /pose as geometry_msgs/PoseWithCovarianceStamped.

Run inside the container (~/scout_shell.sh on the host first), after ~/scout_up.sh --nav:
    nohup python3 /fetch_ws/src/Understory/pi/scripts/pose_from_tf.py > /fetch_ws/logs/pose_from_tf.log 2>&1 &
    python3 /fetch_ws/src/Understory/pi/scripts/pose_from_tf.py --rate 5      # foreground, 5 Hz
"""
import argparse

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.node import Node
from rclpy.time import Time
from tf2_ros import Buffer, TransformException, TransformListener


class PoseFromTf(Node):
    def __init__(self, rate, parent, child):
        super().__init__('pose_from_tf')
        self.parent, self.child = parent, child
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.pub = self.create_publisher(PoseWithCovarianceStamped, '/pose', 10)
        self.create_timer(1.0 / rate, self.tick)
        self.ok = None
        self.get_logger().info(f'{parent} -> {child} on /pose at {rate} Hz')

    def tick(self):
        try:
            t = self.tf_buffer.lookup_transform(self.parent, self.child, Time())
        except TransformException as e:
            if self.ok is not False:
                self.get_logger().warn(f'no TF {self.parent} -> {self.child} yet ({e}); is slam running?')
            self.ok = False
            return
        if self.ok is not True:
            self.get_logger().info('TF found, publishing /pose')
        self.ok = True
        msg = PoseWithCovarianceStamped()
        msg.header.stamp = t.header.stamp
        msg.header.frame_id = self.parent
        msg.pose.pose.position.x = t.transform.translation.x
        msg.pose.pose.position.y = t.transform.translation.y
        msg.pose.pose.position.z = t.transform.translation.z
        msg.pose.pose.orientation = t.transform.rotation
        self.pub.publish(msg)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--rate', type=float, default=10.0)
    ap.add_argument('--parent', default='map')
    ap.add_argument('--child', default='base_link')
    args = ap.parse_args()
    rclpy.init()
    node = PoseFromTf(args.rate, args.parent, args.child)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
