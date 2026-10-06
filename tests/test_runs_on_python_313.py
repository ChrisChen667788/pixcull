"""v3.94 — Python 3.13 was refused at install, for one module.

``requires-python`` said ``<3.13`` because ``serve_app.py`` parsed uploads
with ``cgi.FieldStorage``, and 3.13 removed ``cgi`` (PEP 594). Measured on
a 3.13 interpreter before changing anything: every dependency installs —
torch, transformers, insightface, pyiqa, rembg, and MediaPipe from the
``[face]`` extra, whose 0.10.35 wheels are tagged ``py3-none`` — and with
``cgi`` replaced the whole suite passes. Nothing else stood in the way.

The parser is ``multipart``, one of the two replacements the Python
documentation's ``cgi`` deprecation note gives for request bodies ("the
email.message module or multipart for POST and PUT"); the other does not
stream. Two of its defaults matter here and are set on
purpose: it refuses more than 128 parts, and an upload may carry 500
files; and it keeps parts under 64 KB in memory and spools the rest to a
temporary file, which is what lets an 8 GB upload through without holding
it in RAM.

The upload had never been tested over HTTP: ``cgi`` worked, so nothing
checked that it did. These tests send real multipart bodies through the
real handler.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from pixcull.report import serve_app as SA

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "pixcull"

#: PEP 594 — removed in 3.13.
REMOVED_IN_313 = {
    "aifc", "audioop", "cgi", "cgitb", "chunk", "crypt", "imghdr", "mailcap",
    "msilib", "nis", "nntplib", "ossaudiodev", "pipes", "sndhdr", "spwd",
    "sunau", "telnetlib", "uu", "xdrlib", "lib2to3",
}


def _imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(node.lineno, a.name.split(".")[0]) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.append((node.lineno, node.module.split(".")[0]))
    return out


def test_nothing_in_the_package_imports_a_module_313_removed():
    bad = [f"{p.relative_to(ROOT)}:{line} imports {mod}"
           for p in sorted(PACKAGE.rglob("*.py"))
           for line, mod in _imports(p) if mod in REMOVED_IN_313]
    assert not bad, bad


def test_the_scan_sees_an_import_inside_a_function(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("def f():\n    import cgi\n    from imghdr import what\n"
                     "# import telnetlib\n", "utf-8")
    assert [m for _, m in _imports(probe)] == ["cgi", "imghdr"]


def test_the_declared_range_includes_313():
    import tomllib
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    assert meta["requires-python"] == ">=3.11,<3.14"
    assert "Programming Language :: Python :: 3.13" in meta["classifiers"]
    assert any(d.startswith("multipart>=2.0,<3") for d in meta["dependencies"])


# -- the upload, over HTTP -----------------------------------------------------

BOUNDARY = "----pixcullTestBoundary7MA4YWxkTrZu0gW"


def _body(parts: list[tuple[str, str | None, bytes]]) -> bytes:
    out = b""
    for name, filename, data in parts:
        disp = f'form-data; name="{name}"'
        if filename is not None:
            disp += f'; filename="{filename}"'
        out += (f"--{BOUNDARY}\r\nContent-Disposition: {disp}\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode("utf-8")
        out += data + b"\r\n"
    return out + f"--{BOUNDARY}--\r\n".encode()


@pytest.fixture
def server(tmp_path, monkeypatch):
    import pixcull.license as L
    monkeypatch.setattr(SA, "_DEMO_ROOT", tmp_path)
    monkeypatch.setattr(SA, "_analyze_in_background", lambda *a, **k: None)
    monkeypatch.setattr(L, "check_quota", lambda n: (True, "test"))
    monkeypatch.setattr(L, "increment_usage", lambda n=1: 0)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), SA._Handler)
    srv.max_upload_bytes = 64 * 1024 * 1024
    srv.max_upload_files = 5
    srv.rescorer_mode = srv.rescorer_path = None
    srv.vlm_mode = srv.meta_mode = "off"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path, srv
    srv.shutdown()


def _post(url: str, data: bytes, *, ctype: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": ctype or f"multipart/form-data; boundary={BOUNDARY}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _saved(root: Path, run_id: str) -> dict[str, bytes]:
    d = root / run_id / "input"
    return {p.name: p.read_bytes() for p in sorted(d.iterdir())}


def test_photos_arrive_byte_for_byte(server, monkeypatch):
    """A part under 64 KB stays in memory, one over it is spooled to disk;
    both must land intact, and a 3 MB RAW must not be read back whole.

    The last clause is checked, not hoped: the spooled part must be copied
    with ``save_as`` (chunked) and never ``read()`` whole. The first version
    of this test asserted only the hashes, and a handler that read the RAW
    into memory passed it (review of v3.94)."""
    import multipart
    copied, whole_reads = [], []
    real_save = multipart.MultipartPart.save_as

    def _save(self, path):
        copied.append((self.filename, self.is_buffered()))
        return real_save(self, path)
    monkeypatch.setattr(multipart.MultipartPart, "save_as", _save)

    class _Spy:
        """Wraps a spooled part's file to see an unbounded read."""
        def __init__(self, f, name):
            self._f, self._name = f, name
        def read(self, n=-1):
            if n is None or n < 0:
                whole_reads.append(self._name)
            return self._f.read(n)
        def __getattr__(self, attr):
            return getattr(self._f, attr)

    real_iter = multipart.MultipartParser.__iter__

    def _iter(self):
        for part in real_iter(self):
            if not part.is_buffered():
                part.file = _Spy(part.file, part.filename)
            yield part
    monkeypatch.setattr(multipart.MultipartParser, "__iter__", _iter)
    base, root, _ = server
    small = b"\xff\xd8\xff" + os.urandom(2000)
    big = os.urandom(3 * 1024 * 1024)
    status, d = _post(base + "/analyze", _body([
        ("files", "a.jpg", small), ("files", "DSC_0001.NEF", big)]))
    assert status == 200, d
    got = _saved(root, d["run_id"])
    assert d["n"] == 2 and set(got) == {"a.jpg", "DSC_0001.NEF"}
    assert hashlib.sha256(got["DSC_0001.NEF"]).digest() == \
        hashlib.sha256(big).digest()
    assert got["a.jpg"] == small
    assert ("DSC_0001.NEF", False) in copied, (
        f"the spooled RAW was not copied with save_as: {copied}")
    assert whole_reads == [], f"a spooled part was read whole: {whole_reads}"


def test_names_are_kept_and_paths_are_not(server):
    """A Windows client may send a path; a Chinese name is a name. The
    parser strips a drive-letter path itself; a relative one with
    backslashes it leaves, and a POSIX ``Path`` does not split it."""
    base, root, _ = server
    status, d = _post(base + "/analyze", _body([
        ("files", "照片 一.jpg", b"x"),
        ("files", "C:\\Users\\someone\\Pictures\\b.jpg", b"y"),
        ("files", "shoot\\day2\\c.jpg", b"w"),
        ("files", "../../escape.jpg", b"z")]))
    assert status == 200, d
    assert set(_saved(root, d["run_id"])) == {
        "照片 一.jpg", "b.jpg", "c.jpg", "escape.jpg"}
    assert not (root / "escape.jpg").exists()


def test_what_is_not_a_photograph_is_skipped_and_counted(server):
    base, root, _ = server
    status, d = _post(base + "/analyze", _body([
        ("files", "notes.txt", b"x"), ("files", "c.png", b"y"),
        ("other", None, b"a field the page does not send")]))
    assert status == 200 and d["n"] == 1
    status, d = _post(base + "/analyze", _body([("files", "notes.txt", b"x")]))
    assert status == 400 and "跳过" in d["error"]


def test_more_files_than_allowed_is_413_not_a_parser_error(server):
    """The parser's own limit is 128 parts. Set to the server's file limit
    plus headroom, the refusal is ours and says what to do."""
    base, _, srv = server
    over = _body([("files", f"f{i}.jpg", b"x") for i in range(srv.max_upload_files + 1)])
    status, d = _post(base + "/analyze", over)
    assert status == 413 and "--max-upload-files" in d["error"]
    way_over = _body([("files", f"f{i}.jpg", b"x") for i in range(200)])
    status, d = _post(base + "/analyze", way_over)
    assert status == 413 and "--max-upload-files" in d["error"]


def test_many_small_files_are_not_refused_for_memory(server):
    """Review of v3.94 — the parser caps the total of in-memory parts at
    8 MB by default, whatever the part limit. 300 photographs of 60 KB
    (18 MB, each kept in memory) were refused, and the refusal said there
    were too many files."""
    base, root, srv = server
    srv.max_upload_files = 500
    status, d = _post(base + "/analyze", _body(
        [("files", f"s{i:03d}.jpg", os.urandom(60_000)) for i in range(300)]))
    assert status == 200, d
    assert d["n"] == 300


def test_a_limit_that_is_not_the_file_count_says_what_it_is(server):
    """A header longer than the parser allows is a 413 too, and must not be
    answered with "upload fewer files"."""
    base, _, _ = server
    status, d = _post(base + "/analyze", _body(
        [("files", "a" * 5000 + ".jpg", b"x")]))
    assert status == 413, d
    assert "--max-upload-files" not in d["error"] and "解析限制" in d["error"]


def test_a_large_upload_is_not_capped_at_128_parts(server):
    """The parser's default would refuse this; the server's limit allows it."""
    base, root, srv = server
    srv.max_upload_files = 300
    status, d = _post(base + "/analyze", _body(
        [("files", f"f{i:03d}.jpg", b"x") for i in range(200)]))
    assert status == 200 and d["n"] == 200


@pytest.mark.parametrize("body,ctype", [
    (b"--nope\r\n", None),                                  # truncated
    (_body([("files", "a.jpg", b"x")])[:-20], None),        # ends early
    (_body([("files", "a.jpg", b"x")]), "multipart/form-data"),  # no boundary
])
def test_a_malformed_body_is_a_400(server, body, ctype):
    base, root, _ = server
    status, d = _post(base + "/analyze", body, ctype=ctype)
    assert status == 400 and "multipart" in d["error"]
    assert not any(root.iterdir()), "a run directory for a body that failed"


def test_spooled_parts_are_closed(server, monkeypatch):
    """A spooled part holds an open temporary file until closed."""
    import multipart
    closed = []
    real = multipart.MultipartPart.close
    monkeypatch.setattr(multipart.MultipartPart, "close",
                        lambda self: closed.append(self.filename) or real(self))
    base, _, _ = server
    status, _ = _post(base + "/analyze", _body([
        ("files", "a.jpg", os.urandom(200_000)), ("files", "b.txt", b"x")]))
    # The handler answers first and closes after, in its `finally`; the
    # first version of this test asserted on the answer and raced it.
    import time
    deadline = time.monotonic() + 5
    while len(set(closed)) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert status == 200 and set(closed) == {"a.jpg", "b.txt"}


def test_the_vertical_sample_upload_goes_through_the_same_parser(server,
                                                                 monkeypatch):
    from pixcull import verticals as V
    key = "landscape"
    saved = []
    monkeypatch.setattr(V, "get_vertical", lambda k: {"key": k})
    monkeypatch.setattr(V, "save_sample",
                        lambda k, b, name, content: saved.append((name, len(content))) or {"name": name})
    monkeypatch.setattr(V, "count_samples", lambda k: {})
    base, _, _ = server
    status, d = _post(f"{base}/verticals/upload/{key}?bucket=good", _body([
        ("files", "one.jpg", b"abc"), ("files", "empty.jpg", b""),
        ("files", "big.jpg", os.urandom(300_000))]))
    assert status == 200, d
    assert saved == [("one.jpg", 3), ("big.jpg", 300_000)]


def test_the_vertical_bank_still_refuses_an_oversized_file(server, monkeypatch):
    from pixcull import verticals as V
    saved = []
    monkeypatch.setattr(SA, "_VERTICAL_SAMPLE_MAX_BYTES", 100_000)
    monkeypatch.setattr(V, "get_vertical", lambda k: {"key": k})
    monkeypatch.setattr(V, "save_sample",
                        lambda k, b, name, content: saved.append(name) or {"name": name})
    monkeypatch.setattr(V, "count_samples", lambda k: {})
    base, _, _ = server
    status, _ = _post(f"{base}/verticals/upload/landscape?bucket=good", _body([
        ("files", "fits.jpg", os.urandom(50_000)),
        ("files", "too_big.jpg", os.urandom(150_000))]))
    assert status == 200 and saved == ["fits.jpg"]


@pytest.mark.parametrize("route", ["/analyze", "/verticals/upload/landscape?bucket=good"])
def test_a_body_with_no_length_is_refused_and_the_thread_is_not_held(server, route):
    """Review of v3.94 — the vertical upload passed a missing Content-Length
    to the parser as -1, which reads until the client closes the
    connection; a keep-alive client never does, and the server thread
    waited forever. Sent over a raw socket that stays open, as a browser's
    would; the answer must come back anyway."""
    import socket
    from urllib.parse import urlsplit
    base, _, _ = server
    u = urlsplit(base)
    body = _body([("files", "a.jpg", b"x")])
    head = (f"POST {route} HTTP/1.1\r\nHost: {u.hostname}\r\n"
            f"Content-Type: multipart/form-data; boundary={BOUNDARY}\r\n"
            f"Connection: keep-alive\r\n\r\n").encode()
    s = socket.create_connection((u.hostname, u.port), timeout=10)
    try:
        s.sendall(head + body)            # no Content-Length, socket left open
        s.settimeout(10)
        reply = s.recv(4096)
    finally:
        s.close()
    assert reply.startswith(b"HTTP/1.") and b" 400 " in reply.split(b"\r\n")[0], reply[:200]


def test_the_parser_helper_refuses_an_unknown_length_for_any_caller():
    import io
    with pytest.raises(ValueError, match="Content-Length"):
        SA._multipart_parts(io.BytesIO(b""), f"multipart/form-data; boundary={BOUNDARY}",
                            -1, max_parts=10)

