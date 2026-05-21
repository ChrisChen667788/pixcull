"""V27 — action peak ranking within bursts.

ROADMAP P1.2. Sports / event / kids photographer shoots a 30-frame
burst of a soccer kick, a player diving, a kid laughing. The "THE
shot" is one frame: the one where the foot meets the ball, the body
is fully extended, the eyes are wide. Today PixCull treats each frame
independently — keep / maybe / cull on per-image scores — and the
photographer manually scrubs through the burst to find THE peak.

V27 adds a per-burst peak rank: within each ``cluster_id`` group
(already populated by ``detectors.duplicate.cluster_bursts``), photos
are scored by a composite "peakness" metric. The top-1 in each cluster
is marked ``is_burst_peak=True``; a ``peak_rank`` int (0=peak, 1=second,
...) is also surfaced for the UI to show "show me the top 3 in this
burst."

Composite peakness score
========================
Combines four signals, weighted to favor the moment over technical
perfection (a slightly soft peak action shot still beats a sharp
in-between frame):

    peakness = 0.40 * score_final              # overall rule-stack
             + 0.25 * score_sharpness          # peak action ≈ stop-motion
                                               # rather than blurry follow-through
             + 0.20 * (1 - face_max_blink)     # eyes open (1 - blink)
             + 0.15 * (face_min_ear)           # eye-aspect-ratio non-zero

Weights tuned by hand on the canonical sports use case (soccer +
basketball + skating photos). Score_final dominates because it
already encodes most of what we care about; the face terms break
ties between two near-equally-good frames.

Edge cases:
* Burst of size 1: peak_rank=0, is_burst_peak=True (every photo is
  its own cluster). Practically the same as the keep/cull flag,
  doesn't add information; UI filter ignores size-1 clusters.
* face_max_blink / face_min_ear missing: those terms contribute 0,
  the technical/final dominate. Common for non-face shots (wildlife
  bursts, landscape brackets).
* score_final missing: row gets peakness=0 and ranks last.

Output schema
=============
Per row:
    "peak_rank"        int     # 0 = peak, N-1 = worst in cluster
    "is_burst_peak"    bool    # True iff peak_rank == 0

Whole-run summary via ``burst_peak_summary``:
    {cluster_id: {n_photos, peak_filename, peak_score}}
    (clusters of size 1 omitted — not meaningful peaks)
"""

from __future__ import annotations

import sys
from typing import Any

import pandas as pd


# Composite peakness weights. Documented up top in the module
# docstring; tweak here if you find a real-world burst where these
# choose the wrong frame.
_PEAKNESS_WEIGHTS = {
    "score_final":      0.40,
    "score_sharpness":  0.25,
    "blink_inverse":    0.20,    # (1 - face_max_blink) when available
    "ear":              0.15,    # face_min_ear when available
}


def _peakness_for_row(row: dict[str, Any]) -> float:
    """Compute a single peakness number for one row. Missing signals
    contribute 0 (not NaN — that would poison the per-cluster sort).
    """
    sf = _safe_float(row.get("score_final"))
    ss = _safe_float(row.get("score_sharpness"))
    blink_inv = 1.0 - _safe_float(row.get("face_max_blink"), default=0.0)
    ear = _safe_float(row.get("face_min_ear"))
    w = _PEAKNESS_WEIGHTS
    return (w["score_final"]     * sf
            + w["score_sharpness"] * ss
            + w["blink_inverse"]   * blink_inv
            + w["ear"]             * ear)


def _safe_float(v: object, default: float = 0.0) -> float:
    """NaN-safe float coerce. pandas reads missing CSV cells as NaN,
    which would propagate through arithmetic; treat them as 0."""
    if v is None:
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f:   # NaN
        return default
    return f


def rank_burst_peaks(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``peak_rank`` + ``is_burst_peak`` columns to the dataframe.

    Idempotent — re-running on a df that already has the columns
    overwrites with the same values (deterministic from the inputs).

    Args:
      df: orchestrator's dataframe AFTER ``cluster_bursts`` ran
          (i.e. must have ``cluster_id`` populated).

    Returns the dataframe with new columns added (mutates in place
    AND returns for fluent chaining).
    """
    if df.empty or "cluster_id" not in df.columns:
        df["peak_rank"] = 0
        df["is_burst_peak"] = False
        return df

    # Compute peakness for every row
    peakness = df.apply(lambda r: _peakness_for_row(r.to_dict()),
                          axis=1)
    df = df.copy()
    df["_peakness"] = peakness

    # Within each cluster, rank by descending peakness (peak_rank=0 =
    # highest peakness). pandas `groupby + rank` does the job; use
    # method='first' so ties get distinct ranks (otherwise two
    # photos with identical peakness would both get rank 0).
    df["peak_rank"] = (
        df.groupby("cluster_id")["_peakness"]
          .rank(method="first", ascending=False)
          .astype(int) - 1
    )
    df["is_burst_peak"] = df["peak_rank"] == 0

    # Don't keep the intermediate in the output — it'd bloat scores.csv
    # and isn't useful downstream.
    df = df.drop(columns=["_peakness"])

    n_peaks = int(df["is_burst_peak"].sum())
    n_clusters = df["cluster_id"].nunique()
    print(f"[burst_peak] {n_clusters} clusters → {n_peaks} marked as peak",
          file=sys.stderr)
    return df


def burst_peak_summary(df: pd.DataFrame) -> list[dict]:
    """V27 — per-burst summary for the UI:
    [{cluster_id, n_photos, peak_filename, peak_score}, ...]

    Only includes clusters of size ≥ 2 — a burst of 1 isn't a
    meaningful peak pick. Sorted by n_photos descending so the biggest
    bursts surface first in the filter UI.
    """
    if df.empty or "cluster_id" not in df.columns:
        return []
    out = []
    for cid, group in df.groupby("cluster_id"):
        if len(group) < 2:
            continue
        peak_row = group[group["is_burst_peak"]].iloc[0] \
            if "is_burst_peak" in group.columns \
            and group["is_burst_peak"].any() else group.iloc[0]
        out.append({
            "cluster_id":    int(cid),
            "n_photos":      len(group),
            "peak_filename": str(peak_row.get("filename", "")),
            "peak_score":    _safe_float(peak_row.get("score_final")),
        })
    out.sort(key=lambda d: -d["n_photos"])
    return out


def annotate_burst_peak_reasons(df: pd.DataFrame) -> pd.DataFrame:
    """P-AI-5.1 — add ``burst_peak_reason`` to whichever row V27
    already flagged as ``is_burst_peak`` for each cluster.

    The reason string is produced by the more sophisticated P-AI-5
    picker in ``pixcull.scoring.burst_peak`` (z-scored sharpness +
    embedding distinctness + score_final + face evidence).  We do
    NOT change ``is_burst_peak`` — that stays as V27's authoritative
    pick to avoid disturbing downstream consumers (the lightbox
    🏆 badge, the export filter, the iOS app).  Instead we attach
    a per-component explanation so the user can see *why* a frame
    is the peak ("眼睛睁开 95%" / "簇内最锐 100%" /
    "姿态/动作差异最大 85%").

    Adds:
      ``burst_peak_reason``  str | None — explanation, only set on
                                          rows where is_burst_peak
                                          is True AND cluster size
                                          ≥ 2 (singletons aren't
                                          meaningful peaks).

    Idempotent.  No-op if cluster_id or is_burst_peak is missing.
    """
    if df.empty:
        df["burst_peak_reason"] = None
        return df
    if ("cluster_id" not in df.columns
        or "is_burst_peak" not in df.columns):
        df["burst_peak_reason"] = None
        return df

    # Local import — keeps the V27 import surface unchanged for
    # callers that only want the original ranker, and avoids a
    # cross-module cycle if scoring.burst_peak ever wants to
    # import something from pipeline.
    from pixcull.scoring.burst_peak import rank_burst_peak

    reasons: dict[int, str] = {}   # row index → reason
    for cid, group in df.groupby("cluster_id"):
        if len(group) < 2:
            continue
        # Build a list of plain row dicts; preserve the original df
        # index so we can write the reason back to the right row.
        rows: list[dict] = []
        for idx, row in group.iterrows():
            d = row.to_dict()
            d["_orig_idx"] = idx
            rows.append(d)
        try:
            result = rank_burst_peak(rows)
        except Exception:
            # Defensive — never let the explanation step crash the
            # pipeline.  Pipeline ships fine without reasons.
            continue
        # Find the V27-picked winner (is_burst_peak == True) in
        # this cluster, look up the P-AI-5 reason for that filename.
        peaks = group[group["is_burst_peak"]]
        if peaks.empty:
            continue
        peak_idx = peaks.index[0]
        peak_fn = str(group.loc[peak_idx].get("filename", ""))
        # P-AI-5 result.reasons is keyed by filename — direct lookup.
        if peak_fn in result.reasons:
            reasons[peak_idx] = result.reasons[peak_fn]

    # Materialize the column
    df = df.copy()
    df["burst_peak_reason"] = df.index.map(
        lambda i: reasons.get(i)
    )
    return df


__all__ = [
    "rank_burst_peaks",
    "burst_peak_summary",
    "annotate_burst_peak_reasons",
]
