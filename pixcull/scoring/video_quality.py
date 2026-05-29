"""v2.0-P1-4 — Shake / blur batch culling for video.

Charter ``docs/ROADMAP-v2.0-charter.md`` § v2.0-P1-4: flag the handheld
shake stretches and the soft / out-of-focus stretches in a clip so the
shooter can drop or stabilise them before they ever reach a reel.

Two signals, both per frame, then run-length-merged into ≥ ``min_dur``
second segments:

* **shake** — fast *and* erratic global motion.  A smooth pan moves a
  lot but coherently (high :func:`temporal.motion_continuity`); shake
  moves a lot *incoherently*.  ``shake = motion_mag_norm × (1 −
  continuity)``.
* **blur** — frame much softer than the clip's own median sharpness
  (Laplacian variance).  Relative, so a softly-graded clip isn't all
  flagged; only the focus-misses / motion-blur dips are.

Each flagged segment carries a human suggestion ("丢 / Gyroflow 后处理"
for shake, "对焦失败,建议丢" for blur).  The per-frame ``shake`` /
``blur`` arrays also feed the P0-3 reel detector as a soft penalty.

Pure-numpy core (``*_series`` + :func:`detect_segments`) unit-tests on
synthetic arrays; the image reader reuses ``temporal``'s frame loading.
OpenCV is used opportunistically for dense-flow shake when present, but
is never required (numpy phase correlation is the default).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from pixcull.scoring.temporal import (
    _load_gray,
    frame_motion_series,
    motion_continuity_series,
)

# A segment must persist at least this long to be worth flagging
# (a single soft frame in an otherwise sharp pan isn't actionable).
DEFAULT_MIN_DUR_S = 0.4
# Merge two same-kind segments separated by a gap shorter than this.
DEFAULT_MERGE_GAP_S = 0.5
# Per-frame score above which a frame is "bad" for that signal.
SHAKE_THRESH = 0.45
BLUR_THRESH = 0.55
# Sharpness below this fraction of the clip median counts as soft.
_BLUR_REL = 0.5


def laplacian_variance(gray: np.ndarray) -> float:
    """Variance of the discrete Laplacian — a classic focus measure.

    Higher = sharper.  Computed on the interior to avoid edge effects.
    """
    g = gray.astype(np.float64)
    lap = (g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
           - 4.0 * g[1:-1, 1:-1])
    return float(lap.var()) if lap.size else 0.0


def _robust_norm(x: np.ndarray) -> np.ndarray:
    if x.size == 0:
        return x
    hi = float(np.percentile(np.abs(x), 95))
    return np.clip(np.abs(x) / hi, 0.0, 1.0) if hi > 0 else np.zeros_like(x)


def shake_series(
    motion_mag: Sequence[float],
    motion_continuity: Sequence[float],
) -> np.ndarray:
    """Per-frame shake score in ``[0, 1]`` — fast *and* incoherent motion."""
    mag = _robust_norm(np.asarray(motion_mag, dtype=np.float64))
    cont = np.clip(np.asarray(motion_continuity, dtype=np.float64), 0.0, 1.0)
    return np.clip(mag * (1.0 - cont), 0.0, 1.0)


def blur_series(sharpness: Sequence[float]) -> np.ndarray:
    """Per-frame blur score in ``[0, 1]`` relative to the clip median.

    ``0`` at/above the median sharpness, ramping to ``1`` as a frame
    falls toward ``_BLUR_REL × median``.
    """
    s = np.asarray(sharpness, dtype=np.float64)
    if s.size == 0:
        return s
    med = float(np.median(s))
    if med <= 0:
        return np.zeros_like(s)
    rel = s / med
    # rel >= 1 → 0 ; rel <= _BLUR_REL → 1 ; linear between.
    return np.clip((1.0 - rel) / (1.0 - _BLUR_REL), 0.0, 1.0)


@dataclass
class QualitySegment:
    start_s: float
    end_s: float
    duration_s: float
    kind: str            # "shake" | "blur"
    severity: float      # mean signal over the segment, 0..1
    suggestion: str

    def to_dict(self) -> dict:
        return asdict(self)


_SUGGESTIONS = {
    "shake": "手持抖动过大,建议丢弃或用 Gyroflow / warp-stabilizer 后处理",
    "blur":  "对焦失败 / 运动模糊,建议丢弃(或仅作转场垫片)",
}


def detect_segments(
    score: Sequence[float],
    timestamps: Sequence[float],
    *,
    kind: str,
    thresh: float,
    min_dur_s: float = DEFAULT_MIN_DUR_S,
    merge_gap_s: float = DEFAULT_MERGE_GAP_S,
) -> list[QualitySegment]:
    """Run-length-merge frames whose ``score`` exceeds ``thresh`` into
    flagged segments of at least ``min_dur_s`` seconds."""
    s = np.asarray(score, dtype=np.float64)
    ts = np.asarray(timestamps, dtype=np.float64)
    n = s.shape[0]
    if n == 0 or ts.shape[0] != n:
        return []
    bad = s > thresh
    # Collect raw runs of consecutive bad frames.
    runs: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if bad[i]:
            j = i
            while j + 1 < n and bad[j + 1]:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    if not runs:
        return []
    # Merge runs separated by a short gap (in time).
    merged: list[tuple[int, int]] = [runs[0]]
    for a, b in runs[1:]:
        pa, pb = merged[-1]
        if ts[a] - ts[pb] <= merge_gap_s:
            merged[-1] = (pa, b)
        else:
            merged.append((a, b))
    out: list[QualitySegment] = []
    for a, b in merged:
        start = float(ts[a])
        # Single-frame run: give it nominal width so duration is sensible.
        end = float(ts[b]) if b > a else float(ts[b]) + (
            float(ts[1] - ts[0]) if n > 1 else 0.5)
        dur = end - start
        if dur + 1e-9 < min_dur_s:
            continue
        out.append(QualitySegment(
            start_s=round(start, 3),
            end_s=round(end, 3),
            duration_s=round(dur, 3),
            kind=kind,
            severity=round(float(s[a:b + 1].mean()), 4),
            suggestion=_SUGGESTIONS.get(kind, ""),
        ))
    return out


def frame_quality_series(
    frame_paths: Sequence[Path],
    *,
    sharp_size: int = 128,
    motion_size: int = 64,
    use_cv2: bool = True,
) -> dict:
    """Read frames once; return per-frame ``sharpness`` + motion signals.

    Returns ``{sharpness, motion_mag, motion_continuity}`` (equal-length
    lists).  Sharpness uses a larger downsample for detail; motion reuses
    :func:`temporal.frame_motion_series` semantics.
    """
    paths = [Path(p) for p in frame_paths]
    sharpness = [
        (laplacian_variance(g) if (g := _load_gray(p, sharp_size)) is not None
         else 0.0)
        for p in paths
    ]
    motion = frame_motion_series(paths, size=motion_size, use_cv2=use_cv2)
    cont = motion_continuity_series(
        motion["dx"], motion["dy"], frame_dim=float(motion_size),
        spatial_coherence=motion.get("spatial_coherence"))
    return {
        "sharpness": sharpness,
        "motion_mag": motion["mag"],
        "motion_continuity": cont.tolist(),
    }


@dataclass
class QualityResult:
    frame_count: int
    shake: list[float]
    blur: list[float]
    segments: list[QualitySegment]

    def to_dict(self) -> dict:
        shaky = [s for s in self.segments if s.kind == "shake"]
        blurry = [s for s in self.segments if s.kind == "blur"]
        return {
            "schema_version": 1,
            "frame_count": self.frame_count,
            "shake_per_frame": [round(v, 4) for v in self.shake],
            "blur_per_frame": [round(v, 4) for v in self.blur],
            "segments": [s.to_dict() for s in self.segments],
            "summary": {
                "shake_segments": len(shaky),
                "blur_segments": len(blurry),
                "flagged_seconds": round(
                    sum(s.duration_s for s in self.segments), 2),
            },
        }


def analyze_quality(
    timestamps: Sequence[float],
    *,
    sharpness: Sequence[float] | None = None,
    motion_mag: Sequence[float] | None = None,
    motion_continuity: Sequence[float] | None = None,
    imu_shake: Sequence[float] | None = None,
    min_dur_s: float = DEFAULT_MIN_DUR_S,
) -> QualityResult:
    """Compute per-frame shake/blur + flagged segments (pure; no IO).

    ``imu_shake`` (v2.1-P1-3): an optional per-frame gyro-derived shake
    signal (e.g. resampled from GoPro/DJI IMU) blended into the visual
    shake via ``max`` — catches rotational shake an optical-flow estimate
    on a low-texture frame can miss.
    """
    n = len(timestamps)
    shake = (shake_series(motion_mag, motion_continuity)
             if motion_mag is not None and motion_continuity is not None
             else np.zeros(n))
    if imu_shake is not None:
        imu = np.asarray(list(imu_shake), dtype=np.float64)
        if imu.shape[0] != n:                       # align to frame count
            fixed = np.zeros(n)
            fixed[:min(n, imu.shape[0])] = imu[:n]
            imu = fixed
        shake = np.maximum(np.asarray(shake, dtype=np.float64),
                           np.clip(imu, 0.0, 1.0))
    blur = blur_series(sharpness) if sharpness is not None else np.zeros(n)
    segs = (detect_segments(shake, timestamps, kind="shake",
                            thresh=SHAKE_THRESH, min_dur_s=min_dur_s)
            + detect_segments(blur, timestamps, kind="blur",
                              thresh=BLUR_THRESH, min_dur_s=min_dur_s))
    segs.sort(key=lambda s: s.start_s)
    return QualityResult(frame_count=n, shake=list(map(float, shake)),
                         blur=list(map(float, blur)), segments=segs)


def _imu_shake_for_run(frames_dir: Path, timestamps: Sequence[float]):
    """v2.2-P1-1 — best-effort: pull GoPro/DJI gyro shake from the run's
    source video and resample it onto the frame timestamps.  Returns None
    when there's no telemetry (the common case)."""
    import json as _json
    try:
        manifest = _json.loads((frames_dir / "manifest.json").read_text("utf-8"))
        source = manifest.get("source_path")
        duration = float(manifest.get("duration_s") or 0.0)
        if not source or not Path(source).exists() or duration <= 0:
            return None
        from pixcull.io.gpmf import parse_telemetry, resample_to_frames
        tel = parse_telemetry(Path(source))
        if not tel.imu_shake:
            return None
        return resample_to_frames(tel.imu_shake, duration, timestamps).tolist()
    except Exception:        # telemetry is optional; never break the run
        return None


def run_quality_analysis(
    output_dir: Path,
    frames_dir: Path | None = None,
    *,
    write: bool = True,
    read_imu: bool = True,
) -> QualityResult:
    """Read a video run's frames, flag shake/blur, write ``quality_flags.json``.

    v2.2-P1-1: when the source carries GoPro/DJI IMU, its gyro shake is
    auto-resampled onto the frames and blended into the shake signal."""
    from pixcull.scoring.temporal import load_run_records, _resolve_frames_dir
    output_dir = Path(output_dir)
    frames_dir = _resolve_frames_dir(output_dir, frames_dir)
    records, paths = load_run_records(output_dir, frames_dir)
    timestamps = [r.get("timestamp_s", 0.0) for r in records]
    q = frame_quality_series(paths)
    imu_shake = _imu_shake_for_run(frames_dir, timestamps) if read_imu else None
    result = analyze_quality(
        timestamps,
        sharpness=q["sharpness"],
        motion_mag=q["motion_mag"],
        motion_continuity=q["motion_continuity"],
        imu_shake=imu_shake,
    )
    if write:
        (output_dir / "quality_flags.json").write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8")
    return result
