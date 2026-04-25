import cv2
import numpy as np
from PIL import Image

from pixcull.detectors.base import DetectionResult, Detector


class ExposureDetector(Detector):
    """Histogram-based exposure diagnostics."""

    name = "exposure"

    def analyze(self, img: Image.Image, **_: object) -> DetectionResult:
        arr = np.array(img)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        total = gray.size

        result = DetectionResult()
        result.metrics["mean_luma"] = float(gray.mean())
        result.metrics["highlight_clip_pct"] = float((gray > 250).sum() / total * 100)
        result.metrics["shadow_clip_pct"] = float((gray < 5).sum() / total * 100)

        if result.metrics["highlight_clip_pct"] > 5:
            result.flags.append("highlights_clipped")
        if result.metrics["shadow_clip_pct"] > 5:
            result.flags.append("shadows_clipped")
        if result.metrics["mean_luma"] < 40:
            result.flags.append("severely_underexposed")
        elif result.metrics["mean_luma"] > 220:
            result.flags.append("severely_overexposed")

        return result
