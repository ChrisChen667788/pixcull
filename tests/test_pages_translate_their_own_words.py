"""v3.102 — a page translates its own wording, never the photographer's.

The history and disagreement pages put the run cards into the template and
then translated the whole page. A run folder whose name is a catalogue key
was translated with it: `上传` is the key for the upload link, so a run
called `上传` became `/results/Upload` in English, and that link 404s. The
results page always localised its template first and inserted the user's
content after; these two pages do the same now, and their own fragments
(counts, empty states) go through the catalogue one at a time.

Found reviewing PR #7, the contribution that made these pages English.
"""
from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from tests.test_video_discoverability import _build_photo_run, _get, _import_server

# Each is a real key in its own page's catalogue, so translating the run
# name would change it: the history page's word for the upload link, and the
# disagreement page's column heading.
RUN = "上传"
DIS_RUN = "反转率"


@pytest.fixture(scope="module")
def server_mod():
    return _import_server()


@pytest.fixture
def live(server_mod, tmp_path, monkeypatch):
    home = tmp_path / "home"
    runs = home / ".pixcull" / "runs" / DIS_RUN
    runs.mkdir(parents=True)
    # One reversal so the disagreement page lists the run by name.
    rows = [{"filename": f"p{i}.jpg", "decision": "cull",
             "model_decision": "keep", "scene": "landscape"} for i in range(3)]
    (runs / "annotations.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))          # report + its cache
    demo = tmp_path / "demo"
    demo.mkdir()
    monkeypatch.setattr(server_mod, "_DEMO_ROOT", demo)
    _build_photo_run(demo, RUN)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server_mod._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address
    srv.shutdown()


def test_the_keys_are_really_in_the_catalogues():
    """Otherwise the tests below pass whatever the order is."""
    from pixcull.report.page_i18n import localize_page
    assert localize_page("pages/history.html", RUN, "en_US") != RUN
    assert localize_page("pages/disagreement.html", DIS_RUN, "en_US") != DIS_RUN


def test_history_keeps_the_run_name_and_translates_the_page(live):
    status, html = _get(live, "/history?lang=en_US")
    assert status == 200
    assert f"/results/{RUN}" in html
    assert "/results/Upload" not in html
    assert "Upload page" in html            # the page itself is English
    assert " photos · " in html             # and so is the count fragment


def test_disagreement_keeps_the_run_name_and_translates_the_page(live):
    status, html = _get(live, "/admin/disagreement?lang=en_US")
    assert status == 200
    assert f"/results/{DIS_RUN}'>{DIS_RUN}</a>" in html
    assert "/results/Reversal" not in html
    assert "Disagreement analysis" in html
    assert " records · " in html


def test_chinese_is_still_the_template_unchanged(live):
    status, html = _get(live, "/history?lang=zh_CN")
    assert status == 200
    assert f"/results/{RUN}" in html and "个 run" in html


def test_the_bulk_classifier_is_translated_before_it_is_filled_in(live):
    """Review of v3.102 found the same order on a third page: the vertical's
    name went into `批量分类 · __VZH__` first, and no catalogue key matched
    what was left, so the English title and heading stayed Chinese."""
    status, html = _get(live, "/verticals/bulk/landscape?lang=en_US")
    assert status == 200
    assert "<title>PixCull · Bulk classify · Landscape</title>" in html
    assert "批量分类" not in html and "风光摄影" not in html
    status, html = _get(live, "/verticals/bulk/landscape?lang=zh_CN")
    assert status == 200
    assert "<title>PixCull — 批量分类 · 风光摄影</title>" in html
