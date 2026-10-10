# understory_nav — navigation + mission (Teammate 3)

ROS 2 Humble (Jetson, JetPack 6). slam_toolbox → `/map` + pose, Nav2 → `/cmd_vel_auto`,
twist_mux → `/cmd_vel`, mission manager → `/mission/state`, `/survey/capture`.

## Build & run

```bash
sudo apt install ros-humble-slam-toolbox ros-humble-navigation2 ros-humble-twist-mux
cd ros2_ws && colcon build --symlink-install && source install/setup.bash
export ROS_DOMAIN_ID=42

# No hardware: fake robot + LiDAR + panorama
ros2 launch understory_nav sim.launch.py
# Real robot (needs /scan from the LiDAR, ESP32 bridge listening on /cmd_vel)
ros2 launch understory_nav nav.launch.py laser_z:=0.15 laser_yaw:=0.0

ros2 topic pub --once /voice/text std_msgs/String "data: start survey"
ros2 topic echo /mission/state
```

Unit tests (no ROS needed): `python -m pytest ros2_ws/src/understory_nav/test`
Interrupt-path check against a running stack: `python ros2_ws/src/understory_nav/scripts/sim_scenario.py`

**Verified in sim (ROS 2 Humble via RoboStack on a Mac):** a cold-start survey with 8 bubbles, all
`capture_done`s received, return home in 4.4 min; Nav2 reset/crash recovery; `sim_scenario.py` passes all 15 checks (teleop takeover,
manual capture, resume, e-stop blocks `/cmd_vel` at twist_mux, "come back"). Not yet run on the Jetson or real hardware.

## What it does

- **Survey points**: `waypoints: "x,y; x,y"` in `config/mission.yaml`, or empty to auto-plan.
  Auto mode re-plans after every bubble: the nearest reachable spot on a 1 m lattice, ≥0.35 m from
  walls/unknown, not near a visited one. The survey starts on an empty map and expands as SLAM sees more.
  It stops after `max_points` bubbles.
- **At each point**: 12 stops, 30° apart (closed-loop on slam_toolbox yaw). At every stop:
  settle 0.4 s → publish `bubble_id` on `/survey/capture` → hold 0.6 s.
  After the 12th stop, wait up to 15 s for that `bubble_id` on `/survey/capture_done`, then move on.
- **Return**: drives back to where "start" was said, then `IDLE`.
- **Fallbacks**: Nav2 down → `MANUAL` (drive with sticks, say "capture" for a bubble in place).
  Point unreachable → skipped. No `capture_done` → logged, moves on anyway.
- **Nav2 recovery**: if Nav2 is down, rejects goals, or doesn't answer within 10 s, the mission goes to
  `MANUAL` (survey kept open) and asks Nav2's lifecycle manager to start back up; say "resume" to carry on
  from the same point. Crashed Nav2 servers respawn. Tested in sim: Nav2 reset and `kill -9 controller_server`
  mid-survey both recover in about 2 s.

## Interface notes for the team

| For | Note |
| --- | --- |
| Alvaro (panorama) | A bubble = **12** `/survey/capture` messages with the same `bubble_id`, robot still for ≥0.6 s after each. Publish `/survey/capture_done` once per bubble. Change `frames_per_bubble` on both sides if it changes. |
| Alvaro (Whisper) / Kevin | Commands on `/voice/text`, matched by keyword: **start / stop / return (come back, go home) / manual / capture / resume**. A Quest button can publish the same words. |
| Kevin / dashboard | `/mission/state` is the plain state name (`IDLE`, `SURVEYING`, …), latched + 1 Hz. Robot pose: TF `map→base_link`, or `/pose` from slam_toolbox. |
| Kevin | Touching the sticks during autonomy cancels it → `MANUAL` (ignored for 1 s after a voice command, so a stick message already in flight can't undo "come back"). Keep stick drift under the 0.05 deadband or send nothing when idle. E-stop `true` → `STOPPED`; after releasing it, say "resume" or "start". |
| Teammate 4 (ESP32) | Odometry is dead-reckoned from `/cmd_vel` (`cmd_vel_odom`). If you add encoders, publish `odom→base_link` + `/odom` and launch with `odom_source:=external`. Calibrate `linear_scale` / `angular_scale` otherwise. |
| Teammate 4 (logger) | Save the map into the mission folder: `ros2 run nav2_map_server map_saver_cli -f missions/m1/map` |

Measure and set `laser_*` / `camera_*` launch args on the real robot; robot radius (0.17 m) and speeds are in `config/nav2.yaml`.
