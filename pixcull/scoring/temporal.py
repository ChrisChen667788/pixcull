"""v2.0-P0-2 — Temporal scoring + time-window aggregation for video.

The second slice of the "PixCull for video" charter
(``docs/ROADMAP-v2.0-charter.md`` § v2.0-P0-2).  P0-1 extracts frames
and scores each one with the existing 6-axis rubric; this module adds
the **time dimension** the rubric can't see:

``score_temporal`` per frame = weighted blend of three signals
-------------------------------------------------------------
1. **motion_continuity** — is camera/global motion *smooth*?  A steady
   pan or a locked-off static shot scores high; handheld shake scores
   low.  Derived from frame-to-frame global translation (numpy phase
   correlation) by measuring directional coherence over a local window
   (``||Σv|| / Σ||v||``).  Optionally boosted by cv2 dense-flow spatial
   coherence when OpenCV is installed.
2. **temporal_stability** — does *content* change smoothly?  Penalises
   exposure flicker, focus pumping, subject popping in/out, and hard
   scene cuts.  Derived from the smoothness of the luma / sharpness /
   subject-fraction / scene-label time series.
3. **burst_event** — is this a *peak instant*?  Rewards frames that
   stand out from their temporal neighbours (the smile, the jump apex,
   the kiss) via a local z-score of a salience signal built from the
   "moment" axis + appearance change + face activity.

time-window aggregation
-----------------------
Frames are binned into ``window_s``-second windows; each window's score
is ``mean(score_final per frame) + max(score_temporal per frame)`` (the
formula the charter specifies).  These per-window scores are what the
P0-3 reel-candidate detector will rank.

Design notes
------------
* The numeric core (``*_series`` functions, :func:`analyze_temporal`,
  :func:`aggregate_windows`) is pure numpy / lists — no image or disk
  access — so it unit-tests with synthetic time-series.
* Image reading (:func:`frame_motion_series`) and run joining
  (:func:`load_run_records`, :func:`run_temporal_analysis`) live in a
  thin IO layer that degrades gracefully when frames or score columns
  are missing.
* No new hard dependency: numpy + Pillow are already required; OpenCV
  is used opportunistically and never required.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np

DEFAULT_WINDOW_S = 1.0
DEFAULT_WEIGHTS: dict[str, float] = {
    "motion": 0.35,
    "stability": 0.25,
    "burst": 0.40,
}

# Local-window sizes (in frames) for the three signals.
_MOTION_WIN = 5
_STABILITY_WIN = 5
_BURST_WIN = 9

# A global translation smaller than this fraction of the frame is treated
# as "static" (a locked-off shot), which is maximally smooth.
_STATIC_FRAC = 0.01

# Burst z-score that maps to a full 1.0 (≈2σ above the local baseline).
_BURST_Z = 2.0

# Fixed smoothness scales for exp(-delta/scale) stability sub-signals.
_LUMA_SCALE = 15.0          # mean_luma is 0–255
_SUBJECT_SCALE = 0.12       # subject_fraction is 0–1
_SHARP_REL_SCALE = 0.4      # sharpness normalised by its own median


# ==========================================================================
# Global motion estimation (numpy phase correlation)
# ==========================================================================

def phase_correlate(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Return the dominant ``(dx, dy)`` translation from ``a`` to ``b``.

    Pure-numpy phase correlation on two equally-shaped 2-D arrays.  A
    Hanning window suppresses edge wrap-around.  The sign convention is
    internally consistent (all that matters for continuity).
    """
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    a = a - a.mean()
    b = b - b.mean()
    h, w = a.shape
    win = np.outer(np.hanning(h), np.hanning(w))
    fa = np.fft.fft2(a * win)
    fb = np.fft.fft2(b * win)
    cross = fa * np.conj(fb)
    denom = np.abs(cross)
    denom[denom == 0] = 1e-12
    cross /= denom
    r = np.fft.ifft2(cross).real
    py, px = np.unravel_index(int(np.argmax(r)), r.shape)
    if py > h // 2:
        py -= h
    if px > w // 2:
        px -= w
    return float(px), float(py)


# ==========================================================================
# Per-frame signal series (pure numpy)
# ==========================================================================

def _as_array(x: Sequence[float] | None, n: int, default: float = 0.0) -> np.ndarray:
    if x is None:
        return np.full(n, default, dtype=np.float64)
    arr = np.array([default if v is None else float(v) for v in x],
                   dtype=np.float64)
    if arr.shape[0] != n:  # pragma: no cover - defensive
        out = np.full(n, default, dtype=np.float64)
        out[: arr.shape[0]] = arr[:n]
        return out
    return arr


def _window_bounds(i: int, n: int, win: int) -> tuple[int, int]:
    half = win // 2
    return max(0, i - half), min(n, i + half + 1)


def motion_continuity_series(
    dx: Sequence[float],
    dy: Sequence[float],
    *,
    win: int = _MOTION_WIN,
    frame_dim: float = 64.0,
    spatial_coherence: Sequence[float] | None = None,
) -> np.ndarray:
    """Directional coherence of global motion over a local window.

    ``1.0`` = perfectly smooth pan or static lock-off; ``~0`` = erratic
    shake.  Computed as ``||Σ v|| / Σ ||v||`` over the window (which is
    magnitude-weighted and undefined-direction-safe).  Optionally blended
    50/50 with a per-frame spatial-coherence signal (e.g. cv2 dense-flow
    field uniformity) when supplied.
    """
    dxv = np.asarray(dx, dtype=np.float64)
    dyv = np.asarray(dy, dtype=np.float64)
    n = dxv.shape[0]
    out = np.ones(n, dtype=np.float64)
    static_thresh = _STATIC_FRAC * frame_dim
    mags = np.hypot(dxv, dyv)
    for i in range(n):
        lo, hi = _window_bounds(i, n, win)
        m = mags[lo:hi]
        if m.size == 0 or float(m.mean()) < static_thresh:
            out[i] = 1.0  # static / locked-off ⇒ maximally smooth
            continue
        sum_vec = np.hypot(dxv[lo:hi].sum(), dyv[lo:hi].sum())
        sum_mag = float(m.sum())
        out[i] = sum_vec / sum_mag if sum_mag > 0 else 1.0
    out = np.clip(out, 0.0, 1.0)
    if spatial_coherence is not None:
        sc = np.clip(_as_array(spatial_coherence, n, 1.0), 0.0, 1.0)
        out = 0.5 * out + 0.5 * sc
    return out


def temporal_stability_series(
    *,
    luma: Sequence[float] | None = None,
    sharpness: Sequence[float] | None = None,
    subject_fraction: Sequence[float] | None = None,
    scene_id: Sequence[int] | None = None,
    n: int,
    win: int = _STABILITY_WIN,
) -> np.ndarray:
    """Smoothness of the content time series, in ``[0, 1]``.

    Averages whichever sub-signals are available: luma flicker, focus
    pumping (sharpness), subject framing drift, and scene-label cuts.
    Each numeric sub-signal uses ``exp(-local_mean(|Δ|)/scale)`` so a
    perfectly steady clip → 1.0 and a flickering one → ~0.
    """
    subsignals: list[np.ndarray] = []

    def _smoothness(values: np.ndarray, scale: float) -> np.ndarray:
        deltas = np.abs(np.diff(values, prepend=values[:1]))
        sm = np.empty(n, dtype=np.float64)
        for i in range(n):
            lo, hi = _window_bounds(i, n, win)
            sm[i] = np.exp(-float(deltas[lo:hi].mean()) / scale)
        return sm

    if luma is not None:
        subsignals.append(_smoothness(_as_array(luma, n), _LUMA_SCALE))
    if sharpness is not None:
        s = _as_array(sharpness, n)
        med = float(np.median(s)) if np.median(s) > 0 else 1.0
        subsignals.append(_smoothness(s / med, _SHARP_REL_SCALE))
    if subject_fraction is not None:
        subsignals.append(
            _smoothness(_as_array(subject_fraction, n), _SUBJECT_SCALE))
    if scene_id is not None:
        ids = list(scene_id)
        sc = np.empty(n, dtype=np.float64)
        for i in range(n):
            lo, hi = _window_bounds(i, n, win)
            window_ids = ids[lo:hi]
            same = sum(1 for v in window_ids if v == ids[i])
            sc[i] = same / max(1, len(window_ids))
        subsignals.append(sc)

    if not subsignals:
        return np.ones(n, dtype=np.float64)
    return np.clip(np.mean(subsignals, axis=0), 0.0, 1.0)


def _robust_norm(x: np.ndarray) -> np.ndarray:
    """Scale to [0,1] by the 95th percentile (robust to single spikes)."""
    if x.size == 0:
        return x
    hi = float(np.percentile(np.abs(x), 95))
    if hi <= 0:
        return np.zeros_like(x)
    return np.clip(np.abs(x) / hi, 0.0, 1.0)


def burst_event_series(
    salience: Sequence[float],
    *,
    win: int = _BURST_WIN,
) -> np.ndarray:
    """Local positive z-score of ``salience`` mapped to ``[0, 1]``.

    A frame that exceeds its local neighbourhood baseline by ≈2σ scores
    ~1.0; frames at or below the baseline score 0.  This isolates the
    *peak instant* within a stretch of similar frames.
    """
    s = np.asarray(salience, dtype=np.float64)
    n = s.shape[0]
    out = np.zeros(n, dtype=np.float64)
    for i in range(n):
        lo, hi = _window_bounds(i, n, win)
        local = s[lo:hi]
        mu = float(local.mean())
        sd = float(local.std())
        if sd < 1e-9:
            out[i] = 0.0
            continue
        z = (s[i] - mu) / sd
        out[i] = np.clip(z / _BURST_Z, 0.0, 1.0)
    return out


def build_salience(
    *,
    score_moment: Sequence[float] | None,
    appearance_change: Sequence[float] | None,
    face_count: Sequence[float] | None,
    n: int,
) -> np.ndarray:
    """Combine moment-axis + appearance change + face activity → salience."""
    moment = np.clip(_as_array(score_moment, n), 0.0, 1.0)
    appear = _robust_norm(_as_array(appearance_change, n))
    faces = _as_array(face_count, n)
    face_activity = _robust_norm(np.abs(np.diff(faces, prepend=faces[:1])))
    return 0.5 * moment + 0.3 * appear + 0.2 * face_activity


# ==========================================================================
# Composite + dataclasses
# ==========================================================================

@dataclass
class FrameTemporal:
    frame_id: str
    timestamp_s: float
    score_final: float | None
    motion_continuity: float
    temporal_stability: float
    burst_event: float
    score_temporal: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WindowScore:
    index: int
    start_s: float
    end_s: float
    frame_count: int
    frame_ids: list[str]
    mean_score_final: float
    max_score_temporal: float
    window_score: float
    peak_frame_id: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TemporalResult:
    frames: list[FrameTemporal] = field(default_factory=list)
    windows: list[WindowScore] = field(default_factory=list)
    window_s: float = DEFAULT_WINDOW_S
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    used_motion: bool = False

    def to_dict(self) -> dict:
        best = max(self.windows, key=lambda w: w.window_score, default=None)
        return {
            "schema_version": 1,
            "window_s": self.window_s,
            "weights": self.weights,
            "used_motion": self.used_motion,
            "frame_count": len(self.frames),
            "window_count": len(self.windows),
            "mean_score_temporal": (
                round(float(np.mean([f.score_temporal for f in self.frames])), 4)
                if self.frames else 0.0
            ),
            "best_window": best.to_dict() if best else None,
            "frames": [f.to_dict() for f in self.frames],
            "windows": [w.to_dict() for w in self.windows],
        }


def _normalise_weights(weights: dict[str, float] | None) -> dict[str, float]:
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update({k: float(v) for k, v in weights.items() if k in w})
    total = sum(w.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in w.items()}


def aggregate_windows(
    timestamps: Sequence[float],
    score_final: Sequence[float | None],
    score_temporal: Sequence[float],
    frame_ids: Sequence[str],
    *,
    window_s: float = DEFAULT_WINDOW_S,
) -> list[WindowScore]:
    """Bin frames into ``window_s`` windows; per the charter each window's
    score is ``mean(score_final) + max(score_temporal)``."""
    if window_s <= 0:
        raise ValueError(f"window_s must be > 0, got {window_s}")
    n = len(timestamps)
    if n == 0:
        return []
    t0 = float(timestamps[0])
    buckets: dict[int, list[int]] = {}
    for i in range(n):
        idx = int((float(timestamps[i]) - t0) // window_s)
        buckets.setdefault(idx, []).append(i)

    out: list[WindowScore] = []
    for idx in sorted(buckets):
        members = buckets[idx]
        finals = [score_final[i] for i in members if score_final[i] is not None]
        temps = [float(score_temporal[i]) for i in members]
        mean_final = float(np.mean(finals)) if finals else 0.0
        max_temp = max(temps) if temps else 0.0
        peak_i = max(members, key=lambda i: float(score_temporal[i]))
        out.append(WindowScore(
            index=idx,
            start_s=round(t0 + idx * window_s, 3),
            end_s=round(t0 + (idx + 1) * window_s, 3),
            frame_count=len(members),
            frame_ids=[frame_ids[i] for i in members],
            mean_score_final=round(mean_final, 4),
            max_score_temporal=round(max_temp, 4),
            window_score=round(mean_final + max_temp, 4),
            peak_frame_id=frame_ids[peak_i],
        ))
    return out


def analyze_temporal(
    records: list[dict],
    *,
    motion: dict | None = None,
    window_s: float = DEFAULT_WINDOW_S,
    weights: dict[str, float] | None = None,
) -> TemporalResult:
    """Compute per-frame ``score_temporal`` + per-window aggregation.

    Args:
        records: per-frame dicts **in temporal order**, each with
            ``frame_id``, ``timestamp_s`` and any of ``score_final``,
            ``score_moment``, ``mean_luma``, ``sharpness``,
            ``subject_fraction``, ``face_count``, ``scene``.
        motion: optional output of :func:`frame_motion_series`
            (``dx``/``dy``/``appearance``/``spatial_coherence`` arrays).
            When absent, motion is treated as static and burst relies on
            the moment axis + face activity only.
        window_s: aggregation window in seconds.
        weights: override the ``motion``/``stability``/``burst`` blend.
    """
    n = len(records)
    w = _normalise_weights(weights)
    result = TemporalResult(window_s=window_s, weights=w,
                            used_motion=motion is not None)
    if n == 0:
        return result

    def col(key: str):
        return [r.get(key) for r in records]

    frame_ids = [str(r.get("frame_id", f"frame_{i:06d}"))
                 for i, r in enumerate(records)]
    timestamps = _as_array(col("timestamp_s"), n)

    # scene labels → small int ids
    scenes = col("scene")
    uniq: dict = {}
    scene_ids = [uniq.setdefault(s, len(uniq)) for s in scenes]

    if motion:
        dx = _as_array(motion.get("dx"), n)
        dy = _as_array(motion.get("dy"), n)
        appearance = motion.get("appearance")
        frame_dim = float(motion.get("frame_dim", 64.0))
        spatial = motion.get("spatial_coherence")
    else:
        dx = np.zeros(n)
        dy = np.zeros(n)
        appearance = None
        frame_dim = 64.0
        spatial = None

    motion_cont = motion_continuity_series(
        dx, dy, frame_dim=frame_dim, spatial_coherence=spatial)
    stability = temporal_stability_series(
        luma=col("mean_luma"),
        sharpness=col("sharpness"),
        subject_fraction=col("subject_fraction"),
        scene_id=scene_ids,
        n=n,
    )
    salience = build_salience(
        score_moment=col("score_moment"),
        appearance_change=appearance,
        face_count=col("face_count"),
        n=n,
    )
    burst = burst_event_series(salience)

    score_temporal = np.clip(
        w["motion"] * motion_cont
        + w["stability"] * stability
        + w["burst"] * burst,
        0.0, 1.0,
    )

    sf_raw = col("score_final")
    for i in range(n):
        result.frames.append(FrameTemporal(
            frame_id=frame_ids[i],
            timestamp_s=round(float(timestamps[i]), 3),
            score_final=(None if sf_raw[i] is None else round(float(sf_raw[i]), 4)),
            motion_continuity=round(float(motion_cont[i]), 4),
            temporal_stability=round(float(stability[i]), 4),
            burst_event=round(float(burst[i]), 4),
            score_temporal=round(float(score_temporal[i]), 4),
        ))

    result.windows = aggregate_windows(
        timestamps.tolist(), sf_raw, score_temporal.tolist(),
        frame_ids, window_s=window_s,
    )
    return result


# ==========================================================================
# Image-based motion extraction (Pillow; optional cv2 booster)
# ==========================================================================

def _load_gray(path: Path, size: int) -> np.ndarray | None:
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("L").resize((size, size))
            return np.asarray(im, dtype=np.float64)
    except Exception:  # pragma: no cover - corrupt/missing frame
        return None


def _cv2_flow_coherence(prev: np.ndarray, cur: np.ndarray) -> float | None:
    """Spatial uniformity of dense optical flow, 0–1, or None if no cv2."""
    try:
        import cv2  # noqa: PLC0415
    except Exception:
        return None
    try:
        flow = cv2.calcOpticalFlowFarneback(
            prev.astype(np.uint8), cur.astype(np.uint8),
            None, 0.5, 2, 11, 2, 5, 1.1, 0,
        )
        fx, fy = flow[..., 0].ravel(), flow[..., 1].ravel()
        mag = np.hypot(fx, fy)
        if float(mag.sum()) < 1e-6:
            return 1.0  # no flow ⇒ perfectly coherent (static)
        resultant = np.hypot(fx.sum(), fy.sum())
        return float(np.clip(resultant / mag.sum(), 0.0, 1.0))
    except Exception:  # pragma: no cover
        return None


def frame_motion_series(
    frame_paths: Sequence[Path],
    *,
    size: int = 64,
    use_cv2: bool = True,
) -> dict:
    """Read frames and return per-frame motion signals.

    Returns a dict with equal-length lists ``dx``/``dy``/``mag``/
    ``appearance``/``spatial_coherence`` (the first frame gets zeros),
    plus ``frame_dim`` for normalisation.  Unreadable frames inherit the
    previous frame's zeros.
    """
    paths = [Path(p) for p in frame_paths]
    n = len(paths)
    dx = [0.0] * n
    dy = [0.0] * n
    mag = [0.0] * n
    appearance = [0.0] * n
    coherence: list[float] = [1.0] * n

    prev = _load_gray(paths[0], size) if n else None
    any_coherence = False
    for i in range(1, n):
        cur = _load_gray(paths[i], size)
        if prev is None or cur is None:
            prev = cur if cur is not None else prev
            continue
        ddx, ddy = phase_correlate(prev, cur)
        dx[i], dy[i] = ddx, ddy
        mag[i] = float(np.hypot(ddx, ddy))
        appearance[i] = float(np.abs(cur - prev).mean())
        if use_cv2:
            c = _cv2_flow_coherence(prev, cur)
            if c is not None:
                coherence[i] = c
                any_coherence = True
        prev = cur

    out = {
        "dx": dx, "dy": dy, "mag": mag,
        "appearance": appearance, "frame_dim": float(size),
    }
    if any_coherence:
        out["spatial_coherence"] = coherence
    return out


# ==========================================================================
# Run IO — join manifest + scores.csv, write temporal.json
# ==========================================================================

# scores.csv column → record key.  Missing columns degrade gracefully.
_SCORE_COLS = {
    "score_final": "score_final",
    "score_moment": "score_moment",
    "mean_luma": "mean_luma",
    "laplacian_global": "sharpness",
    "subject_fraction": "subject_fraction",
    "face_count": "face_count",
    "scene": "scene",
}


def _resolve_frames_dir(output_dir: Path, frames_dir: Path | None) -> Path:
    if frames_dir is not None:
        return Path(frames_dir)
    root = Path(output_dir) / "video_frames"
    subs = [p for p in root.iterdir() if p.is_dir()] if root.exists() else []
    if len(subs) != 1:
        raise FileNotFoundError(
            f"could not auto-resolve a single video_frames/<id>/ under "
            f"{output_dir} (found {len(subs)}); pass frames_dir explicitly."
        )
    return subs[0]


def load_run_records(
    output_dir: Path,
    frames_dir: Path | None = None,
) -> tuple[list[dict], list[Path]]:
    """Join ``manifest.json`` (frame order + timestamps) with
    ``scores.csv`` (per-frame rubric) into ordered records + frame paths."""
    output_dir = Path(output_dir)
    frames_dir = _resolve_frames_dir(output_dir, frames_dir)

    manifest = json.loads((frames_dir / "manifest.json").read_text("utf-8"))
    man_frames = manifest.get("frames", [])

    scores_by_name: dict[str, dict] = {}
    scores_csv = output_dir / "scores.csv"
    if scores_csv.exists():
        import pandas as pd
        df = pd.read_csv(scores_csv)
        for _, row in df.iterrows():
            rec = {}
            for col, key in _SCORE_COLS.items():
                if col in df.columns:
                    val = row[col]
                    if key == "scene":
                        rec[key] = None if pd.isna(val) else str(val)
                    else:
                        rec[key] = None if pd.isna(val) else float(val)
            scores_by_name[str(row.get("filename", ""))] = rec

    records: list[dict] = []
    paths: list[Path] = []
    for fr in man_frames:
        fn = fr.get("filename", "")
        rec = {
            "frame_id": fr.get("frame_id"),
            "timestamp_s": fr.get("timestamp_s", 0.0),
        }
        rec.update(scores_by_name.get(fn, {}))
        records.append(rec)
        paths.append(frames_dir / fn)
    return records, paths


def run_temporal_analysis(
    output_dir: Path,
    frames_dir: Path | None = None,
    *,
    window_s: float = DEFAULT_WINDOW_S,
    weights: dict[str, float] | None = None,
    read_motion: bool = True,
    write: bool = True,
) -> TemporalResult:
    """Full P0-2 pass for one video run.

    Reads ``manifest.json`` + ``scores.csv``, computes motion signals
    from the extracted frames, scores ``score_temporal`` per frame,
    aggregates per-window scores, and (by default) writes
    ``<output_dir>/temporal.json``.  Returns the :class:`TemporalResult`.
    """
    output_dir = Path(output_dir)
    records, paths = load_run_records(output_dir, frames_dir)

    motion = None
    if read_motion and paths and all(p.exists() for p in paths[:1]):
        existing = [p for p in paths if p.exists()]
        if len(existing) == len(paths):
            motion = frame_motion_series(paths)

    result = analyze_temporal(
        records, motion=motion, window_s=window_s, weights=weights)

    if write:
        (output_dir / "temporal.json").write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return result
