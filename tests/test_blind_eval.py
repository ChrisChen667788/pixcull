"""v2.80 — the harness that decides whether a critique change was real.

Every guard here exists because the alternative is this project quoting
its own noise. Agreement on written critique is historically poor; a
margin between two arms measured by raters who disagree with each other
is a percentage sign wrapped around a coin flip.
"""
import pytest

from pixcull.scoring.blind_eval import (
    Ballot, Item, build_sheet, sheet_digest, verdict, write_sheet,
)


def _pairs(n, a_text="A critique", b_text="B critique"):
    return [(f"p{i}", f"{a_text} {i}", f"{b_text} {i}") for i in range(n)]


def _sweep(sheet, raters, pick_arm):
    """Every rater votes for whichever side carries ``pick_arm``."""
    out = []
    for r in raters:
        for it in sheet:
            side = "left" if it.left_arm == pick_arm else "right"
            out.append(Ballot(it.photo_id, r, side))
    return out


# ---------------------------------------------------------------- blinding


def test_the_sheet_never_carries_the_arm_names():
    sheet = build_sheet(_pairs(20), "old", "new", seed=1)
    written = write_sheet(sheet, __import__("pathlib").Path("/tmp/pcsheet.json"), seed=1)
    body = __import__("pathlib").Path("/tmp/pcsheet.json").read_text(encoding="utf-8")
    assert "old" not in body and "new" not in body, \
        "the file a rater opens names the arms"
    assert written


def test_sides_are_shuffled_not_fixed():
    """If arm A is always on the left, a rater learns it by photo three."""
    sheet = build_sheet(_pairs(60), "a", "b", seed=7)
    lefts = sum(1 for it in sheet if it.left_arm == "a")
    assert 15 < lefts < 45, f"arm 'a' took the left side {lefts}/60 times"


def test_the_same_seed_rebuilds_the_same_sheet():
    d1 = sheet_digest(build_sheet(_pairs(30), "a", "b", seed=3))
    d2 = sheet_digest(build_sheet(_pairs(30), "a", "b", seed=3))
    assert d1 == d2


def test_changing_the_sheet_changes_the_digest():
    """Pre-registration only bites if a quiet re-run is detectable."""
    base = sheet_digest(build_sheet(_pairs(30), "a", "b", seed=3))
    assert sheet_digest(build_sheet(_pairs(30), "a", "b", seed=4)) != base
    assert sheet_digest(build_sheet(_pairs(29), "a", "b", seed=3)) != base


# ---------------------------------------------------------------- refusals


def test_one_rater_is_refused():
    sheet = build_sheet(_pairs(200), "old", "new", seed=1)
    v = verdict(sheet, _sweep(sheet, ["r1"], "new"))
    assert v.winner is None and "two raters" in v.refused


def test_too_few_photographs_is_refused():
    sheet = build_sheet(_pairs(40), "old", "new", seed=1)
    v = verdict(sheet, _sweep(sheet, ["r1", "r2"], "new"))
    assert v.winner is None and "below the 100" in v.refused


def test_raters_who_disagree_get_no_winner():
    """The guard that matters. Two raters voting oppositely produce a
    clean-looking 50/50 tally and zero agreement; without this check the
    only thing stopping a declared winner is the tie test, and a third
    rater breaks the tie while agreement stays at chance."""
    sheet = build_sheet(_pairs(150), "old", "new", seed=2)
    ballots = _sweep(sheet, ["r1"], "new") + _sweep(sheet, ["r2"], "old")
    v = verdict(sheet, ballots)
    assert v.winner is None
    assert "agreed" in v.refused
    assert v.agreement == pytest.approx(0.0)


def test_a_real_agreement_declares_the_winner():
    sheet = build_sheet(_pairs(150), "old", "new", seed=5)
    v = verdict(sheet, _sweep(sheet, ["r1", "r2", "r3"], "new"))
    assert v.winner == "new"
    assert v.agreement == pytest.approx(1.0)
    assert v.n == 150


def test_a_tie_is_not_a_winner():
    sheet = build_sheet(_pairs(150), "old", "new", seed=6)
    half = len(sheet) // 2
    ballots = []
    for r in ("r1", "r2"):
        for it in sheet[:half]:
            ballots.append(Ballot(it.photo_id, r, "left" if it.left_arm == "new" else "right"))
        for it in sheet[half:]:
            ballots.append(Ballot(it.photo_id, r, "left" if it.left_arm == "old" else "right"))
    v = verdict(sheet, ballots)
    assert v.winner is None
    assert v.agreement == pytest.approx(1.0), "the raters agreed; the arms tied"


def test_ballots_for_photographs_not_on_the_sheet_are_ignored():
    """A rater working from a stale sheet must not contribute votes to
    this one — that is how a re-run leaks into a pre-registered result."""
    sheet = build_sheet(_pairs(150), "old", "new", seed=8)
    ballots = _sweep(sheet, ["r1", "r2"], "new")
    ballots += [Ballot("ghost", "r1", "left")] * 40
    v = verdict(sheet, ballots)
    assert v.n == 150
    assert sum(v.per_arm.values()) == 300


def test_neither_is_a_real_answer():
    """"Both are equally shallow" must be recordable, or raters are
    forced to invent a preference and the margin becomes fiction."""
    sheet = build_sheet(_pairs(150), "old", "new", seed=9)
    ballots = [Ballot(it.photo_id, r, "neither") for r in ("r1", "r2") for it in sheet]
    v = verdict(sheet, ballots)
    assert v.per_arm == {}
    assert v.agreement == pytest.approx(1.0)
    assert v.winner is None
