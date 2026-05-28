"""v0.8-P1-1 — style clone V2 (CLIP embedding centroid).

V1 (median-of-axes, see ``pixcull/style/clone.py``) learned the
user's style purely from rubric stars + scene labels.  V2 layers
on CLIP embeddings so the distance reflects how a photo *looks*,
not just how it scored.

Implementation
==============
Reuses the P-AI-2 ``embeddings.npz`` cache built by the semantic
search feature.  Same on-disk file (one per run), same vector
space, same model.  No new CLIP encode at train time — every
photo in the run was already encoded the first time the user ran
semantic search.

* ``learn_visual_profile(refs, embeddings)`` → centroid vector
  (L2-normalised mean of the references' embeddings).  Returns
  None when none of the refs are in the cache (cache stale or
  ref set empty).
* ``visual_distance(filename, centroid, embeddings)`` →
  ``1 - cosine(row_emb, centroid)`` in [0, 2], then clamped to
  [0, 1].  Since both vectors are unit-norm, cosine ∈ [-1, 1] →
  ``1 - cosine`` ∈ [0, 2].  We clamp the upper end to 1.0 because
  values > 1 only happen for ANTI-correlated photos (rare on
  real photo sets — usually means the cache contains noise);
  capping keeps the V1 / V2 distances on the same [0, 1] scale
  so the UI's blended display stays interpretable.

The blended distance the UI surfaces by default is:

    blended = λ * v1 + (1 - λ) * v2,   λ default = 0.3

i.e. axis-MAD signal weighed at 30%, visual signal at 70% — the
ratio the charter committed.  λ is exposed in the Inspector so
the user can tune it; the persisted distances file always carries
both raw components so re-blending is a pure client-side op.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional


# Default blend ratio shipped in the UI.  Charter:
#   blended = λ * V1 + (1-λ) * V2,  λ default = 0.3
DEFAULT_LAMBDA: float = 0.3


def _load_cache(cache_path: Path):
    """Return the embeddings cache or None when missing / unreadable.

    Importing semantic_search lazily so style-V1-only deployments
    (no numpy / no CLIP) keep working.  When numpy isn't installed,
    the import raises and we degrade gracefully (caller treats
    "no cache" same as "cache missing").
    """
    try:
        from pixcull.scoring.semantic_search import load_embeddings_cache
    except ImportError:
        return None
    return load_embeddings_cache(cache_path)


def _filename_to_index(cache: dict) -> dict:
    """Build a filename → row-index map from the cache.  Cached
    per-cache identity so repeated lookups are O(1) — the caller
    is expected to use the result for a whole batch of rows."""
    fns = cache.get("filenames") if cache else None
    if fns is None:
        return {}
    # numpy arrays of strings — iterate once
    return {str(fns[i]): i for i in range(len(fns))}


def learn_visual_profile(
    refs: Iterable[str],
    cache_path: Path,
) -> Optional[dict]:
    """Return {centroid, n_refs, dim, model} or None when CLIP cache
    isn't usable (file missing, numpy unavailable, no refs matched).

    ``refs`` is an iterable of filenames the user marked as "this
    is my style".  We project each into the cached vector space,
    average them, and re-normalise — that centroid IS the learned
    style.
    """
    import numpy as np

    cache = _load_cache(cache_path)
    if not cache:
        return None
    fn_to_idx = _filename_to_index(cache)
    if not fn_to_idx:
        return None
    rows = [fn_to_idx[fn] for fn in refs if fn in fn_to_idx]
    if not rows:
        return None
    vectors = cache["vectors"]
    sub = vectors[rows]                    # (n_refs, D)
    centroid = sub.mean(axis=0)            # (D,)
    n = float(np.linalg.norm(centroid))
    if n == 0:
        return None
    centroid = centroid / n                # re-normalise
    return {
        "schema":   "pixcull.style_profile_v2/v1",
        "centroid": centroid.tolist(),
        "n_refs":   len(rows),
        "dim":      int(centroid.shape[0]),
        "model":    cache.get("model", ""),
    }


def compute_visual_distances(
    profile: Optional[dict],
    cache_path: Path,
) -> dict:
    """Return {filename: distance ∈ [0, 1]} for every row in the
    embeddings cache.  Empty dict when no profile / no cache.

    Distance = 1 - cosine(row, centroid), then clamped to [0, 1].
    """
    if not profile or "centroid" not in profile:
        return {}
    import numpy as np

    cache = _load_cache(cache_path)
    if not cache:
        return {}
    fns = cache.get("filenames")
    vectors = cache.get("vectors")
    if fns is None or vectors is None or len(fns) == 0:
        return {}
    centroid = np.asarray(profile["centroid"], dtype=vectors.dtype)
    if centroid.shape != (vectors.shape[1],):
        # Profile was built against a different model / dim — bail.
        return {}
    # vectors and centroid are both unit-norm → dot is cosine.
    sims = vectors @ centroid              # (N,)
    dists = 1.0 - sims                     # (N,)
    # Clamp to [0, 1] — anti-correlated outliers (rare) shouldn't
    # dominate the UI scale.
    dists = np.clip(dists, 0.0, 1.0)
    return {
        str(fns[i]): float(round(float(dists[i]), 3))
        for i in range(len(fns))
    }


def blend(v1: Optional[float], v2: Optional[float],
          lam: float = DEFAULT_LAMBDA) -> Optional[float]:
    """λ * V1 + (1-λ) * V2.  Returns None when both inputs are None;
    when one is None, returns the other (graceful degradation).

    Used server-side as the canonical "blended distance" persisted
    in style_distances.json so older clients (that don't know about
    the dual-chip rendering) still see a single number that's
    visually meaningful.
    """
    if v1 is None and v2 is None:
        return None
    if v1 is None:
        return v2
    if v2 is None:
        return v1
    lam = max(0.0, min(1.0, lam))
    return round(lam * v1 + (1.0 - lam) * v2, 3)


def compute_per_ref_distances(
    target_filename: str,
    ref_filenames: Iterable[str],
    cache_path: Path,
) -> list[dict]:
    """v0.13.1 — return per-ref CLIP cosine distance for ``target``.

    For each reference in ``ref_filenames`` that's present in the
    embeddings cache, compute ``1 - cosine(target_emb, ref_emb)``
    clamped to ``[0, 1]``.  Surfaces in the Inspector's "🔭 视觉"
    chip popover so the photographer can see WHICH references drive
    the aggregate distance — not just the V2 centroid total.

    Returns a list of ``{filename, distance, rank}`` dicts sorted
    by distance (closest first).  ``rank`` is 1-based.

    Empty when:
      * The target isn't in the cache
      * No refs are in the cache
      * numpy / cache unavailable
    """
    import numpy as np

    cache = _load_cache(cache_path)
    if not cache:
        return []
    fn_to_idx = _filename_to_index(cache)
    if target_filename not in fn_to_idx:
        return []
    vectors = cache.get("vectors")
    if vectors is None or len(vectors) == 0:
        return []
    target_vec = vectors[fn_to_idx[target_filename]]
    out: list[tuple[str, float]] = []
    for ref in ref_filenames:
        if ref == target_filename:
            continue   # don't include the photo as its own ref
        if ref not in fn_to_idx:
            continue
        ref_vec = vectors[fn_to_idx[ref]]
        cosine = float(target_vec @ ref_vec)
        dist = float(np.clip(1.0 - cosine, 0.0, 1.0))
        out.append((ref, dist))
    # Sort closest first
    out.sort(key=lambda t: t[1])
    return [
        {"filename": fn, "distance": round(d, 3), "rank": i + 1}
        for i, (fn, d) in enumerate(out)
    ]


__all__ = [
    "DEFAULT_LAMBDA",
    "blend",
    "compute_per_ref_distances",
    "compute_visual_distances",
    "learn_visual_profile",
]
