#!/usr/bin/env bash
# run.sh - serve the dashboard to the other machines on the network (http://<this machine's IP>:8501).
#   dashboard/run.sh                                  # missions from ~/fetch_ws/missions if it exists, else the repo defaults
#   MISSIONS_DIR=fake_data/missions dashboard/run.sh
#   dashboard/run.sh --stop
# First time: python3 -m venv dashboard/.venv && dashboard/.venv/bin/pip install -r dashboard/requirements.txt
HERE=$(dirname "$(readlink -f "$0")")
LOG=${DASHBOARD_LOG:-$HOME/fetch_ws/logs/dashboard.log}
if [ "$1" = "--stop" ]; then pkill -f "streamlit run $HERE/app.py" && echo "Dashboard stopped."; exit 0; fi
if pgrep -f "streamlit run $HERE/app.py" >/dev/null; then echo "Dashboard already running."; exit 0; fi
if [ -z "$MISSIONS_DIR" ] && [ -d "$HOME/fetch_ws/missions" ]; then export MISSIONS_DIR=$HOME/fetch_ws/missions; fi
mkdir -p "$(dirname "$LOG")"
nohup "$HERE/.venv/bin/streamlit" run "$HERE/app.py" --server.address 0.0.0.0 --server.port "${PORT:-8501}" \
  --server.headless true --browser.gatherUsageStats false > "$LOG" 2>&1 &
sleep 4
if pgrep -f "streamlit run $HERE/app.py" >/dev/null; then
  echo "Dashboard: http://$(hostname -I | awk '{print $1}'):${PORT:-8501}   (log: $LOG)"
else
  echo "Dashboard did not start; see $LOG"; exit 1
fi
