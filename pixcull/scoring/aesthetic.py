from functools import cache

import torch
import torchvision.transforms as T
from PIL import Image

from pixcull.detectors.base import DetectionResult, Detector


@cache
def _metrics():
    import pyiqa

    device = (
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )
    return {
        "laion_aes": pyiqa.create_metric("laion_aes", device=device),
        "clipiqa":   pyiqa.create_metric("clipiqa", device=device),
    }, device


_PRE = T.Compose([T.Resize((224, 224)), T.ToTensor()])


class AestheticScorer(Detector):
    """Wraps pyiqa LAION-Aesthetic + CLIP-IQA into one call."""

    name = "aesthetic"

    @torch.no_grad()
    def analyze(self, img: Image.Image, **_: object) -> DetectionResult:
        metrics, device = _metrics()
        t = _PRE(img).unsqueeze(0).to(device)
        result = DetectionResult()
        result.metrics["laion_aes"] = float(metrics["laion_aes"](t).item())
        result.metrics["clipiqa"] = float(metrics["clipiqa"](t).item())
        return result
