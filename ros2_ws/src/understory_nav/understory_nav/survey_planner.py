"""Pick survey (bubble) points from an occupancy grid. Pure numpy, no ROS."""
import math
from collections import deque

import numpy as np


def _dilate(mask, r):
    """Square dilation by r cells using array shifts (no scipy on the Jetson image)."""
    if r <= 0:
        return mask.copy()
    h, w = mask.shape
    padded = np.pad(mask, r, constant_values=False)
    out = np.zeros_like(mask)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy > r * r:
                continue
            out |= padded[r + dy:r + dy + h, r + dx:r + dx + w]
    return out


def _flood(safe, start):
    """Cells reachable from start through safe cells (4-connected)."""
    h, w = safe.shape
    seen = np.zeros_like(safe)
    sy, sx = start
    if not safe[sy, sx]:
        return seen
    seen[sy, sx] = True
    q = deque([(sy, sx)])
    while q:
        y, x = q.popleft()
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= ny < h and 0 <= nx < w and safe[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))
    return seen


def _nearest_safe(safe, cell, max_r):
    y0, x0 = cell
    h, w = safe.shape
    for r in range(max_r + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                y, x = y0 + dy, x0 + dx
                if 0 <= y < h and 0 <= x < w and safe[y, x]:
                    return y, x
    return None


def plan_survey_points(data, width, height, resolution, origin_x, origin_y,
                       start_xy, spacing=1.0, clearance=0.35, max_points=10):
    """Return [(x, y), ...] in the map frame, ordered as a greedy tour from start_xy.

    data: OccupancyGrid.data (row-major, -1 unknown, 0..100 occupancy).
    Points lie on a `spacing` lattice, at least `clearance` m from obstacles and
    unknown space, and reachable from the robot.
    """
    grid = np.asarray(data, dtype=np.int16).reshape(height, width)
    free = grid == 0
    blocked = _dilate(~free, int(math.ceil(clearance / resolution)))
    safe = free & ~blocked

    def to_cell(x, y):
        return (int((y - origin_y) / resolution), int((x - origin_x) / resolution))

    def to_xy(cell):
        y, x = cell
        return (origin_x + (x + 0.5) * resolution, origin_y + (y + 0.5) * resolution)

    sy, sx = to_cell(*start_xy)
    sy = min(max(sy, 0), height - 1)
    sx = min(max(sx, 0), width - 1)
    # The robot itself may sit inside the clearance band; start the flood from
    # the nearest safe cell instead.
    seed = _nearest_safe(safe, (sy, sx), int(math.ceil(1.0 / resolution)))
    if seed is None:
        return []
    reachable = _flood(safe, seed)

    step = max(1, int(round(spacing / resolution)))
    # Anchor the lattice on the robot so the first bubble is where it stands.
    ys = list(range(seed[0] % step, height, step))
    xs = list(range(seed[1] % step, width, step))
    candidates = [to_xy((y, x)) for y in ys for x in xs if reachable[y, x]]

    tour = []
    cur = start_xy
    while candidates and len(tour) < max_points:
        i = min(range(len(candidates)),
                key=lambda k: (candidates[k][0] - cur[0]) ** 2 + (candidates[k][1] - cur[1]) ** 2)
        cur = candidates.pop(i)
        tour.append(cur)
    return tour
