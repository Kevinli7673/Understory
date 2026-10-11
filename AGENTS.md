# AGENTS.md — Understory

Guidance for AI coding agents working in this repo. Read this before writing code.

## What this is

**Understory** (working name "Scout" in older notes) is a Knight Hacks IX project (Oct 9–11, 2026): a ground robot that surveys places people can't easily reach, identifies plants and animals with open-source AI, and turns the survey into a place you can walk through in VR.

Use case: mapping invasive plants (Brazilian pepper, air potato, cogongrass) on Central Florida conservation land, then re-surveying to prove removal worked (before/after counts).

Architecture line: **live on the edge (Jetson), deep in the cloud (AMD).**

Honest framing: an indoor mecanum robot on the venue floor stands in for the field. Don't oversell in docs or Devpost copy.

## Current status

_Updated Sat Oct 10, ~7 PM._

- **Quest ↔ Pi works (Sat ~6:20 PM):** the headset connected live to the Pi's ros_tcp_endpoint; real camera + LiDAR map on the table. **The Pi is now on Kevin's hotspot "iPhone (2)" at `172.20.10.3`** (was `172.20.10.10` on the other iPhone; switch back with `sudo nmcli dev wifi connect "<ssid>" password ...`). Quest: panel → Robot address.
- **Kevin (Quest app):** **Headset build works** (Quest 3S, OpenXR + Meta Quest, `com.knighthacks.understory`; first IL2CPP build ~13 min, then faster). Unity 6 (`6000.4.9f1`, URP) at `Unity/`: Meta XR SDK 207, Android, ROS-TCP-Connector (ROS2 define set). Contract classes + `RosCoords` in `Assets/Scripts/Contracts/`. `fake_data/` (m1 before / m2 after, run `python fake_data/generate.py`) replayed by `FakeSurveySource` → `SurveyHub`. `BubbleRingBuilder` + `TabletopMap` + `ViewSwitcher` (A / Tab, click a disc) tested in the editor, merged to `main`.
  - **On `main`; tested on the headset:** live ROS via the mock, voice → Whisper, e-stop, live survey, species popups. Components: `RosSurveySource` (survey topics, `/map`, `/mission/state`, `/pose` → hub; fake replay stops on the first real message), `TeleopController` (left stick drive/strafe, right stick turn → `/cmd_vel_teleop` only while held; **B** toggles `/estop`; editor WASD/QE/Space), `MissionPanel` (buttons → `/voice/text` keywords start/capture/resume/manual/return/stop), `SpeciesAlert` (popup + buzz per new species), `CameraScreen` (`/camera/image/compressed` behind the table), `ControllerPointer` (right-hand ray + trigger). One-click scene/player setup: **Understory → Set Up Quest Rig and Player Settings** (needs `com.unity.xr.openxr` + OpenXR/Meta Quest enabled on Android first).
  - Also (not yet tried on the headset): `BeforeAfterOverlay` (earlier mission's invasives → removed/still here, same 0.5 m rule as the dashboard; panel "Compare before" / V), `SensorHeatmap` (readings in 25 cm cells; "Sensor map" / H), `BubbleNavigator` (floor arrows to neighboring bubbles in the bubble view), `TableGrab` (left grip moves the table), robot trail on the table, `SplatView` (AMD `scene.splat` / point cloud as a 3D miniature on the table via the `Understory/SplatBillboard` shader; panel "3D model" / M; fake `scene.splat` per mission from `generate.py`), `PinCard` (pick a pin → photo card from its bubble frame with a marker at the detection; pick again → stand in that bubble). New `mission_id` → hub archives the previous mission so before/after works live.
  - **Demo without the robot (headset or editor):** m1 replays on launch; press **Start survey** after it finishes → m2 (the re-survey) replays; **Compare before** → "7 invasive → 1 remaining".
  - **Test ROS without a robot:** `python tools/quest_mock_endpoint.py --missions m1,m2` speaks the ros_tcp_endpoint protocol (stdlib only), replays fake missions in order (press Start survey for the next = live before/after rehearsal), simulates the robot (teleop, e-stop, voice keywords) and prints what the Quest sends. Editor connects to 127.0.0.1 by default.
  - **Compile check without focusing Unity:** `bash tools/check_unity_scripts.sh` (Unity's Roslyn against the project's DLLs).
  - **Logic unit tests:** `bash tools/test_unity_logic.sh` (contracts, map loading, before/after rule, RosCoords).
  - **ROS wire-format test:** `bash tools/test_ros_compat.sh` round-trips messages between the mock (Python) and the app's real ROS-TCP-Connector message classes (run on Unity's .NET, no editor).
  - **Jetson IP on the headset:** in VR: panel **Robot address** → keypad → Connect (saved, reconnects immediately). Or: `echo <ip> > ros_ip.txt && adb push ros_ip.txt /sdcard/Android/data/com.knighthacks.understory/files/`, restart the app. Table status line shows `LIVE <ip>` / `FAKE · connecting <ip>`.
- **Open (Kevin → Alvaro), proposed:** `/voice/audio` = `std_msgs/UInt8MultiArray` whose `data` is a complete **WAV file, 16 kHz mono 16-bit** (Quest `PushToTalk`: hold X, release to send). Whisper node: `wave` + numpy reads it directly (skip faster-whisper's PyAV decoder, it breaks on newer `av`) → transcribe with `initial_prompt` listing the commands (short clips get misheard: "Start survey" came out "Sorry, survey." without it) → publish the text on `/voice/text`. Reference: `transcribe()` / `command_from_text()` in `tools/quest_mock_endpoint.py`. `tools/quest_mock_endpoint.py` saves received clips to `%TEMP%/understory_voice_last.wav` for testing.
- **Done:** `panorama_node` always publishes every frame (`<bubble_id>/<index>`) and adds the stitched pano only as an extra; the Quest shows the frame ring (exact yaws) and uses the pano only when no frames arrive.

## Open software work (Sat ~7 PM)

Check `HANDOFF.md` section 1 for the Pi/Jetson details. Owners as in "Components and owners" below.

**Blocking the demo**
- **Robot driving on hardware** (Kevin / Teammate 4): flash `firmware/esp32_drive` (Arduino IDE, Adafruit Motor
  Shield V2 library), bench-test with wheels up (`C 0.1 0 0` in the Serial Monitor, fix `WHEEL_DIR`), then plug into
  the Pi; `scout_up.sh` starts `esp32_bridge.py`. Then Quest sticks / e-stop / 360° capture work for real.
- **Whisper with a real Quest clip** (Alvaro + Kevin): works with synthetic speech on the Pi; never tried with the
  headset's push-to-talk (hold X) end to end.
- **Pi + Jetson together** (Alvaro): never tried. The Pi throttles at 83 °C with the AI on; mapping/nav/AI should move
  to the Jetson (TensorRT detector already 15 Hz there).
- **Record a real mission** (`logger_node`, everyone): needed by the dashboard, a real before/after, and the splat.
  Plan a "before" run and an "after" run tonight; keep it as the pre-synced fallback.

**Makes it much better**
- **LiDAR odometry** (Teammate 3): odom is dead-reckoned from `/cmd_vel`, so carrying the robot doesn't move it and
  mecanum slip will drift. `rf2o_laser_odometry` + `odom_source:=external`.
- **Sensor pod** (Teammate 4): Grove sensors in `readSensors()` in `firmware/esp32_drive` (keys as in `/survey/readings`);
  then stop `fake_sensors.py`.

**Cloud and demo**
- **`sync.py` + Neon + Streamlit dashboard** (Fullstack): in `dashboard/`, works on `fake_data/missions/m1`/`m2`
  from folders (offline). Not yet run against a real Neon DB / HF dataset (needs `.env`); pins need embeddings
  (`publish_embedding:=true`, deep pass, or `sync.py --embed`) for similar-plant search.
- **AMD on the W7900** (Teammate 3 / Kevin): `amd/deep_pass.py` and the splat (`splat/setup_amd.sh`, `run.sh`) have
  not run on ROCm yet. Splat output `splat/out/<id>/scene.splat` shows up in the Quest's "3D model" button.
- **Devpost** (everyone): write-up, headset video (record the robot-free demo now as a backup), pitch.

## Hackathon rules that affect code

- Code freeze Sun 11 AM; submit by 9:30 AM. Favor working, demoable code over clean abstractions.
- **Nobody waits on anyone.** Every component builds against fake data and the data contracts below, then plugs into the real thing.
- **The live demo never depends on the internet or the cloud pipeline.** Live AI runs on the Jetson offline.
- Secrets (Neon URL, HF token, AMD credentials) live in `.env`, never committed.
- Every fragile subsystem has a fallback (see "Fallbacks"). When implementing one, keep the fallback path working too.

## System overview

| Zone | Runs | Notes |
| --- | --- | --- |
| Robot | Pi (power bank) + ESP32 (motors on 6×AA in series, ~7.2 V) | Pi: LiDAR, camera, ESP32 serial bridge. ESP32: wheels with **300 ms cmd watchdog**, Grove sensor pod. |
| Jetson Orin Nano | All live AI + robotics, wall power, no internet | GPU: NanoOWL (TensorRT), BioCLIP, Whisper small.en, stitching. CPU: slam_toolbox, Nav2, mission manager, twist_mux, localizer, logger. |
| Quest 3S | Unity app via ROS-TCP-Connector → ROS-TCP-Endpoint on Jetson | Live view, tabletop map twin, 360° bubbles, splat view, sticks, push-to-talk, e-stop. |
| Cloud (after mission) | HF Hub dataset, Neon (Postgres + pgvector), AMD Radeon PRO W7900 | Sync script + Streamlit dashboard + Gaussian splat. |

**Mode A** (build first): sensors plugged directly into the Jetson. **Mode B**: Pi on robot, Jetson at table, phone hotspot. ROS 2 makes the switch code-free — don't write code that assumes either mode.

**Jetson memory:** 8 GB shared CPU/GPU. Load models once at startup, never per-request. Check with `tegrastats`.

## Data contracts (source of truth)

Change these only with team agreement, and update this file when you do.

- `ROS_DOMAIN_ID=42`
- JSON travels as `std_msgs/String`.
- Positions are in the `map` frame, meters, **ROS axes** (x forward, y left, z up). Yaw in radians.
- Unity uses x right, y up, z forward. **All conversion goes through one function** in the Unity app; never convert ad hoc.

| Topic | Type | From → To |
| --- | --- | --- |
| `/scan` | LaserScan | LiDAR → slam_toolbox, Unity |
| `/map` | OccupancyGrid | slam_toolbox → Nav2, mission, Unity, dashboard |
| `/camera/image/compressed` | CompressedImage | Camera → detector, panorama, Quest |
| `/detections` | String (JSON) | Detector → species ID, Quest |
| `/species` | String (JSON) | Species ID → localizer, Quest |
| `/sensors` | String (JSON) | ESP32 bridge → localizer |
| `/survey/bubbles` | String (JSON) | Panorama → Quest, logger |
| `/survey/bubble_images` | CompressedImage | Panorama → Quest |
| `/survey/pins` | String (JSON) | Localizer → Quest, logger |
| `/survey/readings` | String (JSON) | Localizer → Quest, logger |
| `/voice/audio` | audio clip (16 kHz) | Quest → Whisper |
| `/voice/text` | String | Whisper → mission |
| `/mission/state` | String | Mission → Quest, dashboard |
| `/cmd_vel_teleop` | Twist | Quest → twist_mux |
| `/cmd_vel_auto` | Twist | Mission / Nav2 → twist_mux |
| `/estop` | Bool | Quest → twist_mux |
| `/cmd_vel` | Twist | twist_mux → ESP32 bridge |
| `/survey/capture` | String (`bubble_id`) | Mission → panorama, at each 30° stop |
| `/survey/capture_done` | String (`bubble_id`) | Panorama → mission, once the bubble is built |

twist_mux priority: **e-stop > Quest teleop > autonomy.**

Bubble image `frame_id` = `"<bubble_id>/<index>"` or `"<bubble_id>/pano"`.

IDs: mission `m1`, bubble `m1-b03`, pin `m1-p07`.

```json
// /survey/bubbles
{"bubble_id": "m1-b03", "mission_id": "m1", "t": 1791600000.12, "x": 1.42, "y": -0.35,
 "stitched": true, "frames": [{"index": 0, "yaw": 0.0}, {"index": 1, "yaw": 0.52}], "hfov": 1.22}

// /survey/pins
{"pin_id": "m1-p07", "mission_id": "m1", "bubble_id": "m1-b03", "label": "Brazilian pepper",
 "invasive": true, "confidence": 0.81, "yaw": 2.10, "x": 2.05, "y": 0.40, "crop": "m1-p07.jpg"}

// /survey/readings — ESP32 sends without x/y; localizer adds them; missing sensors are omitted, not null
{"mission_id": "m1", "t": 1791600003.5, "x": 1.50, "y": -0.30, "temp_c": 24.1,
 "pressure_hpa": 1013.2, "soil_moisture": 410, "light": 340, "uv": 0.2, "air_quality": 112, "sound": 48}
```

Mission states: `IDLE → SURVEYING → CAPTURING → NEXT_POINT → RETURNING`; `MANUAL` and `STOPPED` reachable from any state.

### Mission folder (logger output, pipeline input)

```
missions/<mission_id>/
  bubbles.jsonl       # one 360° capture per line
  pins.jsonl          # one detected species per line
  readings.jsonl      # one sensor reading per line
  frames/             # <bubble_id>_<index>.jpg or <bubble_id>_pano.jpg
  crops/              # <pin_id>.jpg
  map.pgm + map.yaml  # saved via: ros2 run nav2_map_server map_saver_cli
```

Store frames, not video.

## Components and owners

| Area | Owner | Produces |
| --- | --- | --- |
| Perception (NanoOWL, BioCLIP, Whisper, panorama, localizer) | Alvaro | `/detections`, `/species`, `/survey/*` (bubbles, images, pins, readings, capture_done), `/voice/text` |
| Quest app (Unity, Meta XR SDK) + AMD splat | Kevin | `/cmd_vel_teleop`, `/estop`, `/voice/audio`, `.splat` |
| Navigation + mission | Teammate 3 | `/map`, pose, `/cmd_vel_auto`, `/mission/state`, `/survey/capture` |
| Hardware, ESP32 firmware, logger, habitat | Teammate 4 | `/sensors`, motors obeying `/cmd_vel`, mission folders |
| Data pipeline + dashboard | Fullstack | Neon schema, `sync.py`, Streamlit dashboard |

## Start now (no cross-team dependencies)

Each role can start these right away, using fake data and the contracts above.

**Quest app + AMD (Kevin)**
- Shared `fake_data/`: sample `bubbles.jsonl`, `pins.jsonl`, `readings.jsonl`, fake `map.pgm` + `map.yaml`.
- C# contract classes (`Bubble`, `Pin`, `Reading`) and the single `RosCoords.ToUnity()` conversion.
- `FakeSurveySource` that feeds the same handlers the ROS subscribers will use.
- ROS scripts: teleop + e-stop publisher, camera subscriber, survey subscriber, push-to-talk.
- Bubble ring builder (unstitched panels at their yaw, plus the stitched cylinder).
- AMD ROCm check on the W7900: PyTorch sees the GPU, splat library installs, MASt3R runs on a few test photos. Decide whether the splat path is viable.
- Confirm a Gaussian splat plugin builds and renders on standalone Quest.

**Perception (Alvaro)**
- Flash JetPack, install ROS 2, build the NanoOWL container.
- BioCLIP label list (habitat species + invasive flags), tested on a laptop against printed invasive photos.
- Panorama builder as a plain Python function: 12 frames + yaws in, stitched strip (or ring fallback) + bubble JSON out.
- Detection → pin math (box position + frame yaw → bearing) with unit tests.

**Navigation + mission (Teammate 3): laptop-only for now, no Jetson, AMD or hardware**
- Mission state machine node (`IDLE → SURVEYING → CAPTURING → NEXT_POINT → RETURNING`, plus `MANUAL`/`STOPPED`), publishing `/mission/state`.
- Voice-command parsing ("survey this area", "where did you see X", "come back"), driven by typed `/voice/text`.
- Spin-in-place capture routine (rotate, stop every ~30°, publish `/survey/capture`, wait for `/survey/capture_done`), tested against a fake capture node.
- twist_mux config (e-stop > teleop > auto) and slam_toolbox params, ready to drop onto the Jetson.

**Hardware + robot data (Teammate 4)**
- Wire 6×AA in series, pull the VIN jumper, shared ground.
- ESP32 drive firmware with the 300 ms watchdog; serial bridge node; keyboard teleop.
- Sensor pod firmware emitting JSON lines; borrow Grove sensors from MLH.
- Logger node writing the mission folder layout from recorded or fake topics.

## Component notes

### 360° bubbles
- Robot spins in place, stops every ~30° (~12 frames), each tagged with heading from slam_toolbox.
- Lock exposure + white balance with `v4l2-ctl` before capture, or seams appear.
- Try `cv2.Stitcher_create()` → cylinder strip; **if stitching fails, fall back to the unstitched ring** (frames placed as curved panels at their yaw). `stitched` in the bubble JSON tells Unity which one it got.
- It's a cylinder band, not a sphere; Unity fills top/bottom with a dark gradient.
- Pin direction = detection box's horizontal position + frame yaw. Distance from LiDAR or camera floor-row calibration.

### Perception
- BioCLIP uses a **fixed label list** (habitat species + invasive flag), not open vocabulary.
- Benchmark NanoOWL FPS TensorRT vs PyTorch, and camera→headset latency; these become pitch charts.
- If memory is tight: run Whisper only while push-to-talk is held, or move STT to a laptop.

### Quest app (Unity)
- Iterate in the editor on fake data (phone panorama + sample JSON); headset builds are slow APK builds.
- B = e-stop, A/B switch between tabletop map twin and immersive bubble view. Haptic buzz per new species.
- Splat on standalone Quest must be small (cropped, capped blob count).

### ESP32 firmware
- Stop motors if no `/cmd_vel` for 300 ms. If motors are 6 V, cap PWM ~85%.
- Sensor pod emits JSON lines over serial; the bridge node republishes on `/sensors`.

### Data pipeline (`sync.py`) and dashboard
- `python sync.py missions/m1`: upload `frames/`, `crops/`, map image to an HF Hub dataset repo; upsert mission, bubbles, pins (with BioCLIP embeddings, `vector(512)` — confirm size), readings into Neon. **Must be idempotent** (upserts).
- Build first against a fake-mission generator that makes "before" and "after" folders (fewer invasives in "after").
- Dashboard (Streamlit): survey overview, floor plan with pins + sensor heat maps (meters→pixels via `map.yaml`), before/after (match pins by same label within ~0.5 m: "7 found → 1 remaining"), similar plants via pgvector (`order by embedding <-> $1 limit 12`).
- Neon schema: `missions`, `bubbles`, `pins`, `readings` (see the plan doc, section 18).

### AMD splat (stretch)
- Runs on a separate Radeon Cloud W7900 machine, not the Jetson.
- Use the PyTorch ROCm image: `pip install` extras, **never reinstall `torch`**. Logged in as root, no `sudo`.
- Pipeline: frames → MASt3R poses → splat training → align to LiDAR map via SLAM poses → `.ply`/`.splat` to Unity.
- Splat libraries (e.g. `gsplat`) may have CUDA-only kernels. Fallback: Depth Anything point cloud.

## Fallbacks

| If this fails | Fall back to |
| --- | --- |
| NanoOWL build | YOLO-World → plain YOLO (BioCLIP still names crops) |
| ROS 2 discovery over hotspot | `rmw_zenoh` → tethered Mode A |
| Video lag | Lower live res/FPS; full quality only for bubble frames |
| Stitching | Unstitched ring |
| Autonomous survey | Manual drive + capture button |
| Splat on ROCm | Depth Anything point cloud → skip AMD |
| Venue internet | Pre-synced Saturday-night mission |
| Quest app | Laptop dashboard / Foxglove |

## Conventions

- Python for ROS nodes, pipeline, and dashboard; C# for Unity; Arduino/C++ for ESP32.
- One ROS node per job. Topic names and JSON keys exactly as in the contracts above.
- Timestamps are Unix seconds (float) in JSON, `timestamptz` in Neon.
- Debug with `ros2 topic list`, `ros2 topic echo <topic>`, and Foxglove before adding logging code.
- Keep changes scoped to your component; contract changes go through the team.
