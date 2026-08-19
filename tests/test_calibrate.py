"""v2.59 — `pixcull calibrate`, and the negative result it found first.

The rule stack ships one keep/cull threshold for everybody. On a blind
pass it culled 53 of 150 frames while the photographer culled 10.
Calibration is the obvious fix and, measured, it is not one: every one
of those 53 culls fires on a hard flag, which a score shift cannot
touch. The command has to be able to say that.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pixcull.cli import app

_COLS = ["filename", "scene", "flags", "score_final",
         "rubric_technical_stars", "rubric_subject_stars",
         "rubric_composition_stars", "rubric_light_stars",
         "rubric_moment_stars", "rubric_aesthetic_stars"]


def _scores(tmp_path, rows) -> Path:
    p = tmp_path / "scores.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_COLS)
        w.writeheader()
        for fn, flags, sf in rows:
            # NOT `landscape`: decision.py exempts `no_clear_subject` for
            # tiny-subject scenes, so a landscape fixture silently tests
            # nothing. The first draft of this test used one and the
            # branch never fired.
            w.writerow({"filename": fn, "scene": "portrait", "flags": flags,
                        "score_final": sf,
                        **{c: 3 for c in _COLS if c.startswith("rubric_")}})
    return p


def _labels(tmp_path, verdicts, selection="blind") -> Path:
    p = tmp_path / "blind-review.json"
    p.write_text(json.dumps({"selection": selection, "verdicts": verdicts}),
                 encoding="utf-8")
    return p


def test_labels_that_saw_a_verdict_are_refused(tmp_path):
    """Fitting to non-blind labels calibrates you to the rule stack.

    This project did exactly that once: a profile learned from 608
    "corrections" whose labels were the rule's own output concluded the
    photographer culls 20.4% when the blind answer is 6.7% — off by
    3.1x, while the UI said "tuned to you".
    """
    rows = [(f"{i}.jpg", "", 0.8) for i in range(60)]
    s = _scores(tmp_path, rows)
    lab = _labels(tmp_path, {f"{i}.jpg": "keep" for i in range(60)},
                  selection="disagreements")
    res = CliRunner().invoke(app, ["calibrate", "--labels", str(lab),
                                   "--scores", str(s)])
    assert res.exit_code == 1
    assert "not a blind pass" in res.output
    assert "3.1x" in res.output, "the refusal does not say what went wrong"


def test_it_reports_before_it_writes(tmp_path):
    """A profile changes every future run, so writing is opt-in."""
    rows = [(f"{i}.jpg", "", 0.9) for i in range(60)]
    s = _scores(tmp_path, rows)
    lab = _labels(tmp_path, {f"{i}.jpg": "keep" for i in range(60)})
    dest = tmp_path / "profile.json"
    res = CliRunner().invoke(app, ["calibrate", "--labels", str(lab),
                                   "--scores", str(s), "--out", str(dest)])
    assert res.exit_code == 0, res.output
    assert not dest.exists(), "a bare calibrate wrote a profile"
    assert "Report only" in res.output

    res2 = CliRunner().invoke(app, ["calibrate", "--labels", str(lab),
                                    "--scores", str(s), "--out", str(dest),
                                    "--write"])
    assert res2.exit_code == 0, res2.output
    assert dest.exists()
    saved = json.loads(dest.read_text())
    assert saved["label_provenance"] == "blind", (
        "the written profile does not record where its labels came from, "
        "so the v2.57 provenance gate will refuse to apply it")


def test_a_flag_driven_cull_says_the_threshold_cannot_help(tmp_path):
    """The finding, as a test.

    `no_clear_subject` is a hard cull: it fires regardless of score, so
    no shift of the boundary reaches it. Reporting "this fit does
    nothing" without saying why leaves the photographer with a dead end.
    """
    rows = [(f"k{i}.jpg", "", 0.9) for i in range(50)]
    rows += [(f"c{i}.jpg", "no_clear_subject", 0.9) for i in range(20)]
    s = _scores(tmp_path, rows)
    verdicts = {f"k{i}.jpg": "keep" for i in range(50)}
    verdicts.update({f"c{i}.jpg": "keep" for i in range(18)})
    verdicts.update({f"c{i}.jpg": "cull" for i in (18, 19)})
    lab = _labels(tmp_path, verdicts)

    res = CliRunner().invoke(app, ["calibrate", "--labels", str(lab),
                                   "--scores", str(s)])
    assert res.exit_code == 0, res.output
    assert "threshold cannot help" in res.output
    assert "no_clear_subject" in res.output, (
        "the flag doing the culling is not named")
    assert "hard flags" in res.output


def test_the_hard_cull_list_is_not_a_second_copy():
    """Two lists of hard-cull flags is how one goes stale.

    The report needs to name these flags; `decide()` needs to act on
    them. They are the same set, exported once.
    """
    import inspect

    from pixcull.scoring.decision import _HARD_CULL_FLAGS_FOR_REPORT, decide

    body = inspect.getsource(decide)
    for flag in _HARD_CULL_FLAGS_FOR_REPORT:
        assert f'"{flag}"' in body, (
            f"{flag} is in the exported set but decide() no longer treats "
            f"it as a hard cull — the report would name a flag that does "
            f"nothing")


def test_mismatched_inputs_fail_loudly(tmp_path):
    s = _scores(tmp_path, [("a.jpg", "", 0.9)])
    lab = _labels(tmp_path, {"zzz.jpg": "keep"})
    res = CliRunner().invoke(app, ["calibrate", "--labels", str(lab),
                                   "--scores", str(s)])
    assert res.exit_code == 1
    assert "No overlap" in res.output


# ── v2.60 ─────────────────────────────────────────────────────────────

def test_an_unknown_scene_does_not_hard_cull_on_subject(tmp_path):
    """`no_clear_subject` is a claim about what the frame is OF.

    When the classifier could not say what the frame is, that claim is
    unfounded rather than false — and this is the only flag that
    destroys a photograph over a judgement about subject matter. An
    assertion the system says it cannot make must not be grounds for
    the cull.
    """
    from pixcull.config import PixCullConfig
    from pixcull.scoring.decision import Decision, decide

    cfg = PixCullConfig.load()
    # NOT `None` / `""`: a caller who omitted the argument has told us
    # nothing, while a classifier that wrote "unknown" has told us it
    # could not decide. Only the second is evidence, and
    # test_missing_scene_uses_strict_interpretation guards the first.
    for scene in ("unknown", "uncertain"):
        d, _ = decide(0.7, ["no_clear_subject"], cfg, "standard", scene=scene)
        assert d is not Decision.CULL, f"hard-culled on scene={scene!r}"

    # Still load-bearing where the scene IS known and subject matters.
    d, _ = decide(0.7, ["no_clear_subject"], cfg, "standard", scene="portrait")
    assert d is Decision.CULL, "the flag stopped working where it should"


def test_exemptions_are_proposed_only_on_enough_firings(tmp_path):
    """The guard is the whole feature.

    Naming a bad flag is half an answer; the actionable unit is
    (flag, scene). But a scene that fired three times says nothing about
    the scene, and this project has drawn a confident conclusion from a
    handful of rows more than once.
    """
    rows = [(f"k{i}.jpg", "", 0.9) for i in range(50)]
    # 12 firings in `portrait`, none culled → proposable.
    rows += [(f"p{i}.jpg", "no_clear_subject", 0.9) for i in range(12)]
    # 3 firings in `fashion`, none culled → too few to say anything.
    rows += [(f"f{i}.jpg", "no_clear_subject", 0.9) for i in range(3)]
    p = tmp_path / "scores.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_COLS)
        w.writeheader()
        for fn, flags, sf in rows:
            w.writerow({"filename": fn,
                        "scene": "fashion" if fn.startswith("f") else "portrait",
                        "flags": flags, "score_final": sf,
                        **{c: 3 for c in _COLS if c.startswith("rubric_")}})

    verdicts = {fn: "keep" for fn, _, _ in rows}
    for i in range(5):
        verdicts[f"k{i}.jpg"] = "cull"       # a baseline to compare against
    lab = _labels(tmp_path, verdicts)

    res = CliRunner().invoke(app, ["calibrate", "--labels", str(lab),
                                   "--scores", str(p)])
    assert res.exit_code == 0, res.output
    assert "proposed exemptions" in res.output
    assert "portrait" in res.output, "the well-evidenced scene was not proposed"
    assert "fashion" not in res.output.split("proposed exemptions")[1].split(
        "flags that fire")[0], (
        "a scene with 3 firings was proposed — the evidence bar is not "
        "holding, and this is exactly how n=3 becomes a product decision")


def test_a_learned_exemption_reaches_the_decision(tmp_path, monkeypatch):
    """Advertised-but-unreachable is this repo's named recurring defect.

    A profile can carry scene exemptions, `calibrate --write` can put
    them there, and `decide()` can act on them — and none of that is
    worth anything unless the value arrives at the call that produces
    `decision`. Asserted through the real call, not by reading either
    end of the wire.
    """
    from pixcull.config import PixCullConfig
    from pixcull.scoring.decision import Decision, decide
    from pixcull.scoring.personalized import (
        PersonalProfile, load_profile, save_profile,
    )

    cfg = PixCullConfig.load()
    base, _ = decide(0.7, ["no_clear_subject"], cfg, "standard", scene="event")
    assert base is Decision.CULL, "fixture no longer starts from a cull"

    got, _ = decide(0.7, ["no_clear_subject"], cfg, "standard", scene="event",
                    personal_exemptions={"no_clear_subject": ["event"]})
    assert got is not Decision.CULL, "the exemption never reached decide()"

    # It must survive a round trip, or it lasts one process.
    prof = PersonalProfile(
        user_id="local", n_annotations=150, keep_rate=0.93, cull_rate=0.07,
        keep_threshold_shift=-0.02, axis_keep_means={}, axis_cull_means={},
        most_cared_axis=None, label_provenance="blind",
        scene_exemptions={"no_clear_subject": ["event"]})
    p = tmp_path / "profile.json"
    save_profile(prof, p)
    assert load_profile(p).scene_exemptions == {"no_clear_subject": ["event"]}

    # And the orchestrator must hand it to the call that decides.
    import inspect

    from pixcull.pipeline import orchestrator
    src = inspect.getsource(orchestrator.run_pipeline)
    assert "personal_exemptions=_personal_exempt" in src, (
        "the pipeline loads exemptions but never passes them to decide()")


def test_an_exemption_can_only_widen_tolerance(tmp_path):
    """A personal entry must not re-arm a flag the rules already forgave.

    Applied last and only ever subtracting, so the worst a bad profile
    can do is keep a frame — never destroy one that the shipped rules
    would have kept.
    """
    from pixcull.config import PixCullConfig
    from pixcull.scoring.decision import Decision, decide

    cfg = PixCullConfig.load()
    # `landscape` already exempts no_clear_subject globally.
    got, _ = decide(0.7, ["no_clear_subject"], cfg, "standard",
                    scene="landscape",
                    personal_exemptions={"closed_eyes": ["landscape"]})
    assert got is not Decision.CULL

    # A nonsense profile cannot turn a keep into a cull.
    got2, _ = decide(0.9, [], cfg, "standard", scene="portrait",
                     personal_exemptions={"anything": ["portrait"]})
    assert got2 is not Decision.CULL
