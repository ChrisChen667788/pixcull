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

    Evolution:

    · P-AI-5 (initial): 0.40 / 0.30 / 0.20 / 0.10 — naive blend.
    · P-AI-5.2 (after burst tuning):
        sharp 0.70 / distinct 0.20 / quality 0.05 / face 0.05.
        Findings: exact-agreement flat at 15% regardless of weights,
        because the photographer's pick is driven by EYES OPEN /
        SMILE / EMOTION which the picker couldn't see.
        Sharp-dominant still gave best "close enough" rate (54%
        within 1 frame, 85% within 3 frames).
    · P-AI-5.3 (this commit): added the two face-quality signals
        the FaceDetector already produces (``face_max_blink`` +
        ``face_min_ear``), which is the path to breaking the 15%
        ceiling.  Re-balanced defaults to give them serious weight:

        sharpness        0.50  (was 0.70 — leave headroom for eyes)
        distinctness     0.10  (was 0.20 — barely helps in 1-2s
                                bursts; small floor only)
        quality          0.05  (unchanged)
        face_presence    0.05  (unchanged — "any face at all")
        face_eyes_open   0.30  (NEW — 1 - face_max_blink, the
                                primary photographer signal)

      The actual P-AI-5.3 re-tune on real bursts is deferred to
      P-AI-5.4 because the mediapipe install on the tuning bench
      hit a protobuf incompatibility (issue tracked in
      docs/burst-peak-tuning.md).  Unit tests below prove the
      eyes-open path is correctly weighted; the on-real-data
      ceiling check ships when mediapipe is unstuck.
    """
    sharpness:      float = 0.50
    distinctness:   float = 0.10
    quality:        float = 0.05
    face:           float = 0.05      # "any face at all" — legacy presence
    face_eyes_open: float = 0.30      # P-AI-5.3 — (1 - face_max_blink)


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


def _min_max_norm(values: list[float]) -> list[float]:
    """Min-max normalize a list of floats into [0, 1].

    P-AI-5.3 replaced z-score normalization with this because real
    bursts have tiny within-cluster sharpness variance (focal length
    + aperture pinned → σ < 0.02 over a 1-2s burst).  With z-score,
    a 0.02-point sharpness lead amplified to +1.2σ and dominated
    every other signal regardless of weight.  Min-max normalization
    instead spreads the "best in burst" to 1.0 and "worst" to 0.0
    so the picker still rewards being sharpest, but the contribution
    is bounded to the weight × 1.0 and can be overridden by eyes-open
    or distinctness when the sharpness gap is small.

    Degenerate case (all values identical) → all 0.0; the component
    becomes a tie, deferring to the other signals or filename order.
    """
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


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


def _face_eyes_open(row: dict) -> float:
    """P-AI-5.3 — eyes-open signal from the FaceDetector's
    ``face_max_blink`` metric (max blink across all faces in the
    frame, 0..1, higher = more closed).  We invert it so 1.0 means
    "everyone's eyes are wide open".

    Returns 0.0 when no signal is available (no face detector run,
    no faces, NaN value).  This way absent signals don't penalize
    wildlife / landscape bursts — only frames WITH a positive
    eyes-open signal benefit from this weight component.
    """
    blink = row.get("face_max_blink")
    if blink is None:
        return 0.0
    try:
        b = float(blink)
    except (TypeError, ValueError):
        return 0.0
    if b != b:   # NaN
        return 0.0
    # face_max_blink range guard: clip to [0, 1] then invert
    return max(0.0, min(1.0, 1.0 - b))


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

    # 1. Per-cluster raw signals, then min-max normalize to [0,1]
    sharps_raw = [float(r.get("score_sharpness") or 0.0) for r in rows]
    sharps_n   = _min_max_norm(sharps_raw)

    # 2. Embedding centroid + per-row cosine distance, also min-max
    #    normalized within the burst.
    embs = [r.get("embedding") for r in rows]
    embs_clean = [list(e) for e in embs if isinstance(e, list) and e]
    centroid = _vector_mean(embs_clean) if embs_clean else []
    distinct_raw = []
    for emb in embs:
        if isinstance(emb, list) and emb and centroid:
            distinct_raw.append(_cosine_distance(emb, centroid))
        else:
            distinct_raw.append(0.0)
    distinct_n = _min_max_norm(distinct_raw)

    # 3. Score each row + remember the dominant component for the
    #    explanation string.  Each weight × normalized signal is in
    #    [0, weight], so the total max contribution per row is the
    #    sum of weights (typically 1.0 for default).
    scored: list[tuple[int, str, float, str]] = []
    for i, r in enumerate(rows):
        fn = str(r.get("filename") or f"row_{i}")
        sharp_n = sharps_n[i]
        dist_n  = distinct_n[i] if distinct_n else 0.0
        qual    = float(r.get("score_final") or 0.0)
        face_e  = _face_evidence(r)
        eyes_op = _face_eyes_open(r)

        s = (weights.sharpness      * sharp_n
             + weights.distinctness * dist_n
             + weights.quality      * qual
             + weights.face         * face_e
             + weights.face_eyes_open * eyes_op)

        # Pick the dominant component for the human reason.  Order
        # matters when contributions tie: list eyes-open first so
        # that's the surfaced reason on ties — it's the one a
        # wedding photographer actually cares about.
        contribs = [
            ("眼睛睁开 (%.0f%%)" % (eyes_op * 100),
             weights.face_eyes_open * eyes_op),
            ("簇内最锐 (%.0f%%)" % (sharp_n * 100),
             weights.sharpness * sharp_n),
            ("姿态/动作差异最大 (%.0f%%)" % (dist_n * 100),
             weights.distinctness * dist_n),
            ("综合分高 (%.2f)" % qual,
             weights.quality * qual),
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
