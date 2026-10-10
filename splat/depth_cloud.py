"""Fallback when splats won't train: Depth Anything V2 (metric, indoor) point cloud
placed with the SLAM poses. No MASt3R or gsplat needed; runs on ROCm, CUDA or CPU.

  python depth_cloud.py missions/m1 out/m1/cloud.ply
"""
import argparse
import sys

import numpy as np

from common import intrinsics, load_frames, points_to_ply, voxel_downsample

MODEL = 'depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf'


def backproject(depth, rgb, c2w, hfov, stride, max_depth):
    h, w = depth.shape
    fx, fy, cx, cy = intrinsics(w, h, hfov)
    v, u = np.mgrid[0:h:stride, 0:w:stride]
    d = depth[v, u]
    ok = (d > 0.1) & (d < max_depth)
    u, v, d = u[ok], v[ok], d[ok]
    cam = np.stack([(u - cx) / fx * d, (v - cy) / fy * d, d], axis=1)
    world = cam @ c2w[:3, :3].T + c2w[:3, 3]
    return world, rgb[v, u]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mission_dir')
    ap.add_argument('out_ply')
    ap.add_argument('--model', default=MODEL)
    ap.add_argument('--stride', type=int, default=4)
    ap.add_argument('--max-depth', type=float, default=4.0)
    ap.add_argument('--voxel', type=float, default=0.02)
    ap.add_argument('--cam-height', type=float, default=0.20)
    args = ap.parse_args()

    import torch
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    frames = load_frames(args.mission_dir, cam_height=args.cam_height)
    if not frames:
        sys.exit(f'no frames found in {args.mission_dir}')
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    processor = AutoImageProcessor.from_pretrained(args.model)
    model = AutoModelForDepthEstimation.from_pretrained(args.model).to(device).eval()

    all_xyz, all_rgb = [], []
    for i, f in enumerate(frames):
        img = Image.open(f['path']).convert('RGB')
        inputs = processor(images=img, return_tensors='pt').to(device)
        with torch.no_grad():
            pred = model(**inputs).predicted_depth
        depth = torch.nn.functional.interpolate(pred.unsqueeze(1), size=(img.height, img.width),
                                                mode='bicubic', align_corners=False)
        depth = depth.squeeze().float().cpu().numpy()
        xyz, rgb = backproject(depth, np.asarray(img), f['c2w'], f['hfov'], args.stride, args.max_depth)
        all_xyz.append(xyz)
        all_rgb.append(rgb)
        print(f'[{i + 1}/{len(frames)}] {f["path"]}: {len(xyz)} pts')

    xyz, rgb = voxel_downsample(np.concatenate(all_xyz), np.concatenate(all_rgb), args.voxel)
    points_to_ply(args.out_ply, xyz.astype(np.float32), rgb.astype(np.uint8))
    print(f'wrote {args.out_ply}: {len(xyz)} points')


if __name__ == '__main__':
    main()
