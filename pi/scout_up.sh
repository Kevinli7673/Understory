#!/usr/bin/env bash
# scout_up.sh - one-command startup for the Scout Pi (run on the HOST, not in the container).
# Safe to re-run: anything already running is left alone.
#   ~/scout_up.sh         sensors + Foxglove + Quest endpoint (use this when the Jetson runs mapping/mission)
#   ~/scout_up.sh --nav   also mapping + Nav2 + mission manager + panorama on the Pi (no Jetson needed)
#   SCOUT_PEER=<other machine's IP> ~/scout_up.sh   only if the Jetson can't see the Pi's topics:
#       makes ROS discovery talk straight to that IP instead of relying on multicast

SRC='source /opt/ros/jazzy/setup.bash && source /ros2_ws/install/setup.bash && source /fetch_ws/install/setup.bash'
STAMP="$HOME/.scout_last_up"   # time of the previous run, used to catch a clock that jumped backwards

warn() { printf '\n\033[1;31m!!! WARNING: %s\033[0m\n\n' "$*"; }
PEER=${SCOUT_PEER:+-e ROS_STATIC_PEERS=$SCOUT_PEER}
in_scout() { docker exec $PEER scout bash -c "$SRC && $1"; }

# --- 1. clock (no RTC battery; venue Wi-Fi blocks NTP) ---
echo "Date: $(date)"
today=$(date +%Y%m%d)
if [ "$today" -lt 20261009 ] || [ "$today" -gt 20261012 ]; then
  warn "Clock is outside the hackathon dates (Oct 9-11 2026). Fix: sudo date -u -s \"YYYY-MM-DD HH:MM:SS\" (UTC)"
elif [ -f "$STAMP" ] && [ "$(date +%s)" -lt "$(stat -c %Y "$STAMP")" ]; then
  warn "Clock is EARLIER than the last scout_up run ($(date -r "$STAMP")). Fix: sudo date -u -s \"YYYY-MM-DD HH:MM:SS\" (UTC)"
fi
touch "$STAMP"

# --- 2. network (must be on the iPhone hotspot, 172.20.10.x) ---
ips=$(hostname -I)
echo "IPs:  $ips"
if ! grep -q '172\.20\.10\.' <<<"$ips"; then
  warn "Not on the hotspot (no 172.20.10.x address; probably fell back to eduroam). Fix: sudo nmcli con up hotspot"
fi

# --- 3. container ---
if [ "$(docker inspect -f '{{.State.Running}}' scout 2>/dev/null)" = "true" ]; then
  echo "Container 'scout' already running."
elif docker inspect scout >/dev/null 2>&1; then
  echo "Starting existing container 'scout'..."
  docker start scout >/dev/null
else
  echo "Creating container 'scout'..."
  docker run -d --name scout --restart unless-stopped --net=host --ipc=host --privileged \
    -v /dev:/dev -v "$HOME/fetch_ws:/fetch_ws" scout-ros sleep infinity >/dev/null || exit 1
fi
docker exec scout mkdir -p /fetch_ws/logs

# --- 4. bringup + Quest endpoint (detached, logs in ~/fetch_ws/logs) ---
if docker exec scout pgrep -f scout_bringup.launch.py >/dev/null; then
  echo "Bringup already running."
else
  echo "Starting bringup..."
  docker exec scout pkill -INT -f usb_cam_node_exe   # a stray standalone camera would hold /dev/video0
  docker exec -d $PEER scout bash -c "$SRC && ros2 launch /fetch_ws/src/Understory/pi/scout_bringup.launch.py > /fetch_ws/logs/bringup.log 2>&1"
fi
# bringup is up but the camera node died or was never started (e.g. launched before the camera was plugged in)
sleep 2
if ! docker exec scout pgrep -f usb_cam_node_exe >/dev/null; then
  warn "Camera node is not running. Check ~/fetch_ws/logs/bringup.log, then ~/scout_down.sh --keep && ~/scout_up.sh"
fi

if docker exec scout pgrep -f default_server_endpoint >/dev/null; then
  echo "TCP endpoint already running."
else
  echo "Starting ROS-TCP-Endpoint..."
  docker exec -d $PEER scout bash -c "$SRC && ros2 run ros_tcp_endpoint default_server_endpoint --ros-args -p ROS_IP:=0.0.0.0 > /fetch_ws/logs/tcp_endpoint.log 2>&1"
fi

# --- 4b. optional: mapping + mission + panorama on the Pi (Teammate 3's understory_nav, no Nav2) ---
if [ "$1" = "--nav" ]; then
  if docker exec scout pgrep -f scout_nav.launch.py >/dev/null; then
    echo "Nav (slam + Nav2 + mission + panorama) already running."
  elif in_scout "timeout 5 ros2 node list" | grep -q slam_toolbox; then
    warn "slam_toolbox is already running on another machine (the Jetson?). Not starting a second one."
  else
    echo "Starting slam + Nav2 + mission + panorama..."
    docker exec -d $PEER scout bash -c "$SRC && ros2 launch /fetch_ws/src/Understory/pi/scout_nav.launch.py > /fetch_ws/logs/nav.log 2>&1"
  fi
fi

# --- 5. health check ---
echo "Waiting for nodes, then measuring rates (~15 s)..."
sleep 5
for topic in /scan /camera/image/compressed; do
  rate=$(in_scout "timeout 8 ros2 topic hz $topic 2>/dev/null" | grep 'average rate' | tail -1 | awk '{print $3}')
  if [ -n "$rate" ]; then echo "  $topic: $rate Hz"; else warn "$topic is NOT publishing"; fi
done
if docker exec scout pgrep -f scout_nav.launch.py >/dev/null; then
  state=$(in_scout "timeout 5 ros2 topic echo /mission/state --once --field data 2>/dev/null" | head -1)
  if [ -n "$state" ]; then echo "  /mission/state: $state"; else warn "mission manager is NOT publishing /mission/state"; fi
  if in_scout "timeout 5 ros2 run tf2_ros tf2_echo map base_link 2>&1" | grep -q Translation; then
    echo "  TF map -> base_link: ok (slam is localizing)"
  else warn "no TF map -> base_link (slam_toolbox not mapping; check ~/fetch_ws/logs/nav.log)"; fi
fi
for port in 10000 8765; do
  if ss -ltn | grep -q ":$port "; then echo "  port $port: listening"; else warn "port $port is NOT listening"; fi
done

# files the container creates are root-owned; hand them back to the host user
docker exec scout chown -R "$(id -u):$(id -g)" /fetch_ws/logs
echo "Done. Quest: ROS IP 172.20.10.10 port 10000 | Foxglove: ws://172.20.10.10:8765 | shell: ~/scout_shell.sh"
