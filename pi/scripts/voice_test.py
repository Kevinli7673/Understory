#!/usr/bin/env python3
"""voice_test.py - send WAV files to /voice/audio the way the Quest does, print what comes back on /voice/text.

    python3 /fetch_ws/src/Understory/pi/scripts/voice_test.py clip.wav [more.wav ...]

Needs whisper_node running. The mission manager acts on the text, so on the live ROS domain only
send clips that are safe to obey. voice_selftest.sh runs this on a separate domain.
"""
import sys
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, UInt8MultiArray


def main():
    rclpy.init()
    node = Node('voice_test')
    heard = []
    node.create_subscription(String, '/voice/text', lambda m: heard.append(m.data), 10)
    pub = node.create_publisher(UInt8MultiArray, '/voice/audio', 1)
    deadline = time.monotonic() + 10
    while pub.get_subscription_count() == 0 and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.2)
    if pub.get_subscription_count() == 0:
        sys.exit('nothing is subscribed to /voice/audio: is whisper_node running?')
    for path in sys.argv[1:]:
        with open(path, 'rb') as f:
            pub.publish(UInt8MultiArray(data=f.read()))
        heard.clear()
        start = time.monotonic()
        while not heard and time.monotonic() - start < 60:
            rclpy.spin_once(node, timeout_sec=0.2)
        took = time.monotonic() - start
        print(f'{path}: "{heard[0]}" after {took:.1f} s' if heard else f'{path}: no text within 60 s', flush=True)


if __name__ == '__main__':
    main()
