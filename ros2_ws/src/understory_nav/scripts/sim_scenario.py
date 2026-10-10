"""Interrupt-path check against a running stack (sim.launch.py or the real robot, wheels up!).

  python scripts/sim_scenario.py

Drives /voice/text, /cmd_vel_teleop and /estop; checks /mission/state and /cmd_vel.
"""
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from std_msgs.msg import String, Bool
from geometry_msgs.msg import Twist

rclpy.init()
n = Node('scenario')
st = {'state': None, 'cmd_nonzero': 0}
n.create_subscription(String, '/mission/state', lambda m: st.update(state=m.data),
                      QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
def on_cmd(m):
    if abs(m.linear.x) + abs(m.linear.y) + abs(m.angular.z) > 1e-6:
        st['cmd_nonzero'] += 1
n.create_subscription(Twist, '/cmd_vel', on_cmd, 10)
voice = n.create_publisher(String, '/voice/text', 10)
estop = n.create_publisher(Bool, '/estop', 10)
tele = n.create_publisher(Twist, '/cmd_vel_teleop', 10)
results = []

def spin(sec, teleop=None):
    t0 = time.time()
    while time.time() - t0 < sec:
        if teleop is not None:
            tele.publish(teleop)
        rclpy.spin_once(n, timeout_sec=0.05)

def say(text):
    voice.publish(String(data=text)); spin(0.5)

def wait_state(want, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if st['state'] in want:
            return True
        spin(0.2)
    return False

def check(name, ok):
    results.append((name, ok)); print(('PASS ' if ok else 'FAIL ') + name + f'  (state={st["state"]})', flush=True)

spin(2)
check('starts IDLE', st['state'] == 'IDLE')
say('start survey')
check('start -> autonomy', wait_state({'NEXT_POINT', 'SURVEYING', 'CAPTURING'}, 10))
spin(3)
fwd = Twist(); fwd.linear.x = 0.1
spin(1.0, teleop=fwd)
check('teleop sticks -> MANUAL', wait_state({'MANUAL'}, 3))
spin(1)
say('capture here')
check('"capture" in MANUAL -> CAPTURING', wait_state({'CAPTURING'}, 3))
check('manual capture returns to MANUAL', wait_state({'MANUAL'}, 240))
say('resume')
check('"resume" -> survey continues', wait_state({'NEXT_POINT', 'SURVEYING', 'CAPTURING'}, 5))
spin(2)
estop.publish(Bool(data=True)); spin(0.5)
check('e-stop -> STOPPED', wait_state({'STOPPED'}, 3))
spin(1)
st['cmd_nonzero'] = 0
spin(2.0, teleop=fwd)
check('e-stop blocks teleop at twist_mux (/cmd_vel silent)', st['cmd_nonzero'] == 0)
say('resume')
spin(1)
check('"resume" ignored while e-stop held', st['state'] == 'STOPPED')
estop.publish(Bool(data=False)); spin(1)
check('releasing e-stop stays STOPPED', st['state'] == 'STOPPED')
say('keep going')
check('"keep going" after release -> survey continues', wait_state({'NEXT_POINT', 'SURVEYING', 'CAPTURING'}, 5))
spin(2)
st['cmd_nonzero'] = 0
spin(1.5, teleop=fwd)
check('teleop reaches /cmd_vel after release', st['cmd_nonzero'] > 0)
wait_state({'MANUAL'}, 3)
say('okay come back')
check('"come back" -> RETURNING', wait_state({'RETURNING'}, 10))
check('returns home -> IDLE', wait_state({'IDLE'}, 120))
say('stop')
check('"stop" from IDLE -> STOPPED', wait_state({'STOPPED'}, 3))
print(f"{sum(ok for _, ok in results)}/{len(results)} passed")
raise SystemExit(0 if all(ok for _, ok in results) else 1)
