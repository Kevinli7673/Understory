"""Detector backends. Each one turns a BGR image into a list of boxes:

    [{"label": "Brazilian pepper", "score": 0.81, "xyxy": [x1, y1, x2, y2]}, ...]   (pixels)

Only `dummy` is implemented. The Pi CPU is too slow for real models; the other two are
STUBS to be filled in on the Jetson.
"""

DEFAULT_LABELS = ['Brazilian pepper', 'air potato', 'cogongrass', 'saw palmetto', 'wild coffee']


class DummyBackend:
    """One fixed box in the centre of every frame. For testing the plumbing only."""

    def __init__(self, labels):
        self.label = labels[0]

    def detect(self, bgr):
        h, w = bgr.shape[:2]
        return [{'label': self.label, 'score': 0.5,
                 'xyxy': [w // 4, h // 4, 3 * w // 4, 3 * h // 4]}]


class OwlVitTorchBackend:
    """STUB (Jetson): OWL-ViT through HuggingFace transformers + PyTorch."""

    def __init__(self, labels):
        # TODO(Jetson): load OwlViTProcessor / OwlViTForObjectDetection ("google/owlvit-base-patch32"),
        # move to cuda, keep `labels` as the text prompts.
        raise NotImplementedError('owlvit_torch backend is a stub; implement it on the Jetson')

    def detect(self, bgr):
        # TODO(Jetson): BGR -> RGB, run the model, post_process_object_detection, return boxes.
        raise NotImplementedError


class NanoOwlTrtBackend:
    """STUB (Jetson): NanoOWL with a TensorRT image-encoder engine."""

    def __init__(self, labels):
        # TODO(Jetson): nanoowl.owl_predictor.OwlPredictor(image_encoder_engine=...),
        # then encode_text(labels) once and cache it.
        raise NotImplementedError('nanoowl_trt backend is a stub; implement it on the Jetson')

    def detect(self, bgr):
        # TODO(Jetson): BGR -> PIL RGB, predictor.predict(...), return boxes.
        raise NotImplementedError


BACKENDS = {'dummy': DummyBackend, 'owlvit_torch': OwlVitTorchBackend, 'nanoowl_trt': NanoOwlTrtBackend}


def make_backend(name, labels):
    if name not in BACKENDS:
        raise ValueError(f"unknown backend '{name}', choose one of {sorted(BACKENDS)}")
    return BACKENDS[name](labels)
