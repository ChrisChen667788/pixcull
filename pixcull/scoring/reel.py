"""v2.0-P0-3 — Reel candidate detector.

The third slice of the "PixCull for video" charter
(``docs/ROADMAP-v2.0-charter.md`` § v2.0-P0-3).  P0-2 produces per-frame
``score_temporal`` + per-window scores; P0-3 sweeps **overlapping
sliding windows** of several lengths across the whole clip and returns a
short, diverse list of "reel candidates" the user keeps / culls like
photos.

Ranking (charter formula)
-------------------------
``rank_score = window_score × confidence × novelty``

* **window_score** — ``mean(score_final) + max(score_temporal)`` over the
  window (the P0-2 formula), normalised to ``[0, 1]``.
* **confidence** — how trustworthy the window is as a usable clip:
  blends quality *consistency*, frame *coverage*, peak strength, and
  temporal stability.  Down-weights thin / shaky / erratic windows.
* **novelty** — ``1 − max overlap with already-picked candidates``
  (temporal overlap + a soft same-scene penalty).  Greedy selection so
  the list spreads across the timeline instead of clustering on one
  moment.

Selection is greedy MMR with non-max suppression: pick the best
``window_score × confidence × novelty``, suppress windows that
substantially overlap it (containment-aware, so the nested 1/2/3-second
windows at one spot collapse to one), repeat until 10–20 candidates.

Output
------
``<output_dir>/reel_candidates.json`` — a JSON **array** (per the
charter) of candidate objects with ``start_s / end_s / score / why /
best_frame_id / best_frame_score`` (+ a few extra fields).  This is what
the P0-4 lightbox renders as scrub-able peaks.

The ``why`` text is composed from the window's own signals
(burst / motion / stability / quality / faces / scene) — honest and
deterministic.  Richer semantic captions ("groom turns + embrace") need
a VLM and are deferred.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np

DEFAULT_WINDOW_LENS_S = (1.0, 2.0, 3.0)
DEFAULT_STRIDE_S = 0.5
DEFAULT_MIN_CANDIDATES = 10
DEFAULT_MAX_CANDIDATES = 20

# Containment-aware overlap above which a window is suppressed (NMS).
_NMS_OVERLAP = 0.6
# Soft same-scene penalty applied within this time gap.
_SCENE_GAP_S = 3.0
_SCENE_PENALTY = 0.4
# Stop early once the best remaining candidate's novelty-weighted score
# falls below this (only after the minimum count is met).
_NOVELTY_FLOOR = 0.05


# ==========================================================================
# Geometry / similarity helpers
# ==========================================================================

def interval_overlap_ratio(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Intersection over the *shorter* interval (containment-aware).

    Nested windows (a 1-s window inside a 3-s window at the same spot)
    return ~1.0, which is what NMS needs to collapse the multi-length
    sweep at one moment.
    """
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    shorter = min(a[1] - a[0], b[1] - b[0])
    return inter / shorter if shorter > 0 else 0.0


def _scene_similarity(a: dict, b: dict) -> float:
    sa, sb = a.get("scene"), b.get("scene")
    if sa is None or sb is None or sa != sb:
        return 0.0
    gap = max(0.0, max(a["start_s"], b["start_s"]) - min(a["end_s"], b["end_s"]))
    return _SCENE_PENALTY if gap <= _SCENE_GAP_S else 0.0


def novelty_vs(cand: dict, selected: Sequence[dict]) -> float:
    """``1 − max similarity`` to any already-picked candidate, in [0,1]."""
    if not selected:
        return 1.0
    sim = 0.0
    span = (cand["start_s"], cand["end_s"])
    for s in selected:
        overlap = interval_overlap_ratio(span, (s["start_s"], s["end_s"]))
        sim = max(sim, overlap, _scene_similarity(cand, s))
    return float(np.clip(1.0 - sim, 0.0, 1.0))


# ==========================================================================
# Window aggregation
# ==========================================================================

def _get(frame: dict, key: str, default: float = 0.0) -> float:
    v = frame.get(key)
    return default if v is None else float(v)


def window_confidence(frames: list[dict]) -> float:
    """Trust that this window is a usable clip, in ``[0, 1]``."""
    if not frames:
        return 0.0
    finals = [_get(f, "score_final") for f in frames]
    temporals = [_get(f, "score_temporal") for f in frames]
    stabilities = [_get(f, "temporal_stability", 1.0) for f in frames]
    # Consistency: low spread of frame quality ⇒ confident.
    consistency = float(np.clip(1.0 - np.std(finals) / 0.25, 0.0, 1.0))
    # Coverage: thin windows (1 frame) are weak evidence; 3+ frames full.
    coverage = float(np.clip(len(frames) / 3.0, 0.0, 1.0))
    peak = float(np.clip(max(temporals), 0.0, 1.0))
    stability = float(np.clip(np.mean(stabilities), 0.0, 1.0))
    return float(np.clip(
        0.30 * consistency + 0.20 * coverage
        + 0.25 * peak + 0.25 * stability,
        0.0, 1.0,
    ))


def window_aggregate(frames: list[dict], start_s: float, end_s: float) -> dict:
    """Aggregate one sliding window into ranking inputs + a best frame."""
    finals = [_get(f, "score_final") for f in frames]
    temporals = [_get(f, "score_temporal") for f in frames]
    mean_final = float(np.mean(finals)) if finals else 0.0
    max_temporal = max(temporals) if temporals else 0.0
    window_score = mean_final + max_temporal                  # 0..2
    # Best still = best blend of photo quality + moment.
    best_i = int(np.argmax([
        0.5 * _get(f, "score_final") + 0.5 * _get(f, "score_temporal")
        for f in frames
    ])) if frames else 0
    best = frames[best_i] if frames else {}
    best_frame_score = round(
        0.5 * _get(best, "score_final") + 0.5 * _get(best, "score_temporal"), 4)
    conf = window_confidence(frames)
    return {
        "start_s": round(start_s, 3),
        "end_s": round(end_s, 3),
        "frames": frames,
        "frame_ids": [str(f.get("frame_id")) for f in frames],
        "window_score": round(window_score, 4),
        "window_score_norm": round(window_score / 2.0, 4),
        "confidence": round(conf, 4),
        "mean_score_final": round(mean_final, 4),
        "max_score_temporal": round(max_temporal, 4),
        "best_frame_id": str(best.get("frame_id")) if best else None,
        "best_frame_score": best_frame_score,
        "scene": best.get("scene"),
    }


# ==========================================================================
# Sliding-window sweep
# ==========================================================================

def sliding_windows(
    frames: list[dict],
    *,
    window_lens_s: Sequence[float] = DEFAULT_WINDOW_LENS_S,
    stride_s: float = DEFAULT_STRIDE_S,
) -> list[dict]:
    """Sweep overlapping windows of each length; aggregate each."""
    if not frames:
        return []
    ts = [_get(f, "timestamp_s") for f in frames]
    t0, t_end = min(ts), max(ts)
    duration = max(t_end - t0, 1e-6)
    order = np.argsort(ts)
    ts_sorted = [ts[i] for i in order]
    frames_sorted = [frames[i] for i in order]

    out: list[dict] = []
    seen: set[tuple[float, float]] = set()
    for L in window_lens_s:
        if L >= duration:
            # Whole clip is a single window of this (or larger) length.
            members = frames_sorted
            key = (round(t0, 3), round(t_end, 3))
            if key not in seen and members:
                seen.add(key)
                out.append(window_aggregate(members, t0, t_end))
            continue
        start = t0
        while start <= t_end - L + 1e-9:
            end = start + L
            members = [f for f, t in zip(frames_sorted, ts_sorted)
                       if start - 1e-9 <= t < end - 1e-9 or abs(t - start) < 1e-9]
            if members:
                key = (round(start, 3), round(end, 3))
                if key not in seen:
                    seen.add(key)
                    out.append(window_aggregate(members, start, end))
            start += stride_s
        # Ensure the tail is covered.
        tail_start = t_end - L
        if tail_start > t0:
            members = [f for f, t in zip(frames_sorted, ts_sorted)
                       if tail_start - 1e-9 <= t <= t_end + 1e-9]
            key = (round(tail_start, 3), round(t_end, 3))
            if members and key not in seen:
                seen.add(key)
                out.append(window_aggregate(members, tail_start, t_end))
    return out


# ==========================================================================
# "why" composition (signal-based, deterministic)
# ==========================================================================

_SCENE_WORDS = {
    "portrait": "人物特写", "event": "现场氛围", "wedding": "婚礼时刻",
    "landscape": "风景空镜", "street": "街拍", "documentary": "纪实",
    "sports": "动感", "food": "美食", "architecture": "建筑线条",
}


def compose_why(window: dict, *, max_fragments: int = 3) -> str:
    """Human-readable reason from the window's own signals."""
    frames = window.get("frames", [])
    if not frames:
        return "可用片段"
    burst = max(_get(f, "burst_event") for f in frames)
    motion = float(np.mean([_get(f, "motion_continuity", 1.0) for f in frames]))
    stability = float(np.mean([_get(f, "temporal_stability", 1.0) for f in frames]))
    quality = window.get("mean_score_final", 0.0)
    faces = max(_get(f, "face_count") for f in frames)
    scene = window.get("scene")

    # (strength, fragment) pairs; keep the strongest few.
    cands: list[tuple[float, str]] = []
    if burst >= 0.4:
        cands.append((burst, "精彩瞬间"))
    if motion >= 0.8:
        cands.append((motion * 0.9, "平稳运镜"))
    if stability >= 0.85:
        cands.append((stability * 0.85, "画面稳定"))
    if quality >= 0.6:
        cands.append((quality, "高画质"))
    if faces >= 1:
        cands.append((0.7, "人物入镜"))
    if scene and scene in _SCENE_WORDS:
        cands.append((0.6, _SCENE_WORDS[scene]))

    if not cands:
        return "稳定可用片段"
    cands.sort(key=lambda x: x[0], reverse=True)
    seen: list[str] = []
    for _, frag in cands:
        if frag not in seen:
            seen.append(frag)
        if len(seen) >= max_fragments:
            break
    return " + ".join(seen)


# ==========================================================================
# Candidate dataclass + selection
# ==========================================================================

@dataclass
class ReelCandidate:
    rank: int
    start_s: float
    end_s: float
    duration_s: float
    window_len_s: float
    score: float           # final rank score (window_score_norm × conf × novelty)
    window_score: float    # mean(final)+max(temporal), 0..2
    confidence: float
    novelty: float
    why: str
    best_frame_id: str | None
    best_frame_score: float
    frame_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def select_candidates(
    windows: list[dict],
    *,
    n_min: int = DEFAULT_MIN_CANDIDATES,
    n_max: int = DEFAULT_MAX_CANDIDATES,
    nms_overlap: float = _NMS_OVERLAP,
) -> list[ReelCandidate]:
    """Greedy MMR + NMS over candidate windows → ranked ReelCandidates."""
    pool = [w for w in windows if w.get("frames")]
    for w in pool:
        w["_base"] = w["window_score_norm"] * w["confidence"]

    selected: list[dict] = []
    while pool and len(selected) < n_max:
        best_w = None
        best_val = -1.0
        best_nov = 0.0
        for w in pool:
            nov = novelty_vs(w, selected)
            val = w["_base"] * nov
            if val > best_val:
                best_val, best_w, best_nov = val, w, nov
        if best_w is None:
            break
        if len(selected) >= n_min and best_nov < _NOVELTY_FLOOR:
            break  # everything left is a near-duplicate
        best_w["_novelty"] = best_nov
        best_w["_score"] = best_val
        selected.append(best_w)
        # NMS: drop windows that substantially overlap the pick.
        span = (best_w["start_s"], best_w["end_s"])
        pool = [
            w for w in pool
            if w is not best_w
            and interval_overlap_ratio(
                (w["start_s"], w["end_s"]), span) <= nms_overlap
        ]

    selected.sort(key=lambda w: w["_score"], reverse=True)
    out: list[ReelCandidate] = []
    for rank, w in enumerate(selected, start=1):
        out.append(ReelCandidate(
            rank=rank,
            start_s=w["start_s"],
            end_s=w["end_s"],
            duration_s=round(w["end_s"] - w["start_s"], 3),
            window_len_s=round(w["end_s"] - w["start_s"], 3),
            score=round(w["_score"], 4),
            window_score=w["window_score"],
            confidence=w["confidence"],
            novelty=round(w["_novelty"], 4),
            why=compose_why(w),
            best_frame_id=w["best_frame_id"],
            best_frame_score=w["best_frame_score"],
            frame_ids=w["frame_ids"],
        ))
    return out


def detect_reel_candidates(
    frames: list[dict],
    *,
    window_lens_s: Sequence[float] = DEFAULT_WINDOW_LENS_S,
    stride_s: float = DEFAULT_STRIDE_S,
    n_min: int = DEFAULT_MIN_CANDIDATES,
    n_max: int = DEFAULT_MAX_CANDIDATES,
) -> list[ReelCandidate]:
    """Full P0-3 detection over per-frame records (pure; no IO)."""
    windows = sliding_windows(
        frames, window_lens_s=window_lens_s, stride_s=stride_s)
    return select_candidates(windows, n_min=n_min, n_max=n_max)


# ==========================================================================
# Run IO — read temporal.json (+ scores.csv), write reel_candidates.json
# ==========================================================================

def _load_scene_face(output_dir: Path) -> dict[str, dict]:
    """Map frame filename stem → {scene, face_count} from scores.csv."""
    out: dict[str, dict] = {}
    scores_csv = output_dir / "scores.csv"
    if not scores_csv.exists():
        return out
    try:
        with open(scores_csv, newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                fn = row.get("filename", "")
                stem = Path(fn).stem
                rec: dict = {}
                scene = row.get("scene")
                if scene not in (None, "", "nan"):
                    rec["scene"] = scene
                fc = row.get("face_count")
                try:
                    if fc not in (None, "", "nan"):
                        rec["face_count"] = float(fc)
                except (TypeError, ValueError):
                    pass
                out[stem] = rec
    except OSError:  # pragma: no cover
        pass
    return out


def run_reel_detection(
    output_dir: Path,
    *,
    window_lens_s: Sequence[float] = DEFAULT_WINDOW_LENS_S,
    stride_s: float = DEFAULT_STRIDE_S,
    n_min: int = DEFAULT_MIN_CANDIDATES,
    n_max: int = DEFAULT_MAX_CANDIDATES,
    write: bool = True,
) -> list[ReelCandidate]:
    """Read ``temporal.json`` (P0-2) + ``scores.csv``, detect reel
    candidates, write ``reel_candidates.json`` (charter array format)."""
    output_dir = Path(output_dir)
    temporal_path = output_dir / "temporal.json"
    if not temporal_path.exists():
        raise FileNotFoundError(
            f"{temporal_path} not found — run the P0-2 temporal pass first."
        )
    temporal = json.loads(temporal_path.read_text("utf-8"))
    scene_face = _load_scene_face(output_dir)

    frames: list[dict] = []
    for fr in temporal.get("frames", []):
        rec = dict(fr)
        extra = scene_face.get(str(fr.get("frame_id")), {})
        rec.update(extra)
        frames.append(rec)

    candidates = detect_reel_candidates(
        frames, window_lens_s=window_lens_s, stride_s=stride_s,
        n_min=n_min, n_max=n_max,
    )

    # v2.1-P0-3 — add a fluent `why_semantic` per candidate (optional LLM,
    # deterministic template fallback — always succeeds).
    # v2.4-P0-1 — pass the run's output dir so the opt-in VLM path
    # (PIXCULL_REEL_VLM=on) can find + caption each candidate's best frame
    # under output_dir/video_frames/<id>/.
    dicts = [c.to_dict() for c in candidates]
    try:
        from pixcull.scoring.reel_caption import enrich
        enrich(dicts, frames_root=output_dir)
    except Exception:  # pragma: no cover - captioning is best-effort
        pass
    if write:
        (output_dir / "reel_candidates.json").write_text(
            json.dumps(dicts, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return candidates
