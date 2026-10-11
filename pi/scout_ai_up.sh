#!/usr/bin/env bash
# scout_ai_up.sh - start the plant AI: detector (OWL-ViT) -> species (BioCLIP) -> localizer (pins + readings),
# and the voice node (Whisper: /voice/audio from the Quest -> /voice/text).
# Run on the HOST of whichever machine does the AI (Pi or Jetson), after scout_up.sh / jetson_up.sh.
# It runs in its own container, `scout-ai`, next to `scout`, and talks to it over ROS.
#
#   ~/scout_ai_up.sh             start (safe to re-run; anything already running is left alone)
#   ~/scout_ai_up.sh --stop      stop the AI nodes (the container stays)
#   ~/scout_ai_up.sh --fake-sensors   also publish fake /sensors, until the ESP32 bridge exists
#   ~/scout_ai_up.sh --voice-only     only the Whisper node (the Pi, when the Jetson runs the plant AI)
#
# Settings (environment variables):
#   AI_IMAGE=scout-ros-ai        Docker image. Default is the CPU build (pi/docker/Dockerfile.ai).
#   AI_RUNTIME=nvidia            Docker runtime, for a CUDA image on the Jetson. Default: none.
#   AI_THREADS=2                 CPU threads PyTorch may use. Keeps cores free for mapping and Nav2.
#   DETECTOR_BACKEND=owlvit_torch | nanoowl_trt | dummy        SPECIES_BACKEND=bioclip | dummy
#                                nanoowl_trt: Jetson GPU only, after pi/scripts/build_owl_engine.py has built its engine
#   DETECTOR_THRESHOLD=0.05      lower finds more plants and more junk
#   WHISPER_MODEL=openai/whisper-base.en   or openai/whisper-small.en (slower, more accurate), or none to skip it
#   WHISPER_DEVICE=cpu           cpu keeps Whisper off the GPU. Each GPU process loads about 1 GB of CUDA libraries,
#                                and three of them froze the 8 GB Jetson. Set to gpu only with memory to spare.
#   AI_ONE_PROCESS=1             detector and species in one process (ai_node, log in ai.log). Use it on the Jetson GPU:
#                                it needs about 1.6 GB instead of 3.5 GB, and the two models never peak together.
#   SCOUT_PEER=<other machine's IP>   same meaning as in scout_up.sh
#   CAMERA_TOPIC=/camera/image/throttled   the detector, species and localizer nodes read this topic instead of
#                                /camera/image/compressed. For a weak link to the camera's machine, which must be
#                                running pi/scripts/camera_throttle.py

AI_IMAGE=${AI_IMAGE:-scout-ros-ai}
DET=${DETECTOR_BACKEND:-owlvit_torch}
SPEC=${SPECIES_BACKEND:-bioclip}
THRESH=${DETECTOR_THRESHOLD:-0.05}
THREADS=${AI_THREADS:-2}
CAM=${CAMERA_TOPIC:+-r /camera/image/compressed:=$CAMERA_TOPIC}
[ -n "$AI_ONE_PROCESS" ] && DLOG=ai SLOG=ai || DLOG=detector SLOG=species
WHISPER=${WHISPER_MODEL:-openai/whisper-base.en}
[ "${WHISPER_DEVICE:-cpu}" = cpu ] && WHISPER_ENV='export CUDA_VISIBLE_DEVICES= &&' || WHISPER_ENV=
SRC='source /opt/ros/jazzy/setup.bash && source /ros2_ws/install/setup.bash && source /fetch_ws/install/setup.bash'
PEER=${SCOUT_PEER:+-e ROS_STATIC_PEERS=$SCOUT_PEER}
HERE=$(dirname "$(readlink -f "$0")")
HF="$HOME/.cache/huggingface"

warn() { printf '\n\033[1;31m!!! WARNING: %s\033[0m\n\n' "$*"; }
in_ai() { docker exec $PEER scout-ai bash -c "$SRC && $1"; }

if [ "$1" = "--stop" ]; then
  for pat in ai_node detector_node species_node localizer_node whisper_node fake_sensors.py; do docker exec scout-ai pkill -INT -f "$pat"; done
  echo "AI nodes stopped."; exit 0
fi

# --- 1. image + container (--init reaps stopped nodes; as zombies, pgrep would report them still running) ---
# the image only matters when the container has to be created; a running one is used as it is
if [ "$(docker inspect -f '{{.State.Running}}' scout-ai 2>/dev/null)" != "true" ] && ! docker image inspect "$AI_IMAGE" >/dev/null 2>&1; then
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
  docker run -d --init --name scout-ai --restart unless-stopped --net=host --ipc=host ${AI_RUNTIME:+--runtime $AI_RUNTIME} \
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
if [ "$1" = "--voice-only" ]; then
  :
elif [ -n "$AI_ONE_PROCESS" ]; then
  start ai_node ai "ros2 run scout_perception ai_node --ros-args -p detector_node:backend:=$DET -p detector_node:score_threshold:=$THRESH -p species_node:backend:=$SPEC $CAM"
else
  start detector_node detector "ros2 run scout_perception detector_node --ros-args -p backend:=$DET -p score_threshold:=$THRESH $CAM"
  start species_node species "ros2 run scout_perception species_node --ros-args -p backend:=$SPEC $CAM"
fi
[ "$1" = "--voice-only" ] || start localizer_node localizer "ros2 run scout_perception localizer_node${CAM:+ --ros-args $CAM}"
if [ "$WHISPER" != none ]; then
  # Whisper has its own offline switch, so a missing voice model never forces the plant models online
  PLANT_OFFLINE=$OFFLINE; OFFLINE=
  if ls "$HF/hub/models--${WHISPER//\//--}"/snapshots/*/model.safetensors >/dev/null 2>&1; then OFFLINE='export HF_HUB_OFFLINE=1 &&'
  else echo "Voice model $WHISPER is not on disk; downloading it (needs internet once)..."; fi
  start whisper_node whisper "$WHISPER_ENV ros2 run scout_perception whisper_node --ros-args -p model:=$WHISPER"
  OFFLINE=$PLANT_OFFLINE
fi
[ "$1" = "--fake-sensors" ] && start fake_sensors.py fake_sensors "python3 /fetch_ws/src/Understory/pi/scripts/fake_sensors.py"

# --- 4. health check ---
if [ "$1" != "--voice-only" ]; then
echo "Waiting for the models to load (up to 3 minutes the first time)..."
for i in $(seq 36); do
  grep -q 'detector running' "$HOME/fetch_ws/logs/$DLOG.log" 2>/dev/null &&
    grep -q 'species node running' "$HOME/fetch_ws/logs/$SLOG.log" 2>/dev/null && break
  # with AI_ONE_PROCESS both names match the one ai_node process, through its parameter names
  for n in detector:$DLOG species:$SLOG; do
    docker exec scout-ai pgrep -f "${n%:*}_node" >/dev/null || { warn "${n%:*} node died. See ~/fetch_ws/logs/${n#*:}.log"; tail -5 "$HOME/fetch_ws/logs/${n#*:}.log"; }
  done
  sleep 5
done
# one message is enough: on a CPU the detector manages a frame every few seconds, too slow for `ros2 topic hz`
det_ok=
for i in 1 2 3; do   # the first try can fail at once while the models are still warming up; errors go to ai_check.log
  in_ai "timeout 20 ros2 topic echo /detections std_msgs/msg/String --once" >/dev/null 2>>"$HOME/fetch_ws/logs/ai_check.log" && { det_ok=1; break; }
  echo "try $i failed at $(date +%T)" >>"$HOME/fetch_ws/logs/ai_check.log"; sleep 3
done
if [ -n "$det_ok" ]; then
  echo "  /detections: publishing"
else warn "/detections is NOT publishing (see ~/fetch_ws/logs/$DLOG.log; is the camera up?)"; fi
docker exec scout-ai pgrep -f species_node >/dev/null && echo "  species node: running" || warn "species node is NOT running"
docker exec scout-ai pgrep -f localizer_node >/dev/null && echo "  localizer: running" || warn "localizer is NOT running"
else
  for i in $(seq 30); do grep -q 'whisper node running' "$HOME/fetch_ws/logs/whisper.log" 2>/dev/null && break; sleep 3; done
fi
if [ "$WHISPER" != none ]; then
  if grep -q 'whisper node running' "$HOME/fetch_ws/logs/whisper.log" 2>/dev/null; then echo "  voice (whisper): running"
  elif docker exec scout-ai pgrep -f whisper_node >/dev/null; then echo "  voice (whisper): still loading or downloading, see ~/fetch_ws/logs/whisper.log"
  else warn "whisper node is NOT running. See ~/fetch_ws/logs/whisper.log"; fi
fi
if [ "$1" != "--voice-only" ]; then
  echo "  /species and /survey/pins only appear while a listed plant is in view. Watch them with:"
  echo "    tail -f ~/fetch_ws/logs/localizer.log"
fi
docker exec scout-ai chown -R "$(id -u):$(id -g)" /fetch_ws/logs 2>/dev/null
docker exec scout-ai bash -c "[ -d /fetch_ws/missions ] && chown -R $(id -u):$(id -g) /fetch_ws/missions" 2>/dev/null
echo "Done. Stop with: $0 --stop"
