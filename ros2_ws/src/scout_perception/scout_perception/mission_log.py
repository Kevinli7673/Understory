"""Mission folder writer. Plain Python (no ROS imports) so it can be unit-tested.

Writes the layout in AGENTS.md, which the splat pipeline, the AMD deep pass and sync.py read:

    missions/<mission_id>/
      bubbles.jsonl  pins.jsonl  readings.jsonl
      frames/<bubble_id>_<index>.jpg   frames/<bubble_id>_pano.jpg
      crops/<pin_id>.jpg               (written by the localizer, not here)
      map.pgm + map.yaml

Bubbles and pins are kept one line per id: a bubble is sent again when its pano is stitched, and
after a restart the same ids can arrive twice. Readings are appended.
"""
import json
import os

import numpy as np


def mission_of(item_id):
    """'m1-b03' or 'm1-p07' -> 'm1'. Mission ids may contain dashes; the last part is the item."""
    return item_id.rsplit('-', 1)[0] if '-' in item_id else item_id


def frame_file(frame_id):
    """'m1-b03/4' -> ('m1', 'm1-b03_4.jpg'). None if the frame_id is not '<bubble_id>/<index or pano>'."""
    bubble_id, slash, index = frame_id.partition('/')
    if not slash or not bubble_id or not (index == 'pano' or index.isdigit()):
        return None
    return mission_of(bubble_id), f'{bubble_id}_{index}.jpg'


def map_to_pgm(data, width, height):
    """OccupancyGrid data (-1 unknown, 0..100) -> PGM bytes, the way nav2's map_saver writes them:
    occupied 0, free 254, unknown 205, and the top image row is the largest y."""
    grid = np.asarray(data, dtype=np.int16).reshape(height, width)
    image = np.full((height, width), 205, dtype=np.uint8)
    image[(grid >= 0) & (grid <= 25)] = 254
    image[grid >= 65] = 0
    return f'P5\n{width} {height}\n255\n'.encode('ascii') + np.flipud(image).tobytes()


def map_yaml(resolution, origin_x, origin_y):
    return (f'image: map.pgm\nmode: trinary\nresolution: {resolution:.4g}\n'
            f'origin: [{origin_x:.3f}, {origin_y:.3f}, 0.0]\nnegate: 0\n'
            'occupied_thresh: 0.65\nfree_thresh: 0.25\n')


class MissionLog:
    def __init__(self, root):
        self.root = root
        self.tables = {}      # (mission_id, 'bubbles' | 'pins') -> {id: dict}, in arrival order

    def folder(self, mission_id, *sub):
        path = os.path.join(self.root, mission_id, *sub)
        os.makedirs(path, exist_ok=True)
        return path

    def _table(self, mission_id, name, key):
        """Rows of bubbles.jsonl or pins.jsonl, read back from disk the first time."""
        if (mission_id, name) not in self.tables:
            rows = {}
            path = os.path.join(self.root, mission_id, f'{name}.jsonl')
            if os.path.exists(path):
                with open(path) as f:
                    for line in f:
                        try:
                            row = json.loads(line)
                            rows[row[key]] = row
                        except (ValueError, KeyError, TypeError):
                            pass
            self.tables[(mission_id, name)] = rows
        return self.tables[(mission_id, name)]

    def _upsert(self, name, key, row):
        mission_id = row.get('mission_id') or mission_of(row[key])
        rows = self._table(mission_id, name, key)
        rows[row[key]] = row
        path = os.path.join(self.folder(mission_id), f'{name}.jsonl')
        with open(path + '.tmp', 'w') as f:
            for r in rows.values():
                f.write(json.dumps(r) + '\n')
        os.replace(path + '.tmp', path)    # never leaves a half-written file behind
        return mission_id, len(rows)

    def bubble(self, row):
        return self._upsert('bubbles', 'bubble_id', row)

    def pin(self, row):
        return self._upsert('pins', 'pin_id', row)

    def reading(self, row):
        mission_id = row['mission_id']
        with open(os.path.join(self.folder(mission_id), 'readings.jsonl'), 'a') as f:
            f.write(json.dumps(row) + '\n')
        return mission_id

    def frame(self, frame_id, jpeg):
        """Returns the path written, or None if the frame_id is not a bubble frame."""
        where = frame_file(frame_id)
        if where is None:
            return None
        path = os.path.join(self.folder(where[0], 'frames'), where[1])
        with open(path, 'wb') as f:
            f.write(bytes(jpeg))
        return path

    def save_map(self, mission_id, data, width, height, resolution, origin_x, origin_y):
        folder = self.folder(mission_id)
        with open(os.path.join(folder, 'map.pgm.tmp'), 'wb') as f:
            f.write(map_to_pgm(data, width, height))
        os.replace(os.path.join(folder, 'map.pgm.tmp'), os.path.join(folder, 'map.pgm'))
        with open(os.path.join(folder, 'map.yaml'), 'w') as f:
            f.write(map_yaml(resolution, origin_x, origin_y))
