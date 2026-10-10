# fake_data

Fake mission folders in the exact `missions/<mission_id>/` layout from AGENTS.md, so the Quest app,
logger, `sync.py` and dashboard can all be built before the robot works.

```
python fake_data/generate.py     # needs Pillow; deterministic, safe to re-run
```

| Mission | What | Pins |
| --- | --- | --- |
| `m1` | "before" survey | 11 (7 invasive: Brazilian pepper ×2, air potato ×2, cogongrass ×3) |
| `m2` | "after", 14 days later | 5 (1 invasive cogongrass left, moved ~0.2 m to exercise the 0.5 m match) |

- Room and plant beds match `ros2_ws/src/understory_nav/understory_nav/fake_world.py`, in the map frame
  (map origin = robot start at world (1, 1)), so `map.pgm` lines up with the nav sim.
- 5 bubbles × 12 frames. `m*-b03` is `stitched: false` (no pano) to exercise the unstitched ring fallback.
- Frames are labeled with bubble, index and yaw, and draw a box where each pin should appear.
  If a pin's box isn't where Unity puts the pin, the yaw/coordinate math is wrong somewhere.
- Readings omit `uv` on ~20% of lines and `air_quality` on 2 of 3, to test "missing sensors are omitted".

**Open question for perception:** the pano image convention isn't in the contract yet. These fakes use
center = yaw 0, left edge = +π, right edge = −π (u = (π − yaw) / 2π, left-to-right = turning clockwise).
