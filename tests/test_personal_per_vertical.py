"""v3.8 — one taste per kind of shoot, and a guard against several thin ones.

`Example` carried axes, decision and run_id.  Not the vertical.  So every
correction pooled into one profile, and a photographer who shoots weddings
and wildlife got the average of two tastes that disagree by design:
wedding corrections forgive soft technical for emotion, wildlife
corrections do the opposite, and the mean forgives neither.

The risk in fixing it is the mirror image — splitting an already-small
correction set produces several profiles fitted to noise, and a profile
fitted to noise looks exactly like a profile.
"""
from pixcull.scoring.personal_learn import (
    MIN_PER_VERTICAL, POOLED, Example, evaluate_by_vertical, learn_profiles,
    profile_for, split_by_vertical,
)


def _rows(n, vertical, decision="keep", stars=4.0, run="r"):
    return [Example({"technical": stars, "subject": stars,
                     "composition": stars, "light": stars,
                     "moment": stars, "aesthetic": stars},
                    decision, run_id=f"{run}{i % 3}", vertical=vertical)
            for i in range(n)]


def test_the_example_carries_the_vertical():
    e = Example({}, "keep", vertical="wedding")
    assert e.vertical == "wedding"


def test_unlabelled_corrections_are_not_pooled_into_their_own_taste():
    """An unlabelled correction is one whose shoot type nobody recorded.
    Treating "unknown" as a vertical fits a profile to a coincidence."""
    got = split_by_vertical(_rows(5, "") + _rows(5, "   ") + _rows(5, "sport"))
    assert set(got) == {"sport"}


def test_a_thin_vertical_gets_no_profile_of_its_own():
    """Absent, not thin. An absent key makes the caller fall back; a thin
    profile makes it confident."""
    profs = learn_profiles(_rows(MIN_PER_VERTICAL - 1, "wildlife"))
    assert set(profs) == {POOLED}


def test_a_vertical_that_clears_the_bar_gets_its_own():
    profs = learn_profiles(_rows(MIN_PER_VERTICAL, "wedding"))
    assert "wedding" in profs and POOLED in profs


def test_the_pooled_profile_always_exists_as_the_fallback():
    profs = learn_profiles(_rows(3, "sport"))
    assert profs[POOLED] is not None
    assert profile_for(profs, "sport") is profs[POOLED]
    assert profile_for(profs, None) is profs[POOLED]
    assert profile_for(profs, "never-seen") is profs[POOLED]


def test_a_vertical_with_its_own_profile_uses_it():
    profs = learn_profiles(_rows(MIN_PER_VERTICAL, "wedding"))
    assert profile_for(profs, "wedding") is profs["wedding"]
    assert profile_for(profs, "wedding") is not profs[POOLED]


# -- the measurement refuses rather than returning a flattering zero --

def test_one_eligible_vertical_is_refused_not_scored():
    """With one vertical the pooled profile IS the per-vertical profile,
    so a delta of 0.0 would be an artefact printed as a finding."""
    out = evaluate_by_vertical(_rows(MIN_PER_VERTICAL + 5, "wedding")
                               + _rows(4, "sport"))
    assert out["refused"]
    assert "delta" not in out
    assert out["verticals_eligible"] == ["wedding"]


def test_the_refusal_says_what_it_saw():
    out = evaluate_by_vertical(_rows(10, "wedding") + _rows(4, "sport"))
    assert out["verticals_seen"] == {"sport": 4, "wedding": 10}


def test_two_eligible_verticals_produce_a_comparison():
    exs = (_rows(MIN_PER_VERTICAL + 4, "wedding", "keep", 4.5)
           + _rows(MIN_PER_VERTICAL + 4, "wildlife", "cull", 1.5))
    out = evaluate_by_vertical(exs)
    assert out["refused"] is None
    assert set(out["verticals_eligible"]) == {"wedding", "wildlife"}
    assert "pooled_f1" in out and "per_vertical_f1" in out
    assert out["delta"] == round(out["per_vertical_f1"]
                                 - out["pooled_f1"], 3)


def test_the_pooled_arm_trains_on_the_other_verticals_too():
    """That is the comparison that matters: are the other verticals'
    corrections helping this one, or diluting it. A pooled arm trained
    only within the vertical would be the per-vertical arm twice."""
    import inspect
    from pixcull.scoring import personal_learn
    src = inspect.getsource(personal_learn.evaluate_by_vertical)
    assert "train_all = [e for e in exs if e not in test]" in src


def test_gather_reads_the_shoot_type_that_was_already_in_the_row():
    import inspect
    from pixcull.scoring import personal_learn
    src = inspect.getsource(personal_learn.gather_examples_from_runs)
    assert 'row.get("vertical")' in src and 'row.get("scene")' in src
    assert "vertical=vmap.get(f" in src
