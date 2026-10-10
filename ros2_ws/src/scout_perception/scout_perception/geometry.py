"""Pin geometry and de-duplication. Plain Python (no ROS imports) so it can be unit-tested.

Frames follow ROS: x forward, y left, yaw counter-clockwise in radians. A 2D pose is (x, y, yaw).
"""
import math


def yaw_from_quaternion(x, y, z, w):
    return math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))


def wrap(angle):
    """Wrap an angle to (-pi, pi]."""
    return math.atan2(math.sin(angle), math.cos(angle))


def pixel_to_bearing(cx, image_width, hfov):
    """Angle of image column `cx` from the camera's forward axis. Left of centre is positive.

    Pinhole model: the edge of the image is at hfov / 2.
    """
    focal = (image_width / 2) / math.tan(hfov / 2)
    return -math.atan((cx - image_width / 2) / focal)


def scan_range_at(ranges, angle_min, angle_increment, angle, window=0.035,
                  range_min=0.05, range_max=12.0):
    """Median of the valid LiDAR ranges within +-`window` rad of `angle` (laser frame), or None."""
    if not ranges or angle_increment == 0:
        return None
    n = len(ranges)
    full_circle = abs(n * angle_increment) > 2 * math.pi - 0.2
    centre = round((angle - angle_min) / angle_increment)
    half = max(0, int(window / abs(angle_increment)))
    valid = []
    for i in range(centre - half, centre + half + 1):
        if full_circle:
            i %= n
        elif not 0 <= i < n:
            continue
        r = ranges[i]
        if r is not None and math.isfinite(r) and range_min <= r <= range_max:
            valid.append(r)
    if not valid:
        return None
    valid.sort()
    return valid[len(valid) // 2]


def to_map(pose, x, y):
    """Point (x, y) in the frame whose map pose is `pose` -> map coordinates."""
    px, py, yaw = pose
    return (px + x * math.cos(yaw) - y * math.sin(yaw),
            py + x * math.sin(yaw) + y * math.cos(yaw))


def locate(robot, camera, laser, cx, image_width, hfov, scan):
    """Map position of whatever the camera sees at image column `cx`, or None if the LiDAR has no return there.

    robot   (x, y, yaw) of base_link in the map
    camera  (x, y, yaw) of the camera in base_link
    laser   (x, y, yaw) of the LiDAR in base_link
    scan    (ranges, angle_min, angle_increment)

    The direction comes from the camera, the distance from the LiDAR ray in that same direction.
    The few centimetres between the two sensors are ignored.
    """
    direction = camera[2] + pixel_to_bearing(cx, image_width, hfov)     # in base_link
    dist = scan_range_at(scan[0], scan[1], scan[2], direction - laser[2])
    if dist is None:
        return None
    return to_map(robot, laser[0] + dist * math.cos(direction), laser[1] + dist * math.sin(direction))


def bearing_from(origin_xy, target_xy):
    """Map-frame yaw of the line from origin to target (the pin's `yaw` as seen from its bubble)."""
    return math.atan2(target_xy[1] - origin_xy[1], target_xy[0] - origin_xy[0])


class PinTracker:
    """Turns repeated sightings of the same plant into one pin.

    A sighting joins an existing track when the label matches and it is within `merge_radius`
    metres; the track position is the running mean. `add` returns (track, publish):
    publish is True the moment a track reaches `min_sightings`, and again whenever a later
    sighting beats the published confidence by `republish_gain`.
    """

    def __init__(self, merge_radius=0.5, min_sightings=3, republish_gain=0.05):
        self.merge_radius = merge_radius
        self.min_sightings = min_sightings
        self.republish_gain = republish_gain
        self.tracks = []
        self.published = 0

    def add(self, label, x, y, confidence):
        track = None
        for t in self.tracks:
            if t['label'] == label and math.hypot(t['x'] - x, t['y'] - y) <= self.merge_radius:
                track = t
                break
        if track is None:
            track = {'label': label, 'x': x, 'y': y, 'n': 0, 'confidence': 0.0,
                     'number': None, 'published_confidence': None}
            self.tracks.append(track)
        track['n'] += 1
        track['x'] += (x - track['x']) / track['n']
        track['y'] += (y - track['y']) / track['n']
        track['confidence'] = max(track['confidence'], confidence)

        if track['n'] < self.min_sightings:
            return track, False
        if track['number'] is None:
            self.published += 1
            track['number'] = self.published
        elif confidence < track['published_confidence'] + self.republish_gain:
            return track, False
        track['published_confidence'] = track['confidence']
        return track, True
