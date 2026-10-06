"""v3.93.1 — what an installed copy could not reach, and now can or says so.

v3.93 found the delivery-audit page running a script the wheel does not
carry. Sweeping the package for that defect class — a feature needing a
file that exists in a checkout and not in an install — found five more,
each confirmed against the published 3.92.0 wheel:

* the MediaPipe face models (``pixcull/detectors/_models/``), tracked and
  never in the build allowlist, so ``pixcull[face]`` found no face;
* the vendored font and the empty-state art, served from the
  repository's ``docs/``;
* the app icon, three PNGs that have never existed anywhere;
* user LUTs, looked for beside the repository;
* retraining and the sample run, which need a checkout and offered
  themselves on every install anyway.

The packaging side (the files are in the wheel, and a gate derives that
list from the code) is in ``tests/test_packaging.py``. This file holds
the behaviour: served from the package, found in the user's folder, or
refused up front with the reason — tested with the checkout taken away,
since a checkout is the one place none of this was ever broken.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from pixcull.report import serve_app as SA

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(SA, "_DEMO_ROOT", tmp_path)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), SA._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def installed(monkeypatch):
    """No checkout: what `pip install pixcull` gives the server."""
    monkeypatch.setattr(SA, "_repo_root", lambda: None)


def _req(url: str, *, data: bytes | None = None,
         method: str | None = None) -> tuple[int, dict, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=data, method=method, headers=(
        {"Content-Type": "application/json"} if data is not None else {}))
    try:
        with opener.open(req, timeout=60) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


# -- assets the pages load ----------------------------------------------------

ASSETS = [
    ("/docs/brand/geist-variable.woff2", "font/woff2"),
    ("/docs/brand/pixcull-icon.svg", "image/svg+xml"),
    ("/docs/illustrations/art-empty-history.png", "image/png"),
    ("/docs/illustrations/art-empty-inbox.png", "image/png"),
    ("/docs/illustrations/art-no-match.png", "image/png"),
    ("/docs/illustrations/art-no-search.png", "image/png"),
]


@pytest.mark.parametrize("url,ctype", ASSETS, ids=[a[0] for a in ASSETS])
def test_an_install_serves_what_the_pages_load(server, installed, url, ctype):
    status, headers, body = _req(server + url)
    assert status == 200, f"{url} → {status} with no checkout"
    assert headers.get("Content-Type", "").startswith(ctype)
    assert len(body) > 100


def test_a_checkout_still_serves_the_readme_artwork(server):
    """The other side: docs/brand still holds what the README shows, and a
    checkout still serves it."""
    status, _, _ = _req(server + "/docs/brand/pixcull-hero-dark.svg")
    assert status == 200


def test_an_install_does_not_serve_the_directory_above_the_package(
        server, installed):
    """The old fallback for an install was site-packages itself."""
    for url in ("/docs/brand/../../serve_app.py",
                "/docs/brand/..%2F..%2Fserve_app.py",
                "/docs/../pixcull/report/serve_app.py",
                "/docs/brand/pixcull-hero-dark.svg"):
        status, _, body = _req(server + url)
        assert status in (403, 404), f"{url} → {status}"
        assert b"def _serve_static_doc_asset" not in body


def test_a_checkout_cannot_be_walked_out_of_docs(server):
    for url in ("/docs/brand/../../pyproject.toml",
                "/docs/illustrations/../../CLAUDE.md"):
        status, _, body = _req(server + url)
        assert status in (403, 404), f"{url} → {status}"
        assert b"[project]" not in body


def test_every_icon_the_manifest_names_is_served(server, installed):
    status, _, body = _req(server + "/manifest.json")
    assert status == 200
    icons = json.loads(body)["icons"]
    assert icons, "the manifest names no icon"
    for icon in icons:
        st, headers, _ = _req(server + icon["src"])
        assert st == 200, f"{icon['src']} → {st}"
        assert headers.get("Content-Type", "").startswith(icon["type"])


# -- retraining ---------------------------------------------------------------

def test_an_install_refuses_to_retrain_before_starting(server, installed,
                                                       monkeypatch):
    started = []
    monkeypatch.setattr(SA, "_retrain_in_background",
                        lambda *a: started.append(a))
    status, _, body = _req(server + "/retrain", data=b"{}", method="POST")
    assert status == 409
    assert "源码仓库" in json.loads(body)["error"]
    assert started == [], "a retrain was started that can only fail"


def test_the_admin_page_is_told_before_anyone_clicks(server, installed):
    status, _, body = _req(server + "/retrain_status")
    state = json.loads(body)
    assert status == 200 and state["available"] is False
    assert "源码仓库" in state["unavailable_reason"]
    page = (ROOT / "pixcull" / "report" / "templates" / "pages"
            / "admin.html").read_text("utf-8")
    block = page[page.index('fetch("/retrain_status")'):]
    block = block[:block.index("// Status pill")]
    assert "s.available === false" in block and "retrainBtn.disabled = true" in block


def test_a_checkout_can_still_retrain(server, monkeypatch):
    started = []
    monkeypatch.setattr(SA, "_retrain_in_background",
                        lambda *a: started.append(a))
    monkeypatch.setattr(SA, "_RETRAIN_STATE", {})
    status, _, _ = _req(server + "/retrain", data=b"{}", method="POST")
    assert status == 200
    _, _, body = _req(server + "/retrain_status")
    assert json.loads(body)["available"] is True


def _run_on_disk(root: Path, rid: str = "abcdef0123") -> str:
    out = root / rid / "output"
    out.mkdir(parents=True)
    (out / "scores.csv").write_text("filename,decision\na.jpg,keep\n", "utf-8")
    return rid


@pytest.mark.parametrize("checkout", [True, False],
                         ids=["checkout", "install"])
def test_the_tenth_correction_retrains_only_where_it_can(
        server, tmp_path, monkeypatch, checkout):
    """Every tenth correction started a retrain. From an install it died on
    its first import and left the admin page in an error state."""
    if not checkout:
        monkeypatch.setattr(SA, "_repo_root", lambda: None)
    started = []
    monkeypatch.setattr(SA, "_retrain_in_background",
                        lambda *a: started.append(a))
    monkeypatch.setattr(SA, "_AUTO_RETRAIN_THRESHOLD", 1)
    monkeypatch.setattr(SA, "_annotations_since_retrain", 0)
    monkeypatch.setattr(SA, "_RETRAIN_STATE", {})
    rid = _run_on_disk(tmp_path)
    status, _, body = _req(
        f"{server}/annotation/{rid}/a.jpg", method="POST",
        data=json.dumps({"overall_label": "cull"}).encode("utf-8"))
    assert status == 200, body[:300]
    assert json.loads(body)["auto_retrain_spawned"] is checkout
    assert bool(started) is checkout


# -- the sample run -----------------------------------------------------------

def test_an_install_says_it_has_no_sample_run(server, installed):
    status, _, body = _req(server + "/sample_demo")
    d = json.loads(body)
    assert status == 200 and d["available"] is False and d["why"]
    status, _, body = _req(server + "/sample_demo", data=b"", method="POST")
    assert status == 404, "nothing failed; the data is not in an install"
    assert "源码仓库" in json.loads(body)["error"]


def test_a_checkout_offers_it(server):
    status, _, body = _req(server + "/sample_demo")
    assert status == 200 and json.loads(body)["available"] is True


def test_the_upload_page_asks_before_showing_the_button():
    page = (ROOT / "pixcull" / "report" / "templates" / "pages"
            / "upload.html").read_text("utf-8")
    code = "\n".join(l.split("//", 1)[0] for l in page.splitlines())
    assert 'fetch("/sample_demo").then' in code
    assert "sampleBtn.hidden = true" in code


# -- LUTs ---------------------------------------------------------------------

def _cube(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(f"{r} {g} {b}" for b in (0, 1) for g in (0, 1)
                     for r in (0, 1))
    path.write_text(f"LUT_3D_SIZE 2\n{rows}\n", "utf-8")
    return path


@pytest.fixture
def lut_dirs(tmp_path, monkeypatch):
    from pixcull.scoring import color_grade as C
    user, checkout, env = (tmp_path / "home_luts", tmp_path / "repo_luts",
                           tmp_path / "env_luts")
    monkeypatch.setattr(C, "USER_LUTS_DIR", user)
    monkeypatch.setattr(C, "CHECKOUT_LUTS_DIR", checkout)
    monkeypatch.delenv("PIXCULL_LUTS_DIR", raising=False)
    C._CUBE_CACHE.clear()
    return C, user, checkout, env


def test_an_install_finds_luts_in_the_users_folder(lut_dirs):
    C, user, checkout, _ = lut_dirs
    assert not checkout.exists(), "no checkout, as from a wheel"
    _cube(user / "Kodak2383.cube")
    assert [c["id"] for c in C.list_cubes()] == ["cube:Kodak2383"]
    assert C._resolve_cube("cube:Kodak2383") is not None


def test_a_checkouts_folder_is_still_read(lut_dirs):
    C, _, checkout, _ = lut_dirs
    _cube(checkout / "Fuji3513.cube")
    assert [c["id"] for c in C.list_cubes()] == ["cube:Fuji3513"]


def test_the_env_folder_comes_first_and_a_name_is_listed_once(
        lut_dirs, monkeypatch):
    C, user, checkout, env = lut_dirs
    a = _cube(env / "Look.cube")
    _cube(user / "Look.cube")
    _cube(checkout / "Other.cube")
    monkeypatch.setenv("PIXCULL_LUTS_DIR", str(env))
    assert C.luts_dirs()[0] == env
    assert [c["id"] for c in C.list_cubes()] == ["cube:Look", "cube:Other"]
    assert C._cube_files()["Look"] == a


def test_an_explicit_folder_is_the_only_one_read(lut_dirs, tmp_path):
    C, user, _, _ = lut_dirs
    _cube(user / "Mine.cube")
    only = _cube(tmp_path / "only" / "There.cube").parent
    assert [c["id"] for c in C.list_cubes(only)] == ["cube:There"]
    assert C._resolve_cube("cube:Mine", only) is None


def test_the_folder_setting_is_registered_and_documented():
    from pixcull.env_registry import KNOWN
    assert "PIXCULL_LUTS_DIR" in KNOWN
    guide = (ROOT / "docs" / "USER-GUIDE.md").read_text("utf-8")
    assert "`PIXCULL_LUTS_DIR`" in guide


# -- face detection -----------------------------------------------------------

def test_face_detection_says_when_mediapipe_is_missing(monkeypatch):
    import importlib.util
    from pixcull.detectors import face as F
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda n, *a: None if n == "mediapipe" else real(n, *a))
    why = F.face_detection_unavailable()
    assert why and "pixcull[face]" in why


def test_face_detection_says_when_the_models_are_missing(monkeypatch, tmp_path):
    import importlib.util
    from pixcull.detectors import face as F
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda n, *a: object() if n == "mediapipe" else real(n, *a))
    monkeypatch.setattr(F, "FACE_LANDMARKER_MODEL", tmp_path / "gone.task")
    why = F.face_detection_unavailable()
    assert why and "gone.task" in why and "reinstall" in why


def test_face_detection_has_nothing_to_say_when_it_can_run(monkeypatch):
    import importlib.util
    from pixcull.detectors import face as F
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda n, *a: object() if n == "mediapipe" else real(n, *a))
    assert F.FACE_DETECTOR_MODEL.is_file() and F.FACE_LANDMARKER_MODEL.is_file()
    assert F.face_detection_unavailable() is None


def test_the_run_summary_asks_once_in_the_main_process():
    """Not in the detector, which runs per frame in every worker."""
    import ast
    src = (ROOT / "pixcull" / "pipeline" / "orchestrator.py").read_text("utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "run_pipeline")
    calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
             and getattr(c.func, "id", "") == "face_detection_unavailable"]
    assert len(calls) == 1
    face_src = (ROOT / "pixcull" / "detectors" / "face.py").read_text("utf-8")
    det = ast.parse(face_src)
    cls = next(n for n in ast.walk(det)
               if isinstance(n, ast.ClassDef) and n.name == "FaceDetector")
    assert not any(getattr(c.func, "id", "") == "face_detection_unavailable"
                   for c in ast.walk(cls) if isinstance(c, ast.Call))
