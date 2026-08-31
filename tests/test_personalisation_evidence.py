"""v2.83 — "we could not measure" must not print as "no effect".

`evaluate()` returned `delta: 0.0` when there was too little data, and
the CLI printed that in the same cell as a real result. Those are
opposite findings: one says personalisation makes no difference, the
other says nobody looked. A photographer reading the first would stop
correcting.

The second half is subtler. Folds were a stride through the example
list, so a fold could be drawn entirely from one shoot — the model
tested on frames beside the ones it learned from, in the same light on
the same day. A high figure there shows it remembered, not that it
learned a taste.
"""
import ast
from pathlib import Path

import pytest

from pixcull.scoring.personal_learn import AXES, Example, evaluate

CLI = Path(__file__).resolve().parents[1] / "pixcull" / "cli.py"


def _ex(run, n, *, keep_above=3.0, bias=1.0, seed=0):
    import random
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        ax = {a: rnd.uniform(1, 5) for a in AXES}
        ax["composition"] *= bias
        out.append(Example(axes=ax, run_id=run,
                           decision="keep" if ax["composition"] > keep_above
                           else "cull"))
    return out


def test_too_little_data_refuses_instead_of_returning_zero():
    ev = evaluate(_ex("r1", 5))
    assert ev.get("refused")
    for k in ("generic_f1", "personal_f1", "delta"):
        assert k not in ev, (
            f"{k} is present on a refused evaluation; a caller will print "
            "it and a reader will believe it")


def test_a_real_evaluation_carries_no_refusal():
    ev = evaluate(_ex("a", 40, seed=1) + _ex("b", 40, seed=2))
    assert ev.get("refused") is None
    assert "delta" in ev


def test_folds_are_whole_shoots_when_shoots_are_known():
    ev = evaluate(_ex("a", 40, seed=1) + _ex("b", 40, seed=2) + _ex("c", 40, seed=3))
    assert ev["grouped"] is True
    assert ev["n_runs"] == 3
    assert ev["folds"] == 3, "one fold per unseen shoot"


def test_a_single_shoot_is_reported_as_ungrouped():
    """Not refused — an ungrouped figure is worth something. It must not
    be mistakable for the other kind."""
    ev = evaluate(_ex("only", 60, seed=4))
    assert ev["grouped"] is False
    assert ev.get("refused") is None
    assert "delta" in ev


def test_examples_without_a_run_id_fall_back_rather_than_crash():
    exs = [Example(axes=e.axes, decision=e.decision) for e in _ex("x", 40)]
    ev = evaluate(exs)
    assert ev["grouped"] is False
    assert "delta" in ev


def test_a_mix_of_known_and_unknown_shoots_is_not_treated_as_grouped():
    """One unlabelled example must not become its own pseudo-shoot and
    make an ungrouped run look grouped."""
    exs = _ex("a", 40, seed=1) + [Example(axes=e.axes, decision=e.decision)
                                  for e in _ex("b", 40, seed=2)]
    assert evaluate(exs)["grouped"] is False


def _code_only(path):
    text = path.read_text(encoding="utf-8")
    docs = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docs.add(d)
    body = "\n".join("" if l.lstrip().startswith("#") else l.split("#", 1)[0]
                     for l in text.splitlines())
    for d in docs:
        body = body.replace(d, "")
    return body


def test_the_cli_handles_the_refusal():
    code = _code_only(CLI)
    i = code.find("held-out keep-F1")
    assert i > 0
    window = code[max(0, i - 900):i + 900]
    # The CONDITION, not merely a mention. Reading `ev["refused"]` inside
    # a branch that never runs still puts the string in the window, so
    # `"refused" in window` passes on a CLI that prints the figures
    # unconditionally — which is the whole defect.
    assert 'if ev.get("refused")' in window, (
        "the CLI prints held-out figures without branching on whether the "
        "evaluation refused to produce them")
    guard = window.find('if ev.get("refused")')
    figures = window.find("generic_f1")
    assert 0 <= guard < figures, \
        "the refusal is checked after the figures are already on the table"
