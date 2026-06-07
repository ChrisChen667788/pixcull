"""v2.4-P0-2 — tests for learning a taste profile from local corrections."""
import random

from pixcull.scoring.personal_learn import (
    AXES,
    Example,
    aggregate_prefs,
    axis_weights,
    decide,
    evaluate,
    gather_examples_from_runs,
    learn_profile,
)


def _composition_lover(n=160, seed=7):
    """A synthetic shooter whose taste is driven by composition: keep iff
    composition is strong, regardless of the other (noisy) axes."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        ax = {a: rng.randint(1, 5) for a in AXES}
        comp = ax["composition"]
        d = "keep" if comp >= 4 else ("maybe" if comp == 3 else "cull")
        out.append(Example(axes=ax, decision=d))
    return out


def test_learn_recovers_the_preference():
    prof = learn_profile(_composition_lover())
    assert prof.most_cared_axis == "composition"
    w = axis_weights(prof)
    assert w["composition"] == max(w.values())


def test_personalization_beats_generic_on_held_out():
    """The moat: on held-out corrections, the personalised keep-F1 must be
    at least the generic one (and here, better)."""
    ev = evaluate(_composition_lover(), folds=4)
    assert ev["folds"] == 4
    assert ev["personal_f1"] >= ev["generic_f1"]   # ≥ generic on the taste
    assert ev["personal_f1"] > 0.6                  # actually learned it
    assert ev["delta"] >= 0.0


def test_aggregate_prefs_shape():
    exs = [Example({a: 5 for a in AXES}, "keep"),
           Example({a: 1 for a in AXES}, "cull")]
    p = aggregate_prefs(exs)
    assert p["total_human_annotations"] == 2
    assert p["scene_decision_counts"]["all"] == {"keep": 1, "maybe": 0, "cull": 1}
    assert p["avg_rubric_when"]["keep"]["composition"] == 5.0


def test_decide_generic_vs_personal():
    prof = learn_profile(_composition_lover())
    strong_comp = {"technical": 2, "subject": 2, "composition": 5,
                   "light": 2, "moment": 2, "aesthetic": 2}
    # composition-weighted → keep; the equal-weight generic would not.
    assert decide(strong_comp, profile=prof) == "keep"
    assert decide(strong_comp, profile=None) != "keep"


def test_gather_from_runs(tmp_path):
    run = tmp_path / "run1"
    run.mkdir()
    (run / "scores.csv").write_text(
        "filename,rubric_technical_stars,rubric_subject_stars,"
        "rubric_composition_stars,rubric_light_stars,rubric_moment_stars,"
        "rubric_aesthetic_stars\n"
        "a.jpg,3,3,5,3,3,3\nb.jpg,2,2,1,2,2,2\n")
    (run / "annotations.jsonl").write_text(
        '{"filename":"a.jpg","overall_label":"keep"}\n'
        '{"filename":"b.jpg","overall_label":"cull"}\n')
    exs = gather_examples_from_runs(tmp_path)
    assert len(exs) == 2
    a = next(e for e in exs if e.axes["composition"] == 5)
    assert a.decision == "keep"


def test_gather_empty_when_no_runs(tmp_path):
    assert gather_examples_from_runs(tmp_path / "nope") == []


def test_cli_personalize_show_and_reset(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    import pixcull.cli as cli
    monkeypatch.setattr(cli, "_PROFILE_PATH", tmp_path / "personal_profile.json")
    r = CliRunner().invoke(cli.app, ["personalize", "show"])
    assert r.exit_code == 1                      # no profile yet
    r = CliRunner().invoke(cli.app, ["personalize", "reset"])
    assert r.exit_code == 0                       # nothing to reset, but clean
