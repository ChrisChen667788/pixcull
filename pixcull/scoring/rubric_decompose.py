"""Map existing detector outputs to rubric axis scores.

This is the bridge between V1's flat scoring and V2's rubric scoring:
given a row dict from the pipeline (the same dict ``decide()`` and
``fuse_score()`` see), we evaluate each axis's check list and emit a
soft 1-5 star score. No human input required.

Why "soft" stars: the check list passes are a 0..1 fraction (e.g. 4/5
checks passed = 0.8). We linearly map that to the 1-5 star range with
``stars = 1 + 4 * checklist_pass`` so a row passing zero checks lands
at 1★ and a row passing all checks lands at 5★. This is intentionally
generous — the rubric is supposed to be a pre-fill the human edits,
not a final verdict. In practice the auto-stars cluster around 3-4
for keepers, 2-3 for ambiguous shots, 1-2 for hard culls, which is
exactly the spread we want for active learning to surface the
uncertain middle.

Notes on missing data: the face axis checks need ``face_count`` etc.
which only fire when mediapipe was installed at training time. When
those are absent, we skip the corresponding checklist item and rebase
the denominator — same logic the rescorer uses for ``__missing``
indicators. Better to under-weight an axis than to lie about it.
"""

from __future__ import annotations

from typing import Any

from pixcull.scoring.rubric import (
    RUBRIC_AXES,
    AxisScore,
    RubricScore,
    get_axis,
)


# ---------------------------------------------------------------------------
# Per-checklist evaluators. Each returns either a bool (pass/fail) or
# None (insufficient data — skip this item from the denominator).
#
# Keeping these as small named functions instead of lambdas inside a
# big dict pays off when one needs adjusting — git blame stays clean.
# ---------------------------------------------------------------------------

def _f(row: dict[str, Any], key: str) -> float | None:
    v = row.get(key)
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def _flag(row: dict[str, Any], flag_name: str) -> bool:
    """Return True iff the named flag is set on this row.

    The pipeline serializes flags as a comma-joined string in scores.csv
    but as a list inside the in-memory row dict. Handle both.
    """
    flags = row.get("flags") or ""
    if isinstance(flags, str):
        items = [s.strip() for s in flags.split(",") if s.strip()]
    else:
        items = list(flags)
    return flag_name in items


def _check_eval(check_key: str, row: dict[str, Any]) -> bool | None:
    """Evaluate one named check against the row. None means skip."""
    # technical
    if check_key == "not_severely_blurry":
        return not _flag(row, "severely_blurry")
    if check_key == "not_severely_overexposed":
        return not _flag(row, "severely_overexposed")
    if check_key == "not_severely_underexposed":
        return not _flag(row, "severely_underexposed")
    if check_key == "subject_in_focus":
        # Per-subject sharpness > a healthy floor; if subject lap is
        # missing fall back to global, if both missing skip.
        ls = _f(row, "laplacian_subject")
        lg = _f(row, "laplacian_global")
        ref = ls if ls is not None else lg
        if ref is None:
            return None
        return ref >= 60.0  # tuned on golden set; see eval_findings
    if check_key == "face_not_motion_blurred":
        if _f(row, "face_count") in (None, 0):
            return None  # no face → not applicable
        return not _flag(row, "motion_blur_on_face")
    # V5.1 canon checks — Adams Zone System
    if check_key == "canon_zone_full_range":
        # Distribution KL < 0.5 means histogram is reasonably close
        # to a "good photo" prior with thin tails. > 0.5 means
        # heavy clipping or severe imbalance.
        kl = _f(row, "canon_zone_distribution_kl")
        if kl is None:
            return None
        return kl < 0.5
    if check_key == "canon_no_zone_clipping":
        clip = _f(row, "canon_zone_clip_pct")
        if clip is None:
            return None
        return clip < 0.05  # < 5% in zones 0+X
    if check_key == "canon_midgray_anchored":
        offset = _f(row, "canon_midgray_offset")
        if offset is None:
            return None
        return offset < 0.15

    # subject
    if check_key == "has_clear_subject":
        return not _flag(row, "no_clear_subject")
    if check_key == "subject_eyes_open":
        if _f(row, "face_count") in (None, 0):
            return None
        return not _flag(row, "closed_eyes")
    if check_key == "subject_pose_natural":
        # No detector for this; treat as passing unless the user has
        # added a manual rationale flag (future work). For now skip.
        return None
    if check_key == "not_random_passersby":
        # No detector; skip.
        return None

    # composition
    if check_key == "horizon_within_2deg":
        h = _f(row, "horizon_tilt_deg")
        if h is None:
            return None
        return abs(h) <= 2.0
    if check_key == "rule_of_thirds_close":
        d = _f(row, "rule_of_thirds_offset")
        if d is None:
            return None
        return d <= 0.20  # within 20% of an intersection
    if check_key == "subject_not_at_edge":
        # Approximated via composition_score being above floor; not
        # perfect but the only signal currently available.
        c = _f(row, "composition_score")
        if c is None:
            return None
        return c >= 0.4
    if check_key == "no_distracting_clutter":
        # subject_fraction in a plausible range — too small means the
        # subject is lost, too large means there's no breathing room.
        s = _f(row, "subject_fraction")
        if s is None:
            return None
        return 0.05 <= s <= 0.85
    # V5.1 canon — composition
    if check_key == "canon_thirds_concentration":
        # Above 0.45 means the rule-of-thirds intersection cells
        # carry meaningful weight (vs. concentrated dead-center).
        t = _f(row, "canon_thirds_concentration")
        if t is None:
            return None
        return t >= 0.45
    if check_key == "canon_balanced_weight":
        b = _f(row, "canon_balance")
        if b is None:
            return None
        return b >= 0.6
    if check_key == "canon_lead_room_ok":
        lr = _f(row, "canon_lead_room")
        if lr is None:
            return None
        # 0.5 = symmetric (no clear direction); we want lead room
        # positively above 0.5 OR exactly at 0.5 (no directional
        # subject — not applicable, treat as pass).
        return lr >= 0.45
    if check_key == "canon_figure_ground_pop":
        fg = _f(row, "canon_figure_ground")
        if fg is None:
            return None
        return fg >= 0.4

    # light
    if check_key == "not_blown_highlights":
        h = _f(row, "highlight_clip_pct")
        if h is None:
            return None
        return h < 0.05  # < 5% of pixels clipped
    if check_key == "not_crushed_shadows":
        s = _f(row, "shadow_clip_pct")
        if s is None:
            return None
        return s < 0.20
    if check_key == "color_temperature_clean":
        # No detector; skip until we add a WB-cast metric.
        return None

    # moment
    if check_key == "not_blink_or_mid_yawn":
        if _f(row, "face_count") in (None, 0):
            return None
        return not _flag(row, "closed_eyes")
    if check_key == "action_at_peak":
        # v2.14-P1.1 — within a REAL burst (size≥2), the frame the burst-peak
        # ranker crowned (non-empty burst_peak_reason, e.g. "最锐 +1.6σ") IS the
        # captured action peak; a burst frame that lost the race
        # (is_burst_peak False) is not. A singleton (is_burst_peak trivially
        # True but no reason — "peak of 1") has no action sequence to peak
        # within, so stay None (skipped) rather than fabricate a peak.
        bp = row.get("is_burst_peak")
        if bp is None or (isinstance(bp, float) and bp != bp):  # missing / NaN
            return None
        is_peak = bp in (True, "True", "true", 1, "1")
        if not is_peak:
            return False
        reason = row.get("burst_peak_reason")
        return True if (isinstance(reason, str) and reason.strip()) else None
    if check_key == "emotion_present":
        # v2.14 — wedding scenes: the moment classifier estimates emotional /
        # decisive peak in [0,1].
        wmc = _f(row, "wedding_moment_confidence")
        if wmc is not None:
            return wmc >= 0.5
        # v2.14-P1.1 — non-wedding: a smiling face is real "emotion present"
        # (MediaPipe smile blendshape, face_max_smile 0..1). Faceless frames
        # stay None (skipped) — honest, not faked.
        if _f(row, "face_count") in (None, 0):
            return None
        smile = _f(row, "face_max_smile")
        if smile is None:
            return None
        return smile >= 0.30

    # aesthetic
    if check_key == "clipiqa_above_median":
        c = _f(row, "clipiqa")
        if c is None:
            return None
        return c >= 0.55  # rough median on the golden set
    if check_key == "laion_aes_above_median":
        a = _f(row, "laion_aes")
        if a is None:
            return None
        return a >= 5.5
    if check_key == "no_subject_environment_conflict":
        return None  # subjective

    return None


# ---------------------------------------------------------------------------
# Top-level decomposer.
# ---------------------------------------------------------------------------

def decompose_row(row: dict[str, Any]) -> RubricScore:
    """Compute the rubric for one pipeline row.

    V8.0: routes through ``detect_style_modes`` first so that
    intentionally-broken-rules photos (B&W, low-key, long exposure,
    silhouette) don't get punished for breaking rules they're MEANT
    to break. Style overrides apply per-check:
      "suppress" → check excluded from this image's denominator
      "boost"    → passed check counts double
      "invert"   → failed check considered passing

    Each axis's stars come from the weighted check list pass rate; the
    rationale is the list of failed checks (reverse-engineered to be
    human-readable). Sources stays "auto" so downstream code can tell
    auto-pre-fills from human gold labels.
    """
    from pixcull.scoring.style_modes import detect_style_modes
    from pixcull.scoring.genre_strategies import get_strategy
    rs = RubricScore.empty(row.get("filename", ""))
    rs.source = "auto"

    style = detect_style_modes(row)
    # V8.2: per-genre strategy. Style overrides take priority over
    # genre overrides where they conflict (style is more specific
    # than genre — a B&W landscape uses mono's overrides over
    # landscape's defaults).
    scene_name = str(row.get("scene", "") or "")
    genre = get_strategy(scene_name)
    merged_overrides: dict[str, str] = {}
    merged_overrides.update(genre.check_overrides)
    merged_overrides.update(style.overrides)        # style wins ties

    for axis in RUBRIC_AXES:
        weighted_sum = 0.0
        weight_total = 0.0
        failed: list[str] = []
        for check_key, w in axis.checklist:
            override = merged_overrides.get(check_key)
            if override == "suppress":
                continue                  # skip this check entirely
            result = _check_eval(check_key, row)
            if result is None:
                continue
            if override == "invert":
                result = not result
            effective_w = w * 2.0 if (override == "boost" and result) else w
            weight_total += effective_w
            if result:
                weighted_sum += effective_w
            else:
                failed.append(check_key)
        if weight_total > 0:
            pct = weighted_sum / weight_total
            base_stars = 1.0 + 4.0 * pct
            # V8.2: per-genre axis emphasis. Multiplied AFTER the base
            # 1-5 mapping; clipped to [1, 5] to stay in-range. A
            # 1.3× emphasis on a 4.0 → 5.0 (capped); 0.6× on 4.0 → 2.4.
            emphasis = genre.emphasis_for(axis.name)
            stars = max(1.0, min(5.0, round(base_stars * emphasis, 2)))
        else:
            pct = None
            stars = None
        rs.axes[axis.name] = AxisScore(
            stars=stars,
            checklist_pass=pct,
            rationale=("失分项: " + ", ".join(failed)) if failed else "",
            source="auto",
        )

    # Stash detected styles + genre into the overall rationale prefix
    # so downstream UI surfaces them. Doesn't change scoring beyond
    # the overrides + emphasis above.
    prefix_bits = []
    if style.modes:
        prefix_bits.append(" · ".join(sorted(style.modes)))
    if scene_name and scene_name in {
        "macro", "astro", "abstract", "documentary", "fashion",
        "architecture", "sports", "food",
    }:
        prefix_bits.append(scene_name)
    if prefix_bits:
        rs.overall_rationale = (
            "[" + " | ".join(prefix_bits) + "] "
        ) + (rs.overall_rationale or "")

    # Overall label — borrow from the pipeline's own decision (already
    # in row["decision"] when called post-decide). Rationale is the
    # axis names that scored < 3★, which is what a photographer would
    # call out anyway ("光不行 + 主体不清").
    rs.overall_label = str(row.get("decision", ""))
    weak = [
        get_axis(name).label_zh
        for name, axis in rs.axes.items()
        if axis.stars is not None and axis.stars < 3.0
    ]
    if weak:
        rs.overall_rationale = " · ".join(weak) + " 偏弱"
    elif all(a.stars is not None and a.stars >= 4.0 for a in rs.axes.values()):
        rs.overall_rationale = "六轴全部 ≥ 4★"
    else:
        rs.overall_rationale = ""
    return rs


def decompose_dataframe(df) -> list[RubricScore]:
    """Vectorless wrapper for pandas — one rubric per row."""
    return [decompose_row(row.to_dict()) for _, row in df.iterrows()]
