import logging
from functools import cache

logger = logging.getLogger(__name__)

from PIL import Image

from pixcull.detectors.base import DetectionResult, Detector

# NOTE: torch + torchvision are NOT imported at module load — they cost
# ~30s to import cold and pull in the whole neural stack.  Anything that
# only needs the lightweight scoring package (e.g. color_grade's numpy
# LUTs, or a CLI path that never runs the aesthetic model) must not pay
# that.  They are imported lazily inside the functions that actually use
# them (_metrics / _pre / AestheticScorer.analyze).  See
# docs/ROADMAP-v2.2-charter.md and the import-hygiene fix notes.


@cache
def _metrics():
    import pyiqa
    import torch

    device = (
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )
    return {
        "laion_aes": pyiqa.create_metric("laion_aes", device=device),
        "clipiqa":   pyiqa.create_metric("clipiqa", device=device),
    }, device


@cache
def _pre():
    """Preprocess transform, built once on first use (lazy: torchvision
    import is part of the heavy stack we defer past module load)."""
    import torchvision.transforms as T

    return T.Compose([T.Resize((224, 224)), T.ToTensor()])


class AestheticScorer(Detector):
    """Wraps pyiqa LAION-Aesthetic + CLIP-IQA into one call."""

    name = "aesthetic"

    def analyze(self, img: Image.Image, **_: object) -> DetectionResult:
        import torch

        # v3.60 — pyiqa missing must not take the run down with it.
        #
        # It is a required dependency, so this should not happen from a
        # plain `pip install pixcull`. It happens in the environments
        # people actually build: `--no-deps`, a constrained mirror, a
        # conda base where the resolver gave up. Before this, the whole
        # pipeline died on `ImportError: No module named pyiqa` at the
        # first photograph, with nothing to say which of two dozen
        # dependencies was the one.
        #
        # The other five rubric axes do not need it. Losing the aesthetic
        # axis is a real loss and it is reported as one — an empty result
        # with a flag, not silence, and not a crash.
        try:
            metrics, device = _metrics()
        except ImportError as exc:
            logger.warning(
                "aesthetic axis unavailable: %s. Install it with "
                "`pip install pyiqa` (it ships with pixcull; a --no-deps "
                "or constrained install can miss it). The other five axes "
                "are unaffected.", exc)
            out = DetectionResult()
            out.flags.append("aesthetic_unavailable")
            return out

        with torch.no_grad():
            t = _pre()(img).unsqueeze(0).to(device)
            result = DetectionResult()
            result.metrics["laion_aes"] = float(metrics["laion_aes"](t).item())
            result.metrics["clipiqa"] = float(metrics["clipiqa"](t).item())
        return result
