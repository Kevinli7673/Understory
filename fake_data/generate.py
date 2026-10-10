"""Generate fake mission folders matching the AGENTS.md contracts.

    python fake_data/generate.py

Writes fake_data/missions/m1 ("before": 7 invasives) and m2 ("after": 1 remaining),
each with bubbles.jsonl, pins.jsonl, readings.jsonl, frames/, crops/, map.pgm + map.yaml.
Deterministic (fixed seed), so re-running gives identical files. Needs Pillow.

The room matches ros2_ws/.../fake_world.py, shifted into the map frame (map origin =
robot start pose at world (1, 1)), so this map lines up with the nav sim.
"""
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / 'missions'
SEED = 7
T0 = 1791600000.0
AFTER_DAYS = 14

# --- world (map frame, meters) -------------------------------------------------
ROOM = (-2.0, -2.0, 6.0, 4.0)
BOXES = [(1.0, 1.0, 2.0, 1.6), (3.5, -0.5, 4.2, 0.4), (3.0, 2.5, 5.0, 3.0)]  # plant beds

RES = 0.05
MAP_ORIGIN = (-2.5, -2.5)
MAP_W, MAP_H = 180, 140  # 9 m x 7 m

BUBBLES = [(0.0, 0.0, True), (2.6, -1.2, True), (5.0, 1.2, False), (2.5, 2.0, True), (0.0, 3.0, True)]
N_FRAMES = 12
HFOV = 1.22  # rad, ~70 deg
FRAME_W, FRAME_H = 640, 480
PANO_W, PANO_H = 2048, 300

# (x, y, label, invasive). m1 sees all; m2 keeps natives + one cogongrass (moved a little).
PLANTS = [
    (1.0, 1.7, 'Brazilian pepper', True),
    (2.1, 1.0, 'Brazilian pepper', True),
    (3.4, -0.6, 'Air potato', True),
    (4.3, 0.2, 'Air potato', True),
    (3.2, 2.4, 'Cogongrass', True),
    (4.8, 3.1, 'Cogongrass', True),
    (-1.8, 3.5, 'Cogongrass', True),
    (5.8, -1.6, 'Saw palmetto', False),
    (0.5, -1.8, 'American beautyberry', False),
    (-1.7, 0.8, 'Coontie', False),
    (4.0, 2.4, 'Wild coffee', False),
]
SURVIVOR = 5  # index into PLANTS still present in "after"


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


# --- map ----------------------------------------------------------------------
def write_map(d):
    """Trinary map like map_saver_cli: 254 free, 0 occupied, 205 unknown. Row 0 = top (max y)."""
    img = Image.new('L', (MAP_W, MAP_H), 205)
    px = img.load()

    def to_px(x, y):
        return int((x - MAP_ORIGIN[0]) / RES), MAP_H - 1 - int((y - MAP_ORIGIN[1]) / RES)

    x0, y0 = to_px(ROOM[0], ROOM[3])
    x1, y1 = to_px(ROOM[2], ROOM[1])
    for v in range(y0, y1 + 1):
        for u in range(x0, x1 + 1):
            px[u, v] = 0 if u - x0 < 2 or x1 - u < 2 or v - y0 < 2 or y1 - v < 2 else 254
    draw = ImageDraw.Draw(img)
    for bx0, by0, bx1, by1 in BOXES:
        a, b = to_px(bx0, by1), to_px(bx1, by0)
        draw.rectangle([a, b], fill=205, outline=0, width=2)
    img.save(d / 'map.pgm')
    (d / 'map.yaml').write_text(
        'image: map.pgm\nmode: trinary\n'
        f'resolution: {RES}\norigin: [{MAP_ORIGIN[0]}, {MAP_ORIGIN[1]}, 0.0]\n'
        'negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n')


# --- images -------------------------------------------------------------------
def frame_u(bearing, frame_yaw):
    """Horizontal position (0 = left edge, 1 = right) of a bearing in a frame, or None if outside.
    Yaw is CCW, so larger yaw is further LEFT."""
    d = wrap(bearing - frame_yaw)
    if abs(d) >= HFOV / 2:
        return None
    return 0.5 - math.tan(d) / (2 * math.tan(HFOV / 2))


def pano_u(bearing):
    """Pano convention (proposed, confirm with perception): center = yaw 0, left edge = +pi,
    right edge = -pi, i.e. u = (pi - yaw) / 2pi. Reads left-to-right like turning clockwise."""
    return (math.pi - wrap(bearing)) / (2 * math.pi)


def sky(w, h, hue):
    img = Image.new('RGB', (w, h))
    draw = ImageDraw.Draw(img)
    for v in range(h):
        k = v / h
        if k < 0.55:
            c = (int(90 + 60 * k), int(140 + 60 * k), int(200 - 40 * k))
        else:
            g = int(90 + 50 * (k - 0.55))
            c = (int(40 + hue * 30), g, 40)
        draw.line([(0, v), (w, v)], fill=c)
    return img


def mark(draw, u, w, h, pin):
    cx = int(u * w)
    bw, bh = int(h * 0.22), int(h * 0.35)
    color = (230, 40, 40) if pin['invasive'] else (60, 220, 90)
    draw.rectangle([cx - bw // 2, int(h * 0.5), cx + bw // 2, int(h * 0.5) + bh], outline=color, width=3)
    draw.text((cx - bw // 2, int(h * 0.5) - 18), pin['label'], fill=color, font=font(14))


def write_frame(d, bubble_id, index, yaw, pins):
    img = sky(FRAME_W, FRAME_H, index / N_FRAMES)
    draw = ImageDraw.Draw(img)
    # Centered: the bubble ring only shows the middle ~30 deg of each frame.
    draw.text((FRAME_W // 2, 30), f'{bubble_id} #{index}', fill='white', font=font(40), anchor='mt')
    draw.text((FRAME_W // 2, 80), f'yaw {math.degrees(yaw):.0f} deg', fill='white', font=font(28), anchor='mt')
    draw.line([(FRAME_W // 2, 0), (FRAME_W // 2, FRAME_H)], fill=(255, 255, 255), width=1)
    for p in pins:
        u = frame_u(p['yaw'], yaw)
        if u is not None:
            mark(draw, u, FRAME_W, FRAME_H, p)
    img.save(d / 'frames' / f'{bubble_id}_{index}.jpg', quality=70)


def write_pano(d, bubble_id, pins):
    img = sky(PANO_W, PANO_H, 0.3)
    draw = ImageDraw.Draw(img)
    for deg in range(180, -180, -30):
        u = int(pano_u(math.radians(deg)) * PANO_W)
        draw.line([(u, 0), (u, 40)], fill='white', width=2)
        draw.text((u + 4, 4), f'{deg}', fill='white', font=font(22))
    draw.text((PANO_W // 2 - 80, 50), f'{bubble_id} pano', fill='white', font=font(28))
    for p in pins:
        mark(draw, pano_u(p['yaw']), PANO_W, PANO_H, p)
    img.save(d / 'frames' / f'{bubble_id}_pano.jpg', quality=70)


def write_crop(d, pin):
    color = (230, 40, 40) if pin['invasive'] else (60, 220, 90)
    img = Image.new('RGB', (224, 224), (50, 90, 45))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 223, 223], outline=color, width=8)
    draw.text((16, 90), pin['label'], fill='white', font=font(20))
    draw.text((16, 120), pin['pin_id'], fill='white', font=font(16))
    img.save(d / 'crops' / f"{pin['pin_id']}.jpg", quality=80)


# --- mission ------------------------------------------------------------------
def make_mission(mission_id, plants, t0, rng):
    d = OUT / mission_id
    (d / 'frames').mkdir(parents=True, exist_ok=True)
    (d / 'crops').mkdir(parents=True, exist_ok=True)
    write_map(d)

    # Each plant is pinned from its nearest bubble.
    def nearest(x, y):
        return min(range(len(BUBBLES)), key=lambda i: math.hypot(BUBBLES[i][0] - x, BUBBLES[i][1] - y))

    pins_by_bubble = {i: [] for i in range(len(BUBBLES))}
    for x, y, label, invasive in plants:
        bi = nearest(x, y)
        bx, by, _ = BUBBLES[bi]
        pins_by_bubble[bi].append({
            'mission_id': mission_id, 'bubble_id': f'{mission_id}-b{bi + 1:02d}',
            'label': label, 'invasive': invasive, 'confidence': round(rng.uniform(0.62, 0.95), 2),
            'yaw': round(math.atan2(y - by, x - bx), 3), 'x': round(x, 2), 'y': round(y, 2),
        })
    # Number pins in discovery order, like the real localizer.
    n = 0
    for bi in range(len(BUBBLES)):
        for p in pins_by_bubble[bi]:
            n += 1
            pid = f'{mission_id}-p{n:02d}'
            p_ordered = {'pin_id': pid, **p, 'crop': f'{pid}.jpg'}
            p.clear()
            p.update(p_ordered)

    bubbles, pins, readings = [], [], []
    t, px, py = t0, 0.0, 0.0

    def reading(x, y):
        # Wetter near plant beds; uv sensor sometimes missing, air_quality on every 3rd (omitted, not null).
        bed = min(math.hypot(x - (a + c) / 2, y - (b + e) / 2) for a, b, c, e in BOXES)
        r = {'mission_id': mission_id, 't': round(t, 2), 'x': round(x, 2), 'y': round(y, 2),
             'temp_c': round(24.0 + 0.3 * x + rng.gauss(0, 0.2), 1),
             'pressure_hpa': round(1013.2 + rng.gauss(0, 0.3), 1),
             'soil_moisture': int(520 - 90 * min(bed, 3) + rng.gauss(0, 10)),
             'light': int(340 - 20 * y + rng.gauss(0, 8)), 'sound': int(48 + rng.gauss(0, 3))}
        if rng.random() > 0.2:
            r['uv'] = round(max(0.0, 0.2 + rng.gauss(0, 0.05)), 2)
        if len(readings) % 3 == 0:
            r['air_quality'] = int(112 + rng.gauss(0, 6))
        readings.append(r)

    for bi, (bx, by, stitched) in enumerate(BUBBLES):
        # Drive to the bubble at 0.2 m/s, one reading per second.
        dist = math.hypot(bx - px, by - py)
        steps = max(1, int(dist / 0.2))
        for s in range(1, steps + 1):
            t += 1.0
            reading(px + (bx - px) * s / steps, py + (by - py) * s / steps)
        px, py = bx, by

        bubble_id = f'{mission_id}-b{bi + 1:02d}'
        frames = []
        for i in range(N_FRAMES):
            yaw = round(wrap(i * 2 * math.pi / N_FRAMES), 3)
            frames.append({'index': i, 'yaw': yaw})
            write_frame(d, bubble_id, i, yaw, pins_by_bubble[bi])
            t += 2.0
            if i % 3 == 0:
                reading(bx, by)
        if stitched:
            write_pano(d, bubble_id, pins_by_bubble[bi])
        bubbles.append({'bubble_id': bubble_id, 'mission_id': mission_id, 't': round(t, 2),
                        'x': bx, 'y': by, 'stitched': stitched, 'frames': frames, 'hfov': HFOV})
        for p in pins_by_bubble[bi]:
            write_crop(d, p)
            pins.append(p)

    for name, rows in (('bubbles', bubbles), ('pins', pins), ('readings', readings)):
        with open(d / f'{name}.jsonl', 'w', newline='\n') as f:
            for row in rows:
                f.write(json.dumps(row) + '\n')
    inv = sum(p['invasive'] for p in pins)
    print(f'{mission_id}: {len(bubbles)} bubbles, {len(pins)} pins ({inv} invasive), {len(readings)} readings')


def main():
    rng = random.Random(SEED)
    make_mission('m1', PLANTS, T0, rng)
    after = [p for i, p in enumerate(PLANTS) if not p[3] or i == SURVIVOR]
    after = [(x + 0.15, y - 0.1, l, inv) if inv else (x, y, l, inv) for x, y, l, inv in after]
    make_mission('m2', after, T0 + AFTER_DAYS * 86400, rng)


if __name__ == '__main__':
    main()
