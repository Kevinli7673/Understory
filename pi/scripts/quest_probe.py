#!/usr/bin/env python3
"""quest_probe.py - stand in for the Quest app: connect to ROS-TCP-Endpoint as the headset does and check
that everything the app subscribes to arrives, and that a push-to-talk clip comes back as text.

    python3 /fetch_ws/src/Understory/pi/scripts/quest_probe.py 172.20.10.10 [clip.wav] [--seconds 20]

Run it inside the `scout` container (it needs rclpy only to decode messages). It subscribes to the
same topics with the same types as Unity/Assets/Scripts/Ros, and publishes only /voice/audio, and only
when a clip is given. The mission manager acts on the text, so send a clip that is safe to obey.
It never publishes /cmd_vel_teleop or /estop.
"""
import argparse
import json
import socket
import struct
import time

from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid
from rclpy.serialization import deserialize_message, serialize_message
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String, UInt8MultiArray

SUBSCRIBE = {   # topic: type, exactly as RosSurveySource.cs / CameraScreen.cs / PushToTalk.cs
    '/mission/state': String, '/map': OccupancyGrid, '/pose': PoseWithCovarianceStamped,
    '/camera/image/compressed': CompressedImage, '/survey/bubbles': String,
    '/survey/bubble_images': CompressedImage, '/survey/pins': String, '/survey/readings': String,
    '/voice/text': String,
}


def name(cls):
    return cls.__module__.split('.')[0] + '/' + cls.__name__


def frame(topic, payload):
    t = topic.encode()
    return struct.pack('<I', len(t)) + t + struct.pack('<I', len(payload)) + payload


def command(kind, topic, cls):
    # the endpoint drops the last byte of a system command (Unity sends a trailing NUL)
    return frame(kind, json.dumps({'topic': topic, 'message_name': name(cls)}).encode() + b'\x00')


def read_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('endpoint closed the connection')
        buf += chunk
    return buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('host')
    ap.add_argument('clip', nargs='?')
    ap.add_argument('--port', type=int, default=10000)
    ap.add_argument('--seconds', type=float, default=20)
    args = ap.parse_args()

    sock = socket.create_connection((args.host, args.port), timeout=5)
    for topic, cls in SUBSCRIBE.items():
        sock.sendall(command('__subscribe', topic, cls))
    if args.clip:
        sock.sendall(command('__publish', '/voice/audio', UInt8MultiArray))

    seen = {t: [] for t in SUBSCRIBE}      # arrival times
    last = {}
    start = time.monotonic()
    sent = None
    sock.settimeout(0.5)
    while time.monotonic() - start < args.seconds:
        if args.clip and sent is None and time.monotonic() - start > 3:   # give the endpoint time to register
            with open(args.clip, 'rb') as f:
                sock.sendall(frame('/voice/audio', serialize_message(UInt8MultiArray(data=f.read()))))
            sent = time.monotonic()
            print(f'sent {args.clip} on /voice/audio', flush=True)
        try:
            n = struct.unpack('<I', read_exact(sock, 4))[0]
            topic = read_exact(sock, n).decode()
            sock.settimeout(5)
            payload = read_exact(sock, struct.unpack('<I', read_exact(sock, 4))[0])
            sock.settimeout(0.5)
        except socket.timeout:
            continue
        if topic == '__handshake':
            print('handshake:', payload.decode(), flush=True)
        elif topic in SUBSCRIBE:
            seen[topic].append(time.monotonic())
            last[topic] = deserialize_message(payload, SUBSCRIBE[topic])
            if topic == '/voice/text' and sent:
                print(f'/voice/text: "{last[topic].data}" {time.monotonic() - sent:.1f} s after the clip', flush=True)

    print(f'\nover {args.seconds:.0f} s, as the Quest would receive it:')
    for topic, times in seen.items():
        m, extra = last.get(topic), ''
        if isinstance(m, String):
            extra = m.data[:70]
        elif isinstance(m, CompressedImage):
            extra = f'{len(m.data) // 1024} KB {m.format} frame_id={m.header.frame_id}'
        elif isinstance(m, OccupancyGrid):
            extra = f'{m.info.width}x{m.info.height} cells at {m.info.resolution:.2f} m'
        elif isinstance(m, PoseWithCovarianceStamped):
            extra = f'x={m.pose.pose.position.x:.2f} y={m.pose.pose.position.y:.2f} frame={m.header.frame_id}'
        rate = f'{len(times) / args.seconds:5.1f} Hz' if len(times) > 1 else f'{len(times)} msg  '
        print(f'  {topic:28s} {rate}  {extra}')


if __name__ == '__main__':
    main()
