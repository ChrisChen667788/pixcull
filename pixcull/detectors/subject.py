from functools import cache

import numpy as np
from PIL import Image

from pixcull.detectors.base import DetectionResult, Detector


@cache
def _session():
    from rembg import new_session
    return new_session(model_name="u2net")


class SubjectDetector(Detector):
    """U²-Net salient object segmentation (via rembg)."""

    name = "subject"

    def analyze(self, img: Image.Image, **_: object) -> DetectionResult:
        from rembg import remove

        mask_img = remove(img, session=_session(), only_mask=True, post_process_mask=True)
        mask = np.array(mask_img) > 127

        result = DetectionResult()
        result.metrics["subject_fraction"] = float(mask.sum()) / mask.size
        if result.metrics["subject_fraction"] < 0.02:
            result.flags.append("no_clear_subject")
        result.extras["mask"] = mask
        return result
