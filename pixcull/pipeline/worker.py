import time
from functools import cache
from pathlib import Path
from typing import Optional

from pixcull.detectors.blur import BlurDetector
from pixcull.detectors.composition import CompositionDetector
from pixcull.detectors.duplicate import DuplicateDetector
from pixcull.detectors.exposure import ExposureDetector
from pixcull.detectors.face import FaceDetector
from pixcull.detectors.scene import SceneDetector
from pixcull.detectors.subject import SubjectDetector
from pixcull.io.exif import read_exif_time
from pixcull.io.loader import load_image
from pixcull.scoring.aesthetic import AestheticScorer


@cache
def _detectors():
    return {
        "subject":     SubjectDetector(),
        "blur":        BlurDetector(),
        "exposure":    ExposureDetector(),
        "scene":       SceneDetector(),
        "duplicate":   DuplicateDetector(),
        "aesthetic":   AestheticScorer(),
        "face":        FaceDetector(),
        "composition": CompositionDetector(),
    }


def analyze_one(path: Path) -> Optional[dict]:
    """Run all single-image detectors. Clustering happens later in the orchestrator."""
    img = load_image(path)
    if img is None:
        return None

    t0 = time.time()
    d = _detectors()
    subj = d["subject"].analyze(img)
    mask = subj.extras.get("mask")
    blur = d["blur"].analyze(img, mask=mask)
    expo = d["exposure"].analyze(img)
    scene = d["scene"].analyze(img)
    scene_name = scene.extras["scene"]
    dup = d["duplicate"].analyze(img)
    aes = d["aesthetic"].analyze(img)
    face = d["face"].analyze(img)
    comp = d["composition"].analyze(img, mask=mask, scene=scene_name)

    metrics: dict = {}
    flags: list[str] = []
    for r in (subj, blur, expo, scene, dup, aes, face, comp):
        metrics.update(r.metrics)
        flags.extend(r.flags)

    return {
        "path": str(path),
        "filename": path.name,
        "datetime": read_exif_time(path),
        "scene": scene_name,
        "scene_probs": scene.extras["scene_probs"],
        "embedding": dup.extras["embedding"],
        "flags": flags,
        "elapsed_s": time.time() - t0,
        **metrics,
    }
