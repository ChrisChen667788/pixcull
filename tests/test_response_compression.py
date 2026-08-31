"""v2.92 — the review page went out at 3.13 MB even when asked for gzip.

The browser sends `Accept-Encoding: gzip` on every request and the
server ignored it. gzip -6 takes the page to 390 KB, an 8x reduction,
measured through a real browser: transferSize 390,754 against
decodedBodySize 3,127,750.

v2.77 correctly refused to ship this as a first-screen fix — on
localhost the download is 11 ms either way. It is for the LAN feature
that already exists and for remote access, and v2.86 just multiplied the
thumbnail bytes on a Retina screen tenfold, so this is the bill for that.

The cost is stated rather than hidden: TTFB goes from 61 ms to 94 ms
locally, which is the compression itself. First-screen ready is
unchanged at 365 ms against 359 ms.
"""
import gzip
import io
import ast
from pathlib import Path

import pytest

SRV = Path(__file__).resolve().parents[1] / "pixcull" / "report" / "serve_app.py"


class _FakeWFile(io.BytesIO):
    pass


class _Recorder:
    """The smallest thing that can stand in for BaseHTTPRequestHandler."""

    def __init__(self, accept_encoding=""):
        from pixcull.report.serve_app import _Handler
        self.headers = {"Accept-Encoding": accept_encoding}
        self.sent = []
        self.status = None
        self.wfile = _FakeWFile()
        self._send_compressible = _Handler._send_compressible.__get__(self)
        self._accepts_gzip = _Handler._accepts_gzip.__get__(self)
        self._GZIP_MIN_BYTES = _Handler._GZIP_MIN_BYTES
        self._GZIP_LEVEL = _Handler._GZIP_LEVEL

    def send_response(self, status):
        self.status = status

    def send_header(self, k, v):
        self.sent.append((k, v))

    def end_headers(self):
        pass

    def header(self, name):
        for k, v in self.sent:
            if k.lower() == name.lower():
                return v
        return None


BIG = b"<html>" + b"the same paragraph over and over. " * 4000 + b"</html>"
SMALL = b"<html>tiny</html>"


def test_a_large_page_is_compressed_when_asked():
    r = _Recorder("gzip, deflate, br")
    r._send_compressible(200, BIG, "text/html; charset=utf-8")
    assert r.header("Content-Encoding") == "gzip"
    body = r.wfile.getvalue()
    assert len(body) < len(BIG) / 4
    assert gzip.decompress(body) == BIG


def test_a_client_that_did_not_ask_gets_the_bytes_unchanged():
    r = _Recorder("")
    r._send_compressible(200, BIG, "text/html; charset=utf-8")
    assert r.header("Content-Encoding") is None
    assert r.wfile.getvalue() == BIG


def test_content_length_describes_what_was_actually_sent():
    """The classic way to break this: compress the body and leave the
    length of the original, so the client waits for bytes that never come."""
    for enc in ("gzip", ""):
        r = _Recorder(enc)
        r._send_compressible(200, BIG, "text/html; charset=utf-8")
        assert int(r.header("Content-Length")) == len(r.wfile.getvalue())


def test_a_compressed_reply_varies_on_the_request_header():
    """Without Vary, a cache hands a gzipped body to a client that never
    asked for one."""
    r = _Recorder("gzip")
    r._send_compressible(200, BIG, "text/html; charset=utf-8")
    assert r.header("Vary") == "Accept-Encoding"


def test_small_replies_are_not_worth_compressing():
    """The payload must be COMPRESSIBLE and under the threshold, or the
    test proves nothing: 17 bytes of HTML gzips to more than 17 bytes and
    the "did it actually help" check rejects it whatever the threshold
    says. This is 2 KB of repetition — gzip shrinks it happily, and the
    threshold is the only thing that declines."""
    payload = b"<html>" + b"ab" * 1000 + b"</html>"
    r = _Recorder("gzip")
    assert len(payload) < r._GZIP_MIN_BYTES
    assert len(gzip.compress(payload, 6)) < len(payload), \
        "the fixture is not compressible, so this tests nothing"
    r._send_compressible(200, payload, "text/html; charset=utf-8")
    assert r.header("Content-Encoding") is None
    assert r.wfile.getvalue() == payload


def test_an_incompressible_tiny_reply_is_also_left_alone():
    r = _Recorder("gzip")
    r._send_compressible(200, SMALL, "text/html; charset=utf-8")
    assert r.header("Content-Encoding") is None
    assert r.wfile.getvalue() == SMALL


def test_a_payload_that_grows_is_sent_uncompressed():
    """Already-compressed bytes come back bigger. Shipping those is a
    slower response wearing a Content-Encoding header."""
    import os
    incompressible = os.urandom(60_000)
    r = _Recorder("gzip")
    r._send_compressible(200, incompressible, "application/octet-stream")
    assert r.header("Content-Encoding") is None
    assert r.wfile.getvalue() == incompressible


def test_the_level_is_not_maximum():
    """Level 9 buys ~3% on this payload for roughly triple the CPU, and
    cold start is the resource v2.77 spent two fixes reclaiming."""
    from pixcull.report.serve_app import _Handler
    assert 1 <= _Handler._GZIP_LEVEL <= 6


def test_images_do_not_route_through_the_text_sender():
    """Gzipping a JPEG spends CPU to make it very slightly larger."""
    src = SRV.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_serve_image":
            body = ast.get_source_segment(src, node) or ""
            assert "_send_compressible" not in body
            assert "_send_html" not in body
            break
    else:
        pytest.fail("_serve_image not found")
