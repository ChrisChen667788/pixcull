"""v2.9-P0-1 — face Close-ups backend.

Covers the serve-time face-detection helper that powers the lightbox
close-ups rail: graceful empty results, normalized-bbox correctness on a
real face, and the path+mtime cache. Heavy/optional deps (mediapipe +
the .task weights, scikit-image for the astronaut fixture) are skipped
gracefully — mirroring the repo's existing "2 face-fixture skips".
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_serve_demo():
    """Import scripts/serve_demo.py as a module without starting the server
    (its socket bind is guarded by ``if __name__ == '__main__'``)."""
    p = ROOT / "scripts" / "serve_demo.py"
    spec = importlib.util.spec_from_file_location("serve_demo", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["serve_demo"] = mod        # set before exec for dataclass resolution
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def sd():
    return _load_serve_demo()


def test_missing_path_returns_empty(sd, tmp_path):
    """A non-existent source yields [] (never raises) — the rail just hides."""
    assert sd._detect_faces_for_src(tmp_path / "nope.jpg") == []


def test_faceless_image_returns_empty(sd, tmp_path):
    """A flat synthetic image has no faces → []."""
    from PIL import Image
    p = tmp_path / "flat.jpg"
    Image.new("RGB", (256, 256), (123, 144, 99)).save(p, "JPEG")
    boxes = sd._detect_faces_for_src(p)
    assert isinstance(boxes, list)
    assert boxes == []          # no face in a solid-colour frame


def _have_mediapipe_models() -> bool:
    try:
        from pixcull.detectors.face import (
            FACE_DETECTOR_MODEL, FACE_LANDMARKER_MODEL)
        import mediapipe  # noqa: F401
    except Exception:
        return False
    return FACE_DETECTOR_MODEL.exists() and FACE_LANDMARKER_MODEL.exists()


def test_real_face_detected_normalized(sd, tmp_path):
    """On a real face, detection fires and every bbox is normalized to [0,1],
    non-degenerate, and the result is cached on a second call."""
    if not _have_mediapipe_models():
        pytest.skip("mediapipe / face weights unavailable")
    try:
        from skimage import data
    except Exception:
        pytest.skip("scikit-image unavailable for the astronaut face fixture")
    from PIL import Image
    p = tmp_path / "astronaut.jpg"
    Image.fromarray(data.astronaut()).save(p, "JPEG", quality=95)

    boxes = sd._detect_faces_for_src(p)
    assert len(boxes) >= 1, "expected at least one face on the astronaut image"
    for nx1, ny1, nx2, ny2, conf in boxes:
        assert 0.0 <= nx1 < nx2 <= 1.0
        assert 0.0 <= ny1 < ny2 <= 1.0
        assert 0.0 <= conf <= 1.0
    # largest-first ordering
    areas = [(b[2] - b[0]) * (b[3] - b[1]) for b in boxes]
    assert areas == sorted(areas, reverse=True)
    # cache hit: same list object back on the second call (no re-detect)
    assert sd._detect_faces_for_src(p) is boxes
