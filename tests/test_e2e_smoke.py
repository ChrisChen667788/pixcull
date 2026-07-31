"""v2.41 — one end-to-end journey: run → serve → export.

DESIGN-AUDIT-2031Q1 named this repo's most common defect: **advertised
but unreachable**.  A feature is live, the unit tests are green, and yet
one real user path cannot get to it.  Four independent instances:

* v2.34 — `pixcull library index` reported "nothing resolvable" and
  indexed zero photos, because it never consulted scores.csv's own
  ``path`` column;
* v2.36 — `/timeline` served 50 broken thumbnails and 50 404s, because a
  video run didn't satisfy "is this a run";
* v2.35 — light theme had never once applied on ten pages;
* v2.40 — `pixcull export` exited 1 with no output while the package
  blurb advertised Lightroom/Capture One export.

Every one of them would have been caught here.  None was caught by the
unit suite, because unit tests exercise functions and these were broken
*journeys*.

Two rules this file follows, both learned from those four:

1. **Drive the real entry points.**  A subprocess running the installed
   CLI and an HTTP request to a real server — not an imported function.
   Three of the four bugs were invisible from inside the process.
2. **Assert content, not status.**  All four returned 200 or exited
   quietly.  A smoke test that only checks exit codes would have gone
   green through every one of them.

Hermetic by construction: the pipeline's models are never loaded, so
this runs in the ordinary CI lane.  The `pixcull run` half of the
journey needs real weights and lives in
:func:`test_full_journey_including_run`, gated on the model cache the
same way the rest of the real-model tests are.
"""

from __future__ import annotations

import contextlib
import csv
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

_SCORES_HEADER = "path,filename,scene,decision,score_final,cluster_id\n"
_DECISIONS = ["keep", "keep", "maybe", "cull", "keep", "maybe"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cli(*args, env_extra=None, timeout=300):
    """Run the CLI exactly as a user would: a fresh process."""
    env = {**os.environ, "COLUMNS": "200", "NO_COLOR": "1", "TERM": "dumb",
           **(env_extra or {})}
    return subprocess.run([sys.executable, "-m", "pixcull", *args],
                          capture_output=True, text=True, timeout=timeout,
                          cwd=REPO, env=env)


def _get(url, timeout=60):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@pytest.fixture
def shoot(tmp_path):
    """A finished run, shaped exactly as the pipeline leaves one."""
    from PIL import Image
    import numpy as np

    photos = tmp_path / "photos"
    photos.mkdir()
    out = tmp_path / "myshoot" / "output"
    out.mkdir(parents=True)

    lines = []
    for i, d in enumerate(_DECISIONS):
        p = photos / f"img{i}.jpg"
        a = np.zeros((120, 160, 3), np.uint8)
        a[:, :, i % 3] = 40 + 30 * i
        Image.fromarray(a).save(p, quality=88)
        lines.append(f"{p},img{i}.jpg,landscape,{d},0.{7 - i % 3},{i // 2}\n")
    (out / "scores.csv").write_text(_SCORES_HEADER + "".join(lines),
                                    encoding="utf-8")
    return {"root": tmp_path, "run_dir": out, "photos": photos,
            "run_id": "myshoot"}


@contextlib.contextmanager
def _server(demo_root: Path, lib_dir: Path):
    """A real `pixcull serve` subprocess on a free port."""
    port = _free_port()
    env = {**os.environ,
           "PIXCULL_LIBRARY_DIR": str(lib_dir),
           "PIXCULL_NO_AUTO_INDEX": "1",
           "NO_COLOR": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "pixcull", "serve", "--port", str(port),
         "--root", str(demo_root), "--no-open"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        cwd=REPO, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 180
        while time.time() < deadline:
            if proc.poll() is not None:
                raise AssertionError(
                    "`pixcull serve` exited before serving:\n"
                    + (proc.stdout.read() if proc.stdout else ""))
            with contextlib.suppress(Exception):
                if _get(f"{base}/history", timeout=5)[0] == 200:
                    break
            time.sleep(0.5)
        else:
            raise AssertionError("`pixcull serve` never came up")
        yield base
    finally:
        proc.kill()
        with contextlib.suppress(Exception):
            proc.wait(timeout=30)


def test_journey_serve_then_export(shoot, tmp_path):
    """The whole reachable path, through the real front doors."""
    lib = tmp_path / "lib"

    with _server(shoot["root"], lib) as base:
        # --- the run must be reachable AND carry its rows -------------
        # v2.36: /timeline answered 200 while every thumbnail 404'd, so
        # status alone proves nothing.
        status, body = _get(f"{base}/results/{shoot['run_id']}")
        assert status == 200, f"/results returned {status}"
        text = body.decode("utf-8", "replace")
        for i in range(len(_DECISIONS)):
            assert f"img{i}.jpg" in text, (
                f"img{i}.jpg missing from the results page — the run "
                f"loaded but its rows didn't")

        # --- the API agrees with the page -----------------------------
        status, body = _get(
            f"{base}/api/v1/runs/{shoot['run_id']}/rows?limit=100")
        assert status == 200
        payload = json.loads(body)
        rows = payload.get("rows", payload if isinstance(payload, list) else [])
        assert len(rows) == len(_DECISIONS), (
            f"API returned {len(rows)} rows, expected {len(_DECISIONS)}")

        # --- thumbnails must actually decode --------------------------
        # v2.36 shipped 50 broken images behind 50 HTTP 404s.
        for i in range(len(_DECISIONS)):
            status, blob = _get(
                f"{base}/thumb/{shoot['run_id']}/img{i}.jpg?w=200")
            assert status == 200, f"thumb img{i} → {status}"
            assert blob[:3] == b"\xff\xd8\xff" or blob[:8].startswith(b"\x89PNG"), (
                f"thumb img{i} is not a decodable image ({blob[:12]!r})")

        # --- the standalone pages render ------------------------------
        for route in ("/history", "/library", "/tether"):
            status, body = _get(f"{base}{route}")
            assert status == 200, f"{route} → {status}"
            page = body.decode("utf-8", "replace")
            # v2.35: these pages answered 200 for months while light
            # theme could never apply, because the tokens were absent.
            assert 'html[data-theme="light"]' in page, (
                f"{route} rendered without the light-theme block")
            assert "pixcull_theme" in page, (
                f"{route} rendered without the theme boot script")

    # --- export, through the CLI ------------------------------------
    # v2.40: this exited 1 with no output for years.
    res = _cli("export", str(shoot["run_dir"]))
    assert res.returncode == 0, f"export failed:\n{res.stdout}\n{res.stderr}"

    from pixcull.io.xmp import decision_to_xmp, read_xmp
    for i, d in enumerate(_DECISIONS):
        sidecar = shoot["photos"] / f"img{i}.xmp"
        assert sidecar.is_file(), f"no sidecar for img{i} — Lightroom sees nothing"
        stars, label = decision_to_xmp(d)
        got = read_xmp(shoot["photos"] / f"img{i}.jpg")
        assert got.get("rating") == stars, f"img{i}: rating didn't round-trip"
        assert got.get("color_label") == label, f"img{i}: label didn't round-trip"


def test_journey_csv_export(shoot):
    res = _cli("export", str(shoot["run_dir"]), "--format", "csv")
    assert res.returncode == 0, res.stdout + res.stderr
    rows = list(csv.DictReader(
        (shoot["run_dir"] / "ratings.csv").open(encoding="utf-8")))
    assert [r["decision"] for r in rows] == _DECISIONS


def test_journey_library_index_actually_indexes(shoot, tmp_path):
    """v2.34: this printed 'nothing resolvable' and indexed zero photos
    while reporting success, because it never read scores.csv's `path`.

    The embeddings cache is a pipeline by-product, so synthesise one
    here — this test is about the *resolution* half, which is what broke.
    """
    import numpy as np

    n = len(_DECISIONS)
    rng = np.random.default_rng(0)
    vecs = rng.normal(size=(n, 512)).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    with (shoot["run_dir"] / "embeddings.npz").open("wb") as fh:
        np.savez(fh, filenames=np.array([f"img{i}.jpg" for i in range(n)]),
                 vectors=vecs, model=np.array("clip-vit-base-patch32"))

    lib = tmp_path / "lib"
    res = _cli("library", "index", "--root", str(shoot["root"]),
               "--library", str(lib))
    assert res.returncode == 0, res.stdout + res.stderr

    from pixcull.scoring import library_index as LX
    st = LX.status(lib)
    assert st["n_photos"] == n, (
        f"indexed {st['n_photos']}/{n} — resolution is broken again "
        f"(output was: {res.stdout.strip()})")
    assert st["n_stale"] == 0, "freshly indexed photos reported as missing"


def test_serve_starts_from_a_clean_env(tmp_path):
    """A pip user's very first `pixcull serve` — no runs, no library."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with _server(empty, tmp_path / "lib") as base:
        for route in ("/", "/history", "/library"):
            status, _ = _get(f"{base}{route}")
            assert status == 200, f"{route} → {status} on a fresh install"


@pytest.mark.slow
def test_full_journey_including_run(tmp_path):
    """The other half: `pixcull run` itself.

    Needs real weights, so it is gated on the model cache exactly like
    the other real-model tests — if CLIP is cached it MUST run, and a
    failure is a failure rather than a skip (see tests/_model_gate.py).
    """
    from tests._model_gate import CLIP_REPO, is_cached
    if not is_cached(CLIP_REPO):
        pytest.skip(f"pipeline weights not cached ({CLIP_REPO})")

    from PIL import Image
    import numpy as np

    src = tmp_path / "in"
    src.mkdir()
    rng = np.random.default_rng(1)
    for i in range(3):
        a = rng.integers(0, 255, (240, 320, 3), dtype=np.uint8)
        Image.fromarray(a).save(src / f"s{i}.jpg", quality=88)

    out = tmp_path / "run" / "output"
    res = _cli("run", str(src), "--output", str(out),
               env_extra={"PIXCULL_NO_AUTO_INDEX": "1",
                          "PIXCULL_LIBRARY_DIR": str(tmp_path / "lib")},
               timeout=1800)
    assert res.returncode == 0, f"pixcull run failed:\n{res.stdout[-3000:]}"
    assert (out / "scores.csv").is_file(), "run produced no scores.csv"

    rows = list(csv.DictReader((out / "scores.csv").open(encoding="utf-8")))
    assert len(rows) == 3, f"run scored {len(rows)}/3 images"
    assert all(r.get("decision") for r in rows), "a row has no decision"

    # …and the thing it just produced must export.
    assert _cli("export", str(out)).returncode == 0
