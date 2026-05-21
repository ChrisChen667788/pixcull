"""P-AI-4 — cross-run face library quality audit.

V22.x built a per-user face library with up to 16 centroids per
labeled identity ("Alice" has 16 representative ArcFace vectors
across all her runs). That's enough recall for "is this Alice"
suggestions on a new cluster, but nothing yet TELLS the operator
how healthy the library is:

  · Has Alice fragmented? If we labeled her in 5 runs but every
    run hit different lighting and she now has 14 / 16 slots
    used, the label suggester will SILENTLY drop a 15th
    appearance.
  · Has a cluster been polluted? If a wedding photographer
    accepted a bad suggestion for "Bob", Bob's centroids now
    include a few photos of "Carl"; subsequent suggestions
    drift.  Detectable via pairwise similarity inside the
    cluster.
  · Is cross-run continuity dropping? Run A labeled 80% of
    faces.  Run B in the same venue suggested labels for only
    40%.  Something — lighting? new haircuts? algorithm? — is
    breaking the match.  Worth flagging.

This module provides the pure-Python audits — numpy-free so
they can run inside the admin web UI without torch / numpy
loaded, against centroid lists deserialized from the existing
.npz library snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Iterable, Optional


# Threshold below which two members of a cluster are considered
# "suspicious" — i.e. the cluster might have mixed identities.
# Chosen empirically: ArcFace cosine sim between the same person
# under different lighting is typically 0.55 - 0.75; between
# different people it drops below 0.30.  Picking 0.45 as the
# "outlier" floor catches mixed-identity leaks while leaving
# headroom for the lighting/expression noise within a true
# single-identity cluster.
CLUSTER_PAIR_OUTLIER_SIM: float = 0.45

# A label with >= this many accumulated centroids is "fragmented"
# — the library is approaching its 16-slot cap.
LIBRARY_FRAGMENT_FLOOR: int = 14


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity, numpy-free.  Returns 0.0 for degenerate
    inputs (mismatched lengths, zero vectors) instead of NaN."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sqrt(sum(x * x for x in a))
    nb = sqrt(sum(x * x for x in b))
    if na <= 1e-9 or nb <= 1e-9:
        return 0.0
    return dot / (na * nb)


@dataclass
class ClusterPrecisionReport:
    """Pairwise-similarity health check for one cluster."""
    cluster_id: object
    n_members:  int
    min_pair_sim: float = 1.0
    mean_pair_sim: float = 1.0
    outlier_indices: list[int] = field(default_factory=list)
    polluted: bool = False

    @property
    def healthy(self) -> bool:
        return not self.polluted


def cluster_precision_audit(
    embeddings: list[list[float]],
    cluster_id: object = None,
    outlier_threshold: float = CLUSTER_PAIR_OUTLIER_SIM,
) -> ClusterPrecisionReport:
    """Run pairwise similarity on every (a, b) inside a cluster.

    Returns the min + mean similarity + the indices of members
    that look like outliers (members whose mean similarity to
    every other member is below the threshold).  A cluster with
    fewer than 2 members is trivially healthy.
    """
    n = len(embeddings)
    if n < 2:
        return ClusterPrecisionReport(cluster_id, n, 1.0, 1.0, [], False)

    # Build pair sim matrix; remember each member's per-row list
    # of sims-with-others so we can take the MEDIAN.  Median is
    # the right aggregator here — with mean, a single intruder
    # drags down every legit member's average and the audit flags
    # the whole cluster.  Median ignores the one bad sample.
    pair_sims: list[float] = []
    per_member_sims: list[list[float]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            s = _cosine_sim(embeddings[i], embeddings[j])
            pair_sims.append(s)
            per_member_sims[i].append(s)
            per_member_sims[j].append(s)

    min_s = min(pair_sims) if pair_sims else 1.0
    mean_s = (sum(pair_sims) / len(pair_sims)) if pair_sims else 1.0

    def _median(xs: list[float]) -> float:
        if not xs:
            return 1.0
        ys = sorted(xs)
        m = len(ys)
        return ys[m // 2] if m % 2 else 0.5 * (ys[m // 2 - 1] + ys[m // 2])

    # An outlier is a member whose MEDIAN similarity to the
    # rest is below the threshold.  A legit member with one
    # bad pair (e.g. matched-but-noisy) still has median sim
    # ≈ 1.0 from its remaining neighbors; the intruder's median
    # is uniformly low.
    outliers: list[int] = []
    for i in range(n):
        if _median(per_member_sims[i]) < outlier_threshold:
            outliers.append(i)

    return ClusterPrecisionReport(
        cluster_id=cluster_id,
        n_members=n,
        min_pair_sim=min_s,
        mean_pair_sim=mean_s,
        outlier_indices=outliers,
        polluted=bool(outliers),
    )


@dataclass
class LibraryFragmentReport:
    """Per-label "are we running out of slots?" audit."""
    label:        str
    n_centroids:  int
    fragmented:   bool


def library_fragmentation_audit(
    centroids_per_label: dict[str, list[list[float]]],
    fragment_floor: int = LIBRARY_FRAGMENT_FLOOR,
) -> list[LibraryFragmentReport]:
    """One report per label, sorted by n_centroids descending."""
    reports = []
    for label, vecs in centroids_per_label.items():
        n = len(vecs)
        reports.append(LibraryFragmentReport(
            label=label,
            n_centroids=n,
            fragmented=(n >= fragment_floor),
        ))
    reports.sort(key=lambda r: r.n_centroids, reverse=True)
    return reports


@dataclass
class CrossRunContinuityReport:
    """% of this run's clusters that linked to a known identity."""
    n_current_clusters:    int
    n_matched_to_library:  int
    @property
    def match_rate(self) -> float:
        if self.n_current_clusters == 0:
            return 0.0
        return round(100.0 * self.n_matched_to_library
                     / self.n_current_clusters, 1)


def cross_run_continuity_audit(
    current_centroids: list[list[float]],
    library_centroids: list[list[float]],
    match_threshold: float = 0.50,
) -> CrossRunContinuityReport:
    """For each cluster centroid in the current run, check whether
    SOME library centroid is within match_threshold.

    Returns the match rate — a drop run-over-run is the signal that
    something (lighting, hairstyle, algorithm change) is breaking
    cross-run identity continuity.
    """
    if not current_centroids:
        return CrossRunContinuityReport(0, 0)
    matched = 0
    for cur in current_centroids:
        for lib in library_centroids:
            if _cosine_sim(cur, lib) >= match_threshold:
                matched += 1
                break
    return CrossRunContinuityReport(
        n_current_clusters=len(current_centroids),
        n_matched_to_library=matched,
    )
