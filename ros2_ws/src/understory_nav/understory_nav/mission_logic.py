"""Pure mission logic (no ROS imports) so it can be unit-tested anywhere."""
import math
import re

IDLE = 'IDLE'
SURVEYING = 'SURVEYING'
CAPTURING = 'CAPTURING'
NEXT_POINT = 'NEXT_POINT'
RETURNING = 'RETURNING'
MANUAL = 'MANUAL'
STOPPED = 'STOPPED'

ALL_STATES = (IDLE, SURVEYING, CAPTURING, NEXT_POINT, RETURNING, MANUAL, STOPPED)
# States where the mission (or Nav2 on its behalf) is moving the robot.
AUTONOMOUS_STATES = (SURVEYING, CAPTURING, NEXT_POINT, RETURNING)

# Order matters: safety words first, then phrases that contain other keywords
# ("go home" contains "go", "stop survey" contains "survey").
_COMMAND_PATTERNS = [
    ('stop', r'\b(stop|halt|freeze|abort|pause)\b'),
    ('return', r'\b(return|come back|go back|go home|head home|back home|home)\b'),
    ('manual', r'\b(manual|take over|i\'ll drive|let me drive)\b'),
    ('capture', r'\b(capture|bubble|picture|photo|scan here|look around)\b'),
    ('resume', r'\b(resume|continue|carry on|keep going)\b'),
    ('start', r'\b(start|begin|survey|explore|go)\b'),
]


def parse_command(text):
    """Map a Whisper transcript (or a button's text) to a command name, or None."""
    if not text:
        return None
    t = re.sub(r"[^a-z' ]+", ' ', text.lower())
    t = ' '.join(t.split())
    for name, pattern in _COMMAND_PATTERNS:
        if re.search(pattern, t):
            return name
    return None


def decide(state, command, estopped, survey_active):
    """Return the action to take for `command` in `state`, or None to ignore it.

    survey_active: there are survey points left to visit (so 'resume' makes sense).
    """
    if command == 'stop':
        return 'stop'
    if command == 'manual':
        return 'manual'
    if estopped:
        # While the Quest e-stop is held, only stop/manual are honored.
        return None
    if command == 'start':
        return 'start' if state in (IDLE, MANUAL, STOPPED) else None
    if command == 'resume':
        if state in (MANUAL, STOPPED):
            return 'resume' if survey_active else None
        return None
    if command == 'return':
        return 'return' if state != RETURNING else None
    if command == 'capture':
        return 'capture' if state in (IDLE, MANUAL, STOPPED) else None
    return None


def bubble_id(mission_id, n):
    return f'{mission_id}-b{n:02d}'


def wrap_angle(a):
    return math.atan2(math.sin(a), math.cos(a))


def spin_targets(start_yaw, n):
    """Headings for n evenly spaced stops covering a full turn, starting where we are."""
    return [wrap_angle(start_yaw + k * 2.0 * math.pi / n) for k in range(n)]


def spin_command(target_yaw, yaw, kp, min_speed, max_speed, tolerance):
    """Angular velocity toward target_yaw. Returns (wz, reached)."""
    err = wrap_angle(target_yaw - yaw)
    if abs(err) < tolerance:
        return 0.0, True
    wz = kp * err
    mag = min(max(abs(wz), min_speed), max_speed)
    return math.copysign(mag, err), False


def parse_waypoints(text):
    """'1.0,2.0; 3,-1' -> [(1.0, 2.0), (3.0, -1.0)]."""
    points = []
    for chunk in (text or '').split(';'):
        chunk = chunk.strip()
        if not chunk:
            continue
        x, y = (float(v) for v in chunk.split(','))
        points.append((x, y))
    return points
