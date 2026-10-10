"""Bubble frames -> MASt3R poses + dense points -> aligned to the SLAM map -> COLMAP model.

  python mast3r_poses.py missions/m1 out/m1/colmap --mast3r ~/mast3r

Writes <out>/images/*.jpg (at MASt3R resolution, so intrinsics match exactly),
<out>/sparse/0/{cameras,images,points3D}.txt for gsplat, and <out>/mast3r_points.ply.
Run on the AMD W7900 box (PyTorch ROCm image; "cuda" is the ROCm device in torch).
"""
import argparse
import math
import os
import sys

import numpy as np

from align import align_sim3, apply_to_points, apply_to_pose
from common import load_frames, points_to_ply, voxel_downsample

MODEL = 'naver/MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric'


def choose_pairs(frames, ring=2, max_dist=3.0, max_yaw=math.radians(50)):
    """Neighbors within a bubble (spin) plus same-direction frames from nearby bubbles.

    The cross-bubble pairs are what give MASt3R real parallax; a single spin barely has any.
    """
    pairs = set()
    n = len(frames)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = frames[i], frames[j]
            if a['bubble_id'] == b['bubble_id']:
                size = sum(f['bubble_id'] == a['bubble_id'] for f in frames)
                d = abs(a['index'] - b['index'])
                if min(d, size - d) <= ring:
                    pairs.add((i, j))
            else:
                dist = np.linalg.norm(a['c2w'][:2, 3] - b['c2w'][:2, 3])
                dyaw = abs(math.atan2(math.sin(a['yaw'] - b['yaw']), math.cos(a['yaw'] - b['yaw'])))
                if dist <= max_dist and dyaw <= max_yaw:
                    pairs.add((i, j))
    return sorted(pairs)


def rot_to_quat(r):
    """3x3 rotation -> (w, x, y, z)."""
    w = math.sqrt(max(0.0, 1.0 + r[0, 0] + r[1, 1] + r[2, 2])) / 2.0
    x = math.copysign(math.sqrt(max(0.0, 1.0 + r[0, 0] - r[1, 1] - r[2, 2])) / 2.0, r[2, 1] - r[1, 2])
    y = math.copysign(math.sqrt(max(0.0, 1.0 - r[0, 0] + r[1, 1] - r[2, 2])) / 2.0, r[0, 2] - r[2, 0])
    z = math.copysign(math.sqrt(max(0.0, 1.0 - r[0, 0] - r[1, 1] + r[2, 2])) / 2.0, r[1, 0] - r[0, 1])
    return w, x, y, z


def write_colmap(out_dir, names, c2ws, focal, width, height, xyz, rgb):
    sparse = os.path.join(out_dir, 'sparse', '0')
    os.makedirs(sparse, exist_ok=True)
    with open(os.path.join(sparse, 'cameras.txt'), 'w') as f:
        f.write(f'1 PINHOLE {width} {height} {focal} {focal} {width / 2.0} {height / 2.0}\n')
    with open(os.path.join(sparse, 'images.txt'), 'w') as f:
        for i, (name, c2w) in enumerate(zip(names, c2ws), start=1):
            w2c = np.linalg.inv(c2w)
            qw, qx, qy, qz = rot_to_quat(w2c[:3, :3])
            tx, ty, tz = w2c[:3, 3]
            f.write(f'{i} {qw} {qx} {qy} {qz} {tx} {ty} {tz} 1 {name}\n\n')
    with open(os.path.join(sparse, 'points3D.txt'), 'w') as f:
        for i, (p, c) in enumerate(zip(xyz, rgb), start=1):
            f.write(f'{i} {p[0]} {p[1]} {p[2]} {c[0]} {c[1]} {c[2]} 0\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mission_dir')
    ap.add_argument('out_dir')
    ap.add_argument('--mast3r', default=os.path.expanduser('~/mast3r'), help='clone of naver/mast3r')
    ap.add_argument('--max-frames', type=int, default=120)
    ap.add_argument('--niter1', type=int, default=300)
    ap.add_argument('--niter2', type=int, default=200)
    ap.add_argument('--min-conf', type=float, default=1.5)
    ap.add_argument('--voxel', type=float, default=0.02)
    ap.add_argument('--max-points', type=int, default=150000)
    args = ap.parse_args()

    sys.path.insert(0, args.mast3r)
    import torch
    from PIL import Image
    from mast3r.cloud_opt.sparse_ga import sparse_global_alignment
    from mast3r.model import AsymmetricMASt3R
    import mast3r.utils.path_to_dust3r  # noqa: F401
    from dust3r.utils.image import load_images

    frames = load_frames(args.mission_dir)
    if not frames:
        sys.exit(f'no frames found in {args.mission_dir}')
    if len(frames) > args.max_frames:
        keep = np.linspace(0, len(frames) - 1, args.max_frames).round().astype(int)
        frames = [frames[i] for i in keep]
    print(f'{len(frames)} frames')

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = AsymmetricMASt3R.from_pretrained(MODEL).to(device)
    files = [f['path'] for f in frames]
    imgs = load_images(files, size=512, verbose=False)
    pair_idx = choose_pairs(frames)
    pairs = [p for i, j in pair_idx for p in ((imgs[i], imgs[j]), (imgs[j], imgs[i]))]
    print(f'{len(pair_idx)} image pairs')

    cache = os.path.join(args.out_dir, 'mast3r_cache')
    os.makedirs(cache, exist_ok=True)
    scene = sparse_global_alignment(files, pairs, cache, model, lr1=0.07, niter1=args.niter1,
                                    lr2=0.014, niter2=args.niter2, device=device, opt_depth=True,
                                    shared_intrinsics=True, matching_conf_thr=5.0)

    poses = scene.get_im_poses().detach().cpu().numpy()
    focal = float(scene.get_focals().detach().cpu().numpy().mean())
    pts3d, _, confs = scene.get_dense_pts3d(clean_depth=True)
    pts = [p.detach().cpu().numpy().reshape(-1, 3) for p in pts3d]
    masks = [(c.detach().cpu().numpy() > args.min_conf).ravel() for c in confs]
    images = [np.asarray(im) for im in scene.imgs]

    # Put everything in the SLAM map frame.
    sim3 = align_sim3(poses, np.stack([f['c2w'] for f in frames]))
    print('scale MASt3R -> map:', np.cbrt(np.linalg.det(sim3[:3, :3])))
    c2ws = [apply_to_pose(sim3, p) for p in poses]
    xyz = np.concatenate([p[m] for p, m in zip(pts, masks)])
    rgb = np.concatenate([(im.reshape(-1, 3)[m] * 255).astype(np.uint8) for im, m in zip(images, masks)])
    xyz = apply_to_points(sim3, xyz)
    xyz, rgb = voxel_downsample(xyz, rgb, args.voxel)
    if len(xyz) > args.max_points:
        keep = np.random.default_rng(0).choice(len(xyz), args.max_points, replace=False)
        xyz, rgb = xyz[keep], rgb[keep]
    print(f'{len(xyz)} points')

    img_dir = os.path.join(args.out_dir, 'images')
    os.makedirs(img_dir, exist_ok=True)
    names = []
    for f, im in zip(frames, images):
        name = os.path.basename(f['path'])
        Image.fromarray((im * 255).astype(np.uint8)).save(os.path.join(img_dir, name), quality=95)
        names.append(name)
    h, w = images[0].shape[:2]
    write_colmap(args.out_dir, names, c2ws, focal, w, h, xyz, rgb)
    points_to_ply(os.path.join(args.out_dir, 'mast3r_points.ply'), xyz, rgb)
    print('wrote', args.out_dir)


if __name__ == '__main__':
    main()
