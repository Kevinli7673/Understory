# pi/ — robot bringup (Pi) and the Jetson startup

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
| `jetson/jetson_up.sh` | Jetson: start container, build, check it can see the Pi, start `scout_nav.launch.py` + detector. |
| `scripts/camera_lock.sh` | Lock camera exposure + white balance before bubbles (`--auto` to undo). |
| `scripts/save_frames.py`, `scripts/record_bag.sh` | Capture test data to `~/fetch_ws/frames` and `~/fetch_ws/bags`. |
| `scripts/fake_survey.py` | Publish contract-correct fake `/survey/*` data for the Quest app and dashboard. |
| `docker/Dockerfile` | The `scout-ros` image. Its base image `fetch-ros` only exists on the Pi, so other machines load the exported image instead of building. |

On the Pi, `~/scout_up.sh`, `~/scout_down.sh`, `~/scout_shell.sh`, `~/fetch_ws/scripts` and the two launch
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

## Pi + Jetson

The Jetson takes over mapping, Nav2, the mission manager, the panorama node and the detector. The Pi keeps
the sensors, Foxglove and the Quest endpoint, so the Quest connection does not change.

GPU models (NanoOWL, BioCLIP, Whisper) are **not** in this image. It has no CUDA or TensorRT.

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

`jetson_up.sh` prints `/scan` from the Pi, `/mission/state`, the `map -> base_link` check and the
detector rate.

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
- Not tested: the robot actually driving, Pi and Jetson together, stitching real rotated frames.

## Known gaps

- `detector_node` only has the `dummy` backend; `owlvit_torch` and `nanoowl_trt` are stubs in
  `ros2_ws/src/scout_perception/scout_perception/backends.py`.
- TF offsets in `scout_bringup.launch.py` are placeholders (`laser` z 0.15, `camera` x 0.08 z 0.10).
- Odometry is dead-reckoned from `/cmd_vel`. With the robot standing still and spin commands sent,
  the map pose followed the odometry instead of the scans, so calibrate `angular_scale` on the real robot.
