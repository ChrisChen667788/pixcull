"""v2.18-P0 — progressive hydration: big runs inline only the first row
slice (PAYLOAD.rows_meta carries the total); /rows serves the rest."""

import importlib.util
import json
import re
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.test_5k_scale import _synth_scores_csv  # reuse the row factory


@pytest.fixture(scope="module")
def server_mod():
    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "serve_demo_hydration_test", repo / "scripts" / "serve_demo.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["serve_demo_hydration_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _mk_run(root: Path, rid: str, n: int):
    out = root / rid / "output"
    out.mkdir(parents=True)
    _synth_scores_csv(out / "scores.csv", n=n)
    (out / "manifest.json").write_text("{}")


@pytest.fixture
def live(server_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(server_mod, "_DEMO_ROOT", tmp_path)
    _mk_run(tmp_path, "bigrun", 2500)
    _mk_run(tmp_path, "smallrun", 10)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server_mod._Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8")


def test_big_run_inlines_first_slice_only(live):
    html = _get(f"{live}/results/bigrun")
    m = re.search(r'"rows_meta":\s*(\{[^}]*\})', html)
    assert m, "rows_meta missing from big-run payload"
    meta = json.loads(m.group(1))
    assert meta["total"] == 2500
    assert meta["inlined"] == 800
    # the page must NOT carry all 2500 rows inline
    assert html.count('"filename"') < 1000


def test_small_run_keeps_full_inline(live):
    html = _get(f"{live}/results/smallrun")
    assert '"rows_meta": null' in html
    assert html.count('"filename"') >= 10


def test_full_rows_endpoint_serves_the_remainder(live):
    d = json.loads(_get(f"{live}/results_rows/bigrun?offset=800&limit=1000"))
    assert d["ok"] and d["total"] == 2500 and d["offset"] == 800
    assert len(d["rows"]) == 1000
    d2 = json.loads(_get(f"{live}/results_rows/bigrun?offset=2400&limit=1000"))
    assert len(d2["rows"]) == 100
    # FULL shape — hydrated rows must carry everything the inline dump does
    assert {"filename", "decision", "score_final", "rubric_stars",
            "human_decided"} <= set(d["rows"][0])


def test_api_v1_rows_alias_stays_slim_for_ios(live):
    # The v1 alias intentionally serves the iOS SLIM shape (and has
    # shadowed the full endpoint since P2.1 — hydration uses
    # /results_rows/ instead). Guard the coexistence.
    d = json.loads(_get(f"{live}/api/v1/runs/bigrun/rows?offset=0&limit=5"))
    assert d["schema"].startswith("pixcull.api.v1.rows")
    assert d["n_total"] == 2500
    assert "rubric_stars" not in d["rows"][0]
