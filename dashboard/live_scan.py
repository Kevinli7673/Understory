"""LiDAR scan -> map-frame points. Pure math, shared by scan_bridge.py (ROS) and fake_live.py; no ROS imports."""
import math


def scan_to_points(ranges, angle_min, angle_increment, range_min, range_max, laser_pose, max_points=720):
    """LaserScan ranges -> [[x, y], ...] in the map frame.

    laser_pose = (x, y, yaw) of the laser frame in the map frame. Invalid ranges (inf, nan, out of
    [range_min, range_max]) are dropped. Every n-th beam is kept so at most max_points come out.
    """
    lx, ly, lyaw = laser_pose
    step = max(1, math.ceil(len(ranges) / max_points)) if max_points else 1
    points = []
    for i in range(0, len(ranges), step):
        r = ranges[i]
        if not math.isfinite(r) or r < range_min or r > range_max:
            continue
        a = lyaw + angle_min + i * angle_increment
        points.append([round(lx + r * math.cos(a), 3), round(ly + r * math.sin(a), 3)])
    return points


def yaw_from_quaternion(x, y, z, w):
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def raycast(grid, meta, pose, n_beams=360, max_range=8.0):
    """Fake scan: ranges from pose through an occupancy image (numpy array, 0 = wall), for fake_live.py.

    meta is mission_io.load_map_meta(); row 0 of the image is the top (max y), like map.pgm.
    """
    x0, y0, res = meta['origin_x'], meta['origin_y'], meta['resolution']
    h, w = grid.shape
    px, py, yaw = pose
    ranges = []
    for i in range(n_beams):
        a = yaw - math.pi + i * (2 * math.pi / n_beams)
        r = float('inf')
        d = 0.05
        while d <= max_range:
            cx = int((px + d * math.cos(a) - x0) / res)
            cy = h - 1 - int((py + d * math.sin(a) - y0) / res)
            if not (0 <= cx < w and 0 <= cy < h):
                break
            if grid[cy, cx] < 100:
                r = d
                break
            d += res
        ranges.append(r)
    return ranges, -math.pi, 2 * math.pi / n_beams
