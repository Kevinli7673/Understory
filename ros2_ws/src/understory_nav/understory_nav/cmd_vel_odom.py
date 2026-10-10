"""Dead-reckoning odom from /cmd_vel for a mecanum base without wheel encoders.

Publishes odom->base_link TF and /odom. Crude on purpose: slam_toolbox's scan
matching corrects the drift; this only gives it a motion prior. Mirrors the
ESP32's 300 ms watchdog so odom stops when the wheels stop.
"""
import math

import rclpy
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from tf2_ros import TransformBroadcaster


class CmdVelOdom(Node):
    def __init__(self):
        super().__init__('cmd_vel_odom')
        self.odom_frame = self.declare_parameter('odom_frame', 'odom').value
        self.base_frame = self.declare_parameter('base_frame', 'base_link').value
        # Measured speed / commanded speed; calibrate by driving 1 m and checking.
        self.lin_scale = self.declare_parameter('linear_scale', 1.0).value
        self.ang_scale = self.declare_parameter('angular_scale', 1.0).value
        self.watchdog = self.declare_parameter('watchdog_s', 0.3).value

        self.x = self.y = self.yaw = 0.0
        self.cmd = Twist()
        self.cmd_t = None
        self.last_t = self.get_clock().now()

        self.tf = TransformBroadcaster(self)
        self.odom_pub = self.create_publisher(Odometry, '/odom', 10)
        self.create_subscription(Twist, '/cmd_vel', self._on_cmd, 10)
        self.create_timer(0.02, self._tick)

    def _on_cmd(self, msg):
        self.cmd = msg
        self.cmd_t = self.get_clock().now()

    def _tick(self):
        now = self.get_clock().now()
        dt = (now - self.last_t).nanoseconds * 1e-9
        self.last_t = now
        fresh = self.cmd_t is not None and (now - self.cmd_t).nanoseconds * 1e-9 < self.watchdog
        vx = self.cmd.linear.x * self.lin_scale if fresh else 0.0
        vy = self.cmd.linear.y * self.lin_scale if fresh else 0.0
        wz = self.cmd.angular.z * self.ang_scale if fresh else 0.0

        c, s = math.cos(self.yaw), math.sin(self.yaw)
        self.x += (vx * c - vy * s) * dt
        self.y += (vx * s + vy * c) * dt
        self.yaw = math.atan2(math.sin(self.yaw + wz * dt), math.cos(self.yaw + wz * dt))
        publish_odom(self, now, self.x, self.y, self.yaw, vx, vy, wz)


def publish_odom(node, stamp, x, y, yaw, vx, vy, wz):
    """Shared by cmd_vel_odom and fake_world."""
    qz, qw = math.sin(yaw / 2.0), math.cos(yaw / 2.0)
    t = TransformStamped()
    t.header.stamp = stamp.to_msg()
    t.header.frame_id = node.odom_frame
    t.child_frame_id = node.base_frame
    t.transform.translation.x = x
    t.transform.translation.y = y
    t.transform.rotation.z = qz
    t.transform.rotation.w = qw
    node.tf.sendTransform(t)

    o = Odometry()
    o.header = t.header
    o.child_frame_id = node.base_frame
    o.pose.pose.position.x = x
    o.pose.pose.position.y = y
    o.pose.pose.orientation.z = qz
    o.pose.pose.orientation.w = qw
    o.twist.twist.linear.x = vx
    o.twist.twist.linear.y = vy
    o.twist.twist.angular.z = wz
    node.odom_pub.publish(o)


def main():
    rclpy.init()
    node = CmdVelOdom()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
