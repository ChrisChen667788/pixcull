"""v2.53 — the disagreement-review page.

This mechanism is the reason the M3 evaluation stopped being circular, so
its properties are worth pinning rather than trusting:

* the photos stay on the machine (embedded, never uploaded)
* the reviewer's verdicts survive a closed tab
* building the page never spends money
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixcull.report.review_sheet import (
    load_verdicts,
    render,
    thumbnail_data_uri,
    write,
)


@pytest.fixture
def photo(tmp_path):
    from PIL import Image
    p = tmp_path / "shot.jpg"
    Image.new("RGB", (2400, 1600), (90, 120, 80)).save(p, "JPEG")
    return p


def _items(photo, n=2):
    return [{"fn": f"img_{i}.jpg", "path": str(photo), "scene": "portrait",
             "a": "cull", "b": "keep", "note": "推翻了 closed_eyes",
             "why": f"理由 {i}", "axes": {"technical": 4, "moment": 5},
             "yes": "M3 对了", "no": "M3 错了"} for i in range(n)]


# ---------------------------------------------------------------------------
# The photos stay here
# ---------------------------------------------------------------------------

def test_the_photo_is_embedded_not_linked(photo):
    """A <img src="/Users/…/wedding/IMG_1234.jpg"> would leak the client
    folder layout to anyone the file is forwarded to, and would break the
    moment the drive unmounts."""
    doc = render(_items(photo), title="t", lede="l", slug="s")
    assert "data:image/jpeg;base64," in doc
    assert str(photo) not in doc


def test_no_network_references_at_all(photo):
    """Self-contained: no CDN, no font host, no analytics. This file gets
    opened on machines that should not be phoning anywhere."""
    doc = render(_items(photo), title="t", lede="l", slug="s")
    for token in ("http://", "https://", "//cdn", "fetch(", "XMLHttpRequest"):
        assert token not in doc, f"page reaches out via {token!r}"


def test_a_big_photo_is_downscaled(photo):
    """A 45 MP shoot must not produce a file nobody can open."""
    uri = thumbnail_data_uri(photo, px=400)
    assert len(uri) < 400_000


# ---------------------------------------------------------------------------
# The reviewer's work survives
# ---------------------------------------------------------------------------

def test_verdicts_are_mirrored_to_local_storage(photo):
    """The first version only offered "copy to clipboard", so a closed tab
    lost the pass. Ten minutes of a photographer's judgement is the
    scarcest input this system has."""
    doc = render(_items(photo), title="t", lede="l", slug="s")
    assert "localStorage.setItem" in doc
    assert "localStorage.getItem" in doc


def test_a_reload_repaints_what_was_already_judged(photo):
    doc = render(_items(photo), title="t", lede="l", slug="s")
    assert "DOMContentLoaded" in doc and "paint(i)" in doc


def test_saving_produces_a_file_not_just_a_paste(photo):
    doc = render(_items(photo), title="t", lede="l", slug="s")
    assert "Blob(" in doc and "download=" in doc


def test_the_storage_key_is_per_review(photo):
    """Two different review sets must not overwrite each other."""
    a = render(_items(photo), title="t", lede="l", slug="overrides")
    b = render(_items(photo), title="t", lede="l", slug="disagreements")
    assert "pixcull-review-overrides" in a
    assert "pixcull-review-disagreements" in b


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------

def test_saved_json_reads_back(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"reviewed_at": "now", "verdicts":
                             {"a.jpg": "keep", "b.jpg": "cull"}}))
    assert load_verdicts(p) == {"a.jpg": "keep", "b.jpg": "cull"}


def test_the_old_clipboard_format_still_reads(tmp_path):
    """The first review was done before there was a JSON format. Losing
    those 18 verdicts to a parser upgrade would be absurd."""
    p = tmp_path / "r.txt"
    p.write_text("M3 推翻复核结果\n该留  a.jpg\n该扔  b.jpg\n", encoding="utf-8")
    assert load_verdicts(p) == {"a.jpg": "该留", "b.jpg": "该扔"}


def test_write_creates_the_file(photo, tmp_path):
    dest = write(_items(photo), tmp_path / "deep" / "r.html",
                 title="t", lede="l", slug="s")
    assert dest.exists() and dest.stat().st_size > 1000


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

def test_the_overturned_flag_is_shown(photo):
    """Without it the reviewer cannot tell WHY the rule wanted it gone."""
    doc = render(_items(photo), title="t", lede="l", slug="s")
    assert "closed_eyes" in doc


def test_filenames_are_escaped(photo):
    it = _items(photo, 1)
    it[0]["fn"] = '<script>alert(1)</script>.jpg'
    doc = render(it, title="t", lede="l", slug="s")
    assert "<script>alert(1)</script>.jpg" not in doc
    assert "&lt;script&gt;" in doc


def test_the_cli_command_exists():
    from typer.testing import CliRunner

    from pixcull.cli import app
    assert "review" in CliRunner().invoke(app, ["m3", "--help"]).output


def test_the_review_page_is_built_from_cache_only():
    """Building a review page must never bill. Asserted structurally: the
    command skips any row whose verdict did not come from the cache."""
    import inspect

    from pixcull import cli
    src = inspect.getsource(cli.m3_review)
    assert "v.elapsed_s > 0" in src, (
        "nothing distinguishes a cache hit from a paid call, so building "
        "the page could quietly spend money")


def test_eval_accepts_a_saved_review():
    import inspect

    from pixcull import cli
    assert "--review" in inspect.getsource(cli.m3_eval)
    assert "load_verdicts" in inspect.getsource(cli.m3_eval)


# ---------------------------------------------------------------------------
# v2.53.1 — the answer differs per card
# ---------------------------------------------------------------------------

def test_each_card_records_its_own_verdict(photo):
    """A page-level pair of labels is wrong the moment the pool has more
    than one direction in it.

    The first batch was entirely cull→keep, so one fixed pair worked. The
    second is 88% keep→maybe, where "M3 was right" means `maybe` — and the
    fixed pair silently recorded `keep`/`cull` for every one of them. A
    whole review pass would have produced labels for a question nobody
    was asked.
    """
    items = [
        {"fn": "a.jpg", "path": str(photo), "a": "keep", "b": "maybe",
         "yes_value": "maybe", "no_value": "keep", "axes": {}},
        {"fn": "b.jpg", "path": str(photo), "a": "keep", "b": "cull",
         "yes_value": "cull", "no_value": "keep", "axes": {}},
    ]
    doc = render(items, title="t", lede="l", slug="s")
    assert 'data-yes="maybe"' in doc and 'data-yes="cull"' in doc
    assert doc.count('data-no="keep"') == 2


def test_the_saved_label_comes_from_the_card_not_the_page(photo):
    doc = render([{"fn": "a.jpg", "path": str(photo), "a": "keep",
                   "b": "maybe", "axes": {}}], title="t", lede="l", slug="s")
    assert "c.dataset.yes" in doc and "c.dataset.no" in doc


def test_button_text_names_the_actual_decision(photo):
    """"M3 对了 · 该留" on a demotion asks the reviewer the wrong
    question."""
    doc = render([{"fn": "a.jpg", "path": str(photo), "a": "keep",
                   "b": "maybe", "axes": {}}], title="t", lede="l", slug="s")
    assert "M3 对了 · maybe" in doc
    assert "规则对了 · keep" in doc


# ---------------------------------------------------------------------------
# v2.53.1 — sampling, not truncation
# ---------------------------------------------------------------------------

def _pool():
    """19 high-stakes rows buried under 166 cheap ones, as measured."""
    out = [{"fn": f"cull{i}.jpg", "bucket": "keep->cull", "scene": "portrait"}
           for i in range(19)]
    for i in range(166):
        out.append({"fn": f"maybe{i}.jpg", "bucket": "keep->maybe",
                    "scene": ["landscape", "portrait", "event"][i % 3]})
    return out


def test_the_expensive_bucket_is_covered_in_full():
    """M3 wanting to CULL a rule-keep can destroy a keeper; a demotion to
    maybe costs a second look. Proportional sampling would show 4 of the
    19 — covering the cheap failure well and the expensive one barely."""
    from pixcull.report.review_sheet import stratify
    picked = stratify(_pool(), 40, priority=("keep->cull",))
    assert sum(1 for p in picked if p["bucket"] == "keep->cull") == 19


def test_the_remainder_spreads_across_scenes():
    """A correction set drawn entirely from landscapes teaches you about
    landscapes."""
    from pixcull.report.review_sheet import stratify
    picked = stratify(_pool(), 40, priority=("keep->cull",))
    rest = [p for p in picked if p["bucket"] != "keep->cull"]
    scenes = {p["scene"] for p in rest}
    assert len(scenes) >= 3, f"only sampled {scenes}"


def test_a_prefix_would_have_been_worse():
    """The property under test, stated as a comparison."""
    from pixcull.report.review_sheet import stratify
    pool = _pool()
    prefix_scenes = {p["scene"] for p in pool[:40] if p["bucket"] != "keep->cull"}
    sampled = stratify(pool, 40, priority=("keep->cull",))
    sampled_scenes = {p["scene"] for p in sampled if p["bucket"] != "keep->cull"}
    assert len(sampled_scenes) >= len(prefix_scenes)


def test_sampling_never_exceeds_the_quota():
    from pixcull.report.review_sheet import stratify
    assert len(stratify(_pool(), 40, priority=("keep->cull",))) == 40
    assert len(stratify(_pool(), 5, priority=("keep->cull",))) == 5


def test_a_small_pool_is_returned_whole():
    from pixcull.report.review_sheet import stratify
    small = _pool()[:6]
    assert len(stratify(small, 40, priority=("keep->cull",))) == 6
