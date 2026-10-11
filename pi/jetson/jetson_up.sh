#!/usr/bin/env bash
# jetson_up.sh - start the Jetson side of Scout (run on the JETSON host, not on the Pi).
# The Jetson runs the SAME Docker image as the Pi (scout-ros, ROS 2 Jazzy, arm64) and takes over
# mapping + Nav2 + mission + panorama, then starts the plant AI (scout_ai_up.sh, its own container).
# The Pi keeps the sensors, Foxglove and the Quest endpoint.
# Safe to re-run. First-time setup (loading the image, cloning the repo) is in pi/README.md.
#
#   ~/fetch_ws/src/Understory/pi/jetson/jetson_up.sh
#   SCOUT_PEER=<Pi IP> .../jetson_up.sh        # if the Pi's topics don't show up (see step 4)
#   NO_AI=1 .../jetson_up.sh                        # mapping + mission only, no plant AI
#   The plant AI uses the image scout-ros-ai-gpu when it exists (build: pi/jetson/Dockerfile.gpu, HANDOFF.md),
#   with AI_ONE_PROCESS=1 and WHISPER_MODEL=none, and the TensorRT detector (DETECTOR_BACKEND=nanoowl_trt) when
#   ~/fetch_ws/models/owlvit-base-patch32.engine exists. Set AI_IMAGE / AI_RUNTIME / AI_ONE_PROCESS= / WHISPER_MODEL /
#   DETECTOR_BACKEND to override.

SRC='source /opt/ros/jazzy/setup.bash && source /ros2_ws/install/setup.bash && source /fetch_ws/install/setup.bash'
PEER=${SCOUT_PEER:+-e ROS_STATIC_PEERS=$SCOUT_PEER}

warn() { printf '\n\033[1;31m!!! WARNING: %s\033[0m\n\n' "$*"; }
in_scout() { docker exec $PEER scout bash -c "$SRC && $1"; }

# --- 1. clock + network (TF between Pi and Jetson breaks if the clocks disagree by more than ~0.2 s) ---
echo "Date: $(date)   <- compare with 'date' on the Pi"
ips=$(hostname -I)
echo "IPs:  $ips"
grep -q '172\.20\.10\.' <<<"$ips" || warn "Not on the iPhone hotspot (no 172.20.10.x address). The Pi prints its own address when ~/scout_up.sh runs."

# --- 2. container ---
if ! docker image inspect scout-ros >/dev/null 2>&1; then
  warn "Docker image scout-ros is missing. Load it first (pi/README.md, Jetson setup)."; exit 1
fi
if [ "$(docker inspect -f '{{.State.Running}}' scout 2>/dev/null)" = "true" ]; then
  echo "Container 'scout' already running."
elif docker inspect scout >/dev/null 2>&1; then
  docker start scout >/dev/null
else
  echo "Creating container 'scout'..."
  docker run -d --name scout --restart unless-stopped --net=host --ipc=host --privileged \
    -v /dev:/dev -v "$HOME/fetch_ws:/fetch_ws" scout-ros sleep infinity >/dev/null || exit 1
fi
docker exec scout mkdir -p /fetch_ws/logs
# 70 KB camera frames cross the hotspot as ~50 IP fragments each. With the kernel defaults, lost fragments
# sit in the reassembly queue for 30 s, fill it, and then no frame gets through at all (seen on the Jetson).
# Not namespaced, so setting it from the privileged host-network container sets it for the host. Lost on reboot.
docker exec scout sysctl -q -w net.ipv4.ipfrag_time=3 net.ipv4.ipfrag_high_thresh=134217728 \
  net.core.rmem_max=16777216 net.core.rmem_default=16777216
# the helper scripts document themselves as /fetch_ws/scripts/...; make that path exist here too
[ -e "$HOME/fetch_ws/scripts" ] || ln -s src/Understory/pi/scripts "$HOME/fetch_ws/scripts"

# --- 3. build the workspace (fast; needed the first time and after every code change) ---
echo "Building workspace..."
docker exec scout bash -c 'source /opt/ros/jazzy/setup.bash && source /ros2_ws/install/setup.bash && cd /fetch_ws &&
  colcon build --symlink-install --packages-select understory_nav scout_perception 2>&1 | tail -3' || exit 1

# --- 4. can we see the Pi? ---
echo "Looking for the Pi's /scan (8 s)..."
rate=$(in_scout "timeout 8 ros2 topic hz /scan 2>/dev/null" | grep 'average rate' | tail -1 | awk '{print $3}')
if [ -n "$rate" ]; then
  echo "  /scan from the Pi: $rate Hz"
else
  warn "Cannot see /scan. Is ~/scout_up.sh running on the Pi? If yes, discovery is blocked. Run
    Pi:     ~/scout_down.sh --keep && SCOUT_PEER=<this Jetson's 172.20.10.x IP> ~/scout_up.sh
    Jetson: SCOUT_PEER=<the Pi's 172.20.10.x IP> $0"
  exit 1
fi

# --- 5. mapping + mission + panorama ---
if docker exec scout pgrep -f scout_nav.launch.py >/dev/null; then
  echo "Nav already running here."
# --no-daemon: the ROS daemon's cached list missed a Pi that had just rejoined the network (Sat 7:50 PM),
# and a second mapping stack was started beside the Pi's
elif in_scout "timeout 12 ros2 node list --no-daemon --spin-time 6" | grep -q slam_toolbox; then
  warn "slam_toolbox is already running on the Pi. Stop it there first (~/scout_down.sh --keep && ~/scout_up.sh), then re-run this."
  # the mission still has to be written to disk; the logger only listens, so it is safe beside the Pi's stack
  if ! in_scout "timeout 5 ros2 node list" | grep -q logger_node; then
    echo "Starting the mission logger here (the Pi's stack does not run one)..."
    docker exec -d $PEER scout bash -c "$SRC && ros2 run scout_perception logger_node > /fetch_ws/logs/logger.log 2>&1"
  fi
else
  echo "Starting slam + Nav2 + mission + panorama..."
  docker exec -d $PEER scout bash -c "$SRC && ros2 launch /fetch_ws/src/Understory/pi/scout_nav.launch.py > /fetch_ws/logs/nav.log 2>&1"
fi
# --- 6. health check ---
echo "Waiting for nodes (~20 s)..."
sleep 20
state=$(in_scout "timeout 5 ros2 topic echo /mission/state --once --field data 2>/dev/null" | head -1)
if [ -n "$state" ]; then echo "  /mission/state: $state"; else warn "no /mission/state (check ~/fetch_ws/logs/nav.log)"; fi
if in_scout "timeout 5 ros2 run tf2_ros tf2_echo map base_link 2>&1" | grep -q Translation; then
  echo "  TF map -> base_link: ok (slam is localizing)"
else
  warn "no TF map -> base_link. Usual cause: Pi and Jetson clocks differ. Compare 'date' on both."
fi
for topic in /camera/image/compressed; do
  rate=$(in_scout "timeout 8 ros2 topic hz $topic 2>/dev/null" | grep 'average rate' | tail -1 | awk '{print $3}')
  if [ -n "$rate" ]; then echo "  $topic: $rate Hz"; else warn "$topic is NOT publishing"; fi
done
docker exec scout chown -R "$(id -u):$(id -g)" /fetch_ws/logs /fetch_ws/build /fetch_ws/install /fetch_ws/log 2>/dev/null
# --- 7. plant AI: detector + species + localizer in the scout-ai container (NO_AI=1 skips it) ---
if [ -z "$NO_AI" ]; then
  # Jetson defaults (set any of them yourself to override): the GPU image if it has been built, both
  # models in one process, and no Whisper here - it runs on the Pi (~/scout_ai_up.sh --voice-only).
  if [ -z "$AI_IMAGE" ] && docker image inspect scout-ros-ai-gpu >/dev/null 2>&1; then
    export AI_IMAGE=scout-ros-ai-gpu AI_RUNTIME=${AI_RUNTIME:-nvidia}
  fi
  export AI_ONE_PROCESS=${AI_ONE_PROCESS-1} WHISPER_MODEL=${WHISPER_MODEL:-none}
  # the TensorRT detector once its engine has been built (pi/scripts/build_owl_engine.py);
  # DETECTOR_BACKEND=owlvit_torch goes back to plain PyTorch
  if [ -z "$DETECTOR_BACKEND" ] && [ "$AI_IMAGE" = scout-ros-ai-gpu ] && [ -f "$HOME/fetch_ws/models/owlvit-base-patch32.engine" ]; then
    export DETECTOR_BACKEND=nanoowl_trt
  fi
  "$(dirname "$(readlink -f "$0")")/../scout_ai_up.sh"
fi
echo "Done. Stop with: docker exec scout pkill -INT -f 'ros2 launch'; $(dirname "$(readlink -f "$0")")/../scout_ai_up.sh --stop"
echo "Test:  docker exec scout bash -c \"$SRC && ros2 topic pub --once /voice/text std_msgs/msg/String 'data: capture'\""
