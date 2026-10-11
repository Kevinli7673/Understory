#!/usr/bin/env bash
# Everything the W7900 box does for one mission, from the Hugging Face dataset and back:
#   bash amd/run_all.sh m1
# Needs HF_DATASET_REPO and HF_TOKEN (environment or .env at the repo root), and amd/setup_amd.sh run once.
# The mission has to be in the dataset already (dashboard/sync.py puts it there).
# The splat is optional: if it fails, the deep pass is still sent. SKIP_SPLAT=1 leaves it out.
# Extra arguments go to deep_pass.py:  bash amd/run_all.sh m1 --detector google/owlv2-base-patch16-ensemble
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
ID=${1:?usage: bash amd/run_all.sh <mission id> [deep_pass.py options]}; shift

python amd/hub.py pull "$ID" || exit 1
python amd/deep_pass.py "missions/$ID" "$@" || exit 1
if [ -z "${SKIP_SPLAT:-}" ]; then
  bash splat/run.sh "missions/$ID" || echo ">>> the splat failed (see above). Sending the deep pass without it."
fi
python amd/hub.py push "missions/$ID" || exit 1
echo "--- missions/$ID/deep_report.json holds the numbers for the pitch ---"
head -c 1500 "missions/$ID/deep_report.json"; echo
