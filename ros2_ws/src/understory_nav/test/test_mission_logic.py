import math

from understory_nav import mission_logic as ml


def test_parse_command():
    cases = {
        'Start survey.': 'start',
        'stop the survey': 'stop',
        'Okay, go home!': 'return',
        'come back': 'return',
        "I'll drive": 'manual',
        'take a picture here': 'capture',
        'keep going': 'resume',
        'go': 'start',
        'what a nice plant': None,
        '': None,
    }
    for text, want in cases.items():
        assert ml.parse_command(text) == want, text


def test_decide():
    assert ml.decide(ml.SURVEYING, 'stop', False, True) == 'stop'
    assert ml.decide(ml.IDLE, 'start', False, False) == 'start'
    assert ml.decide(ml.SURVEYING, 'start', False, True) is None
    assert ml.decide(ml.STOPPED, 'start', True, True) is None  # e-stop held
    assert ml.decide(ml.STOPPED, 'manual', True, True) == 'manual'
    assert ml.decide(ml.STOPPED, 'resume', False, True) == 'resume'
    assert ml.decide(ml.STOPPED, 'resume', False, False) is None
    assert ml.decide(ml.MANUAL, 'capture', False, False) == 'capture'
    assert ml.decide(ml.CAPTURING, 'capture', False, True) is None
    assert ml.decide(ml.RETURNING, 'return', False, False) is None
    assert ml.decide(ml.IDLE, None, False, False) is None


def test_bubble_id():
    assert ml.bubble_id('m1', 3) == 'm1-b03'


def test_spin_targets_cover_full_turn():
    t = ml.spin_targets(0.5, 12)
    assert len(t) == 12
    assert math.isclose(t[0], 0.5)
    steps = [ml.wrap_angle(t[i + 1] - t[i]) for i in range(11)]
    assert all(math.isclose(s, math.pi / 6) for s in steps)


def test_spin_command():
    wz, done = ml.spin_command(1.0, 0.0, 1.5, 0.25, 0.6, 0.05)
    assert not done and wz == 0.6
    wz, done = ml.spin_command(0.1, 0.0, 1.5, 0.25, 0.6, 0.05)
    assert not done and wz == 0.25  # min speed so the wheels don't stall
    wz, done = ml.spin_command(-3.0, 3.0, 1.5, 0.25, 0.6, 0.05)
    assert wz > 0  # shortest way across +-pi
    assert ml.spin_command(0.02, 0.0, 1.5, 0.25, 0.6, 0.05) == (0.0, True)


def test_parse_waypoints():
    assert ml.parse_waypoints('1,2; 3.5,-1;') == [(1.0, 2.0), (3.5, -1.0)]
    assert ml.parse_waypoints('') == []
