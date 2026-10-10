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
from nav2_msgs.srv import ManageLifecycleNodes
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
        self.teleop_grace = p('teleop_grace_s', 1.0).value
        self.accept_timeout = p('goal_accept_timeout_s', 10.0).value
        self.nav_timeout = p('nav_timeout_s', 120.0).value

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
        self.nav_lifecycle = self.create_client(
            ManageLifecycleNodes, p('nav2_lifecycle_service', '/lifecycle_manager_navigation/manage_nodes').value)
        self.nav_restart_t = -1e9

        self.state = None
        self.map_msg = None
        self.estopped = False
        self.visited = []      # survey points done or skipped this mission
        self.target = None
        self.survey_on = False
        self.home = None
        self.bubble_count = 0
        self.done_ids = set()
        self.cap = None
        self.goal_handle = None
        self.goal_token = 0
        self.command_t = -1e9   # last voice command; sticks are ignored briefly after it
        self.goal_watch = None  # {'t0', 'accepted', 'on_result'} while a Nav2 goal is in flight

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
        # Grace period: a stick message already in flight shouldn't undo "come back".
        recent_command = self._now() - self.command_t < self.teleop_grace
        if moving and self.teleop_takes_over and self.state in ml.AUTONOMOUS_STATES and not recent_command:
            self.get_logger().info('teleop input, switching to MANUAL')
            self._manual()

    def _on_text(self, msg):
        cmd = ml.parse_command(msg.data)
        action = ml.decide(self.state, cmd, self.estopped, self.survey_on)
        self.get_logger().info(f'heard "{msg.data}" -> {cmd} -> {action}')
        if action in ('start', 'resume', 'return', 'capture'):
            self.command_t = self._now()
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
        self.goal_watch = None
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
        self.home = pose
        self.visited = []
        self.survey_on = True
        how = f'{len(self.waypoints)} fixed waypoints' if self.waypoints else 're-planning from /map as it grows'
        self.get_logger().info(f'survey started ({how})')
        self._go_to_point()

    def _next_target(self):
        """Next survey point, or None when the survey is done.

        Auto mode re-plans from the latest /map every time, so a survey started
        on a barely-mapped room keeps expanding as the robot sees more.
        """
        if len(self.visited) >= (len(self.waypoints) if self.waypoints else self.max_points):
            return None
        if self.waypoints:
            return self.waypoints[len(self.visited)]
        pose = self._pose()
        plan = []
        if pose is not None and self.map_msg is not None:
            m = self.map_msg
            plan = plan_survey_points(
                m.data, m.info.width, m.info.height, m.info.resolution,
                m.info.origin.position.x, m.info.origin.position.y,
                (pose[0], pose[1]), self.spacing, self.clearance, 1, visited=self.visited)
        if plan:
            return plan[0]
        if not self.visited and pose is not None:
            self.get_logger().warn('no safe survey point on the map yet; capturing where we stand')
            return (pose[0], pose[1])
        return None

    def _go_to_point(self):
        self.target = self._next_target()
        if self.target is None:
            self._return_home()
            return
        x, y = self.target
        self.get_logger().info(f'survey point {len(self.visited) + 1}: ({x:.2f}, {y:.2f})')
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
            self._nav2_down('is not available')
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
        self.goal_watch = {'t0': self._now(), 'accepted': False, 'on_result': on_result}

        def finish(status):
            if token == self.goal_token:
                self.goal_watch = None
                on_result(status)

        def on_accept(future):
            if token != self.goal_token:
                return
            handle = future.result()
            if not handle.accepted:
                # Nav2 rejects goals when it's inactive (e.g. after a heartbeat failure),
                # not because a point is unreachable; don't burn through the survey.
                self._nav2_down('rejected the goal')
                return
            self.goal_handle = handle
            self.goal_watch.update(t0=self._now(), accepted=True)
            self._set_state(state_on_accept)
            handle.get_result_async().add_done_callback(lambda f: finish(f.result().status))

        self.nav.send_goal_async(goal).add_done_callback(on_accept)

    def _on_point_result(self, status):
        self.goal_handle = None
        if status == GoalStatus.STATUS_SUCCEEDED:
            self._start_capture(return_state=ml.NEXT_POINT)
        else:
            self.get_logger().warn(f'could not reach {self.target}, skipping')
            self.visited.append(self.target)
            self._go_to_point()

    def _on_home_result(self, status):
        self.goal_handle = None
        if status != GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().warn('could not reach home')
        self.survey_on = False
        self.get_logger().info(f'mission complete: {self.bubble_count} bubbles')
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

    def _check_goal(self):
        """Nav2 can die or restart mid-goal and never answer; don't wait forever."""
        w = self.goal_watch
        if w is None:
            return
        waited = self._now() - w['t0']
        limit = self.nav_timeout if w['accepted'] else self.accept_timeout
        if waited <= limit:
            return
        if not w['accepted']:
            self._nav2_down(f'did not answer a goal within {limit:.0f} s')
            return
        self.get_logger().warn(f'Nav2 did not finish the goal within {limit:.0f} s; giving up on it')
        on_result = w['on_result']
        self._cancel_nav()
        on_result(GoalStatus.STATUS_ABORTED)

    def _nav2_down(self, why):
        """AGENTS.md fallback: manual drive + capture. The survey stays open for "resume"."""
        self._cancel_nav()
        self.cap = None
        self._zero()
        self.get_logger().error(
            f'Nav2 {why}; switching to MANUAL (drive + say "capture", or "resume" once Nav2 is back)')
        self._set_state(ml.MANUAL)
        # Nav2's lifecycle manager doesn't bring nodes back after a heartbeat failure
        # unless they restart; ask it to start them up again.
        now = self._now()
        if self.nav_lifecycle.service_is_ready() and now - self.nav_restart_t > 30.0:
            self.nav_restart_t = now
            self.get_logger().info('asking Nav2 lifecycle manager to start up again')
            req = ManageLifecycleNodes.Request()
            req.command = ManageLifecycleNodes.Request.STARTUP
            self.nav_lifecycle.call_async(req).add_done_callback(
                lambda f: self.get_logger().info(
                    f'Nav2 startup {"ok" if f.result() and f.result().success else "failed"}'))

    def _tick(self):
        self._check_goal()
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
                    self.visited.append(self.target)
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
