"""v2.70 — is each detector flag evidence at all?

v2.68 asked what a flag should DO when it fires and answered "demote,
never delete". This asks the prior question one flag at a time, and the
answer changed what the question should have been.

Three findings, and the third is the one that matters:

1. **Two flags carry measured lift and neither is in the attention set**
   (`severely_underexposed` 2.32x [1.41, 3.60], `shadows_clipped` 1.72x
   [1.04, 2.72]), while every flag that IS in the set is either
   unmeasured — three never fired once on 494 frames — or inconclusive.

2. **v2.68 overstated its own evidence.** Its commit says the flags
   carry "0.9x lift — worse than chance". That was a point estimate with
   no interval. `no_clear_subject`, the dominant flag at 301 firings, is
   0.83x with a 95% interval of [0.56, 1.22]: it spans 1.0, and nothing
   can be concluded. The DECISION v2.68 took still stands — it rests on
   a direct A/B (274 keepers destroyed against 4) — but the statistic
   quoted for it did not support the words around it.

3. **Raw lift is the wrong number, and macro-F1 cannot supply the right
   one.** A flag fires on frames whose score is already low, and a low
   score already sends them to MAYBE: of `severely_underexposed`'s 63
   firings, 52 are non-KEEP before the flag is consulted. What matters
   is the marginal question — of the frames the flag ALONE moves, how
   many did the photographer cull. `shadows_clipped` moves 22 and 2 are
   culls: 9.1%, the base rate exactly.

   macro-F1 scores MAYBE as KEEP, so moving a frame between them is
   invisible to it. Adding either flag changed macro-F1 by 0.0. Same
   identifiability trap as v2.68's `keep_min`, one parameter over.
"""

from __future__ import annotations

import pytest

from pixcull.scoring.flag_lift import (
    MIN_FIRINGS, flags_worth_acting_on, marginal, measure,
)


def _rows(spec):
    """(flag-tuple, truth, weight)."""
    return [(f, t, w) for f, t, w in spec]


def test_lift_is_measured_against_the_base_rate():
    rows = _rows([(("a",), "cull", 1.0)] * 3
                 + [(("a",), "keep", 1.0)] * 7
                 + [((), "keep", 1.0)] * 90)
    st = measure(rows)["a"]
    assert st.n_raw == 10
    assert round(st.rate, 3) == 0.3
    assert round(st.base_rate, 3) == 0.03
    assert round(st.lift, 1) == 10.0


def test_a_handful_of_firings_is_never_a_verdict():
    """A 0.00x lift on four firings is four frames.

    Three of the eight flags on the blind set fired fewer than ten
    times, two of them at 0.00x — which reads as "this flag is useless"
    and is nothing of the kind.
    """
    rows = _rows([(("rare",), "keep", 1.0)] * 4
                 + [((), "cull", 1.0)] * 10
                 + [((), "keep", 1.0)] * 86)
    st = measure(rows)["rare"]
    assert st.n_raw < MIN_FIRINGS
    assert st.lift == 0.0
    assert st.verdict == "unmeasured", (
        "a flag that fired four times got a verdict")


def test_an_interval_spanning_one_is_inconclusive_not_negative():
    """`no_clear_subject` is 0.83x over 301 firings and still cannot be
    called: [0.56, 1.22] contains 1.0. Reporting the point estimate as
    'worse than chance' is what v2.68's commit message did."""
    rows = _rows([(("f",), "cull", 1.0)] * 5
                 + [(("f",), "keep", 1.0)] * 45
                 + [((), "cull", 1.0)] * 11
                 + [((), "keep", 1.0)] * 89)
    st = measure(rows)["f"]
    lo, hi = st.lift_ci
    assert lo < 1.0 < hi, f"fixture no longer straddles 1.0: [{lo}, {hi}]"
    assert st.verdict == "inconclusive"


def test_never_fired_is_not_the_same_as_no_lift():
    """Three flags in the shipped set did not fire once on 494 frames.

    Dropping them would be acting on the absence of evidence, which is
    how a sample's shape becomes a product decision.
    """
    stats = measure(_rows([(("seen",), "keep", 1.0)] * 30
                          + [((), "cull", 1.0)] * 5))
    keep, notes = flags_worth_acting_on(stats, ["seen", "ghost"])
    assert "ghost" in keep, "a flag was dropped for never having fired"
    assert any("never fired" in n and "ghost" in n for n in notes), (
        "the report does not say WHY ghost was kept")


def test_the_marginal_number_conditions_on_the_decision_already_taken():
    """The number that decides, and the reason raw lift misleads.

    Ten firings, nine of which the score had already sent to MAYBE. Raw
    lift looks strong; the flag actually moves one frame.
    """
    rows = [(("f",), "cull", "maybe", 1.0)] * 9 + [(("f",), "keep", "keep", 1.0)]
    mg = marginal(rows, "f", base_rate=0.09)
    assert mg.n_fired == 10
    assert mg.n_already_flagged_by_score == 9
    assert mg.n_changed == 1, "frames already off KEEP were counted as moved"
    assert mg.n_changed_culls == 0
    assert mg.lift == 0.0, (
        "the flag surfaced no culls among the frames it alone moved, and "
        "the marginal lift has to say so")


def test_the_cli_command_exists_and_is_documented():
    """A one-off script is not a measurement anyone can repeat.

    Every earlier finding in this project that lived only in a scratch
    file had to be re-derived, and twice was re-derived wrongly.
    """
    import inspect

    from pixcull import cli

    fn = getattr(cli, "flag_lift", None)
    assert fn is not None, "`pixcull flag-lift` is gone"
    doc = inspect.getdoc(fn) or ""
    assert "marginal" in doc, (
        "the command does not explain the number that decides, so a "
        "reader will act on the raw lift")
