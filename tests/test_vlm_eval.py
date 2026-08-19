"""v2.49 — the measurement that gates the positioning rewrite.

The riskiest property of an eval is not that it computes F1 wrong. It is
that it computes F1 *plausibly* wrong and nobody notices, because the
number looks reasonable and there is nothing to compare it against. So
these tests build inputs where the right answer is known by construction
and assert the exact value.

The second-riskiest property is that it only ever says yes. An eval whose
verdict cannot come out negative is not a measurement, it is a rubber
stamp — and this one exists specifically to be allowed to block a
rewrite of 47 public promises.
"""

from __future__ import annotations

import csv

import pytest

from pixcull.config import PixCullConfig
from pixcull.scoring.rubric import RUBRIC_AXES
from pixcull.scoring.vlm_eval import (
    Confusion,
    EvalResult,
    evaluate,
    load_labels,
    render_report,
)
from pixcull.scoring.vlm_judge import VlmAxisScore, VlmVerdict


@pytest.fixture(scope="module")
def cfg():
    return PixCullConfig.load()


class ScriptedJudge:
    """Says exactly what the test tells it to, per filename."""

    def __init__(self, verdicts: dict, technical=4.0, errors=()):
        self.verdicts = verdicts
        self.technical = technical
        self.errors = set(errors)
        self.seen: list[dict] = []

    def score_row(self, row):
        fn = row["filename"]
        self.seen.append(row)
        v = VlmVerdict(filename=fn, model_name="minimax:minimax-m3",
                       axes={a.name: VlmAxisScore(stars=self.technical)
                             for a in RUBRIC_AXES})
        if fn in self.errors:
            v.error = "APIStatusError: 503"
            return v
        v.overall_label = self.verdicts.get(fn, "keep")
        v.overall_rationale = f"because {fn}"
        return v


def _rows(spec):
    """spec: list of (filename, score_final, flags, scene)."""
    return [{"filename": fn, "score_final": str(s), "flags": f,
             "scene": sc, "path": ""}
            for fn, s, f, sc in spec]


def _labels(d):
    return {fn: {"filename": fn, "manual_label": v} for fn, v in d.items()}


# ---------------------------------------------------------------------------
# Arithmetic — verified against hand-computed values
# ---------------------------------------------------------------------------

def test_confusion_arithmetic():
    c = Confusion("keep", tp=8, fp=2, fn=4)
    assert c.precision == pytest.approx(0.8)
    assert c.recall == pytest.approx(2 / 3)
    assert c.f1 == pytest.approx(2 * 0.8 * (2 / 3) / (0.8 + 2 / 3))


def test_confusion_handles_empty_without_dividing_by_zero():
    c = Confusion("cull")
    assert (c.precision, c.recall, c.f1) == (0.0, 0.0, 0.0)


def test_a_perfect_judge_scores_one(cfg):
    """Constructed so the answer is 1.000 and nothing else."""
    rows = _rows([("a.jpg", 0.9, "", "portrait"),
                  ("b.jpg", 0.1, "", "portrait")])
    labels = _labels({"a.jpg": "keep", "b.jpg": "cull"})
    res = evaluate(rows, labels,
                   ScriptedJudge({"a.jpg": "keep", "b.jpg": "cull"}), cfg)
    assert res.vlm_macro_f1 == pytest.approx(1.0)
    assert res.n_scored == 2


def test_an_inverted_judge_scores_zero(cfg):
    rows = _rows([("a.jpg", 0.9, "", "portrait"),
                  ("b.jpg", 0.1, "", "portrait")])
    labels = _labels({"a.jpg": "keep", "b.jpg": "cull"})
    res = evaluate(rows, labels,
                   ScriptedJudge({"a.jpg": "cull", "b.jpg": "keep"}), cfg)
    assert res.vlm_macro_f1 == pytest.approx(0.0)


def test_maybe_is_excluded_from_the_headline(cfg):
    """The human used `maybe` to mean "I am not sure".

    Counting a model as wrong for disagreeing with an explicit shrug
    measures nothing, and with 16 of 608 rows labelled that way it would
    have moved the number enough to matter.
    """
    rows = _rows([("a.jpg", 0.5, "", "portrait")])
    labels = _labels({"a.jpg": "maybe"})
    res = evaluate(rows, labels, ScriptedJudge({"a.jpg": "keep"}), cfg)
    assert res.n_scored == 1
    assert res.vlm_macro_f1 == 0.0     # nothing scorable, not a penalty
    assert res.vlm.get("keep", Confusion("keep")).fp == 0, (
        "a `maybe` row must not count as a wrong `keep`")


# ---------------------------------------------------------------------------
# The verdict must be able to say no
# ---------------------------------------------------------------------------

def test_verdict_says_no_when_m3_is_worse():
    res = EvalResult(n_scored=608, n_label_disagreements=40)
    res.truth_counts = {"keep": 300, "cull": 308}
    res.arm_changes = {"rescue": 40, "primary": 40}
    res.class_disagreements = {"keep": 20, "cull": 20}
    res.rule = {"keep": Confusion("keep", tp=90, fp=10, fn=10),
                "cull": Confusion("cull", tp=90, fp=10, fn=10)}
    res.vlm = {"keep": Confusion("keep", tp=50, fp=50, fn=50),
               "cull": Confusion("cull", tp=50, fp=50, fn=50)}
    # v2.54 — the verdict ranks three modes now, so a test that sets only
    # two is asking about a mode it never configured: an unset `rescue`
    # scores 0.000 and loses for the wrong reason. Give it a losing hand
    # on purpose.
    res.rescue = dict(res.vlm)
    v = res.verdict
    assert "KEEP M3 OPT-IN" in v, v
    assert "noise floor" in v


def test_verdict_refuses_to_call_noise_an_improvement():
    """The failure mode that would make this whole version theatre."""
    res = EvalResult(n_scored=608, n_label_disagreements=40)
    res.truth_counts = {"keep": 300, "cull": 308}
    res.arm_changes = {"rescue": 40, "primary": 40}
    res.class_disagreements = {"keep": 20, "cull": 20}
    same = {"keep": Confusion("keep", tp=90, fp=10, fn=10),
            "cull": Confusion("cull", tp=90, fp=10, fn=10)}
    res.rule = same
    res.vlm = {"keep": Confusion("keep", tp=90, fp=10, fn=10),
               "cull": Confusion("cull", tp=91, fp=10, fn=9)}
    res.rescue = dict(same)
    v = res.verdict
    assert "KEEP M3 OPT-IN" in v, v
    assert "noise floor" in v


def test_verdict_says_yes_only_on_a_real_margin():
    res = EvalResult(n_scored=608, n_label_disagreements=40)
    res.truth_counts = {"keep": 300, "cull": 308}
    res.arm_changes = {"rescue": 40, "primary": 40}
    res.class_disagreements = {"keep": 20, "cull": 20}
    res.rule = {"keep": Confusion("keep", tp=50, fp=50, fn=50),
                "cull": Confusion("cull", tp=50, fp=50, fn=50)}
    res.vlm = {"keep": Confusion("keep", tp=95, fp=5, fn=5),
               "cull": Confusion("cull", tp=95, fp=5, fn=5)}
    res.rescue = dict(res.rule)
    v = res.verdict
    assert "SHIP `vlm_authority=primary`" in v, v


def test_total_failure_is_not_reported_as_a_tie():
    """0 == 0 must read as a broken run, not as parity."""
    res = EvalResult(n_scored=0, n_errors=608)
    assert "NO DATA" in res.verdict
    assert "doctor" in res.verdict


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------

def test_errored_rows_do_not_silently_flatter_m3(cfg):
    """The subtle one.

    If a failed call were simply dropped, M3 would be scored only on the
    rows it managed to answer — and a model that errors on everything
    hard would look *better* than the rule stack, which is scored on all
    of them.

    v2.54 — this used to assert `rule_total > vlm_total`, which made the
    asymmetry a REQUIREMENT and left the very hole the paragraph above
    warns about wide open: fewer rows for the model is exactly how it
    gets scored on an easier subset. Every arm now takes the rule
    stack's own outcome on an errored row, which is what production
    does — a model with no verdict does not override anything. So the
    arms cover identical rows, and a judge that fails on everything ties
    the rule stack instead of beating it.
    """
    rows = _rows([("a.jpg", 0.9, "", "p"), ("b.jpg", 0.1, "", "p"),
                  ("c.jpg", 0.9, "", "p")])
    labels = _labels({"a.jpg": "keep", "b.jpg": "cull", "c.jpg": "cull"})
    judge = ScriptedJudge({"a.jpg": "keep", "b.jpg": "cull"},
                          errors={"c.jpg"})
    res = evaluate(rows, labels, judge, cfg)
    assert res.n_errors == 1
    assert res.n_scored == 2
    rule_total = sum(c.tp + c.fp + c.fn for c in res.rule.values())
    vlm_total = sum(c.tp + c.fp + c.fn for c in res.vlm.values())
    rescue_total = sum(c.tp + c.fp + c.fn for c in res.rescue.values())
    assert rule_total == vlm_total == rescue_total, (
        "the three arms must cover the same rows, or the comparison is "
        "between different populations")

    # The property the docstring is actually about, asserted directly.
    allfail = evaluate(rows, labels,
                       ScriptedJudge({}, errors={"a.jpg", "b.jpg", "c.jpg"}),
                       cfg)
    assert allfail.n_errors == 3
    assert allfail.vlm_macro_f1 == allfail.rule_macro_f1, (
        "a judge that answers nothing must tie the rule stack, never beat it")


def test_unlabelled_rows_are_skipped(cfg):
    rows = _rows([("a.jpg", 0.9, "", "p"), ("zz.jpg", 0.9, "", "p")])
    res = evaluate(rows, _labels({"a.jpg": "keep"}),
                   ScriptedJudge({}), cfg)
    assert res.n_rows == 1


def test_limit_is_honoured(cfg):
    rows = _rows([(f"{i}.jpg", 0.9, "", "p") for i in range(20)])
    labels = _labels({f"{i}.jpg": "keep" for i in range(20)})
    res = evaluate(rows, labels, ScriptedJudge({}), cfg, limit=5)
    assert res.n_rows == 5


def test_detector_metrics_reach_the_judge(cfg):
    """Evidence fusion is the premise; an eval that skips it measures
    a different system than the one that ships."""
    rows = _rows([("a.jpg", 0.9, "", "p")])
    rows[0]["laplacian_subject"] = "412.0"
    judge = ScriptedJudge({})
    evaluate(rows, _labels({"a.jpg": "keep"}), judge, cfg)
    assert judge.seen and "laplacian_subject" in judge.seen[0]


def test_overrides_and_incoherence_are_counted(cfg):
    rows = _rows([("a.jpg", 0.7, "closed_eyes", "portrait"),
                  ("b.jpg", 0.7, "closed_eyes", "portrait")])
    labels = _labels({"a.jpg": "keep", "b.jpg": "cull"})
    res = evaluate(rows, labels, ScriptedJudge({"a.jpg": "keep",
                                                "b.jpg": "keep"}), cfg)
    assert res.n_overrides == 2
    assert res.n_incoherent == 0

    res2 = evaluate(rows, labels,
                    ScriptedJudge({"a.jpg": "keep", "b.jpg": "keep"},
                                  technical=1.0), cfg)
    assert res2.n_incoherent == 2
    assert res2.n_overrides == 0


def test_disagreements_are_listed_with_who_was_right(cfg):
    rows = _rows([("a.jpg", 0.7, "closed_eyes", "portrait")])
    res = evaluate(rows, _labels({"a.jpg": "keep"}),
                   ScriptedJudge({"a.jpg": "keep"}), cfg)
    assert len(res.disagreements) == 1
    d = res.disagreements[0]
    assert (d.truth, d.rule, d.vlm) == ("keep", "cull", "keep")
    assert d.overrode_hard_cull


def test_per_scene_breakdown(cfg):
    rows = _rows([("a.jpg", 0.9, "", "wedding"), ("b.jpg", 0.1, "", "wedding"),
                  ("c.jpg", 0.9, "", "landscape")])
    labels = _labels({"a.jpg": "keep", "b.jpg": "cull", "c.jpg": "keep"})
    res = evaluate(rows, labels, ScriptedJudge({}), cfg)
    assert res.by_scene["wedding"]["n"] == 2
    assert res.by_scene["landscape"]["n"] == 1


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def test_label_sheet_with_an_excel_bom_still_joins(tmp_path):
    """The sheet round-trips through Excel.

    A BOM renames the first column to \\ufefffilename, every lookup
    misses, and the eval cheerfully reports zero rows — which reads as
    "no overlap" rather than "you have an encoding bug".
    """
    p = tmp_path / "labels.csv"
    p.write_bytes("﻿".encode() +
                  b"filename,manual_label\na.jpg,keep\nb.jpg,cull\n")
    labels = load_labels(p)
    assert set(labels) == {"a.jpg", "b.jpg"}


def test_rows_without_a_label_are_dropped_at_load(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("filename,manual_label\na.jpg,keep\nb.jpg,\n",
                 encoding="utf-8")
    assert set(load_labels(p)) == {"a.jpg"}


def test_report_leads_with_the_verdict(cfg):
    # The fixture has to clear three guards before a RANKING verdict can
    # appear at all, and each one is a real defect this eval has shipped:
    #   * the labels must disagree with the rule somewhere (v2.49.3
    #     circularity) — a.jpg is scored keep and labelled cull;
    #   * both scored labels must be present (v2.54.2) — otherwise the
    #     missing one is 0.000 for every arm and nothing can be compared;
    #   * some arm must actually change a scored row. `rescue` only acts
    #     on a HARD cull, so b.jpg carries `closed_eyes` — a low score
    #     alone leaves rescue idle, which is how this fixture first
    #     tripped the new guard.
    rows = _rows([("a.jpg", 0.9, "", "p"),
                  ("b.jpg", 0.1, "closed_eyes", "p")])
    labels = _labels({"a.jpg": "cull", "b.jpg": "keep"})
    res = evaluate(rows, labels, ScriptedJudge({}), cfg)
    assert not res.unmeasurable and not res.unexercised, (
        "fixture no longer reaches the ranking path: "
        f"unmeasurable={res.unmeasurable} unexercised={res.unexercised}")
    md = render_report(res, labels_path="l.csv")
    head = md.split("\n\n")[1]
    assert any(w in head for w in ("SHIP `vlm_authority=", "KEEP M3 OPT-IN",
                                   "NOT A RANKING", "NO DATA",
                                   # v2.56.1 — a two-row fixture puts one
                                   # row in each class, so an arm that
                                   # misses its single `cull` scores 0
                                   # there and is refused. That is the
                                   # guard working, not the report
                                   # failing to lead with a verdict.
                                   "DO NOT SHIP")), head
    assert "need eyes on them" in md or "eyes" in md


def test_report_survives_an_empty_result():
    md = render_report(EvalResult())
    assert "NO DATA" in md


def test_eval_never_mutates_the_input_rows(cfg):
    """Running this against a real run directory has to be safe."""
    rows = _rows([("a.jpg", 0.9, "", "p")])
    before = [dict(r) for r in rows]
    evaluate(rows, _labels({"a.jpg": "keep"}), ScriptedJudge({}), cfg)
    assert rows == before


def test_cli_exposes_the_command():
    from typer.testing import CliRunner

    from pixcull.cli import app
    out = CliRunner().invoke(app, ["m3", "--help"]).output
    assert "eval" in out


# ---------------------------------------------------------------------------
# v2.49.1 — verify before spending
# ---------------------------------------------------------------------------

def _tiny_csvs(tmp_path, *, photo_exists: bool):
    from PIL import Image
    img = tmp_path / "a.jpg"
    if photo_exists:
        Image.new("RGB", (16, 16)).save(img, "JPEG")
    lab = tmp_path / "labels.csv"
    lab.write_text("filename,manual_label\na.jpg,keep\n", encoding="utf-8")
    sc = tmp_path / "scores.csv"
    sc.write_text(f"filename,path,scene,score_final,flags\n"
                  f"a.jpg,{img},portrait,0.8,\n", encoding="utf-8")
    return lab, sc


def _run(args, monkeypatch):
    monkeypatch.setattr("pixcull.scoring.m3.api_key_from_env",
                        lambda: "sk-" + "0" * 32)
    from typer.testing import CliRunner

    from pixcull.cli import app
    return CliRunner().invoke(app, ["m3", "eval", *args])


def test_dry_run_sends_nothing(tmp_path, monkeypatch):
    """A 608-row run that dies on row 3 has still been billed for 1 and 2,
    and the failure reads identically to "the model had no opinion"."""
    lab, sc = _tiny_csvs(tmp_path, photo_exists=True)
    sent = []
    monkeypatch.setattr("pixcull.scoring.vlm_judge.make_minimax_judge",
                        lambda *a, **k: sent.append(1))
    res = _run(["--labels", str(lab), "--scores", str(sc), "--dry-run",
                "--out", str(tmp_path / "r.md")], monkeypatch)
    assert res.exit_code == 0
    assert not sent, "a dry run constructed a judge"
    assert "Dry run" in res.output


def test_dry_run_reports_the_cost_before_it_is_incurred(tmp_path, monkeypatch):
    lab, sc = _tiny_csvs(tmp_path, photo_exists=True)
    out = _run(["--labels", str(lab), "--scores", str(sc), "--dry-run",
                "--out", str(tmp_path / "r.md")], monkeypatch).output
    assert "¥" in out and "call" in out


def test_stale_paths_stop_the_run_and_say_why(tmp_path, monkeypatch):
    """The real failure this hit: a drive remounted under a different name.

    Every path in the CSV named one volume while the disk was mounted
    under a slightly different one, so nothing resolved. Without this
    check the eval would have billed for hundreds of unreadable photos
    and reported a confident-looking 0.000 F1 for both sides — the same
    output a genuinely useless model produces.

    (The drive's actual name is deliberately not written here. This file
    is tracked, and tests/test_repo_hygiene.py bans personal drive names
    precisely because the paths beside them expose how a photographer's
    client folders are laid out. It caught this docstring.)
    """
    lab, sc = _tiny_csvs(tmp_path, photo_exists=False)
    res = _run(["--labels", str(lab), "--scores", str(sc),
                "--out", str(tmp_path / "r.md")], monkeypatch)
    assert res.exit_code == 2
    assert "remounts" in res.output or "stale" in res.output.lower()


# ---------------------------------------------------------------------------
# v2.49.3 — the labels must be able to disagree with the rule stack
# ---------------------------------------------------------------------------

def test_a_label_set_that_never_disagrees_is_refused(cfg):
    """The expensive lesson, made cheap.

    training_combined.csv's `manual_label` was byte-identical to the rule
    stack's own `decision` on all 408 rows — the owner reviewed the sheet
    and endorsed every decision as-is. A real review, but not an
    independent judgement: the rule then scores exactly 1.000 BY
    CONSTRUCTION and anything that differs looks worse. The run reported
    "M3 WORSE by 63.9 points" and that number measured
    disagreement-with-the-rule, not correctness.
    """
    rows = _rows([("a.jpg", 0.9, "", "p"), ("b.jpg", 0.1, "", "p")])
    labels = _labels({"a.jpg": "keep", "b.jpg": "cull"})   # == the rule
    res = evaluate(rows, labels, ScriptedJudge({"a.jpg": "cull"}), cfg)
    assert res.n_label_disagreements == 0
    assert "INVALID" in res.verdict
    assert "by construction" in res.verdict


def test_one_real_disagreement_is_enough_to_rank(cfg):
    rows = _rows([("a.jpg", 0.9, "", "p"), ("b.jpg", 0.1, "", "p")])
    labels = _labels({"a.jpg": "cull", "b.jpg": "cull"})   # rule says keep
    res = evaluate(rows, labels, ScriptedJudge({}), cfg)
    assert res.n_label_disagreements == 1
    assert "INVALID" not in res.verdict


def test_the_report_says_the_table_is_not_a_ranking(cfg):
    rows = _rows([("a.jpg", 0.9, "", "p"), ("b.jpg", 0.1, "", "p")])
    labels = _labels({"a.jpg": "keep", "b.jpg": "cull"})
    md = render_report(evaluate(rows, labels, ScriptedJudge({}), cfg))
    assert "Read no further for a ranking" in md
    assert "scored against its own answers" in md


# ── v2.54: three authority modes, and knowing when not to rank ────────

def _res(rule_f1_src, rescue_src, primary_src, **kw):
    """Build an EvalResult whose three arms have known outcomes."""
    from pixcull.scoring.vlm_eval import EvalResult, _tally
    r = EvalResult(n_scored=100, n_label_disagreements=20, **kw)
    for truth, pred in rule_f1_src:
        _tally(r.rule, truth, pred)
        r.truth_counts[truth] = r.truth_counts.get(truth, 0) + 1
    for truth, pred in rescue_src:
        _tally(r.rescue, truth, pred)
    for truth, pred in primary_src:
        _tally(r.vlm, truth, pred)
    # v2.54.2 — a hand-built result must state what its sample contained
    # and which arms actually acted, or the "cannot rank" / "not
    # measured" guards fire first. That strictness is the point: a
    # result that cannot say those things cannot rank anything either.
    # Non-zero, or the per-class circularity guard fires first — these
    # fixtures are about the CI, not about label provenance.
    r.class_disagreements = {c: 5 for c in ("keep", "cull")}
    r.arm_changes = {"rescue": sum(1 for a, b in zip(rescue_src, rule_f1_src)
                                   if a[1] != b[1]) or 1,
                     "primary": sum(1 for a, b in zip(primary_src, rule_f1_src)
                                    if a[1] != b[1]) or 1}
    return r


_PERFECT = [("keep", "keep")] * 10 + [("cull", "cull")] * 10
_AWFUL = [("keep", "cull")] * 10 + [("cull", "keep")] * 10


def test_a_disagreement_sample_refuses_to_rank():
    """The second shape of the circularity bug, and the more convincing one.

    Rows chosen BECAUSE two systems disagreed measure the rule stack
    only where it is weakest. Its score there is a floor, not an
    estimate, and the model consequently looks great. The first version
    of this defect (labels copied from the rule) pointed the other way
    and cost ¥8 to discover; believing this one ships the opposite
    mistake with more confidence.
    """
    res = _res(_AWFUL, _PERFECT, _PERFECT, selection="disagreements")
    assert res.rescue_macro_f1 > res.rule_macro_f1        # model "wins"
    v = res.verdict
    assert "NOT A RANKING" in v, v
    assert "RANDOM" in v.upper(), "does not say what sample would work"
    assert "SHIP" not in v, "recommended a default off a rigged sample"


def test_a_census_is_allowed_to_rank():
    res = _res(_AWFUL, _PERFECT, _AWFUL, selection="all")
    assert res.best_mode == "rescue"
    assert "SHIP `vlm_authority=rescue`" in res.verdict


def test_a_mode_that_only_ties_is_not_shipped():
    """A cloud call that buys nothing is worse than no cloud call.

    It costs money, adds a dependency that can fail, and contradicts
    every claim in the README about what the network is for.
    """
    res = _res(_PERFECT, _PERFECT, _PERFECT, selection="all")
    assert res.best_mode == "off"
    assert "KEEP M3 OPT-IN" in res.verdict


def test_missing_provenance_is_treated_as_biased(tmp_path):
    """Verdict files written before v2.54 carry no `selection`.

    Every batch built before it was disagreement-selected, and the safe
    reading of an unknown provenance is the one that refuses to rank.
    """
    import json as _json

    from pixcull.report.review_sheet import load_selection

    old = tmp_path / "old.json"
    old.write_text(_json.dumps({"verdicts": {"a.jpg": "keep"}}))
    assert load_selection(old) == "disagreements"

    new = tmp_path / "new.json"
    new.write_text(_json.dumps({"selection": "random", "verdicts": {}}))
    assert load_selection(new) == "random"

    assert load_selection(tmp_path / "nope.json") == "disagreements"


def test_a_sample_with_no_cull_labels_refuses_to_rank():
    """The owner's 40-row random pass, reproduced.

    A 89%-keep corpus yields fewer than three culls in 40 uniform draws,
    and the owner judged both of the ones that appeared as `maybe` —
    which is excluded from scoring. So `cull` F1 was 0.000 for all three
    arms, the macro was halved for all three equally, and the table
    looked like three mediocre modes rather than a question the sample
    could not answer.
    """
    from pixcull.scoring.vlm_eval import EvalResult
    res = _res(_PERFECT, _PERFECT, _AWFUL, selection="all")
    res.truth_counts = {"keep": 20}          # zero culls
    v = res.verdict
    assert "CANNOT RANK" in v, v
    assert "cull" in v and "0.000" in v
    assert "SHIP" not in v
    assert isinstance(res, EvalResult)


def test_an_arm_that_never_acted_is_not_reported_as_a_tie():
    """`rescue +0.0` meant "never played", not "no gain".

    In the random pass every rescue-eligible row landed on `maybe`, so
    rescue changed nothing the metric could see and scored an exact tie
    with the rule stack. A tie and an untested mode print the same
    number and call for opposite responses.
    """
    res = _res(_PERFECT, _PERFECT, _PERFECT, selection="all")
    res.truth_counts = {"keep": 20, "cull": 20}
    res.arm_changes = {"primary": 5, "rescue": 0}
    v = res.verdict
    assert "NOT MEASURED" in v, v
    assert "rescue" in v
    assert "KEEP M3 OPT-IN" not in v, "an untested mode is not a tie"


def test_stratified_weights_recover_the_population_rate():
    """Inverse-probability weighting, checked against a known answer.

    Population: 90 keeps, 10 culls. Sample 10 of each, so a keep row
    stands for 9 and a cull row for 1. A judge that is perfect on keeps
    and wrong on every cull must score as if it had seen the real 90/10
    mix, not the sampled 50/50 one — otherwise stratifying to reach the
    rare class silently rewrites what the number means.
    """
    from pixcull.scoring.vlm_eval import Confusion, _macro, _tally
    cm: dict[str, Confusion] = {}
    for _ in range(10):
        _tally(cm, "keep", "keep", 9.0)
        _tally(cm, "cull", "keep", 1.0)
    keep = cm["keep"]
    assert keep.tp == pytest.approx(90.0)
    assert keep.fp == pytest.approx(10.0)      # the culls, at weight 1
    assert keep.precision == pytest.approx(0.9)
    assert cm["cull"].f1 == 0.0
    # keep F1 = 2·0.9·1.0/1.9 = 0.947368; cull has no true positives,
    # so the macro is half of it.
    assert cm["keep"].f1 == pytest.approx(0.9473684, abs=1e-6)
    assert _macro(cm) == pytest.approx(0.4736842, abs=1e-6)


# ── v2.55: a point estimate that cannot say how stable it is ──────────

def _mixed_outcomes():
    """The stratified pass's actual shape: each arm wins somewhere.

    21 keep rows carrying the keep stratum's ×24.27 weight, 7 cull rows
    at ×1.93. The rule stack catches 2 of 7 culls; primary catches 6 but
    drops 3 more keeps. That trade is the whole question, and on 28 rows
    it is not resolvable.
    """
    out = []
    for i in range(21):
        out.append(("keep", "keep" if i < 20 else "cull", "keep",
                    "keep" if i < 17 else "cull", 24.27))
    for i in range(7):
        out.append(("cull", "cull" if i < 2 else "keep", "cull",
                    "cull" if i < 6 else "keep", 1.93))
    return out


def _clean_outcomes(n_keep, n_cull, w_keep=1.0, w_cull=1.0):
    """Primary strictly better, no counter-examples."""
    out = []
    for i in range(n_keep):
        out.append(("keep", "keep" if i < n_keep - 4 else "cull", "keep",
                    "keep", w_keep))
    for i in range(n_cull):
        out.append(("cull", "keep", "cull", "cull", w_cull))
    return out


def test_a_small_sample_reports_an_interval_that_spans_zero():
    """The stratified pass: +13.6 points, 95% CI [-12.0, +41.4].

    28 scoreable rows, 7 of them `cull`. The point estimate printed to
    three decimals and the line under it said SHIP. Resampling says the
    sample cannot tell the mode apart from no change at all — and this
    project has already reached a wrong conclusion off a confident
    single number three times.
    """
    from pixcull.scoring.vlm_eval import EvalResult, bootstrap_delta
    res = EvalResult(n_scored=28)
    res.outcomes = _mixed_outcomes()
    pt, lo, hi = bootstrap_delta(res, "vlm", rounds=1500)
    assert lo <= 0 <= hi, f"expected a spanning CI on 28 rows: [{lo}, {hi}]"
    assert hi - lo > 20, "an interval this narrow would not match the data"


def test_more_rows_narrow_the_interval_off_zero():
    """Same effect, twenty times the rows."""
    from pixcull.scoring.vlm_eval import EvalResult, bootstrap_delta
    small = EvalResult(); small.outcomes = _clean_outcomes(21, 7)
    big = EvalResult(); big.outcomes = _clean_outcomes(420, 140)
    _, slo, shi = bootstrap_delta(small, "vlm", rounds=800)
    _, blo, bhi = bootstrap_delta(big, "vlm", rounds=800)
    assert (bhi - blo) < (shi - slo), "more rows must not widen the interval"
    assert blo > 0, f"a real effect on 560 rows should clear zero: [{blo},{bhi}]"


def test_reweighting_a_stratified_sample_can_flip_the_sign():
    """Why the weights are not a nicety.

    Stratifying over-samples the rare class on purpose — here `cull` is
    52% of the sample and 7% of the corpus. `primary` happens to be
    strong exactly there, so on the raw sample it scores +15.4. Weighted
    back to the corpus it scores −3.5. Same rows, same model, opposite
    conclusion.

    (I first assumed weighting mainly widened the interval. Measured, it
    does not — on both a clean and a mixed fixture the weighted interval
    is slightly narrower. What it moves is the estimate itself, which is
    the thing that decides the default.)
    """
    from pixcull.scoring.vlm_eval import EvalResult, bootstrap_delta

    def mixed(w_keep, w_cull):
        out = []
        for i in range(21):
            out.append(("keep", "keep" if i < 20 else "cull", "keep",
                        "keep" if i < 17 else "cull", w_keep))
        for i in range(7):
            out.append(("cull", "cull" if i < 2 else "keep", "cull",
                        "cull" if i < 6 else "keep", w_cull))
        return out

    flat = EvalResult(); flat.outcomes = mixed(1.0, 1.0)
    wtd = EvalResult(); wtd.outcomes = mixed(24.27, 1.93)
    raw = bootstrap_delta(flat, "vlm", rounds=1500)[0]
    corrected = bootstrap_delta(wtd, "vlm", rounds=1500)[0]
    assert raw > 0 > corrected, (
        f"expected the sign to flip: raw {raw:+.1f}, weighted "
        f"{corrected:+.1f} — if it no longer does, this fixture has "
        f"drifted and the lesson needs re-deriving, not deleting")


def test_the_verdict_will_not_ship_a_mode_whose_interval_spans_zero():
    """The contradiction that printed for one run.

    The table said `primary +13.6` and the verdict said SHIP, while the
    CI printed between them contained zero. A tool that recommends a
    change its own interval calls noise is worse than one that says
    nothing.
    """
    res = _res(_AWFUL, _AWFUL, _PERFECT, selection="all")
    res.ci = {"primary": (-12.0, 41.4), "rescue": (-24.5, 14.8)}
    v = res.verdict
    assert "NOT DISTINGUISHABLE" in v, v
    assert "SHIP" not in v


def test_the_verdict_still_ships_when_the_interval_clears_zero():
    res = _res(_AWFUL, _AWFUL, _PERFECT, selection="all")
    res.ci = {"primary": (6.2, 31.0), "rescue": (-24.5, 14.8)}
    assert "SHIP `vlm_authority=primary`" in res.verdict


def test_the_interval_is_reproducible():
    """A CI that moves per run invites re-rolling until it agrees."""
    from pixcull.scoring.vlm_eval import EvalResult, bootstrap_delta
    res = EvalResult(n_scored=28)
    res.outcomes = _mixed_outcomes()
    assert (bootstrap_delta(res, "vlm", rounds=400)
            == bootstrap_delta(res, "vlm", rounds=400))


def test_a_scores_file_without_a_flags_column_is_refused(cfg):
    """The one that produced the most convincing wrong table yet.

    A label sheet was fed to `m3 eval` as if it were a scores file. It
    had `score_final`, so nothing errored — but no `flags` column, and
    hard culls come only from flags. The rule stack was therefore
    measured with its detectors removed: `cull` F1 0.000 against 95 real
    cull labels, `rescue` never firing because no hard cull could
    trigger, and a clean three-column table reporting all of it as the
    rule stack's opinion.

    An absent COLUMN is the fault. An empty VALUE is legitimate — that
    frame tripped nothing — so the two must not be conflated.
    """
    spec = [("a.jpg", 0.9, "", "p"), ("b.jpg", 0.1, "", "p")]
    labels = _labels({"a.jpg": "cull", "b.jpg": "keep"})

    bare = [{k: v for k, v in r.items() if k != "flags"} for r in _rows(spec)]
    res = evaluate(bare, labels, ScriptedJudge({}), cfg)
    assert res.n_missing_flags_column == res.n_rows
    v = res.verdict
    assert "INVALID INPUT" in v, v
    assert "flags" in v and "pixcull run" in v

    withcol = evaluate(_rows(spec), labels, ScriptedJudge({}), cfg)
    assert withcol.n_missing_flags_column == 0, (
        "an empty flags value is a frame that tripped nothing, not a "
        "missing column")
    assert "INVALID INPUT" not in withcol.verdict


def test_a_class_whose_labels_came_from_the_rule_is_refused(cfg):
    """The circularity bug's third costume, and the best-hidden one.

    A 200-frame shoot's `manual_label` turned out to be the pipeline's
    own decisions. Overall disagreement was 20% — healthy-looking, so
    the global `n_label_disagreements == 0` check passed — but all 95
    `cull` labels were the rule's own culls, exactly. `cull` F1 came out
    1.000 and the noise in the `keep` class hid it.

    The class carrying the headline was the circular one, so the check
    has to be per class. A global rate cannot express this.
    """
    # keep: rule and label differ on 2 of 4 → that class is fine.
    # cull: rule and label agree on all 3 → that class is circular.
    rows = _rows([("k1.jpg", 0.9, "", "p"), ("k2.jpg", 0.9, "", "p"),
                  ("k3.jpg", 0.1, "", "p"), ("k4.jpg", 0.1, "", "p"),
                  ("c1.jpg", 0.1, "closed_eyes", "p"),
                  ("c2.jpg", 0.1, "closed_eyes", "p"),
                  ("c3.jpg", 0.1, "closed_eyes", "p")])
    labels = _labels({"k1.jpg": "keep", "k2.jpg": "keep",
                      "k3.jpg": "keep", "k4.jpg": "keep",
                      "c1.jpg": "cull", "c2.jpg": "cull", "c3.jpg": "cull"})
    res = evaluate(rows, labels, ScriptedJudge({}), cfg)
    assert res.class_disagreements.get("cull") == 0, (
        "fixture must make `cull` circular")
    assert res.class_disagreements.get("keep"), (
        "fixture must leave `keep` non-circular, or the global check "
        "would have caught it and this test proves nothing")
    assert res.n_label_disagreements > 0, (
        "the global check must PASS here — that is the whole point")
    v = res.verdict
    assert "CIRCULAR ON `cull`" in v, v
    assert "1.000 by construction" in v
    # What the condition guarantees is RECALL, not F1: the rule caught
    # every labelled cull. F1 is only 1.000 when it also culled nothing
    # else — true of the real 200-frame shoot, not of this fixture,
    # where the rule culls two `keep` rows as well.
    assert res.rule.get("cull").recall == pytest.approx(1.0)
    assert res.rule.get("cull").f1 < 1.0


def test_labels_can_come_straight_from_a_blind_json(tmp_path):
    """No CSV to hand-edit between labelling and measuring.

    Every hand-edit of a label sheet in this project's history was an
    opportunity to paste the rule stack's answers back in, and four
    separate label sets did exactly that.
    """
    import json as _json
    p = tmp_path / "blind-review.json"
    p.write_text(_json.dumps({"selection": "blind",
                              "verdicts": {"a.jpg": "keep",
                                           "b.jpg": "CULL"}}))
    got = load_labels(p)
    assert got["a.jpg"]["manual_label"] == "keep"
    assert got["b.jpg"]["manual_label"] == "cull", "case must be normalised"


# ── v2.56.1: two holes the blind pass found ───────────────────────────

def test_an_arm_that_wins_the_average_by_abandoning_a_class_is_refused():
    """Blind labels came out 140 keep / 10 cull, and the metric lied.

    `rescue` scored the best macro-F1 while getting ZERO of those 10
    culls right. On a truth set that is 93% one class, turning culls into
    keeps lifts the big class far more than surrendering the small one
    costs — so the mode that wins the average is the mode that stops
    doing the job the product exists for.
    """
    res = _res(_PERFECT, _PERFECT, _PERFECT, selection="all")
    res.truth_counts = {"keep": 140, "cull": 10}
    res.class_disagreements = {"keep": 30, "cull": 8}
    res.arm_changes = {"rescue": 40, "primary": 40}
    res.rescue = {"keep": Confusion("keep", tp=140, fp=10, fn=0),
                  "cull": Confusion("cull", tp=0, fp=0, fn=10)}
    res.rule = {"keep": Confusion("keep", tp=100, fp=30, fn=40),
                "cull": Confusion("cull", tp=1, fp=9, fn=9)}
    res.vlm = dict(res.rule)
    res.ci = {"rescue": (1.0, 8.0), "primary": (-3.0, 3.0)}
    assert res.best_mode == "rescue", "fixture must make rescue win"
    v = res.verdict
    assert "DO NOT SHIP `rescue`" in v, v
    assert "SHIP `vlm_authority" not in v


def test_every_eval_path_computes_an_interval_before_the_verdict():
    """v2.55 gated the verdict on a CI, then wired it to ONE branch.

    A run driven by `--labels blind.json` took the other branch and
    printed `SHIP vlm_authority=rescue` with no interval computed —
    the exact contradiction v2.55 existed to remove, alive one branch
    over. Both of that run's intervals turned out to span zero.

    Asserted structurally: `_print_cis` calls `compute_cis`, and every
    place the CLI prints a verdict is preceded by a `_print_cis` call.
    """
    import inspect
    import re

    from pixcull import cli

    src = inspect.getsource(cli._print_cis)
    assert "compute_cis" in src, (
        "_print_cis no longer fills `ci`, so the verdict cannot gate on it")

    body = inspect.getsource(cli.m3_eval)
    verdicts = [m.start() for m in re.finditer(r"\.verdict", body)]
    assert verdicts, "m3_eval prints no verdict — this test is stale"
    for pos in verdicts:
        before = body[:pos]
        assert "_print_cis" in before, (
            "a verdict is printed with no interval computed before it")


def test_an_arm_that_finds_less_than_the_rule_is_refused():
    """v2.63 — the guard is a comparison now, not a threshold.

    v2.56.1 refused an arm scoring 0.000 on a class with ground truth.
    On 394 blind frames `rescue` scored 0.043 on `cull`, cleared that
    bar, won macro-F1 by +5.2 with an interval EXCLUDING zero, and the
    tool said SHIP — while finding 1 of the 28 frames the photographer
    wanted deleted, against the rule stack's 5.

    A threshold cannot catch "wins the average by doing less of the
    job". A comparison against the mode it would replace can.
    """
    res = _res(_PERFECT, _PERFECT, _PERFECT, selection="all")
    res.truth_counts = {"keep": 365, "cull": 28}
    res.class_disagreements = {"keep": 40, "cull": 20}
    res.arm_changes = {"rescue": 60, "primary": 60}
    res.ci = {"rescue": (1.0, 9.6), "primary": (-7.1, 9.2)}
    # rule catches 5 of 28; rescue catches 1 but is tidy about it.
    res.rule = {"keep": Confusion("keep", tp=215, fp=20, fn=150),
                "cull": Confusion("cull", tp=5, fp=125, fn=23)}
    res.rescue = {"keep": Confusion("keep", tp=279, fp=19, fn=86),
                  "cull": Confusion("cull", tp=1, fp=16, fn=27)}
    res.vlm = dict(res.rule)
    assert res.best_mode == "rescue", "fixture must make rescue win macro"
    v = res.verdict
    assert "DO NOT SHIP `rescue`" in v, v
    assert "LESS of the job" in v
    assert "recall" in v and "0.04" in v, (
        f"the refusal does not show the recalls being compared: {v}")
