"""Tests for pixcull.report.executive_pdf — v0.9-P1-3.

Covers
------
* Dashboard roll-up: counts, ratios, score median, scene/moment tops
* pick_best_n returns top-scored keep rows
* pick_inconsistencies catches human-vs-model disagreement + borderline
* render_* fragments emit the expected anchor / class markers
* build_executive_html composes a parseable HTML document
* Empty-input edge cases don't crash the layout
* inline_thumb returns a data: URI for a real image and the empty
  placeholder for a missing one
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pixcull.report.executive_pdf import (
    build_executive_html,
    compute_dashboard,
    inline_thumb,
    pick_best_n,
    pick_inconsistencies,
    render_cover_html,
    render_cull_bars_html,
    render_dashboard_html,
    render_toc_html,
    render_wall_html,
)


def _row(fn, decision, score, **kw):
    """Tiny scores.csv-shaped row factory."""
    r = {"filename": fn, "decision": decision, "score_final": score}
    r.update(kw)
    return r


# ---------------------------------------------------------------------------
# compute_dashboard
# ---------------------------------------------------------------------------


def test_dashboard_counts_decisions():
    rows = [
        _row("a.jpg", "keep",  0.82, scene="landscape"),
        _row("b.jpg", "keep",  0.78, scene="landscape"),
        _row("c.jpg", "maybe", 0.61, scene="portrait"),
        _row("d.jpg", "cull",  0.40, scene="portrait",
             cull_reason="focus"),
        _row("e.jpg", "cull",  0.32, scene="wedding",
             cull_reason="blur",
             wedding_moment="ceremony"),
    ]
    d = compute_dashboard(rows)
    assert d["n_total"] == 5
    assert d["n_keep"]  == 2
    assert d["n_maybe"] == 1
    assert d["n_cull"]  == 2
    assert d["keep_ratio"] == pytest.approx(2 / 5)
    assert d["score_median"] == pytest.approx(0.61)
    assert dict(d["scenes_top"])      == {"landscape": 2, "portrait": 2,
                                          "wedding":   1}
    assert dict(d["cull_reasons_top"]) == {"focus": 1, "blur": 1}
    assert dict(d["moments_top"])      == {"ceremony": 1}


def test_dashboard_ignores_unknown_scene():
    rows = [
        _row("a.jpg", "keep", 0.8, scene="unknown"),
        _row("b.jpg", "keep", 0.7, scene="landscape"),
    ]
    d = compute_dashboard(rows)
    # "unknown" is P-CORE-2's abstain sentinel — drops out of the top-N
    assert dict(d["scenes_top"]) == {"landscape": 1}


def test_dashboard_handles_empty():
    d = compute_dashboard([])
    assert d["n_total"] == 0
    assert d["keep_ratio"] == 0.0
    assert d["score_median"] is None
    assert d["scenes_top"] == []


def test_dashboard_human_label_counter():
    rows = [
        _row("a.jpg", "keep", 0.8, rubric_human_labeled="True"),
        _row("b.jpg", "keep", 0.7, rubric_human_labeled="False"),
        _row("c.jpg", "keep", 0.6, rubric_human_labeled="1"),
        _row("d.jpg", "keep", 0.5),
    ]
    d = compute_dashboard(rows)
    assert d["n_with_human"] == 2


# ---------------------------------------------------------------------------
# pick_best_n / pick_inconsistencies
# ---------------------------------------------------------------------------


def test_pick_best_n_sorts_by_score_among_keeps():
    rows = [
        _row("a.jpg", "keep", 0.70),
        _row("b.jpg", "cull", 0.95),    # not a keep — skipped
        _row("c.jpg", "keep", 0.92),
        _row("d.jpg", "keep", 0.85),
        _row("e.jpg", "keep", 0.60),
    ]
    best = pick_best_n(rows, n=3)
    assert [r["filename"] for r in best] == ["c.jpg", "d.jpg", "a.jpg"]


def test_pick_best_n_handles_no_keeps():
    rows = [_row("a.jpg", "cull", 0.40)]
    assert pick_best_n(rows, n=3) == []


def test_pick_inconsistencies_flags_human_mismatch():
    rows = [
        # Human said keep but model gave 0.40 — clear conflict
        _row("a.jpg", "keep", 0.40, rubric_human_labeled="True"),
        # Clear keep, no conflict
        _row("b.jpg", "keep", 0.92, rubric_human_labeled="True"),
        # Borderline (score ≈ keep threshold 0.65)
        _row("c.jpg", "keep", 0.66),
    ]
    flagged = pick_inconsistencies(rows, n=2)
    fns = [r["filename"] for r in flagged]
    # Human-mismatch wins the priority slot
    assert "a.jpg" in fns


def test_pick_inconsistencies_borderline_threshold():
    rows = [_row(f"{i}.jpg", "keep", 0.65 + i * 0.005)
            for i in range(-4, 5)]
    flagged = pick_inconsistencies(rows, n=10)
    # All 9 are within ±0.04 of 0.65 → all flagged
    assert len(flagged) >= 5


# ---------------------------------------------------------------------------
# Render fragments
# ---------------------------------------------------------------------------


def test_render_cover_html_contains_brand_and_stats():
    h = render_cover_html(
        photographer="ChrisChen", client="Li & Liang",
        event="婚礼", event_date="2026-06-15",
        n_total=1500, n_keep=380, keep_ratio=0.253,
    )
    assert "ChrisChen" in h
    assert "Li &amp; Liang" in h  # escaped
    assert "婚礼" in h
    assert "2026-06-15" in h
    assert "1500" in h
    assert "380" in h
    assert "25" in h  # rounded percent
    assert "exec-cover" in h


def test_render_toc_html_lists_anchors():
    toc = render_toc_html([
        ("dashboard", "关键数据"),
        ("best-5",    "最佳 5 张"),
    ])
    assert 'href="#dashboard"' in toc
    assert 'href="#best-5"' in toc
    assert "关键数据" in toc


def test_render_dashboard_html_emits_cards():
    d = compute_dashboard([
        _row("a.jpg", "keep", 0.8, scene="landscape"),
        _row("b.jpg", "cull", 0.3, scene="portrait", cull_reason="focus"),
    ])
    h = render_dashboard_html(d)
    assert "exec-card" in h
    assert "入选率" in h
    assert "landscape" in h
    assert 'id="dashboard"' in h


def test_render_wall_html_empty_case():
    h = render_wall_html("最佳 5 张", [], anchor="best-5",
                          empty_msg="no rows")
    assert "no rows" in h
    assert "exec-wall-card" not in h  # no figs


def test_render_wall_html_with_cards():
    cards = [
        {"thumb": "data:image/png;base64,abc",
         "fn": "IMG_001.jpg", "badge": "BEST", "score": 0.91},
        {"thumb": "data:image/png;base64,def",
         "fn": "IMG_002.jpg", "score": 0.83, "note": "borderline"},
    ]
    h = render_wall_html("最佳 5 张", cards, anchor="best-5")
    assert h.count("exec-wall-card") == 2
    assert "IMG_001.jpg" in h
    assert "BEST" in h
    assert "borderline" in h


def test_render_cull_bars_empty():
    h = render_cull_bars_html([])
    assert "exec-bar-row" not in h
    assert "id=\"cull-reasons\"" in h


def test_render_cull_bars_with_zh_labels():
    h = render_cull_bars_html([("focus", 12), ("blur", 6), ("other", 1)])
    assert "对焦不准" in h
    assert "模糊抖动" in h
    assert "exec-bar-fill" in h


# ---------------------------------------------------------------------------
# build_executive_html — top-level integration
# ---------------------------------------------------------------------------


def test_build_executive_html_is_valid_document():
    d = compute_dashboard([
        _row("a.jpg", "keep", 0.92, scene="landscape"),
        _row("b.jpg", "cull", 0.30, scene="wedding",
             cull_reason="focus"),
    ])
    h = build_executive_html(
        cover={"photographer": "ChrisChen",
               "client":       "Li",
               "event":        "Wedding",
               "event_date":   "2026-06-15"},
        dashboard=d,
        best_cards=[{"thumb": "data:image/png;base64,abc",
                     "fn": "a.jpg", "badge": "BEST", "score": 0.92}],
        inconsistency_cards=[],
        cull_top=list(d.get("cull_reasons_top") or []),
        body_html="<h2>scene audit</h2><table><tr><td>x</td></tr></table>",
        run_id="run_42",
    )
    # Document chrome
    assert h.startswith("<!DOCTYPE html>")
    assert "<html" in h and "</html>" in h
    # Each section is present
    assert 'id="dashboard"' in h
    assert 'id="best-5"' in h
    assert 'id="inconsistency"' in h
    assert 'id="cull-reasons"' in h
    assert 'id="audit"' in h
    # ToC contains a link to each anchor
    for anchor in ("dashboard", "best-5", "inconsistency",
                   "cull-reasons", "audit"):
        assert f'href="#{anchor}"' in h


def test_build_executive_html_empty_run_does_not_crash():
    """An empty scores.csv (no rows) should still produce a doc."""
    h = build_executive_html(
        cover={"photographer": "", "client": "", "event": "", "event_date": ""},
        dashboard=compute_dashboard([]),
        best_cards=[],
        inconsistency_cards=[],
        cull_top=[],
        body_html="<p>no body</p>",
        run_id="empty_run",
    )
    assert "<!DOCTYPE html>" in h
    # Cover still picks up a default title
    assert "Delivery Report" in h


# ---------------------------------------------------------------------------
# inline_thumb
# ---------------------------------------------------------------------------


def test_inline_thumb_missing_path_returns_empty_placeholder():
    uri = inline_thumb(None)
    assert uri.startswith("data:image/png;base64,")


def test_inline_thumb_nonexistent_path_returns_empty_placeholder(tmp_path):
    uri = inline_thumb(tmp_path / "not_here.jpg")
    assert uri.startswith("data:image/png;base64,")


def test_inline_thumb_real_image_returns_jpeg_data_uri(tmp_path):
    pil = pytest.importorskip("PIL.Image")
    p = tmp_path / "real.jpg"
    pil.new("RGB", (1000, 600), (110, 86, 207)).save(p, "JPEG")
    uri = inline_thumb(p, max_side=160)
    assert uri.startswith("data:image/jpeg;base64,")
    # Roundtrip: the data must decode + be smaller than the input
    import base64
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert 200 < len(raw) < 25_000
