#!/usr/bin/env bash
# scout_down.sh - stop Scout cleanly (run on the HOST).
#   ~/scout_down.sh          stop ROS processes, then stop + remove the container
#   ~/scout_down.sh --keep   stop ROS processes only, leave the container running
# Nothing in ~/fetch_ws is deleted.

if [ "$(docker inspect -f '{{.State.Running}}' scout 2>/dev/null)" != "true" ]; then
  echo "Container 'scout' is not running."
  docker rm scout >/dev/null 2>&1   # clear a stopped leftover so scout_up starts fresh
  exit 0
fi

# Ctrl+C-style stop so nodes shut down properly (the lidar takes ~5 s to spin down)
echo "Stopping ROS processes..."
for pat in 'ros2 launch' 'ros2 bag record' default_server_endpoint usb_cam_node_exe fake_survey.py save_frames.py lib/scout_perception; do
  docker exec scout pkill -INT -f "$pat"
done
# the plant AI lives in its own container (scout_ai_up.sh); it is left running, only its nodes stop
if [ "$(docker inspect -f '{{.State.Running}}' scout-ai 2>/dev/null)" = "true" ]; then
  for pat in detector_node species_node localizer_node whisper_node fake_sensors.py; do docker exec scout-ai pkill -INT -f "$pat"; done
fi
sleep 8
# anything still alive gets a hard kill
for pat in rplidar_node usb_cam_node_exe foxglove_bridge static_transform_publisher default_server_endpoint \
    async_slam_toolbox_node twist_mux lib/understory_nav lib/scout_perception \
    controller_server planner_server behavior_server bt_navigator lifecycle_manager 'ros2 launch'; do
  docker exec scout pkill -KILL -f "$pat"
done
docker exec scout chown -R "$(id -u):$(id -g)" /fetch_ws/logs 2>/dev/null

[ "$1" = "--keep" ] && { echo "ROS stopped; container left running."; exit 0; }

# an interactive container (docker run -it) means someone may have a shell open in it
if [ "$(docker inspect -f '{{.Config.Tty}}' scout)" = "true" ]; then
  read -r -p "Container 'scout' was started interactively; stopping it closes those shells. Stop it? [y/N] " ans
  [ "$ans" = "y" ] || { echo "Container left running."; exit 0; }
fi
echo "Stopping container..."
docker stop -t 5 scout >/dev/null
docker rm scout >/dev/null 2>&1   # already gone if it was started with --rm
echo "Scout is down."
