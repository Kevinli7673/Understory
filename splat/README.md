# AMD splat pipeline (stretch, Teammate 3)

Runs on the Radeon Cloud W7900 box, never the Jetson. Input: a mission folder. Output:
`out/<id>/scene.splat` + `scene.ply`, in the ROS `map` frame (Unity converts with its one function).

```bash
bash setup_amd.sh                         # once; filters torch out of every requirements file
bash run.sh missions/m1                   # optional crop: run.sh missions/m1 -1 8 -1 6 -0.1 2
```

Pipeline, with a fallback at each step:

1. `mast3r_poses.py`: bubble frames → MASt3R (pairs = neighbors in a spin + same-heading frames
   from nearby bubbles) → poses + dense points → **aligned to the SLAM map** using the frame
   yaws and bubble positions → COLMAP model.
2. `train_splat.sh`: gsplat `simple_trainer` with world normalization off, so output stays in the map frame.
   *gsplat fails on ROCm* → MASt3R point cloud.
   *MASt3R fails* → `depth_cloud.py` (Depth Anything V2 metric-indoor + SLAM poses).
3. `ply_to_splat.py`: crop, keep the largest/most opaque splats (default cap 150k for standalone Quest),
   write `.splat` + a trimmed `.ply`. Point clouds become small round splats, so the Unity side is the same either way.

Tests (numpy only): `python -m pytest splat/tests`

Caveat: a bubble is a spin in place, which gives almost no parallax. The splat depends on
having several bubbles about 1 m apart. With only one or two, expect the point cloud fallback to look better.
