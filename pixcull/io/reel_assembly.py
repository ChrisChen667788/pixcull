"""v2.0-P1-1 — Reel auto-assembly.

Charter ``docs/ROADMAP-v2.0-charter.md`` § v2.0-P1-1: stitch the chosen
reel candidates (time ranges inside the *source* video) into one
30–90 s cut, with simple cross-fades and a faded audio bed, and emit an
EDL so the editor can re-cut in DaVinci / Premiere.

Two deliverables:

* ``<reel_id>.mp4`` (h.264) — segments concatenated in *time order*
  with ``xfade`` video cross-fades + ``acrossfade`` audio (overall
  ``afade`` in/out).  ``crossfade_s = 0`` falls back to hard cuts.
* ``<reel_id>.edl`` — CMX-3600 cut list referencing the source clip's
  timecodes, so the assembly is a starting point, not a black box.

The EDL builder + the ffmpeg filter-graph builder are pure functions
(unit-tested without ffmpeg); :func:`assemble_reel` shells out to
ffmpeg and is exercised against a tiny real clip.

Selection: by default the top-scoring candidates are taken greedily up
to ``target_s`` of material, then ordered by ``start_s`` (time order).
Explicit ``ranks=[...]`` overrides the auto pick.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from pixcull.io.video import FFmpegError, probe_video

DEFAULT_CROSSFADE_S = 0.5
DEFAULT_TARGET_S = 60.0
DEFAULT_MAX_CLIPS = 16


@dataclass
class Clip:
    start_s: float
    end_s: float
    rank: int = 0
    score: float = 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end_s - self.start_s)


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------

def select_for_assembly(
    candidates: list[dict],
    *,
    ranks: Sequence[int] | None = None,
    target_s: float = DEFAULT_TARGET_S,
    max_clips: int = DEFAULT_MAX_CLIPS,
) -> list[Clip]:
    """Pick clips to assemble, returned in time order.

    ``ranks`` selects explicit candidate ranks; otherwise the
    highest-``score`` candidates are taken until their combined duration
    reaches ``target_s`` (or ``max_clips``).
    """
    by_rank = {int(c.get("rank", i + 1)): c for i, c in enumerate(candidates)}
    if ranks:
        chosen = [by_rank[r] for r in ranks if r in by_rank]
    else:
        ordered = sorted(candidates, key=lambda c: -float(c.get("score", 0)))
        chosen, total = [], 0.0
        for c in ordered:
            d = float(c.get("end_s", 0)) - float(c.get("start_s", 0))
            if d <= 0:
                continue
            chosen.append(c)
            total += d
            if total >= target_s or len(chosen) >= max_clips:
                break
    clips = [
        Clip(start_s=float(c["start_s"]), end_s=float(c["end_s"]),
             rank=int(c.get("rank", 0)), score=float(c.get("score", 0)))
        for c in chosen
    ]
    clips.sort(key=lambda c: c.start_s)
    return clips


# --------------------------------------------------------------------------
# EDL (CMX 3600)
# --------------------------------------------------------------------------

def seconds_to_timecode(s: float, fps: float) -> str:
    """Seconds → ``HH:MM:SS:FF`` (non-drop)."""
    fps = fps if fps and fps > 0 else 25.0
    if s < 0:
        s = 0.0
    total_frames = int(round(s * fps))
    fps_i = int(round(fps))
    frames = total_frames % fps_i
    total_secs = total_frames // fps_i
    ss = total_secs % 60
    mm = (total_secs // 60) % 60
    hh = total_secs // 3600
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{frames:02d}"


def build_edl(
    clips: Sequence[Clip],
    source_name: str,
    fps: float,
    *,
    title: str = "PixCull Reel",
) -> str:
    """CMX-3600 EDL: one cut event per clip, record TC accumulating."""
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    rec = 0.0
    for i, c in enumerate(clips, start=1):
        src_in = seconds_to_timecode(c.start_s, fps)
        src_out = seconds_to_timecode(c.end_s, fps)
        rec_in = seconds_to_timecode(rec, fps)
        rec_out = seconds_to_timecode(rec + c.duration, fps)
        rec += c.duration
        lines.append(
            f"{i:03d}  AX       AA/V  C        "
            f"{src_in} {src_out} {rec_in} {rec_out}")
        lines.append(f"* FROM CLIP NAME: {source_name}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------
# ffmpeg filter graph
# --------------------------------------------------------------------------

def build_montage_filter(
    clips: Sequence[Clip],
    *,
    crossfade_s: float,
    has_audio: bool,
    fade_io_s: float = 0.4,
) -> tuple[str, str, str | None]:
    """Build an ffmpeg ``-filter_complex`` for a single-input montage.

    Returns ``(filter_str, video_out_label, audio_out_label|None)``.
    Uses ``xfade``/``acrossfade`` when ``crossfade_s > 0``, else hard
    ``concat``.  Trims are taken from one input (``0:v`` / ``0:a``).
    """
    n = len(clips)
    if n == 0:
        raise ValueError("no clips to assemble")
    parts: list[str] = []
    # Per-clip trims.
    for i, c in enumerate(clips):
        parts.append(
            f"[0:v]trim=start={c.start_s:.3f}:end={c.end_s:.3f},"
            f"setpts=PTS-STARTPTS[v{i}]")
        if has_audio:
            parts.append(
                f"[0:a]atrim=start={c.start_s:.3f}:end={c.end_s:.3f},"
                f"asetpts=PTS-STARTPTS[a{i}]")

    xf = max(0.0, float(crossfade_s))
    # Cross-fades only make sense when each clip is longer than the fade.
    if xf > 0 and all(c.duration > xf + 0.05 for c in clips) and n > 1:
        # Video xfade chain.
        cur = "v0"
        t = clips[0].duration
        for i in range(1, n):
            off = t - xf
            out = f"vx{i}"
            parts.append(
                f"[{cur}][v{i}]xfade=transition=fade:"
                f"duration={xf:.3f}:offset={off:.3f}[{out}]")
            cur = out
            t = t + clips[i].duration - xf
        vlabel = cur
        alabel = None
        if has_audio:
            acur = "a0"
            for i in range(1, n):
                out = f"ax{i}"
                parts.append(
                    f"[{acur}][a{i}]acrossfade=d={xf:.3f}[{out}]")
                acur = out
            alabel = acur
    else:
        # Hard-cut concat.
        vins = "".join(f"[v{i}]" for i in range(n))
        parts.append(f"{vins}concat=n={n}:v=1:a=0[vcat]")
        vlabel = "vcat"
        alabel = None
        if has_audio:
            ains = "".join(f"[a{i}]" for i in range(n))
            parts.append(f"{ains}concat=n={n}:v=0:a=1[acat]")
            alabel = "acat"

    # Overall fade in/out.
    total = sum(c.duration for c in clips) - (xf * (n - 1) if (
        xf > 0 and all(c.duration > xf + 0.05 for c in clips) and n > 1) else 0)
    fio = min(fade_io_s, max(0.05, total / 4))
    parts.append(
        f"[{vlabel}]fade=t=in:st=0:d={fio:.3f},"
        f"fade=t=out:st={max(0.0, total - fio):.3f}:d={fio:.3f}[vout]")
    vout = "vout"
    aout = None
    if has_audio and alabel:
        parts.append(
            f"[{alabel}]afade=t=in:st=0:d={fio:.3f},"
            f"afade=t=out:st={max(0.0, total - fio):.3f}:d={fio:.3f}[aout]")
        aout = "aout"
    return ";".join(parts), vout, aout


# --------------------------------------------------------------------------
# Assemble
# --------------------------------------------------------------------------

@dataclass
class ReelResult:
    reel_id: str
    mp4_path: Path | None
    edl_path: Path
    clips: list[Clip]
    duration_s: float


def assemble_reel(
    source_video: Path,
    clips: Sequence[Clip],
    output_dir: Path,
    *,
    reel_id: str = "reel",
    crossfade_s: float = DEFAULT_CROSSFADE_S,
    edl_only: bool = False,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
) -> ReelResult:
    """Assemble ``clips`` from ``source_video`` into ``<reel_id>.mp4`` +
    ``<reel_id>.edl`` under ``output_dir/<reel_id>/``."""
    source_video = Path(source_video)
    if not clips:
        raise ValueError("no clips selected for the reel")
    meta = probe_video(source_video, ffprobe=ffprobe)
    out_dir = Path(output_dir) / reel_id
    out_dir.mkdir(parents=True, exist_ok=True)

    edl_path = out_dir / f"{reel_id}.edl"
    edl_path.write_text(
        build_edl(clips, meta.source_name, meta.fps or 25.0), encoding="utf-8")

    total = sum(c.duration for c in clips)
    if edl_only:
        return ReelResult(reel_id, None, edl_path, list(clips), round(total, 3))

    ffmpeg_bin = shutil.which(ffmpeg or "ffmpeg") or ffmpeg
    if not ffmpeg_bin:
        raise FFmpegError("ffmpeg not found on PATH")
    has_audio = (meta.audio_track_count or 0) > 0
    filt, vlabel, alabel = build_montage_filter(
        clips, crossfade_s=crossfade_s, has_audio=has_audio)
    mp4_path = out_dir / f"{reel_id}.mp4"
    cmd = [
        ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source_video),
        "-filter_complex", filt,
        "-map", f"[{vlabel}]",
    ]
    if alabel:
        cmd += ["-map", f"[{alabel}]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            str(mp4_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
        raise FFmpegError(f"ffmpeg assembly failed: {exc}")
    if proc.returncode != 0:
        raise FFmpegError(
            f"ffmpeg returned {proc.returncode}: {proc.stderr.strip()[:400]}")

    # Real duration from the output.
    try:
        out_dur = probe_video(mp4_path, ffprobe=ffprobe).duration_s or total
    except FFmpegError:
        out_dur = total
    return ReelResult(reel_id, mp4_path, edl_path, list(clips),
                      round(out_dur, 3))


def assemble_from_run(
    run_dir: Path,
    *,
    ranks: Sequence[int] | None = None,
    target_s: float = DEFAULT_TARGET_S,
    crossfade_s: float = DEFAULT_CROSSFADE_S,
    reel_id: str = "reel",
    edl_only: bool = False,
) -> ReelResult:
    """Read ``reel_candidates.json`` + the source video from a run's
    ``manifest.json`` and assemble the reel."""
    from pixcull.scoring.temporal import _resolve_frames_dir
    run_dir = Path(run_dir)
    reel_path = run_dir / "reel_candidates.json"
    if not reel_path.exists():
        raise FileNotFoundError(
            f"{reel_path} not found — run the P0-3 reel detector first.")
    candidates = json.loads(reel_path.read_text("utf-8"))
    frames_dir = _resolve_frames_dir(run_dir, None)
    manifest = json.loads((frames_dir / "manifest.json").read_text("utf-8"))
    source = manifest.get("source_path")
    if not source or not Path(source).exists():
        raise FileNotFoundError(
            f"source video not found (manifest source_path={source!r}); "
            f"the original clip must be present to assemble.")
    clips = select_for_assembly(
        candidates, ranks=ranks, target_s=target_s)
    if not clips:
        raise ValueError("no reel candidates to assemble")
    return assemble_reel(
        Path(source), clips, run_dir,
        reel_id=reel_id, crossfade_s=crossfade_s, edl_only=edl_only)
