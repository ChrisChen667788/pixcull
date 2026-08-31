"""v2.89 — the keep/maybe boundary, and why a number for it is still refused.

v2.68 found `keep_min_score` unidentifiable: the metric scores `maybe`
as `keep`, so the parameter moves rows between two buckets the score
cannot tell apart. Sweeping it moved 409 frames and changed macro-F1 by
nothing at four decimal places, while five folds "agreed" on 6.75 —
agreement about an arbitrary tie-break.

That two-way rule is CORRECT for its own question and was measured, not
assumed: on kept frames 58 of 60 maybes were worth another look, on
culled frames 13 of 16 were a genuine miss. Scoring a maybe as a keep is
what that evidence says when the question is "how good is the model".

It is the wrong metric for "where should the boundary sit", and one
metric was serving both questions. `three_way=True` separates them.

What it does not do is make a fitted value trustworthy. On the blind
fixture:

  truths labelled maybe                    0 of 494
  maybe predictions under the shipped
    flags policy                           0 of 494

The boundary is unobservable twice over — nothing predicts it and
nothing labels it. A three-way metric that responds to the parameter is
necessary and not sufficient, and this version ships the mechanism while
refusing the number.
"""
import json
from pathlib import Path

import pytest

from pixcull.config import PixCullConfig
from pixcull.scoring import rule_calibration as rc

FIXTURE = Path(__file__).parent / "fixtures" / "blind_rule_stack.jsonl"


@pytest.fixture(scope="module")
def rows():
    out = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append(rc.Row(score_final=d.get("score_final"),
                          flags=d.get("flags") or "", scene=d.get("scene") or "",
                          truth=d.get("truth"), weight=d.get("weight", 1.0)))
    return out


@pytest.fixture(scope="module")
def cfg():
    return PixCullConfig.load()


def _thr(**kw):
    base = dict(keep_min_score=0.62, cull_max_score=0.45, flags_policy="cull")
    base.update(kw)
    return rc.RuleThresholds(**base)


def test_two_way_cannot_see_either_threshold(rows, cfg):
    dead = rc.unidentifiable(rows, _thr(), cfg)
    assert "keep_min_score" in dead
    assert "cull_max_score" in dead, (
        "v2.68 reported only keep_min_score; cull_max_score is invisible "
        "to the same metric for the same reason")


def test_three_way_makes_the_keep_boundary_visible(rows, cfg):
    dead = rc.unidentifiable(rows, _thr(), cfg, three_way=True)
    assert "keep_min_score" not in dead


def test_three_way_does_not_rescue_the_cull_boundary(rows, cfg):
    """Reported rather than glossed: separating maybe from keep does
    nothing for a threshold on the other side."""
    dead = rc.unidentifiable(rows, _thr(), cfg, three_way=True)
    assert "cull_max_score" in dead


def test_the_sweep_and_the_baseline_use_the_same_metric(rows, cfg):
    """A three-way baseline compared against two-way sweeps reports
    every parameter as identifiable, because the two numbers are not
    commensurable. That was the state of this code for one commit."""
    import inspect
    src = inspect.getsource(rc.unidentifiable)
    assert src.count("three_way=three_way") >= 2, (
        "the baseline and the sweep do not both honour three_way")


def test_a_maybe_truth_is_not_dropped_under_three_way():
    """The two-way tally drops rows whose truth is maybe — correct there,
    fatal here. Dropping them under three-way leaves the parameter as
    invisible as before while looking fixed."""
    cm = {}
    rc._tally3(cm, "maybe", "maybe", 1.0)
    assert cm and cm["maybe"].tp == 1


def test_the_fixture_contains_no_maybe_truth(rows):
    """The fact that blocks a number. Stated as a test so it stops being
    true the moment someone labels a sample."""
    assert not [r for r in rows if r.truth == "maybe"], (
        "there are maybe truths now — re-run the boundary fit and "
        "delete this test")


def test_the_shipped_policy_never_predicts_maybe(rows, cfg):
    """The other half. Even a perfect metric sees nothing if the stack
    emits no maybes: flags_policy='cull' sends flagged frames straight
    to cull."""
    preds = {rc.predict(r, _thr(), cfg, "standard") for r in rows}
    assert "maybe" not in preds


def test_three_way_is_not_the_default(rows, cfg):
    """It answers "can this parameter be identified", not "is the model
    good". Reporting it as the headline would be a different number
    wearing the same name."""
    import inspect
    sig = inspect.signature(rc.score)
    assert sig.parameters["three_way"].default is False
    assert sig.parameters["three_way"].kind is inspect.Parameter.KEYWORD_ONLY
