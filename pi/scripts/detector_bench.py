#!/usr/bin/env python3
"""Time one detector backend on the photos in a folder, as 640x480 camera frames. No ROS topics involved.

    docker exec scout-ai bash -c 'source /fetch_ws/install/setup.bash &&
      python3 /fetch_ws/src/Understory/pi/scripts/detector_bench.py owlvit_torch /fetch_ws/test_plants'
    ... detector_bench.py nanoowl_trt /fetch_ws/test_plants

Run one backend per process, with the live AI nodes stopped (~/scout_ai_up.sh --stop), and compare
the two outputs. "model" is the network alone; "whole frame" adds the resize before it and the box
filtering after it, which is what the detector node pays per frame.
"""
import glob
import statistics
import sys
import time

import cv2
import torch

from scout_perception.backends import DEFAULT_PROMPTS, make_backend

name, folder = sys.argv[1], sys.argv[2]
rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 20
frames = [cv2.resize(cv2.imread(p), (640, 480)) for p in sorted(glob.glob(f'{folder}/*.jpg'))]
backend = make_backend(name, DEFAULT_PROMPTS, 0.05)

# time the network alone by wrapping the call that runs it
model_ms = []
if name == 'nanoowl_trt':
    target, attr = backend.context, 'execute_async_v3'
else:
    target, attr = backend, 'model'
inner = getattr(target, attr)


def timed(*args, **kwargs):
    torch.cuda.synchronize()
    t = time.perf_counter()
    out = inner(*args, **kwargs)
    torch.cuda.synchronize()
    if name == 'nanoowl_trt':
        backend.stream.synchronize()
    model_ms.append((time.perf_counter() - t) * 1e3)
    return out


if name == 'nanoowl_trt':
    class Context:   # the TensorRT context has read-only attributes, so stand in front of it
        def __getattr__(self, key):
            return timed if key == attr else getattr(target, key)
    backend.context = Context()
else:
    backend.model = timed

for f in frames:   # warm up
    backend.detect(f)
model_ms.clear()
frame_ms = []
for _ in range(rounds):
    for f in frames:
        t = time.perf_counter()
        boxes = backend.detect(f)
        frame_ms.append((time.perf_counter() - t) * 1e3)
m, w = statistics.median(model_ms), statistics.median(frame_ms)
print(f'{name}: {len(frame_ms)} frames   model {m:.1f} ms ({1000 / m:.1f} per second)   '
      f'whole frame {w:.1f} ms ({1000 / w:.1f} per second)')
for path, f in zip(sorted(glob.glob(f'{folder}/*.jpg')), frames):
    print(' ', path.split('/')[-1], [(b['label'], b['score'], b['xyxy']) for b in backend.detect(f)])
