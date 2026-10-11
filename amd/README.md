# AMD deep pass (ROCm, Radeon PRO W7900)

The second half of "live on the edge, deep in the cloud". During a mission the Jetson (8 GB) runs the
smallest OWL-ViT so it can keep up with the camera. Afterwards the mission folder goes to the Radeon
Cloud W7900 (48 GB), where `deep_pass.py` re-reads every bubble frame with a larger detector and writes
a second set of pins beside the live ones. `splat/` (Kevin) builds the 3D model from the same folder.

```bash
# on the W7900 box, in the repo
bash amd/setup_amd.sh                       # once. Never reinstalls torch
python amd/deep_pass.py missions/m1         # OWLv2 large + BioCLIP on every frame
bash splat/run.sh missions/m1               # the 3D model (see splat/README.md)
```

Getting a mission there: the logger node writes `~/fetch_ws/missions/<id>/` on the machine that runs
mapping (the Jetson). Copy that folder to the box, for example
`rsync -a ~/fetch_ws/missions/m1 root@<box>:Understory/missions/`.

## What comes out

In the mission folder; the live `pins.jsonl` and `crops/` are never changed.

| File | What it is |
| --- | --- |
| `pins_deep.jsonl` | One pin per plant, same keys as `/survey/pins`, ids `m1-d01`, `m1-d02`, ... Extra keys: `range` (`map` or `default`), `detector_score`, `sightings`, `wide_top3`, `wide_agrees`, `embedding` (512 numbers; `--no-embeddings` leaves it out) |
| `crops_deep/<pin_id>.jpg` | The crop each pin was named from |
| `deep_report.json` | GPU name, ROCm or CUDA, milliseconds per frame, frames per second, peak GPU memory, pins per species, and `vs_live`: which live pins the deep pass confirmed, which it found that the robot missed, which only the robot found |

`deep_report.json` holds the numbers for the pitch: the Jetson's TensorRT detector is 19 ms per frame
(HANDOFF.md, session 9); put the W7900's `detector_ms_per_frame` for the large model next to it.

## How it decides

- **Detector:** `google/owlv2-large-patch14-ensemble` by default, with the same prompts as the Jetson.
  `--detector google/owlv2-base-patch16-ensemble` is smaller; `--detector google/owlvit-base-patch32`
  is the Jetson's own model, for a like-for-like speed number.
- **Species:** the same BioCLIP and the same five-species list as the live system (it imports
  `scout_perception` from this repo, so there is one list to edit), so labels compare one to one.
- **Second opinion:** each crop is also scored against 26 Central Florida plants (`florida_species.py`).
  That never changes the label. When its first choice differs, the pin gets `"wide_agrees": false`
  and is listed in the report as worth a second look.
- **Position:** the folder has no LiDAR scans, so distance is a ray through `map.pgm` from the bubble
  centre along the plant's bearing to the first wall. With no wall inside `--max-range` (4 m) it
  uses `--default-range` (1.5 m) and marks the pin `"range": "default"`. The camera's small offset from
  the robot's centre is ignored.
- **One plant, one pin:** sightings with the same label merge when they are within 0.5 m, or in the
  same bubble within 0.2 rad of each other.

## What was tested, and what was not

Tested Sat Oct 10 on the **Jetson's GPU (CUDA), not on ROCm**: PyTorch presents a ROCm GPU as `cuda`,
so the code path is the same, but nobody has run this on the W7900 yet. Input was one test bubble
made from the five reference plant photos, in the fake `m1` map.

| Detector | Species named correctly (of 5) | Other pins | Detector time on the Jetson |
| --- | --- | --- | --- |
| `owlvit-base-patch32` (the Jetson's) | 4: no pin for the wild coffee photo | 2, both flagged by the wide list | 226 ms per frame, full precision |
| `owlv2-base-patch16-ensemble` | 5 | 5, three flagged by the wide list | 1333 ms per frame |

`owlv2-large-patch14-ensemble`, the default, has **not been run anywhere**: it is the same code path
as the base model with a different name. If it fails on the box, use `--detector google/owlv2-base-patch16-ensemble`.
The extra pins are extra boxes on the same photo that BioCLIP named differently; a higher
`--min-confidence` (default 0.5, the Jetson's value) removes most of them. Five photos is a small test.

Unit tests (numpy only): `python -m pytest amd/tests`
