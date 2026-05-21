"""P-AI-5 — motion-aware burst peak picker.

Sports + wildlife photographers fire 8-15 fps bursts.  At 15 fps a
basketball jump shot is 12 frames; only 1-2 are the peak — moment
of contact, apex of the jump, eye open.  Today PixCull groups the
burst (V0.8 duplicate detector → cluster_id) but leaves the user
to pick the winner inside the cluster.  For a 1500-photo wedding
that's 100+ bursts × 2 minutes of click-comparison = 200 minutes
wasted on choices PixCull can make.

This module picks the peak frame automatically using metrics the
pipeline already computes:

  · score_sharpness        — fused sharpness (V18 rubric)
  · embedding              — CLIP image vector
  · face_bboxes            — count + position
  · score_final            — overall rubric quality
  · cluster_id             — already attached by V0.8 duplicate detector

Picking heuristic (all weighted z-scores within the cluster so a
"sharp" burst is judged against itself, not against the whole
event):

  peak_score = 0.40 * sharpness_z
             + 0.30 * embedding_distinctness_z
             + 0.20 * score_final
             + 0.10 * face_evidence

where:
  embedding_distinctness = cosine distance from cluster centroid
                           (a frame in a near-identical burst gets
                           a small distance; the "apex" frame
                           that's visually different gets a big
                           one — proxying for "moment of peak
                           action")
  face_evidence          = 0.15 per face up to cap 1.0; absent
                           faces don't penalize bird/wildlife
                           bursts because score_sharpness already
                           caps the influence

The module is intentionally pure-Python (numpy only when an
embedding list is given) so it can run in the admin UI without
torch loaded, against rows loaded from a CSV/JSONL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Optional


@dataclass
class BurstPeakWeights:
    """Tuneable knobs for the peak-score blend.

    Default weights were re-tuned in P-AI-5.2 against 13 real wedding
    bursts (3-11 frames each, 80 photos total) cross-referenced
    against the photographer's curated cut.  Findings:

      · Exact agreement with the photographer's pick is hopeless
        without face / expression signals — flat at 15% regardless
        of weight blend, because wedding-photographer picks are
        driven by eyes-open / smile / emotion, not visual
        distinctness or sharpness.
      · Sharp-dominant (0.70) achieved the best "close enough"
        rate: 54% within 1 frame of the photographer's pick, 85%
        within 3.  In practice this turns a 6-frame burst into a
        2-frame A/B for the photographer — still a 3× speedup.
      · Distinctness-dominant performed WORST: within a 1-2 second
        burst frames are visually almost identical, so the
        distinctness signal is near-zero across all candidates.

    Until P-AI-5.3 adds face EAR / smile / expression signals,
    these are the best blind weights we have.
    """
    sharpness:    float = 0.70   # bumped from 0.40 — see docstring
    distinctness: float = 0.20   # cut from 0.30
    quality:      float = 0.05   # cut from 0.20 (score_final missing
                                  # for most rows in the tuning corpus
                                  # — leans back when face signals land
                                  # in P-AI-5.3)
    face:         float = 0.05


DEFAULT_WEIGHTS = BurstPeakWeights()
FACE_EVIDENCE_PER_FACE = 0.15
FACE_EVIDENCE_CAP      = 1.0


@dataclass
class BurstPeakResult:
    """Outcome of running rank_burst_peak() on a cluster."""
    winner_filename: Optional[str]
    winner_idx:      int
    ranking:         list[tuple[str, float]]   # [(filename, score), …] desc
    reasons:         dict[str, str]            # filename → why it scored

    @property
    def has_winner(self) -> bool:
        return self.winner_filename is not None


def _z_score(value: float, mean: float, std: float) -> float:
    if std <= 1e-9:
        return 0.0
    return (value - mean) / std


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """1 − cosine_similarity. Numpy-free for portability."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sqrt(sum(x * x for x in a))
    nb = sqrt(sum(x * x for x in b))
    if na <= 1e-9 or nb <= 1e-9:
        return 0.0
    sim = dot / (na * nb)
    return 1.0 - sim


def _vector_mean(vecs: list[list[float]]) -> list[float]:
    if not vecs:
        return []
    n = len(vecs)
    d = len(vecs[0])
    out = [0.0] * d
    for v in vecs:
        for i in range(min(d, len(v))):
            out[i] += v[i]
    return [x / n for x in out]


def _face_evidence(row: dict) -> float:
    bb = row.get("face_bboxes") or []
    n = len(bb) if isinstance(bb, list) else 0
    return min(FACE_EVIDENCE_CAP, n * FACE_EVIDENCE_PER_FACE)


def rank_burst_peak(
    rows: list[dict],
    weights: BurstPeakWeights = DEFAULT_WEIGHTS,
) -> BurstPeakResult:
    """Pick the peak-action frame within a burst cluster.

    Each row should carry: filename (required), score_sharpness,
    score_final, embedding, face_bboxes.  Missing fields fall back
    to 0.0 / [] so partial data doesn't crash the picker.

    Single-frame clusters return that frame as the winner with
    a "single frame in burst" reason.  Empty input returns a
    no-winner result (caller should special-case).
    """
    if not rows:
        return BurstPeakResult(None, -1, [], {})
    if len(rows) == 1:
        fn = str(rows[0].get("filename") or "?")
        return BurstPeakResult(
            fn, 0, [(fn, 1.0)], {fn: "唯一帧 — 自动入选"}
        )

    # 1. Cluster-internal statistics for z-scoring
    sharps = [float(r.get("score_sharpness") or 0.0) for r in rows]
    s_mean = sum(sharps) / len(sharps)
    s_var  = sum((x - s_mean) ** 2 for x in sharps) / len(sharps)
    s_std  = sqrt(s_var)

    # 2. Embedding centroid (skipping rows missing embeddings)
    embs = [r.get("embedding") for r in rows]
    embs_clean = [list(e) for e in embs if isinstance(e, list) and e]
    centroid = _vector_mean(embs_clean) if embs_clean else []

    distinct = []
    for emb in embs:
        if isinstance(emb, list) and emb and centroid:
            distinct.append(_cosine_distance(emb, centroid))
        else:
            distinct.append(0.0)
    d_mean = (sum(distinct) / len(distinct)) if distinct else 0.0
    d_var  = sum((x - d_mean) ** 2 for x in distinct) / len(distinct) \
             if distinct else 0.0
    d_std  = sqrt(d_var)

    # 3. Score each row + remember the dominant component for the
    #    explanation string
    scored: list[tuple[int, str, float, str]] = []
    for i, r in enumerate(rows):
        fn = str(r.get("filename") or f"row_{i}")
        sharp_z = _z_score(sharps[i], s_mean, s_std)
        dist_z  = _z_score(distinct[i], d_mean, d_std)
        qual    = float(r.get("score_final") or 0.0)
        face_e  = _face_evidence(r)

        s = (weights.sharpness    * sharp_z
             + weights.distinctness * dist_z
             + weights.quality      * qual
             + weights.face         * face_e)

        # Pick the dominant component for the human reason
        contribs = [
            ("最锐 — 簇内 +%.1fσ 锐度" % sharp_z, weights.sharpness * sharp_z),
            ("姿态/动作差异最大 — 簇内 +%.1fσ" % dist_z,
             weights.distinctness * dist_z),
            ("综合分高 (%.2f)" % qual,             weights.quality * qual),
            ("有人脸 (%d 张)" % len(r.get("face_bboxes") or []),
             weights.face * face_e),
        ]
        contribs.sort(key=lambda kv: kv[1], reverse=True)
        reason = contribs[0][0] if contribs[0][1] > 0 else "簇内默认"

        scored.append((i, fn, s, reason))

    # 4. Sort descending; ties broken by score_final, then by
    #    filename for deterministic output
    scored.sort(key=lambda t: (
        -t[2],
        -float(rows[t[0]].get("score_final") or 0.0),
        t[1],
    ))

    winner = scored[0]
    return BurstPeakResult(
        winner_filename=winner[1],
        winner_idx=winner[0],
        ranking=[(t[1], round(t[2], 4)) for t in scored],
        reasons={t[1]: t[3] for t in scored},
    )


def rank_clusters(
    rows: list[dict],
    cluster_field: str = "cluster_id",
    weights: BurstPeakWeights = DEFAULT_WEIGHTS,
) -> dict[str, BurstPeakResult]:
    """Apply rank_burst_peak() to every cluster_id present.

    Returns {cluster_id_str: BurstPeakResult}. Rows with a missing
    or None cluster_id are skipped (they aren't part of any burst).
    """
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        cid = r.get(cluster_field)
        if cid is None or cid == "":
            continue
        buckets.setdefault(str(cid), []).append(r)

    return {cid: rank_burst_peak(group, weights) for cid, group in buckets.items()}
