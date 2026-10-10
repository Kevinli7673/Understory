"""Shared helpers: read a mission folder, camera poses in the map frame, PLY I/O.

Everything stays in the ROS `map` frame (x forward, y left, z up, meters). The
Unity app converts with its one conversion function; we never convert here.
"""
import json
import math
import os

import numpy as np


def load_frames(mission_dir, cam_height=0.20, cam_forward=0.08):
    """One dict per bubble frame on disk: path, bubble_id, index, yaw, hfov, c2w (4x4).

    Frame yaw is the absolute map-frame heading from slam_toolbox (per AGENTS.md).
    The camera sits cam_forward meters ahead of base_link, so it swings on a small
    circle while the robot spins; that is the only intra-bubble parallax we get.
    """
    frames = []
    path = os.path.join(mission_dir, 'bubbles.jsonl')
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            b = json.loads(line)
            for fr in b.get('frames', []):
                img = os.path.join(mission_dir, 'frames', f"{b['bubble_id']}_{fr['index']}.jpg")
                if not os.path.exists(img):
                    continue
                yaw = float(fr['yaw'])
                center = np.array([b['x'] + cam_forward * math.cos(yaw),
                                   b['y'] + cam_forward * math.sin(yaw), cam_height])
                frames.append({
                    'path': img,
                    'bubble_id': b['bubble_id'],
                    'index': fr['index'],
                    'yaw': yaw,
                    'hfov': float(b.get('hfov', 1.22)),
                    'c2w': camera_to_world(center, yaw),
                })
    return frames


def camera_to_world(center, yaw):
    """OpenCV camera (x right, y down, z forward) -> map frame, level camera facing `yaw`."""
    fwd = np.array([math.cos(yaw), math.sin(yaw), 0.0])
    right = np.array([math.sin(yaw), -math.cos(yaw), 0.0])
    down = np.array([0.0, 0.0, -1.0])
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = right, down, fwd, center
    return m


def intrinsics(width, height, hfov):
    f = (width / 2.0) / math.tan(hfov / 2.0)
    return f, f, width / 2.0, height / 2.0


# ---------- PLY ----------
_PLY_TYPES = {'float': 'f4', 'float32': 'f4', 'double': 'f8', 'uchar': 'u1', 'uint8': 'u1',
              'char': 'i1', 'int8': 'i1', 'short': 'i2', 'ushort': 'u2', 'int': 'i4',
              'int32': 'i4', 'uint': 'u4', 'uint32': 'u4'}
_NP_TO_PLY = {'f4': 'float', 'f8': 'double', 'u1': 'uchar', 'i1': 'char', 'i2': 'short',
              'u2': 'ushort', 'i4': 'int', 'u4': 'uint'}


def read_ply(path):
    """Binary little-endian vertex PLY -> numpy structured array."""
    with open(path, 'rb') as f:
        if f.readline().strip() != b'ply':
            raise ValueError(f'{path}: not a PLY file')
        fields, count, fmt = [], 0, None
        in_vertex = False
        while True:
            line = f.readline().decode('ascii').strip()
            if line == 'end_header':
                break
            parts = line.split()
            if parts[0] == 'format':
                fmt = parts[1]
            elif parts[0] == 'element':
                in_vertex = parts[1] == 'vertex'
                if in_vertex:
                    count = int(parts[2])
            elif parts[0] == 'property' and in_vertex:
                fields.append((parts[2], '<' + _PLY_TYPES[parts[1]]))
        if fmt != 'binary_little_endian':
            raise ValueError(f'{path}: only binary_little_endian PLY is supported, got {fmt}')
        return np.frombuffer(f.read(count * np.dtype(fields).itemsize), dtype=fields, count=count)


def write_ply(path, data):
    header = ['ply', 'format binary_little_endian 1.0', f'element vertex {len(data)}']
    for name in data.dtype.names:
        header.append(f'property {_NP_TO_PLY[data.dtype[name].str[1:]]} {name}')
    header.append('end_header')
    with open(path, 'wb') as f:
        f.write(('\n'.join(header) + '\n').encode('ascii'))
        f.write(np.ascontiguousarray(data.astype(data.dtype.newbyteorder('<'))).tobytes())


def points_to_ply(path, xyz, rgb):
    data = np.zeros(len(xyz), dtype=[('x', '<f4'), ('y', '<f4'), ('z', '<f4'),
                                     ('red', 'u1'), ('green', 'u1'), ('blue', 'u1')])
    data['x'], data['y'], data['z'] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    data['red'], data['green'], data['blue'] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    write_ply(path, data)


def voxel_downsample(xyz, rgb, voxel):
    if voxel <= 0 or len(xyz) == 0:
        return xyz, rgb
    keys = np.floor(xyz / voxel).astype(np.int64)
    _, idx = np.unique(keys, axis=0, return_index=True)
    return xyz[idx], rgb[idx]
