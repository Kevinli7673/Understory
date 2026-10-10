"""Stand-in for the robot + LiDAR so nav and mission can be tested with no hardware.

Integrates /cmd_vel into a perfect odom->base_link TF and ray-casts a fake /scan
against a small room with a few boxes. Use with sim.launch.py.
"""
import math

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from tf2_ros import TransformBroadcaster

from understory_nav.cmd_vel_odom import publish_odom


def _box(x0, y0, x1, y1):
    return [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]


# 8 m x 6 m room, robot starts at (1, 1). Boxes play the part of plant beds.
WORLD = (_box(-1.0, -1.0, 7.0, 5.0) + _box(2.0, 2.0, 3.0, 2.6)
         + _box(4.5, 0.5, 5.2, 1.4) + _box(4.0, 3.5, 6.0, 4.0))


def raycast(ox, oy, angle, max_range, segments=WORLD):
    dx, dy = math.cos(angle), math.sin(angle)
    best = max_range
    for (ax, ay), (bx, by) in segments:
        ex, ey = bx - ax, by - ay
        den = dx * ey - dy * ex
        if abs(den) < 1e-9:
            continue
        t = ((ax - ox) * ey - (ay - oy) * ex) / den
        u = ((ax - ox) * dy - (ay - oy) * dx) / den
        if 0.0 <= u <= 1.0 and 0.0 < t < best:
            best = t
    return best


class FakeWorld(Node):
    def __init__(self):
        super().__init__('fake_world')
        self.odom_frame = 'odom'
        self.base_frame = 'base_link'
        self.laser_frame = self.declare_parameter('laser_frame', 'laser').value
        self.beams = self.declare_parameter('beams', 360).value
        self.max_range = self.declare_parameter('max_range', 8.0).value
        # World pose of the odom origin, so the map isn't centered on a wall.
        self.x0, self.y0 = 1.0, 1.0
        self.x = self.y = self.yaw = 0.0
        self.cmd = Twist()
        self.cmd_t = None
        self.last_t = self.get_clock().now()

        self.tf = TransformBroadcaster(self)
        self.odom_pub = self.create_publisher(Odometry, '/odom', 10)
        self.scan_pub = self.create_publisher(LaserScan, '/scan', 10)
        self.create_subscription(Twist, '/cmd_vel', self._on_cmd, 10)
        self.create_timer(0.02, self._step)
        self.create_timer(0.1, self._scan)

    def _on_cmd(self, msg):
        self.cmd, self.cmd_t = msg, self.get_clock().now()

    def _step(self):
        now = self.get_clock().now()
        dt = (now - self.last_t).nanoseconds * 1e-9
        self.last_t = now
        fresh = self.cmd_t is not None and (now - self.cmd_t).nanoseconds < 3e8  # ESP32 watchdog
        vx, vy, wz = (self.cmd.linear.x, self.cmd.linear.y, self.cmd.angular.z) if fresh else (0.0, 0.0, 0.0)
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        self.x += (vx * c - vy * s) * dt
        self.y += (vx * s + vy * c) * dt
        self.yaw = math.atan2(math.sin(self.yaw + wz * dt), math.cos(self.yaw + wz * dt))
        publish_odom(self, now, self.x, self.y, self.yaw, vx, vy, wz)

    def _scan(self):
        msg = LaserScan()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.laser_frame
        msg.angle_min = -math.pi
        msg.angle_increment = 2.0 * math.pi / self.beams
        msg.angle_max = msg.angle_min + msg.angle_increment * (self.beams - 1)
        msg.scan_time = 0.1
        msg.range_min = 0.1
        msg.range_max = self.max_range
        wx, wy = self.x0 + self.x, self.y0 + self.y
        msg.ranges = [raycast(wx, wy, self.yaw + msg.angle_min + i * msg.angle_increment, self.max_range)
                      for i in range(self.beams)]
        self.scan_pub.publish(msg)


def main():
    rclpy.init()
    node = FakeWorld()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
