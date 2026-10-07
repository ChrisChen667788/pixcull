import importlib.util
import logging
import sys
import types
from contextlib import contextmanager
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


@contextmanager
def _pkg_resources_for_openai_clip():
    """v3.94.1 — the aesthetic axis was missing from every fresh install.

    pyiqa builds both metrics on `clip` (openai-clip 1.0.1), whose module
    begins `from pkg_resources import packaging` to compare torch versions.
    setuptools 82 (2026-02-08) removed pkg_resources, and torch requires
    setuptools, so a fresh install gets the newest; from then on `import clip`
    raised, the ImportError below caught it, and the run went on with five
    axes and one warning line that told the user to install pyiqa — which
    was installed.

    `packaging` is the only name clip takes from it. Provide that, for the
    duration of the import only, and take it away again: a library that
    probes for pkg_resources afterwards must still find it absent, not a
    module with one attribute.
    """
    if "clip" in sys.modules or importlib.util.find_spec("pkg_resources") is not None:
        yield
        return
    import packaging
    import packaging.version  # clip calls packaging.version.parse

    shim = types.ModuleType("pkg_resources")
    shim.packaging = packaging
    sys.modules["pkg_resources"] = shim
    try:
        yield
    finally:
        if sys.modules.get("pkg_resources") is shim:
            del sys.modules["pkg_resources"]


@cache
def _metrics():
    import pyiqa
    import torch

    device = (
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )
    with _pkg_resources_for_openai_clip():
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
            # v3.94.1 — say which import failed. This used to tell everyone
            # to install pyiqa, including the people whose pyiqa was fine
            # and whose `clip` could not find pkg_resources.
            if getattr(exc, "name", None) == "pyiqa":
                hint = ("Install it with `pip install pyiqa` (it ships with "
                        "pixcull; a --no-deps or constrained install can miss it).")
            else:
                hint = (f"pyiqa is installed; the import that failed is "
                        f"{getattr(exc, 'name', None) or 'one of its dependencies'}.")
            logger.warning(
                "aesthetic axis unavailable: %s. %s The other five axes "
                "are unaffected.", exc, hint)
            out = DetectionResult()
            out.flags.append("aesthetic_unavailable")
            return out

        with torch.no_grad():
            t = _pre()(img).unsqueeze(0).to(device)
            result = DetectionResult()
            result.metrics["laion_aes"] = float(metrics["laion_aes"](t).item())
            result.metrics["clipiqa"] = float(metrics["clipiqa"](t).item())
        return result
