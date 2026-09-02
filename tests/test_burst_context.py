"""v3.3 — the critique is told a sibling exists, and never shown it.

The failure this replaces: a frame that lost to its burst sibling was
told so as a float ("the next burst frame is 0.31 sharper"), and the
prompt that writes the actual critique had no burst section at all. So
the model answering "why is this being discarded" did not know the frame
had lost a comparison, and had to find some other fault.

The second failure this must not introduce: naming the winning frame and
letting the model imagine it. The pixels are not sent, so the prompt has
to say so.
"""
import inspect

from pixcull.scoring.burst_context import (
    MIN_CLUSTER, burst_note, index_clusters,
)

PEAK = {"cluster_id": 7, "filename": "a.jpg", "is_burst_peak": True,
        "burst_peak_reason": "最锐 +1.6σ"}
LOSER = {"cluster_id": 7, "filename": "b.jpg", "is_burst_peak": False}
THIRD = {"cluster_id": 7, "filename": "c.jpg", "is_burst_peak": False}
LONE = {"cluster_id": 9, "filename": "d.jpg", "is_burst_peak": True}


def test_loser_is_told_it_lost_and_on_what_grounds():
    cl = index_clusters([PEAK, LOSER, THIRD])
    note = burst_note(LOSER, cl)
    assert "3 张" in note, "the cluster size is the fact that makes it a burst"
    assert "最锐 +1.6σ" in note, "the winner's measured grounds must be relayed"


def test_loser_is_forbidden_from_describing_the_frame_it_cannot_see():
    """Without this the model writes confident sentences about a
    photograph nobody showed it."""
    note = burst_note(LOSER, index_clusters([PEAK, LOSER, THIRD]))
    assert "你看不到那一帧" in note
    assert "不要描述它" in note


def test_loser_may_say_the_frame_is_fine_and_simply_lost():
    """A burst loser is frequently a good photograph. A prompt that only
    asks for faults gets invented faults."""
    note = burst_note(LOSER, index_clusters([PEAK, LOSER, THIRD]))
    assert "输在比较上" in note


def test_winner_is_not_asked_to_repeat_that_it_won():
    note = burst_note(PEAK, index_clusters([PEAK, LOSER, THIRD]))
    assert "被选中" in note
    assert "不要只是重复" in note


def test_a_cluster_of_one_produces_no_note():
    """Otherwise every single photograph in the shoot carries burst
    boilerplate, and the section stops meaning anything."""
    assert burst_note(LONE, index_clusters([PEAK, LOSER, THIRD, LONE])) == ""
    assert MIN_CLUSTER >= 2


def test_rows_without_a_cluster_are_not_pooled_into_one_giant_burst():
    recs = [{"filename": "x.jpg"}, {"filename": "y.jpg", "cluster_id": None},
            {"filename": "z.jpg", "cluster_id": ""}]
    assert index_clusters(recs) == {}
    assert burst_note(recs[0], {}) == ""


def test_note_is_a_string_never_none_so_it_cannot_render_into_a_prompt():
    assert burst_note({"cluster_id": 999}, {}) == ""
    assert isinstance(burst_note(LONE, {}), str)


# -- the reachability half -------------------------------------------

def test_prompt_carries_the_note_and_is_unchanged_without_one():
    from pixcull.scoring.m3_advice import build_prompt
    with_note = build_prompt({}, {}, "cull", burst="连拍组:测试标记。")
    without = build_prompt({}, {}, "cull")
    assert "连拍组:测试标记。" in with_note
    assert "None" not in without and "{burst}" not in without


def test_the_advice_pass_actually_builds_and_passes_the_note():
    """The defect class this repo keeps hitting is a capability that is
    written and never reached. Assert the call site, not just the helper."""
    src = inspect.getsource(
        __import__("pixcull.report.serve_app", fromlist=["x"]))
    assert "from pixcull.scoring.burst_context import index_clusters" in src
    assert "burst_note(rec or row, clusters)" in src
    # Not "burst=note)" — the closing paren belongs to whatever argument
    # happens to be last, and v3.4 added one after it. Asserting on
    # punctuation makes a passing test fail for a reason that is not the
    # behaviour it exists to protect.
    assert "burst=note" in src
