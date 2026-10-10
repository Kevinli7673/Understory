import math
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from align import align_sim3, apply_to_points, apply_to_pose  # noqa: E402
from common import camera_to_world, points_to_ply, read_ply, write_ply  # noqa: E402
from depth_cloud import backproject  # noqa: E402
from mast3r_poses import choose_pairs, rot_to_quat  # noqa: E402
from ply_to_splat import select, to_splat_bytes  # noqa: E402


def _rand_rot(rng):
    q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
    return q * np.sign(np.linalg.det(q))


def test_camera_looks_along_yaw():
    c2w = camera_to_world(np.array([1.0, 2.0, 0.2]), math.pi / 2)
    assert np.allclose(c2w[:3, 2], [0, 1, 0], atol=1e-9)    # forward = +y
    assert np.allclose(c2w[:3, 1], [0, 0, -1])              # image down = -z
    assert np.isclose(np.linalg.det(c2w[:3, :3]), 1.0)


def test_align_recovers_sim3():
    rng = np.random.default_rng(1)
    dst = [camera_to_world(np.array([x, y, 0.2]), yaw)
           for x, y in [(0, 0), (2, 0), (1, 1.5)] for yaw in np.linspace(0, 6, 12)]
    r, s, t = _rand_rot(rng), 0.37, np.array([3.0, -1.0, 0.5])
    true = np.eye(4); true[:3, :3], true[:3, 3] = s * r, t
    inv = np.linalg.inv(true)
    src = [apply_to_pose(inv, d) for d in dst]
    est = align_sim3(src, dst)
    assert np.allclose(est, true, atol=1e-6)
    p = rng.normal(size=(5, 3))
    assert np.allclose(apply_to_points(est, apply_to_points(inv, p)), p, atol=1e-6)


def test_align_single_bubble_keeps_unit_scale():
    dst = [camera_to_world(np.array([1.0, 1.0, 0.2]), yaw) for yaw in np.linspace(0, 6, 12)]
    est = align_sim3(dst, dst)
    assert np.allclose(est, np.eye(4), atol=1e-6)


def test_rot_to_quat_roundtrip():
    rng = np.random.default_rng(2)
    for _ in range(20):
        r = _rand_rot(rng)
        w, x, y, z = rot_to_quat(r)
        back = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])
        assert np.allclose(back, r, atol=1e-6)


def test_backproject_center_pixel():
    depth = np.full((40, 60), 2.0)
    rgb = np.zeros((40, 60, 3), np.uint8)
    c2w = camera_to_world(np.array([0.0, 0.0, 0.2]), 0.0)
    xyz, _ = backproject(depth, rgb, c2w, 1.2, 1, 5.0)
    center = xyz[20 * 60 + 30]
    assert np.allclose(center, [2.0, 0.0, 0.2], atol=1e-9)


def test_choose_pairs():
    frames = []
    for b, (x, y) in enumerate([(0, 0), (1, 0), (10, 0)]):
        for k in range(12):
            yaw = k * math.pi / 6
            frames.append({'bubble_id': f'm1-b{b}', 'index': k, 'yaw': yaw,
                           'c2w': camera_to_world(np.array([x, y, 0.2]), yaw)})
    pairs = set(choose_pairs(frames))
    assert (0, 1) in pairs and (0, 11) in pairs and (0, 3) not in pairs
    assert (0, 12) in pairs          # same heading, nearby bubble
    assert (0, 18) not in pairs      # opposite heading
    assert not any(j >= 24 > i for i, j in pairs)  # far bubble only pairs with itself


def _gaussians(n):
    names = ['x', 'y', 'z', 'f_dc_0', 'f_dc_1', 'f_dc_2', 'opacity',
             'scale_0', 'scale_1', 'scale_2', 'rot_0', 'rot_1', 'rot_2', 'rot_3']
    d = np.zeros(n, dtype=[(k, '<f4') for k in names])
    d['x'] = np.arange(n)
    d['scale_0'] = d['scale_1'] = d['scale_2'] = np.log(0.01 * (np.arange(n) + 1))
    d['opacity'] = 2.0
    d['rot_0'] = 1.0
    return d


def test_ply_roundtrip_and_splat():
    with tempfile.TemporaryDirectory() as tmp:
        g = _gaussians(10)
        write_ply(os.path.join(tmp, 'g.ply'), g)
        back = read_ply(os.path.join(tmp, 'g.ply'))
        assert back.dtype.names == g.dtype.names and np.array_equal(back, g)

        idx = select(back, crop=[-1, 5.5, -1, 1, -1, 1], max_count=3)
        assert list(idx) == [5, 4, 3]  # biggest first, cropped to x <= 5.5
        raw = to_splat_bytes(back[idx])
        assert len(raw) == 3 * 32
        rec = np.frombuffer(raw, dtype=[('pos', '<f4', 3), ('scale', '<f4', 3),
                                        ('rgba', 'u1', 4), ('rot', 'u1', 4)])
        assert rec['pos'][0][0] == 5.0 and np.isclose(rec['scale'][0][0], 0.06)
        assert tuple(rec['rot'][0]) == (255, 128, 128, 128)

        points_to_ply(os.path.join(tmp, 'p.ply'), np.zeros((4, 3)), np.full((4, 3), 200, np.uint8))
        p = read_ply(os.path.join(tmp, 'p.ply'))
        rec = np.frombuffer(to_splat_bytes(p), dtype=[('pos', '<f4', 3), ('scale', '<f4', 3),
                                                      ('rgba', 'u1', 4), ('rot', 'u1', 4)])
        assert tuple(rec['rgba'][0]) == (200, 200, 200, 255)
