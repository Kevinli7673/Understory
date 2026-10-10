#!/usr/bin/env python3
"""Save one JPEG every N seconds from /camera/image/compressed.

Run inside the container (~/scout_shell.sh on the host first):
    python3 /fetch_ws/scripts/save_frames.py                # 1 frame/s until Ctrl+C
    python3 /fetch_ws/scripts/save_frames.py --period 0.5   # 2 frames/s
    python3 /fetch_ws/scripts/save_frames.py --duration 30  # stop by itself after 30 s

Frames go to /fetch_ws/frames/<timestamp>/000000.jpg ... (= ~/fetch_ws/frames on the host).
"""
import argparse
import os
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


class FrameSaver(Node):
    def __init__(self, out_dir, period):
        super().__init__('save_frames')
        self.out_dir, self.period = out_dir, period
        self.count, self.last_save = 0, 0.0
        self.create_subscription(CompressedImage, '/camera/image/compressed',
                                 self.on_image, qos_profile_sensor_data)

    def on_image(self, msg):
        now = time.monotonic()
        if now - self.last_save < self.period:
            return
        self.last_save = now
        # the message payload is already a JPEG file, so write it as-is (no decoding)
        with open(os.path.join(self.out_dir, f'{self.count:06d}.jpg'), 'wb') as f:
            f.write(bytes(msg.data))
        self.count += 1
        print(f'\rsaved {self.count} frames', end='', flush=True)


def give_back_to_host_user(path):
    """The container runs as root; chown output to whoever owns /fetch_ws so scp works."""
    st = os.stat('/fetch_ws')
    for root, _, files in os.walk(path):
        os.chown(root, st.st_uid, st.st_gid)
        for name in files:
            os.chown(os.path.join(root, name), st.st_uid, st.st_gid)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--period', type=float, default=1.0, help='seconds between saved frames')
    ap.add_argument('--duration', type=float, default=0.0, help='stop after this many seconds (0 = Ctrl+C)')
    args = ap.parse_args()

    out_dir = os.path.join('/fetch_ws/frames', time.strftime('%Y%m%d-%H%M%S'))
    os.makedirs(out_dir)
    print(f'Saving to {out_dir} every {args.period} s. Ctrl+C to stop.')

    rclpy.init()
    node = FrameSaver(out_dir, args.period)
    end = time.monotonic() + args.duration if args.duration > 0 else None
    try:
        while rclpy.ok() and (end is None or time.monotonic() < end):
            rclpy.spin_once(node, timeout_sec=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        give_back_to_host_user('/fetch_ws/frames')
        print(f'\nDone: {node.count} frames in {out_dir}')
        if node.count == 0:
            print('No frames received. Is the camera publishing? (ros2 topic hz /camera/image/compressed)')


if __name__ == '__main__':
    main()
