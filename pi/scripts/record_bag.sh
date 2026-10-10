#!/usr/bin/env bash
# record_bag.sh <name> [seconds] - record a test bag to ~/fetch_ws/bags/<name>.
# Works from the host or from inside the container. Ctrl+C to stop (or give a duration).
#   ~/fetch_ws/scripts/record_bag.sh hallway_run1
#   ~/fetch_ws/scripts/record_bag.sh spin_test 30
# Records /scan /camera/image/compressed /tf /tf_static, plus /sensors and /cmd_vel if they exist.

NAME=$1; SECONDS_TO_RECORD=$2
[ -z "$NAME" ] && { echo "usage: record_bag.sh <name> [seconds]"; exit 1; }

# on the host: re-run this same script inside the container
if [ ! -f /.dockerenv ]; then
  [ -t 0 ] && TTY=-it
  exec docker exec $TTY scout bash /fetch_ws/scripts/record_bag.sh "$@"
fi

source /opt/ros/jazzy/setup.bash && source /ros2_ws/install/setup.bash && source /fetch_ws/install/setup.bash
OUT=/fetch_ws/bags/$NAME
[ -e "$OUT" ] && { echo "$OUT already exists, pick another name."; exit 1; }
mkdir -p /fetch_ws/bags

TOPICS="/scan /camera/image/compressed /tf /tf_static"
existing=$(ros2 topic list)
for t in /sensors /cmd_vel; do
  grep -qx "$t" <<<"$existing" && TOPICS="$TOPICS $t"
done
echo "Recording: $TOPICS"
echo "       to: $OUT"

if [ -n "$SECONDS_TO_RECORD" ]; then
  timeout -s INT "$SECONDS_TO_RECORD" ros2 bag record -o "$OUT" $TOPICS
else
  ros2 bag record -o "$OUT" $TOPICS
fi

# the container runs as root; give the bag to whoever owns /fetch_ws so scp works
chown -R "$(stat -c %u:%g /fetch_ws)" /fetch_ws/bags
ros2 bag info "$OUT"
