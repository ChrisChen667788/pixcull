"""v0.7-P2-1 — style-clone V1 core.

Takes a list of reference rows (from scores.csv) and produces a
``StyleProfile`` capturing the user's keep-style fingerprint.
Given that profile + a candidate row, returns a distance in
[0, 1] where 0 means "indistinguishable from your style" and 1
means "couldn't be further".

Why median (not mean):
  Pros tend to pick a tight, recognizable style.  The median is
  robust to one outlier reference (a single off-style photo the
  user dropped into their favorites by accident shouldn't shift
  the whole profile).

Why no learned weights in V1:
  Logistic regression on 6 axes from 5-20 references over-fits
  trivially (Wald approximation has more parameters than data).
  A median-based profile + uniform-weight distance is the right
  V1 — simple, interpretable, no NaN-trap edge cases.

V2 (v0.8 plan):
  - CLIP embedding centroid + cosine distance, blended with the
    axis-MAD signal at a learned ratio
  - Per-axis variance (so we down-weight axes the user is
    indifferent to)
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping, Sequence

# Six rubric axes that drive the distance metric. These are the
# core "what makes a photo good" dimensions PixCull already scores
# every row on; reusing them means no new feature engineering and
# every photo with axis stars (~all of them) gets a distance for
# free.
AXIS_NAMES: tuple[str, ...] = (
    "technical", "subject", "composition", "light", "moment", "aesthetic",
)

# Each axis's value lives at row["rubric_<axis>_stars"]. The
# scores.csv column type is float-stringified; the loader below
# tolerates None / "" / non-numeric and treats those as "unknown"
# (the axis is dropped from the median computation, not zero-ed,
# so a row with one missing star isn't pushed toward the cull
# tier).
_AXIS_COLS: tuple[str, ...] = tuple(f"rubric_{a}_stars" for a in AXIS_NAMES)

# Maximum star value PixCull emits today. The distance metric
# normalises differences to [0, 1] by dividing by this so axis
# disagreement of 5 stars (max possible) maps to distance 1.0.
_STAR_MAX: float = 5.0

# How much a scene mismatch costs.  Scene is a coarse categorical
# signal ("portrait" vs "landscape"); we add at most ``_SCENE_PENALTY``
# to the average-axis distance when the candidate's scene doesn't
# match any of the references' scenes.  Kept small so axis distance
# still dominates — scene mismatch alone shouldn't disqualify a
# photo if the rubric agrees.
_SCENE_PENALTY: float = 0.15


# --- helpers ---------------------------------------------------------------


def _as_float(v):
    """Convert v to float, treating empty / None / non-numeric as None.

    scores.csv columns are stringly-typed; this gives us a
    one-call cleanup that matches the loader semantics elsewhere
    in pixcull/.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None  # NaN check
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _median(xs: Sequence[float]) -> float | None:
    """Median of a non-empty sequence, or None when xs is empty.

    Plain sorted-middle; we don't need numpy here and avoiding the
    dependency keeps style-clone runnable in minimal environments
    (CI containers, the Docker image's slim variant, etc.).
    """
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


# --- public API ------------------------------------------------------------


def learn_style_profile(
    refs: Iterable[Mapping[str, object]],
) -> dict:
    """Build a StyleProfile from the user's hand-picked references.

    Parameters
    ----------
    refs
        Iterable of row dicts (from scores.csv).  Each row should
        carry ``rubric_<axis>_stars`` for at least *some* axes and
        a ``scene`` string.  Rows with no axis data at all are
        silently dropped (they contribute nothing to the median).

    Returns
    -------
    profile dict
        ``{
            "schema":     "pixcull.style_profile/v1",
            "n_refs":     int,           # how many refs contributed
            "axis_median": {axis: float},# per-axis median, ∈ [0,5]
            "scene_modes": {scene: int}, # scene → ref count
            "scenes_total": int,         # total scene labels seen
        }``

        Profiles whose ``n_refs`` is 0 are valid and round-trippable
        but every distance against them is 1.0 (we treat an empty
        profile as "no style preference learned yet").
    """
    refs_list = list(refs)
    # Collect per-axis arrays + scene labels
    by_axis: dict[str, list[float]] = {a: [] for a in AXIS_NAMES}
    scene_counts: Counter[str] = Counter()
    n_contributed = 0
    for r in refs_list:
        any_axis = False
        for axis, col in zip(AXIS_NAMES, _AXIS_COLS):
            v = _as_float(r.get(col))
            if v is None:
                continue
            # Clamp to [0, _STAR_MAX] — older rows occasionally have
            # 5.1 / 4.95 due to fuse_score rounding; not a hard
            # error, just clip.
            by_axis[axis].append(max(0.0, min(_STAR_MAX, v)))
            any_axis = True
        scene = r.get("scene")
        if isinstance(scene, str) and scene.strip():
            scene_counts[scene.strip()] += 1
        if any_axis:
            n_contributed += 1
    axis_median: dict[str, float] = {}
    for axis, vals in by_axis.items():
        med = _median(vals)
        if med is not None:
            axis_median[axis] = round(float(med), 3)
    return {
        "schema":      "pixcull.style_profile/v1",
        "n_refs":      n_contributed,
        "axis_median": axis_median,
        "scene_modes": dict(scene_counts),
        "scenes_total": int(sum(scene_counts.values())),
    }


def style_distance(
    row: Mapping[str, object], profile: Mapping[str, object]
) -> float:
    """Distance ∈ [0, 1] from row to the learned profile.

    Definitions
    -----------
    * Axis distance: for each axis present in BOTH the row and the
      profile, ``|row.axis - profile.axis| / _STAR_MAX``. The
      per-row score is the mean across those axes.
    * Scene mismatch: if the row's scene isn't in the profile's
      scene_modes at all, add ``_SCENE_PENALTY``.  Within-profile
      scenes contribute 0 regardless of frequency — V1 only
      penalises totally-unseen scenes, not under-represented ones
      (sample sizes are too small to read into proportions).

    Returns
    -------
    float in [0, 1].
    """
    if not profile or not profile.get("n_refs"):
        return 1.0
    medians = profile.get("axis_median") or {}
    if not isinstance(medians, Mapping):
        medians = {}
    diffs: list[float] = []
    for axis, col in zip(AXIS_NAMES, _AXIS_COLS):
        if axis not in medians:
            continue
        v = _as_float(row.get(col))
        if v is None:
            continue
        ref = float(medians[axis])
        diffs.append(abs(v - ref) / _STAR_MAX)
    if not diffs:
        # No overlapping axes — can't compute, treat as max distance.
        return 1.0
    base = sum(diffs) / len(diffs)
    # Scene penalty
    scene = row.get("scene")
    scene_modes = profile.get("scene_modes") or {}
    if isinstance(scene_modes, Mapping):
        if isinstance(scene, str) and scene.strip():
            if scene.strip() not in scene_modes:
                base += _SCENE_PENALTY
        else:
            # Missing scene → treat as mismatch, but only at half
            # the full penalty (less information, less punishment).
            base += _SCENE_PENALTY / 2
    return max(0.0, min(1.0, base))


def compute_distances(
    rows: Iterable[Mapping[str, object]],
    profile: Mapping[str, object],
) -> dict[str, float]:
    """Convenience: {filename: style_distance} for every row.

    Rows without a usable ``filename`` are skipped.  Distances are
    rounded to 3 decimals so the resulting JSON file is compact
    and diffs cleanly under version control.
    """
    out: dict[str, float] = {}
    for r in rows:
        fn = r.get("filename")
        if not isinstance(fn, str) or not fn:
            continue
        out[fn] = round(style_distance(r, profile), 3)
    return out
