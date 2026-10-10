"""localizer_node: turns /species sightings into map pins, and tags sensor readings with a position.

    ros2 run scout_perception localizer_node

Pins     /species + /scan + TF  ->  /survey/pins   (and the crop saved as <pin_id>.jpg)
    direction = robot yaw + camera yaw + angle of the box centre in the image
    distance  = LiDAR range in that direction
    The same plant seen in many frames is one pin (same label within `merge_radius` metres).
    A pin is published after `min_sightings` sightings, and again if its confidence improves.

Readings /sensors + TF  ->  /survey/readings   (adds mission_id, x, y; drops null values)

/survey/pins: {"pin_id": "m1-p07", "mission_id": "m1", "bubble_id": "m1-b03", "label": "Brazilian pepper",
               "invasive": true, "confidence": 0.81, "yaw": 2.10, "x": 2.05, "y": 0.40, "crop": "m1-p07.jpg"}
`yaw` is the direction of the plant from its bubble's centre (map frame), which is how the Quest
finds it in the bubble's frames. The mission and bubble come from /survey/capture and /survey/bubbles.
"""
import json
import math
import os
import time
from collections import OrderedDict

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CompressedImage, LaserScan
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener

from scout_perception.geometry import PinTracker, bearing_from, locate, yaw_from_quaternion


class LocalizerNode(Node):
    def __init__(self):
        super().__init__('localizer_node')
        p = self.declare_parameter
        # Horizontal field of view in radians. Same default as panorama_node: computed from the
        # Brio 101's spec, not measured.
        self.hfov = p('hfov', 0.83).value
        self.merge_radius = p('merge_radius', 0.5).value
        self.min_sightings = p('min_sightings', 3).value
        self.mission_id = p('default_mission', 'm1').value
        self.missions_dir = p('missions_dir', '/fetch_ws/missions').value   # crops go in <dir>/<mission>/crops/
        self.publish_embedding = p('publish_embedding', False).value        # not in the AGENTS.md pin yet
        self.max_scan_age = p('max_scan_age', 1.0).value

        self.tracker = PinTracker(self.merge_radius, self.min_sightings)
        self.scan = None                   # (ranges, angle_min, angle_increment, wall time received)
        self.frames = OrderedDict()        # stamp in nanoseconds -> JPEG bytes, newest last
        self.bubbles = {}                  # bubble_id -> (x, y)
        self.capturing = (None, 0.0)       # (bubble_id being captured, wall time of the last capture message)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.pub_pins = self.create_publisher(String, '/survey/pins', 10)
        self.pub_readings = self.create_publisher(String, '/survey/readings', 10)
        best_effort = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(LaserScan, '/scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(CompressedImage, '/camera/image/compressed', self.on_image, best_effort)
        self.create_subscription(String, '/species', self.on_species, 20)
        self.create_subscription(String, '/sensors', self.on_sensors, 10)
        self.create_subscription(String, '/survey/bubbles', self.on_bubble, 10)
        self.create_subscription(String, '/survey/capture', self.on_capture, 20)
        self.get_logger().info(f'localizer running, mission={self.mission_id}, hfov={self.hfov}, '
                               f'crops in {self.missions_dir}/<mission>/crops')

    # ---- inputs ----
    def on_scan(self, msg):
        self.scan = (list(msg.ranges), msg.angle_min, msg.angle_increment, time.time())

    def on_image(self, msg):
        self.frames[msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec] = bytes(msg.data)
        while len(self.frames) > 90:                    # about 6 s at 15 Hz
            self.frames.popitem(last=False)

    def set_mission(self, mission_id):
        if mission_id and mission_id != self.mission_id:
            self.get_logger().info(f'new mission {mission_id}: pin numbering restarts')
            self.mission_id = mission_id
            self.tracker = PinTracker(self.merge_radius, self.min_sightings)
            self.bubbles = {}

    def on_capture(self, msg):
        bubble_id = msg.data.strip().partition('/')[0]          # "m1-b03" or "m1-b03/done"
        if '-' in bubble_id:
            self.set_mission(bubble_id.rsplit('-', 1)[0])
            self.capturing = (bubble_id, time.time())

    def on_bubble(self, msg):
        try:
            b = json.loads(msg.data)
            self.set_mission(b.get('mission_id'))
            self.bubbles[b['bubble_id']] = (float(b['x']), float(b['y']))
        except (ValueError, KeyError, TypeError):
            self.get_logger().warn('bad /survey/bubbles message', throttle_duration_sec=5.0)

    # ---- TF ----
    def pose_2d(self, parent, child):
        """(x, y, yaw) of `child` in `parent`, or None."""
        try:
            tf = self.tf_buffer.lookup_transform(parent, child, Time()).transform
        except TransformException:
            return None
        q = tf.rotation
        return tf.translation.x, tf.translation.y, yaw_from_quaternion(q.x, q.y, q.z, q.w)

    # ---- pins ----
    def bubble_for(self, robot_xy):
        """(bubble_id, centre) the pin belongs to: the bubble being captured, else the nearest one."""
        bubble_id, last = self.capturing
        if bubble_id and time.time() - last < 5.0:
            return bubble_id, self.bubbles.get(bubble_id, robot_xy)     # mid-spin the robot is the centre
        if self.bubbles:
            bubble_id = min(self.bubbles, key=lambda b: math.dist(self.bubbles[b], robot_xy))
            return bubble_id, self.bubbles[bubble_id]
        return '', robot_xy

    def on_species(self, msg):
        try:
            s = json.loads(msg.data)
            label, x1, y1, x2, y2 = s['label'], *s['xyxy']
        except (ValueError, KeyError, TypeError):
            self.get_logger().warn('bad /species message', throttle_duration_sec=5.0)
            return
        robot = self.pose_2d('map', 'base_link')
        if robot is None:
            self.get_logger().warn('no TF map -> base_link (is slam_toolbox running?), pin skipped',
                                   throttle_duration_sec=10.0)
            return
        if self.scan is None or time.time() - self.scan[3] > self.max_scan_age:
            self.get_logger().warn('no recent /scan, pin skipped', throttle_duration_sec=10.0)
            return
        # sensor offsets come from TF, so they follow whatever the hardware owner measures
        camera = self.pose_2d('base_link', s.get('frame_id') or 'camera') or (0.0, 0.0, 0.0)
        laser = self.pose_2d('base_link', 'laser') or (0.0, 0.0, 0.0)
        jpeg, width = self.frame_at(s.get('t'))
        spot = locate(robot, camera, laser, (x1 + x2) / 2, width, self.hfov, self.scan[:3])
        if spot is None:
            self.get_logger().warn(f'{label}: no LiDAR return in that direction, pin skipped',
                                   throttle_duration_sec=5.0)
            return

        track, publish = self.tracker.add(label, spot[0], spot[1], float(s.get('confidence', 0.0)))
        if not publish:
            return
        pin_id = f'{self.mission_id}-p{track["number"]:02d}'
        bubble_id, centre = self.bubble_for(robot[:2])
        pin = {'pin_id': pin_id, 'mission_id': self.mission_id, 'bubble_id': bubble_id,
               'label': label, 'invasive': bool(s.get('invasive', False)),
               'confidence': round(track['confidence'], 2),
               'yaw': round(bearing_from(centre, (track['x'], track['y'])), 2),
               'x': round(track['x'], 2), 'y': round(track['y'], 2), 'crop': f'{pin_id}.jpg'}
        if self.publish_embedding and s.get('embedding'):
            pin['embedding'] = s['embedding']
        self.save_crop(pin_id, jpeg, (x1, y1, x2, y2))
        self.pub_pins.publish(String(data=json.dumps(pin)))
        self.get_logger().info(f'pin {pin_id}: {label} at ({pin["x"]}, {pin["y"]}) '
                               f'conf={pin["confidence"]} bubble={bubble_id or "none"} sightings={track["n"]}')

    def frame_at(self, t):
        """(JPEG bytes, image width) of the camera frame stamped `t`, falling back to the newest frame."""
        if not self.frames:
            return None, 640
        stamp = round(t * 1e9) if t else 0
        key = min(self.frames, key=lambda k: abs(k - stamp))
        if abs(key - stamp) > 2_000_000:
            key = next(reversed(self.frames))
        jpeg = self.frames[key]
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_8)
        return jpeg, image.shape[1] * 8 if image is not None else 640

    def save_crop(self, pin_id, jpeg, box):
        if jpeg is None:
            return
        bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            return
        x1, y1, x2, y2 = (max(0, int(v)) for v in box)
        folder = os.path.join(self.missions_dir, self.mission_id, 'crops')
        try:
            os.makedirs(folder, exist_ok=True)
            cv2.imwrite(os.path.join(folder, f'{pin_id}.jpg'), bgr[y1:y2, x1:x2])
        except (OSError, cv2.error) as e:
            self.get_logger().warn(f'could not save crop for {pin_id}: {e}')

    # ---- readings ----
    def on_sensors(self, msg):
        try:
            reading = {k: v for k, v in json.loads(msg.data).items() if v is not None}
        except (ValueError, AttributeError):
            self.get_logger().warn('bad /sensors message', throttle_duration_sec=5.0)
            return
        robot = self.pose_2d('map', 'base_link')
        if robot is None:
            self.get_logger().warn('no TF map -> base_link, readings sent with x=y=0', throttle_duration_sec=10.0)
            robot = (0.0, 0.0, 0.0)
        reading.setdefault('t', round(time.time(), 2))
        reading.update(mission_id=self.mission_id, x=round(robot[0], 2), y=round(robot[1], 2))
        self.pub_readings.publish(String(data=json.dumps(reading)))


def main():
    rclpy.init()
    try:
        rclpy.spin(LocalizerNode())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
