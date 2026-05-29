"""v2.0-P1-5 — GoPro / DJI metadata (GPMF KLV + HiLight tags).

Charter ``docs/ROADMAP-v2.0-charter.md`` § v2.0-P1-5: read the action-cam
telemetry stream so frames near a shooter-pressed **HiLight** mark get a
score boost, and surface GPS for the location story.

Two sources, both pure-Python (no SDK):

* **HiLight tags** — GoPro writes the moments the user tagged in-camera
  to the MP4 ``udta`` atom as an ``HMMT`` box (count + millisecond
  offsets).  :func:`parse_hmmt_atom` walks the atom tree and returns
  those marks in seconds — cross-camera-reliable and cheap.
* **GPMF telemetry** — the ``gpmd`` data stream (GPS5 / ACCL / GYRO /
  device markers) is KLV-encoded.  :func:`parse_gpmf` decodes the
  Key-Length-Value tree; :func:`extract_gps` pulls scaled lat/lon/alt.

:func:`highlight_boost` turns HiLight seconds into a per-frame ``[0,1]``
boost (triangular falloff over ``window_s``) that the reel / moment
scorers can add.

Deviations: full IMU (ACCL/GYRO) is *parsed* but not yet scored; DJI
stores GPS in an SRT subtitle track rather than GPMF, so DJI GPS parsing
is deferred (HiLight via HMMT still works where present).
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

# GPMF type char → (struct code, byte size).  0x00 == nested container.
_GPMF_TYPES: dict[str, tuple[str, int]] = {
    "b": ("b", 1), "B": ("B", 1),
    "s": (">h", 2), "S": (">H", 2),
    "l": (">i", 4), "L": (">I", 4),
    "f": (">f", 4), "d": (">d", 8),
    "j": (">q", 8), "J": (">Q", 8),
}


@dataclass
class GpmfElement:
    fourcc: str
    type_char: str
    values: list          # scalars (typed) — flat
    children: list        # nested GpmfElement list (type 0x00)


def parse_gpmf(data: bytes) -> list[GpmfElement]:
    """Decode a GPMF KLV byte string into a tree of :class:`GpmfElement`.

    Each element is ``FourCC(4) · type(1) · sample_size(1) · repeat(2 BE)``
    followed by ``sample_size × repeat`` bytes padded to a 4-byte
    boundary.  ``type == 0x00`` marks a nested container (recursed).
    """
    out: list[GpmfElement] = []
    i, n = 0, len(data)
    while i + 8 <= n:
        fourcc = data[i:i + 4].decode("latin-1")
        type_byte = data[i + 4]
        sample_size = data[i + 5]
        repeat = struct.unpack(">H", data[i + 6:i + 8])[0]
        payload_len = sample_size * repeat
        body_start = i + 8
        body_end = body_start + payload_len
        if body_end > n:
            break
        body = data[body_start:body_end]
        type_char = chr(type_byte) if type_byte != 0 else "\x00"
        children: list[GpmfElement] = []
        values: list = []
        if type_byte == 0:
            children = parse_gpmf(body)
        elif type_char in _GPMF_TYPES:
            code, size = _GPMF_TYPES[type_char]
            if size and len(body) >= size:
                count = len(body) // size
                try:
                    values = [struct.unpack(code, body[k * size:(k + 1) * size])[0]
                              for k in range(count)]
                except struct.error:
                    values = []
        elif type_char in ("c", "U", "F"):
            values = [body.rstrip(b"\x00").decode("latin-1", "replace")]
        out.append(GpmfElement(fourcc, type_char, values, children))
        # Advance past payload, padded to 4-byte alignment.
        pad = (-payload_len) % 4
        i = body_end + pad
    return out


def _walk(elements: Sequence[GpmfElement], fourcc: str) -> list[GpmfElement]:
    """Depth-first collect every element with ``fourcc``."""
    found: list[GpmfElement] = []
    for el in elements:
        if el.fourcc == fourcc:
            found.append(el)
        if el.children:
            found.extend(_walk(el.children, fourcc))
    return found


def extract_gps(elements: Sequence[GpmfElement]) -> list[dict]:
    """Pull GPS5 samples (lat, lon, alt, 2D, 3D speed), scaled by SCAL.

    Returns a list of ``{lat, lon, alt_m, speed_2d, speed_3d}`` dicts.
    Empty when the stream has no GPS5.
    """
    out: list[dict] = []
    # GPS5 lives in a STRM container next to its SCAL divisors.
    def _scan(els: Sequence[GpmfElement]):
        scal: list[float] = []
        for el in els:
            if el.fourcc == "SCAL" and el.values:
                scal = [float(v) if v else 1.0 for v in el.values]
            elif el.fourcc == "GPS5" and el.values:
                vals = el.values
                for k in range(0, len(vals) - 4, 5):
                    group = vals[k:k + 5]
                    div = (scal + [1.0] * 5)[:5] if scal else [1.0] * 5
                    # SCAL may carry one divisor per field or a single one.
                    if len(scal) == 1:
                        div = [scal[0]] * 5
                    out.append({
                        "lat": group[0] / div[0],
                        "lon": group[1] / div[1],
                        "alt_m": group[2] / div[2],
                        "speed_2d": group[3] / div[3],
                        "speed_3d": group[4] / div[4],
                    })
            if el.children:
                _scan(el.children)
    _scan(elements)
    return out


# --------------------------------------------------------------------------
# MP4 atom tree → HMMT HiLight tags
# --------------------------------------------------------------------------

def _iter_atoms(data: bytes, start: int, end: int):
    """Yield ``(atom_type, body_start, body_end)`` for atoms in [start,end)."""
    i = start
    while i + 8 <= end:
        size = struct.unpack(">I", data[i:i + 4])[0]
        atype = data[i + 4:i + 8].decode("latin-1", "replace")
        if size == 1:  # 64-bit extended size
            if i + 16 > end:
                break
            size = struct.unpack(">Q", data[i + 8:i + 16])[0]
            body_start = i + 16
        elif size == 0:  # extends to end
            size = end - i
            body_start = i + 8
        else:
            body_start = i + 8
        body_end = min(i + size, end)
        if size < 8:
            break
        yield atype, body_start, body_end
        i += size


def _find_atom(data: bytes, path: Sequence[str], start=0, end=None):
    """Follow a nested atom ``path`` (e.g. ['moov','udta','HMMT'])."""
    end = len(data) if end is None else end
    if not path:
        return start, end
    target = path[0]
    for atype, bs, be in _iter_atoms(data, start, end):
        if atype == target:
            return _find_atom(data, path[1:], bs, be)
    return None


def parse_hmmt_atom(data: bytes) -> list[float]:
    """Return GoPro HiLight tag times (seconds) from an MP4's bytes.

    Looks for ``HMMT`` under ``moov/udta`` (and top-level/``udta``).  The
    HMMT payload is a big-endian uint32 count followed by that many
    millisecond offsets (a trailing 0 terminator is common).
    """
    for path in (["moov", "udta", "HMMT"], ["udta", "HMMT"], ["HMMT"]):
        loc = _find_atom(data, path)
        if loc is None:
            continue
        bs, be = loc
        body = data[bs:be]
        if len(body) < 8:
            continue
        count = struct.unpack(">I", body[0:4])[0]
        marks: list[float] = []
        off = 4
        for _ in range(count):
            if off + 4 > len(body):
                break
            ms = struct.unpack(">I", body[off:off + 4])[0]
            off += 4
            if ms > 0:
                marks.append(ms / 1000.0)
        if marks:
            return sorted(marks)
    return []


# --------------------------------------------------------------------------
# HiLight → per-frame boost
# --------------------------------------------------------------------------

def highlight_boost(
    timestamps: Sequence[float],
    highlights_s: Sequence[float],
    *,
    window_s: float = 1.5,
) -> np.ndarray:
    """Per-frame boost in ``[0,1]`` — triangular falloff around each mark.

    A frame exactly on a HiLight mark scores 1.0, decaying linearly to 0
    at ``window_s`` away; overlapping marks take the max.
    """
    ts = np.asarray(timestamps, dtype=np.float64)
    out = np.zeros(ts.shape[0], dtype=np.float64)
    if not len(highlights_s) or not ts.size or window_s <= 0:
        return out
    for h in highlights_s:
        d = np.abs(ts - float(h))
        out = np.maximum(out, np.clip(1.0 - d / window_s, 0.0, 1.0))
    return out


# --------------------------------------------------------------------------
# Video → metadata
# --------------------------------------------------------------------------

@dataclass
class GpmfMeta:
    has_gpmf: bool
    highlights_s: list[float]
    gps: list[dict]

    def to_dict(self) -> dict:
        return {
            "has_gpmf": self.has_gpmf,
            "highlights_s": self.highlights_s,
            "highlight_count": len(self.highlights_s),
            "gps_sample_count": len(self.gps),
            "gps": self.gps[:1000],
        }


def _extract_gpmd_stream(path: Path, ffmpeg: str | None) -> bytes:
    """Copy the ``gpmd`` data stream out of an MP4 via ffmpeg (or b'')."""
    ff = shutil.which(ffmpeg or "ffmpeg") or ffmpeg
    if not ff:
        return b""
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(path), "-map", "0:d", "-codec", "copy",
           "-f", "data", "pipe:1"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return b""
    return proc.stdout if proc.returncode == 0 else b""


def parse_video_metadata(
    path: Path,
    *,
    ffmpeg: str | None = None,
) -> GpmfMeta:
    """Read HiLight tags (HMMT) + GPMF GPS from a video file.

    Degrades gracefully: a non-GoPro clip with no GPMF / HMMT returns
    ``has_gpmf=False`` with empty marks rather than raising.
    """
    path = Path(path)
    raw = b""
    try:
        raw = path.read_bytes() if path.stat().st_size < 256 * 1024 * 1024 \
            else path.open("rb").read(64 * 1024 * 1024)
    except OSError:
        raw = b""
    highlights = parse_hmmt_atom(raw) if raw else []

    gpmd = _extract_gpmd_stream(path, ffmpeg)
    elements = parse_gpmf(gpmd) if gpmd else []
    gps = extract_gps(elements) if elements else []
    # GPMF may also carry device markers; HMMT remains the primary source.
    has_gpmf = bool(elements) or bool(highlights)
    return GpmfMeta(has_gpmf=has_gpmf, highlights_s=highlights, gps=gps)


def run_gpmf_analysis(
    output_dir: Path,
    *,
    write: bool = True,
) -> GpmfMeta:
    """Read the run's source video (from manifest), parse GoPro/DJI
    metadata, write ``gpmf.json``."""
    from pixcull.scoring.temporal import _resolve_frames_dir
    output_dir = Path(output_dir)
    frames_dir = _resolve_frames_dir(output_dir, None)
    manifest = json.loads((frames_dir / "manifest.json").read_text("utf-8"))
    source = manifest.get("source_path")
    if not source or not Path(source).exists():
        meta = GpmfMeta(False, [], [])
    else:
        meta = parse_video_metadata(Path(source))
    if write:
        (output_dir / "gpmf.json").write_text(
            json.dumps(meta.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8")
    return meta
