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


# --------------------------------------------------------------------------
# v2.1-P1-2 — in/out trim + multi-video (shoot-level) reels
# --------------------------------------------------------------------------

def trim_clip(clip: Clip, in_s: float | None, out_s: float | None) -> Clip:
    """Clamp a clip to user in/out marks (intersection with [start,end])."""
    start = clip.start_s if in_s is None else max(clip.start_s, float(in_s))
    end = clip.end_s if out_s is None else min(clip.end_s, float(out_s))
    if end <= start:                       # marks collapsed the clip
        end = start + 0.1
    return Clip(start_s=round(start, 3), end_s=round(end, 3),
                rank=clip.rank, score=clip.score)


@dataclass
class SourceClips:
    source_video: Path
    clips: list[Clip]
    label: str = ""


def build_multi_edl(sources: Sequence[SourceClips], fps: float,
                    *, title: str = "PixCull Shoot Reel") -> str:
    """CMX-3600 EDL across multiple source clips (per-event FROM CLIP)."""
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    rec = 0.0
    ev = 1
    for sc in sources:
        name = sc.label or Path(sc.source_video).name
        for c in sc.clips:
            lines.append(
                f"{ev:03d}  AX       AA/V  C        "
                f"{seconds_to_timecode(c.start_s, fps)} "
                f"{seconds_to_timecode(c.end_s, fps)} "
                f"{seconds_to_timecode(rec, fps)} "
                f"{seconds_to_timecode(rec + c.duration, fps)}")
            lines.append(f"* FROM CLIP NAME: {name}")
            lines.append("")
            rec += c.duration
            ev += 1
    return "\n".join(lines).rstrip() + "\n"


def build_multi_montage_filter(
    flat: Sequence[tuple[int, Clip]],
    *,
    crossfade_s: float,
    has_audio: bool,
    fade_io_s: float = 0.4,
) -> tuple[str, str, str | None]:
    """ffmpeg filter graph for clips drawn from multiple inputs.

    ``flat`` is the final ordered list of ``(input_index, Clip)``."""
    n = len(flat)
    if n == 0:
        raise ValueError("no clips to assemble")
    parts: list[str] = []
    for k, (inp, c) in enumerate(flat):
        parts.append(f"[{inp}:v]trim=start={c.start_s:.3f}:end={c.end_s:.3f},"
                     f"setpts=PTS-STARTPTS[v{k}]")
        if has_audio:
            parts.append(f"[{inp}:a]atrim=start={c.start_s:.3f}:end={c.end_s:.3f},"
                         f"asetpts=PTS-STARTPTS[a{k}]")
    durs = [c.duration for _, c in flat]
    xf = max(0.0, float(crossfade_s))
    use_xf = xf > 0 and n > 1 and all(d > xf + 0.05 for d in durs)
    if use_xf:
        cur, t = "v0", durs[0]
        for k in range(1, n):
            parts.append(f"[{cur}][v{k}]xfade=transition=fade:duration={xf:.3f}:"
                         f"offset={t - xf:.3f}[vx{k}]")
            cur = f"vx{k}"
            t += durs[k] - xf
        vlabel, alabel = cur, None
        if has_audio:
            acur = "a0"
            for k in range(1, n):
                parts.append(f"[{acur}][a{k}]acrossfade=d={xf:.3f}[ax{k}]")
                acur = f"ax{k}"
            alabel = acur
        total = sum(durs) - xf * (n - 1)
    else:
        parts.append("".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0[vcat]")
        vlabel, alabel = "vcat", None
        if has_audio:
            parts.append("".join(f"[a{k}]" for k in range(n)) + f"concat=n={n}:v=0:a=1[acat]")
            alabel = "acat"
        total = sum(durs)
    fio = min(fade_io_s, max(0.05, total / 4))
    parts.append(f"[{vlabel}]fade=t=in:st=0:d={fio:.3f},"
                 f"fade=t=out:st={max(0.0, total - fio):.3f}:d={fio:.3f}[vout]")
    aout = None
    if has_audio and alabel:
        parts.append(f"[{alabel}]afade=t=in:st=0:d={fio:.3f},"
                     f"afade=t=out:st={max(0.0, total - fio):.3f}:d={fio:.3f}[aout]")
        aout = "aout"
    return ";".join(parts), "vout", aout


def assemble_multi(
    sources: Sequence[SourceClips],
    output_dir: Path,
    *,
    reel_id: str = "shoot_reel",
    crossfade_s: float = DEFAULT_CROSSFADE_S,
    edl_only: bool = False,
    ffmpeg: str | None = None,
    ffprobe: str | None = None,
) -> ReelResult:
    """Assemble a reel across multiple source clips (one shoot)."""
    sources = [s for s in sources if s.clips]
    if not sources:
        raise ValueError("no clips selected across sources")
    metas = [probe_video(s.source_video, ffprobe=ffprobe) for s in sources]
    fps = next((m.fps for m in metas if m.fps), 25.0)
    out_dir = Path(output_dir) / reel_id
    out_dir.mkdir(parents=True, exist_ok=True)
    edl_path = out_dir / f"{reel_id}.edl"
    edl_path.write_text(build_multi_edl(sources, fps), encoding="utf-8")

    flat = [(i, c) for i, sc in enumerate(sources) for c in sc.clips]
    all_clips = [c for _, c in flat]
    total = sum(c.duration for c in all_clips)
    if edl_only:
        return ReelResult(reel_id, None, edl_path, all_clips, round(total, 3))

    ffmpeg_bin = shutil.which(ffmpeg or "ffmpeg") or ffmpeg
    if not ffmpeg_bin:
        raise FFmpegError("ffmpeg not found on PATH")
    has_audio = all((m.audio_track_count or 0) > 0 for m in metas)
    filt, vlabel, alabel = build_multi_montage_filter(
        flat, crossfade_s=crossfade_s, has_audio=has_audio)
    mp4_path = out_dir / f"{reel_id}.mp4"
    cmd = [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y"]
    for sc in sources:
        cmd += ["-i", str(sc.source_video)]
    cmd += ["-filter_complex", filt, "-map", f"[{vlabel}]"]
    if alabel:
        cmd += ["-map", f"[{alabel}]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            str(mp4_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
        raise FFmpegError(f"ffmpeg multi-assembly failed: {exc}")
    if proc.returncode != 0:
        raise FFmpegError(
            f"ffmpeg returned {proc.returncode}: {proc.stderr.strip()[:400]}")
    try:
        out_dur = probe_video(mp4_path, ffprobe=ffprobe).duration_s or total
    except FFmpegError:
        out_dur = total
    return ReelResult(reel_id, mp4_path, edl_path, all_clips, round(out_dur, 3))


def assemble_shoot(
    run_dirs: Sequence[Path],
    output_dir: Path,
    *,
    target_s: float = DEFAULT_TARGET_S,
    crossfade_s: float = DEFAULT_CROSSFADE_S,
    reel_id: str = "shoot_reel",
    edl_only: bool = False,
) -> ReelResult:
    """Read several video runs and assemble one shoot-level reel.

    Each run contributes its top candidates (split of ``target_s`` across
    the runs), clips ordered within each source, sources in run order."""
    from pixcull.scoring.temporal import _resolve_frames_dir
    run_dirs = [Path(r) for r in run_dirs]
    per_run_budget = max(2.0, target_s / max(1, len(run_dirs)))
    sources: list[SourceClips] = []
    for rd in run_dirs:
        reel_path = rd / "reel_candidates.json"
        if not reel_path.exists():
            continue
        cands = json.loads(reel_path.read_text("utf-8"))
        manifest = json.loads(
            (_resolve_frames_dir(rd, None) / "manifest.json").read_text("utf-8"))
        src = manifest.get("source_path")
        if not src or not Path(src).exists():
            continue
        clips = select_for_assembly(cands, target_s=per_run_budget)
        if clips:
            sources.append(SourceClips(Path(src), clips,
                                       label=manifest.get("source_name", "")))
    if not sources:
        raise ValueError("no usable runs (need reel_candidates.json + source)")
    return assemble_multi(sources, output_dir, reel_id=reel_id,
                          crossfade_s=crossfade_s, edl_only=edl_only)


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
