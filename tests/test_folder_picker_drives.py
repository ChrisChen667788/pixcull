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


def test_the_logical_drive_list_is_asked_before_any_drive_is_touched():
    """``os.listdrives`` reads a list; ``isdir`` is a stat, and on a mapped
    drive whose server is away a stat waits ten seconds or more. With the
    list available, nothing may be probed."""
    probed = []
    roots = SA._drive_roots(
        "nt", isdir=lambda p: probed.append(p) or True,
        listdrives=lambda: ["C:\\", "E:\\", "Z:\\"])
    assert roots == [{"label": "C:", "path": "C:/"},
                     {"label": "E:", "path": "E:/"},
                     {"label": "Z:", "path": "Z:/"}]
    assert probed == [], f"drives were stat-ed although a list existed: {probed}"


def test_odd_entries_in_the_drive_list_are_left_out():
    roots = SA._drive_roots("nt", isdir=lambda p: False, listdrives=lambda: [
        "d:\\", "C:\\", "\\\\?\\Volume{0}\\", "", "C:\\"])
    assert [r["label"] for r in roots] == ["C:", "D:"]


def test_a_failing_drive_list_falls_back_to_probing():
    def _broken():
        raise OSError("listdrives failed")
    roots = SA._drive_roots("nt", isdir=lambda p: p == "D:/",
                            listdrives=_broken)
    assert roots == [{"label": "D:", "path": "D:/"}]


def test_python_311_has_no_drive_list_and_probes(monkeypatch):
    import os
    monkeypatch.delattr(os, "listdrives", raising=False)
    assert SA._drive_roots("nt", isdir=lambda p: p == "C:/") == [
        {"label": "C:", "path": "C:/"}]


def test_the_drive_list_is_not_rebuilt_on_every_click(monkeypatch):
    """The picker asks on every navigation. One enumeration per window."""
    calls = []
    monkeypatch.setattr(SA, "_drive_roots",
                        lambda: calls.append(1) or [{"label": "C:",
                                                     "path": "C:/"}])
    monkeypatch.setitem(SA._DRIVE_ROOTS_CACHE, "roots", None)
    first = SA._drive_roots_cached(now=1000.0)
    again = SA._drive_roots_cached(now=1000.0 + SA._DRIVE_ROOTS_TTL_S - 1)
    assert first == again and len(calls) == 1
    SA._drive_roots_cached(now=1000.0 + SA._DRIVE_ROOTS_TTL_S + 1)
    assert len(calls) == 2, "a drive plugged in later must show up"


def test_an_empty_answer_is_cached_too(monkeypatch):
    """Off Windows the answer is ``[]``, and ``[]`` is falsy: caching on
    truthiness would re-enumerate on every request."""
    calls = []
    monkeypatch.setattr(SA, "_drive_roots", lambda: calls.append(1) or [])
    monkeypatch.setitem(SA._DRIVE_ROOTS_CACHE, "roots", None)
    SA._drive_roots_cached(now=50.0)
    SA._drive_roots_cached(now=51.0)
    assert len(calls) == 1


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
    monkeypatch.setitem(SA._DRIVE_ROOTS_CACHE, "roots", None)
    data = _browse(live, str(tmp_path))
    assert data["roots"] == fake
    assert Path(data["path"]) == tmp_path.resolve()


def test_browse_still_answers_as_before_off_windows(live, tmp_path,
                                                   monkeypatch):
    monkeypatch.setitem(SA._DRIVE_ROOTS_CACHE, "roots", None)
    (tmp_path / "shoot").mkdir()
    data = _browse(live, str(tmp_path))
    assert data["roots"] == []
    assert [e["name"] for e in data["entries"]] == ["shoot"]
    assert {"path", "parent", "n_images_here", "entries"} <= set(data)


def _js_code(js: str) -> str:
    """The script with ``//`` and ``/* */`` comments removed.

    The first version of the test below searched the raw text, and
    commenting out the call it was looking for left it passing — the
    comment still contained the words. The second stripped ``//`` and not
    ``/* */``, which a reviewer found. A check that its own subject can
    satisfy from inside a comment is not checking the code.
    """
    out = []
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)       # block comments first
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
    assert "paintRoots(data)" not in _js_code("/* paintRoots(data); */\n")
    assert "paintRoots(data)" not in _js_code(
        "/*\n  paintRoots(data);\n*/\nother();\n")
    assert "other()" in _js_code("/*\n  paintRoots(data);\n*/\nother();\n")
