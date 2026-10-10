import numpy as np

from understory_nav.survey_planner import plan_survey_points


def _room(w=100, h=80, res=0.05):
    g = np.zeros((h, w), dtype=np.int8)
    g[0, :] = g[-1, :] = g[:, 0] = g[:, -1] = 100
    g[30:50, 40:60] = 100  # a box in the middle
    return g, res


def test_points_are_safe_reachable_and_spaced():
    g, res = _room()
    h, w = g.shape
    pts = plan_survey_points(g.ravel().tolist(), w, h, res, 0.0, 0.0, (0.5, 0.5),
                             spacing=1.0, clearance=0.3, max_points=20)
    assert pts, 'expected some points'
    assert np.hypot(pts[0][0] - 0.5, pts[0][1] - 0.5) < 0.1  # first bubble where we stand
    for x, y in pts:
        cx, cy = int(x / res), int(y / res)
        assert g[cy, cx] == 0
        # clearance from the box
        near = g[max(cy - 5, 0):cy + 6, max(cx - 5, 0):cx + 6]
        assert (near == 0).all()
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            assert np.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) >= 0.99


def test_unreachable_region_excluded():
    g, res = _room()
    g[:, 70] = 100  # wall off the right side
    h, w = g.shape
    pts = plan_survey_points(g.ravel().tolist(), w, h, res, 0.0, 0.0, (0.5, 0.5),
                             spacing=0.5, clearance=0.2, max_points=100)
    assert all(x < 70 * res for x, _ in pts)


def test_unknown_space_is_not_safe():
    g = -np.ones((40, 40), dtype=np.int8)
    g[10:30, 10:30] = 0
    pts = plan_survey_points(g.ravel().tolist(), 40, 40, 0.1, -2.0, -2.0, (0.0, 0.0),
                             spacing=0.5, clearance=0.2, max_points=50)
    assert pts
    assert all(-1.0 + 0.2 <= x <= 1.0 - 0.2 and -1.0 + 0.2 <= y <= 1.0 - 0.2 for x, y in pts)


def test_max_points_and_origin_offset():
    g, res = _room()
    h, w = g.shape
    pts = plan_survey_points(g.ravel().tolist(), w, h, res, -2.5, -2.0, (-2.0, -1.5),
                             spacing=1.0, clearance=0.3, max_points=3)
    assert len(pts) == 3
    assert all(-2.5 < x < 2.5 and -2.0 < y < 2.0 for x, y in pts)
