#!/usr/bin/env python3
"""Build the TensorRT engine that the `nanoowl_trt` detector backend runs (Jetson, in the scout-ai container).

The image side of OWL-ViT (vision transformer, box head, class head) is exported to ONNX and compiled
in half precision. The text side stays in PyTorch and runs once per start, so the prompts can change
without a rebuild. Then the engine is checked against PyTorch on one photo.

    docker exec scout-ai python3 /fetch_ws/src/Understory/pi/scripts/build_owl_engine.py [photo.jpg]

It takes several minutes and a few GB of memory: stop the AI nodes first (~/scout_ai_up.sh --stop).
The engine only works on the kind of GPU that built it, so it is not in the repo.
"""
import os
import sys
import time

import cv2
import numpy as np
import tensorrt as trt
import torch
from transformers import OwlViTForObjectDetection

from scout_perception.backends import DEFAULT_PROMPTS, OWL_ENGINE, OWL_MODEL, NanoOwlTrtBackend, OwlVitTorchBackend


class ImageSide(torch.nn.Module):
    """pixel_values -> everything OWL-ViT computes from the image alone."""

    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, pixel_values):
        m = self.model
        feature_map, _ = m.image_embedder(pixel_values)
        feats = feature_map.reshape(feature_map.shape[0], -1, feature_map.shape[-1])
        head = m.class_head
        class_embeds = head.dense0(feats)
        class_embeds = class_embeds / (torch.linalg.norm(class_embeds, dim=-1, keepdim=True) + 1e-6)
        return (class_embeds, head.logit_shift(feats), head.elu(head.logit_scale(feats)) + 1,
                m.box_predictor(feats, feature_map))


def main():
    engine_path = os.environ.get('OWL_ENGINE', OWL_ENGINE)
    onnx_path = engine_path.replace('.engine', '.onnx')
    os.makedirs(os.path.dirname(engine_path), exist_ok=True)

    # TensorRT 11 takes its precision from the ONNX file, so the export itself is in half precision
    model = OwlViTForObjectDetection.from_pretrained(OWL_MODEL).eval().half().cuda()
    size = model.config.vision_config.image_size
    print(f'Exporting the image side to {onnx_path} ...')
    pixels = torch.zeros(1, 3, size, size, dtype=torch.float16, device='cuda')
    torch.onnx.export(ImageSide(model), (pixels,), onnx_path, dynamo=False,
                      input_names=['pixel_values'], opset_version=17,
                      output_names=['class_embeds', 'logit_shift', 'logit_scale', 'pred_boxes'])
    del model, pixels
    torch.cuda.empty_cache()

    print('Building the engine (several minutes) ...')
    t0 = time.time()
    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    network = builder.create_network()
    parser = trt.OnnxParser(network, logger)
    if not parser.parse_from_file(onnx_path):
        sys.exit('\n'.join(str(parser.get_error(i)) for i in range(parser.num_errors)))
    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 2 << 30)
    blob = builder.build_serialized_network(network, config)
    if blob is None:
        sys.exit('engine build failed')
    with open(engine_path, 'wb') as f:
        f.write(blob)
    print(f'Wrote {engine_path} ({os.path.getsize(engine_path) / 1e6:.0f} MB) in {time.time() - t0:.0f} s')
    del blob, builder, network, parser, config

    # same photo through both backends
    photo = cv2.imread(sys.argv[1]) if len(sys.argv) > 1 else None
    if photo is None:
        photo = np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8)
    for name, cls in (('tensorrt', NanoOwlTrtBackend), ('pytorch', OwlVitTorchBackend)):
        boxes = cls(DEFAULT_PROMPTS, 0.05).detect(photo)
        print(f'{name:9s}', boxes)


if __name__ == '__main__':
    main()
