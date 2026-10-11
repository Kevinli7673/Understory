#!/usr/bin/env bash
# run.sh - serve the dashboard and its live feeds to the other machines on the network.
#   dashboard/run.sh            dashboard on :8501, live relay on :8770, and (on the Jetson or Pi, where the ROS
#                               container "scout" runs) the LiDAR bridge that feeds the relay
#   dashboard/run.sh --stop     stop all three
#   MISSIONS_DIR=fake_data/missions dashboard/run.sh     default: ~/fetch_ws/missions if it exists, else the repo defaults
#   NO_LIVE=1 dashboard/run.sh  dashboard only
# First time: python3 -m venv dashboard/.venv && dashboard/.venv/bin/pip install -r dashboard/requirements.txt
# The Quest sends its view to ws://<this machine>:8770/ws/headset/pub once dashboard_ip.txt is on it (dashboard/README.md).
HERE=$(dirname "$(readlink -f "$0")")
LOGS=${DASHBOARD_LOGS:-$HOME/fetch_ws/logs}
PORT=${PORT:-8501}
BRIDGE=/fetch_ws/src/Understory/dashboard/scan_bridge.py
has_scout() { command -v docker >/dev/null && [ "$(docker inspect -f '{{.State.Running}}' scout 2>/dev/null)" = true ]; }

if [ "$1" = "--stop" ]; then
  pkill -f "streamlit run $HERE/app.py"; pkill -f "$HERE/live_relay.py"
  has_scout && docker exec scout pkill -f scan_bridge.py
  echo "Dashboard, live relay and LiDAR bridge stopped."; exit 0
fi
mkdir -p "$LOGS"
cd "$HERE/.." || exit 1   # Streamlit reads .streamlit/config.toml (theme, fonts) from the folder it runs in
if [ -z "$MISSIONS_DIR" ] && [ -d "$HOME/fetch_ws/missions" ]; then export MISSIONS_DIR=$HOME/fetch_ws/missions; fi

if [ -z "$NO_LIVE" ]; then
  if pgrep -f "$HERE/live_relay.py" >/dev/null; then echo "Live relay already running."
  else nohup "$HERE/.venv/bin/python" "$HERE/live_relay.py" > "$LOGS/live_relay.log" 2>&1 & fi
  if has_scout; then
    if docker exec scout pgrep -f scan_bridge.py >/dev/null; then echo "LiDAR bridge already running."
    else docker exec -d scout bash -c "source /opt/ros/jazzy/setup.bash && python3 $BRIDGE --relay http://127.0.0.1:8770 > /fetch_ws/logs/scan_bridge.log 2>&1"; fi
  else
    echo "No ROS container here: run scan_bridge.py where mapping runs (dashboard/README.md) for the live LiDAR."
  fi
fi
if pgrep -f "streamlit run $HERE/app.py" >/dev/null; then echo "Dashboard already running."
else
  nohup "$HERE/.venv/bin/streamlit" run "$HERE/app.py" --server.address 0.0.0.0 --server.port "$PORT" \
    --server.headless true --browser.gatherUsageStats false > "$LOGS/dashboard.log" 2>&1 &
fi
sleep 5
IP=$(hostname -I | awk '{print $1}')
if pgrep -f "streamlit run $HERE/app.py" >/dev/null; then echo "Dashboard:  http://$IP:$PORT   (log: $LOGS/dashboard.log)"
else echo "Dashboard did not start; see $LOGS/dashboard.log"; exit 1; fi
if [ -z "$NO_LIVE" ]; then
  if pgrep -f "$HERE/live_relay.py" >/dev/null; then echo "Live relay: http://$IP:8770/health   Quest: put $IP in dashboard_ip.txt"
  else echo "Live relay did not start; see $LOGS/live_relay.log (pip install -r dashboard/requirements.txt?)"; fi
fi
