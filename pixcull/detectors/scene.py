from functools import cache

import torch
from PIL import Image

from pixcull.detectors.base import DetectionResult, Detector

SCENE_PROMPTS: dict[str, str] = {
    "portrait":  "a portrait photo of people, wedding or event portrait",
    "wildlife":  "a wildlife photo of a bird or animal in nature",
    "event":     "a sports or event photo with people in action",
    "stilllife": "a product or still life photo, indoor studio setup",
    "landscape": "a landscape or scenery photo, outdoors",
    "street":    "a street photography photo",
}


@cache
def _clip():
    from transformers import CLIPModel, CLIPProcessor

    device = (
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )
    proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device).eval()
    return proc, model, device


class SceneDetector(Detector):
    """CLIP zero-shot scene classifier. No training needed."""

    name = "scene"

    @torch.no_grad()
    def analyze(self, img: Image.Image, **_: object) -> DetectionResult:
        proc, model, device = _clip()
        inputs = proc(
            text=list(SCENE_PROMPTS.values()),
            images=img,
            return_tensors="pt",
            padding=True,
        ).to(device)
        out = model(**inputs)
        probs = out.logits_per_image.softmax(dim=-1).cpu().numpy()[0]
        names = list(SCENE_PROMPTS.keys())
        scene = names[int(probs.argmax())]

        result = DetectionResult()
        result.metrics["scene_confidence"] = float(probs.max())
        result.extras["scene"] = scene
        result.extras["scene_probs"] = dict(zip(names, [float(p) for p in probs]))
        return result
