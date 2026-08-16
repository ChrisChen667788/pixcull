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
    # 0.9/"cull" makes the rule disagree with the label on one row, so
    # the circularity guard does not fire and the ranking verdict shows.
    rows = _rows([("a.jpg", 0.9, "", "p"), ("b.jpg", 0.1, "", "p")])
    labels = _labels({"a.jpg": "cull", "b.jpg": "cull"})
    res = evaluate(rows, labels, ScriptedJudge({}), cfg)
    md = render_report(res, labels_path="l.csv")
    head = md.split("\n\n")[1]
    assert any(w in head for w in ("SHIP `vlm_authority=", "KEEP M3 OPT-IN",
                                   "NOT A RANKING", "NO DATA")), head
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
    for truth, pred in rescue_src:
        _tally(r.rescue, truth, pred)
    for truth, pred in primary_src:
        _tally(r.vlm, truth, pred)
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
