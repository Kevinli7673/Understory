# dashboard

`sync.py` (mission folder → HF Hub + Neon) and the Streamlit dashboard for land managers.

```bash
python3 -m venv dashboard/.venv && dashboard/.venv/bin/pip install -r dashboard/requirements.txt
dashboard/.venv/bin/streamlit run dashboard/app.py          # http://localhost:8501
dashboard/.venv/bin/python -m pytest dashboard/tests -q
dashboard/run.sh                                            # serve it to the network: http://<this machine's IP>:8501
dashboard/run.sh --stop
```

If `python3 -m venv` fails with "ensurepip is not available" (the Jetson, no sudo): `python3 -m venv --without-pip
dashboard/.venv`, download `https://bootstrap.pypa.io/get-pip.py`, run it with `dashboard/.venv/bin/python`, then the
`pip install` above.

## Data source

- **Mission folders** (always available, works offline): `MISSIONS_DIR`, else `missions/`, else
  `fake_data/missions/`. This is the "venue internet" fallback: keep the pre-synced Saturday-night
  folders on the laptop.
- **Neon**: shown when `DATABASE_URL` is in `.env`. If Neon can't be reached the app drops back to the folders.
- **Hugging Face**: shown when `HF_DATASET_REPO` is in `.env` (`HF_TOKEN` too if the dataset is private). The app
  downloads the dataset into `~/.cache/understory/hf_missions/` (`HF_MISSIONS_CACHE` to change it) and reads it like
  mission folders, so every tab works without Neon. Only changed files are fetched again ("Download again" in the
  sidebar, or after 5 minutes). With no internet it shows the last download.

## Pages

| Tab | What |
| --- | --- |
| Survey | Counts, floor plan (`map.pgm` placed by `map.yaml`) with pins, bubbles and the robot path; pins per species; panorama or frame ring per bubble; pin table with crops |
| Sensors | Per-sensor heat map (mean per grid cell) over the floor plan, plus the value over time. Missing sensors are skipped, not zero |
| Before / after | Same label within 0.5 m = same plant. Headline "7 invasive plants found → 1 remaining", per-species table, map of removed / still there / new |
| Similar plants | pgvector `embedding <-> $1 limit 12` (or numpy on folders). Pins without an embedding fall back to the same species |

The sidebar "Pins from" filter switches between live (Jetson) pins and `pins_deep.jsonl` from the AMD deep pass.

## sync.py

```bash
dashboard/.venv/bin/python dashboard/sync.py missions/m1 missions/m2            # HF + Neon
dashboard/.venv/bin/python dashboard/sync.py missions/m1 --no-hf                # Neon only
dashboard/.venv/bin/python dashboard/sync.py missions/m1                        # no DATABASE_URL in .env: HF only
dashboard/.venv/bin/python dashboard/sync.py fake_data/missions/m1 --dry-run    # just read and count
```

`.env` (never committed): `DATABASE_URL=postgresql://...neon.tech/...?sslmode=require`, `HF_TOKEN=hf_...`,
`HF_DATASET_REPO=<org>/understory-missions`.

- The dataset is created private unless `--public` is given (frames show whoever stood near the robot). The image
  URLs written to Neon only open in a browser for a public dataset; the Hugging Face data source works either way.
- Creates the schema (`schema.sql`: `missions`, `bubbles`, `pins` with `embedding vector(512)`, `readings`)
  on every run; all writes are upserts, so re-running is safe.
- Uploads `frames/`, `crops/`, `crops_deep/`, the JSONL files, `map.pgm`/`map.yaml`, plus a `map.png` that
  browsers can show, to `<repo>/<mission_id>/` in the dataset.
- Embeddings come from the pin's `embedding` key (localizer with `publish_embedding:=true`, or
  `pins_deep.jsonl`). `--embed` fills the rest with BioCLIP on the crops (needs `open_clip_torch`).
  Re-syncing without an embedding keeps the one already in Neon.
- Readings use `(mission_id, t)` as the key.
