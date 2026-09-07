"""v3.19 — "deliver 400 selects", as an instruction the tool can take.

Event work is contracted in counts.  PixCull has three strictness presets
and a personal shift, and every one of them moves a THRESHOLD.  A
threshold is blind to set size: the same preset yields wildly different
counts on a 300-frame shoot and a 3,000-frame one, so there is no
portable setting that reliably lands on a number.  The photographer's
alternative is re-running a 2,000-frame shoot and guessing again.

WHAT A TARGET-COUNT KEEP IS NOT

It is not the same claim as a threshold keep.  A threshold keep says
"this frame cleared the bar".  A target-count keep says "this frame was
in the top N of what you shot", which on a bad afternoon can be true of a
frame the rubric rejected.

So the pass never rewrites `score_final`, and it marks every decision it
changed.  A report that showed the two as the same thing would be telling
the photographer their contracted 400 all cleared the bar, on a shoot
where 250 did.

TIES

Frames tied at the boundary are all promoted, so the result can exceed N.
Choosing between two frames the scorer called identical, by filename or
by row order, would be a decision presented as a measurement.  The pass
says how many and why rather than breaking the tie.
"""
from __future__ import annotations

from typing import Any

#: Column marking a decision this pass changed, and from what.
#: Absent (None) on every frame the pass did not touch.
SOURCE_COL = "target_count_source"

#: What the frame was before the pass promoted or demoted it.
PRIOR_COL = "target_count_prior"


def _rank_key(row: dict[str, Any]) -> tuple:
    """Best first. Score, then the learned head, then filename.

    The filename term is not a quality signal — it exists so two runs
    over the same shoot produce the same list. Without it the boundary
    would wander between runs for no reason the photographer could see.
    """
    def _f(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return float("-inf")
        return f if f == f else float("-inf")     # NaN sorts last
    return (-_f(row.get("score_final")),
            -_f(row.get("rescorer_prob_keep")),
            str(row.get("filename") or ""))


def plan(rows: list[dict[str, Any]], target: int) -> dict[str, Any]:
    """Which frames a target of ``target`` keeps, without touching scores.

    Returns the filenames to keep, the ones to demote, and how many extra
    frames the boundary tie carried in. Pure: the caller applies it.
    """
    target = max(0, int(target))
    ordered = sorted(rows, key=_rank_key)
    n = len(ordered)
    if target >= n:
        # Asking for more than the shoot has is not an error — it is a
        # photographer who over-delivers. Everything is kept and the
        # shortfall is reported rather than silently met.
        return {
            "keep": [str(r.get("filename")) for r in ordered],
            "demote": [],
            "target": target,
            "n": n,
            "ties_at_boundary": 0,
            "short_by": target - n,
        }

    cut = _rank_key(ordered[target - 1]) if target else None
    keep, demote, ties = [], [], 0
    for i, r in enumerate(ordered):
        fn = str(r.get("filename"))
        if i < target:
            keep.append(fn)
            continue
        # A frame outside the count whose rank key is identical to the
        # last one inside it was not beaten; it tied.
        if cut is not None and _rank_key(r)[:2] == cut[:2]:
            keep.append(fn)
            ties += 1
            continue
        demote.append(fn)
    return {"keep": keep, "demote": demote, "target": target, "n": n,
            "ties_at_boundary": ties, "short_by": 0}


def apply(rows: list[dict[str, Any]], target: int,
          *, demote_to: str = "maybe") -> dict[str, Any]:
    """Apply :func:`plan` to ``rows`` in place, marking what changed.

    ``demote_to`` is `maybe`, not `cull`. A frame that missed a contracted
    count is not a frame the tool judged bad, and writing `cull` on it
    would put that claim in the CSV, the XMP sidecar and the catalogue.
    """
    got = plan(rows, target)
    keep = set(got["keep"])
    changed = 0
    for r in rows:
        fn = str(r.get("filename"))
        before = str(r.get("decision") or "")
        after = "keep" if fn in keep else (
            before if before == "cull" else demote_to)
        if after != before:
            r[PRIOR_COL] = before
            r[SOURCE_COL] = ("promoted_to_target" if after == "keep"
                             else "demoted_to_target")
            r["decision"] = after
            changed += 1
    got["changed"] = changed
    return got
