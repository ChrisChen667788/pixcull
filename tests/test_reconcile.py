"""v3.27 — the return leg, and refusing to score the client.

v3.0 kept client picks in their own file and never merged them into the
photographer's record.  That was right, and it left the loop open: picks
come back and the photographer compares 400 rows by hand to find the
fifteen where they and the client disagree.

The framing is the design.  The client is the client.  A tool that
presents their choices as errors — "client picked a reject", a conflict
count, an agreement rate — is worse than no tool, because the
photographer cannot show it to anyone and will stop opening it.
"""
import inspect

from pixcull import reconcile as R

ROWS = [
    {"filename": "both_wanted.jpg", "decision": "keep"},
    {"filename": "client_rescued.jpg", "decision": "cull"},
    {"filename": "you_starred.jpg", "decision": "keep"},
    {"filename": "untouched_maybe.jpg", "decision": "maybe"},
    {"filename": "neither.jpg", "decision": "cull"},
]
PICKED = ["both_wanted.jpg", "client_rescued.jpg"]


def test_a_frame_the_client_rescued_needs_a_call():
    got = R.reconcile(ROWS, PICKED)
    names = [e["filename"] for e in got[R.CLIENT_WANTS_ONE_YOU_SET_ASIDE]]
    assert names == ["client_rescued.jpg"]


def test_a_frame_you_starred_and_they_passed_over_needs_a_call():
    got = R.reconcile(ROWS, PICKED)
    names = [e["filename"] for e in got[R.YOUR_PICK_WENT_UNCHOSEN]]
    assert names == ["you_starred.jpg"]


def test_agreement_is_dropped_not_paginated():
    """A frame both wanted is done; a frame neither wanted is done. That
    is the point of the view, not an optimisation of it."""
    got = R.reconcile(ROWS, PICKED)
    surfaced = R.needs_your_call(ROWS, PICKED)
    assert "both_wanted.jpg" not in surfaced
    assert "neither.jpg" not in surfaced
    assert got["n_settled"] == 3


def test_a_maybe_the_client_did_not_touch_is_not_a_disagreement():
    """`maybe` means the photographer had not decided either. Surfacing
    it would fill the view with rows nobody disagreed about."""
    assert "untouched_maybe.jpg" not in R.needs_your_call(ROWS, PICKED)


def test_no_picks_at_all_still_surfaces_your_keeps():
    """Before the client has answered, "nothing is settled" is the
    truthful state — not "you agree on everything"."""
    got = R.reconcile(ROWS, [])
    assert [e["filename"] for e in got[R.YOUR_PICK_WENT_UNCHOSEN]] == [
        "both_wanted.jpg", "you_starred.jpg"]
    assert got[R.CLIENT_WANTS_ONE_YOU_SET_ASIDE] == []


def test_a_full_agreement_reports_nothing_to_do():
    got = R.reconcile([{"filename": "a.jpg", "decision": "keep"}], ["a.jpg"])
    assert got["n_needs_your_call"] == 0


def test_rows_without_a_filename_are_skipped():
    got = R.reconcile([{"decision": "keep"}, {"filename": "", "decision": "keep"}],
                      [])
    assert got["n_needs_your_call"] == 0 and got["n_settled"] == 0


# -- the part that is about people, not code --------------------------

def test_nothing_here_computes_a_score_on_the_client():
    """An agreement rate is a number about how often the client was
    "right". It must not exist, not even unexported."""
    import ast
    tree = ast.parse(inspect.getsource(R))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            node.value.value = ""      # the module explains itself at length
    code = ast.unparse(tree)
    for forbidden in ("agreement_rate", "conflict_rate", "accuracy",
                      "client_error", "n_wrong"):
        assert forbidden not in code, f"{forbidden} in reconcile.py"


def test_the_categories_are_named_as_actions_not_verdicts():
    """"client picked a reject" is a sentence a photographer cannot show
    to the person who said it."""
    for key in (R.CLIENT_WANTS_ONE_YOU_SET_ASIDE, R.YOUR_PICK_WENT_UNCHOSEN):
        for loaded in ("reject", "error", "wrong", "conflict", "bad"):
            assert loaded not in key


def test_the_chinese_labels_stay_neutral():
    for text in R.LABELS_ZH.values():
        for loaded in ("错", "冲突", "问题", "废片"):
            assert loaded not in text, f"loaded wording: {text}"


def test_the_empty_state_does_not_congratulate_anybody():
    assert "没有出入" in R.LABELS_ZH["empty"]


# -- reachability -----------------------------------------------------

def test_the_endpoint_is_routed_and_returns_the_labels():
    from pixcull.report import serve_app
    src = inspect.getsource(serve_app)
    assert '("/reconcile/", "_serve_reconcile", "tail", ())' in src
    assert 'got["labels"] = LABELS_ZH' in src
