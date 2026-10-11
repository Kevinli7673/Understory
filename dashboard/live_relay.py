"""Live relay between the robot/headset and the dashboard. Runs on the laptop next to the dashboard.

    python dashboard/live_relay.py [--port 8770]

  Quest headset view   ws  /ws/headset/pub   binary JPEG frames in (HeadsetStreamer.cs)
  dashboard browsers   ws  /ws/headset       binary JPEG frames out, newest only
  LiDAR                POST /scan            JSON from scan_bridge.py (ROS), see below
  dashboard server     GET  /scan            newest scan + "age" in seconds, or 204 when none yet
  anything             GET  /headset.jpg     newest headset frame (debugging)
                       GET  /health          counts

Scan JSON (map frame, meters, ROS axes, as in AGENTS.md):
  {"t": 1791600000.1, "pose": {"x": 1.2, "y": -0.3, "yaw": 0.5}, "points": [[x, y], ...]}

Only the newest frame/scan is kept: a slow viewer skips frames instead of falling behind.
"""
import argparse
import asyncio
import json
import time

from aiohttp import WSMsgType, web

MAX_FRAME_BYTES = 2_000_000


class Relay:
    def __init__(self):
        self.frame = None          # newest headset JPEG
        self.frame_t = 0.0
        self.frame_id = 0
        self.scan = None           # newest scan dict
        self.scan_rx = 0.0         # when it arrived (relay clock)
        self.viewers = set()
        self.publishers = 0
        self.new_frame = asyncio.Condition()

    async def publish_frame(self, data):
        async with self.new_frame:
            self.frame, self.frame_t = data, time.time()
            self.frame_id += 1
            self.new_frame.notify_all()


async def headset_pub(request):
    relay = request.app['relay']
    ws = web.WebSocketResponse(max_msg_size=MAX_FRAME_BYTES, heartbeat=10)
    await ws.prepare(request)
    relay.publishers += 1
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                await relay.publish_frame(msg.data)
    finally:
        relay.publishers -= 1
    return ws


async def headset_sub(request):
    relay = request.app['relay']
    ws = web.WebSocketResponse(heartbeat=10)
    await ws.prepare(request)
    relay.viewers.add(ws)

    async def drain():  # viewers send nothing, but reading is how a closed socket is noticed
        async for _ in ws:
            pass
        async with relay.new_frame:
            relay.new_frame.notify_all()
    reader = asyncio.create_task(drain())
    sent = 0
    try:
        if relay.frame is not None:
            await ws.send_bytes(relay.frame)
            sent = relay.frame_id
        while not ws.closed:
            async with relay.new_frame:
                await relay.new_frame.wait_for(lambda: relay.frame_id != sent or ws.closed)
            if ws.closed:
                break
            sent = relay.frame_id
            await ws.send_bytes(relay.frame)
    except (ConnectionError, asyncio.CancelledError):  # aiohttp raises a plain ConnectionError on a lost viewer
        pass
    finally:
        relay.viewers.discard(ws)
        reader.cancel()
    return ws


async def post_scan(request):
    relay = request.app['relay']
    try:
        scan = await request.json()
        assert isinstance(scan.get('points'), list)
    except Exception:
        return web.Response(status=400, text='expected {"pose": {...}, "points": [[x, y], ...]}')
    relay.scan, relay.scan_rx = scan, time.time()
    return web.Response(status=204)


async def get_scan(request):
    relay = request.app['relay']
    if relay.scan is None:
        return web.Response(status=204)
    return web.json_response(dict(relay.scan, age=round(time.time() - relay.scan_rx, 2)))


async def get_frame(request):
    relay = request.app['relay']
    if relay.frame is None:
        return web.Response(status=204)
    return web.Response(body=relay.frame, content_type='image/jpeg', headers={'Cache-Control': 'no-store'})


async def health(request):
    relay = request.app['relay']
    now = time.time()
    return web.json_response({
        'headset_publishers': relay.publishers, 'headset_viewers': len(relay.viewers),
        'frame_age': round(now - relay.frame_t, 2) if relay.frame else None,
        'scan_age': round(now - relay.scan_rx, 2) if relay.scan else None,
    })


@web.middleware
async def cors(request, handler):
    resp = await handler(request)
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


def make_app():
    app = web.Application(middlewares=[cors], client_max_size=4_000_000)
    app['relay'] = Relay()
    app.add_routes([
        web.get('/ws/headset/pub', headset_pub),
        web.get('/ws/headset', headset_sub),
        web.post('/scan', post_scan),
        web.get('/scan', get_scan),
        web.get('/headset.jpg', get_frame),
        web.get('/health', health),
    ])

    async def close_viewers(app):
        relay = app['relay']
        for ws in list(relay.viewers):
            await ws.close()
        async with relay.new_frame:
            relay.new_frame.notify_all()
    app.on_shutdown.append(close_viewers)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host', default='0.0.0.0', help='0.0.0.0 so the Quest and the robot can reach it')
    parser.add_argument('--port', type=int, default=8770)
    args = parser.parse_args()
    print(json.dumps({'relay': f'http://{args.host}:{args.port}'}))
    web.run_app(make_app(), host=args.host, port=args.port, print=None)


if __name__ == '__main__':
    main()
