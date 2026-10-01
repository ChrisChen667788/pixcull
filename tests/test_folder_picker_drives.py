"""v3.91 — on Windows the folder picker could not leave the C: drive.

Issue #2, reported and fixed by gxfc9867 (PR #4). The picker's quick links
were ``~``, Pictures, Desktop, Downloads and ``/Volumes``. The server has
always accepted any absolute path, so the defect was only that the page
offered no way to ask for another drive — and the shoot is usually not on
``C:``.

``/browse`` now reports the drive letters that exist (``roots``) and the
page renders them. The fix was verified by its author on a real Windows
machine; these tests hold the parts that can be held from a machine with
no drive letters, and the two places where a later edit would silently
undo it.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from pixcull.report import serve_app as SA

UPLOAD = (Path(SA.__file__).resolve().parent / "templates" / "pages"
          / "upload.html")


def test_a_machine_with_no_drive_letters_reports_none():
    """POSIX must be unchanged: no roots, whatever the disk looks like."""
    assert SA._drive_roots("posix", isdir=lambda p: True) == []


def test_only_the_drives_that_exist_are_listed():
    """Not a fixed list: a machine with C, D and F gets three buttons, in
    letter order, and no button for a letter with nothing behind it."""
    present = {"C:/", "D:/", "F:/"}
    roots = SA._drive_roots("nt", isdir=lambda p: p in present)
    assert roots == [{"label": "C:", "path": "C:/"},
                     {"label": "D:", "path": "D:/"},
                     {"label": "F:", "path": "F:/"}]


def test_a_windows_machine_with_one_drive_still_gets_it():
    assert SA._drive_roots("nt", isdir=lambda p: p == "C:/") == [
        {"label": "C:", "path": "C:/"}]


def test_the_default_asks_this_machine():
    """No arguments: whatever this OS is. Off Windows that is nothing."""
    import os
    roots = SA._drive_roots()
    if os.name != "nt":
        assert roots == []
    else:                                    # pragma: no cover - Windows CI
        assert roots and all(r["path"].endswith(":/") for r in roots)


@pytest.fixture
def live():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), SA._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _browse(base: str, path: str) -> dict:
    req = urllib.request.Request(
        f"{base}/browse", data=json.dumps({"path": path}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def test_browse_reports_the_roots_the_helper_found(live, tmp_path,
                                                   monkeypatch):
    """The wiring: what the helper returns is what the page receives."""
    fake = [{"label": "E:", "path": "E:/"}]
    monkeypatch.setattr(SA, "_drive_roots", lambda: fake)
    data = _browse(live, str(tmp_path))
    assert data["roots"] == fake
    assert Path(data["path"]) == tmp_path.resolve()


def test_browse_still_answers_as_before_off_windows(live, tmp_path):
    (tmp_path / "shoot").mkdir()
    data = _browse(live, str(tmp_path))
    assert data["roots"] == []
    assert [e["name"] for e in data["entries"]] == ["shoot"]
    assert {"path", "parent", "n_images_here", "entries"} <= set(data)


def _js_code(js: str) -> str:
    """The script with ``//`` comments removed.

    The first version of the test below searched the raw text, and
    commenting out the call it was looking for left it passing — the
    comment still contained the words. A check that its own subject can
    satisfy from inside a comment is not checking the code.
    """
    out = []
    for line in js.splitlines():
        code = line.split("//", 1)[0] if "://" not in line else line
        if code.strip():
            out.append(code)
    return "\n".join(out)


def test_the_page_renders_roots_and_hides_the_macos_shortcut():
    """Two things a later edit to the page could drop without any server
    test noticing: painting the roots it was sent, and getting the
    macOS-only Volumes link out of the way when there are some."""
    html = UPLOAD.read_text("utf-8")
    assert 'id="browserRoots"' in html and 'id="quickVolumes"' in html
    body = html[html.index("function paintRoots("):]
    body = _js_code(body[:body.index("async function loadBrowser(")])
    assert "data.roots" in body
    assert re.search(r'vols\.style\.display\s*=\s*"none"', body)
    assert "loadBrowser(a.dataset.go)" in body, (
        "a painted drive must navigate when clicked")
    load = html[html.index("async function loadBrowser("):]
    load = _js_code(load[:load.index("\n  }\n")])
    assert re.search(r"^\s*paintRoots\(data\);", load, re.M), (
        "loadBrowser must paint the roots from every /browse response")


def test_a_commented_out_call_does_not_count():
    assert "paintRoots(data)" not in _js_code("  // paintRoots(data);\n")
    assert "paintRoots(data)" in _js_code("  paintRoots(data); // why\n")
    assert "https://x" in _js_code('  fetch("https://x");\n')
