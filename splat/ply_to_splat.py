"""Crop + cap a Gaussian-splat PLY (or a plain colored point cloud) for the Quest.

  python ply_to_splat.py in.ply out.splat --out-ply out_small.ply --max 150000 \
      --crop -1 8 -1 6 -0.1 2.0

.splat layout (antimatter15 viewer format), 32 bytes per splat:
  float32 x,y,z | float32 sx,sy,sz | uint8 r,g,b,a | uint8 qw,qx,qy,qz (q*128+128)
Coordinates stay in the ROS map frame; Unity converts.
"""
import argparse

import numpy as np

from common import read_ply, write_ply

SH_C0 = 0.28209479177387814


def is_gaussian(data):
    return all(k in data.dtype.names for k in ('f_dc_0', 'opacity', 'scale_0', 'rot_0'))


def select(data, crop=None, max_count=None):
    """Indices to keep: inside the crop box, most important first, capped."""
    xyz = np.stack([data['x'], data['y'], data['z']], axis=1)
    keep = np.ones(len(data), dtype=bool)
    if crop is not None:
        lo, hi = np.array(crop[0::2]), np.array(crop[1::2])
        keep &= np.all((xyz >= lo) & (xyz <= hi), axis=1)
    idx = np.nonzero(keep)[0]
    if is_gaussian(data):
        vol = np.exp(data['scale_0'] + data['scale_1'] + data['scale_2'])
        alpha = 1.0 / (1.0 + np.exp(-data['opacity']))
        idx = idx[np.argsort(-(vol * alpha)[idx], kind='stable')]
    elif max_count is not None and len(idx) > max_count:
        idx = np.sort(np.random.default_rng(0).choice(idx, max_count, replace=False))
    if max_count is not None:
        idx = idx[:max_count]
    return idx


def to_splat_bytes(data, point_size=0.02):
    n = len(data)
    out = np.zeros(n, dtype=[('pos', '<f4', 3), ('scale', '<f4', 3), ('rgba', 'u1', 4), ('rot', 'u1', 4)])
    out['pos'] = np.stack([data['x'], data['y'], data['z']], axis=1)
    if is_gaussian(data):
        out['scale'] = np.exp(np.stack([data['scale_0'], data['scale_1'], data['scale_2']], axis=1))
        rgb = 0.5 + SH_C0 * np.stack([data['f_dc_0'], data['f_dc_1'], data['f_dc_2']], axis=1)
        alpha = 1.0 / (1.0 + np.exp(-data['opacity']))
        out['rgba'] = np.clip(np.column_stack([rgb, alpha]) * 255, 0, 255).astype(np.uint8)
        q = np.stack([data['rot_0'], data['rot_1'], data['rot_2'], data['rot_3']], axis=1).astype(np.float64)
        q /= np.linalg.norm(q, axis=1, keepdims=True) + 1e-12
    else:
        out['scale'] = point_size
        out['rgba'][:, 0], out['rgba'][:, 1], out['rgba'][:, 2] = data['red'], data['green'], data['blue']
        out['rgba'][:, 3] = 255
        q = np.tile([1.0, 0.0, 0.0, 0.0], (n, 1))
    out['rot'] = np.clip(q * 128 + 128, 0, 255).astype(np.uint8)
    return out.tobytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('in_ply')
    ap.add_argument('out_splat')
    ap.add_argument('--out-ply', help='also write the cropped/capped PLY (Unity Gaussian Splatting importer)')
    ap.add_argument('--max', type=int, default=150000, help='cap for standalone Quest')
    ap.add_argument('--crop', type=float, nargs=6, metavar=('XMIN', 'XMAX', 'YMIN', 'YMAX', 'ZMIN', 'ZMAX'))
    ap.add_argument('--point-size', type=float, default=0.02, help='splat size for plain point clouds (m)')
    args = ap.parse_args()

    data = read_ply(args.in_ply)
    sel = data[select(data, args.crop, args.max)]
    with open(args.out_splat, 'wb') as f:
        f.write(to_splat_bytes(sel, args.point_size))
    if args.out_ply:
        write_ply(args.out_ply, sel)
    kind = 'gaussians' if is_gaussian(data) else 'points'
    print(f'{len(data)} -> {len(sel)} {kind}; wrote {args.out_splat}')


if __name__ == '__main__':
    main()
