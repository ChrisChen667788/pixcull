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


# ── v2.53.2: the save button that silently saved nothing ──────────────

def test_download_anchor_is_attached_before_it_is_clicked(photo):
    """The regression that cost a reviewer their pass over 40 frames.

    ``a.click()`` on an anchor that was never inserted into the document
    is ignored outright by Firefox, and a blob download from a ``file://``
    page is blocked by Safari on top of that.  Neither raises.  The panel
    still opened, the JSON still appeared, and the only symptom was the
    eval command later reporting that the file did not exist.

    Asserted on order rather than mere presence: an ``appendChild`` that
    lands after the click is the same bug with extra steps.
    """
    js = render(_items(photo), title="t", lede="l", slug="s")
    save = js[js.index("function save()"):]
    save = save[:save.index("function selectAll")]
    assert "appendChild" in save, "the download anchor is never attached"
    assert save.index("appendChild") < save.index(".click()"), (
        "the anchor is attached only after it is clicked — Firefox drops "
        "the click and nothing is downloaded")


def test_json_is_revealed_even_when_the_download_throws(photo):
    """The visible copy is the guarantee; the download is best-effort.

    Whatever the browser does with the blob, the reviewer must end up
    holding their JSON — so the panel is filled BEFORE the download is
    attempted, not inside the same try block.
    """
    js = render(_items(photo), title="t", lede="l", slug="s")
    save = js[js.index("function save()"):js.index("function selectAll")]
    assert save.index("o.textContent=text") < save.index("try{"), (
        "the JSON is only shown after a download that may throw")
    assert "catch(e)" in save, "a blocked download must not abort save()"


def test_save_reports_which_file_to_write(photo):
    """A silent failure is what made this expensive: say what happened."""
    page = render(_items(photo), title="t", lede="l", slug="my-batch")
    assert 'id="hint"' in page, "no element to report the outcome in"
    assert "FILE='my-batch-review.json'" in page, (
        "the target filename is not stated, so a reviewer whose download "
        "was blocked cannot know what to name the paste")


# ── v2.53.2: the page is served, not double-clicked ───────────────────

def _fetch(srv, path):
    import urllib.error
    import urllib.request
    url = f"http://127.0.0.1:{srv.server_address[1]}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def test_serving_exposes_the_page_and_nothing_else(tmp_path):
    """A review folder also holds the label CSVs — client data.

    Serving the directory would put the whole shoot's metadata on a
    listening socket for the sake of one HTML file.
    """
    import threading

    from pixcull.cli import _review_server

    page = tmp_path / "sheet.html"
    page.write_text("<h1>ok</h1>", encoding="utf-8")
    (tmp_path / "training.csv").write_text("client,data", encoding="utf-8")

    srv = _review_server(page, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert _fetch(srv, "/") == (200, b"<h1>ok</h1>")
        assert _fetch(srv, "/training.csv")[0] == 404
        assert _fetch(srv, "/sheet.html")[0] == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_review_port_is_fixed_so_the_origin_is_stable():
    """localStorage is keyed by origin, so the port cannot be ephemeral.

    An ephemeral port hands the reviewer a different origin on every
    run — the sheet opens empty, showing none of the verdicts they
    already recorded, and nothing reports that anything was lost.
    """
    import inspect

    from pixcull.cli import REVIEW_PORT, m3_open

    assert REVIEW_PORT != 0, "port 0 means a new origin every run"
    default = inspect.signature(m3_open).parameters["port"].default
    got = getattr(default, "default", default)
    assert got == REVIEW_PORT, (
        f"`m3 open` defaults to port {got}, not the fixed {REVIEW_PORT}")


def test_no_card_can_record_the_same_verdict_either_way(photo):
    """Two buttons that write the same value ask nothing.

    The `random` batch is ~40% rows where both systems already agree —
    which is precisely what makes it an unbiased sample. Rendered with
    the disagreement question ("which was right?") those cards offer one
    answer twice, so the reviewer cannot disagree and the row silently
    echoes the rule stack back into the label set. That is the
    circularity the random sample exists to escape, rebuilt inside it.
    """
    items = _items(photo, 2)
    items[0].update({"a": "keep", "b": "keep",
                     "yes_value": "keep", "no_value": "cull",
                     "yes": "留下 · keep", "no": "删掉 · cull"})
    page = render(items, title="t", lede="l", slug="s")
    import re
    pairs = re.findall(r'data-yes="(\w+)"\s+data-no="(\w+)"', page)
    assert pairs, "no cards rendered"
    bad = [p for p in pairs if p[0] == p[1]]
    assert not bad, (
        f"{len(bad)} card(s) record the same verdict for both buttons: "
        f"{bad} — the reviewer cannot disagree with anything")


# ── v2.54.3: the fixed port collides, routinely ───────────────────────

def test_a_busy_port_names_the_squatter_instead_of_a_traceback(tmp_path):
    """Finish a batch, leave the server up, build the next one — collision.

    The fixed port is deliberate (localStorage is per-origin), so this
    is the normal path, not an edge case. Python's own answer is
    `[Errno 48] Address already in use` under forty lines of traceback,
    naming neither the cause nor the fix.

    The dangerous outcome is not the crash: it is opening the URL anyway
    and being served the PREVIOUS batch — already judged, structurally
    identical — and concluding the new sample failed to build.
    """
    import threading

    import typer

    from pixcull.cli import _page_title_on, _review_server, _serve_review_page

    held = tmp_path / "old.html"
    held.write_text("<title>随机抽样复核 · 40 张</title><p>old",
                    encoding="utf-8")
    srv = _review_server(held, 0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert "随机抽样复核" in _page_title_on(port), (
            "cannot name what is on the port, so the error cannot either")

        fresh = tmp_path / "new.html"
        fresh.write_text("<title>new</title>", encoding="utf-8")
        with pytest.raises(typer.Exit) as e:
            _serve_review_page(fresh, port, open_browser=False)
        assert e.value.exit_code == 1
    finally:
        srv.shutdown()
        srv.server_close()


def test_title_probe_is_quiet_on_a_dead_port():
    """The error path must not raise its own error."""
    from pixcull.cli import _page_title_on
    assert _page_title_on(9) == ""
