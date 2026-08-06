"""v2.47 — two endpoints answer /rows-shaped URLs, and they differ a lot.

``/results_rows/<id>``  → ``_serve_runs_rows``    → all 52 _build_results
                                                    fields; what the review
                                                    page hydrates from.
``/api/v1/runs/<id>/rows`` → ``_serve_api_v1_rows`` → 8 fields, shaped for
                                                    the iOS swipe grid.

Both are deliberate. The hazard is that the URLs look interchangeable: a
server-side comment claimed the page hydrated from the api/v1 one "same
_build_results fields", which is false by 44 fields. Following it would
leave every photo past the inline slice with no rubric stars and no
advice — most of a wedding.

These tests pin the difference so it stays a decision rather than a
surprise, and pin that the *page* keeps using the full one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The eight the iOS grid needs. Kept as a literal so shrinking that
# endpoint is a visible edit, not a silent one.
_IOS_FIELDS = {
    "filename", "decision", "score_final", "scene", "cluster_id",
    "is_burst_peak", "rubric_human_labeled", "cull_reason",
}


def _src() -> str:
    return (REPO / "pixcull" / "report" / "serve_app.py").read_text("utf-8")


def test_the_page_hydrates_from_the_full_field_endpoint():
    """The built artifact is what ships; check it, not just the source."""
    built = (REPO / "pixcull" / "report" / "templates" /
             "results.html").read_text("utf-8")
    assert "results_rows/" in built, (
        "the review page no longer hydrates from /results_rows/ — if it "
        "moved to /api/v1/runs/<id>/rows, rows past the inline slice lose "
        "44 fields including rubric_stars and advice")
    assert "/api/v1/runs/${encodeURIComponent(run_id)}/rows" not in built


def _function_body(src: str, name: str) -> str:
    """Just this function — a fixed character window spills into the next.

    The first draft grabbed 4000 characters and picked up rubric_stars
    from a neighbouring handler, so the test failed on code it was not
    looking at.
    """
    i = src.index(f"def {name}")
    rest = src[i:]
    nxt = re.search(r"\n    def ", rest[1:])
    return rest[:nxt.start() + 1] if nxt else rest


def test_the_ios_endpoint_still_projects_a_small_row():
    """It is small on purpose; this asserts the projection still exists."""
    src = _src()
    body = _function_body(src, "_serve_api_v1_rows")
    for f in _IOS_FIELDS:
        assert f'"{f}"' in body, f"{f} vanished from the iOS row projection"
    # …and must not quietly grow into the full row dump. Check the CODE,
    # not the docstring: this handler's docstring names rubric_stars while
    # explaining that it strips it, so a naive substring search over the
    # whole function reports the opposite of the truth.
    code = re.sub(r'"""[\s\S]*?"""', "", body, count=1)
    assert '"rubric_stars"' not in code, (
        "the iOS endpoint now emits rubric_stars; that re-introduces the "
        "payload bloat it exists to avoid")
    assert '"advice"' not in code, "the iOS endpoint now emits the advice blob"


def test_the_two_endpoints_declare_different_schemas():
    """Same-looking URL, different contract — say so in the payload."""
    src = _src()
    assert "pixcull.api.v1.rows.v1" in src
    assert "pixcull.runs.rows/v1" in src


def test_no_comment_claims_hydration_uses_the_api_v1_rows_endpoint():
    """The specific stale comment that sent v2.47 down a blind alley."""
    src = _src()
    for m in re.finditer(r"#[^\n]*api/v1/runs/<id>/rows[^\n]*", src):
        line = m.group(0)
        assert "same _build_results fields" not in line, (
            f"a comment again claims the api/v1 rows endpoint carries the "
            f"full field set: {line.strip()}")


# ── the inline cap, measured ──────────────────────────────────────────

def test_inline_slice_is_capped_and_advertises_the_rest():
    """A capped first paint must tell the client there is more.

    Measured v2.47 on synthetic runs (no models, serving path only):

        photos   cold    warm   page      bytes/photo
           200   1.88s   0.01s  1275 KB   6529
           800   0.09s   0.04s  2611 KB   3342
          2000   0.15s   0.04s  2529 KB   1295
          5000   0.36s   0.04s  2529 KB    518

    The page stops growing past 800 rows because that is the inline cap,
    and a 5000-photo run serves the same bytes as a 2000-photo one. That
    is only safe because rows_meta tells the client the real total and
    where to get the rest; without it the cap would be a silent
    truncation, which is what the numbers look like from outside.
    """
    src = _src()
    assert 'os.environ.get("PIXCULL_INLINE_ROWS", "800")' in src, (
        "the inline cap moved or lost its override")
    i = src.index("PIXCULL_INLINE_ROWS")
    around = src[i - 500:i + 1200]
    assert '"rows_meta"' in around or "rows_meta = {" in around, (
        "the capped payload no longer carries rows_meta — the client "
        "would show the first slice and never learn the rest exists")
    for key in ("total", "inlined", "slice"):
        assert f'"{key}"' in around, f"rows_meta lost {key}"
