#!/usr/bin/env bash
# scout_shell.sh - open an interactive, already-sourced ROS shell in the scout container.
# Start the container first with ~/scout_up.sh.
exec docker exec -it scout bash -c 'source /opt/ros/jazzy/setup.bash && source /ros2_ws/install/setup.bash && source /fetch_ws/install/setup.bash && cd /fetch_ws && exec bash'
