#!/usr/bin/env bash
# One-time setup on the Radeon Cloud W7900 box (PyTorch ROCm image, logged in as root, no sudo).
# NEVER reinstalls torch: every requirements file is filtered first.
set -euo pipefail
cd ~
REQ=$(mktemp)
no_torch() { grep -viE '^\s*(torch|torchvision|torchaudio)\b' "$1" > "$REQ" || true; }

python -c "import torch; print('torch', torch.__version__, '| gpu:', torch.cuda.is_available())"
pip install numpy pillow 'transformers>=4.45'

[ -d mast3r ] || git clone --recursive https://github.com/naver/mast3r
no_torch mast3r/requirements.txt && pip install -r "$REQ"
no_torch mast3r/dust3r/requirements.txt && pip install -r "$REQ"

# gsplat has CUDA kernels. Try a ROCm build first, then upstream. If both fail,
# run.sh falls back to the MASt3R / Depth Anything point cloud.
[ -d gsplat ] || git clone --recursive https://github.com/nerfstudio-project/gsplat
pip install --no-deps --no-build-isolation git+https://github.com/ROCm/gsplat.git \
  || pip install --no-deps --no-build-isolation gsplat \
  || echo ">>> gsplat install failed; run.sh will use the point-cloud fallback"
no_torch gsplat/examples/requirements.txt && pip install -r "$REQ" || echo ">>> some gsplat example deps failed"

python -c "import torch; print('torch still', torch.__version__)"
