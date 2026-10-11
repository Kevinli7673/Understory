import asyncio
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from live_scan import raycast, scan_to_points, yaw_from_quaternion  # noqa: E402
from mission_io import load_map_meta  # noqa: E402

FAKE = HERE.parent.parent / 'fake_data' / 'missions'


def test_scan_points_rotate_and_translate_into_map():
    # one beam straight ahead of a laser at (1, 2) facing +y: 3 m ahead lands at (1, 5)
    pts = scan_to_points([3.0], 0.0, 0.1, 0.1, 10.0, (1.0, 2.0, math.pi / 2))
    assert pts == [[pytest.approx(1.0, abs=1e-3), pytest.approx(5.0, abs=1e-3)]]


def test_scan_points_drop_invalid_ranges_and_downsample():
    ranges = [1.0, float('inf'), float('nan'), 0.01, 50.0, 2.0]
    pts = scan_to_points(ranges, 0.0, 0.0, 0.1, 10.0, (0, 0, 0))
    assert len(pts) == 2
    assert len(scan_to_points([1.0] * 1000, 0.0, 0.001, 0.1, 10.0, (0, 0, 0), max_points=100)) == 100


def test_yaw_from_quaternion():
    half = math.pi / 8
    assert yaw_from_quaternion(0, 0, math.sin(half), math.cos(half)) == pytest.approx(math.pi / 4)


def test_raycast_hits_fake_map_walls():
    meta = load_map_meta(FAKE / 'm1')
    grid = np.asarray(Image.open(FAKE / 'm1' / meta['image']).convert('L'))
    ranges, a0, inc = raycast(grid, meta, (0.0, 0.0, 0.0), n_beams=72)
    hits = [r for r in ranges if math.isfinite(r)]
    assert len(hits) > 60 and all(0.05 <= r <= 8.0 for r in hits)


def test_relay_passes_frames_and_scans():
    from aiohttp.test_utils import TestClient, TestServer
    from live_relay import make_app

    async def run():
        async with TestClient(TestServer(make_app())) as client:
            assert (await client.get('/scan')).status == 204
            viewer = await client.ws_connect('/ws/headset')
            pub = await client.ws_connect('/ws/headset/pub')
            await pub.send_bytes(b'\xff\xd8jpeg1')
            assert await asyncio.wait_for(viewer.receive_bytes(), 2) == b'\xff\xd8jpeg1'
            await pub.send_bytes(b'\xff\xd8jpeg2')
            assert await asyncio.wait_for(viewer.receive_bytes(), 2) == b'\xff\xd8jpeg2'

            scan = {'t': 1.0, 'pose': {'x': 1, 'y': 2, 'yaw': 0}, 'points': [[1, 2], [3, 4]]}
            assert (await client.post('/scan', json=scan)).status == 204
            got = await (await client.get('/scan')).json()
            assert got['points'] == [[1, 2], [3, 4]] and got['age'] < 1
            assert (await client.post('/scan', json={'nope': 1})).status == 400
            health = await (await client.get('/health')).json()
            assert health['headset_publishers'] == 1 and health['headset_viewers'] == 1
            await viewer.close()
            await pub.close()

    asyncio.run(run())
