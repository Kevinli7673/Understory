"""Read mission folders and compare surveys. Shared by sync.py and the dashboard; no Streamlit or DB here.

Mission folder layout and JSON keys are the contracts in AGENTS.md.
"""
import json
import math
from pathlib import Path

import yaml

SENSOR_KEYS = ['temp_c', 'pressure_hpa', 'soil_moisture', 'light', 'uv', 'air_quality', 'sound']
MATCH_RADIUS_M = 0.5


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_map_meta(mission_dir):
    """map.yaml plus the PGM size. None if the mission has no saved map."""
    mission_dir = Path(mission_dir)
    yaml_path = mission_dir / 'map.yaml'
    if not yaml_path.exists():
        return None
    meta = yaml.safe_load(yaml_path.read_text())
    from PIL import Image
    with Image.open(mission_dir / meta['image']) as img:
        width, height = img.size
    return {
        'image': meta['image'],
        'resolution': float(meta['resolution']),
        'origin_x': float(meta['origin'][0]),
        'origin_y': float(meta['origin'][1]),
        'width': width,
        'height': height,
    }


def map_extent(meta):
    """(x_min, x_max, y_min, y_max) of the map image in the map frame, meters."""
    x0, y0 = meta['origin_x'], meta['origin_y']
    return x0, x0 + meta['width'] * meta['resolution'], y0, y0 + meta['height'] * meta['resolution']


def load_mission(mission_dir):
    """Everything in a mission folder as plain dicts. Deep-pass pins (AMD) are tagged source='deep'."""
    mission_dir = Path(mission_dir)
    pins = [dict(p, source='live') for p in read_jsonl(mission_dir / 'pins.jsonl')]
    pins += [dict(p, source='deep') for p in read_jsonl(mission_dir / 'pins_deep.jsonl')]
    bubbles = read_jsonl(mission_dir / 'bubbles.jsonl')
    readings = read_jsonl(mission_dir / 'readings.jsonl')
    times = [r['t'] for r in bubbles + readings if 't' in r]
    return {
        'mission_id': mission_dir.name,
        'dir': mission_dir,
        'bubbles': bubbles,
        'pins': pins,
        'readings': readings,
        'map': load_map_meta(mission_dir),
        'started_at': min(times) if times else None,
        'ended_at': max(times) if times else None,
    }


def match_pins(before, after, radius=MATCH_RADIUS_M):
    """Pair each 'after' pin with the closest unused 'before' pin of the same label within radius.

    Greedy on distance, one-to-one. Returns (pairs, removed, new) where pairs is [(before, after, dist)],
    removed = before pins with no match (gone), new = after pins with no match (appeared).
    """
    candidates = []
    for i, b in enumerate(before):
        for j, a in enumerate(after):
            if b['label'] != a['label']:
                continue
            d = math.hypot(b['x'] - a['x'], b['y'] - a['y'])
            if d <= radius:
                candidates.append((d, i, j))
    candidates.sort()
    used_b, used_a, pairs = set(), set(), []
    for d, i, j in candidates:
        if i in used_b or j in used_a:
            continue
        used_b.add(i)
        used_a.add(j)
        pairs.append((before[i], after[j], d))
    removed = [b for i, b in enumerate(before) if i not in used_b]
    new = [a for j, a in enumerate(after) if j not in used_a]
    return pairs, removed, new


def before_after_summary(before, after, invasive_only=True, radius=MATCH_RADIUS_M):
    """Per-label counts: found before, still there, removed, new. Plus totals for the headline."""
    if invasive_only:
        before = [p for p in before if p.get('invasive')]
        after = [p for p in after if p.get('invasive')]
    pairs, removed, new = match_pins(before, after, radius)
    labels = sorted({p['label'] for p in before + after})
    rows = []
    for label in labels:
        rows.append({
            'label': label,
            'found': sum(p['label'] == label for p in before),
            'remaining': sum(b['label'] == label for b, _, _ in pairs),
            'removed': sum(p['label'] == label for p in removed),
            'new': sum(p['label'] == label for p in new),
        })
    totals = {
        'found': len(before),
        'remaining': len(pairs),
        'removed': len(removed),
        'new': len(new),
    }
    return rows, totals, pairs, removed, new


def bin_readings(readings, key, cell_m=0.5):
    """Mean of one sensor per grid cell. Returns {(ix, iy): mean}; readings missing the key are skipped."""
    sums = {}
    for r in readings:
        if key not in r or 'x' not in r or 'y' not in r:
            continue
        cell = (math.floor(r['x'] / cell_m), math.floor(r['y'] / cell_m))
        s, n = sums.get(cell, (0.0, 0))
        sums[cell] = (s + r[key], n + 1)
    return {cell: s / n for cell, (s, n) in sums.items()}
