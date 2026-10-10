import math

from scout_perception.geometry import (PinTracker, bearing_from, locate, pixel_to_bearing,
                                       scan_range_at, to_map, wrap, yaw_from_quaternion)

HFOV = 0.83
FULL = (-math.pi, 2 * math.pi / 360)      # angle_min, angle_increment of a 360-beam scan


def scan_with(angle, dist, default=float('inf')):
    ranges = [default] * 360
    ranges[round((angle - FULL[0]) / FULL[1]) % 360] = dist
    return (ranges, *FULL)


def test_pixel_to_bearing_centre_and_edges():
    assert pixel_to_bearing(320, 640, HFOV) == 0
    assert math.isclose(pixel_to_bearing(0, 640, HFOV), HFOV / 2)       # left edge -> positive
    assert math.isclose(pixel_to_bearing(640, 640, HFOV), -HFOV / 2)    # right edge -> negative


def test_yaw_from_quaternion():
    assert math.isclose(yaw_from_quaternion(0, 0, math.sin(0.4), math.cos(0.4)), 0.8)


def test_scan_range_takes_median_of_valid():
    ranges = [float('inf')] * 360
    ranges[179], ranges[180], ranges[181] = 1.0, 0.0, 3.0     # 0.0 is below range_min
    assert scan_range_at(ranges, *FULL, 0.0) in (1.0, 3.0)
    ranges[180] = 2.0
    assert scan_range_at(ranges, *FULL, 0.0) == 2.0


def test_scan_range_wraps_and_handles_no_return():
    assert scan_range_at(*scan_with(math.pi - 0.001, 1.5), -math.pi + 0.001) == 1.5
    assert scan_range_at(*scan_with(1.0, 1.5), -1.0) is None
    assert scan_range_at([], *FULL, 0.0) is None


def test_scan_range_partial_scan_does_not_wrap():
    ranges = [2.0] * 90                                        # covers 0 .. 90 deg only
    inc = math.radians(1)
    assert scan_range_at(ranges, 0.0, inc, math.radians(45)) == 2.0
    assert scan_range_at(ranges, 0.0, inc, math.radians(-45)) is None


def test_to_map_rotates_then_translates():
    x, y = to_map((1.0, 2.0, math.pi / 2), 1.0, 0.0)
    assert math.isclose(x, 1.0, abs_tol=1e-9) and math.isclose(y, 3.0)


def test_locate_straight_ahead():
    x, y = locate((0, 0, 0), (0.08, 0, 0), (0, 0, 0), 320, 640, HFOV, scan_with(0.0, 2.0))
    assert math.isclose(x, 2.0) and math.isclose(y, 0.0, abs_tol=1e-9)


def test_locate_uses_robot_yaw_and_pixel_offset():
    bearing = pixel_to_bearing(480, 640, HFOV)                 # right of centre -> negative
    assert bearing < 0
    x, y = locate((1.0, 1.0, math.pi / 2), (0, 0, 0), (0, 0, 0), 480, 640, HFOV,
                  scan_with(bearing, 1.0))
    assert math.isclose(x, 1.0 + math.cos(math.pi / 2 + bearing))
    assert math.isclose(y, 1.0 + math.sin(math.pi / 2 + bearing))
    assert x > 1.0                                             # facing +y, right of centre is +x


def test_locate_respects_laser_yaw_offset():
    # LiDAR mounted backwards: straight ahead of the robot is angle pi in the laser frame
    x, y = locate((0, 0, 0), (0, 0, 0), (0, 0, math.pi), 320, 640, HFOV, scan_with(-math.pi, 1.2))
    assert math.isclose(x, 1.2) and math.isclose(y, 0.0, abs_tol=1e-9)


def test_locate_none_without_lidar_return():
    assert locate((0, 0, 0), (0, 0, 0), (0, 0, 0), 320, 640, HFOV, scan_with(2.0, 1.0)) is None


def test_bearing_from_and_wrap():
    assert math.isclose(bearing_from((1, 1), (1, 3)), math.pi / 2)
    assert math.isclose(wrap(3 * math.pi / 2), -math.pi / 2)


def test_tracker_publishes_once_after_min_sightings():
    tr = PinTracker(merge_radius=0.5, min_sightings=3)
    assert tr.add('air potato', 1.0, 0.0, 0.6)[1] is False
    assert tr.add('air potato', 1.1, 0.0, 0.6)[1] is False
    track, publish = tr.add('air potato', 1.2, 0.0, 0.6)
    assert publish and track['number'] == 1 and math.isclose(track['x'], 1.1)
    assert tr.add('air potato', 1.1, 0.0, 0.6)[1] is False     # same plant, nothing new
    assert len(tr.tracks) == 1


def test_tracker_republishes_on_better_confidence():
    tr = PinTracker(min_sightings=1, republish_gain=0.05)
    assert tr.add('cogongrass', 0, 0, 0.50)[1] is True
    assert tr.add('cogongrass', 0, 0, 0.52)[1] is False
    track, publish = tr.add('cogongrass', 0, 0, 0.70)
    assert publish and track['number'] == 1 and track['confidence'] == 0.70


def test_tracker_separates_labels_and_distance():
    tr = PinTracker(merge_radius=0.5, min_sightings=1)
    a, _ = tr.add('air potato', 0.0, 0.0, 0.6)
    b, _ = tr.add('cogongrass', 0.1, 0.0, 0.6)                 # different label, same place
    c, _ = tr.add('air potato', 2.0, 0.0, 0.6)                 # same label, far away
    assert [a['number'], b['number'], c['number']] == [1, 2, 3]
