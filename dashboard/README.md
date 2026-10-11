# dashboard

`sync.py` (mission folder → HF Hub + Neon) and the Streamlit dashboard for land managers.

```bash
# keep the venv OUT of the repo if it lives in iCloud Drive (Desktop/Documents): syncing it stalls Python
python3 -m venv ~/.venvs/understory-dashboard
~/.venvs/understory-dashboard/bin/pip install -r dashboard/requirements.txt
# from the repo root, so .streamlit/config.toml (theme, fonts) is used
~/.venvs/understory-dashboard/bin/streamlit run dashboard/app.py      # http://localhost:8501
~/.venvs/understory-dashboard/bin/python -m pytest dashboard/tests -q
dashboard/run.sh                # dashboard :8501 + live relay :8770 + LiDAR bridge, for the whole network (uses dashboard/.venv)
dashboard/run.sh --stop
```

On the Jetson the venv is `dashboard/.venv` (git-ignored). If `python3 -m venv` fails there with "ensurepip is not
available" (no sudo): `python3 -m venv --without-pip dashboard/.venv`, download `https://bootstrap.pypa.io/get-pip.py`,
run it with `dashboard/.venv/bin/python`, then `dashboard/.venv/bin/pip install -r dashboard/requirements.txt`.

Theme: the Eucalyptus / Mist / Plaster / Soot / Moss palette, light or dark (follows the OS until someone uses the
small sidebar Dark / Light button, which pins it for the whole server and fades it in place),
Inter for text and Space Grotesk for headings and numbers (Google Fonts; falls back to system fonts offline). Chart colors are
in `PALETTES` in `app.py`; keep them in sync with `.streamlit/config.toml`.

## Data source

- **Mission folders** (always available, works offline): `MISSIONS_DIR`, else `missions/`, else
  `fake_data/missions/`. This is the "venue internet" fallback: keep the pre-synced Saturday-night
  folders on the laptop.
- **Neon**: shown when `DATABASE_URL` is in `.env`. If Neon can't be reached the app drops back to the folders.
- **Hugging Face**: shown when `HF_DATASET_REPO` is in `.env` (`HF_TOKEN` too if the dataset is private). The app
  downloads the dataset into `~/.cache/understory/hf_missions/` (`HF_MISSIONS_CACHE` to change it) and reads it like
  mission folders, so every tab works without Neon. Only changed files are fetched again ("Download again" in the
  sidebar, or after 5 minutes). With no internet it shows the last download.

## Page

One page: the live headset view across the top, then counts, the survey map (LiDAR map from `map.pgm`/`map.yaml`
with pins, bubbles, robot path and, when the robot is running, the live LiDAR scan and robot pose, refreshed
every second), pins per species and the pin table. The sidebar has the site description and the mission picker.
Sensor readings are still synced to Neon (`readings`) but not shown.

## Live: headset view + LiDAR

```
Quest (HeadsetStreamer.cs) --ws JPEG--> live_relay.py :8770 --ws--> dashboard browser (Headset view)
Jetson/Pi (scan_bridge.py) --HTTP POST /scan--> live_relay.py <--GET /scan-- dashboard (Survey map, 1 Hz)
```

On the Jetson `dashboard/run.sh` starts all of it: the dashboard, the relay, and `scan_bridge.py` inside the `scout`
ROS container. The Quest then needs the Jetson's address in `dashboard_ip.txt` (last block below). By hand, or on a laptop:

```bash
# laptop, next to the dashboard
~/.venvs/understory-dashboard/bin/python dashboard/live_relay.py              # port 8770, all interfaces
~/.venvs/understory-dashboard/bin/python dashboard/fake_live.py               # optional: fake headset + LiDAR

# robot side, inside the ROS container where mapping runs (stdlib only, nothing to install)
python3 /fetch_ws/src/Understory/dashboard/scan_bridge.py --relay http://<laptop-ip>:8770

# Quest: tell the app where the laptop is, then restart the app (no rebuild once HeadsetStreamer.cs is in a build)
echo <laptop-ip> > dashboard_ip.txt
adb push dashboard_ip.txt /sdcard/Android/data/com.knighthacks.understory/files/
```

- `Unity/Assets/Scripts/Util/HeadsetStreamer.cs` creates itself at startup; it is off until `dashboard_ip.txt`
  exists. By default a fixed camera in front of the table frames the LiDAR map and the robot camera screen, whatever the wearer looks at (inside a bubble it shows the wearer's view; `view = Head` on the component always does). 960×540, 55° vertical view, 8 fps, JPEG 70, newest frame only. Passthrough is not in the stream (the OS composites it),
  so virtual content shows over Soot.
- The browser connects to `ws://<dashboard host>:8770/ws/headset`; override with `LIVE_RELAY_WS`. The dashboard
  server reads scans from `LIVE_RELAY_URL` (default `http://localhost:8770`). `LIVE_FLIP=1` flips the image if
  it arrives upside down.
- Everything live is optional: without the relay the panels say offline and the rest works from mission folders.

## sync.py

```bash
~/.venvs/understory-dashboard/bin/python dashboard/sync.py missions/m1 missions/m2            # HF + Neon
~/.venvs/understory-dashboard/bin/python dashboard/sync.py missions/m1 --no-hf                # Neon only
~/.venvs/understory-dashboard/bin/python dashboard/sync.py missions/m1                        # no DATABASE_URL in .env: HF only
~/.venvs/understory-dashboard/bin/python dashboard/sync.py fake_data/missions/m1 --dry-run    # just read and count
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
