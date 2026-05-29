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
from pathlib import Path

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


# --------------------------------------------------------------------------
# v2.1-P1-1 — real .cube 3D LUT support (Resolve / Premiere)
# --------------------------------------------------------------------------

# Where user-supplied .cube LUTs are discovered (drop files here).
LUTS_DIR = Path(__file__).resolve().parent.parent.parent / "luts"


@dataclass(frozen=True)
class Cube:
    """A parsed 3D LUT: ``table`` is ``[N,N,N,3]`` indexed ``[r,g,b]``."""
    size: int
    table: np.ndarray
    domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0)
    domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0)
    title: str = ""


def load_cube(path) -> Cube:
    """Parse an Adobe/Resolve ``.cube`` 3D LUT into a :class:`Cube`.

    Entries are ordered with **red fastest** (the .cube spec); we reshape
    to ``[b,g,r,3]`` then transpose to ``[r,g,b,3]`` for direct indexing.
    """
    size = None
    dmin = [0.0, 0.0, 0.0]
    dmax = [1.0, 1.0, 1.0]
    title = ""
    vals: list[list[float]] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            up = s.upper()
            if up.startswith("TITLE"):
                title = s.split(None, 1)[1].strip().strip('"') if " " in s else ""
            elif up.startswith("LUT_3D_SIZE"):
                size = int(s.split()[1])
            elif up.startswith("LUT_1D_SIZE"):
                raise ValueError("1D LUTs are not supported (need LUT_3D_SIZE)")
            elif up.startswith("DOMAIN_MIN"):
                dmin = [float(x) for x in s.split()[1:4]]
            elif up.startswith("DOMAIN_MAX"):
                dmax = [float(x) for x in s.split()[1:4]]
            else:
                parts = s.split()
                if len(parts) >= 3:
                    try:
                        vals.append([float(parts[0]), float(parts[1]),
                                     float(parts[2])])
                    except ValueError:
                        continue
    if size is None:
        raise ValueError("missing LUT_3D_SIZE")
    arr = np.asarray(vals, dtype=np.float64)
    if arr.shape[0] != size ** 3:
        raise ValueError(
            f"expected {size**3} entries for size {size}, got {arr.shape[0]}")
    table = arr.reshape(size, size, size, 3).transpose(2, 1, 0, 3)  # → [r,g,b]
    return Cube(size, np.ascontiguousarray(table),
                tuple(dmin), tuple(dmax), title)


def apply_cube(img: np.ndarray, cube: Cube) -> np.ndarray:
    """Apply a 3D LUT to an HxWx3 uint8 image via trilinear interpolation."""
    h, w = img.shape[:2]
    x = np.clip(img.astype(np.float64) / 255.0, 0.0, 1.0).reshape(-1, 3)
    n = cube.size
    t = cube.table
    dmin = np.asarray(cube.domain_min)
    dmax = np.asarray(cube.domain_max)
    pos = np.clip((x - dmin) / np.maximum(dmax - dmin, 1e-9) * (n - 1),
                  0.0, n - 1)
    i0 = np.floor(pos).astype(np.intp)
    i1 = np.minimum(i0 + 1, n - 1)
    f = pos - i0
    r0, g0, b0 = i0[:, 0], i0[:, 1], i0[:, 2]
    r1, g1, b1 = i1[:, 0], i1[:, 1], i1[:, 2]
    fr, fg, fb = f[:, 0:1], f[:, 1:2], f[:, 2:3]
    out = (
        t[r0, g0, b0] * ((1 - fr) * (1 - fg) * (1 - fb))
        + t[r1, g0, b0] * (fr * (1 - fg) * (1 - fb))
        + t[r0, g1, b0] * ((1 - fr) * fg * (1 - fb))
        + t[r0, g0, b1] * ((1 - fr) * (1 - fg) * fb)
        + t[r1, g1, b0] * (fr * fg * (1 - fb))
        + t[r1, g0, b1] * (fr * (1 - fg) * fb)
        + t[r0, g1, b1] * ((1 - fr) * fg * fb)
        + t[r1, g1, b1] * (fr * fg * fb)
    )
    return (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8).reshape(h, w, 3)


_CUBE_CACHE: dict[str, Cube] = {}


def list_cubes(luts_dir: Path | None = None) -> list[dict]:
    """Discover ``*.cube`` files → ``[{id:'cube:<stem>', label}]``."""
    d = Path(luts_dir) if luts_dir else LUTS_DIR
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.cube")):
        out.append({"id": f"cube:{p.stem}", "label": f"LUT · {p.stem}"})
    return out


def _resolve_cube(preset: str, luts_dir: Path | None = None) -> Cube | None:
    """Map a ``cube:<stem>`` preset id to a loaded (cached) Cube."""
    if not preset.startswith("cube:"):
        return None
    stem = preset[len("cube:"):]
    d = Path(luts_dir) if luts_dir else LUTS_DIR
    path = d / f"{stem}.cube"
    if not path.exists():
        return None
    key = str(path)
    if key not in _CUBE_CACHE:
        try:
            _CUBE_CACHE[key] = load_cube(path)
        except (OSError, ValueError):
            return None
    return _CUBE_CACHE[key]


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
    cube = _resolve_cube(preset) if (preset or "").startswith("cube:") else None
    parametric = preset in PRESETS and preset != "none"
    if not parametric and cube is None and not max_w:
        return jpeg_bytes
    from PIL import Image
    with Image.open(io.BytesIO(jpeg_bytes)) as im:
        im = im.convert("RGB")
        if max_w and im.width > max_w:
            h = round(im.height * max_w / im.width)
            im = im.resize((max_w, max(1, h)))
        arr = np.asarray(im)
    if cube is not None:
        arr = apply_cube(arr, cube)
    elif parametric:
        arr = apply_grade(arr, preset)
    out = io.BytesIO()
    from PIL import Image as _I
    _I.fromarray(arr).save(out, "JPEG", quality=quality)
    return out.getvalue()
