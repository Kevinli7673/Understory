#!/usr/bin/env bash
# COLMAP model (from mast3r_poses.py) -> trained Gaussian splat PLY via gsplat's simple_trainer.
#   bash train_splat.sh out/m1/colmap out/m1/gsplat [steps]
set -euo pipefail
DATA=$(cd "$1" && pwd)
mkdir -p "$2"; RESULT=$(cd "$2" && pwd)
STEPS=${3:-7000}
cd "${GSPLAT_DIR:-$HOME/gsplat}/examples"

# Keep the splat in our map frame: turn off gsplat's world-space normalization.
HELP=$(python simple_trainer.py default --help 2>&1 || true)
NORM=""
if grep -q -- "--no-normalize-world-space" <<<"$HELP"; then NORM="--no-normalize-world-space"
elif grep -q -- "--no_normalize_world_space" <<<"$HELP"; then NORM="--no_normalize_world_space"
else echo "warning: can't disable world-space normalization; splat may not line up with the map" >&2
fi

python simple_trainer.py default --data_dir "$DATA" --data_factor 1 --result_dir "$RESULT" \
  --max_steps "$STEPS" --save_ply --ply_steps "$STEPS" --disable_viewer $NORM
ls "$RESULT"/ply/*.ply
