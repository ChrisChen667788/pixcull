"""v2.0-P2-2 — Color-graded preview overlay.

Charter ``docs/ROADMAP-v2.0-charter.md`` § v2.0-P2-2: show photographers
a one-click film-look preview on the video review surface (and on each
reel candidate's thumbnail), with the looks they actually reach for —
Fuji Eterna, Kodak Vision3, Arri 709A — plus teal/orange and B&W.

Rather than ship binary ``.cube`` LUT assets (a dependency + licensing
question), each look is a small **parametric grade**: an ASC-CDL-style
per-channel ``slope · offset · power`` plus a saturation term, applied in
numpy.  It's a *preview* — fast, dependency-light, and visually in the
right neighbourhood — not a colour-managed deliverable.

``apply_grade(img, preset)`` works on an HxWx3 uint8 array;
``grade_image_bytes(jpeg, preset, max_w)`` is the decode→grade→(resize)
→encode path the server uses for ``/video/frame/...?grade=<preset>``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np

# Rec.709 luma weights for the saturation pivot.
_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)


@dataclass(frozen=True)
class Grade:
    """ASC-CDL-ish look: per-channel slope/offset/power + saturation."""
    label: str
    slope: tuple[float, float, float] = (1.0, 1.0, 1.0)
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    power: tuple[float, float, float] = (1.0, 1.0, 1.0)
    saturation: float = 1.0


# id → Grade.  "none" is the identity (the "undo" state).
PRESETS: dict[str, Grade] = {
    "none": Grade("Original"),
    "arri_709a": Grade(
        "Arri 709A", slope=(1.0, 1.0, 1.0), offset=(0.0, 0.0, 0.0),
        power=(1.04, 1.04, 1.04), saturation=1.03),
    "fuji_eterna": Grade(
        "Fuji Eterna", slope=(0.97, 1.00, 1.04), offset=(0.03, 0.03, 0.035),
        power=(0.96, 0.96, 0.95), saturation=0.80),
    "kodak_vision3": Grade(
        "Kodak Vision3", slope=(1.07, 1.00, 0.93), offset=(0.0, 0.0, 0.015),
        power=(1.06, 1.05, 1.06), saturation=1.08),
    "teal_orange": Grade(
        "Teal / Orange", slope=(1.05, 1.00, 0.96), offset=(-0.01, 0.0, 0.04),
        power=(1.05, 1.03, 1.05), saturation=1.12),
    "bw": Grade(
        "B&W", slope=(1.0, 1.0, 1.0), offset=(0.0, 0.0, 0.0),
        power=(1.05, 1.05, 1.05), saturation=0.0),
}


def list_presets() -> list[dict]:
    """[{id, label}, …] in display order (Original first)."""
    return [{"id": k, "label": g.label} for k, g in PRESETS.items()]


def apply_grade(img: np.ndarray, preset: str) -> np.ndarray:
    """Apply a preset to an HxWx3 uint8 RGB array → HxWx3 uint8.

    Unknown / ``"none"`` presets return the input unchanged.
    """
    g = PRESETS.get(preset)
    if g is None or preset == "none":
        return img
    x = img.astype(np.float64) / 255.0
    slope = np.array(g.slope)
    offset = np.array(g.offset)
    power = np.array(g.power)
    # ASC CDL: out = (in * slope + offset) ^ power, clamped.
    x = np.clip(x * slope + offset, 0.0, 1.0) ** power
    if g.saturation != 1.0:
        luma = x @ _LUMA
        x = np.clip(luma[..., None] + g.saturation * (x - luma[..., None]),
                    0.0, 1.0)
    return (np.clip(x, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def grade_image_bytes(
    jpeg_bytes: bytes,
    preset: str,
    *,
    max_w: int | None = None,
    quality: int = 88,
) -> bytes:
    """Decode JPEG → optional resize → grade → re-encode JPEG.

    Returns the input bytes unchanged when ``preset`` is ``none``/unknown
    *and* no resize is requested (cheap no-op for the server).
    """
    if (preset in (None, "none") or preset not in PRESETS) and not max_w:
        return jpeg_bytes
    from PIL import Image
    with Image.open(io.BytesIO(jpeg_bytes)) as im:
        im = im.convert("RGB")
        if max_w and im.width > max_w:
            h = round(im.height * max_w / im.width)
            im = im.resize((max_w, max(1, h)))
        arr = np.asarray(im)
    arr = apply_grade(arr, preset) if preset in PRESETS else arr
    out = io.BytesIO()
    from PIL import Image as _I
    _I.fromarray(arr).save(out, "JPEG", quality=quality)
    return out.getvalue()
