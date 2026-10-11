"""Species backends. Each one turns a BGR crop into

    (label, invasive, confidence, embedding)      embedding: list of 512 floats

choosing only among the fixed list in species_labels.py. label is None when the crop looks more
like one of the reject_prompts() (not a plant, or another species) than like any listed species.
"""
from scout_perception.species_labels import EMBEDDING_SIZE, SPECIES, prompt, reject_prompts


class DummySpecies:
    """Always the first species, with a zero embedding. For testing the plumbing without a GPU."""

    def classify(self, bgr):
        label, invasive, _ = SPECIES[0]
        return label, invasive, 0.5, [0.0] * EMBEDDING_SIZE


class BioClipSpecies:
    """BioCLIP (imageomics/bioclip) through open_clip. Needs `pip install open_clip_torch`.

    The label text is encoded once here; classify() only runs the image encoder.
    """

    def __init__(self, model_name='hf-hub:imageomics/bioclip'):
        import open_clip
        import torch
        self.torch = torch
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(model_name)
        self.model = self.model.to(self.device).eval()
        # half precision on the GPU: about half the memory. The scoring below stays in float32.
        self.dtype = torch.float16 if self.device == 'cuda' else torch.float32
        self.model = self.model.to(self.dtype)
        tokens = open_clip.get_tokenizer(model_name)(
            [prompt(label, sci) for label, _, sci in SPECIES] + reject_prompts())
        with torch.no_grad():
            text = self.model.encode_text(tokens.to(self.device)).float()
            self.text = text / text.norm(dim=-1, keepdim=True)
            self.scale = self.model.logit_scale.exp().float()

    def classify(self, bgr):
        from PIL import Image
        image = self.preprocess(Image.fromarray(bgr[:, :, ::-1].copy())).unsqueeze(0).to(self.device, self.dtype)
        with self.torch.no_grad():
            emb = self.model.encode_image(image).float()
            emb = emb / emb.norm(dim=-1, keepdim=True)
            probs = (self.scale * emb @ self.text.T).softmax(dim=-1)[0]
        best = int(probs.argmax())
        embedding = [round(v, 5) for v in emb[0].tolist()]
        if best >= len(SPECIES):
            return None, False, float(probs[best]), embedding
        label, invasive, _ = SPECIES[best]
        return label, invasive, float(probs[best]), embedding


BACKENDS = {'dummy': DummySpecies, 'bioclip': BioClipSpecies}


def make_species_backend(name):
    if name not in BACKENDS:
        raise ValueError(f"unknown species backend '{name}', choose one of {sorted(BACKENDS)}")
    return BACKENDS[name]()
