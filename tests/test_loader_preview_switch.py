"""RAW loading: the embedded preview is fast and sometimes the wrong pixels.

Sony PP9 is S-Log3, so the camera's embedded JPEG is log-encoded while
the sensor data is not. Measured on a real frame: preview mean 74 / p99
120 against RAW mean 117 / p99 251. Thumbnails look flat and exposure is
scored against a curve the photographer never chose.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("rawpy")

from pixcull.io import loader


def test_preview_is_the_default(monkeypatch):
    monkeypatch.delenv("PIXCULL_RAW_PREVIEW", raising=False)
    assert loader.raw_preview_enabled() is True


@pytest.mark.parametrize("value", ["0", "off", "false", "no", "OFF"])
def test_any_off_spelling_disables_the_preview(monkeypatch, value):
    monkeypatch.setenv("PIXCULL_RAW_PREVIEW", value)
    assert loader.raw_preview_enabled() is False


@pytest.mark.parametrize("value", ["1", "on", "true", ""])
def test_anything_else_keeps_it(monkeypatch, value):
    monkeypatch.setenv("PIXCULL_RAW_PREVIEW", value)
    assert loader.raw_preview_enabled() is True


def test_raw_decode_path_runs_when_the_preview_is_off(monkeypatch, tmp_path):
    """The switch has to change what load_image actually does, not just
    what a helper reports."""
    calls = {"postprocess": 0}

    class FakeRaw:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_thumb(self):
            raise AssertionError("preview path taken with the switch off")

        def postprocess(self, **kw):
            calls["postprocess"] += 1
            import numpy as np
            return np.zeros((4, 4, 3), dtype=np.uint8)

    monkeypatch.setenv("PIXCULL_RAW_PREVIEW", "0")
    monkeypatch.setattr(loader.rawpy, "imread", lambda _p: FakeRaw())
    src = tmp_path / "A.ARW"
    src.write_bytes(b"x")

    img = loader.load_image(src)
    assert img is not None
    assert calls["postprocess"] == 1
