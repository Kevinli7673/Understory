"""Mission manager: survey state machine on top of slam_toolbox + Nav2.

IDLE -> SURVEYING (Nav2 to a point) -> CAPTURING (spin, /survey/capture every 30 deg,
wait for /survey/capture_done) -> NEXT_POINT -> ... -> RETURNING -> IDLE.
MANUAL and STOPPED are reachable from any state.

Commands arrive as text on /voice/text (Whisper, or a Quest button publishing the
same words): start, stop, return, manual, capture, resume.
"""
import math

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from std_msgs.msg import Bool, String
from tf2_ros import Buffer, TransformException, TransformListener

from understory_nav import mission_logic as ml
from understory_nav.survey_planner import plan_survey_points


def _yaw_from_quat(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


class MissionManager(Node):
    def __init__(self):
        super().__init__('mission_manager')
        p = self.declare_parameter
        self.mission_id = p('mission_id', 'm1').value
        self.frames_per_bubble = p('frames_per_bubble', 12).value
        self.waypoints = ml.parse_waypoints(p('waypoints', '').value)
        self.spacing = p('survey_spacing', 1.0).value
        self.clearance = p('survey_clearance', 0.35).value
        self.max_points = p('max_points', 10).value
        self.map_frame = p('map_frame', 'map').value
        self.base_frame = p('base_frame', 'base_link').value
        self.spin_kp = p('spin_kp', 1.5).value
        self.spin_min = p('spin_min_speed', 0.25).value
        self.spin_max = p('spin_max_speed', 0.6).value
        self.yaw_tol = p('yaw_tolerance', 0.05).value
        self.step_timeout = p('step_timeout_s', 8.0).value
        self.settle_s = p('settle_s', 0.4).value
        self.dwell_s = p('dwell_s', 0.6).value
        self.done_timeout = p('capture_done_timeout_s', 15.0).value
        self.teleop_deadband = p('teleop_deadband', 0.05).value
        self.teleop_takes_over = p('teleop_takes_over', True).value

        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE)
        self.state_pub = self.create_publisher(String, '/mission/state', latched)
        self.capture_pub = self.create_publisher(String, '/survey/capture', 10)
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel_auto', 10)

        self.create_subscription(OccupancyGrid, '/map', self._on_map, latched)
        self.create_subscription(String, '/voice/text', self._on_text, 10)
        self.create_subscription(String, '/survey/capture_done', self._on_capture_done, 10)
        self.create_subscription(Bool, '/estop', self._on_estop, 10)
        self.create_subscription(Twist, '/cmd_vel_teleop', self._on_teleop, 10)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.nav = ActionClient(self, NavigateToPose, 'navigate_to_pose')

        self.state = None
        self.map_msg = None
        self.estopped = False
        self.points = []
        self.point_idx = 0
        self.home = None
        self.bubble_count = 0
        self.done_ids = set()
        self.cap = None
        self.goal_handle = None
        self.goal_token = 0

        self._set_state(ml.IDLE)
        self.create_timer(0.05, self._tick)
        self.create_timer(1.0, self._publish_state)
        self.get_logger().info(f'mission {self.mission_id} ready; say "start survey"')

    # ---------- inputs ----------
    def _on_map(self, msg):
        self.map_msg = msg

    def _on_capture_done(self, msg):
        self.done_ids.add(msg.data.strip())

    def _on_estop(self, msg):
        if msg.data and not self.estopped:
            self.get_logger().warn('E-STOP')
            self._stop()
        self.estopped = msg.data

    def _on_teleop(self, msg):
        moving = (abs(msg.linear.x) + abs(msg.linear.y) + abs(msg.angular.z)) > self.teleop_deadband
        if moving and self.teleop_takes_over and self.state in ml.AUTONOMOUS_STATES:
            self.get_logger().info('teleop input, switching to MANUAL')
            self._manual()

    def _on_text(self, msg):
        cmd = ml.parse_command(msg.data)
        survey_active = self.point_idx < len(self.points)
        action = ml.decide(self.state, cmd, self.estopped, survey_active)
        self.get_logger().info(f'heard "{msg.data}" -> {cmd} -> {action}')
        if action == 'stop':
            self._stop()
        elif action == 'manual':
            self._manual()
        elif action == 'start':
            self._start_survey()
        elif action == 'resume':
            self._go_to_point()
        elif action == 'return':
            self._return_home()
        elif action == 'capture':
            self._start_capture(return_state=self.state if self.state == ml.MANUAL else ml.IDLE)

    # ---------- state helpers ----------
    def _set_state(self, s):
        if s != self.state:
            self.get_logger().info(f'state {self.state} -> {s}')
            self.state = s
            self._publish_state()

    def _publish_state(self):
        self.state_pub.publish(String(data=self.state))

    def _pose(self):
        try:
            t = self.tf_buffer.lookup_transform(self.map_frame, self.base_frame, Time())
        except TransformException:
            return None
        tr = t.transform
        return tr.translation.x, tr.translation.y, _yaw_from_quat(tr.rotation)

    def _zero(self):
        self.cmd_pub.publish(Twist())

    def _cancel_nav(self):
        self.goal_token += 1
        if self.goal_handle is not None:
            self.goal_handle.cancel_goal_async()
            self.goal_handle = None

    def _stop(self):
        self._cancel_nav()
        self.cap = None
        self._zero()
        self._set_state(ml.STOPPED)

    def _manual(self):
        self._cancel_nav()
        self.cap = None
        self._zero()
        self._set_state(ml.MANUAL)

    # ---------- survey ----------
    def _start_survey(self):
        pose = self._pose()
        if pose is None:
            self.get_logger().error('no map->base_link transform yet; is slam_toolbox running?')
            return
        self.home = (pose[0], pose[1], pose[2])
        if self.waypoints:
            self.points = list(self.waypoints)
        elif self.map_msg is not None:
            m = self.map_msg
            self.points = plan_survey_points(
                m.data, m.info.width, m.info.height, m.info.resolution,
                m.info.origin.position.x, m.info.origin.position.y,
                (pose[0], pose[1]), self.spacing, self.clearance, self.max_points)
        else:
            self.points = []
        if not self.points:
            self.get_logger().warn('no survey points; capturing where we stand')
            self.points = [(pose[0], pose[1])]
        self.get_logger().info(f'survey points: {[(round(x, 2), round(y, 2)) for x, y in self.points]}')
        self.point_idx = 0
        self._go_to_point()

    def _go_to_point(self):
        if self.point_idx >= len(self.points):
            self._return_home()
            return
        x, y = self.points[self.point_idx]
        self._set_state(ml.NEXT_POINT)
        self._send_goal(x, y, None, ml.SURVEYING, self._on_point_result)

    def _return_home(self):
        if self.home is None:
            pose = self._pose()
            if pose is None:
                self._set_state(ml.IDLE)
                return
            self.home = pose
        self.cap = None
        self._send_goal(self.home[0], self.home[1], self.home[2], ml.RETURNING, self._on_home_result)

    def _send_goal(self, x, y, yaw, state_on_accept, on_result):
        self._cancel_nav()
        if not self.nav.server_is_ready():
            # Fallback from AGENTS.md: manual drive + capture button.
            self.get_logger().error('Nav2 not available; switching to MANUAL (drive + say "capture")')
            self._set_state(ml.MANUAL)
            return
        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = self.map_frame
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(x)
        goal.pose.pose.position.y = float(y)
        if yaw is None:
            goal.pose.pose.orientation.w = 1.0
        else:
            goal.pose.pose.orientation.z = math.sin(yaw / 2.0)
            goal.pose.pose.orientation.w = math.cos(yaw / 2.0)
        token = self.goal_token

        def on_accept(future):
            if token != self.goal_token:
                return
            handle = future.result()
            if not handle.accepted:
                self.get_logger().warn(f'goal ({x:.2f}, {y:.2f}) rejected')
                on_result(GoalStatus.STATUS_ABORTED)
                return
            self.goal_handle = handle
            self._set_state(state_on_accept)
            handle.get_result_async().add_done_callback(
                lambda f: token == self.goal_token and on_result(f.result().status))

        self.nav.send_goal_async(goal).add_done_callback(on_accept)

    def _on_point_result(self, status):
        self.goal_handle = None
        if status == GoalStatus.STATUS_SUCCEEDED:
            self._start_capture(return_state=ml.NEXT_POINT)
        else:
            self.get_logger().warn(f'could not reach point {self.point_idx}, skipping')
            self.point_idx += 1
            self._go_to_point()

    def _on_home_result(self, status):
        self.goal_handle = None
        if status != GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().warn('could not reach home')
        self.points, self.point_idx = [], 0
        self.get_logger().info('mission complete')
        self._set_state(ml.IDLE)

    # ---------- 360 capture ----------
    def _start_capture(self, return_state):
        pose = self._pose()
        start_yaw = pose[2] if pose else 0.0
        self.bubble_count += 1
        now = self._now()
        self.cap = {
            'id': ml.bubble_id(self.mission_id, self.bubble_count),
            'targets': ml.spin_targets(start_yaw, self.frames_per_bubble),
            'k': 0,
            'phase': 'rotate',
            'phase_t0': now,
            'return_state': return_state,
        }
        self.get_logger().info(f'capturing bubble {self.cap["id"]}')
        self._set_state(ml.CAPTURING)

    def _now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def _tick(self):
        if self.state != ml.CAPTURING or self.cap is None:
            return
        c, now = self.cap, self._now()
        elapsed = now - c['phase_t0']

        def phase(name):
            c['phase'], c['phase_t0'] = name, now

        if c['phase'] == 'rotate':
            pose = self._pose()
            reached = False
            if pose is not None:
                wz, reached = ml.spin_command(c['targets'][c['k']], pose[2], self.spin_kp,
                                              self.spin_min, self.spin_max, self.yaw_tol)
                twist = Twist()
                twist.angular.z = wz
                self.cmd_pub.publish(twist)
            if reached or elapsed > self.step_timeout:
                self._zero()
                phase('settle')
        elif c['phase'] == 'settle':
            self._zero()
            if elapsed > self.settle_s:
                self.capture_pub.publish(String(data=c['id']))
                phase('dwell')
        elif c['phase'] == 'dwell':
            self._zero()
            if elapsed > self.dwell_s:
                c['k'] += 1
                phase('rotate' if c['k'] < len(c['targets']) else 'wait_done')
        elif c['phase'] == 'wait_done':
            if c['id'] in self.done_ids or elapsed > self.done_timeout:
                if c['id'] not in self.done_ids:
                    self.get_logger().warn(f'no capture_done for {c["id"]}, moving on')
                self.cap = None
                if c['return_state'] == ml.NEXT_POINT:
                    self.point_idx += 1
                    self._go_to_point()
                else:
                    self._set_state(c['return_state'])


def main():
    rclpy.init()
    node = MissionManager()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.cmd_pub.publish(Twist())
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
