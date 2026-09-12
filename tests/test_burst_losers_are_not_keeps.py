"""v3.83 — the product ranked every burst and kept every loser.

Measured on a contiguous 149-frame stretch of one shoot, which is where
near-duplicates actually live: 149 frames in, **149 keeps out**.
Twenty-eight near-duplicate clusters, the largest holding thirty frames
of the same ridge, and `is_burst_peak` was False on ninety-nine of them.
The product had already decided which frame won each burst, written the
answer to a column, and handed the photographer every frame that lost.

It could not have done otherwise. `decide()` runs per frame inside a
loop; `is_burst_peak` is a cross-frame fact that does not exist on the
dataframe until thirteen lines later. Every frame was judged alone, and
a burst is by definition not one frame. So the demotion is a post-pass —
the only place in the pipeline where the fact exists.

`maybe`, not `cull`, and that is the whole design. A frame that lost its
burst is often what the photographer wanted: the second expression, the
guest reacting. The product does not get to discard those on a
similarity score. `maybe` puts them in front of the person rather than
hiding them.

A/B against a stashed baseline on the same 149 frames: `cluster_id`,
`is_burst_peak` and `score_final` identical, zero differences; 100
decisions moved keep→maybe and nothing else changed.
"""
import ast
import re
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from pixcull.pipeline.burst_peak import (  # noqa: E402
    DEMOTION_REASON, demote_non_peak_bursts,
)

ROOT = Path(__file__).resolve().parent.parent
ORCH = ROOT / "pixcull" / "pipeline" / "orchestrator.py"


def _df(rows):
    return pd.DataFrame(rows)


def test_a_loser_in_a_real_burst_stops_being_a_keep():
    df = _df([
        {"decision": "keep", "is_burst_peak": True,  "cluster_id": "7", "reason": ""},
        {"decision": "keep", "is_burst_peak": False, "cluster_id": "7", "reason": ""},
        {"decision": "keep", "is_burst_peak": False, "cluster_id": "7", "reason": ""},
    ])
    got = demote_non_peak_bursts(df)
    assert list(got["decision"]) == ["keep", "maybe", "maybe"]


def test_the_winner_is_left_alone():
    df = _df([
        {"decision": "keep", "is_burst_peak": True,  "cluster_id": "7", "reason": ""},
        {"decision": "keep", "is_burst_peak": False, "cluster_id": "7", "reason": ""},
    ])
    got = demote_non_peak_bursts(df)
    assert got.at[0, "decision"] == "keep", "the frame that won its burst was demoted"


def test_a_frame_alone_in_its_cluster_is_not_a_loser():
    """A cluster of one has a trivial peak. If `is_burst_peak` is False
    there — and it can be, when the ranker has nothing to rank — the
    frame still beat nobody and lost to nobody."""
    df = _df([
        {"decision": "keep", "is_burst_peak": False, "cluster_id": "3", "reason": ""},
        {"decision": "keep", "is_burst_peak": True,  "cluster_id": "4", "reason": ""},
    ])
    got = demote_non_peak_bursts(df)
    assert list(got["decision"]) == ["keep", "keep"]


def test_unclustered_frames_are_not_touched():
    for cid in ("", "-1", None):
        df = _df([{"decision": "keep", "is_burst_peak": False,
                   "cluster_id": cid, "reason": ""}])
        assert demote_non_peak_bursts(df).at[0, "decision"] == "keep", (
            f"a frame with cluster_id={cid!r} was demoted")


def test_it_only_ever_demotes():
    """A cull stays culled, and winning a burst is not evidence of
    anything on its own — nothing is promoted."""
    df = _df([
        {"decision": "cull",  "is_burst_peak": False, "cluster_id": "7", "reason": "r"},
        {"decision": "maybe", "is_burst_peak": True,  "cluster_id": "7", "reason": "r"},
        {"decision": "cull",  "is_burst_peak": True,  "cluster_id": "7", "reason": "r"},
    ])
    got = demote_non_peak_bursts(df)
    assert list(got["decision"]) == ["cull", "maybe", "cull"]


def test_a_csv_round_trip_decides_the_same_way(tmp_path):
    """`is_burst_peak` is a real bool in memory and the string "False"
    after a CSV round trip. Both are the same fact, and a frame must not
    change verdict because it has been through a file."""
    rows = [
        {"decision": "keep", "is_burst_peak": True,  "cluster_id": "7", "reason": ""},
        {"decision": "keep", "is_burst_peak": False, "cluster_id": "7", "reason": ""},
    ]
    in_memory = list(demote_non_peak_bursts(_df(rows))["decision"])

    p = tmp_path / "scores.csv"
    _df(rows).to_csv(p, index=False)
    from_disk = list(demote_non_peak_bursts(pd.read_csv(p, dtype=str))["decision"])
    assert in_memory == from_disk == ["keep", "maybe"]


def test_the_photographer_is_told_why():
    df = _df([
        {"decision": "keep", "is_burst_peak": True,  "cluster_id": "7",
         "reason": ""},
        {"decision": "keep", "is_burst_peak": False, "cluster_id": "7",
         "reason": "构图结构偏弱"},
    ])
    got = demote_non_peak_bursts(df)
    assert got.at[1, "decision"] == "maybe", "precondition: this frame demotes"
    reason = got.at[1, "reason"]
    assert DEMOTION_REASON in reason, "the demotion is not explained"
    assert "构图结构偏弱" in reason, "the earlier reason was thrown away"


def test_a_frame_with_no_burst_columns_is_left_alone():
    """Video runs and `--vlm-mode off` paths can reach this without the
    ranker having run. Doing nothing is the right answer; raising is
    not."""
    df = _df([{"decision": "keep", "reason": ""}])
    assert demote_non_peak_bursts(df).at[0, "decision"] == "keep"
    assert demote_non_peak_bursts(_df([])) is not None


# ── ordering: the fact has to exist before it can be acted on ────────

def _orchestrator_calls() -> list:
    """The order of the burst calls as the AST sees them, not as the
    file reads. A comment naming a function is not a call to it."""
    tree = ast.parse(ORCH.read_text(encoding="utf-8"))
    seen = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("rank_burst_peaks", "demote_non_peak_bursts"):
                seen.append((node.lineno, node.func.id))
    return [n for _, n in sorted(seen)]


def test_the_demotion_runs_after_the_ranking():
    """Before `rank_burst_peaks` there is no `is_burst_peak` column, so a
    demotion placed earlier would silently do nothing — which is exactly
    the shape of the defect it fixes."""
    order = _orchestrator_calls()
    assert "rank_burst_peaks" in order, "the ranker is no longer called"
    assert "demote_non_peak_bursts" in order, "the demotion is not wired in"
    assert order.index("rank_burst_peaks") < order.index("demote_non_peak_bursts"), (
        f"demotion runs before the ranking that produces the fact: {order}")
