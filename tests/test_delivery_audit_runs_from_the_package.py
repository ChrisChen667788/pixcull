"""v3.93 — the delivery-audit page ran a script that is not in the wheel.

``/admin/delivery/<run>`` is linked from every row of the admin page. Its
handler built ``Path(__file__).parent / "cli_audit.py"`` and ran it. That
was right while the server was ``scripts/serve_demo.py`` with the audit
script beside it. v2.31 moved the server into the package so that
``pixcull serve`` would work from a pip install; the audit stayed in
``scripts/``, which the wheel does not contain. From then on the handler
looked for a file in ``pixcull/report/`` that was never there, and every
installed copy answered

    500  cli_audit failed (exit 2): … can't open file …/cli_audit.py

``tests/test_cli_audit_smoke.py`` passed throughout: it runs the script by
its path in the checkout, which is the one place it existed. Nothing
asked the route.

The audit is ``pixcull.report.cli_audit`` now and the handler runs it by
module name. Held here: the page renders, through the real handler and a
real subprocess; and the audit runs with nothing but the package on the
path, which is what an installed copy is.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from pixcull.report import serve_app as SA

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "pixcull"
RUN_ID = "0123456789"


def _scores_csv(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename", "scene", "wedding_moment",
                    "face_cluster_id", "face_embeddings"])
        w.writerow(["IMG_001.jpg", "wedding", "first_kiss", 1,
                    json.dumps([[1.0, 0.0, 0.0]])])
        w.writerow(["IMG_002.jpg", "wedding", "processional", 1,
                    json.dumps([[0.98, 0.02, 0.0]])])
        w.writerow(["IMG_003.jpg", "landscape", "", "", ""])
    return path


@pytest.fixture
def live(tmp_path, monkeypatch):
    """The real handler over a run on disk, as after a server restart."""
    monkeypatch.setattr(SA, "_DEMO_ROOT", tmp_path)
    _scores_csv(tmp_path / RUN_ID / "output" / "scores.csv")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), SA._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _get(url: str) -> tuple[int, str]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=120) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


# -- the page ----------------------------------------------------------------

def test_the_delivery_audit_page_renders(live):
    status, body = _get(f"{live}/admin/delivery/{RUN_ID}")
    assert status == 200, f"/admin/delivery answered {status}: {body[:400]}"
    assert RUN_ID in body and "scene" in body.lower()


def test_the_markdown_form_is_the_audits_own_output(live):
    """What the page wraps: if this is the audit's report, the subprocess
    ran and the handler read its stdout."""
    status, md = _get(f"{live}/admin/delivery/{RUN_ID}?format=md")
    assert status == 200, md[:400]
    assert "face library audit" in md and "P-CORE-2" in md
    assert "wedding" in md.lower(), "the wedding rows were not audited"


def test_a_run_that_does_not_exist_is_a_404_not_a_failed_audit(live):
    status, _ = _get(f"{live}/admin/delivery/ffffffffff")
    assert status == 404


def test_an_audit_that_fails_says_so(live, monkeypatch):
    """The other side. A module that is not there must be a 500 that
    names the failure — which is what every installed copy was getting,
    and is the only reason anyone could have diagnosed it."""
    monkeypatch.setattr(SA, "_DELIVERY_AUDIT_MODULE",
                        "pixcull.report.no_such_audit")
    status, body = _get(f"{live}/admin/delivery/{RUN_ID}")
    assert status == 500 and "cli_audit failed" in body
    assert "no_such_audit" in body


# -- where the audit lives ---------------------------------------------------

def test_the_module_the_handler_runs_is_inside_the_package():
    spec = importlib.util.find_spec(SA._DELIVERY_AUDIT_MODULE)
    assert spec is not None and spec.origin, (
        f"{SA._DELIVERY_AUDIT_MODULE} cannot be imported")
    origin = Path(spec.origin).resolve()
    assert PACKAGE.resolve() in origin.parents, (
        f"the delivery audit resolves to {origin}, outside the package — "
        "the wheel ships the package and nothing else")


def _site_with_only_the_package(tmp_path: Path) -> Path:
    """What a pip install leaves: the package, and none of the checkout."""
    site = tmp_path / "site"
    shutil.copytree(PACKAGE, site / "pixcull", ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".venv", "*.onnx"))
    return site


def test_the_audit_runs_with_only_the_package_on_the_path(tmp_path):
    """The condition the old layout failed. No ``scripts/``, no checkout
    as the working directory, no repo on the path — the package alone."""
    site = _site_with_only_the_package(tmp_path)
    assert not (site / "scripts").exists()
    scores = _scores_csv(tmp_path / "run" / "scores.csv")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(site)
    work = tmp_path / "elsewhere"
    work.mkdir()

    where = subprocess.run(
        [sys.executable, "-c",
         f"import {SA._DELIVERY_AUDIT_MODULE} as m; print(m.__file__)"],
        cwd=work, env=env, capture_output=True, text=True, timeout=120)
    assert where.returncode == 0, where.stderr[-600:]
    assert Path(where.stdout.strip()).resolve().is_relative_to(
        site.resolve()), (
        f"the probe imported {where.stdout.strip()}, not the copy under "
        f"{site} — it would pass with the checkout's help")

    proc = subprocess.run(
        [sys.executable, "-m", SA._DELIVERY_AUDIT_MODULE,
         "--scores-csv", str(scores)],
        cwd=work, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "face library audit" in proc.stdout


def test_the_old_path_still_answers():
    """``python scripts/cli_audit.py`` is in release notes and muscle
    memory; it forwards to the module."""
    shim = (ROOT / "scripts" / "cli_audit.py").read_text("utf-8")
    assert "from pixcull.report.cli_audit import main" in shim
    assert len(shim.splitlines()) < 30, (
        "scripts/cli_audit.py is a shim; an implementation growing back "
        "there is one the wheel will not carry")
