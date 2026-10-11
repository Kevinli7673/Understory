#!/usr/bin/env bash
# One-time setup for amd/deep_pass.py on the Radeon Cloud W7900 box (PyTorch ROCm image, root, no sudo).
# NEVER reinstalls torch: open_clip and timm list torch as a dependency, so they go in with --no-deps.
# splat/setup_amd.sh is separate and either can be run first.
set -euo pipefail
python -c "import torch; print('torch', torch.__version__, '| hip', getattr(torch.version, 'hip', None), '| gpu:', torch.cuda.is_available())"
BEFORE=$(python -c "import torch; print(torch.__version__)")

pip install numpy pillow 'transformers>=4.45' huggingface_hub safetensors ftfy regex tqdm scipy
pip install --no-deps open_clip_torch timm
python -c "import torchvision" 2>/dev/null || echo ">>> torchvision is missing. Install the build that matches this torch from the ROCm wheel index; do not let pip pick one."

AFTER=$(python -c "import torch; print(torch.__version__)")
[ "$BEFORE" = "$AFTER" ] && echo "torch still $AFTER" || { echo ">>> torch changed from $BEFORE to $AFTER: that should not have happened"; exit 1; }

# download the models now (about 2.5 GB), so the mission run does not wait on them
python - <<'PY'
import open_clip
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
for name in ('google/owlv2-large-patch14-ensemble',):
    AutoProcessor.from_pretrained(name); AutoModelForZeroShotObjectDetection.from_pretrained(name)
open_clip.create_model_and_transforms('hf-hub:imageomics/bioclip')
print('models downloaded')
PY
echo "ready: python amd/deep_pass.py missions/<id>"
