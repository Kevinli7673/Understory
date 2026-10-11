"""Detector backends. Each one turns a BGR image into a list of boxes:

    [{"label": "a plant", "score": 0.81, "xyxy": [x1, y1, x2, y2]}, ...]   (pixels)

`dummy` needs nothing. `owlvit_torch` needs PyTorch + transformers; it takes 3 to 4 s per frame on
the Pi's CPU and is meant for the Jetson GPU. `nanoowl_trt` is the same model with its image side
compiled by TensorRT; it needs the `tensorrt` package and an engine file built on the Jetson with
pi/scripts/build_owl_engine.py.

The detector only finds "a plant"; species_node names the species.
"""

import os

DEFAULT_PROMPTS = ['a plant', 'a leaf', 'a potted plant', 'a photo of a plant', 'a tree', 'grass',
                   'a shrub', 'leaves']
OWL_MODEL = 'google/owlvit-base-patch32'
OWL_ENGINE = '/fetch_ws/models/owlvit-base-patch32.engine'


def owl_boxes(torch, logits, pred_boxes, w, h, prompts, threshold, max_boxes):
    """OWL-ViT outputs for one image (logits [patches, prompts], boxes [patches, 4]) -> box dicts."""
    from torchvision.ops import nms
    scores, labels = logits.float().sigmoid().max(dim=-1)
    keep = scores > threshold
    scores, labels, boxes = scores[keep], labels[keep], pred_boxes.float()[keep]
    # pred_boxes are (cx, cy, w, h) as fractions of the image width and height
    cx, cy, bw, bh = (boxes * boxes.new_tensor([w, h, w, h])).unbind(-1)
    xyxy = torch.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], dim=-1)
    xyxy = xyxy.clamp(min=0)
    xyxy[:, [0, 2]] = xyxy[:, [0, 2]].clamp(max=w)
    xyxy[:, [1, 3]] = xyxy[:, [1, 3]].clamp(max=h)
    # several prompts fire on the same plant; keep one box per plant
    keep = nms(xyxy, scores, 0.5)[:max_boxes]
    return [{'label': prompts[int(labels[i])], 'score': round(float(scores[i]), 3),
             'xyxy': [int(v) for v in xyxy[i].round().tolist()]} for i in keep]


class DummyBackend:
    """One fixed box in the centre of every frame. For testing the plumbing only."""

    def __init__(self, prompts, threshold=0.1):
        self.label = prompts[0]

    def detect(self, bgr):
        h, w = bgr.shape[:2]
        return [{'label': self.label, 'score': 0.5,
                 'xyxy': [w // 4, h // 4, 3 * w // 4, 3 * h // 4]}]


class OwlVitTorchBackend:
    """OWL-ViT through HuggingFace transformers + PyTorch. Needs `pip install transformers torchvision`.

    Uses the GPU when there is one. The prompts are tokenized once here, not per frame.
    """

    def __init__(self, prompts, threshold=0.1, max_boxes=5, model_name=OWL_MODEL):
        import torch
        from transformers import OwlViTForObjectDetection, OwlViTProcessor
        self.torch = torch
        self.prompts, self.threshold, self.max_boxes = list(prompts), threshold, max_boxes
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.processor = OwlViTProcessor.from_pretrained(model_name)
        self.model = OwlViTForObjectDetection.from_pretrained(model_name).to(self.device).eval()
        # half precision on the GPU: about half the memory (the Jetson shares 8 GB with everything else)
        self.dtype = torch.float16 if self.device == 'cuda' else torch.float32
        self.model = self.model.to(self.dtype)
        self.text = self.processor(text=[self.prompts], return_tensors='pt').to(self.device)

    def detect(self, bgr):
        h, w = bgr.shape[:2]
        # device: the resize to 768x768 runs on the GPU when there is one (6 ms instead of 26 on the Jetson)
        pixels = self.processor(images=bgr[:, :, ::-1].copy(), return_tensors='pt', device=self.device)
        with self.torch.no_grad():
            out = self.model(pixel_values=pixels['pixel_values'].to(self.dtype), **self.text)
        return owl_boxes(self.torch, out.logits[0], out.pred_boxes[0], w, h,
                         self.prompts, self.threshold, self.max_boxes)


class NanoOwlTrtBackend:
    """OWL-ViT the way NanoOWL runs it: the image side (vision transformer, box head, class head) is one
    TensorRT engine, and the prompts are encoded once with PyTorch at startup.

    Needs a CUDA GPU, `tensorrt`, and the engine file from pi/scripts/build_owl_engine.py (set
    OWL_ENGINE to use another path). An engine only runs on the kind of GPU that built it.
    """

    def __init__(self, prompts, threshold=0.1, max_boxes=5, model_name=OWL_MODEL, engine=None):
        import numpy as np
        import tensorrt as trt
        import torch
        from transformers import OwlViTForObjectDetection, OwlViTProcessor
        engine = engine or os.environ.get('OWL_ENGINE', OWL_ENGINE)
        if not os.path.exists(engine):
            raise FileNotFoundError(f'no TensorRT engine at {engine}; build it with pi/scripts/build_owl_engine.py')
        self.torch = torch
        self.prompts, self.threshold, self.max_boxes = list(prompts), threshold, max_boxes
        self.processor = OwlViTProcessor.from_pretrained(model_name)
        # the text side runs once, on the CPU, and is then dropped
        model = OwlViTForObjectDetection.from_pretrained(model_name).eval()
        text = self.processor(text=[self.prompts], return_tensors='pt')
        with torch.no_grad():
            query = model.owlvit.text_projection(model.owlvit.text_model(**text).pooler_output)
        self.query = (query / (query.norm(dim=-1, keepdim=True) + 1e-6)).cuda()
        del model

        self.logger = trt.Logger(trt.Logger.WARNING)
        with open(engine, 'rb') as f:
            self.engine = trt.Runtime(self.logger).deserialize_cuda_engine(f.read())
        self.context = self.engine.create_execution_context()
        self.stream = torch.cuda.Stream()   # TensorRT is slower on PyTorch's default stream
        # TensorRT reads and writes these GPU tensors in place
        self.io = {}
        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            dtype = torch.from_numpy(np.zeros(1, trt.nptype(self.engine.get_tensor_dtype(name)))).dtype
            self.io[name] = torch.zeros(tuple(self.engine.get_tensor_shape(name)), dtype=dtype, device='cuda')
            self.context.set_tensor_address(name, self.io[name].data_ptr())

    def detect(self, bgr):
        torch = self.torch
        h, w = bgr.shape[:2]
        # every GPU step on the one stream, in order. With the resize on PyTorch's default stream and
        # the engine on another, the engine read its input before the resize had written it and
        # returned the boxes of the previous frame.
        with torch.cuda.stream(self.stream):
            pixels = self.processor(images=bgr[:, :, ::-1].copy(), return_tensors='pt', device='cuda')['pixel_values']
            self.io['pixel_values'].copy_(pixels)
            self.context.execute_async_v3(self.stream.cuda_stream)
            out = {k: v[0].float() for k, v in self.io.items()}
            logits = (out['class_embeds'] @ self.query.T + out['logit_shift']) * out['logit_scale']
            return owl_boxes(torch, logits, out['pred_boxes'], w, h, self.prompts, self.threshold, self.max_boxes)


BACKENDS = {'dummy': DummyBackend, 'owlvit_torch': OwlVitTorchBackend, 'nanoowl_trt': NanoOwlTrtBackend}


def make_backend(name, prompts, threshold=0.1):
    if name not in BACKENDS:
        raise ValueError(f"unknown backend '{name}', choose one of {sorted(BACKENDS)}")
    return BACKENDS[name](prompts, threshold)
