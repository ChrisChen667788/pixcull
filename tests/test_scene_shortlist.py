"""v3.13 — this stretch's best five, and whether any of them is good.

The scenes endpoint segmented a run chronologically and returned each
scene's `filenames` as a flat unsorted list.  So "show me this stretch's
best five" — the interaction Narrative's Scenes View is built around —
was something a client had to reimplement by joining scenes to rows.

The trap is that ranking inside a scene rewards exactly what the global
ranking rewards.  A stretch of uniformly weak frames still yields five
"best" ones, and a UI that renders them as a shortlist has invented five
recommendations out of a bad ten minutes.
"""
import inspect

from pixcull.report import serve_app
from pixcull.report.serve_app import scene_shortlist

ROWS = {
    "a.jpg": {"score_final": 0.91, "decision": "keep"},
    "b.jpg": {"score_final": 0.55, "decision": "maybe"},
    "c.jpg": {"score_final": 0.20, "decision": "cull"},
    "d.jpg": {},                       # never scored
}


def test_candidates_come_back_best_first():
    got = scene_shortlist(["c.jpg", "a.jpg", "b.jpg"], ROWS, 3)
    assert [c["filename"] for c in got["top"]] == ["a.jpg", "b.jpg", "c.jpg"]


def test_a_shortlist_of_nothing_good_says_so():
    """The flag is the whole honest half. Without it a caller renders
    five recommendations out of a bad stretch."""
    got = scene_shortlist(["b.jpg", "c.jpg"], ROWS, 2)
    assert got["none_is_keep"] is True


def test_a_shortlist_containing_a_keep_does_not_raise_the_flag():
    assert scene_shortlist(["a.jpg", "c.jpg"], ROWS, 2)["none_is_keep"] is False


def test_each_candidate_carries_its_own_verdict_and_score():
    """So the caller can show what the frame actually is, rather than
    only that it came top of a list."""
    top = scene_shortlist(["a.jpg"], ROWS, 1)["top"][0]
    assert top["decision"] == "keep" and top["score_final"] == 0.91


def test_an_unscored_frame_sorts_last_and_is_not_dropped():
    """It is part of the scene. Removing it makes the scene look smaller
    than it was."""
    got = scene_shortlist(["d.jpg", "c.jpg"], ROWS, 2)
    assert [c["filename"] for c in got["top"]] == ["c.jpg", "d.jpg"]
    assert got["top"][1]["score_final"] is None


def test_ties_break_deterministically():
    rows = {"x.jpg": {"score_final": 0.5}, "y.jpg": {"score_final": 0.5}}
    a = scene_shortlist(["y.jpg", "x.jpg"], rows, 2)
    b = scene_shortlist(["x.jpg", "y.jpg"], rows, 2)
    assert a["top"] == b["top"]


def test_asking_for_more_than_the_scene_has_returns_what_it_has():
    assert len(scene_shortlist(["a.jpg"], ROWS, 5)["top"]) == 1


def test_n_below_one_is_clamped_rather_than_returning_nothing():
    assert len(scene_shortlist(["a.jpg", "b.jpg"], ROWS, 0)["top"]) == 1


# -- the endpoint -----------------------------------------------------

def test_the_shortlist_is_opt_in_so_existing_clients_see_no_change():
    src = inspect.getsource(serve_app)
    assert 'qp.get("top_n", ["0"])[0]' in src
    assert "if top_n:" in src


def test_top_n_is_bounded():
    """A client asking for 5,000 candidates per scene would turn a
    summary endpoint into a second copy of the whole run."""
    src = inspect.getsource(serve_app)
    assert "top_n = max(0, min(20, top_n))" in src
