#!/usr/bin/env bash
# ai_selftest.sh - prove the plant AI works end to end with no robot and no plant (run on the HOST).
# Feeds the photos in a folder through detector -> species -> localizer and prints the pins.
# Everything runs on ROS domain 43, so the real robot, the Quest and the dashboard never see it.
# The live AI nodes are stopped first so the CPU is free; restart them after with ~/scout_ai_up.sh.
#
#   pi/scripts/ai_selftest.sh [photo folder] [seconds per photo]
#   default folder: ~/fetch_ws/test_plants (any .jpg photos of the plants in species_labels.py)
#
# DETECTOR_BACKEND / SPECIES_BACKEND / DETECTOR_THRESHOLD work as in scout_ai_up.sh.

FOLDER=${1:-$HOME/fetch_ws/test_plants}
HOLD=${2:-20}
DET=${DETECTOR_BACKEND:-owlvit_torch}; SPEC=${SPECIES_BACKEND:-bioclip}; THRESH=${DETECTOR_THRESHOLD:-0.05}
SRC='source /opt/ros/jazzy/setup.bash && source /ros2_ws/install/setup.bash && source /fetch_ws/install/setup.bash && export ROS_DOMAIN_ID=43 HF_HUB_OFFLINE=1'
[ -d "$FOLDER" ] || { echo "No folder $FOLDER. Put a few plant .jpg photos there."; exit 1; }
[ "$(docker inspect -f '{{.State.Running}}' scout-ai 2>/dev/null)" = "true" ] || { echo "Run ~/scout_ai_up.sh once first (it creates the scout-ai container)."; exit 1; }

for pat in detector_node species_node localizer_node; do docker exec scout-ai pkill -INT -f "$pat"; done
sleep 2
docker exec scout-ai rm -rf /tmp/selftest && docker exec scout-ai mkdir -p /tmp/selftest/photos
docker cp "$FOLDER/." scout-ai:/tmp/selftest/photos >/dev/null
docker exec -d scout-ai bash -c "$SRC && ros2 run scout_perception detector_node --ros-args -p backend:=$DET -p score_threshold:=$THRESH > /tmp/selftest/detector.log 2>&1"
docker exec -d scout-ai bash -c "$SRC && ros2 run scout_perception species_node --ros-args -p backend:=$SPEC > /tmp/selftest/species.log 2>&1"
docker exec -d scout-ai bash -c "$SRC && ros2 run scout_perception localizer_node --ros-args -p missions_dir:=/tmp/selftest/missions > /tmp/selftest/localizer.log 2>&1"
echo "Loading models..."
for i in $(seq 60); do
  docker exec scout-ai bash -c "grep -q 'detector running' /tmp/selftest/detector.log && grep -q 'species node running' /tmp/selftest/species.log" 2>/dev/null && break
  sleep 3
done
docker exec scout-ai bash -c "$SRC && python3 /fetch_ws/src/Understory/pi/scripts/ai_selftest.py /tmp/selftest/photos --hold $HOLD"
for pat in detector_node species_node localizer_node; do docker exec scout-ai pkill -INT -f "$pat"; done
echo "Logs: docker exec scout-ai tail /tmp/selftest/{detector,species,localizer}.log"
echo "The live AI nodes are stopped. Restart them with ~/scout_ai_up.sh"
