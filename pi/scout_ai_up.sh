#!/usr/bin/env bash
# scout_ai_up.sh - start the plant AI: detector (OWL-ViT) -> species (BioCLIP) -> localizer (pins + readings),
# and the voice node (Whisper: /voice/audio from the Quest -> /voice/text).
# Run on the HOST of whichever machine does the AI (Pi or Jetson), after scout_up.sh / jetson_up.sh.
# It runs in its own container, `scout-ai`, next to `scout`, and talks to it over ROS.
#
#   ~/scout_ai_up.sh             start (safe to re-run; anything already running is left alone)
#   ~/scout_ai_up.sh --stop      stop the AI nodes (the container stays)
#   ~/scout_ai_up.sh --fake-sensors   also publish fake /sensors, until the ESP32 bridge exists
#
# Settings (environment variables):
#   AI_IMAGE=scout-ros-ai        Docker image. Default is the CPU build (pi/docker/Dockerfile.ai).
#   AI_RUNTIME=nvidia            Docker runtime, for a CUDA image on the Jetson. Default: none.
#   AI_THREADS=2                 CPU threads PyTorch may use. Keeps cores free for mapping and Nav2.
#   DETECTOR_BACKEND=owlvit_torch | dummy        SPECIES_BACKEND=bioclip | dummy
#   DETECTOR_THRESHOLD=0.05      lower finds more plants and more junk
#   WHISPER_MODEL=openai/whisper-base.en   or openai/whisper-small.en (slower, more accurate), or none to skip it
#   SCOUT_PEER=<other machine's IP>   same meaning as in scout_up.sh

AI_IMAGE=${AI_IMAGE:-scout-ros-ai}
DET=${DETECTOR_BACKEND:-owlvit_torch}
SPEC=${SPECIES_BACKEND:-bioclip}
THRESH=${DETECTOR_THRESHOLD:-0.05}
THREADS=${AI_THREADS:-2}
WHISPER=${WHISPER_MODEL:-openai/whisper-base.en}
SRC='source /opt/ros/jazzy/setup.bash && source /ros2_ws/install/setup.bash && source /fetch_ws/install/setup.bash'
PEER=${SCOUT_PEER:+-e ROS_STATIC_PEERS=$SCOUT_PEER}
HERE=$(dirname "$(readlink -f "$0")")
HF="$HOME/.cache/huggingface"

warn() { printf '\n\033[1;31m!!! WARNING: %s\033[0m\n\n' "$*"; }
in_ai() { docker exec $PEER scout-ai bash -c "$SRC && $1"; }

if [ "$1" = "--stop" ]; then
  for pat in detector_node species_node localizer_node whisper_node fake_sensors.py; do docker exec scout-ai pkill -INT -f "$pat"; done
  echo "AI nodes stopped."; exit 0
fi

# --- 1. image + container ---
if ! docker image inspect "$AI_IMAGE" >/dev/null 2>&1; then
  if [ "$AI_IMAGE" = scout-ros-ai ] && docker image inspect scout-ros >/dev/null 2>&1; then
    echo "Building $AI_IMAGE (one time, needs internet, about 5 minutes)..."
    docker build -t scout-ros-ai -f "$HERE/docker/Dockerfile.ai" "$HERE/docker" || exit 1
  else
    warn "Docker image $AI_IMAGE is missing."; exit 1
  fi
fi
mkdir -p "$HF" "$HOME/fetch_ws/logs"
if [ "$(docker inspect -f '{{.State.Running}}' scout-ai 2>/dev/null)" = "true" ]; then
  echo "Container 'scout-ai' already running."
else
  docker rm scout-ai >/dev/null 2>&1
  echo "Creating container 'scout-ai' from $AI_IMAGE..."
  docker run -d --name scout-ai --restart unless-stopped --net=host --ipc=host ${AI_RUNTIME:+--runtime $AI_RUNTIME} \
    -e OMP_NUM_THREADS="$THREADS" -v "$HOME/fetch_ws:/fetch_ws" -v "$HF:/root/.cache/huggingface" \
    "$AI_IMAGE" sleep infinity >/dev/null || exit 1
fi

# --- 2. models: once both are on disk, never touch the network again (the demo has no internet) ---
OFFLINE=
if [ "$DET" = dummy ] || [ -d "$HF/hub/models--google--owlvit-base-patch32" ]; then
  if [ "$SPEC" = dummy ] || [ -d "$HF/hub/models--imageomics--bioclip" ]; then OFFLINE='export HF_HUB_OFFLINE=1 &&'; fi
fi
[ -n "$OFFLINE" ] && echo "Models are cached; running offline." || echo "First run: downloading models to $HF (about 1 GB, needs internet)..."

# --- 3. the nodes (detached, logs in ~/fetch_ws/logs) ---
if ! in_ai "ros2 pkg executables scout_perception" | grep -q localizer_node; then
  warn "scout_perception is not built. On the Pi: ~/scout_shell.sh then  cd /fetch_ws && colcon build --symlink-install --packages-select scout_perception"; exit 1
fi
start() {   # start <process pattern> <log name> <command>
  if docker exec scout-ai pgrep -f "$1" >/dev/null; then echo "$2 already running."; return; fi
  echo "Starting $2..."
  docker exec -d $PEER scout-ai bash -c "$SRC && $OFFLINE $3 > /fetch_ws/logs/$2.log 2>&1"
}
start detector_node detector "ros2 run scout_perception detector_node --ros-args -p backend:=$DET -p score_threshold:=$THRESH"
start species_node species "ros2 run scout_perception species_node --ros-args -p backend:=$SPEC"
start localizer_node localizer "ros2 run scout_perception localizer_node"
if [ "$WHISPER" != none ]; then
  # Whisper has its own offline switch, so a missing voice model never forces the plant models online
  PLANT_OFFLINE=$OFFLINE; OFFLINE=
  if ls "$HF/hub/models--${WHISPER//\//--}"/snapshots/*/model.safetensors >/dev/null 2>&1; then OFFLINE='export HF_HUB_OFFLINE=1 &&'
  else echo "Voice model $WHISPER is not on disk; downloading it (needs internet once)..."; fi
  start whisper_node whisper "ros2 run scout_perception whisper_node --ros-args -p model:=$WHISPER"
  OFFLINE=$PLANT_OFFLINE
fi
[ "$1" = "--fake-sensors" ] && start fake_sensors.py fake_sensors "python3 /fetch_ws/src/Understory/pi/scripts/fake_sensors.py"

# --- 4. health check ---
echo "Waiting for the models to load (up to 3 minutes the first time)..."
for i in $(seq 36); do
  grep -q 'detector running' "$HOME/fetch_ws/logs/detector.log" 2>/dev/null &&
    grep -q 'species node running' "$HOME/fetch_ws/logs/species.log" 2>/dev/null && break
  for n in detector species; do
    docker exec scout-ai pgrep -f "${n}_node" >/dev/null || { warn "$n node died. See ~/fetch_ws/logs/$n.log"; tail -5 "$HOME/fetch_ws/logs/$n.log"; }
  done
  sleep 5
done
# one message is enough: on a CPU the detector manages a frame every few seconds, too slow for `ros2 topic hz`
if in_ai "timeout 60 ros2 topic echo /detections std_msgs/msg/String --once" >/dev/null 2>&1; then
  echo "  /detections: publishing"
else warn "/detections is NOT publishing (see ~/fetch_ws/logs/detector.log; is the camera up?)"; fi
docker exec scout-ai pgrep -f species_node >/dev/null && echo "  species node: running" || warn "species node is NOT running"
docker exec scout-ai pgrep -f localizer_node >/dev/null && echo "  localizer: running" || warn "localizer is NOT running"
if [ "$WHISPER" != none ]; then
  if grep -q 'whisper node running' "$HOME/fetch_ws/logs/whisper.log" 2>/dev/null; then echo "  voice (whisper): running"
  elif docker exec scout-ai pgrep -f whisper_node >/dev/null; then echo "  voice (whisper): still loading or downloading, see ~/fetch_ws/logs/whisper.log"
  else warn "whisper node is NOT running. See ~/fetch_ws/logs/whisper.log"; fi
fi
echo "  /species and /survey/pins only appear while a listed plant is in view. Watch them with:"
echo "    tail -f ~/fetch_ws/logs/localizer.log"
docker exec scout-ai chown -R "$(id -u):$(id -g)" /fetch_ws/logs 2>/dev/null
docker exec scout-ai bash -c "[ -d /fetch_ws/missions ] && chown -R $(id -u):$(id -g) /fetch_ws/missions" 2>/dev/null
echo "Done. Stop with: $0 --stop"
