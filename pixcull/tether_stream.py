"""v0.10-P1-2 — streaming burst-peak picker for tether sessions.

The v0.7-P2-2 tether session analyzes one image at a time and
appends to scores.csv.  v0.9 added burst-peak picking, but it
ran offline on the whole batch — so during a tether session
(live wedding shoot), the photographer's burst-peak badge stayed
static until they next ran the full pipeline.

v0.10-P1-2 streams it: after each new row lands, this module:

  1. Clusters the last N rows (default 50, ~5 s of bursts at
     10 fps) by mtime proximity (≤ 2 s gap by default) + scene
     match.
  2. If the new row falls into an existing burst cluster,
     re-ranks that cluster's peak using the existing scoring
     features (sharpness / eyes-open / expression).
  3. Returns the updated cluster row dicts with `is_burst_peak`
     flipped to whichever frame just became the new peak.

Pure functions; the caller (tether.TetherSession) handles the
IO.  Unit-test friendly because we don't touch disk or watcher
threads here.
"""

from __future__ import annotations

import math
from typing import Iterable

# Defaults.  WINDOW_SIZE is the max number of recent rows we
# consider for clustering — 50 covers ~5 s of 10 fps bursts plus
# any sparse non-burst frames around them.  BURST_GAP_S is the
# inter-frame mtime threshold below which two adjacent shots are
# considered "the same burst" (200 ms is generous for handheld;
# DSLR bursts shoot at 30-60 ms).
WINDOW_SIZE = 50
BURST_GAP_S = 2.0


def _safe_float(v, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if not math.isnan(x) else default
    except (TypeError, ValueError):
        return default


def cluster_recent(
    rows: list[dict],
    *,
    gap_s: float = BURST_GAP_S,
) -> list[list[dict]]:
    """Cluster rows into burst groups by mtime proximity + scene.

    Two adjacent rows belong to the same burst when:
      * |row[i].mtime - row[i-1].mtime| ≤ gap_s
      * row[i].scene == row[i-1].scene (loose check; better than
        nothing for "the photographer changed venues mid-burst")

    Rows must arrive in mtime order — the streamer feeds them in
    capture order by construction.  Returns a list of clusters
    (each cluster is a list of rows in order).
    """
    if not rows:
        return []
    clusters: list[list[dict]] = []
    current: list[dict] = [rows[0]]
    for r in rows[1:]:
        prev = current[-1]
        prev_t = _safe_float(prev.get("mtime") or prev.get("timestamp"))
        cur_t  = _safe_float(r.get("mtime")    or r.get("timestamp"))
        same_scene = (prev.get("scene") or "") == (r.get("scene") or "")
        if (cur_t - prev_t) <= gap_s and same_scene:
            current.append(r)
        else:
            clusters.append(current)
            current = [r]
    clusters.append(current)
    return clusters


def _peakness_score(row: dict) -> float:
    """One scalar per row — higher = more likely the burst peak.

    Pulls from the same scoring signals the offline picker uses,
    but reads them out of the row dict directly so we don't need
    to re-run the analyzer:
      * score_final          (composite quality)
      * sharpness            (1 - blur)
      * face_eyes_open       (0..1)
      * face_smile           (0..1)  — only counts for portraits/wedding
      * face_no_frown        (0..1)

    Missing signals default to 0 — a frame with no face data
    doesn't get inflated peakness.
    """
    s_final = _safe_float(row.get("score_final"))
    sharp   = _safe_float(row.get("sharpness"))
    eyes    = _safe_float(row.get("face_eyes_open"), default=0.5)
    smile   = _safe_float(row.get("face_smile"))
    nofrown = _safe_float(row.get("face_no_frown"), default=0.5)
    # Weighted sum — same shape as scoring/burst_peak.py defaults,
    # capped to keep the math friendly across scene families.
    return (
        0.45 * s_final
        + 0.20 * sharp
        + 0.15 * eyes
        + 0.10 * smile
        + 0.10 * nofrown
    )


def rerank_cluster(cluster: list[dict]) -> list[dict]:
    """Mark exactly one row in the cluster as ``is_burst_peak=True``.

    Returns a new list of row dicts (defensive copies) so the
    caller can write them back to scores.csv without aliasing
    the originals.  Singleton clusters get the peak flag too —
    a 1-photo "burst" is trivially its own peak.
    """
    if not cluster:
        return []
    scored = [(_peakness_score(r), i) for i, r in enumerate(cluster)]
    # Break ties toward the LATEST frame (higher i) — when two
    # frames score identically, the photographer probably wanted
    # the moment they paused on.
    best_idx = max(scored, key=lambda kv: (kv[0], kv[1]))[1]
    out: list[dict] = []
    for i, r in enumerate(cluster):
        new = dict(r)
        new["is_burst_peak"] = (i == best_idx)
        out.append(new)
    return out


def update_burst_peaks(
    recent_rows: list[dict],
    *,
    window: int = WINDOW_SIZE,
    gap_s: float = BURST_GAP_S,
) -> list[dict]:
    """Re-evaluate the burst peaks across the last ``window`` rows.

    Pipeline:
      1. Take the trailing ``window`` rows
      2. Cluster them by mtime + scene
      3. Re-rank each cluster, setting exactly one is_burst_peak=True per

    Returns the same trailing window with is_burst_peak refreshed.
    Caller is responsible for diffing this against scores.csv and
    writing back the changed flags.  Rows outside the window are
    not affected — bursts that happened > window-rows ago are
    already frozen.
    """
    if not recent_rows:
        return []
    window_rows = recent_rows[-window:]
    out: list[dict] = []
    for cl in cluster_recent(window_rows, gap_s=gap_s):
        out.extend(rerank_cluster(cl))
    return out
