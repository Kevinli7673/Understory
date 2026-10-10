"""Detector backends. Each one turns a BGR image into a list of boxes:

    [{"label": "a plant", "score": 0.81, "xyxy": [x1, y1, x2, y2]}, ...]   (pixels)

`dummy` needs nothing. `owlvit_torch` needs PyTorch + transformers; it takes 3 to 4 s per frame on
the Pi's CPU and is meant for the Jetson GPU. `nanoowl_trt` is still a STUB.

The detector only finds "a plant"; species_node names the species.
"""

DEFAULT_PROMPTS = ['a plant', 'a leaf', 'a potted plant', 'a photo of a plant', 'a tree', 'grass',
                   'a shrub', 'leaves']


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

    def __init__(self, prompts, threshold=0.1, max_boxes=5, model_name='google/owlvit-base-patch32'):
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
        from torchvision.ops import nms
        h, w = bgr.shape[:2]
        pixels = self.processor(images=bgr[:, :, ::-1].copy(), return_tensors='pt').to(self.device)
        with self.torch.no_grad():
            out = self.model(pixel_values=pixels['pixel_values'].to(self.dtype), **self.text)
        scores, labels = out.logits[0].float().sigmoid().max(dim=-1)
        keep = scores > self.threshold
        scores, labels, boxes = scores[keep], labels[keep], out.pred_boxes[0].float()[keep]
        # pred_boxes are (cx, cy, w, h) as fractions of the image width and height
        cx, cy, bw, bh = (boxes * boxes.new_tensor([w, h, w, h])).unbind(-1)
        xyxy = self.torch.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], dim=-1)
        xyxy = xyxy.clamp(min=0)
        xyxy[:, [0, 2]] = xyxy[:, [0, 2]].clamp(max=w)
        xyxy[:, [1, 3]] = xyxy[:, [1, 3]].clamp(max=h)
        # several prompts fire on the same plant; keep one box per plant
        keep = nms(xyxy, scores, 0.5)[:self.max_boxes]
        return [{'label': self.prompts[int(labels[i])], 'score': round(float(scores[i]), 3),
                 'xyxy': [int(v) for v in xyxy[i].round().tolist()]} for i in keep]


class NanoOwlTrtBackend:
    """STUB (Jetson): NanoOWL with a TensorRT image-encoder engine."""

    def __init__(self, prompts, threshold=0.1):
        # TODO(Jetson): nanoowl.owl_predictor.OwlPredictor(image_encoder_engine=...),
        # then encode_text(prompts) once and cache it.
        raise NotImplementedError('nanoowl_trt backend is a stub; implement it on the Jetson')

    def detect(self, bgr):
        # TODO(Jetson): BGR -> PIL RGB, predictor.predict(...), return boxes.
        raise NotImplementedError


BACKENDS = {'dummy': DummyBackend, 'owlvit_torch': OwlVitTorchBackend, 'nanoowl_trt': NanoOwlTrtBackend}


def make_backend(name, prompts, threshold=0.1):
    if name not in BACKENDS:
        raise ValueError(f"unknown backend '{name}', choose one of {sorted(BACKENDS)}")
    return BACKENDS[name](prompts, threshold)
