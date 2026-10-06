"""v3.93.2 — one missing `}` turned the review page's stylesheet inside out.

PR #4 restored a `.buckets-toggle {` selector that had gone missing, and
the closing brace did not come with it. Chrome reads CSS nesting now, so
nothing was rejected: every rule after that point became a rule *inside*
`.buckets-toggle`, matching only its descendants. The brand mark, the
export button and the breadcrumb lost their colours and fell back to the
browser's own dark-mode link blue; the client-present mode's rules that
hide scores and verdicts stopped applying, so a client could read
"保留 / 剔除 / 0.80" off the screen. The browser lane caught both.

The PR's own test passed throughout: it looked for `cursor: grab` and
`touch-action: none` within 900 characters of the selector, and they were
there — inside a block that never closed. Text present is not a rule bound.

This counts braces, which is the property that broke: every stylesheet
the product serves ends at depth zero, with comments and strings
excluded so that a `{` in either cannot balance or unbalance it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "pixcull" / "report" / "templates"


def _depth_report(css: str) -> tuple[int, int, int]:
    """``(final depth, lowest depth, line where depth first went wrong)``.

    Comments and quoted strings are removed first; a brace inside either
    is not structure. The line is 0 when nothing went wrong.
    """
    css = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"),
                 css, flags=re.S)
    css = re.sub(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', '""', css)
    depth = low = 0
    bad_line = 0
    line = 1
    for ch in css:
        if ch == "\n":
            line += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < low:
                low = depth
                bad_line = bad_line or line
    return depth, low, bad_line


def _style_blocks(html: str) -> list[str]:
    return re.findall(r"<style[^>]*>(.*?)</style>", html, flags=re.S | re.I)


def _sheets() -> list[tuple[str, str]]:
    out = [("templates/src/results.css",
            (TEMPLATES / "src" / "results.css").read_text("utf-8"))]
    pages = [TEMPLATES / "results.html", TEMPLATES / "video_review.html",
             TEMPLATES / "timeline.html", *sorted((TEMPLATES / "pages").glob("*.html"))]
    for page in pages:
        if not page.is_file():
            continue
        for i, css in enumerate(_style_blocks(page.read_text("utf-8"))):
            out.append((f"{page.relative_to(TEMPLATES)}<style #{i}>", css))
    # And every <style> written inside Python: the page builders in
    # serve_app, the review sheet, the executive PDF, the gallery, the
    # delivery audit, the proof sheet. Read from the source text, so an
    # f-string's doubled braces and its {interpolations} are counted too —
    # both are balanced when the CSS is. (The first version of this file
    # read the template files only and missed eleven of these; review.)
    for py in sorted((ROOT / "pixcull").rglob("*.py")):
        src = py.read_text("utf-8")
        for i, css in enumerate(_style_blocks(src)):
            out.append((f"{py.relative_to(ROOT)}<style #{i}>", css))
    for name, fn in _css_builders():
        out.append((name, fn()))
    return out


def _css_builders():
    """Stylesheets assembled by a function rather than written in a
    <style> literal — the scan above cannot see these."""
    from pixcull.report import executive_pdf, review_sheet
    found = []
    if hasattr(review_sheet, "_CSS"):
        found.append(("report/review_sheet._CSS", lambda: review_sheet._CSS))
    if hasattr(executive_pdf, "_print_css"):
        found.append(("report/executive_pdf._print_css()",
                      executive_pdf._print_css))
    return found


SHEETS = _sheets()


def test_the_scan_found_the_stylesheets():
    """By name, not by count: a count passes when the scan loses one
    source and another file grows a block."""
    names = [n for n, _ in SHEETS]
    for must in ("results.html", "video_review.html", "pages/upload.html",
                 "pixcull/report/serve_app.py", "pixcull/export/proof_sheet.py",
                 "pixcull/report/gallery.py", "pixcull/report/cli_audit.py",
                 "report/review_sheet._CSS", "report/executive_pdf._print_css()"):
        assert any(n.startswith(must) for n in names), f"{must} was not scanned"
    assert sum(n.startswith("pixcull/report/serve_app.py") for n in names) >= 4


@pytest.mark.parametrize("name,css", SHEETS, ids=[n for n, _ in SHEETS])
def test_every_stylesheet_closes_every_block(name, css):
    depth, low, line = _depth_report(css)
    assert low == 0, f"{name}: a `}}` closes a block that was never opened (line {line})"
    assert depth == 0, (
        f"{name}: {depth} block(s) never closed — every rule after the open "
        f"one is read as nested inside it, and silently matches nothing")


def test_the_counter_sees_the_defect_that_shipped_in_the_pr():
    broken = (".buckets-toggle {\n  cursor: grab;\n  touch-action: none;\n"
              "/* comment with a } in it */\n"
              ".buckets-toggle.bk-toggle-dragging {\n  cursor: grabbing;\n}\n"
              ".brand-mark { color: var(--fg); }\n")
    assert _depth_report(broken)[0] == 1
    fixed = broken.replace("touch-action: none;\n", "touch-action: none;\n}\n")
    assert _depth_report(fixed) == (0, 0, 0)


def test_braces_in_comments_and_strings_are_not_structure():
    css = ('a { content: "{"; }\n/* { { { */\nb { content: \'}\'; }\n'
           '@media (max-width: 1px) { c { d: e; } }\n')
    assert _depth_report(css) == (0, 0, 0)
    assert _depth_report("a { b: c; } }")[1] == -1


def test_the_drag_rule_is_a_top_level_rule():
    """The PR's own test, made to check what it meant: the dragging rule
    is reached at depth zero, i.e. it is not nested in the toggle's block."""
    for name, css in SHEETS:
        if name not in ("templates/src/results.css",) and not name.startswith("results.html"):
            continue
        clean = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        i = clean.find(".buckets-toggle.bk-toggle-dragging")
        assert i != -1, f"{name}: the dragging rule is gone"
        before = clean[:i]
        assert before.count("{") == before.count("}"), (
            f"{name}: the dragging rule sits inside an unclosed block")
