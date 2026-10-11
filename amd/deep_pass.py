#!/usr/bin/env python3
"""deep_pass.py - re-read a finished mission with larger models, on the AMD Radeon PRO W7900 (ROCm).

    python amd/deep_pass.py missions/m1
    python amd/deep_pass.py missions/m1 --detector google/owlv2-base-patch16-ensemble
    python amd/deep_pass.py missions/m1 --detector google/owlvit-base-patch32     # the Jetson's model

During a mission the Jetson has 8 GB and a 15 Hz camera, so it runs the smallest OWL-ViT and names
plants from five species. This runs afterwards, on every bubble frame in the mission folder, with:

  - a larger detector (OWLv2 large by default; the W7900 has 48 GB);
  - the same BioCLIP and the same five-species list, so pins compare one to one with the live ones;
  - a second opinion from a longer list of Central Florida plants (florida_species.py), kept
    beside the pin as `wide_top3`, never replacing its label;
  - the BioCLIP embedding of every crop (512 numbers, for the dashboard's similar-plant search).

Out, inside the mission folder (the live pins.jsonl is never touched):
    pins_deep.jsonl     same keys as /survey/pins, plus range, detector_score, wide_top3, wide_agrees,
                        embedding, sightings
    crops_deep/<pin_id>.jpg
    deep_report.json    device, timings, frames per second, and a comparison with the live pins

Pin ids are <mission>-d01, d02, ... so they cannot collide with the live <mission>-p07.

The mission folder has no LiDAR scans, so distance comes from the saved map: a ray from the bubble
centre along the plant's bearing, to the first occupied cell. Without a map, or with no wall in
range, --default-range is used and the pin is marked "range": "default".

The same code runs on ROCm, CUDA and CPU (PyTorch reports a ROCm GPU as `cuda`). Setup: amd/setup_amd.sh.
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
# the live perception code, reused as plain Python (none of these modules import ROS)
sys.path.insert(0, os.path.join(HERE, '..', 'ros2_ws', 'src', 'scout_perception'))
sys.path.insert(0, HERE)


# ---------- plain geometry and bookkeeping (numpy only, unit-tested) ----------

def load_map(mission_dir):
    """map.pgm + map.yaml -> (grid [rows, cols] uint8, resolution, origin_x, origin_y), or None."""
    pgm, yaml = os.path.join(mission_dir, 'map.pgm'), os.path.join(mission_dir, 'map.yaml')
    if not (os.path.exists(pgm) and os.path.exists(yaml)):
        return None
    from PIL import Image
    resolution, origin = 0.05, [0.0, 0.0]
    with open(yaml) as f:
        for line in f:
            key, _, value = line.partition(':')
            if key.strip() == 'resolution':
                resolution = float(value)
            elif key.strip() == 'origin':
                origin = [float(v) for v in value.strip().strip('[]').split(',')]
    return np.array(Image.open(pgm).convert('L')), resolution, origin[0], origin[1]


def raycast(grid_map, x, y, bearing, max_range=4.0, occupied_below=100):
    """Distance from (x, y) along `bearing` to the first occupied cell, or None within max_range.

    map_saver images: occupied 0, unknown 205, free 254; image row 0 is the largest y.
    """
    grid, resolution, ox, oy = grid_map
    rows, cols = grid.shape
    step = resolution / 2
    for i in range(1, int(max_range / step) + 1):
        d = i * step
        col = int((x + d * math.cos(bearing) - ox) / resolution)
        row = rows - 1 - int((y + d * math.sin(bearing) - oy) / resolution)
        if not (0 <= col < cols and 0 <= row < rows):
            return None
        if grid[row, col] < occupied_below:
            return d
    return None


def merge_sightings(sightings, radius=0.5, same_bearing=0.2):
    """The same plant is seen in several boxes, frames and bubbles. Two sightings with the same label
    become one pin when they are within `radius` metres, or when they are from the same bubble and
    within `same_bearing` radians: one spin cannot tell two plants apart along one line of sight.
    The most confident sighting is kept; `sightings` counts the rest."""
    def turn(a, b):
        return abs(math.atan2(math.sin(a - b), math.cos(a - b)))

    pins = []
    for s in sorted(sightings, key=lambda s: -s['confidence']):
        for p in pins:
            if p['label'] != s['label']:
                continue
            near = math.hypot(p['x'] - s['x'], p['y'] - s['y']) <= radius
            in_line = (p.get('bubble_id') is not None and p.get('bubble_id') == s.get('bubble_id')
                       and turn(p.get('yaw', 0.0), s.get('yaw', 0.0)) <= same_bearing)
            if near or in_line:
                p['sightings'] += 1
                break
        else:
            pins.append(dict(s, sightings=1))
    return pins


def compare(live, deep, radius=0.5):
    """Match pins by the dashboard's rule (same label within `radius` m). Each live pin is used once."""
    unused = list(live)
    confirmed, new = [], []
    for d in deep:
        match = next((p for p in unused if p['label'] == d['label']
                      and math.hypot(p['x'] - d['x'], p['y'] - d['y']) <= radius), None)
        if match is None:
            new.append(d['pin_id'])
        else:
            unused.remove(match)
            confirmed.append([match['pin_id'], d['pin_id']])
    return {'live_pins': len(live), 'deep_pins': len(deep), 'confirmed': confirmed,
            'only_deep': new, 'only_live': [p['pin_id'] for p in unused]}


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def device_info(torch):
    if not torch.cuda.is_available():
        return {'device': 'cpu', 'backend': 'CPU', 'torch': torch.__version__}
    hip = getattr(torch.version, 'hip', None)
    return {'device': torch.cuda.get_device_name(0),
            'backend': f'ROCm (HIP {hip})' if hip else f'CUDA {torch.version.cuda}',
            'memory_gb': round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1),
            'torch': torch.__version__}


# ---------- models ----------

class Owl:
    """OWL-ViT or OWLv2 through transformers. The prompts are tokenised once."""

    def __init__(self, torch, name, prompts, threshold, max_boxes, device, dtype):
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        self.torch, self.prompts, self.threshold, self.max_boxes = torch, prompts, threshold, max_boxes
        self.device, self.dtype = device, dtype
        self.processor = AutoProcessor.from_pretrained(name)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(name).to(device, dtype).eval()
        self.text = self.processor(text=[prompts], return_tensors='pt').to(device)
        # OWLv2 pads the image to a square before resizing, so its boxes are fractions of that square
        self.square = self.model.config.model_type == 'owlv2'

    def detect(self, rgb):
        from scout_perception.backends import owl_boxes
        h, w = rgb.shape[:2]
        pixels = self.processor(images=rgb, return_tensors='pt')['pixel_values'].to(self.device, self.dtype)
        with self.torch.no_grad():
            out = self.model(pixel_values=pixels, input_ids=self.text['input_ids'],
                             attention_mask=self.text['attention_mask'])
        side_w, side_h = (max(w, h), max(w, h)) if self.square else (w, h)
        boxes = owl_boxes(self.torch, out.logits[0], out.pred_boxes[0], side_w, side_h,
                          self.prompts, self.threshold, self.max_boxes)
        for b in boxes:
            x1, y1, x2, y2 = b['xyxy']
            b['xyxy'] = [min(x1, w), min(y1, h), min(x2, w), min(y2, h)]
        return boxes


def wide_text(torch, species, model_name):
    """Text embeddings for the long Florida list, with the same BioCLIP the pins use."""
    import open_clip
    from florida_species import FLORIDA_SPECIES
    from scout_perception.species_labels import NOT_PLANTS, prompt
    tokens = open_clip.get_tokenizer(model_name)(
        [prompt(label, sci) for label, _, sci in FLORIDA_SPECIES] + NOT_PLANTS)
    with torch.no_grad():
        text = species.model.encode_text(tokens.to(species.device)).float()
    return FLORIDA_SPECIES, text / text.norm(dim=-1, keepdim=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mission', help='mission folder, e.g. missions/m1')
    ap.add_argument('--detector', default='google/owlv2-large-patch14-ensemble')
    ap.add_argument('--threshold', type=float, default=0.1, help='detector score threshold')
    ap.add_argument('--min-confidence', type=float, default=0.5, help='species confidence, as on the Jetson')
    ap.add_argument('--max-boxes', type=int, default=8, help='boxes per frame (the Jetson keeps 3)')
    ap.add_argument('--min-box-px', type=int, default=24)
    ap.add_argument('--merge-radius', type=float, default=0.5)
    ap.add_argument('--max-range', type=float, default=4.0)
    ap.add_argument('--default-range', type=float, default=1.5)
    ap.add_argument('--half', action='store_true', help='half precision (default: full; the W7900 has the memory)')
    ap.add_argument('--no-embeddings', action='store_true', help='leave the 512 numbers out of pins_deep.jsonl')
    args = ap.parse_args()

    import torch
    from PIL import Image
    from scout_perception.backends import DEFAULT_PROMPTS
    from scout_perception.geometry import pixel_to_bearing, wrap
    from scout_perception.species_backends import BioClipSpecies
    from scout_perception.species_labels import SPECIES

    mission_dir = args.mission.rstrip('/')
    bubbles = read_jsonl(os.path.join(mission_dir, 'bubbles.jsonl'))
    if not bubbles:
        sys.exit(f'no bubbles in {mission_dir}/bubbles.jsonl')
    mission_id = bubbles[0].get('mission_id') or os.path.basename(mission_dir)
    grid_map = load_map(mission_dir)

    info = device_info(torch)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    dtype = torch.float16 if (args.half and device == 'cuda') else torch.float32
    print(f'device: {info["device"]} | {info["backend"]} | torch {info["torch"]} | '
          f'{"half" if dtype == torch.float16 else "full"} precision')

    t0 = time.perf_counter()
    owl = Owl(torch, args.detector, DEFAULT_PROMPTS, args.threshold, args.max_boxes, device, dtype)
    species = BioClipSpecies()
    if dtype == torch.float32:
        species.model, species.dtype = species.model.float(), torch.float32
    wide, wide_emb = wide_text(torch, species, 'hf-hub:imageomics/bioclip')
    load_s = time.perf_counter() - t0
    print(f'models loaded in {load_s:.1f} s: {args.detector} + BioCLIP, '
          f'{len(SPECIES)} habitat species, {len(wide)} in the wide list')

    def sync():
        if device == 'cuda':
            torch.cuda.synchronize()

    sightings, frames, boxes_seen = [], 0, 0
    detect_s = species_s = 0.0
    for b in bubbles:
        hfov = float(b.get('hfov', 1.22))
        for fr in b.get('frames', []):
            path = os.path.join(mission_dir, 'frames', f'{b["bubble_id"]}_{fr["index"]}.jpg')
            if not os.path.exists(path):
                continue
            rgb = np.array(Image.open(path).convert('RGB'))
            height, width = rgb.shape[:2]
            t = time.perf_counter()
            boxes = owl.detect(rgb)
            sync()
            if frames:                      # the first frame includes one-time GPU setup; not timed
                detect_s += time.perf_counter() - t
            frames += 1
            for box in boxes:
                x1, y1, x2, y2 = box['xyxy']
                if x2 - x1 < args.min_box_px or y2 - y1 < args.min_box_px:
                    continue
                boxes_seen += 1
                t = time.perf_counter()
                label, invasive, confidence, embedding = species.classify(rgb[y1:y2, x1:x2, ::-1])
                sync()
                species_s += time.perf_counter() - t
                if label is None or confidence < args.min_confidence:
                    continue
                emb = torch.tensor(embedding, device=wide_emb.device)
                probs = (species.scale * emb @ wide_emb.T).softmax(dim=-1)
                top = probs.topk(3)
                wide_top3 = [{'label': wide[i][0] if i < len(wide) else 'not a plant',
                              'invasive': bool(wide[i][1]) if i < len(wide) else False,
                              'confidence': round(float(p), 2)}
                             for p, i in zip(top.values.tolist(), top.indices.tolist())]
                bearing = wrap(float(fr['yaw']) + pixel_to_bearing((x1 + x2) / 2, width, hfov))
                distance = raycast(grid_map, b['x'], b['y'], bearing, args.max_range) if grid_map else None
                d = distance if distance is not None else args.default_range
                sightings.append({
                    'mission_id': mission_id, 'bubble_id': b['bubble_id'], 'label': label,
                    'invasive': bool(invasive), 'confidence': round(confidence, 2), 'yaw': round(bearing, 2),
                    'x': round(b['x'] + d * math.cos(bearing), 2), 'y': round(b['y'] + d * math.sin(bearing), 2),
                    'range': 'map' if distance is not None else 'default',
                    'detector_score': box['score'], 'wide_top3': wide_top3,
                    # false when the longer list prefers another plant: a pin worth a second look
                    'wide_agrees': wide_top3[0]['label'] == label, 'embedding': embedding,
                    '_crop': (path, (x1, y1, x2, y2))})
    if not frames:
        sys.exit(f'no frames found in {mission_dir}/frames (expected <bubble_id>_<index>.jpg)')

    pins = merge_sightings(sightings, args.merge_radius)
    pins.sort(key=lambda p: (p['bubble_id'], -p['confidence']))
    crops = os.path.join(mission_dir, 'crops_deep')
    os.makedirs(crops, exist_ok=True)
    for n, pin in enumerate(pins, 1):
        pin['pin_id'] = f'{mission_id}-d{n:02d}'
        pin['crop'] = f'{pin["pin_id"]}.jpg'
        path, (x1, y1, x2, y2) = pin.pop('_crop')
        Image.open(path).convert('RGB').crop((x1, y1, x2, y2)).save(os.path.join(crops, pin['crop']), quality=92)
        if args.no_embeddings:
            pin.pop('embedding')
    order = ['pin_id', 'mission_id', 'bubble_id', 'label', 'invasive', 'confidence', 'yaw', 'x', 'y', 'crop']
    with open(os.path.join(mission_dir, 'pins_deep.jsonl'), 'w') as f:
        for pin in pins:
            f.write(json.dumps({**{k: pin[k] for k in order}, **{k: v for k, v in pin.items() if k not in order}}) + '\n')

    timed = max(frames - 1, 1)
    report = {
        **info, 'mission_id': mission_id, 'detector': args.detector, 'species_model': 'imageomics/bioclip',
        'precision': 'half' if dtype == torch.float16 else 'full',
        'bubbles': len(bubbles), 'frames': frames, 'boxes_classified': boxes_seen,
        'sightings': len(sightings), 'pins': len(pins),
        'model_load_s': round(load_s, 1),
        'detector_ms_per_frame': round(1000 * detect_s / timed, 1),
        'detector_frames_per_s': round(timed / detect_s, 1) if detect_s else None,
        'species_ms_per_crop': round(1000 * species_s / boxes_seen, 1) if boxes_seen else None,
        'by_species': {label: sum(p['label'] == label for p in pins) for label, _, _ in SPECIES},
        'invasive_pins': sum(p['invasive'] for p in pins),
        'pins_located_from_map': sum(p['range'] == 'map' for p in pins),
        'pins_wide_list_disagrees': [p['pin_id'] for p in pins if not p['wide_agrees']],
        'vs_live': compare(read_jsonl(os.path.join(mission_dir, 'pins.jsonl')), pins, args.merge_radius),
    }
    if device == 'cuda':
        report['peak_gpu_memory_gb'] = round(torch.cuda.max_memory_allocated() / 2**30, 2)
    with open(os.path.join(mission_dir, 'deep_report.json'), 'w') as f:
        json.dump(report, f, indent=1)

    v = report['vs_live']
    print(f'{frames} frames in {len(bubbles)} bubbles: detector {report["detector_ms_per_frame"]} ms per frame '
          f'({report["detector_frames_per_s"]} per second), species {report["species_ms_per_crop"]} ms per crop')
    print(f'{len(pins)} pins from {len(sightings)} sightings ({report["invasive_pins"]} invasive). '
          f'Live run: {v["live_pins"]} pins; {len(v["confirmed"])} confirmed, '
          f'{len(v["only_deep"])} found only here, {len(v["only_live"])} only live')
    for pin in pins:
        print(f'  {pin["pin_id"]}  {pin["label"]:18s} conf {pin["confidence"]:.2f}  ({pin["x"]:.2f}, {pin["y"]:.2f}) '
              f'{pin["range"]:7s} seen {pin["sightings"]}x'
              + ('' if pin['wide_agrees'] else f'  (wide list says {pin["wide_top3"][0]["label"]})'))
    print(f'wrote {mission_dir}/pins_deep.jsonl, crops_deep/, deep_report.json')


if __name__ == '__main__':
    main()
