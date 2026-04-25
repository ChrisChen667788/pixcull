from typing import Optional

import cv2
import numpy as np
from PIL import Image

from pixcull.detectors.base import DetectionResult, Detector


class BlurDetector(Detector):
    """Global + subject-aware Laplacian variance.

    Emits informational flags against default thresholds (scene-aware
    evaluation happens in fusion). `severely_blurry` is a hard-cull flag
    triggered when sharpness is well below the default floor.
    """

    name = "blur"

    # Defaults tuned for max_side=2048; fusion re-evaluates per-scene.
    DEFAULT_SUBJECT_MIN = 15.0
    DEFAULT_GLOBAL_MIN = 10.0
    SEVERE_RATIO = 0.5  # below DEFAULT * ratio → severely blurry

    def analyze(
        self, img: Image.Image, mask: Optional[np.ndarray] = None, **_: object
    ) -> DetectionResult:
        gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        lap = cv2.Laplacian(gray, cv2.CV_64F)

        result = DetectionResult()
        lap_global = float(lap.var())
        result.metrics["laplacian_global"] = lap_global

        lap_subject: Optional[float] = None
        if mask is not None:
            if mask.shape != gray.shape:
                mask = cv2.resize(
                    mask.astype(np.uint8), (gray.shape[1], gray.shape[0])
                ) > 0
            if mask.sum() >= 100:
                lap_subject = float(lap[mask].var())
                result.metrics["laplacian_subject"] = lap_subject

        reference = lap_subject if lap_subject is not None else lap_global
        threshold = self.DEFAULT_SUBJECT_MIN if lap_subject is not None else self.DEFAULT_GLOBAL_MIN
        if reference < threshold * self.SEVERE_RATIO:
            result.flags.append("severely_blurry")
        elif reference < threshold:
            result.flags.append("subject_blur" if lap_subject is not None else "global_blur")

        return result


def tenengrad(img: Image.Image) -> float:
    """Alternative sharpness metric based on Sobel gradient magnitude."""
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    return float((gx**2 + gy**2).mean())
