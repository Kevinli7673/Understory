# Understory handoff: Pi + Jetson (perception, bringup, AI)

Written Sat Oct 10 2026, last updated Sun Oct 11 about 3:30 AM EDT, on the Jetson. **Submission is Sun Oct 11, 9:30 AM EDT.**

This file is for Alvaro (perception lead) and for any coding agent picking the work up on either the
Raspberry Pi or the Jetson Orin Nano. It covers what exists, what was tested and how, how to run it,
what is left, and what was done in each working session. `AGENTS.md` is still the team contract for
topic names and JSON shapes; this file does not replace it.

If you are a coding agent: read sections 1 to 4, then go to section 7 (Jetson) or section 6 (Pi), and
follow the rules in section 12.

---

## 1. Where things stand

| Piece | State | How it was checked |
| --- | --- | --- |
| Pi sensors: `/scan` 10 Hz, `/camera/image/compressed` 15 Hz | Works | `scout_up.sh` health check, Sat 12:16 PM, after a power loss and reboot |
| Mapping, Nav2, mission manager, panorama on the Pi | Works | `scout_up.sh --nav`: `/mission/state` `IDLE`, TF `map -> base_link` ok |
| Quest endpoint `172.20.10.10:10000`, Foxglove `:8765` | Listening | port check. No headset has connected since the Quest ROS code was written |
| Panorama node always sends the 12 frames | Works | `capture` on the Pi: 12 frames, bubble JSON, `CAPTURING -> IDLE` |
| Detector, real model (OWL-ViT) | Works, slow on CPU | Pi CPU: about 0.25 Hz. GPU not tried |
| Species ID (BioCLIP, 5 species) | Works | names 5 of 5 test photos at detector threshold 0.05 (now the default), embedding length is 512 |
| Localizer: pins + readings | Works | 14 unit tests; live with real LiDAR + TF; self-test produces pins |
| One command for the AI (`scout_ai_up.sh`) | Works on the Pi | started, `/detections` seen from the `scout` container |
| Pi temperature with the AI running | **Too hot** | 83 °C and thermally throttled after 5 minutes (section 5) |
| Jetson | **Nothing has run on it** | `jetson_up.sh` only passed a dry run on the Pi |
| Pi and Jetson together | **Never tried** | |
| Robot driving | **Bridge talks to the board; wheels not driven yet** | Sat 8:29 PM on the Pi: `scout_up.sh` found the QT Py ESP32-S2, started `esp32_bridge.py`, and the firmware answered `shield=ok moving=0`. The bridge is subscribed to `/cmd_vel` from the Jetson's twist_mux. No drive command has been sent (session 11) |
| `/sensors` from the ESP32 | **Bridge republishes it; no sensor is wired in the firmware yet** | `fake_sensors.py` stands in |
| Whisper (`/voice/audio` -> `/voice/text`) | Works with synthetic speech | 6 of 6 computer-spoken commands transcribed and parsed, Pi CPU, about 2.5 s each. The command prompt and confidence floor are on the Pi too (session 11). **No human voice tried yet** |
| NanoOWL / TensorRT | Works on the Jetson, and is its default | model 19 ms per frame against 62 ms in PyTorch; live `/detections` 15.3 Hz (the camera's rate) against 9.8 Hz; self-test 5 of 5 (section 11, session 9) |
| Mission logger (`logger_node`) | Works with fake data; live pins and crops written Sat night | 3 fake bubbles, 36 frames, pins, readings and a map written in the `AGENTS.md` layout (session 10). Live: 12 pins and crops in `missions/m1`, all false alarms, no bubble captured yet (session 10, continued) |
| AMD deep pass (`amd/deep_pass.py`) | Runs on the Jetson GPU. **Not run on the W7900 / ROCm** | 5 of 5 test photos named with OWLv2 base (session 10, `amd/README.md`) |
| Dashboard (one-page design with the live headset view and live LiDAR) | Runs on the Jetson, `http://<Jetson IP>:8501`; `dashboard/run.sh` starts it, the live relay (`:8770`) and the LiDAR bridge | Sun 3:25 AM: 13 tests pass; folder and Hugging Face sources render; real LiDAR scans reach the page (session 12) |
| Headset view on the dashboard | **Relay works with test frames. The Quest has not sent a frame** | 24 test JPEGs through the WebSocket over the hotspot, all received. Needs the Quest steps in section 8a |
| Hugging Face dataset `a1vcm/understory-missions` (private) | Holds the two **fake** missions m1 and m2 | uploaded Sat 11:40 PM; downloaded by the dashboard Sun 1:40 AM |
| Neon sync | **Not run**: no `DATABASE_URL` in `.env` | |

The short version: **the full perception chain now runs on the Pi alone, slowly.** A plant photo held
in front of the camera becomes a pin about 12 to 15 seconds later. The Jetson's job is to run the same
code faster, and to take mapping and navigation off the Pi.

## 2. The project in one paragraph

Understory (older name "Scout") is a field-survey robot for Knight Hacks IX. A mecanum robot drives
through a staged habitat, maps it with a 2D LiDAR, takes 360° "bubble" photo spins, identifies plants
(invasive: Brazilian pepper, air potato, cogongrass; native: saw palmetto, wild coffee) with
open-source models, and shows the result in a Meta Quest 3 app and a web dashboard. Everything talks
over ROS 2 Jazzy on `ROS_DOMAIN_ID=42`, over an iPhone hotspot. The live demo must work with no internet.

## 3. Machines and network

| Machine | Role | Address |
| --- | --- | --- |
| Raspberry Pi 5 (on the robot) | LiDAR, camera, Foxglove, Quest endpoint. Can also run everything | **`172.20.10.3` since Sat evening** (was `172.20.10.10`; the phone assigns it, `scout_up.sh` prints it), user `a1vcm` |
| Jetson Orin Nano (on the table, wall power) | Mapping, Nav2, mission, panorama, AI | needs a `172.20.10.x` address |
| Quest 3 | Unity app | connects to **the Pi**, port 10000, at the address above |

- Hotspot: "Alvaro's iPhone". The Pi falls back to `eduroam2` if the phone is not in range at boot.
  Fix: `sudo nmcli con up hotspot`.
- **The Pi has no clock battery.** After a reboot on eduroam it came up 5 h 44 min slow, because NTP is
  blocked there. TF between machines fails if clocks differ by more than a fraction of a second.
  Check `date` after every reboot. Fix with internet:
  `sudo date -u -s "$(curl -sI https://github.com | grep -i '^date:' | cut -d' ' -f2-)"`
- Neither machine has ROS on the host. Everything runs in Docker:
  - `scout` container, image `scout-ros`: ROS 2 Jazzy, slam_toolbox, Nav2, twist_mux, Foxglove. No PyTorch.
  - `scout-ai` container, image `scout-ros-ai`: the same plus CPU PyTorch, transformers and open_clip.
  - Both use `--net=host --ipc=host`, so nodes in one see nodes in the other.
- Workspace: `~/fetch_ws` on the host is `/fetch_ws` in both containers. This repo is at
  `~/fetch_ws/src/Understory`. The build is `--symlink-install`, so edited Python takes effect when the
  node restarts. A new node or entry point needs a rebuild (section 13).
- Only **one** `scout_nav.launch.py` (slam + Nav2 + mission) may run on the network: Pi or Jetson, never both.

## 4. Where everything is

| Thing | Path |
| --- | --- |
| Team contract | `AGENTS.md` |
| Pi and Jetson run instructions | `pi/README.md` |
| Pi start / stop / shell | `pi/scout_up.sh`, `pi/scout_down.sh`, `pi/scout_shell.sh` (symlinked into `~` on the Pi) |
| AI start / stop | `pi/scout_ai_up.sh` (symlinked to `~/scout_ai_up.sh` on the Pi) |
| Jetson start | `pi/jetson/jetson_up.sh` |
| Launch files | `pi/scout_bringup.launch.py` (sensors), `pi/scout_nav.launch.py` (slam, Nav2, mission, panorama) |
| Docker images | `pi/docker/Dockerfile` (`scout-ros`), `pi/docker/Dockerfile.ai` (`scout-ros-ai`) |
| Perception package | `ros2_ws/src/scout_perception` |
| Helper scripts | `pi/scripts/` |
| Navigation + mission (mizbahh) | `ros2_ws/src/understory_nav`. **Not ours to edit** |
| Quest app (Kevin) | `Unity/`, `fake_data/`, `tools/`. Newest work is on branch `quest-app` |
| Splat pipeline (Kevin) | `splat/`. **Not ours to edit** |
| Logs | `~/fetch_ws/logs/` (`bringup`, `nav`, `tcp_endpoint`, `detector`, `species`, `localizer`) |
| Pin crops | `~/fetch_ws/missions/<mission_id>/crops/<pin_id>.jpg` |
| Model cache | `~/.cache/huggingface` on the host, mounted into `scout-ai` |
| Exported `scout-ros` image for the Jetson | `~/scout-ros-image.tar.gz` on the Pi, about 925 MB |

### The perception package

| File | What it is |
| --- | --- |
| `detector_node.py` | camera -> `/detections`. Parameters: `backend`, `prompts`, `score_threshold` |
| `backends.py` | `dummy`, `owlvit_torch` (real), `nanoowl_trt` (real, Jetson only: TensorRT engine from `pi/scripts/build_owl_engine.py`) |
| `species_node.py` | `/detections` + camera -> `/species`. Parameters: `backend`, `min_confidence` (0.6), `max_boxes` (3) |
| `species_backends.py` | `dummy`, `bioclip` |
| `species_labels.py` | **The species list. Edit this to match the habitat.** Also the "not a plant" list |
| `localizer_node.py` | `/species` + `/scan` + TF -> `/survey/pins`; `/sensors` -> `/survey/readings` |
| `geometry.py` | bearing, LiDAR lookup, map projection, pin de-duplication. No ROS imports |
| `test/test_geometry.py` | 14 unit tests for `geometry.py` |
| `panorama_node.py` | `/survey/capture` -> 12 frames + bubble JSON + `capture_done`, pano as an extra |
| `whisper_node.py` | `/voice/audio` (WAV bytes) -> `/voice/text`. Parameters: `model`, `min_seconds`, `min_rms` |
| `voice.py` | WAV decoding, resampling, transcript clean-up. No ROS imports |
| `test/test_voice.py` | 12 unit tests for `voice.py` |

## 5. How the AI chain works

```
/camera/image/compressed ──> detector_node ──> /detections ──> species_node ──> /species ──> localizer_node ──> /survey/pins
                                (OWL-ViT)       "a plant" boxes    (BioCLIP)     named plant      + /scan + TF      + crop .jpg
/sensors (ESP32 bridge) ───────────────────────────────────────────────────────────────────> localizer_node ──> /survey/readings
```

1. **Detector** finds plant-like things with general prompts ("a plant", "a leaf", "a tree", ...). It
   does not name species. It drops frames it cannot keep up with.
2. **Species node** cuts each box out of the exact frame it came from (matched by timestamp) and asks
   BioCLIP to pick from the fixed list in `species_labels.py`. The list also holds non-plant entries
   ("a photo of a wall", "a photo of a hand", ...). If one of those wins, or confidence is under
   `min_confidence`, nothing is published. This removed a false "cogongrass" on a ceiling decoration.
   Since Sat 10:15 PM the list also holds other living things by scientific name (`OTHER_LIFE`: people,
   pets, ornamental and house plants), because the phrases alone let a face through (session 10, later).
3. **Localizer** turns the box centre into a direction (camera yaw from TF + pinhole angle from
   `hfov`), reads the LiDAR range in that direction, and projects it into the map from TF
   `map -> base_link`. Sightings of the same label within 0.5 m merge into one pin. A pin is published
   after 3 sightings, and again if a later sighting is at least 0.05 more confident.

### Message shapes

`/detections` (in `AGENTS.md` by name only):

```json
{"t": 1791600000.12, "frame_id": "camera", "boxes": [{"label": "a plant", "score": 0.16, "xyxy": [317, 144, 546, 454]}]}
```

`/species`, **proposed, not yet agreed with the team or written into `AGENTS.md`**. One message per box:

```json
{"t": 1791600000.12, "frame_id": "camera", "label": "air potato", "invasive": true,
 "confidence": 0.98, "xyxy": [317, 144, 546, 454], "embedding": [512 floats]}
```

`/survey/pins` and `/survey/readings` follow `AGENTS.md` exactly. Details that are not in the contract:

- Pin `yaw` is the direction of the plant from its bubble's centre, in the map frame. That is how
  Kevin's `Pin` class documents it.
- Pin `bubble_id` is the bubble being captured when the plant was seen, else the nearest known bubble,
  else `""` if no bubble exists yet. **Kevin should confirm the Quest copes with an empty `bubble_id`.**
- Pins carry no `embedding`. `-p publish_embedding:=true` on the localizer adds it. This is an open
  question with the dashboard owner, whose similar-plant search needs it.
- Readings: null values are dropped, `t` is added if the ESP32 did not send one.

### Measured on the Pi 5 CPU (2 PyTorch threads, mapping and Nav2 running)

| Step | Time |
| --- | --- |
| OWL-ViT, one 640x480 frame | about 3.2 s alone, about 4 s with the rest of the stack |
| BioCLIP, one crop | about 1.0 s |
| `/detections` rate | 0.21 to 0.25 Hz |
| Model load, cached | about 5 s each. First download: about 3 minutes each on the hotspot |
| Pi while the AI runs | load 7 to 10 on 4 cores, `/scan` and camera still at full rate |
| Pi temperature | 71 °C at first, **83 °C after about 5 minutes**, `vcgencmd get_throttled` = `0xe0008` (soft temperature limit active) |

### Known weaknesses

- **The Pi overheats when it runs the AI.** It reached 83 °C and the firmware started slowing the
  CPU. It has no fan. Run the AI on the Pi only for short tests (`~/scout_ai_up.sh --stop` after),
  or add a fan. The AI is left **stopped** on the Pi. This is one more reason to move it to the Jetson.
- **Cogongrass and wild coffee score low in the detector** (0.05 to 0.08), because in a photo they
  look like plain grass and plain leaves. At threshold 0.07 the self-test named 3 or 4 of the 5
  photos; at 0.05 it named all 5, cogongrass with confidence 0.58 and the rest at 1.0. The default
  is now 0.05. On the live camera at 0.05, in a room with no plants, the detector produced two weak
  boxes in 45 s and the species node rejected both, so no false pin appeared. That is one short
  check, not a guarantee: watch `localizer.log` for false pins in the real habitat.
- BioCLIP always picks its best of 5 species plus the non-plant list. A plant that is not in the list
  gets the nearest listed name, sometimes confidently.
- Distance is the LiDAR range at LiDAR height. A photo held in the air above the LiDAR plane gets the
  distance of whatever is behind it at LiDAR height.
- `hfov` is 0.83 rad, computed from the camera spec, not measured. The TF offsets for `laser` and
  `camera` in `pi/scout_bringup.launch.py` are placeholders. Pins are rough until both are measured.
  The localizer reads the offsets from TF, so fixing the launch file fixes the pins.
- With the robot unable to move, the map pose still turns during a `capture`, because odometry is
  dead-reckoned from `/cmd_vel`. Pins seen during that fake spin land in the wrong direction.

## 5a. Voice (Whisper)

`whisper_node` takes one push-to-talk clip from `/voice/audio` (`std_msgs/UInt8MultiArray`, the bytes
of a complete WAV file, which is the format Kevin proposed and the Quest already sends) and publishes
the transcript on `/voice/text`, lower case, no punctuation. The mission manager finds the command
in it by keyword. `scout_ai_up.sh` starts it with the plant AI, in the `scout-ai` container.

- Whisper runs through `transformers`, which the AI image already has. No image rebuild.
- Default model `openai/whisper-base.en` (about 280 MB, downloaded on first start, then offline).
  `WHISPER_MODEL=openai/whisper-small.en ~/scout_ai_up.sh` uses the larger model the plan names; it
  has not been downloaded or timed. `WHISPER_MODEL=none` skips voice.
- Measured on the Pi CPU: model loads in about 8 s; a 1 to 2 s clip takes about 2.5 s alone and
  about 6 s while the detector is also running.
- Tested with computer-generated speech (`espeak-ng`), not a person: "start survey" (heard as
  "star survey"), "stop", "come back home", "take a picture", "manual", "keep going" all reached the
  right command. A seventh, non-command sentence was transcribed wrongly, so expect errors on
  longer speech.
- Clips under 0.3 s or with RMS under 0.005 are dropped before the model runs. Louder background
  noise still gets through: 3 s of pink noise came back as "you". That word is not a command, but
  noise could in principle produce one. The Quest e-stop still overrides everything.
- **Run it on one machine only.** Two Whisper nodes would publish every command twice.
- Test without the Quest (on ROS domain 43, so the mission manager does not act on it):

```bash
# inside scout-ai, both commands with ROS_DOMAIN_ID=43
ros2 run scout_perception whisper_node
python3 /fetch_ws/src/Understory/pi/scripts/voice_test.py /fetch_ws/test_voice/*.wav
```

  `~/fetch_ws/test_voice/` on the Pi holds the synthetic clips. Any 16-bit WAV works.

## 6. Running on the Pi

```bash
# after any reboot: plug in LiDAR + camera, then
sudo nmcli con up hotspot && date        # must show 172.20.10.10 and the right time
~/scout_up.sh --nav                      # sensors + Foxglove + Quest endpoint + mapping + Nav2 + mission + panorama
~/scout_ai_up.sh                         # real plant AI, slow
~/scout_ai_up.sh --fake-sensors          # same, plus fake /sensors so /survey/readings flows
tail -f ~/fetch_ws/logs/localizer.log    # pins appear here

~/scout_ai_up.sh --stop                  # stop the AI only
~/scout_down.sh --keep                   # stop all ROS, keep the containers
```

When the Jetson takes over mapping and AI, the Pi runs sensors only: `~/scout_down.sh --keep && ~/scout_up.sh`.

Test the AI with no plant and no robot (runs on ROS domain 43, invisible to the Quest):

```bash
pi/scripts/ai_selftest.sh                # uses ~/fetch_ws/test_plants/*.jpg, prints pins and PASS/FAIL
~/scout_ai_up.sh                         # the self-test stops the live AI nodes; start them again
```

`~/fetch_ws/test_plants/` on the Pi holds five Wikipedia photos, one per species. They are not in the
repo (their licences need attribution). Any `.jpg` photos of the listed plants work.

## 7. Bringing up the Jetson

Nothing below has been run on the Jetson. Treat every statement about it as an assumption.

### Step 0: look before touching (read-only)

```bash
cat /etc/nv_tegra_release; lsb_release -a; uname -m; free -h; df -h ~
docker --version; docker info | grep -i runtime; docker ps
hostname -I; date; python3 --version; git --version
python3 -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

Needed: a `172.20.10.x` address, `date` matching the Pi to the second, `docker ps` working without sudo
(`sudo usermod -aG docker $USER`, then log out and in), and about 10 GB free disk.

### Step 1: one-time setup

```bash
scp a1vcm@172.20.10.10:scout-ros-image.tar.gz ~/          # or carry it on a USB stick
gunzip -c ~/scout-ros-image.tar.gz | docker load

mkdir -p ~/fetch_ws/src && cd ~/fetch_ws/src
git clone https://github.com/Kevinli7673/Understory.git
cd Understory && git checkout perception-pins     # only until PR #2 is merged into main
```

**The AI code and this file are on branch `perception-pins` (PR #2), not yet on `main`.** Check with
`git log --oneline -1 origin/main`; once PR #2 is merged, stay on `main`.

### Step 2: start it

```bash
# Pi: sensors only, so only one slam_toolbox exists. This drops the Quest connection for about 30 s
~/scout_down.sh --keep && ~/scout_up.sh
# Jetson
~/fetch_ws/src/Understory/pi/jetson/jetson_up.sh
```

`jetson_up.sh` builds the workspace, checks it can see the Pi's `/scan`, starts mapping + Nav2 +
mission + panorama, then calls `scout_ai_up.sh`. On the first run that builds the `scout-ros-ai`
image (about 5 minutes) and downloads the two models (about 1 GB). Both need internet once. After
that it runs offline.

A good run prints `/scan` near 10 Hz, `/mission/state: IDLE`, `TF map -> base_link: ok`, the camera
near 15 Hz, and `/detections: publishing`.

**This default uses the CPU image, not the GPU.** It is the same code that works on the Pi, so it is
the safe first target. Expect roughly Pi speed. `NO_AI=1 jetson_up.sh` skips the AI.

If the Jetson cannot see `/scan`:
1. Confirm the Pi is running `~/scout_up.sh`.
2. The hotspot may be dropping multicast. Point each machine at the other (never tested):
   - Pi: `~/scout_down.sh --keep && SCOUT_PEER=<Jetson IP> ~/scout_up.sh`
   - Jetson: `SCOUT_PEER=172.20.10.10 ~/fetch_ws/src/Understory/pi/jetson/jetson_up.sh`
3. Next fallback in `AGENTS.md` is `rmw_zenoh`, already in the image. After that, plug the LiDAR and
   camera into the Jetson and run `scout_up.sh --nav` there.

If the Jetson misbehaves at any point, the Pi alone is the fallback: `~/scout_up.sh --nav && ~/scout_ai_up.sh`.

### Step 3: GPU (the reason the Jetson is here)

The code already picks `cuda` when `torch.cuda.is_available()` is true; nothing in the nodes changes.
What is missing is a container where that is true **and** ROS 2 Jazzy works. `scout_ai_up.sh` takes
the image and runtime from the environment:

```bash
AI_IMAGE=<your cuda image> AI_RUNTIME=nvidia ~/fetch_ws/src/Understory/pi/jetson/jetson_up.sh
```

The image must contain: ROS 2 Jazzy with `rclpy`, `tf2_ros`, `sensor_msgs`, `python3-opencv`; PyTorch
built for this JetPack with CUDA; `torchvision`, `transformers`, `open_clip_torch`; `numpy<2`. Routes,
in the order to try them:

1. **`FROM scout-ros` plus NVIDIA's Jetson PyTorch wheel**, run with `--runtime nvidia`. Copy
   `pi/docker/Dockerfile.ai`, swap the CPU `torch`/`torchvision` install for the wheel matching the
   JetPack version from step 0. Smallest change. Risk: the wheel wants the host's CUDA libraries,
   which the nvidia runtime mounts on some JetPack versions and not others, and the wheel's Python
   version must match the image's (3.12).
2. **A `dusty-nv/jetson-containers` image with PyTorch and ROS 2.** If its ROS is Humble rather than
   Jazzy, `String` and `CompressedImage` usually cross over, but that pairing is unsupported. Test
   one `ros2 topic echo /camera/image/compressed --once` before building on it.
3. **Models in a plain GPU Python process, thin ROS node in `scout`** talking to it over a local
   socket. Use this if ROS inside the GPU container turns into a fight.

Check each of these before trusting it: `torch.cuda.is_available()` is true inside the container; a
node in it receives `/camera/image/compressed`; `tegrastats` shows GPU load and memory headroom (8 GB
is shared between CPU and GPU, and mapping + Nav2 are already using some). Then run
`pi/scripts/ai_selftest.sh` and record the `/detections` rate for the pitch.

Write the working recipe down as `pi/jetson/Dockerfile.gpu` so it can be rebuilt.

## 8. What the Quest app needs from us (Kevin)

Kevin's app is in `Unity/`. On `main`: bubble ring view, tabletop map, view switching, fake missions.
On branch `quest-app`, compiling but **not yet tested against ROS or on the headset**: live ROS
subscriptions, stick driving, e-stop, mission buttons, before/after overlay, sensor heat map, pin
photo cards, push-to-talk.

| Quest subscribes to | Who publishes it | State |
| --- | --- | --- |
| `/map`, `/pose`, `/mission/state` | slam_toolbox, mission manager | live with `--nav` |
| `/camera/image/compressed` | Pi camera | live |
| `/survey/bubbles`, `/survey/bubble_images` | panorama node | live; frames always sent now |
| `/survey/pins`, `/survey/readings` | localizer | live when `scout_ai_up.sh` runs |

| Quest publishes | Who consumes it | State |
| --- | --- | --- |
| `/cmd_vel_teleop`, `/estop` | twist_mux | wired, but nothing drives the motors |
| `/voice/text` (panel buttons) | mission manager | works |
| `/voice/audio` (hold X) | Whisper node | node written, not yet tried with a real Quest clip |

His two requests in `AGENTS.md`:
1. *Always publish the frames; pano optional.* **Done.** Frames go out first, then the bubble JSON
   and `capture_done`, then stitching runs. If it works, `<bubble_id>/pano` follows and the bubble
   JSON is re-sent with `"stitched": true`.
2. *`/voice/audio` = `std_msgs/UInt8MultiArray` holding a complete WAV file, 16 kHz mono 16-bit.*
   Not answered yet. It is a reasonable format; the Whisper node in section 9 assumes it.

Things to tell Kevin:
- The Quest must point at the **Pi** (`172.20.10.10`), not the Jetson. His notes say Jetson.
- For steady fake bubbles, pins and readings: `python3 /fetch_ws/scripts/fake_survey.py --mission m1`
  inside the `scout` container. Do not run it together with the real AI.
- Ignore test data from Saturday morning: bubble `m1-b01` and pins `m1-p01` to `m1-p15` were
  published around 11:47 AM from dummy backends.

## 8a. Headset view on the dashboard (Kevin): what to do on the Quest

The dashboard's top panel shows what the headset wearer sees. The Quest app sends JPEG frames over a WebSocket to a
relay (`dashboard/live_relay.py`), and every browser that has the dashboard open reads them from the relay.

```
Quest (HeadsetStreamer.cs) --ws JPEG--> relay on the Jetson, port 8770 --ws--> dashboard in a browser
```

The Jetson side is running (`dashboard/run.sh`, Sun 3:25 AM). The relay is at **`172.20.10.4:8770`**. Three steps on your side:

1. **Get the code and build.** `git pull` on `main` once PR #15 is merged, or check out `hf-hub-handoff` now. The
   script is `Unity/Assets/Scripts/Util/HeadsetStreamer.cs`. It adds itself at startup; nothing to place in the scene.
   **It has no `.meta` file in the repo**: open the project in Unity once so it writes one, and commit it. Compile check
   without Unity in focus: `bash tools/check_unity_scripts.sh`. Then build and install the APK as usual.
2. **Tell the app where the relay is.** With the Quest on USB:
   ```bash
   echo 172.20.10.4 > dashboard_ip.txt
   adb push dashboard_ip.txt /sdcard/Android/data/com.knighthacks.understory/files/
   ```
   This file is separate from `ros_ip.txt` (the robot, `172.20.10.3`). It survives app updates; push it again only if
   the Jetson's address changes (`hostname -I` on the Jetson). A full `ws://host:port/path` in the file also works.
   Without the file the streamer stays off and the app behaves as before.
3. **Restart the app, then check.**
   - `adb logcat -s Unity | grep HeadsetStreamer` should print `streaming to ws://172.20.10.4:8770/ws/headset/pub`.
     `off: no dashboard_ip.txt in ...` means step 2 did not land in that folder.
   - `http://172.20.10.4:8770/health` in any browser: `headset_publishers` should be 1 and `frame_age` under 1.
   - `http://172.20.10.4:8770/headset.jpg` shows the newest frame by itself.
   - `http://172.20.10.4:8501`: the top panel changes from "Waiting for the headset" to the picture with "live · 8 fps".

Things to know:
- The stream is 640x360, 8 frames a second, JPEG quality 60 (fields on the component). Passthrough is not in it,
  because the headset's system adds passthrough after the app renders: virtual content shows on a dark background.
- If the picture is upside down, restart the dashboard with `LIVE_FLIP=1 dashboard/run.sh` (after `dashboard/run.sh --stop`).
- The Quest, the Jetson and the viewing laptop must be on the same hotspot. The browser opens
  `ws://<the dashboard's host>:8770/ws/headset` itself.
- **Not tested with a headset.** Only the relay was tested, with frames sent from a script. The capture code in
  `HeadsetStreamer.cs` (mizbahh, Sun 3 AM) has not run on a Quest as far as this file knows.
- To try the panel with no headset: `dashboard/.venv/bin/python dashboard/fake_live.py` on the Jetson. **It also posts
  fake LiDAR scans**, so stop the real bridge first (`docker exec scout pkill -f scan_bridge.py`) and run
  `dashboard/run.sh` again afterwards.

## 9. What is left, in order

1. **Jetson steps 0 to 2** (section 7). Settles the two-machine question, the largest untested risk.
2. **Quest against the live Pi.** First real test of Kevin's ROS code. Needs only the Pi.
3. **Hold real plant photos in front of the camera** with `scout_ai_up.sh` running (short runs on
   the Pi: it overheats). Tune
   `DETECTOR_THRESHOLD`, `min_confidence` and `species_labels.py` to the actual habitat.
4. **Jetson GPU** (section 7, step 3).
5. **Agree `/species`, pin `embedding` and `/voice/audio`** with the team, then update `AGENTS.md`.
6. **As soon as the ESP32 bridge exists:** first drive, first real spin, `angular_scale` calibration,
   a bubble from real rotated frames (run `pi/scripts/camera_lock.sh` first; check the 12 yaws step
   by about 0.52 rad). Stop `fake_sensors.py` once the real `/sensors` is there.
7. **Saturday night:** one full recorded mission as the fallback `AGENTS.md` asks for.
8. **Voice with a real person.** The Whisper node exists (section 5a) but has only heard a
   synthetic voice. Hold X on the Quest, say each command, and read `~/fetch_ws/logs/whisper.log`.
10. **AMD, needs someone with the Radeon Cloud login:** on the box, `bash amd/setup_amd.sh`, copy a mission folder over, `python amd/deep_pass.py missions/<id>` and `bash splat/run.sh missions/<id>`. Put `deep_report.json`'s numbers in the pitch. With no real mission yet, `fake_data/missions/m1` exercises the plumbing (its frames are drawings, so expect no pins).
9. ~~NanoOWL + TensorRT, and a PyTorch-versus-TensorRT speed number for the pitch.~~ Done Sat 5 PM (section 11, session 9).

Waiting on teammates:
- **Hardware (Teammate 4):** ESP32 serial bridge (`/cmd_vel` in as plain `Twist`, `/sensors` JSON
  out, motors stop after 300 ms without a command, use the `/dev/serial/by-id/` name because the
  LiDAR is also USB serial). Measured LiDAR and camera offsets. The logger node.
- **mizbahh:** `angular_scale` once wheels turn; the single-survey-point question from simulation;
  camera frame name (`camera_link` in her launch, `camera` in ours).
- **Fullstack:** build against `fake_survey.py`; embedding size is confirmed as 512.

## 10. Decisions Alvaro still has to make

- `/species` shape (section 5): get the team to agree, then add it to `AGENTS.md`.
- Pin `embedding`: in or out of the published pin.
- `/voice/audio` format: the Whisper node is built on Kevin's proposal. Confirm, then write it into `AGENTS.md`.
- `AGENTS.md` says "code freeze Sun 11 AM; submit by 9:30 AM". One of those is wrong.

## 11. Session log

What was asked in each working session with Claude Code, and what was done.

**Session 1, Fri night, Pi bringup.** Asked for the seven Pi tasks in the original brief. Fixed the
camera launch (device path was not resolved, brightness forced to 50). Started the Quest endpoint.
Wrote `scout_up.sh`, `scout_down.sh`, `scout_shell.sh`, `camera_lock.sh`, `save_frames.py`,
`record_bag.sh`, `fake_survey.py`. Created `scout_perception` with a dummy detector and the panorama node.

**Session 2, Sat early morning, teammate code and Jetson kit.** Cloned the team repo and built
`understory_nav` (its 10 tests pass). Proved the mission-to-panorama handshake. Wrote
`pi/scout_nav.launch.py` because the teammate's launch file targets Humble: on Jazzy slam_toolbox
needs lifecycle activation, twist_mux defaults to `TwistStamped`, and Nav2 plugin names use `::`.
Rebuilt the image with Nav2 and exported it. Ran a simulated survey end to end. Added
`scout_up.sh --nav`. Wrote `jetson_up.sh`. Moved the Pi code into the repo and merged it as PR #1.

**Session 3, Sat morning, rundown.** Asked for a full written summary. Wrote `~/SCOUT_RUNDOWN.md` on the Pi.

**Session 4, Sat morning, Jetson brief.** Asked for paste-in instructions for the Jetson. Wrote
`~/JETSON_BRIEF.md` on the Pi. This file supersedes both.

**Session 5, Sat 11 AM to 12 PM, this handoff.** It ended when the Pi lost power mid-test.
- *"Refer to old chats, what is next, is the Pi good, check the Unity progress."* Found the Pi
  rebooted with no sensors plugged in, on eduroam, no ROS running, and the clock 5 h 44 min slow.
  Fixed the clock. Reviewed Kevin's 11 commits and his two requests. Fast-forwarded the Pi's clone.
- *"Make all the changes, you may push, write a handoff in the repo."* With LiDAR and camera plugged
  back in: switched to the hotspot and restarted the stack. Changed the panorama node to always send
  frames. Wrote the real OWL-ViT backend, the species node with BioCLIP, the localizer with its
  geometry module and 14 tests, `fake_sensors.py`, `Dockerfile.ai`, `scout_ai_up.sh`,
  `ai_selftest.sh`. Made `jetson_up.sh` start the AI and `scout_down.sh` stop it. Tested all of it
  on the Pi. Wrote this file.
- Found and fixed along the way: OWL-ViT box heights were scaled by the image width (boxes ran off
  the bottom of the frame); a non-plant ceiling decoration was named cogongrass until the "not a
  plant" list was added; a 12-frame burst at 50 ms spacing overflowed a slow subscriber, so frames
  are now 150 ms apart.
- Installed `transformers` and `open_clip_torch` into `~/cv-env` on the Pi host for quick model tests.

**Session 6, Sat 12:10 PM, resume after the Pi lost power.** *"Resume from our last chat; the Pi
disconnected midway through your camera testing. Hotspot, LiDAR and cameras are connected. Remember
to document the changes for the Jetson handoff."*
- Nothing was lost: all of session 5's work was still on disk, uncommitted, on branch
  `perception-pins`. Recovered the context from the saved session transcript.
- Checked the Pi after the reboot: on the hotspot at `172.20.10.10`, clock correct to within a few
  seconds of GitHub's, LiDAR and Brio camera both present, containers running.
- Restarted with `~/scout_up.sh --nav`: `/scan` 10.7 Hz, camera 15.0 Hz, `/mission/state` `IDLE`,
  TF `map -> base_link` ok, ports 10000 and 8765 listening.
- Rebuilt the workspace; 14 `scout_perception` tests and 10 `understory_nav` tests pass.
- Finished the test that was cut off: `ai_selftest.sh` at threshold 0.05 named all 5 species and
  made 5 pins. Made 0.05 the default in `scout_ai_up.sh` and `ai_selftest.sh`.
- Ran the real AI on the live camera for a few minutes: `/detections` publishing at about 0.3 Hz,
  no false species or pins. The camera was pointing up at the building and was partly covered, so
  **no real plant has been in front of the live camera yet** (section 9, item 3).
- Found the Pi overheating with the AI on (83 °C, throttled). Stopped the AI nodes. Sensors,
  mapping, Nav2, mission and panorama were left running.
- Committed and pushed the work to branch `perception-pins` and opened PR #2 into `main`. The PR is
  **not merged**: Alvaro or Kevin has to merge it.

**Session 7, Sat 12:35 PM, check after another Pi reboot.** *"You got disconnected again, check the
previous chat and check that everything is connected. The Jetson is connected and Claude is being
installed on it."*
- The Pi had rebooted again (up 2 minutes). Hotspot `172.20.10.10`, clock within seconds of GitHub's,
  LiDAR and Brio camera present, both containers up, 56 °C, not throttled. No ROS nodes were running.
- **PR #2 is merged** (12:25 PM). The Pi's clone is now on `main` at `006a01a`. On the Jetson, clone
  and stay on `main`; skip the `git checkout perception-pins` line in section 7.
- Restarted with `~/scout_up.sh --nav`: `/scan` 10.0 Hz, camera 14.8 Hz, `/mission/state` `IDLE`,
  TF `map -> base_link` ok, ports 10000 and 8765 listening. The AI was left stopped (heat).
- A second device is on the hotspot at `172.20.10.14`, answering ping and with SSH open. It is
  probably the Jetson; not confirmed. Nothing has been run on it from the Pi.
- Before `jetson_up.sh` runs on the Jetson, the Pi must drop to sensors only:
  `~/scout_down.sh --keep && ~/scout_up.sh`.
- *"Start on the Whisper node."* Wrote `whisper_node.py`, `voice.py`, `test/test_voice.py` and
  `pi/scripts/voice_test.py`, on branch `whisper-node`. `scout_ai_up.sh` starts the node and
  `--stop` / `scout_down.sh` stop it. 26 `scout_perception` tests pass. Results are in section 5a.
- **Pi and Jetson now talk.** Around 1:00 PM the Pi was switched to sensors only, and from 1:10 PM
  the Pi could see `slam_toolbox`, Nav2, `mission_manager` and `panorama_node` running on another
  machine, with `/mission/state` `IDLE` arriving on the Pi. This was seen from the Pi only.
- One synthetic clip sent on the live domain: the Pi's Whisper node published its text and the
  remote `mission_manager` was subscribed to `/voice/text`. Its log was not read to confirm receipt.
- Left running on the Pi: sensors, Foxglove, Quest endpoint and the Whisper node. Detector, species
  and localizer were stopped again (the Pi reached 70 °C in two minutes with them on).

**Session 8, Sat 12:45 to 3:40 PM, on the Jetson (three chats; the board froze once).** Branch `jetson-bringup`.
- **GPU image** `scout-ros-ai-gpu` built from `pi/jetson/Dockerfile.gpu` (13.6 GB, PyTorch 2.14.1 + CUDA).
  The models were copied from the Pi's cache, so the Jetson runs offline.
- **The board froze at about 1:50 PM** (watchdog reset) with detector, species and Whisper each in their
  own GPU process. It has 8 GB and no swap, and each GPU process loads over 1 GB of CUDA libraries.
  Three fixes, all in this branch:
  - `ai_node` runs `detector_node` and `species_node` in one process. `AI_ONE_PROCESS=1` selects it in
    `scout_ai_up.sh` and `ai_selftest.sh`. They are still two ROS nodes with the same topics.
  - Both models run in half precision on a GPU (CPU is unchanged).
  - Whisper stays on the CPU by default (`WHISPER_DEVICE=cpu`).
- **Measured on the Jetson GPU** (`AI_ONE_PROCESS=1`, half precision, Nav2 and mapping running):
  five-photo self-test PASS 5 of 5 with the same confidences as full precision, `/detections` 4.4 Hz
  in the self-test and 8.1 Hz on the live camera (Pi CPU: 0.25 Hz). Peak board power 9.7 W; it was
  14.6 W at full precision.
- **Memory is still tight.** With the AI, Whisper, Nav2 and a desktop with Firefox open, about 0.9 GB
  stays available and it dips under 0.7 GB while the models load or a clip is transcribed. `~/fetch_ws/logs/mem_guard.sh` kills the
  AI nodes under 700 MB so the board cannot freeze again; it fired four times. Closing Firefox frees about
  1 GB. The Jetson image has no zram swap; turning it on needs sudo and was not done.
- **Voice on the Jetson CPU** (`whisper-base.en`, synthetic clips, ROS domain 43): "come back home",
  "keep going" and "manual" correct, "start survey" heard as "star survey", 3.5 to 6 s per clip.
  The noise clip produced the word "you". Not tried with a real voice.
- **"System throttled due to over-current"**: the counter (`/sys/class/hwmon/hwmon2/oc3_event_cnt`)
  reached 47 between 1:54 and 2:09 PM, with two and three GPU processes loading at once in 25 W mode.
  The limit is 5.05 A on the 5 V input. Since the changes above the highest reading is 3.4 A and the
  counter has not moved in an hour. `~/fetch_ws/logs/power_watch.py` logs it once a second.
  **One more event at 4:04:44 PM** (count 48) with the board at about 2.0 A and 10 W, sampled 25 times a
  second, so it was a spike shorter than 40 ms: several `ros2` commands started at that moment while
  the GPU was busy. That is 1 event in two hours against 47 in fifteen minutes. The board slows its
  clocks for an instant and shows the banner; nothing else happens. `sudo nvpmodel -m 0` (15 W mode)
  should stop them at the cost of speed; not tried.
- **Quest app on `main` (Kevin, 4 PM) checked against our side:** its contract classes match the pin,
  bubble and reading JSON; its panel buttons send start / capture / resume / manual / return / stop on
  `/voice/text`, all in the mission manager's vocabulary; Whisper's "star survey" still parses as start.
  The app's notes say the endpoint is on the Jetson. It is on the Pi: `172.20.10.10`, port 10000.
- `scout-ai` is now created with `--init`. Without it stopped nodes stayed as zombies, and the
  script's `pgrep` checks reported them as running.
- **Pi dropping off the hotspot: fixed by moving the hotspot to 5 GHz** (iPhone: turn off "Maximize
  Compatibility", then restart the hotspot). On 2.4 GHz channel 6, from 2:17 PM, the Pi stopped answering
  within 20 s whenever the Jetson subscribed to its topics, and came back 30 s after the Jetson's ROS
  nodes stopped (three trials); its kernel log showed the Wi-Fi chip stalling (`brcmf_sdio_bus_rxctl:
  resumed on timeout`). On 5 GHz (3:20 PM on, after a Pi power cycle): 0% ping loss, `/scan` 10.0 Hz and
  camera 15.0 Hz on the Jetson with Nav2 and the AI running, over ten minutes of checks.
- **Whisper is back on the Pi.** On the Jetson, a voice clip arriving while the plant AI ran took
  available memory under 700 MB and the guard killed the AI. The Pi is idle in sensors-only mode and
  transcribes a clip in about 6 s. `scout_ai_up.sh --voice-only` starts only the Whisper node; it is
  new in this branch and the Pi's copy does not have it yet, so at 3:36 PM the node was started on the
  Pi by hand with `docker exec -d scout-ai ... ros2 run scout_perception whisper_node`. **It does not
  come back after a Pi reboot.** Without Whisper the Jetson keeps about 1.3 GB available with Firefox open.
- **Quest app checked without a headset** (Kevin's branch `quest-app`, not merged into this one).
  `pi/scripts/quest_probe.py` connects to the Pi's ROS-TCP-Endpoint the way the app does, with the same
  topics and types as `Unity/Assets/Scripts/Ros`. Through `172.20.10.10:10000` it received
  `/mission/state` 1 Hz, `/map` (226x216), camera 15 Hz at 52 KB, and a WAV sent on `/voice/audio` came
  back on `/voice/text` 6.3 s later and reached `mission_manager` on the Jetson. Two things for Kevin:
  - **`/pose` sent nothing while the robot stood still.** slam_toolbox publishes it only after a scan
    update, so the app has no robot position until the robot first moves.
  - A `capture` (3:53 PM, robot standing still, test bubble `m1-b01` on the live network) reached the
    probe: the bubble JSON and 12 frames on `/survey/bubble_images`. Pins and readings were not seen
    (no listed plant in view, no `/sensors`). Not tested: teleop and e-stop (the probe never publishes
    them), and a real headset.
- `scout_ai_up.sh` printed "/detections is NOT publishing" while `/detections` was at 9 Hz moments
  later. In the 40 s after the models load a new subscriber gets nothing (cause not found), so the
  check now tries three times. It also no longer builds the CPU image when `scout-ai` is already running.
- Left running at 3:40 PM. Pi: sensors, endpoint, Foxglove, Whisper. Jetson: mapping, Nav2, mission,
  panorama, `ai_node`, localizer. Start the Jetson side with `pi/jetson/jetson_up.sh`; on the Jetson it
  now defaults to the GPU image, one process and no Whisper.
- **4:15 PM, both machines rebooted on request.** Pi: now on `main`; after the reboot `~/scout_up.sh`
  then `~/scout_ai_up.sh --voice-only` brought back sensors (10 Hz, 15 Hz), endpoint and Whisper, and
  a clip through the endpoint came back as text in 6.9 s, so `--voice-only` is tested on the Pi. The
  Jetson's nodes kept running through the Pi's reboot and reconnected by themselves. Jetson: rebooted
  at about 4:20 PM; **run `~/start_understory.sh` after it comes up** (memory guard, power logger,
  then `jetson_up.sh`). Nothing starts by itself there except the two containers.
- **4:22 PM, Jetson back up after the reboot.** `~/start_understory.sh` brought everything back with no
  other step: mapping, Nav2, mission, panorama, `ai_node` and localizer. Checked from the Jetson at
  4:32 PM: `/scan` 10.1 Hz, camera 15.4 Hz, `/detections` 9.8 Hz, `/mission/state` `IDLE`, TF
  `map -> base_link` ok, 2.7 GB available (no Firefox open), 10 W, over-current counter 0 since boot.
  The script's own "/detections" check failed twice and passed on the third try, as before. The script
  used to hold the terminal after finishing (its two background helpers kept the output open); fixed.

**Session 9, Sat 4:40 to 5:20 PM, TensorRT detector on the Jetson.** *"Go ahead with NanoOWL + TensorRT."*
- **What it is.** `nanoowl_trt` runs OWL-ViT the way NanoOWL does: the image side (vision transformer, box
  head, class head) is one TensorRT engine, and the prompts are encoded once with PyTorch at startup, so
  they can change without a rebuild. It is written against TensorRT directly in `backends.py`; the
  `nanoowl` package itself is not installed (it needs `torch2trt` and was written for older TensorRT).
- **Image.** `Dockerfile.gpu` now adds `tensorrt-cu13` 11.4, `onnx` and `onnxscript`. The image was rebuilt
  and `scout-ai` recreated from it. TensorRT 11 has no half-precision switch; the precision comes from
  the ONNX file, so the export is done in half precision.
- **Engine.** `docker exec scout-ai bash -c 'source /fetch_ws/install/setup.bash && python3
  /fetch_ws/src/Understory/pi/scripts/build_owl_engine.py'` with the AI nodes stopped. 103 s, 189 MB, at
  `~/fetch_ws/models/owlvit-base-patch32.engine` (not in the repo: an engine only runs on the kind of GPU
  that built it). Lowest available memory during the build: about 0.8 GB.
- **Speed** (`pi/scripts/detector_bench.py`, 100 frames of 640x480, live AI stopped, mapping and Nav2 running):

  | | PyTorch, half precision | TensorRT |
  | --- | --- | --- |
  | Model alone | 61.8 ms (16.2 per second) | 19.0 ms (52.7 per second) |
  | Whole frame (resize + model + box filtering) | 78.1 ms (12.8 per second) | 40.3 ms (24.8 per second) |
  | Live `/detections`, 15 Hz camera | 9.8 Hz | 15.3 Hz (every frame) |

- **The resize to 768x768 now runs on the GPU in both backends** (6 ms instead of 26 ms). Before that
  change the PyTorch whole frame was 103.5 ms. The resized image differs slightly from the CPU one
  and some scores moved (one box on the cogongrass photo went from 0.21 to 0.40); the self-test result
  did not change.
- **Same answers.** Boxes on the five test photos match PyTorch's to a few pixels and about 0.02 in
  score. `ai_selftest.sh` with `AI_ONE_PROCESS=1`: PASS 5 of 5 with both backends, same five pins, same
  confidences.
- **A bug found and fixed on the way:** with the resize on PyTorch's default CUDA stream and the engine on
  its own, every frame got the boxes of the frame before it. All GPU steps now run on one stream;
  200 alternating plant and grey frames gave 0 wrong answers.
- **Default.** `jetson_up.sh` picks `nanoowl_trt` when the engine file exists and the image is
  `scout-ros-ai-gpu`. `DETECTOR_BACKEND=owlvit_torch` goes back to PyTorch. The Pi is unchanged.
- **Over-current counter went from 0 to 14** between 5:06 and 5:08 PM, all during the benchmark and
  self-test runs (board at 13 to 15 W). None since; the live stack sits at about 10.5 W with 2.4 GB available.
- `~/start_understory.sh` now returns when it is done (checked on this restart).
- Left running at 5:17 PM. Jetson: mapping, Nav2, mission, panorama, `ai_node` (TensorRT detector),
  localizer. Pi: sensors, endpoint, Foxglove, Whisper. `/scan` 10.0 Hz, camera 15.2 Hz, `/mission/state` `IDLE`.
- Not tested: a real plant in front of the live camera with the new backend.

**Session 10, Sat 7:00 to 8:20 PM, Kevin's pushes, logger, AMD.** *"Focus on what is next, integrate Kevin's pushes, and integrate AMD's challenge (FSR 4, or ROCm on the Radeon cloud hardware)."* The Jetson had just been power-cycled.
- **Merged `quest-app` (Kevin, 4:20 to 6:40 PM) into `jetson-bringup`:** ESP32 mecanum firmware and `pi/scripts/esp32_bridge.py` (he marks both untested on hardware), `pi/scripts/pose_from_tf.py`, Quest fixes, and his note that the headset connected to the Pi live at 6:20 PM with the Pi on his hotspot "iPhone (2)" at `172.20.10.3`.
- **`/pose`:** `scout_nav.launch.py` now starts `pose_from_tf.py` (argument `pose:=false` turns it off). Seen on the Jetson: "TF found, publishing /pose".
- **ESP32 bridge:** `scout_up.sh` starts it when a USB serial device other than the LiDAR is plugged in (`NO_DRIVE=1` skips it) and `scout_down.sh` stops it. **Syntax-checked only**: the Pi could not be reached. `pyserial` 3.5 is in the `scout-ros` image. The firmware has no sensor wired yet, so `/sensors` stays empty until someone adds one.
- **Whisper, Kevin's request for a command prompt:** `whisper_node` has a `prompt` parameter, default "Robot commands: start survey, stop, return home, come back, manual, capture, resume." On the nine synthetic clips it fixed "star survey" -> "start survey" and changed nothing else, **but the noise clip came out as "start survey"**. So the node now also drops a transcript whose mean token log-probability is under `min_logprob` (-1.0): speech scored -0.18 to -0.67, noise and silence -1.27 and -1.69. Through ROS on domain 43: four commands published, the noise clip logged as dropped. Synthetic voices only. The log line shows the score, for tuning with a real voice. **The Pi runs Whisper and does not have this code yet.**
- **Mission logger, new: `logger_node`** (`mission_log.py`, 7 unit tests). Nothing in the repo wrote the mission folder, so the cloud steps had no real input. It writes `~/fetch_ws/missions/<id>/` `bubbles.jsonl`, `pins.jsonl`, `readings.jsonl`, `frames/<bubble_id>_<index>.jpg`, `map.pgm` + `map.yaml` (map saved at each bubble). `scout_nav.launch.py` starts it (`logger:=false` turns it off); `jetson_up.sh` starts it alone when mapping runs on the Pi. Tested on domain 43 against `fake_survey.py`. The logger is listed under Teammate 4 in `AGENTS.md`; if theirs arrives, run only one.
- **AMD challenge.** FSR 4 does not fit: it is an upscaler for Radeon RX 9000 desktop cards, and our graphics run on a standalone Quest. The ROCm half is what the project already planned ("deep in the cloud"): Kevin's `splat/` (MASt3R + gsplat on the W7900). Added a second ROCm workload, **`amd/deep_pass.py`**: after a mission it re-reads every bubble frame on the W7900 with OWLv2 large + BioCLIP and writes `pins_deep.jsonl`, `crops_deep/` and `deep_report.json` (speed, GPU memory, and which live pins it confirmed or added). Details, the test table and what is untested: `amd/README.md`. **Nobody has run it or `splat/` on the AMD box from this machine; there are no AMD credentials here.**
- **A mistake to know about:** at 7:50 PM `~/start_understory.sh` started mapping, Nav2 and the mission manager on the Jetson while the Pi was off the network. The Pi then appeared for about two minutes with **its own** `scout_up.sh --nav` stack and a Quest connected, so two slam_toolbox, mission manager and twist_mux instances were on the network for that time. The Jetson's launch was stopped at about 8:05 PM. **While the Pi runs `--nav`, do not run `jetson_up.sh` without `~/scout_down.sh --keep && ~/scout_up.sh` on the Pi first.** `jetson_up.sh` checks for this, but cannot see a Pi that is off the network at that moment.
- **Network, unresolved.** The Jetson is on "Alvaro's iPhone" (`172.20.10.11`). The Pi answered at neither `.10` nor `.3` for most of the session, was visible at `.3` from about 7:51 to 8:05 PM, then gone again. Both phones hand out `172.20.10.x`, so the Pi may be moving between them. Pi and Jetson must be on the same hotspot.
- Left running at 8:20 PM on the Jetson: `ai_node` (TensorRT detector), localizer, `logger_node`, memory guard, power logger. Not running here: mapping, Nav2, mission, panorama (the Pi has them).
- **For Kevin (fixed later, see below): `splat/align.py` was an empty file at the tip of every branch**, and `mast3r_poses.py` imports `align_sim3`, `apply_to_points` and `apply_to_pose` from it. As it stands the MASt3R step fails at import, so `splat/run.sh` always falls through to the Depth Anything point cloud, and `python -m pytest splat/tests` fails to collect. The first commit has a 1.5 KB version, emptied by the "rescue: uncommitted work" commit: look at `git show 304f251:splat/align.py` before restoring it. Not touched (`splat/` is his).
- **8:18 to 8:50 PM, pushed, merged, both machines restarted.** The Pi came back on Alvaro's hotspot at **`172.20.10.3`** (older entries in this file say `.10`). `jetson-bringup` was pushed through the Pi and merged into `main` as **PR #7**. The Pi pulled `main`, rebuilt, 33 tests pass there; nothing was running on it, so `~/scout_up.sh` and `~/scout_ai_up.sh --voice-only` were started (`/scan` 10.0 Hz, camera 15.0 Hz, Whisper with the new prompt and floor). No ESP32 was plugged in, so the bridge did not start. Then `~/start_understory.sh` on the Jetson: one each of slam_toolbox, mission manager, twist_mux, panorama, logger and pose publisher on the network, `/mission/state` `IDLE`, `/pose` 8.8 Hz, `/detections` 7.6 Hz, 2.0 GB available.
- **Fixed after that (PR #8):** `scout_up.sh` printed `172.20.10.10` whatever the Pi's address was; it now prints the real one. Both start scripts ask for the node list without the ROS daemon's cache before deciding that no other mapping stack is running. `splat/align.py` restored from commit `304f251` (it was emptied by the "rescue" commit): `splat/tests` 7 pass. **Kevin should check that restored file is the version he wants.**
- Git push from the Pi over SSH needs `git -c credential.helper='!gh auth git-credential' push origin <branch>`; a plain `git push` there fails with "could not read Username".
- Left on disk, safe to delete: `~/fetch_ws/logs/deep_test/` (the photo test mission).

**Session 11, Sat 8:20 to 8:40 PM, on the Pi, at the same time as the end of session 10.** *"Read the repo and implement the changes asked for in the handoff."* Branch `pi-session-11`. The Pi had rebooted at 8:16 PM and was on `main` at PR #7, running sensors, endpoint, Foxglove and Whisper (started by the Jetson session over SSH). Then: *"Pull PR 8 or the new repo changes, take a look at everything."*
- **Network.** The Pi is on the hotspot whose name is "iPhone (2)" (`nmcli`; `AGENTS.md` calls that one Kevin's, session 10 calls it Alvaro's) at `172.20.10.3`, 5 GHz, clock within seconds of GitHub's. From 8:26 PM the Jetson's whole stack was visible from the Pi (slam_toolbox, Nav2, mission manager, panorama, logger, `pose_from_tf`, detector, species, localizer), so **both machines are on the same hotspot again**. Arriving on the Pi: `/mission/state` `IDLE`, `/detections` 8.2 Hz, `/map` 174x305, `/pose` about 4 Hz (10 Hz is sent). `tf2_echo map base_link` on the Pi found no `map` frame in 8 s; nothing on the Pi needs it.
- **The two-slam guard works.** `~/scout_up.sh --nav` on the Pi printed "slam_toolbox is already running on another machine" and started nothing. The Pi stays in sensors + Whisper mode.
- **Whisper prompt and confidence floor, on the Pi** (session 10 left this open). ROS domain 43, the synthetic clips: "start survey", "stop", "come back home", "take a picture", "manual", "keep going" all published (scores -0.18 to -0.67, 2.5 to 2.8 s each, 7.3 s for the first); the noise clip came out as "start survey" with score -1.69 and was dropped; silence was ignored. The live node was started after the pull, so it runs this code. Still no human voice.
- 33 `scout_perception` tests and 12 `understory_nav` tests pass on the Pi. `logger_node` and `ai_node` are already in the Pi's install.
- **ESP32 bridge, first contact with the board.** At about 8:29 PM someone plugged in the Adafruit QT Py ESP32-S2. `scout_up.sh` picked it (not the LiDAR), started `esp32_bridge.py`, and the log shows the port open at 115200 and the firmware's line `# status shield=ok moving=0 cmd=(0.00 0.00 0.00) cmds=0`. `/cmd_vel` has one publisher (the Jetson's twist_mux) and the bridge subscribed. **No drive command was sent from here**, so wheels turning is still unproven. `/sensors` has a publisher and no data (no sensor in the firmware).
- **The LiDAR was unplugged at the same moment** (kernel log: its CP2102 disconnected at 8:28 PM, the ESP32 appeared 40 s later), so `/scan` stopped and the Jetson's mapping has no scans. The LiDAR node does not recover by itself: plug the LiDAR back in, then `~/scout_down.sh --keep && ~/scout_up.sh` on the Pi. **Still unplugged at 8:40 PM.** If the Pi has too few free USB ports for LiDAR + camera + ESP32, that needs a hub.
- `scout_up.sh`: a missing `/scan` with no LiDAR on USB now says so and gives the fix. (This session also fixed the fixed `172.20.10.10` in its last line; PR #8 from the Jetson session did the same thing first, so its version was kept in the merge.)
- **PR #8 read and merged into this branch.** `splat/align.py` is back (Kevin to confirm the version).
- **A second mistake of the same kind, 8:32 PM, about one minute.** With PR #8's check (`ros2 node list --no-daemon --spin-time 6` only), `~/scout_up.sh --nav` was run on the Pi as a test and **started a second slam_toolbox, Nav2, mission manager and twist_mux beside the Jetson's**. The fresh-discovery list did not contain the Jetson's nodes at that moment (three more tries in the next two minutes also returned none, and `/mission/state` did not arrive), while the ROS daemon's list had them. Ten minutes later the same command saw them 6 times out of 6, so the hotspot was dropping discovery traffic for a while (ping to the phone: 36 to 150 ms). The Pi's copy was stopped by 8:34 PM; the Jetson's stack was not restarted by it (same launch node name before and after) and showed `IDLE`, one publisher on `/cmd_vel`. **If the Jetson's map looks wrong after 8:32 PM, restart mapping there.**
- **`scout_up.sh --nav` now asks both ways** (fresh discovery and the daemon) and starts nothing if either lists slam_toolbox; after starting, it warns loudly if slam_toolbox is listed twice. Checked on the Pi: refused with the Jetson's stack up. `jetson_up.sh` still has the fresh-discovery check only; it was not changed here because it cannot be tested from the Pi. **Neither check can see a machine during a network dropout, so the rule stands: do not run `--nav` on the Pi while the Jetson is mapping.**
- The camera measured from the Pi itself varied between 7 and 15 Hz at 8:38 PM and the start script's 8 s check reported it missing twice; the node was running the whole time. Not investigated.
- Left running at 8:40 PM on the Pi: camera, endpoint, Foxglove, Whisper, ESP32 bridge. LiDAR node running with no device. No mapping on the Pi.
- **8:43 to 8:52 PM, LiDAR back, and a third duplicate stack.** The LiDAR was plugged back in at 8:43 PM (the Pi now has LiDAR, camera and ESP32 on USB together). `~/scout_down.sh --keep && ~/scout_up.sh` at 8:44 PM: `/scan` 9.6 Hz, bridge connected. **At 8:45:44 PM someone else ran `~/scout_down.sh && ~/scout_up.sh --nav` on the Pi** (it is the last such line in the Pi's shell history; not this session). Its guard did not see the Jetson and it started mapping, Nav2, mission and twist_mux on the Pi. For about two minutes the network had two mission managers, two twist_mux nodes both publishing `/cmd_vel` to the live ESP32 bridge, two loggers, two panorama nodes and two `/pose` publishers. The Pi's copy was stopped at 8:48 PM because the Jetson's stack holds the AI and localizer; after that one of each, one `/cmd_vel` publisher. **Whoever needs the Pi to map: stop the Jetson's stack first, or tell the Jetson session.**
- **The hotspot is the cause.** Ping from the Pi to the phone between 8:45 and 8:52 PM: 8 ms to 1.1 s, once 50% loss. In the same minutes the Jetson's nodes and topics appeared and disappeared from the Pi (`/mission/state` arrived in one check of three, `/detections` in none), while the Pi's own `/scan` and camera stayed at 10 and 15 Hz. Not fixed. Things to try: phone next to both machines, nothing else on the hotspot, `SCOUT_PEER` on both sides (section 7), or mapping on the Pi alone.
- The Pi's `scout-ai` container was recreated (now with `--init`). Before that `scout_down.sh` had stopped Whisper and `scout_ai_up.sh --voice-only` said "already running" because of the zombie. Whisper is running again and subscribed to `/voice/audio`.
- Left running at 8:52 PM on the Pi: LiDAR, camera, endpoint, Foxglove, ESP32 bridge, Whisper. No mapping on the Pi.

**Session 10, continued, Sat 8:40 to 10:25 PM, on the Jetson.** *"I connected the LiDAR now, do whatever you need"*, then *"check the repo for any changes and then work on what needs to be done."*
- **8:39 PM: the Jetson moved to the hotspot "iPhone (2)" while ROS was running** (address `.11` to `172.20.10.4`). Its nodes kept running but no longer heard the Pi: `/scan` 3 Hz, 15% ping loss. Fix: stop every ROS node on the Jetson, `ros2 daemon stop`, `~/start_understory.sh`. After that 0% loss and `/scan` 10 Hz. **A change of network or address under a running stack needs a full restart of that stack.**
- Since then, one of each node on the network (checked again at 10:05 PM, 43 nodes, no name twice): Jetson has mapping, Nav2, mission manager, twist_mux, panorama, logger, `pose_from_tf`, detector, species, localizer; Pi has LiDAR, camera, endpoint, Foxglove, ESP32 bridge, Whisper. Quest connected from `172.20.10.2`.
- Rates on the Jetson at 10:08 PM: `/detections` 15.5 Hz, camera 14.0 Hz, `/pose` 10.0 Hz, `/scan` 10.5 Hz. `tegrastats` with everything running: 5.3 of 7.5 GB RAM, 53 °C, 9 to 11 W.
- **Robot driving, state at 10:05 PM: the bridge is connected (`shield=ok`) and has received about 2,900 commands, all zero.** No `moving=1` line in `esp32_bridge.log` since the bridge started at 9:34 PM, no message on `/cmd_vel_teleop` in 12 s, and `/mission/state` was `STOPPED` (B button or "stop"). The twist_mux e-stop lock holds until the Quest publishes `false` on `/estop`. Wheels turning from the Quest is still unproven.
- PR #8 was merged at 8:27 PM. The Jetson's repo is on `main` at Kevin's `56fe2fd` (bridge re-sends the last command at 20 Hz and stops on `/estop`; firmware re-sends stop while idle) plus branch `jetson-sat-late`. Nothing in those commits runs on the Jetson, so nothing was rebuilt.
- `jetson_up.sh` now asks both ways for an existing slam_toolbox (fresh discovery and the ROS daemon), the same as the Pi's `scout_up.sh --nav` in PR #9. Checked with the stack up: both lists contain it.
- Whisper was not running on the Pi at 10:05 PM (the Pi's sensors had been restarted at about 9:55 PM). Started again with `~/scout_ai_up.sh --voice-only` at 10:11 PM; the log shows the node running.
- **The first real pins were all wrong.** The logger wrote `~/fetch_ws/missions/m1/pins.jsonl` from the live camera between 8:57 and 10:12 PM: 12 pins, no bubble. The crops are a face (Brazilian pepper, 0.93), a garland of purple artificial flowers (air potato 0.97, cogongrass, saw palmetto), a T-shirt print and blurred frames. So the logger works with real data, and the classifier pinned things that are not the five plants.
- **Fix: `OTHER_LIFE` in `species_labels.py`** (20 scientific names: Homo sapiens, cat, dog, wisteria, pothos, ...) is scored beside the five species and the phrase list; if one wins, the crop is dropped. `species_node` `min_confidence` 0.5 to 0.6. Measured with BioCLIP on the Pi's CPU on the first 11 crops and the five `test_plants` photos: before, the 11 crops scored 0.41 to 0.95 for a listed species; after, 8 lose to another name and the other 3 score 0.42, 0.50 and 0.52, so all 11 are dropped; the five photos stay at 1.00. Adding more phrases ("a photo of a human face", "artificial flowers", ...) changed 2 of 11. The cosine similarity alone does not separate them (a good Brazilian pepper photo 0.264, the garland 0.283).
- **Limits of that test:** wisteria is in the list because the garland was in the room, so the 11 crops are not an independent test. The five good photos are clean web photos; a real or printed plant seen by the robot's camera will score lower than 1.00 and may now fall under 0.6. Not measured. If real plants stop being pinned, lower it: `-p species_node:min_confidence:=0.5`.
- The Jetson's AI node was restarted at 10:18 PM with the new list (only `ai_node`; mapping, mission and the localizer were not touched). 35 `scout_perception` tests and 7 `amd` tests pass. `amd/deep_pass.py` still uses the phrase list only.
- **Before recording the real mission, move `~/fetch_ws/missions/m1` away** (it holds the 12 wrong pins and their crops), or the dashboard, the deep pass and the Quest get them too.
- **10:41 PM: done.** The folder is now `~/fetch_ws/missions/m1_false_alarms_sat` and the Jetson's `ai_node` and localizer were restarted, so pin numbers start again at `m1-p01` and the next capture writes a clean `missions/m1`. After the restart: `/detections` 15.6 Hz, camera 15.0 Hz, `/scan` 9.5 Hz. PRs #9, #10 and #11 (the dashboard) are merged; the Jetson is on `main`.
- **10:40 PM: the motor shield stopped answering.** `esp32_bridge.log` on the Pi: `shield=MISSING`, `ERROR: I2C to motor shield failed (code 5, 58 so far): loose SDA/SCL/GND wire, or motor noise on the I2C lines`, one more every 2 s. It was `shield=ok` until at least 10:05 PM. Hardware: check the three wires between the QT Py and the shield and the shield's power. Still no `moving=1` in the log.
- **Memory on the Jetson at 10:43 PM: 860 MB available, no swap.** Firefox had been opened on the Jetson's desktop (about 1 GB) and a second Claude session was running. With the browser closed it was 2.2 GB. Do not browse on the Jetson while the stack runs.
- For a dry run of the AMD steps before a real mission exists, `fake_data/missions/m1` has 64 frames, a map and bubbles.
- **Mapping was stuck from 10:14 to 10:55 PM and nothing reported it.** `/pose` had stopped and `tf2_echo map base_link` found no transform. slam_toolbox was running and using CPU, and `map -> odom` was still on `/tf` 30 times a second, but with a time stamp 37 minutes old (measured with `~/fetch_ws/logs/tfcheck.py`), so every lookup failed. `/scan` was 9.5 Hz and `odom -> base_link` was current. Cause not found; the old log is `~/fetch_ws/logs/nav_until_2255.log`. Fix: `docker exec scout pkill -INT -f 'ros2 launch'`, then `~/start_understory.sh` (the map starts again from empty). After it: `map -> odom` under 1.2 s old, `/pose` 10.0 Hz, no node name twice. **If the robot marker in the Quest freezes while the robot moves, do this.**
- 10:47 PM: the ESP32 is no longer on the Pi's USB (only the LiDAR is listed) and the Quest is not connected.
- **Hugging Face, 11:30 to 11:55 PM.** The token (account `a1vcm`, write) and `HF_DATASET_REPO=a1vcm/understory-missions` are in `.env` at the repo root on the Jetson (not committed). New `amd/hub.py` (`upload`, `pull`, `push`) and `amd/run_all.sh <id>`: the W7900 box pulls a mission from the dataset, runs the deep pass and the splat, and pushes the results back, so it needs no route to the Jetson. Done for real from the Jetson's `scout-ai` container: `upload` of `fake_data/missions/m1` and `m2` (155 files, dataset created **private**) and `pull m1` into an empty folder (64 frames, map, bubbles, pins). **`push` and `run_all.sh` have not run**: they need deep-pass output, which needs the box. `--public` on the first upload, or the dataset's settings page, makes it public; real frames show whoever stood near the robot.
- **The AI node was killed twice by the memory guard, 10:40 and 11:17 PM, both times right after Firefox was opened on the Jetson's desktop.** `~/fetch_ws/logs/mem_watch.log`: `GUARD: avail 687MB < 700MB, killing AI nodes`. Nothing restarts it, and it is **still down at midnight**. With Firefox open there is not enough memory for it (about 2.6 GB). Close the browser, then `~/start_understory.sh`.
- **11:35 to 11:50 PM the hotspot was unusable:** ping to the phone 2 to 4 s with 25 to 60% loss, and no `/scan` or camera from the Pi. It recovered by itself (9 ms, 0% loss at 11:52 PM). The Hugging Face upload and the browser on the Jetson were using the same hotspot at the time. Do not upload or browse over the robot's hotspot during the demo.
- **The Pi was rebooted at 11:39 PM (during that outage) and came up with its own mapping stack** (`scout_nav.launch.py`: slam_toolbox, Nav2, mission manager, twist_mux, logger, `pose_from_tf`), so at 11:55 PM every one of those names was on the network twice and two twist_mux nodes fed the ESP32 bridge. **The Jetson's copy was stopped at 11:57 PM**, because the Pi's was the newer one and somebody may be working there. After that: no name twice, one `/cmd_vel` publisher, `/mission/state` `IDLE`, `/pose` 9.5 Hz. **Mapping now runs on the Pi and missions are logged on the Pi** (`~/fetch_ws/missions` there). To move mapping back to the Jetson: on the Pi `~/scout_down.sh --keep && ~/scout_up.sh`, then on the Jetson `~/start_understory.sh`. Whisper was not running on the Pi after its reboot.
- **The Pi's GitHub login stopped working at about 11:50 PM** (`gh auth status`: "The token in hosts.yml is invalid"), so nothing can be pushed from the Jetson or the Pi until someone runs `gh auth login` on the Pi. Branch `hf-hub-handoff` is in the Pi's clone and on the Jetson, not on GitHub.

**Session 12, Sun 1:30 to 2:00 AM, on the Jetson.** *"The Pi is connected again, continue on and implement the dashboard and run everything and implement the Hugging Face."* The Jetson had rebooted at 1:21 AM. The Pi is at `172.20.10.3` on "iPhone (2)", had restarted its own `scout_up.sh --nav` stack at 1:30 AM with the ESP32 and LiDAR plugged in and the Quest connected, and has staged, uncommitted work on `pi-session-11` (bridge `--trim`/`--strafe-fix`, `slam_toolbox_pi.yaml`). **Mapping, Nav2, the mission manager, panorama and the logger stay on the Pi.** Nothing in the Pi's clone was touched.
- **Dashboard runs on the Jetson:** `dashboard/run.sh` (new) serves it at `http://172.20.10.4:8501` for any laptop on the hotspot; `--stop` stops it; log in `~/fetch_ws/logs/dashboard.log`. It is not started by `~/start_understory.sh`. `dashboard/.venv` was built without sudo (`dashboard/README.md` has the steps). It uses about 150 MB. **Open it from a laptop, not from a browser on the Jetson** (the memory guard, session 10).
- **Dashboard, new data source "Hugging Face"** (sidebar, shown when `HF_DATASET_REPO` is in `.env`): downloads the dataset to `~/.cache/understory/hf_missions/` and reads it like mission folders, so all four tabs work with no Neon. Done for real at 1:40 AM against the private dataset: 155 files, 71 s over the hotspot the first time, then m1 and m2 listed and "7 invasive plants found -> 1 remaining". With no internet it shows the last download. 2 new tests (8 pass).
- **`dashboard/sync.py` without `DATABASE_URL` now uploads to Hugging Face only** instead of exiting, and creates the dataset private unless `--public` (it used to create it public). Tested with a fake uploader only; the real upload path is the same call `amd/hub.py upload` made on Saturday.
- **What the dashboard shows by default** is `~/fetch_ws/missions` on the Jetson: `m1` (one bubble taken at 12:45 AM from a table top, 2 pins that are not plants) and `m1_false_alarms_sat`. **Neither is a real survey.** For the fake before/after demo choose "Hugging Face", or start with `MISSIONS_DIR=fake_data/missions dashboard/run.sh`.
- **Missions are logged on the Pi while the Pi maps.** After a real survey: `rsync -a a1vcm@172.20.10.3:fetch_ws/missions/ ~/fetch_ws/missions/` on the Jetson (move the Jetson's test `m1` away first), then `dashboard/.venv/bin/python dashboard/sync.py ~/fetch_ws/missions/<id>`. **The dataset's `m1/` and `m2/` are the fake missions; a real `m1` uploaded on top would mix with them.** Delete those two folders on the dataset page first, or record the real missions under other ids.
- **The hotspot is on 2.4 GHz (channel 11) and cannot carry the camera to the Jetson.** With the Jetson's AI subscribed to `/camera/image/compressed`, ping to the Pi went to 0.2 to 2.2 s, the camera arrived at 2 Hz, and `/pose` and `/mission/state` did not arrive; 20 s after the AI was stopped ping was 25 ms. One trial each way. On Saturday at 10 PM the same phone carried 15 Hz.
- **Workaround, running now: `pi/scripts/camera_throttle.py`** (new) on the Pi republishes 3 frames a second on `/camera/image/throttled`, and `CAMERA_TOPIC=/camera/image/throttled ~/start_understory.sh` makes the detector, species and localizer nodes read that topic (`scout_ai_up.sh`, new variable). Measured after: ping 45 ms, `/scan` 10.8 Hz, `/pose` 10.4 Hz, `/detections` 1.7 Hz, 2.8 GB available, no node name twice. The Quest and the panorama node still use the full-rate topic. **The throttle was started by hand from a copy in the Pi's `~/fetch_ws/logs/` and is gone after a Pi restart**: `docker exec -d scout bash -c "source /opt/ros/jazzy/setup.bash && python3 /fetch_ws/logs/camera_throttle.py > /fetch_ws/logs/camera_throttle.log 2>&1"`. **Better fix: put the phone's hotspot on 5 GHz** ("Maximize Compatibility" off), reconnect both machines, and run `~/start_understory.sh` without `CAMERA_TOPIC`.
- At 1:32 AM the Jetson saw none of the Pi's nodes for about three minutes although ping, UDP unicast and multicast worked both ways and the Pi's discovery packets were arriving; it then saw all 41 without any change. Cause not found.
- Not tested: a plant in front of the camera with the 3 Hz feed; a pin written by the Pi's logger from the Jetson's localizer; Whisper with a human voice (the node was started on the Pi at 1:32 AM).
- The Pi's GitHub login works again (checked 1:58 AM). Branch `hf-hub-handoff` was pushed to GitHub through the Pi; **it is not merged into `main`** and has no pull request yet.

**Session 12, continued, Sun 2:05 to 2:35 AM.** *"I turned off Maximize Compatibility ... I restarted the hotspot, restart both sides."*
- **The hotspot is on 5 GHz now** (channel 149; it only changed after the hotspot was switched off and on). Same addresses: Pi `.3`, Jetson `.4`. Ping to the Pi 4 to 9 ms with the Jetson's AI reading the full camera stream, which arrives at 14.9 Hz. `CAMERA_TOPIC` and `camera_throttle.py` are no longer in use.
- **The LiDAR does not stay up on the Pi: USB over-current.** Every start of the Pi's stack (four tries, 2:20 to 2:29 AM, and once starting the LiDAR driver alone with the camera already running) is followed within seconds by `usb usbN-portN: over-current change` in `dmesg`; the Pi cuts power to all USB ports, the LiDAR, camera and ESP32 re-enumerate, the camera node respawns and the bridge reconnects, but **`rplidar_node` is left holding a dead port and `/scan` never appears**, so there is no map, no `/pose` and no TF `map -> base_link`.
- **Why:** the Pi reports a 3 A supply (`/proc/device-tree/chosen/power/max_current` = 3000), and on anything under 5 A a Pi 5 limits its USB ports to 600 mA in total. The Brio camera declares 500 mA, the ESP32 500 mA, and the LiDAR motor draws more when it spins up. `usb_max_current_enable=1` is in `/boot/firmware/config.txt` (last line) **but is not applied**: the device tree and `vcgencmd get_config usb_max_current_enable` both say 0. Not found out why. At 1:30 AM, before two Pi reboots, the same three devices ran with `/scan` at 10 Hz; what powered the Pi then is not known here.
- **Fixes, none done:** power the Pi from a 5 V 5 A supply (the official 27 W one) or a power bank that offers 5 A; or put the LiDAR (or the camera) on a powered USB hub; or set `PSU_MAX_CURRENT=5000` in the bootloader configuration (`sudo rpi-eeprom-config --edit`, then reboot), which raises the limit to 1.6 A whatever the supply and may brown out a weak power bank. After any of them: `~/scout_down.sh --keep && ~/scout_up.sh --nav` on the Pi and check `dmesg | grep over-current`.
- **The Pi rebooted twice in this half hour** (about 2:15 and 2:26 AM) without a command from this session. It does not start its stack by itself after a reboot.
- **`jetson_up.sh` (so `~/start_understory.sh`) exits before the AI when it cannot see `/scan`.** The Jetson's AI was started directly: `AI_IMAGE=scout-ros-ai-gpu AI_RUNTIME=nvidia AI_ONE_PROCESS=1 WHISPER_MODEL=none DETECTOR_BACKEND=nanoowl_trt ~/fetch_ws/src/Understory/pi/scout_ai_up.sh`.
- Left running at 2:35 AM. Pi: camera 15 Hz, Quest endpoint, Foxglove, ESP32 bridge (`shield=ok`), mission manager (`IDLE`), Nav2 and slam_toolbox with no scans, Whisper. Jetson: detector, species, localizer, dashboard on port 8501.
- **2:40 AM: the LiDAR is back.** The Pi was on the wall supply until about 2:15 AM and has been on the power bank since; that is when the over-current started. Alvaro set `PSU_MAX_CURRENT=5000` in the Pi's bootloader configuration (the old one is in `~/eeprom_before.txt` on the Pi; undo with `sudo rpi-eeprom-config --apply ~/eeprom_before.txt` and a reboot). After the reboot the device tree shows `usb_max_current_enable` 1, and `~/scout_up.sh --nav` gave `/scan` 10.0 Hz, camera 15.0 Hz, `IDLE`, TF ok, **no over-current line**. From the Jetson: `/detections` 15.1 Hz, `/pose` 10.4 Hz, 44 nodes, none twice, one `/cmd_vel` publisher, ping 5 ms.
- **The power bank is at its limit:** two minutes after that start `vcgencmd get_throttled` on the Pi was `0x50000` (under-voltage and throttling have each happened since boot; neither active at the time of the check), and the 5 V rail read 4.81 V then 5.02 V. Nothing has been driven yet; the motors are on their own batteries, but a spin with the camera and LiDAR running is the test. If the Pi reboots during the survey, this is the first suspect: `vcgencmd get_throttled` and `dmesg | grep -iE "over-current|voltage"`.

**Session 12, continued, Sun 2:45 to 3:30 AM.** *"Make the pull request and move the test m1 away"*, then *"take a look into the new dashboard that got pushed, make sure everything works including the websocket or VR display"*, then *"put the Hugging Face and run.sh on the new design ... put [the Unity steps] in an updated handoff ... upload the changes."*
- **PR #15** (`hf-hub-handoff` into `main`) is open. `main` (PR #14, the first dashboard redesign) and then branch `dashboard` (mizbahh, 3:03 and 3:05 AM: one-page design, headset view, live LiDAR, `HeadsetStreamer.cs`) were merged into it. `dashboard/app.py` is the new one-page design with the "Hugging Face" data source added to its sidebar. 13 dashboard tests pass.
- **The one-page design has no Before / after, Similar plants or Sensors view.** The "7 found -> 1 remaining" comparison is now only in the Quest app. The functions are still in `mission_io.py`.
- **`dashboard/run.sh` starts three things:** the dashboard (`:8501`), `live_relay.py` (`:8770`) and, where the `scout` ROS container runs, `scan_bridge.py` inside it. `--stop` stops all three; `NO_LIVE=1` starts the dashboard alone. `aiohttp` and `websockets` were added to `dashboard/.venv` (they are in `requirements.txt`).
- **Live LiDAR, tested with the real robot:** the bridge runs in the Jetson's `scout` container and reads `/scan` and TF over the network; scans reach the relay about 0.1 s old, 525 points plus the robot's pose, and the page shows "LiDAR live". **The live scan is in the current mapping session's coordinates and is drawn on the selected mission's saved map**, so it only lines up with a mission recorded since mapping last started (at 3:07 AM the robot was at about (2.4, -8.9) m, off the fake 5 m maps).
- **Headset WebSocket, tested without a headset:** 24 JPEG frames at 8 a second into `ws://172.20.10.4:8770/ws/headset/pub`, all 24 received on `/ws/headset`; a viewer that connects late gets the newest frame at once. The browser side was read, not opened in a browser by this session. Kevin's steps are in section 8a.
- `st.components.v1.html` (the headset panel) prints a deprecation warning on Streamlit 1.65 and still works.
- **Test missions moved aside, nothing restarted:** Jetson `~/fetch_ws/missions/m1_table_test_sun`, Pi `~/fetch_ws/missions/m1_test_sun_0247`. Pin and bubble counters were not reset: restart both sides just before the real survey to start at `m1-p01` and `m1-b01`, and move away any `m1` that has appeared by then.
- With all of it running at 3:25 AM: camera 15 Hz, `/detections` 15 Hz, ping to the Pi 6 ms, 2.4 GB available on the Jetson.

## 12. Rules for anyone (or any agent) continuing

- **Commits carry no Claude attribution.** No `Co-Authored-By`, no "Generated with" footer. Commit
  under the configured git identity.
- Topic names and JSON keys must match `AGENTS.md` exactly. Change the contract only with team agreement.
- Do not edit `ros2_ws/src/understory_nav`, `splat/` or `Unity/`. If something there blocks you, say what and why.
- Never publish on `/cmd_vel`, `/cmd_vel_auto`, `/cmd_vel_teleop` or `/estop` by hand. The mission
  manager publishing during a `capture` test is fine.
- Never `apt install` or `pip install` into a running container; it is lost on recreate. Put it in a Dockerfile.
- Never commit secrets. Tokens go in `.env`, which is git-ignored.
- No reflashing, no `apt upgrade`, nothing that could leave a machine unbootable, without asking.
- One ROS node per job. Python. Match the style of the existing `scout_perception` files.
- Check each change with real output before calling it done. If something is untested, say so.
- Keep every fallback working: Pi alone must always be able to run the demo.

To start a coding agent on the Jetson: open it in `~/fetch_ws/src/Understory` and say
*"Read HANDOFF.md and AGENTS.md, then do section 7 from step 0 and report after each step."*

## 13. Cheat sheet

```bash
# ---- Pi host ----
~/scout_up.sh                 # sensors + Foxglove + Quest endpoint
~/scout_up.sh --nav           # the above + mapping, Nav2, mission, panorama
~/scout_ai_up.sh              # plant AI + voice (add --fake-sensors, or --stop)
~/scout_down.sh --keep        # stop ROS, keep containers
~/scout_shell.sh              # sourced ROS shell in the scout container
sudo nmcli con up hotspot     # if it fell back to eduroam
date                          # check after every reboot

# ---- Jetson host ----
~/fetch_ws/src/Understory/dashboard/run.sh    # dashboard :8501 + live relay :8770 + LiDAR bridge (--stop stops all three)
CAMERA_TOPIC=/camera/image/throttled ~/start_understory.sh   # weak hotspot: the Pi must run camera_throttle.py
~/fetch_ws/src/Understory/pi/jetson/jetson_up.sh
SCOUT_PEER=172.20.10.10 ~/fetch_ws/src/Understory/pi/jetson/jetson_up.sh
NO_AI=1 ~/fetch_ws/src/Understory/pi/jetson/jetson_up.sh
AI_IMAGE=<cuda image> AI_RUNTIME=nvidia ~/fetch_ws/src/Understory/pi/jetson/jetson_up.sh
DETECTOR_BACKEND=owlvit_torch ~/fetch_ws/src/Understory/pi/jetson/jetson_up.sh   # PyTorch detector instead of TensorRT
tegrastats

# ---- inside the scout container ----
ros2 topic pub --once /voice/text std_msgs/msg/String 'data: capture'    # also: start stop return manual resume
ros2 topic echo /mission/state
ros2 topic echo /survey/pins
python3 /fetch_ws/scripts/fake_survey.py --mission m1 --rate 1
python3 /fetch_ws/scripts/fake_sensors.py
/fetch_ws/scripts/camera_lock.sh                                          # --auto to undo

# ---- rebuild after adding a node, and run the unit tests ----
cd /fetch_ws && colcon build --symlink-install --packages-select understory_nav scout_perception
cd /fetch_ws/src/Understory/ros2_ws/src/scout_perception && python3 -m pytest -q test

# ---- tune the AI without editing code ----
DETECTOR_THRESHOLD=0.08 ~/scout_ai_up.sh          # after ~/scout_ai_up.sh --stop. Default 0.05; raise it if junk gets pinned
DETECTOR_BACKEND=dummy SPECIES_BACKEND=dummy ~/scout_ai_up.sh             # plumbing only, no models
```
