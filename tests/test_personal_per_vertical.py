"""v3.8 — one taste per kind of shoot, and a guard against several thin ones.

`Example` carried axes, decision and run_id.  Not the vertical.  So every
correction pooled into one profile, and a photographer who shoots weddings
and wildlife got the average of two tastes that disagree by design:
wedding corrections forgive soft technical for emotion, wildlife
corrections do the opposite, and the mean forgives neither.

The risk in fixing it is the mirror image — splitting an already-small
correction set produces several profiles fitted to noise, and a profile
fitted to noise looks exactly like a profile.

Measured in v3.99 (scripts/measure_generalisation.py, 2026-10-29): over the
owner's 728 blind labels only portrait was shot more than once, and held out
a shoot at a time the portrait profile agrees with the owner on 63.8%,
against 75.1% for one profile and 83.9% for none. The comparison as v3.8
shipped it drew its folds from the shoot the arm learned from and said
+0.072. It holds out whole shoots now.
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


def _spy_learn(monkeypatch):
    """Record what each learn_profile call was trained on."""
    from pixcull.scoring import personal_learn as pl
    seen, real = [], pl.learn_profile
    monkeypatch.setattr(pl, "learn_profile",
                        lambda exs: seen.append(list(exs)) or real(exs))
    return seen


def test_the_pooled_arm_trains_on_the_other_verticals_too(monkeypatch):
    """That is the comparison that matters: are the other verticals'
    corrections helping this one, or diluting it. A pooled arm trained
    only within the vertical would be the per-vertical arm twice.

    It was held by grepping the source for the line that built the arm;
    the line is gone (v3.99) and the behaviour is what is asserted now."""
    seen = _spy_learn(monkeypatch)
    exs = (_rows(MIN_PER_VERTICAL + 4, "wedding", "keep", 4.5, run="w")
           + _rows(MIN_PER_VERTICAL + 4, "wildlife", "cull", 1.5, run="v"))
    evaluate_by_vertical(exs, folds=4)
    assert any({e.vertical for e in tr} == {"wedding", "wildlife"} for tr in seen)


# -- v3.99: the shipped comparison measured memory -----------------------


def _shoots(vertical, shoots, n, decision="keep", stars=4.0, machine=""):
    """`shoots` whole shoots of one vertical, n corrections each."""
    return [Example({a: stars for a in ("technical", "subject", "composition",
                                        "light", "moment", "aesthetic")},
                    decision, run_id=f"{vertical}-{s}", vertical=vertical,
                    machine=machine)
            for s in range(shoots) for _ in range(n)]


def test_with_shoots_recorded_a_fold_is_a_whole_shoot(monkeypatch):
    """A stride fold sat beside the frames the per-vertical arm learned
    from, same light, same day, as evaluate() did before v2.83."""
    seen = _spy_learn(monkeypatch)
    exs = _shoots("portrait", 3, 40) + _shoots("landscape", 1, 40)
    out = evaluate_by_vertical(exs)
    assert out["grouped"] is True
    assert out["verticals_measured"] == ["portrait"]
    assert out["fold_groups"] == [("portrait", f"portrait-{s}") for s in range(3)]
    assert out["fold_n"] == [40, 40, 40]
    # Neither arm ever learned from the shoot it was tested on.
    for (_v, held), (pooled, per) in zip(out["fold_groups"],
                                         zip(seen[0::2], seen[1::2])):
        assert all(e.run_id != held for e in pooled + per)


def test_a_vertical_shot_once_is_named_not_measured():
    """Grouped, it has no other shoot of its own kind to learn from."""
    out = evaluate_by_vertical(_shoots("portrait", 2, 40) + _shoots("landscape", 1, 40))
    assert out["verticals_unmeasured"] == ["landscape"]


def test_one_shoot_per_vertical_falls_back_to_stride_and_says_so():
    """The 2026-09 correction set: 79 and 79, one shoot each. `readiness()`
    said ready; across shoots there was nothing to compare."""
    out = evaluate_by_vertical(_shoots("portrait", 1, 40) + _shoots("landscape", 1, 40))
    assert out["refused"] is None and out["grouped"] is False
    assert out["fold_groups"] is None


def test_two_equal_corrections_are_two_corrections(monkeypatch):
    """`e not in test` compared by value: a second photograph with the same
    stars and verdict was dropped from the pooled arm with the first."""
    seen = _spy_learn(monkeypatch)
    rows = [Example({"technical": 4}, "keep", vertical=v) for v in ("a", "b")
            for _ in range(MIN_PER_VERTICAL + 10)]
    evaluate_by_vertical(rows, folds=4)
    pooled_first = seen[0]
    assert len(pooled_first) == len(rows) - len(rows[0:MIN_PER_VERTICAL + 10][0::4])


def test_a_thin_vertical_decides_with_the_pooled_profile():
    """learn_profiles gives a vertical under MIN_PER_VERTICAL no profile of
    its own, so the per-vertical arm must not invent one. The two kinds
    differ here, so a profile of its own would decide differently."""
    # The machine called every portrait maybe and every landscape keep, so
    # a portrait profile of its own lowers the bar (-0.08) where the
    # pooled one, keeping as much as the machine, does not move it.
    def both(n):
        return (_shoots("portrait", 3, n, "keep", 3.0, machine="maybe")
                + _shoots("landscape", 3, n, "cull", 1.0, machine="keep"))
    out = evaluate_by_vertical(both(12))
    # 24 to learn from per held-out shoot, under the bar: identical arms.
    assert out["fold_deltas"] == [0.0] * 6
    # ...and the same corrections over the bar do make a difference.
    assert any(evaluate_by_vertical(both(20))["fold_deltas"])


def test_the_held_out_shoot_is_out_of_the_pooled_arm_whole(monkeypatch):
    """Keyed by scene label, one shoot holds several verticals. Testing its
    portrait frames, the pooled arm must not learn from its landscape ones:
    same light, same day."""
    seen = _spy_learn(monkeypatch)
    exs = []
    for s in range(2):
        for v in ("portrait", "landscape"):
            exs += [Example({"technical": 4.0}, "keep", run_id=f"shoot-{s}", vertical=v)
                    for _ in range(40)]
    out = evaluate_by_vertical(exs)
    assert out["grouped"] is True and len(out["fold_groups"]) == 4
    for (_v, held), pooled in zip(out["fold_groups"], seen[0::2]):
        assert all(e.run_id != held for e in pooled)


def test_cull_recall_is_reported_beside_keep_f1():
    exs = (_shoots("portrait", 2, 20, "keep", 4.5) + _shoots("portrait", 2, 20, "cull", 1.0)
           + _shoots("landscape", 2, 20, "cull", 1.5))
    out = evaluate_by_vertical(exs)
    assert out["pooled_cull_recall"] is not None
    assert out["per_vertical_cull_recall"] is not None


def test_gather_reads_the_shoot_type_that_was_already_in_the_row():
    import inspect
    from pixcull.scoring import personal_learn
    src = inspect.getsource(personal_learn.gather_examples_from_runs)
    assert 'row.get("vertical")' in src and 'row.get("scene")' in src
    assert "vertical=vmap.get(f" in src
