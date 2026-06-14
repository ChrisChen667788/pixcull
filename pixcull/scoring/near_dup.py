"""v2.6-P1 — CLIP near-duplicate grouping (the deferred half of v2.4-P1-1).

Burst collapse folds *time-bucketed* clusters; this folds **visual**
near-duplicates regardless of capture time — the re-shot composition ten
minutes later, the second pass over the same scene.  Groups are connected
components over the pairwise cosine-similarity graph of the run's CLIP
image embeddings (the same ``embeddings.npz`` cache the semantic search
lazily builds), thresholded high enough that only true near-dups link.

Pure numpy + union-find; no model load here — callers hand in vectors.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

# Default similarity floor. CLIP ViT-B/32 cosine between two frames of
# the same composition is typically 0.93-0.99; distinct compositions of
# the same scene land 0.75-0.90. 0.92 keeps groups tight (precision over
# recall — wrongly folding two DIFFERENT photos is the costly error).
DEFAULT_THRESHOLD = 0.92


class _DSU:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, a: int) -> int:
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def group_near_dups(
    filenames: Sequence[str],
    vectors: np.ndarray,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    min_group: int = 2,
    block: int = 1024,
) -> list[list[str]]:
    """Connected components of the cosine-similarity graph ≥ ``threshold``.

    ``vectors`` is ``[N, D]`` (L2-normalised or not — normalised here for
    safety).  Pairwise similarity is computed in ``block``-row chunks so a
    5k-photo run peaks at ~``block × N`` floats instead of ``N × N``.
    Returns groups of ``min_group``+ filenames, largest first; singletons
    are dropped (nothing to fold).
    """
    n = len(filenames)
    if n == 0 or vectors.shape[0] != n:
        return []
    v = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    v = v / np.where(norms == 0, 1.0, norms)

    dsu = _DSU(n)
    for start in range(0, n, block):
        sims = v[start:start + block] @ v.T          # [block, N]
        rows, cols = np.nonzero(sims >= threshold)
        for r, c in zip(rows, cols):
            gi = start + int(r)
            if gi < c:                               # upper triangle only
                dsu.union(gi, int(c))

    groups: dict[int, list[str]] = {}
    for i in range(n):
        groups.setdefault(dsu.find(i), []).append(str(filenames[i]))
    out = [g for g in groups.values() if len(g) >= min_group]
    out.sort(key=len, reverse=True)
    return out


def pick_heroes(
    groups: Sequence[Sequence[str]],
    scores: dict[str, float] | None = None,
) -> list[dict]:
    """Attach the keep-worthy representative per group.

    Hero = highest ``score_final`` (ties / missing scores → first member,
    which preserves the run's existing sort).  Returns
    ``[{"hero": fn, "members": [fn, ...]}, ...]``.
    """
    scores = scores or {}
    out = []
    for g in groups:
        hero = max(g, key=lambda fn: (scores.get(fn) or 0.0))
        out.append({"hero": hero, "members": list(g)})
    return out
