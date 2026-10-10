#!/usr/bin/env bash
# missions/<id> -> out/<id>/scene.splat + scene.ply for Unity.
#   bash run.sh missions/m1 [xmin xmax ymin ymax zmin zmax]
# Splat first; if anything fails, fall back to a point cloud (AGENTS.md fallbacks).
set -uo pipefail
MISSION=${1:?usage: run.sh missions/m1 [xmin xmax ymin ymax zmin zmax]}
shift
CROP=()
[ $# -eq 6 ] && CROP=(--crop "$@")
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=out/$(basename "$MISSION")
mkdir -p "$OUT"

SRC=""
if python "$HERE/mast3r_poses.py" "$MISSION" "$OUT/colmap"; then
  if bash "$HERE/train_splat.sh" "$OUT/colmap" "$OUT/gsplat"; then
    SRC=$(ls -t "$OUT"/gsplat/ply/*.ply | head -1)
  else
    echo ">>> gsplat failed -> MASt3R point cloud"
    SRC=$OUT/colmap/mast3r_points.ply
  fi
else
  echo ">>> MASt3R failed -> Depth Anything point cloud"
  python "$HERE/depth_cloud.py" "$MISSION" "$OUT/cloud.ply" || exit 1
  SRC=$OUT/cloud.ply
fi

python "$HERE/ply_to_splat.py" "$SRC" "$OUT/scene.splat" --out-ply "$OUT/scene.ply" ${CROP[@]+"${CROP[@]}"}
echo "done: $OUT/scene.splat ($SRC)"
