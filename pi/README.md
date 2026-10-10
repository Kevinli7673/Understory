# pi/ — robot bringup (Pi) and the Jetson startup

**The full picture (status, what is tested, what is left, Jetson steps) is in [`HANDOFF.md`](../HANDOFF.md).**

Everything here runs ROS 2 **Jazzy inside the `scout-ros` Docker image**. Neither machine has ROS on the
host. The workspace is `~/fetch_ws` on the host, mounted at `/fetch_ws` in the container, with this repo
cloned at `~/fetch_ws/src/Understory`.

| File | What it does |
| --- | --- |
| `scout_up.sh` | Pi: start container, LiDAR + camera + Foxglove (8765) + ROS-TCP-Endpoint (10000), print a health check. `--nav` also starts mapping + Nav2 + mission + panorama on the Pi. |
| `scout_down.sh` | Pi: stop everything (`--keep` leaves the container running). |
| `scout_shell.sh` | Open a sourced ROS shell in the container. |
| `scout_bringup.launch.py` | LiDAR, camera, static TFs, Foxglove bridge. `publish_tf:=false` drops the TFs. |
| `scout_nav.launch.py` | slam_toolbox + Nav2 + twist_mux + mission manager + panorama node, using the `understory_nav` configs. Use this instead of `understory_nav/launch/nav.launch.py` on Jazzy (reasons at the top of the file). |
| `scout_ai_up.sh` | Either machine: start the plant AI (detector, species, localizer) in its own `scout-ai` container. `--stop`, `--fake-sensors`. |
| `jetson/jetson_up.sh` | Jetson: start container, build, check it can see the Pi, start `scout_nav.launch.py`, then call `scout_ai_up.sh`. |
| `scripts/camera_lock.sh` | Lock camera exposure + white balance before bubbles (`--auto` to undo). |
| `scripts/save_frames.py`, `scripts/record_bag.sh` | Capture test data to `~/fetch_ws/frames` and `~/fetch_ws/bags`. |
| `scripts/fake_survey.py` | Publish contract-correct fake `/survey/*` data for the Quest app and dashboard. |
| `scripts/fake_sensors.py` | Publish fake `/sensors` (what the ESP32 bridge will send) so `/survey/readings` can be tested. |
| `scripts/pose_from_tf.py` | TF `map -> base_link` -> `/pose` (PoseWithCovarianceStamped) for the Quest's robot marker; slam_toolbox here doesn't publish `/pose`. |
| `scripts/esp32_bridge.py` | `/cmd_vel` -> ESP32 wheels (`firmware/esp32_drive`), ESP32 sensor JSON -> `/sensors`. Auto-picks the ESP32's serial port, never the LiDAR's. |
| `scripts/ai_selftest.sh` | Feed plant photos through the whole AI chain on a separate ROS domain and print the pins. |
| `docker/Dockerfile.ai` | The `scout-ros-ai` image: `scout-ros` plus CPU PyTorch, transformers and open_clip. `scout_ai_up.sh` builds it when missing. |
| `docker/Dockerfile` | The `scout-ros` image. Its base image `fetch-ros` only exists on the Pi, so other machines load the exported image instead of building. |

On the Pi, `~/scout_up.sh`, `~/scout_down.sh`, `~/scout_shell.sh`, `~/scout_ai_up.sh`, `~/fetch_ws/scripts` and the two launch
files in `~/fetch_ws` are symlinks into this folder.

## Pi only (no Jetson)

```bash
~/scout_up.sh --nav
```

Quest: ROS IP `172.20.10.10`, port `10000`. Foxglove: `ws://172.20.10.10:8765`.

Drive the mission by publishing words on `/voice/text` (`start`, `stop`, `return`, `manual`, `capture`, `resume`):

```bash
~/scout_shell.sh
ros2 topic pub --once /voice/text std_msgs/msg/String 'data: capture'
```

### Plant AI on the Pi

```bash
~/scout_ai_up.sh                 # detector (OWL-ViT) -> species (BioCLIP) -> localizer (pins + readings)
~/scout_ai_up.sh --fake-sensors  # also fake /sensors, until the ESP32 bridge exists
tail -f ~/fetch_ws/logs/localizer.log
~/scout_ai_up.sh --stop
```

It runs on the CPU: about one frame every 4 seconds, so a plant held in front of the camera becomes a
pin after roughly 12 to 15 seconds. The first run builds the image and downloads the models (needs
internet); after that it runs offline.

## Pi + Jetson

The Jetson takes over mapping, Nav2, the mission manager, the panorama node and the plant AI. The Pi keeps
the sensors, Foxglove and the Quest endpoint, so the Quest connection does not change.

`jetson_up.sh` starts the AI from the CPU image by default, the same one the Pi uses. A GPU image is
passed in with `AI_IMAGE=... AI_RUNTIME=nvidia`; building one is the open Jetson task (`HANDOFF.md`, section 7).

### One-time setup on the Jetson

1. Join the iPhone hotspot. Check `date` matches the Pi to the second (TF breaks otherwise).
   `docker ps` must work without sudo (`sudo usermod -aG docker $USER`, then log out and in).
2. Load the image from the Pi (about 1 GB; or carry the file on a USB stick):

   ```bash
   scp a1vcm@172.20.10.10:scout-ros-image.tar.gz ~/
   gunzip -c ~/scout-ros-image.tar.gz | docker load
   ```

3. Clone this repo into the workspace:

   ```bash
   mkdir -p ~/fetch_ws/src && cd ~/fetch_ws/src
   git clone https://github.com/Kevinli7673/Understory.git
   ```

### Every time

```bash
# Pi: sensors only, so there is exactly one slam_toolbox on the network
~/scout_down.sh --keep && ~/scout_up.sh
# Jetson
~/fetch_ws/src/Understory/pi/jetson/jetson_up.sh
```

`jetson_up.sh` prints `/scan` from the Pi, `/mission/state`, the `map -> base_link` check, the camera
rate and whether `/detections` is publishing. `NO_AI=1` skips the AI.

### If the Jetson cannot see `/scan`

The hotspot is dropping multicast discovery. Point each machine at the other:

```bash
# Pi
~/scout_down.sh --keep && SCOUT_PEER=<Jetson IP> ~/scout_up.sh
# Jetson
SCOUT_PEER=172.20.10.10 ~/fetch_ws/src/Understory/pi/jetson/jetson_up.sh
```

This fallback has not been tested with two machines.

## What has been tested

- Pi with real LiDAR and camera: `/scan` 10 Hz, `/camera/image/compressed` 15 Hz, slam_toolbox mapping,
  all Nav2 servers active, mission manager + panorama node completing a 12-frame bubble.
- Simulation (`understory_nav` `fake_world`): a full "start survey" run through Nav2, and a 1 m
  `navigate_to_pose` goal.
- Pi, real models on the CPU: OWL-ViT + BioCLIP + localizer through `scout_ai_up.sh`; `ai_selftest.sh`
  turns plant photos into pins. `/detections` runs at about 0.25 Hz.
- Localizer live with the real LiDAR and TF (dummy boxes), and `/sensors` -> `/survey/readings` with `fake_sensors.py`.
- Not tested: the robot actually driving, Pi and Jetson together, anything on the Jetson or its GPU,
  stitching real rotated frames, a real plant photo held in front of the real camera.

## Known gaps

- The Jetson has a GPU image (`pi/jetson/Dockerfile.gpu`) and a TensorRT detector (`nanoowl_trt`, see HANDOFF.md session 9). The Pi runs the AI on the CPU.
- The Whisper node (`/voice/audio` -> `/voice/text`, started by `scout_ai_up.sh`) has only been tested with synthetic speech.
- No ESP32 bridge: nothing drives the motors and nothing publishes the real `/sensors`.
- The `/species` JSON is not in `AGENTS.md` yet (shape in `HANDOFF.md`, section 5).
- TF offsets in `scout_bringup.launch.py` are placeholders (`laser` z 0.15, `camera` x 0.08 z 0.10).
- Odometry is dead-reckoned from `/cmd_vel`. With the robot standing still and spin commands sent,
  the map pose followed the odometry instead of the scans, so calibrate `angular_scale` on the real robot.
