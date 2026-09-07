"""v3.19 — "deliver 400 selects", and staying honest about what that means.

Event work is contracted in counts.  PixCull has three strictness presets
and a personal shift, and every one of them moves a THRESHOLD — which is
blind to set size, so the same preset yields wildly different counts on a
300-frame shoot and a 3,000-frame one.  There is no portable setting that
lands on a number, and the photographer's alternative is re-running a
2,000-frame shoot and guessing again.

The honesty problem is the interesting half.  A threshold keep says "this
cleared the bar".  A target-count keep says "this was in the top N of what
you shot", which on a bad afternoon is true of frames the rubric rejected.
"""
import inspect

from pixcull.scoring.target_count import (
    PRIOR_COL, SOURCE_COL, apply, plan,
)


def _rows(n, decision="cull"):
    return [{"filename": f"{i:03d}.jpg", "score_final": 1.0 - i * 0.01,
             "decision": decision} for i in range(n)]


def test_a_target_of_n_keeps_exactly_n():
    rows = _rows(50)
    assert len(plan(rows, 20)["keep"]) == 20


def test_scores_are_never_rewritten():
    """The count changes what is delivered. It does not change what the
    tool measured, and a report showing otherwise would be a lie about
    the photographs."""
    rows = _rows(20)
    before = [r["score_final"] for r in rows]
    apply(rows, 5)
    assert [r["score_final"] for r in rows] == before


def test_every_changed_decision_is_marked_with_what_it_was():
    rows = _rows(10, decision="cull")
    apply(rows, 3)
    promoted = [r for r in rows if r.get(SOURCE_COL) == "promoted_to_target"]
    assert len(promoted) == 3
    assert all(r[PRIOR_COL] == "cull" for r in promoted)


def test_a_frame_the_pass_did_not_touch_carries_no_marker():
    rows = _rows(4, decision="keep")
    apply(rows, 4)
    assert all(r.get(SOURCE_COL) is None for r in rows)


def test_frames_tied_at_the_boundary_are_all_kept():
    """Choosing between two frames the scorer called identical, by
    filename or by row order, would be a decision presented as a
    measurement."""
    rows = [{"filename": f"{i}.jpg", "score_final": 0.5, "decision": "maybe"}
            for i in range(6)]
    got = plan(rows, 3)
    assert len(got["keep"]) == 6
    assert got["ties_at_boundary"] == 3


def test_a_shortfall_is_reported_not_silently_met():
    got = plan(_rows(10), 40)
    assert len(got["keep"]) == 10
    assert got["short_by"] == 30


def test_a_missed_frame_is_demoted_to_maybe_not_cull():
    """It missed a contracted count. That is not the tool judging it bad,
    and `cull` would put that claim in the CSV, the sidecar and the
    catalogue."""
    rows = _rows(10, decision="keep")
    apply(rows, 3)
    assert {r["decision"] for r in rows} == {"keep", "maybe"}


def test_a_frame_the_rubric_culled_stays_culled_when_it_misses():
    rows = _rows(10, decision="cull")
    apply(rows, 3)
    assert [r["decision"] for r in rows[3:]] == ["cull"] * 7


def test_the_ranking_is_stable_across_runs():
    """Without a deterministic tie-break the boundary wanders between
    runs for no reason the photographer can see."""
    rows = [{"filename": f"{c}.jpg", "score_final": 0.5, "decision": "maybe"}
            for c in "badce"]
    a = plan(list(rows), 2)["keep"]
    b = plan(list(reversed(rows)), 2)["keep"]
    assert a == b


def test_unscored_frames_sort_last_rather_than_first():
    rows = [{"filename": "no.jpg", "decision": "maybe"},
            {"filename": "yes.jpg", "score_final": 0.9, "decision": "maybe"}]
    assert plan(rows, 1)["keep"] == ["yes.jpg"]


def test_nan_scores_sort_last_too():
    rows = [{"filename": "nan.jpg", "score_final": float("nan"),
             "decision": "maybe"},
            {"filename": "ok.jpg", "score_final": 0.1, "decision": "maybe"}]
    assert plan(rows, 1)["keep"] == ["ok.jpg"]


def test_a_target_of_zero_keeps_nothing():
    assert plan(_rows(5), 0)["keep"] == []


# -- reachability -----------------------------------------------------

def test_the_pipeline_applies_it_before_the_export_copy():
    """So scores.csv, the report and the sidecars all agree."""
    from pixcull.pipeline import orchestrator
    src = inspect.getsource(orchestrator.run_pipeline)
    applied = src.index("_apply_target(_recs, int(keep_n))")
    exported = src.index('df_export = df.drop(columns=["embedding"]')
    assert applied < exported


def test_the_cli_exposes_it():
    from pixcull import cli
    src = inspect.getsource(cli)
    assert '"--keep-n"' in src
    assert "keep_n=keep_n," in src
