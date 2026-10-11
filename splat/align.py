"""Similarity transform that puts MASt3R's arbitrary frame onto the SLAM map frame."""
import numpy as np


def align_sim3(c2w_src, c2w_dst):
    """Find s, R, t with  dst ~= s * R @ src + t  from matching camera poses.

    Rotation comes from the camera orientations (chordal mean), so it works even
    when every camera of a bubble shares one center (pure spin). Scale and
    translation come from the camera centers; if they don't spread out (a single
    bubble), scale falls back to 1 because MASt3R's metric model is ~meters.
    Returns a 4x4 matrix.
    """
    src, dst = np.asarray(c2w_src, float), np.asarray(c2w_dst, float)
    m = sum(d[:3, :3] @ s[:3, :3].T for s, d in zip(src, dst))
    u, _, vt = np.linalg.svd(m)
    r = u @ np.diag([1.0, 1.0, np.sign(np.linalg.det(u @ vt))]) @ vt

    p = (r @ src[:, :3, 3].T).T
    c = dst[:, :3, 3]
    pc, cc = p - p.mean(0), c - c.mean(0)
    denom = (pc ** 2).sum()
    scale = (pc * cc).sum() / denom if denom > 1e-6 else 1.0
    if scale <= 0:
        scale = 1.0
    t = c.mean(0) - scale * p.mean(0)

    out = np.eye(4)
    out[:3, :3], out[:3, 3] = scale * r, t
    return out


def apply_to_points(sim3, xyz):
    return xyz @ sim3[:3, :3].T + sim3[:3, 3]


def apply_to_pose(sim3, c2w):
    """Transform a camera-to-world pose; keeps the rotation orthonormal."""
    s = np.cbrt(np.linalg.det(sim3[:3, :3]))
    out = np.eye(4)
    out[:3, :3] = (sim3[:3, :3] / s) @ c2w[:3, :3]
    out[:3, 3] = sim3[:3, :3] @ c2w[:3, 3] + sim3[:3, 3]
    return out
