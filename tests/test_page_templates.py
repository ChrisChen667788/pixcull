"""v2.16-P0 — serve_demo's 7 inline HTML page blobs now live as files under
pixcull/report/templates/pages/ and load via _read_template at import time.

Guards: every template file exists and is non-trivial; the module-level
constants are real full pages; the three token-carrying pages actually got
the shared design-tokens CSS spliced in (no placeholder left behind).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_PAGES = _REPO / "pixcull" / "report" / "templates" / "pages"

_EXPECTED = {
    "_FIRST_RUN_HTML": "first_run.html",
    "_PRIVACY_HTML": "privacy.html",
    "_VERTICALS_HTML": "verticals.html",
    "_VERTICAL_BULK_HTML": "vertical_bulk.html",
    "_UPLOAD_HTML": "upload.html",
    "_ADMIN_HTML": "admin.html",
    "_ADMIN_PERF_HTML": "admin_perf.html",
}
_TOKEN = "/*__DESIGN_TOKENS_CSS__*/"
_TOKENIZED = {"_UPLOAD_HTML", "_ADMIN_HTML", "_ADMIN_PERF_HTML"}


@pytest.fixture(scope="module")
def server_mod():
    spec = importlib.util.spec_from_file_location(
        "serve_demo_pages_test", _REPO / "scripts" / "serve_demo.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["serve_demo_pages_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_template_files_exist_and_nontrivial():
    for fname in _EXPECTED.values():
        p = _PAGES / fname
        assert p.exists(), f"missing template {fname}"
        text = p.read_text(encoding="utf-8")
        assert text.startswith("<!DOCTYPE html"), fname
        assert len(text) > 2000, f"{fname} suspiciously small"


def test_constants_load_full_pages(server_mod):
    for const, fname in _EXPECTED.items():
        val = getattr(server_mod, const)
        assert isinstance(val, str) and val.startswith("<!DOCTYPE html"), const
        assert "</html>" in val, const
        # No unsubstituted placeholder may survive into the served page.
        assert _TOKEN not in val, f"{const}: design-tokens placeholder leaked"


def test_design_tokens_actually_spliced(server_mod):
    tokens_css = getattr(server_mod, "_DESIGN_TOKENS_CSS")
    assert tokens_css.strip()
    probe = tokens_css.strip()[:60]
    for const in _TOKENIZED:
        assert probe in getattr(server_mod, const), (
            f"{const}: shared design-tokens CSS not spliced in")
        # ...and the raw template file carries the placeholder instead.
        raw = (_PAGES / _EXPECTED[const]).read_text(encoding="utf-8")
        assert _TOKEN in raw, f"{_EXPECTED[const]}: placeholder missing in file"


# ── v2.28 — request-time page templates (loaded in-method, not as module
# constants): tether (fully static), history + disagreement (static shell
# + placeholder injections). Guard existence + placeholders so the
# extraction can't silently regress. Their routes are byte-verified in
# CI-adjacent manual checks; here we assert the template contract.
_INMETHOD_PAGES = {
    "tether.html":       ["/*__DESIGN_TOKENS_CSS__*/"],
    "history.html":      ["/*__DESIGN_TOKENS_CSS__*/",
                          "<!--__HISTORY_COUNT__-->", "<!--__HISTORY_CARDS__-->"],
    "disagreement.html": ["<!--__DIS_NROWS_META__-->",
                          "<!--__DIS_ROWS__-->", "<!--__DIS_PER_RUN__-->"],
}


def test_inmethod_page_templates_exist_with_placeholders():
    for fname, placeholders in _INMETHOD_PAGES.items():
        p = _PAGES / fname
        assert p.exists(), f"missing in-method template {fname}"
        text = p.read_text(encoding="utf-8")
        assert text[:20].lower().startswith("<!doctype html"), fname
        assert len(text) > 800, f"{fname} suspiciously small"
        for ph in placeholders:
            assert text.count(ph) == 1, (
                f"{fname}: placeholder {ph!r} must appear exactly once "
                f"(found {text.count(ph)})")


def test_inmethod_templates_referenced_by_serve_demo():
    src = (_REPO / "scripts" / "serve_demo.py").read_text("utf-8")
    for fname in _INMETHOD_PAGES:
        assert f'_read_template("pages/{fname}")' in src, (
            f"serve_demo no longer loads pages/{fname}")
