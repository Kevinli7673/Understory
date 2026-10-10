"""panorama_node: builds a "Street View bubble" from frames captured during a spin.

    ros2 run scout_perception panorama_node

Protocol on /survey/capture (std_msgs/String):
    "m1-b03"        grab the latest camera frame for bubble m1-b03
    "m1-b03/done"   finish the bubble now (otherwise it finishes after `frames_per_bubble` grabs)
A capture for a different bubble_id also finishes the previous bubble.

When a bubble finishes, the node tries to stitch it and publishes:
    /survey/bubble_images   one image with frame_id "<bubble_id>/pano" if stitching worked,
                            otherwise every frame with frame_id "<bubble_id>/<index>"
    /survey/bubbles         the bubble JSON (stitched true/false, per-frame yaw, x, y, hfov)
    /survey/capture_done    the bubble_id, once per bubble
"""
import json
import math
import threading
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener


class PanoramaNode(Node):
    def __init__(self):
        super().__init__('panorama_node')
        self.frames_per_bubble = self.declare_parameter('frames_per_bubble', 12).value
        # Horizontal field of view in radians, sent to the Quest to size each frame.
        # 0.83 (48 deg) is computed from the Brio 101's 58 deg diagonal spec at 4:3, not measured.
        self.hfov = self.declare_parameter('hfov', 0.83).value

        self.latest = None        # most recent camera message
        self.bubble_id = None     # bubble being captured
        self.frames = []          # [(jpeg_bytes, yaw)]
        self.pose = (0.0, 0.0)    # robot x, y at the first capture of the bubble

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.pub_bubbles = self.create_publisher(String, '/survey/bubbles', 10)
        self.pub_images = self.create_publisher(CompressedImage, '/survey/bubble_images', 20)
        self.pub_done = self.create_publisher(String, '/survey/capture_done', 10)
        self.create_subscription(CompressedImage, '/camera/image/compressed', self.on_image,
                                 qos_profile_sensor_data)
        self.create_subscription(String, '/survey/capture', self.on_capture, 20)
        self.get_logger().info(f'panorama node ready ({self.frames_per_bubble} frames per bubble)')

    def on_image(self, msg):
        self.latest = msg

    def robot_pose(self):
        """(x, y, yaw) of base_link in the map frame, or zeros if SLAM isn't running yet."""
        try:
            tf = self.tf_buffer.lookup_transform('map', 'base_link', Time()).transform
        except TransformException:
            self.get_logger().warn('no TF map -> base_link (is slam_toolbox running?), using x=y=yaw=0',
                                   throttle_duration_sec=10.0)
            return 0.0, 0.0, 0.0
        q = tf.rotation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        return tf.translation.x, tf.translation.y, yaw

    def on_capture(self, msg):
        bubble_id, _, suffix = msg.data.strip().partition('/')
        if self.bubble_id is not None and bubble_id != self.bubble_id:
            self.finish()                       # a new bubble started; close the old one
        if suffix == 'done':
            if bubble_id == self.bubble_id:
                self.finish()
            return
        if self.latest is None:
            self.get_logger().warn('capture requested but no camera frame received yet')
            return

        x, y, yaw = self.robot_pose()
        if not self.frames:
            self.bubble_id, self.pose = bubble_id, (x, y)
        self.frames.append((bytes(self.latest.data), yaw))
        self.get_logger().info(f'{bubble_id}: frame {len(self.frames)}/{self.frames_per_bubble} yaw={yaw:.2f}')
        if len(self.frames) >= self.frames_per_bubble:
            self.finish()

    def finish(self):
        """Hand the collected frames to a worker thread (stitching takes seconds) and reset."""
        if self.frames:
            threading.Thread(target=self.build, args=(self.bubble_id, self.frames, self.pose),
                             daemon=True).start()
        self.bubble_id, self.frames = None, []

    def build(self, bubble_id, frames, pose):
        start = time.time()
        pano = None
        if len(frames) >= 2:
            images = [cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR) for jpeg, _ in frames]
            try:
                status, result = cv2.Stitcher_create(cv2.Stitcher_PANORAMA).stitch(images)
                if status == cv2.Stitcher_OK:
                    pano = cv2.imencode('.jpg', result, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
                else:
                    self.get_logger().warn(f'{bubble_id}: stitching failed (status {status}), sending frames')
            except cv2.error as e:
                self.get_logger().warn(f'{bubble_id}: stitcher error ({e}), sending frames')

        if pano is not None:
            self.publish_image(f'{bubble_id}/pano', pano)
        else:
            for i, (jpeg, _) in enumerate(frames):
                self.publish_image(f'{bubble_id}/{i}', jpeg)
                time.sleep(0.05)               # don't flood slow subscribers (Quest over Wi-Fi)

        self.pub_bubbles.publish(String(data=json.dumps({
            'bubble_id': bubble_id,
            'mission_id': bubble_id.rsplit('-', 1)[0],       # "m1-b03" -> "m1"
            't': round(start, 2), 'x': round(pose[0], 2), 'y': round(pose[1], 2),
            'stitched': pano is not None,
            'frames': [{'index': i, 'yaw': round(yaw, 2)} for i, (_, yaw) in enumerate(frames)],
            'hfov': self.hfov})))
        self.pub_done.publish(String(data=bubble_id))
        self.get_logger().info(f'{bubble_id}: published ({len(frames)} frames, stitched={pano is not None}, '
                               f'{time.time() - start:.1f} s)')

    def publish_image(self, frame_id, jpeg):
        msg = CompressedImage(format='jpeg', data=jpeg)
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = frame_id
        self.pub_images.publish(msg)


def main():
    rclpy.init()
    try:
        rclpy.spin(PanoramaNode())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
