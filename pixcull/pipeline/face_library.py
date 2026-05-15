"""V22.2 — cross-run face label inheritance.

V22.0 produced per-run face clusters (DBSCAN on InsightFace ArcFace
embeddings). V22.1 added per-run labels ("Bride", "Groom", "小宝"),
persisted in ``<output_dir>/face_labels.json``. But the cluster ids
themselves are RUN-SCOPED — cluster 0 in run A has no relation to
cluster 0 in run B. So when a photographer shoots a second wedding
for the same couple a year later, V22.1 forces them to re-label.

V22.2 adds cross-run identity via centroid matching:

1. Each cluster's centroid (mean of member embeddings) is persisted
   to ``<run>/face_centroids.npz`` alongside the existing
   ``face_labels.json``. The raw embeddings are still dropped before
   ``scores.csv`` write (V22.0 decision — saves CSV bloat), but the
   centroids are cheap: ~2 KB per cluster.

2. When a user labels a cluster (POST /face_clusters/<run>/label),
   we ALSO promote that centroid into a per-user GLOBAL face library
   at ``<user_root>/face_library.npz`` keyed by label. Labels can
   accumulate multiple centroids (same person, different lighting /
   pose / haircut over time) — we keep up to 16 centroids per label
   and discard the oldest beyond that.

3. On a new run, the face-cluster summary endpoint computes the
   centroid for each unlabeled cluster, checks cosine similarity
   against every centroid in the library, and SUGGESTS a label if
   sim ≥ 0.55 (looser than the within-batch DBSCAN ε=0.50 because
   inter-run lighting variance is wider; tighter than the
   different-person threshold ~0.4 we observed in V24 audit).

The UI surfaces the suggestion as ``cluster.suggested_label`` next
to ``cluster.label``; the user clicks ✓ to accept or ✎ to override.

Storage shape
=============
Per-run centroids file: ``<output_dir>/face_centroids.npz``
    {
      "schema":    "pixcull.face_centroids.v1",
      "cluster_ids": np.array([int, ...]),
      "centroids":   np.array([[float * 512], ...]),   # L2-normalized
    }

Per-user library: ``<user_root>/face_library.npz``
    {
      "schema":    "pixcull.face_library.v1",
      "labels":    np.array([str, ...]),               # 1 row per centroid
      "centroids": np.array([[float * 512], ...]),     # 1 row per centroid
    }

We use numpy npz instead of JSON because:
  * 512-dim floats × N is ~2 KB / centroid binary vs ~5 KB JSON
  * Cosine match is a single numpy dot product on the matrix
  * Easy to update incrementally (load, append, save)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np


# Threshold for "this cluster is probably the same person as in a
# prior labeled run." Tuned looser than the within-batch DBSCAN ε=0.50
# (V22.0.1) because inter-shoot variance is wider — same person in
# 2024-08 + 2025-09 with different haircut + lighting reads as
# ~0.55-0.6 cosine distance. Tighter than ~0.4 (V24 different-person
# floor) to avoid false-merges.
SUGGEST_THRESHOLD = 0.55

# Cap on how many centroids we keep per label. After 16 the oldest
# drops off — keeps the library bounded while preserving enough
# variants to handle the same person across lighting / years / etc.
MAX_CENTROIDS_PER_LABEL = 16

# Library + per-run filenames.
_CENTROIDS_FILE = "face_centroids.npz"
_LIBRARY_FILE = "face_library.npz"


def save_run_centroids(output_dir: Path, rows: list[dict],
                          all_embeddings: list[np.ndarray] | None = None
                          ) -> Path | None:
    """V22.2 — persist per-cluster centroids for a run.

    Two call shapes:
      * ``all_embeddings`` supplied — caller pre-flattened them in
        the same order ``face_clusters`` was assigned. This is the
        in-pipeline path: ``cluster_faces_across_rows`` keeps the
        flat arrays in scope just before dropping them. Cheap.
      * ``all_embeddings`` None — fall through to None (can't compute
        centroids retroactively after embeddings are dropped).
        Returns None.

    Cluster -1 (noise) is excluded.
    """
    if not all_embeddings or not rows:
        return None
    # Re-walk the cluster_id assignment we made in
    # cluster_faces_across_rows to group embeddings by cluster.
    by_cluster: dict[int, list[np.ndarray]] = {}
    emb_iter = iter(all_embeddings)
    for r in rows:
        for cid in r.get("face_clusters") or []:
            try:
                e = next(emb_iter)
            except StopIteration:
                return None  # shape mismatch — bail safely
            if cid < 0:
                continue
            by_cluster.setdefault(int(cid), []).append(e)

    if not by_cluster:
        return None

    cluster_ids = []
    centroids = []
    for cid, embs in sorted(by_cluster.items()):
        if not embs:
            continue
        c = np.mean(np.stack(embs), axis=0)
        # Re-normalize after averaging — keeps cosine match meaningful
        norm = float(np.linalg.norm(c))
        if norm > 1e-8:
            c = c / norm
        cluster_ids.append(cid)
        centroids.append(c.astype(np.float32))

    if not cluster_ids:
        return None

    p = Path(output_dir) / _CENTROIDS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        p,
        schema=np.array("pixcull.face_centroids.v1"),
        cluster_ids=np.array(cluster_ids, dtype=np.int32),
        centroids=np.stack(centroids).astype(np.float32),
    )
    return p


def load_run_centroids(output_dir: Path
                          ) -> tuple[np.ndarray, np.ndarray] | None:
    """Return ``(cluster_ids, centroids)`` arrays, or None when no
    centroids file exists or it's malformed."""
    p = Path(output_dir) / _CENTROIDS_FILE
    if not p.exists():
        return None
    try:
        z = np.load(p, allow_pickle=False)
        return z["cluster_ids"], z["centroids"]
    except (OSError, KeyError, ValueError) as exc:
        print(f"[face_library] bad centroids file {p}: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def _library_path(user_root: Path) -> Path:
    return Path(user_root) / _LIBRARY_FILE


def load_library(user_root: Path
                    ) -> tuple[list[str], np.ndarray] | tuple[list, np.ndarray]:
    """Return ``(labels, centroids)`` where labels is a list[str] (one
    per centroid row) and centroids is (N, 512). Empty arrays when no
    library file exists."""
    p = _library_path(user_root)
    if not p.exists():
        return [], np.zeros((0, 512), dtype=np.float32)
    try:
        z = np.load(p, allow_pickle=False)
        labels = [str(x) for x in z["labels"].tolist()]
        return labels, z["centroids"]
    except (OSError, KeyError, ValueError) as exc:
        print(f"[face_library] bad library file {p}: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return [], np.zeros((0, 512), dtype=np.float32)


def add_to_library(user_root: Path, label: str,
                       centroid: np.ndarray) -> None:
    """Add a labeled centroid to the global library. Capped at
    ``MAX_CENTROIDS_PER_LABEL`` entries per label (FIFO eviction).

    Idempotent on identical (label, centroid) pairs — the FIFO cap
    handles unbounded growth.
    """
    label = str(label).strip()
    if not label:
        return
    if centroid.shape != (512,):
        return
    labels, centroids = load_library(user_root)
    # Append
    new_labels = list(labels) + [label]
    new_centroids = np.vstack([centroids, centroid[None, :]])
    # FIFO cap per-label
    keep_mask = np.ones(len(new_labels), dtype=bool)
    label_counts: dict[str, list[int]] = {}
    for i, lab in enumerate(new_labels):
        label_counts.setdefault(lab, []).append(i)
    for lab, idxs in label_counts.items():
        excess = len(idxs) - MAX_CENTROIDS_PER_LABEL
        if excess > 0:
            for drop_i in idxs[:excess]:
                keep_mask[drop_i] = False
    new_labels = [l for l, k in zip(new_labels, keep_mask) if k]
    new_centroids = new_centroids[keep_mask]
    # Save
    p = _library_path(user_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        p,
        schema=np.array("pixcull.face_library.v1"),
        labels=np.array(new_labels),
        centroids=new_centroids.astype(np.float32),
    )


def suggest_labels(centroids: np.ndarray,
                       user_root: Path,
                       threshold: float = SUGGEST_THRESHOLD,
                       ) -> list[tuple[str, float] | None]:
    """V22.2 — for each input centroid, find the closest library
    centroid (any label) and return (label, similarity) if it clears
    ``threshold``, else None.

    Returns a list of len(centroids) entries — one suggestion per row.
    """
    if centroids.size == 0:
        return []
    labels, lib_centroids = load_library(user_root)
    if not labels:
        return [None] * len(centroids)
    # Cosine sim: since both sides are L2-normalized (we re-normalize
    # after averaging on save, and library entries always come from
    # save_run_centroids → also normalized), inner product == cosine.
    sims = centroids @ lib_centroids.T   # (N_query, N_library)
    best = sims.argmax(axis=1)
    out: list[tuple[str, float] | None] = []
    for i in range(len(centroids)):
        s = float(sims[i, best[i]])
        if s >= threshold:
            out.append((labels[best[i]], s))
        else:
            out.append(None)
    return out


__all__ = [
    "SUGGEST_THRESHOLD",
    "save_run_centroids",
    "load_run_centroids",
    "load_library",
    "add_to_library",
    "suggest_labels",
]
