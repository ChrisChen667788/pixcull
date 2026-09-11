"""v3.32 — seven waiting measurements, one budget, one refusal.

Seven of the eleven versions that ship a mechanism and no number wait on
the same thing: a spend ceiling the owner sets.  Run by hand they would
be seven separate runs whose results live in seven places, and any one of
them could stop halfway.
"""
import pytest

from pixcull.scoring.measurement_plan import (
    DIMENSIONS, WAITING, Measurement, plan,
)


def _est(calls, pt, ct):
    return calls * (pt + ct) / 1_000_000


def test_every_measurement_waiting_on_a_budget_is_here():
    """v2.91 was the one that got away.

    It has waited since the v2.77-v2.95 block on the same single thing —
    a spend ceiling — and kept its own harness because this planner did
    not exist yet. An owner who set a ceiling and ran "the block" would
    still have had one measurement sitting outside it, waiting on a
    decision they had already made.
    """
    versions = {m.version for m in WAITING}
    assert versions == {"v3.3", "v3.4", "v3.5", "v3.6", "v3.11",
                        "v3.17", "v3.18", "v2.91"}


def test_the_prompt_ab_arm_still_says_which_harness_runs_it():
    """This planner relaxes the arms-differ-only-in-the-prompt rule on
    purpose. A prompt A/B still needs it."""
    v291 = next(m for m in WAITING if m.version == "v2.91")
    assert "prompt_ab" in v291.note


def test_every_measurement_declares_exactly_one_dimension():
    """An arm that changes its prompt AND its resolution measures
    neither. That is v2.66's "we changed the prompt and the model and it
    got better", which is why this field exists."""
    for m in WAITING:
        assert m.varies in DIMENSIONS, m.version


def test_an_undeclared_dimension_is_refused_by_name():
    bad = Measurement("v9.9", "x", "vibes")
    got = plan([bad], 10, ceiling_units=99, estimate_cost=_est)
    assert got.refused and "v9.9" in got.refused


def test_it_refuses_before_the_first_call_not_halfway_through():
    """A run that stops halfway leaves half an arm, which is not a result
    and is money nobody gets back."""
    got = plan(WAITING, 200, ceiling_units=0.5, estimate_cost=_est)
    assert got.refused
    assert "ceiling" in got.refused


def test_a_plan_inside_the_ceiling_is_not_refused():
    got = plan(WAITING, 200, ceiling_units=100.0, estimate_cost=_est)
    assert got.refused is None
    assert got.est_calls > 0


def test_multi_call_arms_cost_more_than_single_call_ones():
    """v3.5 and v3.6 are three calls a frame. A planner that priced them
    as one would refuse too late."""
    got = plan(WAITING, 100, ceiling_units=1e9, estimate_cost=_est)
    by = {r["version"]: r["calls"] for r in got.per_measurement}
    assert by["v3.5"] == 300 and by["v3.6"] == 300
    assert by["v3.3"] == 100


def test_zero_frames_is_refused():
    got = plan(WAITING, 0, ceiling_units=99, estimate_cost=_est)
    assert got.refused and "zero frames" in got.refused


def test_an_empty_block_is_refused_rather_than_reported_as_free():
    assert plan([], 10, ceiling_units=99, estimate_cost=_est).refused


def test_the_cost_function_is_injected_not_imported():
    """So the ceiling can be checked against whatever the owner's actual
    pricing is, without this module carrying a price list that goes
    stale — and without a test needing one."""
    import inspect
    from pixcull.scoring import measurement_plan
    src = inspect.getsource(measurement_plan)
    assert "estimate_cost" in inspect.signature(plan).parameters
    for leak in ("yuan", "usd", "0.0", "price"):
        assert f"{leak} =" not in src.lower()


def test_each_measurement_says_what_the_number_would_mean():
    """A row that costs money and produces "a number" is not worth
    running. v3.17's says PER-AXIS, because an aggregate would hide the
    regression its design guards against."""
    for m in WAITING:
        assert m.note.strip(), m.version
    v317 = next(m for m in WAITING if m.version == "v3.17")
    assert "PER-AXIS" in v317.note or "per-axis" in v317.note


def test_this_module_does_not_run_anything():
    """The spend is the owner's and starting it is not an agent's call."""
    import inspect
    from pixcull.scoring import measurement_plan
    src = inspect.getsource(measurement_plan)
    for caller in ("requests", "urllib", "openai", "judge.score", "subprocess"):
        assert caller not in src


# ── v3.79 — "no ceiling" was not the same as "unbounded" ──────────────

def test_no_ceiling_still_refuses_when_the_daily_cap_would_stop_it():
    """The owner's decision was "no ceiling, run it to completion". That
    setting did not make the block unbounded — `llm_budget` declines
    calls against a daily cap that defaults to 10, one call at a time,
    as they happen.

    So the exact failure this planner exists to prevent — a stop halfway
    through, half an arm, nothing usable — was reachable by setting no
    ceiling at all, and it arrived silently."""
    # Derive the cap from the estimate rather than writing a number:
    # the suite's `_est` is on its own scale, and a hard-coded 10.0 here
    # tested nothing but that scale. The claim is about the
    # relationship — a cap below the estimate must refuse.
    unbounded = plan(WAITING, 200, ceiling_units=float("inf"),
                     estimate_cost=_est)
    cap = unbounded.est_units / 2
    got = plan(WAITING, 200, ceiling_units=float("inf"),
               estimate_cost=_est, daily_cap_units=cap)
    assert got.refused, (
        "an infinite ceiling behind a daily cap the block exceeds must "
        "refuse before the first call")
    assert got.bound_by == "daily-cap"
    assert "daily" in got.refused.lower()
    assert "PIXCULL_LLM_BUDGET_YUAN" in got.refused, (
        "the refusal has to name the knob, or the owner re-reads their "
        "own ceiling and finds nothing wrong with it")


def test_the_refusal_names_whichever_limit_actually_binds():
    """Two limits, and being told about the wrong one sends the reader
    to the wrong setting."""
    tight_ceiling = plan(WAITING, 200, ceiling_units=0.5,
                         estimate_cost=_est, daily_cap_units=1e9)
    assert tight_ceiling.bound_by == "ceiling"
    assert "ceiling" in (tight_ceiling.refused or "")
    assert "daily" not in (tight_ceiling.refused or "").lower()

    tight_cap = plan(WAITING, 200, ceiling_units=1e9,
                     estimate_cost=_est, daily_cap_units=0.5)
    assert tight_cap.bound_by == "daily-cap"
    assert "daily" in (tight_cap.refused or "").lower()


def test_a_block_inside_both_limits_is_not_refused():
    got = plan(WAITING, 200, ceiling_units=float("inf"),
               estimate_cost=_est, daily_cap_units=1e9)
    assert got.refused is None


def test_a_plan_that_never_saw_the_daily_cap_says_so():
    """Not a refusal — a plan measured against only half the limits must
    not read like one measured against all of them. `bound_by` is None
    rather than "ceiling", so a caller cannot mistake "nothing bound it"
    for "checked and fine"."""
    got = plan(WAITING, 100, ceiling_units=float("inf"), estimate_cost=_est)
    assert got.refused is None
    assert got.bound_by is None, (
        "with no daily cap supplied the plan has not been measured "
        "against the limit that will actually stop it")
    assert got.daily_cap_units is None


def test_the_daily_cap_default_is_what_the_budget_module_says():
    """The number in the refusal has to be the number that will stop the
    run. Read from the module rather than repeated here, because a
    second copy of a limit is how the two come to disagree."""
    from pixcull.llm_budget import cap_yuan
    cap = cap_yuan()
    assert cap > 0, "the daily cap reads as zero; every call would decline"
    got = plan(WAITING, 200, ceiling_units=float("inf"),
               estimate_cost=_est, daily_cap_units=cap)
    assert got.daily_cap_units == cap
