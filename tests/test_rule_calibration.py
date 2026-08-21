"""v2.68 — the rule-stack calibration, and the guards that make it honest.

The module's whole claim is that its number is out-of-fold.  A
calibration that scores itself on the rows it fitted produces a
confident, stable, entirely fictional result — this repo has shipped
four circular datasets and every one of them looked like this one does.
So the tests below are mostly about what the calibrator REFUSES.
"""

from __future__ import annotations

import pytest

from pixcull.config import PixCullConfig
from pixcull.scoring import rule_calibration as rc


@pytest.fixture(scope="module")
def cfg() -> PixCullConfig:
    return PixCullConfig.load()


def _rows(spec):
    return [rc.Row(truth=t, score_final=s, flags=tuple(f), scene="portrait")
            for t, s, f in spec]


def test_fitting_and_scoring_never_see_the_same_row(cfg):
    """The one property the reported number depends on.

    Built so the two answers differ: the held-out fold is engineered to
    disagree with everything else about where the boundary belongs. If
    the fit ever peeked, the reported score would be the training score
    — high, stable, and meaningless.
    """
    seen: list[list[float]] = []
    real_fit = rc.fit

    def _spy(rows, config, **kw):
        seen.append(sorted(r.score_final for r in rows))
        return real_fit(rows, config, **kw)

    rows = _rows([("keep", 0.9, []) for _ in range(30)]
                 + [("cull", 0.1, []) for _ in range(15)])
    rc.fit = _spy
    try:
        res = rc.cross_validate(rows, cfg, k=3, bootstrap=50)
    finally:
        rc.fit = real_fit

    assert res.refusal is None, res.refusal
    assert len(seen) == 3, "fit was not called once per fold"
    all_scores = sorted(r.score_final for r in rows)
    for train in seen:
        assert len(train) < len(all_scores), (
            "a fold was fitted on the whole set — the held-out rows were "
            "in the training data and the reported number is a fit")


def test_a_fold_with_no_cull_positives_is_refused(cfg):
    """Recall is undefined there, and a mean over undefined folds is not
    a number — it is a number-shaped object."""
    # Sized so the TRAINING folds are fine (4 culls each, above the
    # minimum) and only the held-out side is empty. With 2 culls the
    # training guard fired first and this test passed while the guard it
    # names was deleted — mutation testing found that, not review.
    rows = _rows([("keep", 0.9, []) for _ in range(40)]
                 + [("cull", 0.1, []) for _ in range(5)])
    res = rc.cross_validate(rows, cfg, k=5, bootstrap=50)
    assert res.refusal is not None
    assert "holds no cull positives" in res.refusal, (
        f"refused, but by a different guard: {res.refusal}")


def test_a_stack_that_culls_nothing_is_refused(cfg):
    """Not a calibration — a disablement that scores well.

    With the flags ignored and the cull line at the floor, the stack
    never deletes anything. macro-F1 rewards that, because not
    destroying keepers is most of the metric. It is still a rule stack
    that does not do its job.
    """
    rows = _rows([("keep", 0.9, []) for _ in range(40)]
                 + [("cull", 0.95, []) for _ in range(10)])
    grid = (rc.RuleThresholds(6.5, 0.0, "ignore"),)
    res = rc.cross_validate(rows, cfg, k=3, grid=grid, bootstrap=50)
    assert res.refusal is not None
    assert "culls nothing" in res.refusal


def test_a_parameter_the_data_cannot_see_is_reported_not_fitted(cfg):
    """`keep_min_score` fitted to 6.75, in all five folds, on real data.

    That reads as a stable, well-identified estimate. It was a tie-break:
    the metric scores MAYBE as KEEP, so the keep/maybe boundary is
    invisible to it, and sweeping that parameter from 6.5 to 10.0 moved
    409 frames without changing macro-F1 at four decimal places.
    """
    rows = _rows([("keep", 0.9, []) for _ in range(30)]
                 + [("cull", 0.1, []) for _ in range(15)])
    thr = rc.RuleThresholds(6.5, 4.0, "cull")
    dead = rc.unidentifiable(rows, thr, cfg)
    assert "keep_min_score" in dead, (
        "the keep/maybe boundary is being reported as if the labels "
        "constrained it; they are keep/cull and they do not")

    # And a parameter the data CAN see must not be swept under the same rug.
    assert "cull_max_score" not in dead


def test_the_asymmetric_objective_breaks_its_own_tie(cfg):
    """"Cull nothing" and "find four, destroy four" both net zero.

    The first draft returned `found - killed`, scored those two
    identically, and the folds split between them — half the run fitting
    a stack that deletes nothing. A tie between doing the job badly and
    not doing it at all is not a tie.
    """
    # The tie has to be REAL for this to test anything: four found and
    # four destroyed nets zero, exactly like culling nothing. The first
    # fixture culled 20 and destroyed 0, so `found - killed` still
    # ranked it top and the degenerate objective passed the test written
    # to catch it.
    rows = _rows([("cull", 0.1, []) for _ in range(4)]
                 + [("keep", 0.1, []) for _ in range(4)]
                 + [("keep", 0.9, []) for _ in range(20)])
    nothing = rc.RuleThresholds(6.5, 0.0, "ignore")
    working = rc.RuleThresholds(6.5, 5.0, "ignore")
    k_n, f_n = rc.outcomes(rows, nothing, cfg)
    k_w, f_w = rc.outcomes(rows, working, cfg)
    assert (f_n, k_n) == (0, 0), "fixture no longer starts from a no-op"
    assert f_w > 0, "fixture's working config culls nothing either"
    assert f_w == k_w, (
        f"fixture is not at the tie the objective has to break: "
        f"found={f_w} killed={k_w}")
    assert (rc.asymmetric_score(rows, working, cfg)
            > rc.asymmetric_score(rows, nothing, cfg)), (
        "doing the job scores no better than not doing it")


def test_the_calibrator_scores_the_real_decide(cfg):
    """A tuned model of the product is not the product.

    An earlier draft re-implemented the flag demotion here and applied
    it BEFORE the score check, so a flag could rescue a frame the score
    would have culled — while the shipped `decide()` applied it after.
    The measurement described a system that was never going to run.
    """
    import inspect

    src = inspect.getsource(rc.predict)
    assert "decide(" in src, "the calibrator no longer calls decide()"
    assert "return d.value" in src, (
        "predict() post-processes decide()'s answer again; there are two "
        "implementations of the rule and the measured one is not shipped")

    # Behaviourally: a flag must never make a frame safer.
    flagged = rc.Row("keep", 0.30, ("closed_eyes",), "portrait")
    clean = rc.Row("keep", 0.30, (), "portrait")
    thr = rc.RuleThresholds(6.5, 5.75, "maybe")
    assert rc.predict(flagged, thr, cfg) == rc.predict(clean, thr, cfg) == "cull"
