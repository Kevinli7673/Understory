#!/usr/bin/env python3
"""Publish contract-correct FAKE survey data so the Quest app and dashboard can be built
before the real perception nodes exist.

Run inside the container (~/scout_shell.sh on the host first):
    python3 /fetch_ws/scripts/fake_survey.py                 # mission m1, real-time
    python3 /fetch_ws/scripts/fake_survey.py --mission m2 --rate 2   # twice as fast

Publishes:
    /survey/bubbles        String JSON         a new bubble every 10 s / rate
    /survey/bubble_images  CompressedImage     12 JPEGs per bubble, frame_id "<bubble_id>/<index>",
                                               yaw = index * 30 deg, sent ~0.1 s apart after the bubble
    /survey/pins           String JSON         1-3 pins per bubble (after its images)
    /survey/readings       String JSON         every 1 s / rate

Images: real camera frames from /fetch_ws/frames/ if any exist (see save_frames.py),
otherwise coloured test cards drawn with OpenCV, otherwise a tiny grey JPEG.
"""
import argparse
import base64
import glob
import json
import math
import random
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None

# (label, invasive)
SPECIES = [('Brazilian pepper', True), ('air potato', True), ('cogongrass', True),
           ('saw palmetto', False), ('wild coffee', False)]
FRAMES_PER_BUBBLE = 12
HFOV = 1.22                      # rad, same as the contract sample
X_RANGE, Y_RANGE = (0.0, 4.0), (-1.5, 1.5)   # ~4 m x 3 m habitat, map frame

# 8x8 grey JPEG, used only if OpenCV is missing and there are no saved frames
TINY_JPEG = base64.b64decode(
    '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAFA3PEY8MlBGQUZaVVBfeMiCeG5uePWvuZHI////////////////////////'
    '////////////////////////////2wBDAVVaWnhpeOuCguv/////////////////////////////////////////////'
    '////////////////////////////wAARCAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcI'
    'CQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRol'
    'JicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ip'
    'qrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAA'
    'AAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLR'
    'ChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaX'
    'mJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEA'
    'PwAooooA/9k=')


def clamp(v, lo_hi):
    return max(lo_hi[0], min(lo_hi[1], v))


class FakeSurvey(Node):
    def __init__(self, mission, rate):
        super().__init__('fake_survey')
        self.mission = mission
        self.pub_bubbles = self.create_publisher(String, '/survey/bubbles', 10)
        self.pub_images = self.create_publisher(CompressedImage, '/survey/bubble_images', 20)
        self.pub_pins = self.create_publisher(String, '/survey/pins', 10)
        self.pub_readings = self.create_publisher(String, '/survey/readings', 10)

        self.x, self.y = 2.0, 0.0          # fake robot position (random walk)
        self.bubble_n = self.pin_n = 0
        self.queue = []                    # (publisher, message) waiting to go out, one per tick
        self.real_frames = sorted(glob.glob('/fetch_ws/frames/**/*.jpg', recursive=True))
        source = (f'{len(self.real_frames)} real frames' if self.real_frames
                  else 'OpenCV test cards' if cv2 else 'tiny grey JPEG')
        self.get_logger().info(f'mission={mission} rate={rate} images={source}')

        self.create_timer(10.0 / rate, self.new_bubble)
        self.create_timer(1.0 / rate, self.new_reading)
        self.create_timer(0.1, self.drain_queue)   # spread bursts out so subscribers don't drop
        # first bubble after 2 s (not 10), once subscribers have had time to discover us
        self.first = self.create_timer(2.0, lambda: (self.first.cancel(), self.new_bubble()))

    # ---- helpers ----
    def wander(self, step):
        self.x = clamp(self.x + random.uniform(-step, step), X_RANGE)
        self.y = clamp(self.y + random.uniform(-step, step), Y_RANGE)

    def send_json(self, pub, data):
        self.queue.append((pub, String(data=json.dumps(data))))

    def drain_queue(self):
        if self.queue:
            pub, msg = self.queue.pop(0)
            pub.publish(msg)

    def frame_jpeg(self, bubble_id, index, yaw):
        if self.real_frames:
            path = self.real_frames[(self.bubble_n * FRAMES_PER_BUBBLE + index) % len(self.real_frames)]
            with open(path, 'rb') as f:
                return f.read()
        if cv2 is None:
            return TINY_JPEG
        # test card: hue changes with yaw so each direction is recognisable in the headset
        img = np.full((480, 640, 3), (int(index * 180 / FRAMES_PER_BUBBLE), 200, 200), np.uint8)
        img = cv2.cvtColor(img, cv2.COLOR_HSV2BGR)
        for row, text in enumerate([f'FAKE {bubble_id}', f'frame {index}/{FRAMES_PER_BUBBLE}',
                                    f'yaw {math.degrees(yaw):.0f} deg']):
            cv2.putText(img, text, (30, 120 + 110 * row), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (0, 0, 0), 4)
        return cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()

    # ---- publishers ----
    def new_bubble(self):
        self.wander(0.8)
        self.bubble_n += 1
        bubble_id = f'{self.mission}-b{self.bubble_n:02d}'
        yaws = [round(i * 2 * math.pi / FRAMES_PER_BUBBLE, 2) for i in range(FRAMES_PER_BUBBLE)]

        self.send_json(self.pub_bubbles, {
            'bubble_id': bubble_id, 'mission_id': self.mission, 't': round(time.time(), 2),
            'x': round(self.x, 2), 'y': round(self.y, 2), 'stitched': False,
            'frames': [{'index': i, 'yaw': yaw} for i, yaw in enumerate(yaws)], 'hfov': HFOV})

        for i, yaw in enumerate(yaws):
            img = CompressedImage(format='jpeg', data=self.frame_jpeg(bubble_id, i, yaw))
            img.header.stamp = self.get_clock().now().to_msg()
            img.header.frame_id = f'{bubble_id}/{i}'
            self.queue.append((self.pub_images, img))

        for _ in range(random.randint(1, 3)):
            self.pin_n += 1
            pin_id = f'{self.mission}-p{self.pin_n:02d}'
            label, invasive = random.choice(SPECIES)
            yaw = random.uniform(0, 2 * math.pi)       # direction of the plant from the bubble
            dist = random.uniform(0.5, 1.5)            # metres from the bubble
            self.send_json(self.pub_pins, {
                'pin_id': pin_id, 'mission_id': self.mission, 'bubble_id': bubble_id,
                'label': label, 'invasive': invasive, 'confidence': round(random.uniform(0.55, 0.97), 2),
                'yaw': round(yaw, 2),
                'x': round(self.x + dist * math.cos(yaw), 2), 'y': round(self.y + dist * math.sin(yaw), 2),
                'crop': f'{pin_id}.jpg',
                'embedding': [round(random.gauss(0, 0.05), 4) for _ in range(512)]})
        self.get_logger().info(f'bubble {bubble_id} at ({self.x:.2f}, {self.y:.2f}), pins so far: {self.pin_n}')

    def new_reading(self):
        self.wander(0.05)
        t = time.time()
        self.send_json(self.pub_readings, {
            'mission_id': self.mission, 't': round(t, 2), 'x': round(self.x, 2), 'y': round(self.y, 2),
            'temp_c': round(24 + 1.5 * math.sin(t / 60) + random.uniform(-0.1, 0.1), 1),
            'pressure_hpa': round(1013 + random.uniform(-0.3, 0.3), 1),
            'soil_moisture': random.randint(380, 450), 'light': random.randint(300, 380),
            'uv': round(random.uniform(0.0, 0.4), 1), 'air_quality': random.randint(95, 130),
            'sound': random.randint(40, 65)})


def main():
    ap = argparse.ArgumentParser(description='Publish fake Scout survey data.')
    ap.add_argument('--mission', default='m1', help='mission id used in all ids (default m1)')
    ap.add_argument('--rate', type=float, default=1.0,
                    help='speed multiplier: 1 = bubble every 10 s and reading every 1 s, 2 = twice as fast')
    args = ap.parse_args()

    rclpy.init()
    node = FakeSurvey(args.mission, args.rate)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
