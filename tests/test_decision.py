"""Tests for scene-aware decide() — the V0.6 fix for `no_clear_subject` hard-cull
over-firing on minimalist architecture/landscape/street compositions.
"""

from __future__ import annotations

import pytest

from pixcull.config import PixCullConfig
from pixcull.scoring.decision import (
    Decision,
    _BLUR_TOLERANT_SCENES,
    _TINY_SUBJECT_TOLERANT_SCENES,
    decide,
)


@pytest.fixture(scope="module")
def config() -> PixCullConfig:
    return PixCullConfig.load()


@pytest.fixture(scope="module")
def cull_policy_config() -> PixCullConfig:
    """The shipped config with v2.67's flag policy: a flag deletes.

    v2.68 changed what a firing flag *does* — it demotes to MAYBE now,
    on 493 cross-validated blind frames — and that is orthogonal to
    **which** flags fire in **which** scenes, which is what most of the
    tests below are actually about.  Mixing the two would have meant
    rewriting a scene-exemption test every time the action changed, and
    the rewrite is where intent gets lost.

    So: exemption-logic tests pin the policy they were written against
    and keep asserting CULL, which still says exactly what they meant.
    What the shipped policy does has its own tests, at the bottom.
    """
    cfg = PixCullConfig.load()
    fusion = dict(cfg.fusion)
    fusion["decision"] = {**(fusion.get("decision") or {}),
                          "flags_policy": "cull"}
    return cfg.model_copy(update={"fusion": fusion})


@pytest.fixture(autouse=True)
def _isolate_vertical_overrides(tmp_path, monkeypatch):
    """V18 — isolate vertical-data root so any policy_override.json or
    phrase_override.json files written during real usage don't pollute
    decide() tests that exercise the V17.2 baseline policies.

    V28 — also patch ``pixcull.users._app_data_root`` because that's
    where ``vertical_root`` now resolves through.
    """
    from pixcull import verticals as vmod
    from pixcull import users as _users_mod
    monkeypatch.setattr(vmod, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(_users_mod, "_app_data_root", lambda: tmp_path)
    yield


def test_no_clear_subject_is_hard_cull_for_portrait(cull_policy_config):
    """Portraits without a clear subject really are broken — cull must stick."""
    dec, reasons = decide(0.72, ["no_clear_subject"], cull_policy_config, scene="portrait")
    assert dec is Decision.CULL
    assert "no_clear_subject" in reasons


def test_no_clear_subject_is_soft_for_landscape(config):
    """Tiny subjects are compositionally normal for landscape."""
    dec, _ = decide(0.72, ["no_clear_subject"], config, scene="landscape")
    assert dec is Decision.KEEP


def test_no_clear_subject_is_soft_for_architecture(config):
    """Architecture shots routinely embed the building in environment."""
    dec, _ = decide(0.72, ["no_clear_subject"], config, scene="architecture")
    assert dec is Decision.KEEP


def test_no_clear_subject_is_soft_for_street(config):
    dec, _ = decide(0.72, ["no_clear_subject"], config, scene="street")
    assert dec is Decision.KEEP


def test_other_hard_cull_flags_still_fire_on_tolerant_scenes(cull_policy_config):
    """The exemption is scoped to `no_clear_subject` only. Closed eyes, blown
    highlights, etc. still mean cull everywhere."""
    for flag in ("closed_eyes", "severely_overexposed", "motion_blur_on_face"):
        dec, reasons = decide(0.72, [flag], cull_policy_config, scene="landscape")
        assert dec is Decision.CULL, f"{flag} should still hard-cull"
        assert flag in reasons


def test_missing_scene_uses_strict_interpretation(cull_policy_config):
    """When scene is None (caller omitted it), we don't know whether it's a
    minimalist composition. Fall back to the strict hard-cull behavior."""
    dec, _ = decide(0.72, ["no_clear_subject"], cull_policy_config, scene=None)
    assert dec is Decision.CULL


def test_tolerant_scene_set_matches_templates():
    """V18 doc-tie: wildlife + astro joined the tolerant set after the
    100CANON scan revealed 22 false-cull wildlife shots (small/distant
    subjects shot on telephoto — birds across a lake, monkeys at
    canopy distance — where the small subject IS the genre)."""
    assert "landscape" in _TINY_SUBJECT_TOLERANT_SCENES
    assert "architecture" in _TINY_SUBJECT_TOLERANT_SCENES
    assert "street" in _TINY_SUBJECT_TOLERANT_SCENES
    assert "wildlife" in _TINY_SUBJECT_TOLERANT_SCENES   # V18 addition
    assert "astro" in _TINY_SUBJECT_TOLERANT_SCENES      # V18 addition
    # Portraits + stilllife still should NOT be tolerant.
    assert "portrait" not in _TINY_SUBJECT_TOLERANT_SCENES
    assert "stilllife" not in _TINY_SUBJECT_TOLERANT_SCENES


def test_v18_wildlife_tolerates_no_clear_subject(config):
    """V18: wildlife shots with small/distant subjects are valid (genre
    norm). Before V18, no_clear_subject hard-culled them.

    Verified on the V17.13 100CANON scan: 22 wildlife shots flipped
    from cull → 17 keep + 5 maybe. The flips were all shots that
    scored ≥0.5 (high-quality shots killed only by this one flag)."""
    dec, _ = decide(0.85, ["no_clear_subject"], config, scene="wildlife")
    assert dec is Decision.KEEP


def test_v18_astro_tolerates_no_clear_subject(config):
    """V18: starfield / milky-way shots don't have a "clear subject" by
    the detector's measure. Tolerate."""
    dec, _ = decide(0.75, ["no_clear_subject"], config, scene="astro")
    assert dec is Decision.KEEP


def test_v18_wildlife_still_hard_culls_other_flags(cull_policy_config):
    """The V18 exemption is scoped to no_clear_subject. Closed eyes,
    motion blur on face, severely overexposed still hard-cull a
    wildlife shot."""
    for flag in ("closed_eyes", "motion_blur_on_face",
                  "severely_overexposed"):
        dec, _ = decide(0.85, [flag], cull_policy_config, scene="wildlife")
        assert dec is Decision.CULL, f"{flag} should still cull wildlife"


def test_score_based_decisions_still_work(config):
    """Without any hard-cull flags, decide() falls through to score thresholds.

    v2.68 moved the cull line from 4.0 to 5.75, so the mid-band probe
    moved with it: 0.55 is now below the line and culls correctly. The
    band still exists — that was a condition of the change, not a
    side effect of it.
    """
    assert decide(0.90, [], config, scene="portrait")[0] is Decision.KEEP
    assert decide(0.30, [], config, scene="portrait")[0] is Decision.CULL
    assert decide(0.61, [], config, scene="portrait")[0] is Decision.MAYBE


def test_strictness_presets_shift_thresholds(config):
    """Lenient should keep more, strict should keep fewer. Scene-tolerance is
    independent of strictness."""
    score = 0.60  # sits in the maybe band at standard (6.5/4.0)
    assert decide(score, [], config, scene="portrait", strictness="lenient")[0] is Decision.KEEP
    assert decide(score, [], config, scene="portrait", strictness="strict")[0] is Decision.MAYBE


# --------------------------------------------------- V0.8 hard-cull loosening
def test_severely_underexposed_is_not_hard_cull(config):
    """V0.8: `severely_underexposed` is now advisory across all scenes.

    Rationale: 0/9 correct culls on the V0.7 golden set depended on it, while
    3 keep-photos (AB4A4609/4644 stilllife, 20210801-3J0A8098 landscape) were
    wrongly culled by it. Underexposure is either intentional (low-key,
    silhouette, mood) or recoverable from RAW; `score_exposure` already
    reflects the luma signal in `final_score`.
    """
    for scene in ("stilllife", "landscape", "portrait", "event", "wildlife", None):
        dec, _ = decide(0.72, ["severely_underexposed"], config, scene=scene)
        assert dec is Decision.KEEP, f"scene={scene}: severely_underexposed must not hard-cull"


def test_severely_underexposed_low_score_still_culls_via_score(config):
    """The flag being advisory doesn't let garbage through — a low final_score
    still hits `cull_max` on its own."""
    dec, _ = decide(0.30, ["severely_underexposed"], config, scene="portrait")
    assert dec is Decision.CULL


def test_severely_blurry_still_hard_culls_non_landscape_scenes(cull_policy_config):
    """V0.8: the blur exemption is scoped to landscape only. Portrait,
    stilllife, event, wildlife still hard-cull on severely_blurry."""
    for scene in ("portrait", "stilllife", "event", "wildlife", "architecture", "street"):
        dec, reasons = decide(0.72, ["severely_blurry"], cull_policy_config, scene=scene)
        assert dec is Decision.CULL, f"scene={scene}: severely_blurry should still hard-cull"
        assert "severely_blurry" in reasons


def test_severely_blurry_is_soft_on_landscape(config):
    """V0.8: long-exposure water / clouds / ICM are legitimate landscape techniques.
    A high-score landscape with `severely_blurry` should keep, not cull."""
    dec, _ = decide(0.72, ["severely_blurry"], config, scene="landscape")
    assert dec is Decision.KEEP


def test_severely_blurry_landscape_low_score_goes_to_maybe(config):
    """A mid-band landscape with severely_blurry shouldn't be hard-culled;
    falls through to the score bands — 3J0A3760 (0.455) / 3J0A4411 (0.511)
    are the two photos this fix was targeting. Both land in MAYBE rather
    than CULL — within-one improvement."""
    # v2.68 — asserted against the unflagged verdict. The point was
    # never that the frame lands in MAYBE; it is that `severely_blurry`
    # does not get to decide a landscape. Pinning the destination made
    # the test fail when the score bands moved underneath it, for a
    # reason that had nothing to do with what it was guarding.
    clean, _ = decide(0.50, [], config, scene="landscape")
    dec, _ = decide(0.50, ["severely_blurry"], config, scene="landscape")
    assert dec is clean, "severely_blurry decided a landscape frame"


def test_blur_tolerant_scene_set_is_landscape_only(config):
    """Doc-tie: V0.8 only exempts landscape from the blur hard-cull. We want
    portrait / wildlife to still cull on blur (subject out-of-focus is a real
    failure there)."""
    assert "landscape" in _BLUR_TOLERANT_SCENES
    for s in ("portrait", "stilllife", "event", "wildlife", "architecture", "street"):
        assert s not in _BLUR_TOLERANT_SCENES, f"{s} should not be blur-tolerant"


def test_missing_scene_still_hard_culls_blur(cull_policy_config):
    """Scene=None (caller omitted it) should fall back to the strict blur
    interpretation — we can't assume the intent was long-exposure."""
    dec, _ = decide(0.72, ["severely_blurry"], cull_policy_config, scene=None)
    assert dec is Decision.CULL


def test_other_hard_cull_flags_still_fire_on_landscape(cull_policy_config):
    """V0.8 exemption is scoped to `severely_blurry` + `no_clear_subject` on
    landscape. Other hard-cull flags still fire."""
    for flag in ("closed_eyes", "severely_overexposed", "motion_blur_on_face"):
        dec, _ = decide(0.72, [flag], cull_policy_config, scene="landscape")
        assert dec is Decision.CULL, f"{flag} should still hard-cull on landscape"


# ============================================================================
# V17.2 — per-vertical policy override.  decide(vertical=...) reads the
# registered VerticalPolicy and shifts thresholds + tolerated flags.
# ============================================================================


def test_vertical_unset_is_no_op(config):
    """Calling decide() without ``vertical=`` must reproduce V1.x behavior."""
    score = 0.60
    dec_no_vert, _ = decide(score, [], config, scene="portrait")
    dec_none, _   = decide(score, [], config, scene="portrait", vertical=None)
    dec_empty, _  = decide(score, [], config, scene="portrait", vertical="")
    assert dec_no_vert is dec_none is dec_empty


def test_vertical_unknown_falls_through(config):
    """Unknown vertical key shouldn't crash or change behavior — it's
    treated as if the kwarg wasn't passed."""
    score = 0.60
    dec_a, _ = decide(score, [], config, scene="portrait")
    dec_b, _ = decide(score, [], config, scene="portrait",
                       vertical="__not_a_real_vertical__")
    assert dec_a is dec_b


def test_kids_keep_min_delta_promotes_marginal_score(config):
    """Score that's MAYBE on the default 6.5 keep-line should land KEEP
    on kids (which has keep_min_delta = -0.05)."""
    # 0.61 is below default keep_min (0.65) → MAYBE without vertical.
    dec_default, _ = decide(0.61, [], config, scene="portrait")
    assert dec_default is Decision.MAYBE
    # With kids vertical, threshold drops to ~0.60 → row tips to KEEP.
    dec_kids, _ = decide(0.61, [], config, scene="portrait", vertical="kids")
    assert dec_kids is Decision.KEEP


def test_landscape_keep_min_delta_demotes_marginal_score(config):
    """Score that's barely KEEP on the default 6.5 keep-line should land
    MAYBE on landscape (which has keep_min_delta = +0.03 — stricter)."""
    # 0.66 sits just above default keep_min (0.65) → KEEP without vertical.
    dec_default, _ = decide(0.66, [], config, scene="landscape")
    assert dec_default is Decision.KEEP
    # With landscape vertical, threshold rises to ~0.68 → tips to MAYBE.
    dec_landscape, _ = decide(0.66, [], config, scene="landscape",
                                vertical="landscape")
    assert dec_landscape is Decision.MAYBE


def test_kids_tolerates_motion_blur_on_face(cull_policy_config):
    """kids policy adds motion_blur_on_face to tolerated_flags. Without
    vertical the flag hard-culls; with kids vertical the row falls
    through to score-based decision."""
    dec_default, _ = decide(0.72, ["motion_blur_on_face"], cull_policy_config,
                              scene="portrait")
    assert dec_default is Decision.CULL

    dec_kids, _ = decide(0.72, ["motion_blur_on_face"], cull_policy_config,
                           scene="portrait", vertical="kids")
    assert dec_kids is Decision.KEEP   # 0.72 > kids keep_min (0.60)


def test_kids_does_not_tolerate_severe_overexposure(cull_policy_config):
    """tolerated_flags is scoped — kids tolerates motion_blur but NOT
    severely_overexposed (which is always destructive)."""
    dec_kids, _ = decide(0.72, ["severely_overexposed"], cull_policy_config,
                           scene="portrait", vertical="kids")
    assert dec_kids is Decision.CULL


def test_landscape_tolerates_severely_blurry_via_vertical(config):
    """The V0.8 scene-based exemption already lets landscape tolerate
    severely_blurry. Vertical policy is independent and additive — pass
    a different scene and the vertical-level exemption alone should
    still demote."""
    # scene=portrait wouldn't normally tolerate severely_blurry; but
    # the landscape vertical's policy says it should.
    dec_with_vert, _ = decide(0.72, ["severely_blurry"], config,
                                scene="portrait", vertical="landscape")
    assert dec_with_vert is Decision.KEEP


def test_wedding_tolerates_shadow_clipping(config):
    """Wedding's policy tolerates `shadows_clipped` (not in the default
    hard_cull set anyway, but this confirms the vertical doesn't add
    spurious cull conditions)."""
    # shadows_clipped is NOT in default hard_cull so this is mostly a
    # smoke check — high score should land KEEP regardless of flag.
    dec_w, _ = decide(0.80, ["shadows_clipped"], config,
                       scene="portrait", vertical="wedding")
    assert dec_w is Decision.KEEP


def test_threshold_clamps_to_unit_range(config):
    """Pathologically large delta shouldn't push threshold past 1.0."""
    # We don't actually have such a vertical, but the clamp logic in
    # decide() should withstand one. Use ad-hoc monkeypatch via a
    # custom Vertical fixture below if needed; this just smoke-tests
    # that the existing clamp doesn't crash on the 10 real verticals.
    for vkey in ("kids", "landscape", "wedding", "sports", "bird"):
        # Score at extreme ends should still produce a valid decision.
        for score in (0.0, 0.5, 1.0):
            dec, _ = decide(score, [], config, scene="portrait", vertical=vkey)
            assert dec in (Decision.KEEP, Decision.MAYBE, Decision.CULL)


# ── v2.48-P1 — the vision judge gets real authority ───────────────────
#
# Before this, a VLM verdict was decorative: score_final and decision
# were written before the VLM stage even ran, and rule-CULL rows were
# skipped, so five stars on every axis could not save one photo.
#
# `vlm_authority` is "off" by default and stays that way until the
# positioning rewrite ships alongside it — the README still promises
# photos never leave the machine, and that promise must not be broken by
# a default flip in a patch release.

def test_authority_off_is_exactly_v247(cull_policy_config):
    """`off` must remain a complete, working escape hatch.

    v2.50 flipped the shipped default to `primary`, so this can no longer
    lean on the default — it has to ask for `off` explicitly, which is
    the point: after the flip, `off` is the mode a photographer under an
    NDA depends on, and the README now promises it by name.
    """
    for label in ("keep", "cull", "maybe"):
        dec, reasons = decide(0.72, ["closed_eyes"], cull_policy_config, scene="portrait",
                              vlm_label=label, vlm_axes={"technical": 5},
                              vlm_authority="off")
        assert dec is Decision.CULL, f"{label} changed an off-mode decision"
        assert not any("vlm" in r for r in reasons)


def test_the_shipped_default_is_the_documented_one(config):
    """v2.64 — `primary` ships, on evidence rather than on hope.

    v2.64 — `primary`, on 394 blind frames:

        mode      destroys keepers   finds your culls   second looks
        rule           126 / 366          5 / 28            31
        primary         15 / 366          4 / 28           195

        macro-F1 +14.6 pts, 95% CI [+6.8, +23.1]

    What `maybe` means was measured, not assumed: 58 of 60 `maybe`s on
    kept frames were "worth another look after a crop" (97%); 13 of 16
    on culled frames were genuine misses (81%). Both passes blind.

    If this moves again it should move with a blind pass behind it, and
    this docstring should say which one.

    Superseded v2.58's `off`, which was itself a correction of v2.50's
    unmeasured `primary`.

    v2.50 shipped `primary` "out of the box" on the strength of a
    measurement that turned out to be circular. The first blind pass —
    150 frames labelled before anything was scored — gave `primary` 1 of
    the 10 frames the photographer would delete, with a 95% confidence
    interval spanning zero.

    So `off` ships: the judge scores and explains, and changing a
    decision takes an explicit `--vlm-authority`. If this value moves
    again it should move with a blind pass behind it, and this docstring
    should say which one.

    Paired with tests/test_claims_match_reality.py, which fails if this
    default, run_pipeline's and the CLI's ever disagree.
    """
    import inspect
    sig = inspect.signature(decide)
    assert sig.parameters["vlm_authority"].default == "primary"
    # And the behaviour, not just the signature: a hard-culled frame the
    # judge wants to keep stays culled under the shipped default. Before
    # v2.58 this same call returned KEEP.
    dec, reasons = decide(0.72, ["closed_eyes"], config, scene="portrait",
                          vlm_label="keep", vlm_axes={"technical": 4})
    assert dec is not Decision.CULL, (
        "the judge no longer reaches the decision under the shipped "
        "default — `primary` is advertised and unreachable")

    # `off` leaves the decision reasons untouched — annotating them is
    # `shadow`'s job, tested below. The verdict is not lost: run_vlm_stage
    # writes vlm_overall_label / _rationale / axis stars into scores.csv
    # and vlm_verdicts.jsonl BEFORE authority is consulted, so a user who
    # paid for the call still gets the reasoning in the report.
    assert any("vlm" in r for r in reasons), (
        f"the verdict changed the decision but left no trace: {reasons}")

    # ... and `off` still means off, for anyone who asks for it.
    # v2.68 — compared against the no-judge-at-all verdict rather than
    # against Decision.CULL. What `off` promises is that the judge does
    # not reach the decision, and that promise is kept whatever the rule
    # stack itself decides; naming the destination tied this guarantee
    # to a threshold that has now moved twice.
    no_judge, no_why = decide(0.72, ["closed_eyes"], config, scene="portrait")
    silent, why = decide(0.72, ["closed_eyes"], config, scene="portrait",
                         vlm_label="keep", vlm_axes={"technical": 4},
                         vlm_authority="off")
    assert silent is no_judge, "`--vlm-authority off` is unreachable"
    assert why == no_why, f"`off` touched the reasons: {why}"


def test_shadow_records_without_changing_anything(cull_policy_config):
    dec, reasons = decide(0.72, ["closed_eyes"], cull_policy_config, scene="portrait",
                          vlm_label="keep", vlm_authority="shadow")
    assert dec is Decision.CULL
    assert "vlm_shadow=keep" in reasons


def test_shadow_annotation_survives_the_non_cull_path(config):
    """The bug I wrote and caught: rule_reasons is built fresh.

    Appending the note to `reasons` only reaches the hard-cull return, so
    it vanished on precisely the rows worth shadowing — the ones the rule
    was going to keep anyway and where a disagreement is interesting.
    """
    dec, reasons = decide(0.9, [], config, vlm_label="cull",
                          vlm_authority="shadow")
    assert dec is Decision.KEEP
    assert "vlm_shadow=cull" in reasons


def test_primary_lets_the_judge_override_a_hard_cull(config):
    """A candid of someone laughing with their eyes shut.

    The rule stack has always got this wrong. M3 was shown the blink
    count in its prompt, so keeping it is a considered override, not
    ignorance.
    """
    dec, reasons = decide(0.72, ["closed_eyes"], config, scene="portrait",
                          vlm_label="keep", vlm_axes={"technical": 4},
                          vlm_authority="primary")
    assert dec is Decision.KEEP
    assert any("vlm_kept_despite" in r for r in reasons)
    assert "closed_eyes" in " ".join(reasons), (
        "the photographer must be able to see WHAT was overridden")


def test_primary_distrusts_an_incoherent_verdict(cull_policy_config):
    """"Keep" alongside its own 1★ technical on a flagged frame is not a
    considered override, it is the model contradicting itself."""
    dec, reasons = decide(0.72, ["severely_blurry"], cull_policy_config, scene="portrait",
                          vlm_label="keep", vlm_axes={"technical": 1},
                          vlm_authority="primary")
    assert dec is Decision.CULL
    assert any("vlm_incoherent" in r for r in reasons)


def test_incoherence_guard_only_fires_on_flagged_rows(config):
    """A low technical score is a legitimate keep when nothing is flagged —
    grain, motion blur as intent, a soft-focus portrait.

    Scored at 0.2 so the rule stack would CULL: if the guard wrongly
    fired here we would fall back to the rule and lose the keep. A first
    version used 0.72, where the rule happens to agree, so widening the
    guard changed nothing observable and the mutation survived.
    """
    dec, reasons = decide(0.2, [], config, vlm_label="keep",
                          vlm_axes={"technical": 1}, vlm_authority="primary")
    assert dec is Decision.KEEP, (
        "an unflagged frame is the judge's call however it rates the "
        f"technique; got {reasons}")
    assert not any("incoherent" in r for r in reasons)


def test_primary_falls_back_when_there_is_no_verdict(cull_policy_config):
    """An API error must degrade to the rule stack, not to chaos.

    With M3 primary and the network down, every row arrives here with
    vlm_label=None. The run has to still produce a usable cull.
    """
    dec, _ = decide(0.72, ["closed_eyes"], cull_policy_config, scene="portrait",
                    vlm_label=None, vlm_authority="primary")
    assert dec is Decision.CULL
    dec, _ = decide(0.9, [], cull_policy_config, vlm_label=None, vlm_authority="primary")
    assert dec is Decision.KEEP


def test_unknown_label_falls_through_rather_than_guessing(config):
    dec, reasons = decide(0.9, [], config, vlm_label="probably fine?",
                          vlm_authority="primary")
    assert dec is Decision.KEEP
    assert not any("vlm=" in r for r in reasons)


def test_vendor_synonyms_are_understood(config):
    for label, expect in (("reject", Decision.CULL),
                          ("discard", Decision.CULL),
                          ("borderline", Decision.MAYBE)):
        dec, _ = decide(0.9, [], config, vlm_label=label,
                        vlm_authority="primary")
        assert dec is expect, label


def test_primary_can_cull_what_the_rule_would_keep(config):
    """Authority has to cut both ways or it is not authority."""
    dec, reasons = decide(0.95, [], config, vlm_label="cull",
                          vlm_authority="primary")
    assert dec is Decision.CULL
    assert "vlm=cull" in reasons


def test_case_and_whitespace_are_tolerated(config):
    dec, _ = decide(0.2, [], config, vlm_label="  KEEP \n",
                    vlm_authority="primary")
    assert dec is Decision.KEEP


def test_missing_axes_do_not_crash_the_guard(config):
    """vlm_axes is optional; a verdict with no technical star is common."""
    dec, _ = decide(0.72, ["closed_eyes"], config, scene="portrait",
                    vlm_label="keep", vlm_axes=None, vlm_authority="primary")
    assert dec is Decision.KEEP
    dec, _ = decide(0.72, ["closed_eyes"], config, scene="portrait",
                    vlm_label="keep", vlm_axes={"technical": None},
                    vlm_authority="primary")
    assert dec is Decision.KEEP


# ── v2.53 — "rescue": the authority the evidence actually earned ──────
#
# The owner reviewed 18 frames the rule stack hard-culled and M3 kept,
# and agreed with M3 on 17 (94%). That is a strong verified result about
# ONE behaviour — spotting a frame the detectors wrongly discard — and
# not a result about judging in general: across the measured set M3
# scores well below the rule stack.
#
# So this mode grants exactly that one power and nothing else.

def test_rescue_overturns_a_hard_cull(config):
    dec, reasons = decide(0.72, ["closed_eyes"], config, scene="portrait",
                          vlm_label="keep", vlm_axes={"technical": 4},
                          vlm_authority="rescue")
    assert dec is Decision.KEEP
    assert any("vlm_rescued(closed_eyes)" in r for r in reasons)


def test_rescue_has_no_say_on_anything_else(config):
    """The 94% was measured on hard-cull overrides only. Extending that
    authority to rows nobody reviewed would be inventing evidence."""
    dec, reasons = decide(0.9, [], config, vlm_label="cull",
                          vlm_axes={"technical": 1}, vlm_authority="rescue")
    assert dec is Decision.KEEP, "M3 demoted a row it has no mandate over"
    assert not any("vlm" in r for r in reasons)


def test_rescue_cannot_turn_a_keep_into_a_cull(config):
    dec, _ = decide(0.2, ["closed_eyes"], config, scene="portrait",
                    vlm_label="cull", vlm_authority="rescue")
    assert dec is Decision.CULL      # agrees with the rule; nothing rescued


def test_rescue_still_refuses_an_incoherent_verdict(cull_policy_config):
    """"Keep" beside its own 1★ technical is the model contradicting
    itself, and that guard applies to every mode that can override."""
    dec, reasons = decide(0.72, ["severely_blurry"], cull_policy_config, scene="portrait",
                          vlm_label="keep", vlm_axes={"technical": 1},
                          vlm_authority="rescue")
    assert dec is Decision.CULL
    assert not any("rescued" in r for r in reasons)


def test_rescue_can_land_on_maybe(config):
    """Most of the reviewed overrides were cull→maybe, not cull→keep."""
    dec, _ = decide(0.72, ["closed_eyes"], config, scene="portrait",
                    vlm_label="maybe", vlm_axes={"technical": 4},
                    vlm_authority="rescue")
    assert dec is Decision.MAYBE


def test_rescue_is_weaker_than_primary(config):
    """Structural: the same input that primary would flip, rescue leaves
    alone whenever no hard-cull flag fired."""
    args = dict(vlm_label="cull", vlm_axes={"technical": 3})
    assert decide(0.9, [], config, vlm_authority="primary", **args)[0] is Decision.CULL
    assert decide(0.9, [], config, vlm_authority="rescue", **args)[0] is Decision.KEEP
