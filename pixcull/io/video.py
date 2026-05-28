"""v2.0-P0-1 — Video import + keyframe extraction.

The first half of the "PixCull for video" charter
(``docs/ROADMAP-v2.0-charter.md`` § v2.0-P0-1).  This module turns a
single video file into a folder of still frames that the *existing*
photo pipeline can score unchanged — i.e. each video becomes one
PixCull "run", treated as a dense burst group.

Pipeline
========

1. :func:`probe_video` shells out to ``ffprobe`` (JSON output) to read
   fps / duration / codec / resolution / audio-track count.
2. :func:`extract_keyframes` shells out to ``ffmpeg`` to write
   ``<output_dir>/video_frames/<video_id>/frame_000001.jpg`` … in one
   of two modes:

   * ``interval`` (default): one frame every ``interval_s`` seconds
     (``-vf fps=1/interval_s``).  Timestamps are exact by construction.
   * ``keyframe``: one frame per GOP / I-frame (``-skip_frame nokey``).
     Timestamps come from a prior ``ffprobe`` keyframe scan.

3. A ``manifest.json`` is written alongside the frames recording
   ``{video_id, fps, duration_s, frame_count, codec, audio_track_count,
   …, frames: [{frame_id, timestamp_s, filename}, …]}``.

The extracted ``video_frames/<video_id>/`` folder is a plain directory
of JPEGs, so :func:`pixcull.pipeline.orchestrator.run_pipeline` scores
it with zero changes.  Burst clustering naturally groups temporally
adjacent near-identical frames.

ffmpeg / ffprobe are resolved via :data:`shutil.which`; pass explicit
binary paths to the functions to override (handy for tests / sandboxes).

``.braw`` (Blackmagic RAW) and Canon ``.crm`` RAW-Light are *accepted*
as extensions per the charter, but ffmpeg cannot decode them without
vendor SDKs; probing such a file raises :class:`FFmpegError` with a
clear message.  Real RAW-video support is deferred to v2.1.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Charter §P0-1 accepts .mp4 / .mov / .mkv / .braw; we add the other
# common delivery containers a wedding / event shooter actually hands
# over (m4v from iPhones, AVCHD .mts/.m2ts from older camcorders, avi).
VIDEO_EXTS: set[str] = {
    ".mp4", ".mov", ".mkv", ".braw", ".m4v",
    ".avi", ".mts", ".m2ts", ".webm",
}

# Containers ffmpeg cannot decode without a vendor SDK.  Accepted at the
# CLI boundary so the error message is specific rather than "unknown
# extension", but probing raises FFmpegError.
_VENDOR_RAW_EXTS: set[str] = {".braw", ".crm"}

# How many frames we refuse to silently extract.  A 2-hour 4K clip at
# 1 fps is 7 200 frames; without a cap a fat-fingered ``--interval 0.04``
# would try to dump every frame.  When the estimate exceeds the cap we
# widen the interval to fit rather than truncating the tail.
DEFAULT_MAX_FRAMES = 3000

EXTRACT_MODES = ("interval", "keyframe")


class FFmpegError(RuntimeError):
    """Raised when ffmpeg / ffprobe is missing or returns non-zero."""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def is_video(path_or_ext: str | Path) -> bool:
    """True when the path / extension is a recognised video container."""
    s = str(path_or_ext)
    ext = s if s.startswith(".") else Path(s).suffix
    return ext.lower() in VIDEO_EXTS


def _resolve_bin(name: str, override: str | None) -> str:
    """Return an absolute path to ``name`` (ffmpeg/ffprobe) or raise."""
    if override:
        return override
    found = shutil.which(name)
    if not found:
        raise FFmpegError(
            f"{name} not found on PATH. Install ffmpeg "
            f"(`brew install ffmpeg` / `apt install ffmpeg`) and retry."
        )
    return found


def _parse_fraction(value: str | None) -> float | None:
    """Parse an ffprobe rate string like ``'30000/1001'`` → 29.97."""
    if not value:
        return None
    value = value.strip()
    if value in ("0", "0/0", "N/A", ""):
        return None
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else None
        return float(value)
    except (ValueError, ZeroDivisionError):
        return None


def make_video_id(path: Path) -> str:
    """Stable, filesystem-safe, human-readable id for a video file.

    ``<sanitised-stem>_<8-hex>`` where the hex is a sha1 of the resolved
    path + size + mtime, so re-importing the same file is idempotent but
    two different files with the same name never collide.
    """
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", path.stem)[:40].strip("_")
    stem = stem or "video"
    try:
        st = path.stat()
        sig = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        sig = str(path)
    digest = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:8]
    return f"{stem}_{digest}"


# --------------------------------------------------------------------------
# Probe
# --------------------------------------------------------------------------

@dataclass
class VideoMeta:
    """Container-level metadata read from ffprobe."""

    video_id: str
    source_name: str
    source_path: str
    codec: str | None
    fps: float | None
    duration_s: float | None
    width: int | None
    height: int | None
    audio_track_count: int
    container: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def probe_video(
    path: Path,
    *,
    ffprobe: str | None = None,
) -> VideoMeta:
    """Read container metadata via ``ffprobe -print_format json``.

    Raises :class:`FFmpegError` for vendor-RAW containers ffmpeg can't
    decode, for a missing ffprobe binary, or for an unreadable file.
    """
    path = Path(path)
    if path.suffix.lower() in _VENDOR_RAW_EXTS:
        raise FFmpegError(
            f"{path.suffix} is a vendor RAW-video format that ffmpeg "
            f"cannot decode without a proprietary SDK. PixCull video "
            f"support for RAW codecs is deferred to v2.1 — for now, "
            f"transcode to ProRes/H.264 in your NLE first."
        )
    if not path.exists():
        raise FFmpegError(f"video not found: {path}")

    probe_bin = _resolve_bin("ffprobe", ffprobe)
    cmd = [
        probe_bin, "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
        raise FFmpegError(f"ffprobe failed to run on {path.name}: {exc}")
    if proc.returncode != 0:
        raise FFmpegError(
            f"ffprobe returned {proc.returncode} on {path.name}: "
            f"{proc.stderr.strip()[:300]}"
        )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:  # pragma: no cover
        raise FFmpegError(f"ffprobe gave non-JSON output: {exc}")

    streams = data.get("streams", []) or []
    fmt = data.get("format", {}) or {}
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not video_streams:
        raise FFmpegError(
            f"{path.name} has no decodable video stream "
            f"(streams found: {len(streams)})."
        )
    v = video_streams[0]

    # fps: prefer avg_frame_rate, fall back to r_frame_rate.
    fps = _parse_fraction(v.get("avg_frame_rate")) \
        or _parse_fraction(v.get("r_frame_rate"))

    # duration: stream-level first, then container format-level.
    duration = None
    for src in (v.get("duration"), fmt.get("duration")):
        try:
            if src is not None:
                duration = float(src)
                break
        except (TypeError, ValueError):
            continue

    return VideoMeta(
        video_id=make_video_id(path),
        source_name=path.name,
        source_path=str(path.resolve()),
        codec=v.get("codec_name"),
        fps=round(fps, 4) if fps else None,
        duration_s=round(duration, 3) if duration else None,
        width=v.get("width"),
        height=v.get("height"),
        audio_track_count=len(audio_streams),
        container=(fmt.get("format_name") or "").split(",")[0] or None,
    )


# --------------------------------------------------------------------------
# Extract
# --------------------------------------------------------------------------

@dataclass
class FrameRef:
    frame_id: str
    timestamp_s: float
    filename: str


@dataclass
class ExtractionResult:
    meta: VideoMeta
    frames_dir: Path
    frames: list[FrameRef] = field(default_factory=list)
    mode: str = "interval"
    interval_s: float | None = None

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def to_manifest(self) -> dict:
        """The JSON object persisted as ``manifest.json``."""
        m = self.meta.to_dict()
        m.update({
            "frame_count": self.frame_count,
            "extraction_mode": self.mode,
            "interval_s": self.interval_s,
            "frames": [asdict(f) for f in self.frames],
            "schema_version": 1,
        })
        return m


def _keyframe_timestamps(
    path: Path, probe_bin: str,
) -> list[float]:
    """Return I-frame presentation timestamps (seconds), sorted."""
    cmd = [
        probe_bin, "-v", "error",
        "-select_streams", "v:0",
        "-skip_frame", "nokey",
        "-show_entries", "frame=best_effort_timestamp_time",
        "-of", "json",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
        )
        data = json.loads(proc.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []
    out: list[float] = []
    for fr in data.get("frames", []) or []:
        t = fr.get("best_effort_timestamp_time")
        try:
            if t is not None:
                out.append(float(t))
        except (TypeError, ValueError):
            continue
    return sorted(out)


def extract_keyframes(
    path: Path,
    output_dir: Path,
    *,
    mode: str = "interval",
    interval_s: float = 1.0,
    max_frames: int = DEFAULT_MAX_FRAMES,
    jpeg_quality: int = 2,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
    meta: VideoMeta | None = None,
) -> ExtractionResult:
    """Extract still frames from ``path`` into ``output_dir/video_frames``.

    Args:
        path: source video file.
        output_dir: run root; frames land in
            ``<output_dir>/video_frames/<video_id>/``.
        mode: ``"interval"`` (one frame every ``interval_s`` s) or
            ``"keyframe"`` (one frame per GOP / I-frame).
        interval_s: seconds between frames in interval mode. Auto-widened
            when the frame estimate would exceed ``max_frames``.
        max_frames: safety cap on number of extracted frames.
        jpeg_quality: ffmpeg ``-q:v`` (2 = high, 31 = low).
        ffmpeg / ffprobe: binary path overrides.
        meta: a pre-computed :class:`VideoMeta` (skips a redundant probe).

    Returns:
        :class:`ExtractionResult` (call :meth:`write_manifest` to persist).
    """
    path = Path(path)
    if mode not in EXTRACT_MODES:
        raise ValueError(
            f"mode must be one of {EXTRACT_MODES}, got {mode!r}"
        )
    if interval_s <= 0:
        raise ValueError(f"interval_s must be > 0, got {interval_s}")

    ffmpeg_bin = _resolve_bin("ffmpeg", ffmpeg)
    if meta is None:
        meta = probe_video(path, ffprobe=ffprobe)

    frames_dir = Path(output_dir) / "video_frames" / meta.video_id
    frames_dir.mkdir(parents=True, exist_ok=True)
    # Clean any stale frames from a previous extraction of this id.
    for stale in frames_dir.glob("frame_*.jpg"):
        stale.unlink()

    effective_interval = interval_s
    if mode == "interval" and meta.duration_s and max_frames > 0:
        est = meta.duration_s / interval_s
        if est > max_frames:
            effective_interval = meta.duration_s / max_frames

    out_pattern = str(frames_dir / "frame_%06d.jpg")
    if mode == "interval":
        rate = 1.0 / effective_interval
        vf = f"fps={rate:.6f}"
        cmd = [
            ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(path),
            "-vf", vf,
            "-q:v", str(jpeg_quality),
            "-f", "image2", out_pattern,
        ]
    else:  # keyframe
        cmd = [
            ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
            "-skip_frame", "nokey",
            "-i", str(path),
            "-vsync", "vfr",
            "-q:v", str(jpeg_quality),
            "-frames:v", str(max_frames),
            "-f", "image2", out_pattern,
        ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
        raise FFmpegError(f"ffmpeg extraction failed on {path.name}: {exc}")
    if proc.returncode != 0:
        raise FFmpegError(
            f"ffmpeg returned {proc.returncode} on {path.name}: "
            f"{proc.stderr.strip()[:300]}"
        )

    extracted = sorted(frames_dir.glob("frame_*.jpg"))
    # Hard-enforce the cap even if ffmpeg over-produced (interval mode
    # has no -frames:v guard so a rounding quirk can yield max_frames+1).
    if max_frames > 0 and len(extracted) > max_frames:
        for extra in extracted[max_frames:]:
            extra.unlink()
        extracted = extracted[:max_frames]

    # Per-frame timestamps.
    if mode == "interval":
        timestamps = [i * effective_interval for i in range(len(extracted))]
    else:
        kf = _keyframe_timestamps(path, _resolve_bin("ffprobe", ffprobe))
        if len(kf) == len(extracted):
            timestamps = kf
        elif meta.duration_s and len(extracted) > 1:
            # Counts disagreed (rare codec edge); space evenly as a
            # best-effort fallback so the scrubber still works.
            step = meta.duration_s / (len(extracted) - 1)
            timestamps = [i * step for i in range(len(extracted))]
        else:
            timestamps = [0.0 for _ in extracted]

    frames = [
        FrameRef(
            frame_id=p.stem,                      # "frame_000001"
            timestamp_s=round(ts, 3),
            filename=p.name,
        )
        for p, ts in zip(extracted, timestamps)
    ]

    return ExtractionResult(
        meta=meta,
        frames_dir=frames_dir,
        frames=frames,
        mode=mode,
        interval_s=round(effective_interval, 4) if mode == "interval" else None,
    )


def write_manifest(result: ExtractionResult) -> Path:
    """Write ``manifest.json`` into the frames directory; return its path."""
    manifest_path = result.frames_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(result.to_manifest(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest_path


def import_video(
    path: Path,
    output_dir: Path,
    *,
    mode: str = "interval",
    interval_s: float = 1.0,
    max_frames: int = DEFAULT_MAX_FRAMES,
    jpeg_quality: int = 2,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
) -> ExtractionResult:
    """Probe → extract → write manifest in one call.

    Convenience wrapper used by the ``pixcull video`` CLI command.
    Returns the :class:`ExtractionResult`; ``manifest.json`` is already
    on disk when this returns.
    """
    meta = probe_video(path, ffprobe=ffprobe)
    result = extract_keyframes(
        path, output_dir,
        mode=mode, interval_s=interval_s, max_frames=max_frames,
        jpeg_quality=jpeg_quality, ffmpeg=ffmpeg, ffprobe=ffprobe,
        meta=meta,
    )
    write_manifest(result)
    return result
