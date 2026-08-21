"""v2.68.4 — NaN reached the photographer's screen.

The inspector rendered

    VLM 视觉
    nan

on every row where the vision judge had not run. Three separate guards
were supposed to prevent that and none of them could:

1. ``str(x or "")`` — ``bool(float("nan"))`` is **True**, so NaN is not
   falsy and sails through. Sixteen call sites.
2. ``x not in (None, "", float("nan"))`` — ``in`` compares with ``==``
   and ``nan != nan``, so a NaN never matches the NaN in that tuple.
   Written by someone who was explicitly thinking about NaN.
3. The same idiom plus a bolted-on ``str(x) != "nan"`` — the fingerprint
   of hitting the bug at one site, patching the symptom there, and
   leaving the unusable guard standing at the other two.

Same family as the v2.13 defect where NaN bypassed an ``is None`` check
and clamped every score to 1.0. NaN is neither ``None`` nor falsy nor
equal to itself, in a language where "missing" is usually all three, so
every intuitive guard for it is wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVE = ROOT / "pixcull/report/serve_app.py"

_TRIPLE = re.compile(r'(\"\"\"|\'\'\')(?:.|\n)*?\1')


def _code_only(src: str) -> str:
    """Strip docstrings and comments before linting.

    Both lints below describe the bad idiom in order to forbid it, so a
    lint that reads prose flags the explanation of its own fix. Same
    mistake the grid-observer lint made in v2.68.1, where it counted
    `querySelectorAll` inside the comment saying `querySelectorAll` had
    been removed.
    """
    src = _TRIPLE.sub("", src)
    return "\n".join(ln for ln in src.splitlines()
                      if not ln.lstrip().startswith("#"))


def test_the_nan_safe_coercion_actually_handles_nan():
    from pixcull.report.serve_app import _s

    assert _s(float("nan")) == ""
    assert _s(None) == ""
    # numpy is what actually produces these, via the DataFrame.
    try:
        import numpy as np
        assert _s(np.float64("nan")) == ""
        assert _s(np.nan) == ""
    except ImportError:  # pragma: no cover
        pass
    # The CSV round trip turns NaN into the *string* "nan", which no
    # isinstance check catches.
    for text in ("nan", "NaN", "NAN", "None", "NaT", "<NA>", "  nan  "):
        assert _s(text) == "", f"{text!r} survived"
    # And it must not eat real values that merely start the same way.
    assert _s("nancy") == "nancy"
    assert _s("keep") == "keep"
    assert _s(0) == "0"
    assert _s(False) == "False"


def test_no_membership_test_against_nan_survives():
    """`x in (..., float("nan"))` is always False and always looks fine."""
    body = _code_only(SERVE.read_text(encoding="utf-8"))
    hits = re.findall(r"(?:not\s+)?in\s*\([^)]*float\(['\"]nan['\"]\)",
                      body)
    assert not hits, (
        "a membership test against float('nan') — it can never match, "
        f"because nan != nan: {hits[:3]}")


def test_no_falsy_guard_stands_in_for_a_nan_guard():
    body = _code_only(SERVE.read_text(encoding="utf-8"))
    hits = re.findall(r'str\(r\.get\([^()]*(?:\([^()]*\))?[^()]*\)\s*or\s*""\)',
                      body)
    assert not hits, (
        "`str(r.get(...) or \"\")` treats NaN as present, because NaN is "
        f"truthy. Use _s(): {hits[:3]}")


# ---------------------------------------------------------------------------
# Provenance: the reader has to be able to tell which voice is speaking
# ---------------------------------------------------------------------------

def test_both_advice_paths_declare_their_source():
    """`m3_advice` always set `advice_source`; the template side set
    nothing, so the answer to "did anything look at this photo" was a
    missing key — which is also what a serialisation bug looks like."""
    tmpl = (ROOT / "pixcull/scoring/photo_advice.py").read_text(encoding="utf-8")
    m3 = (ROOT / "pixcull/scoring/m3_advice.py").read_text(encoding="utf-8")
    assert '"advice_source": "template"' in tmpl, (
        "template advice does not say it is template advice")
    assert '"advice_source"' in m3


def test_the_inspector_renders_which_voice_wrote_the_advice():
    """1,576 lines of templates and a model that looked at the frame
    rendered identically — same panel, same canon citations. A reader who
    cannot tell them apart has to discount both."""
    js = (ROOT / "pixcull/report/templates/src/results.js").read_text(
        encoding="utf-8")
    code = "\n".join(re.sub(r"//.*$", "", ln) for ln in js.splitlines())
    assert re.search(r"r\.advice\s*&&\s*r\.advice\.advice_source", code), (
        "the provenance is in the data and nothing reads it — this "
        "repo's recurring defect, in the one place where it costs "
        "credibility rather than a feature")
    assert "advice-src" in code, "no provenance chip is emitted"
    css = (ROOT / "pixcull/report/templates/src/modules/lightbox.css").read_text(
        encoding="utf-8")
    for cls in (".advice-src.saw", ".advice-src.tmpl"):
        assert cls in css, f"{cls} is emitted but has no styling"
