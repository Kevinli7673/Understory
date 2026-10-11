import json
import os

import numpy as np

from scout_perception.mission_log import MissionLog, frame_file, map_to_pgm, map_yaml, mission_of


def lines(path):
    with open(path) as f:
        return [json.loads(line) for line in f]


def test_mission_of():
    assert mission_of('m1-b03') == 'm1'
    assert mission_of('m1-p07') == 'm1'
    assert mission_of('site-a-2-b01') == 'site-a-2'


def test_frame_file():
    assert frame_file('m1-b03/4') == ('m1', 'm1-b03_4.jpg')
    assert frame_file('m1-b03/pano') == ('m1', 'm1-b03_pano.jpg')
    assert frame_file('camera') is None
    assert frame_file('m1-b03/../x') is None
    assert frame_file('/3') is None


def test_bubble_resent_replaces_its_line(tmp_path):
    log = MissionLog(str(tmp_path))
    log.bubble({'bubble_id': 'm1-b01', 'mission_id': 'm1', 'stitched': False})
    log.bubble({'bubble_id': 'm1-b02', 'mission_id': 'm1', 'stitched': False})
    log.bubble({'bubble_id': 'm1-b01', 'mission_id': 'm1', 'stitched': True})
    rows = lines(tmp_path / 'm1' / 'bubbles.jsonl')
    assert [r['bubble_id'] for r in rows] == ['m1-b01', 'm1-b02']
    assert rows[0]['stitched'] is True


def test_restart_keeps_earlier_rows(tmp_path):
    MissionLog(str(tmp_path)).pin({'pin_id': 'm1-p01', 'mission_id': 'm1', 'label': 'cogongrass'})
    again = MissionLog(str(tmp_path))
    again.pin({'pin_id': 'm1-p02', 'mission_id': 'm1', 'label': 'air potato'})
    assert [r['pin_id'] for r in lines(tmp_path / 'm1' / 'pins.jsonl')] == ['m1-p01', 'm1-p02']


def test_missions_do_not_mix(tmp_path):
    log = MissionLog(str(tmp_path))
    log.pin({'pin_id': 'm1-p01', 'mission_id': 'm1'})
    log.pin({'pin_id': 'm2-p01', 'mission_id': 'm2'})
    log.reading({'mission_id': 'm2', 't': 1.0, 'temp_c': 24.1})
    log.reading({'mission_id': 'm2', 't': 2.0, 'temp_c': 24.2})
    assert len(lines(tmp_path / 'm1' / 'pins.jsonl')) == 1
    assert len(lines(tmp_path / 'm2' / 'pins.jsonl')) == 1
    assert len(lines(tmp_path / 'm2' / 'readings.jsonl')) == 2


def test_frames_are_named_like_the_contract(tmp_path):
    log = MissionLog(str(tmp_path))
    path = log.frame('m1-b03/11', b'\xff\xd8jpeg')
    assert path == os.path.join(str(tmp_path), 'm1', 'frames', 'm1-b03_11.jpg')
    with open(path, 'rb') as f:
        assert f.read() == b'\xff\xd8jpeg'
    assert log.frame('not a bubble frame', b'x') is None


def test_map_matches_map_saver(tmp_path):
    # 3 wide, 2 high. Row 0 is the smallest y, so it must end up as the bottom image row.
    data = [0, 100, -1,
            50, 25, 65]
    pgm = map_to_pgm(data, 3, 2)
    header, pixels = pgm[:11], np.frombuffer(pgm[11:], dtype=np.uint8).reshape(2, 3)
    assert header == b'P5\n3 2\n255\n'
    assert pixels.tolist() == [[205, 254, 0], [254, 0, 205]]

    MissionLog(str(tmp_path)).save_map('m1', data, 3, 2, 0.05, -2.5, -1.25)
    with open(tmp_path / 'm1' / 'map.pgm', 'rb') as f:
        assert f.read() == pgm
    assert map_yaml(0.05, -2.5, -1.25).splitlines()[:4] == [
        'image: map.pgm', 'mode: trinary', 'resolution: 0.05', 'origin: [-2.500, -1.250, 0.0]']
