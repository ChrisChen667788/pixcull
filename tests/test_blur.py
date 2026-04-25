import numpy as np
from PIL import Image

from pixcull.detectors.blur import BlurDetector, tenengrad


def test_blur_detector_returns_global_metric(sample_image):
    d = BlurDetector()
    r = d.analyze(sample_image)
    assert "laplacian_global" in r.metrics
    assert r.metrics["laplacian_global"] >= 0


def test_blur_detector_with_mask(sample_image):
    d = BlurDetector()
    mask = np.zeros((512, 512), dtype=bool)
    mask[100:400, 100:400] = True
    r = d.analyze(sample_image, mask=mask)
    assert "laplacian_subject" in r.metrics


def test_tenengrad_positive(sample_image):
    assert tenengrad(sample_image) > 0


def test_sharp_image_beats_blurred(sample_image):
    """A blurred version of random noise should have lower Laplacian variance."""
    import cv2
    arr = np.array(sample_image)
    blurred = Image.fromarray(cv2.GaussianBlur(arr, (15, 15), 0))
    d = BlurDetector()
    sharp_lap = d.analyze(sample_image).metrics["laplacian_global"]
    blur_lap = d.analyze(blurred).metrics["laplacian_global"]
    assert sharp_lap > blur_lap
