"""v2.5-P0-1 — golden guard for the results.html build.

The committed single-file artifact must always equal what the split
sources (templates/src/) build to.  This is what makes the split safe:
hand-editing results.html, or editing src/ without `make results-html`,
fails the gate instead of silently forking the two.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _builder():
    p = ROOT / "scripts" / "build_results_html.py"
    spec = importlib.util.spec_from_file_location("build_results_html", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_results_html"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_sources_exist_and_are_substantial():
    src = ROOT / "pixcull" / "report" / "templates" / "src"
    assert (src / "results.src.html").is_file()
    assert (src / "results.css").stat().st_size > 100_000   # ~212 KB
    assert (src / "results.js").stat().st_size > 300_000    # ~458 KB
    shell = (src / "results.src.html").read_text("utf-8")
    assert shell.count("@@INLINE:results.css@@") == 1
    assert shell.count("@@INLINE:results.js@@") == 1


def test_artifact_matches_sources():
    """The golden check: committed results.html == build(src)."""
    mod = _builder()
    built = mod.build()
    committed = (ROOT / "pixcull" / "report" / "templates"
                 / "results.html").read_text("utf-8")
    assert built == committed, (
        "results.html does not match templates/src/ — edit the sources "
        "and run `make results-html` (never hand-edit the artifact)")


def test_build_resolves_all_markers():
    mod = _builder()
    built = mod.build()
    assert "@@INLINE:" not in built
    assert built.lstrip().startswith("<!DOCTYPE html>") or \
        built.lstrip().startswith("<!doctype html>")
    assert built.rstrip().endswith("</html>")
