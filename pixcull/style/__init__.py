"""v0.7-P2-1 — style-clone subsystem.

Learn a photographer's personal-style profile from a handful of
hand-picked reference photos, then score every other photo by
*style distance* — how close it sits to the learned profile.

The output is *additive*: a per-row ``style_distance`` ∈ [0, 1]
that the UI surfaces in the Inspector + as a chip on each card.
The user can then sort or filter by it to find more shots like
their references.

V1 is intentionally simple (no sklearn / no learned weights):
the profile is the per-axis median + scene mode + a global
photo-count.  Distance is the mean absolute deviation across the
six rubric axes plus a small scene-mismatch penalty.  This is
interpretable, dependency-free, and good enough for the "find
photos like my favorites" use case.

V2 (deferred to v0.8) layers on CLIP embeddings for true visual
similarity beyond axis-star summaries.
"""

from pixcull.style.clone import (
    learn_style_profile,
    style_distance,
    compute_distances,
    AXIS_NAMES,
)
# v0.8-P1-1 — V2 (CLIP embedding centroid) layered on top of V1.
from pixcull.style.clip_clone import (
    DEFAULT_LAMBDA,
    blend,
    compute_visual_distances,
    learn_visual_profile,
)

__all__ = [
    # V1 (axis-MAD)
    "learn_style_profile",
    "style_distance",
    "compute_distances",
    "AXIS_NAMES",
    # V2 (CLIP)
    "learn_visual_profile",
    "compute_visual_distances",
    "blend",
    "DEFAULT_LAMBDA",
]
