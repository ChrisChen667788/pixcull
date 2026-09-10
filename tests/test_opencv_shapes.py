"""v3.65 fixup — the OpenCV 5 shape change, and where else it can bite.

`cv2.HoughLinesP` returns `(N, 1, 4)` on OpenCV 4 and `(N, 4)` on
OpenCV 5. `pyproject.toml` pins `opencv-python>=4.9` with no ceiling, so
the first CI machine to resolve 5.0.0.93 raised

    IndexError: too many indices for array: array is 2-dimensional,
    but 3 were indexed

on every photograph and took the horizon-tilt signal with it. Seven
tests failed, all in `test_composition.py`, and none of them failed
locally — this laptop still had 4.11 from an earlier resolve, so the
upgrade that triggered it (numpy, which forced a full re-resolve) looked
clean on the machine that made it.

Two things follow, and this file is both:

1. The detector must work under either shape, checked directly rather
   than through whichever OpenCV happens to be installed.
2. Nothing else may index an OpenCV result by a hard-coded middle axis.
   `HoughLinesP` was the only one; `findContours`, `goodFeaturesToTrack`
   and `HoughCircles` have the same `(N, 1, …)` habit and the same
   exposure, so the second test is about the class of defect, not this
   instance of it.
"""
import re
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("shape", [(3, 1, 4), (3, 4)])
def test_horizon_tilt_reads_both_opencv_shapes(monkeypatch, shape):
    """The same three line segments, delivered the two ways OpenCV
    delivers them, have to produce the same angle."""
    cv2 = pytest.importorskip("cv2")
    from pixcull.detectors import composition

    # Three segments tilted ~11.3° (dy/dx = 1/5) across a wide frame.
    segs = np.array([[0, 0, 500, 100],
                     [0, 50, 500, 150],
                     [0, 100, 500, 200]], dtype=np.int32)
    monkeypatch.setattr(cv2, "HoughLinesP",
                        lambda *a, **k: segs.reshape(shape))

    gray = np.zeros((400, 600), dtype=np.uint8)
    tilt = composition._detect_horizon_tilt(gray)
    assert tilt is not None, f"no tilt read from an OpenCV {shape} result"
    assert abs(tilt - 11.3) < 1.0, (
        f"shape {shape} gave {tilt}° for segments that are 11.3°")


def test_nothing_indexes_an_opencv_result_by_a_fixed_middle_axis():
    """`lines[:, 0, :]` is correct on one major version and an IndexError
    on the other. `.reshape(-1, N)` is correct on both, so the pattern
    is what this forbids — not the one call that was already wrong."""
    offenders = []
    for path in sorted((ROOT / "pixcull").rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        if "cv2" not in src:
            continue
        body = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
        for m in re.finditer(r"\b(\w+)\[\s*:\s*,\s*0\s*,\s*:\s*\]", body):
            offenders.append(f"{path.relative_to(ROOT)}: {m.group(0)}")
    assert not offenders, (
        "these index an array by a hard-coded middle axis, which OpenCV 5 "
        f"removed from several return shapes: {offenders}. Use "
        ".reshape(-1, N) — it is right under both majors.")


def test_the_opencv_pin_says_which_majors_were_tested():
    """The pin was `>=4.9` with nothing above it, so a major release
    nobody had run arrived silently. It does not have to be narrow, but
    it does have to be deliberate."""
    src = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    body = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    m = re.search(r'"opencv-python([^"]*)"', body)
    assert m, "pyproject.toml no longer declares opencv-python"
    assert "<" in m.group(1), (
        f'opencv-python is pinned as "{m.group(1)}" — an open upper bound, '
        "which is how 5.0.0.93 arrived in CI with nothing having run "
        "against it. State the ceiling you have tested.")
