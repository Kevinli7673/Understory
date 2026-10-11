"""Tests for the plain-Python parts of deep_pass.py (numpy only, no models).  python -m pytest amd/tests"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from deep_pass import compare, merge_sightings, raycast  # noqa: E402
from florida_species import FLORIDA_SPECIES  # noqa: E402


def room():
    """4 m x 4 m of free space with walls on the outer cells. 5 cm cells, origin (-2, -2)."""
    grid = np.full((80, 80), 254, dtype=np.uint8)
    grid[0, :] = grid[-1, :] = grid[:, 0] = grid[:, -1] = 0
    return grid, 0.05, -2.0, -2.0


def test_raycast_hits_each_wall():
    for bearing in (0.0, math.pi / 2, math.pi, -math.pi / 2):
        assert abs(raycast(room(), 0.0, 0.0, bearing) - 1.95) < 0.06


def test_raycast_row_zero_is_the_far_side_in_y():
    grid, res, ox, oy = room()
    grid[10, 40] = 0                 # row 10 from the top = high y, straight "left" of the centre
    # y of that cell: (80 - 1 - 10) * 0.05 - 2 = 1.45
    assert abs(raycast((grid, res, ox, oy), 0.0, 0.0, math.pi / 2) - 1.45) < 0.06


def test_raycast_gives_up():
    assert raycast(room(), 0.0, 0.0, 0.0, max_range=1.0) is None
    grid = np.full((80, 80), 205, dtype=np.uint8)     # all unknown, no walls
    assert raycast((grid, 0.05, -2.0, -2.0), 0.0, 0.0, 0.3) is None


def sighting(label, x, y, confidence):
    return {'label': label, 'x': x, 'y': y, 'confidence': confidence}


def test_merge_keeps_the_most_confident_and_counts():
    pins = merge_sightings([sighting('cogongrass', 1.0, 1.0, 0.6), sighting('cogongrass', 1.2, 1.1, 0.9),
                            sighting('cogongrass', 3.0, 1.0, 0.7), sighting('air potato', 1.0, 1.0, 0.8)])
    assert [(p['label'], p['confidence'], p['sightings']) for p in pins] == [
        ('cogongrass', 0.9, 2), ('air potato', 0.8, 1), ('cogongrass', 0.7, 1)]


def test_merge_same_line_of_sight_in_one_bubble():
    a = dict(sighting('air potato', 3.5, 0.0, 0.9), bubble_id='m1-b01', yaw=0.0)
    b = dict(sighting('air potato', 1.5, 0.1, 0.8), bubble_id='m1-b01', yaw=0.07)    # same direction, other range
    c = dict(sighting('air potato', 1.5, 0.1, 0.7), bubble_id='m1-b02', yaw=0.07)    # another bubble, 2 m from the kept pin: its own pin
    d = dict(sighting('air potato', 0.0, 1.5, 0.6), bubble_id='m1-b01', yaw=1.57)    # another direction: its own pin
    pins = merge_sightings([a, b, c, d])
    assert [(p['confidence'], p['sightings']) for p in pins] == [(0.9, 2), (0.7, 1), (0.6, 1)]


def test_compare_uses_each_live_pin_once():
    live = [dict(sighting('cogongrass', 1.0, 1.0, 0.8), pin_id='m1-p01'),
            dict(sighting('wild coffee', 0.0, 0.0, 0.8), pin_id='m1-p02')]
    deep = [dict(sighting('cogongrass', 1.1, 1.0, 0.9), pin_id='m1-d01'),
            dict(sighting('cogongrass', 1.2, 1.0, 0.7), pin_id='m1-d02'),
            dict(sighting('air potato', 0.0, 0.0, 0.9), pin_id='m1-d03')]
    result = compare(live, deep)
    assert result['confirmed'] == [['m1-p01', 'm1-d01']]
    assert result['only_deep'] == ['m1-d02', 'm1-d03']
    assert result['only_live'] == ['m1-p02']


def test_wide_list_starts_with_the_habitat_list_and_has_no_repeats():
    names = [sci for _, _, sci in FLORIDA_SPECIES]
    assert len(set(names)) == len(names)
    assert names[:5] == ['Schinus terebinthifolia', 'Dioscorea bulbifera', 'Imperata cylindrica',
                         'Serenoa repens', 'Psychotria nervosa']
