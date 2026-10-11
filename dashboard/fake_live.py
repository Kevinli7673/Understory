"""Fake live feed for the dashboard, so the live panels can be built without the robot or the headset.

    python dashboard/fake_live.py [--relay http://localhost:8770] [--mission fake_data/missions/m1]

Drives a fake robot along the mission's reading path, POSTs LiDAR scans ray-cast through its map.pgm (5 Hz),
and streams a drawn "headset view" over the same WebSocket the Quest uses (8 fps).
"""
import argparse
import asyncio
import io
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import websockets
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_scan import raycast, scan_to_points  # noqa: E402
from mission_io import load_map_meta, read_jsonl  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def robot_path(mission_dir):
    pts = [(r['x'], r['y']) for r in read_jsonl(Path(mission_dir) / 'readings.jsonl') if 'x' in r]
    path = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
    return path or [(0.0, 0.0)]


def pose_at(path, t, speed=0.25):
    """Walk the path back and forth at speed m/s."""
    legs = [(a, b, math.dist(a, b)) for a, b in zip(path, path[1:]) if math.dist(a, b) > 0]
    if not legs:
        return (*path[0], 0.0)
    total = sum(d for _, _, d in legs)
    s = (t * speed) % (2 * total)
    forward = s <= total
    s = s if forward else 2 * total - s
    for a, b, d in legs:
        if s <= d:
            f = s / d
            yaw = math.atan2(b[1] - a[1], b[0] - a[0]) + (0 if forward else math.pi)
            return a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), math.atan2(math.sin(yaw), math.cos(yaw))
        s -= d
    return (*path[-1], 0.0)


def headset_frame(t, pose, w=640, h=360):
    img = Image.new('RGB', (w, h), (45, 53, 54))
    d = ImageDraw.Draw(img)
    horizon = h // 2 + int(20 * math.sin(t * 0.7))
    d.rectangle([0, horizon, w, h], fill=(105, 124, 112))
    for i in range(6):
        x = int((i * 140 - t * 60) % (w + 140)) - 70
        d.ellipse([x, horizon - 70, x + 90, horizon + 10], fill=(152, 170, 157))
    d.rectangle([16, 16, 300, 64], fill=(242, 239, 226))
    d.text((28, 24), 'FAKE HEADSET VIEW', fill=(45, 53, 54))
    d.text((28, 42), f'{time.strftime("%H:%M:%S")}  robot ({pose[0]:.1f}, {pose[1]:.1f})', fill=(45, 53, 54))
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=70)
    return buf.getvalue()


async def stream_headset(ws_url, path, start, fps):
    while True:
        try:
            async with websockets.connect(ws_url, max_size=None) as ws:
                print(f'headset -> {ws_url}')
                while True:
                    t = time.time() - start
                    await ws.send(headset_frame(t, pose_at(path, t)))
                    await asyncio.sleep(1 / fps)
        except (OSError, websockets.ConnectionClosed) as e:
            print(f'headset: relay unreachable ({e.__class__.__name__}), retrying')
            await asyncio.sleep(2)


async def stream_scans(scan_url, path, mission_dir, start, rate):
    meta = load_map_meta(mission_dir)
    grid = np.asarray(Image.open(Path(mission_dir) / meta['image']).convert('L'))
    while True:
        t = time.time() - start
        pose = pose_at(path, t)
        ranges, a0, inc = raycast(grid, meta, pose, n_beams=360)
        scan = {'t': time.time(), 'pose': {'x': round(pose[0], 3), 'y': round(pose[1], 3), 'yaw': round(pose[2], 3)},
                'points': scan_to_points(ranges, a0, inc, 0.05, 8.0, pose)}
        req = urllib.request.Request(scan_url, data=json.dumps(scan).encode(), method='POST',
                                     headers={'Content-Type': 'application/json'})
        try:
            await asyncio.to_thread(lambda: urllib.request.urlopen(req, timeout=1).read())
        except OSError as e:
            print(f'scan: relay unreachable ({e.__class__.__name__}), retrying')
        await asyncio.sleep(1 / rate)


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--relay', default='http://localhost:8770')
    parser.add_argument('--mission', default=str(REPO / 'fake_data' / 'missions' / 'm1'))
    parser.add_argument('--fps', type=float, default=8)
    parser.add_argument('--scan-rate', type=float, default=5)
    args = parser.parse_args()
    relay = args.relay.rstrip('/')
    path, start = robot_path(args.mission), time.time()
    await asyncio.gather(
        stream_headset(relay.replace('http', 'ws', 1) + '/ws/headset/pub', path, start, args.fps),
        stream_scans(relay + '/scan', path, args.mission, start, args.scan_rate))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
