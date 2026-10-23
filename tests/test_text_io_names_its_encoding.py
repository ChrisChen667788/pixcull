"""v3.94.4 — every text the package reads or decodes names its encoding.

Issue #5: on Traditional-Chinese Windows (locale cp950) `pixcull run` died
before analysing anything, because `PixCullConfig.load()` opened the bundled
UTF-8 scene templates with `open(path)`, which decodes with the locale. PR #6
fixed that and the two `scores.csv` readers with the same shape. Sweeping for
the class found twelve more of a shape the PR's search did not cover:
`subprocess.run(..., text=True)` decodes the child's output with the locale
too, and four of those parse ffprobe / exiftool JSON, which is UTF-8 whatever
the locale — a video or photo with Chinese metadata crashed the same way.

This reads the source rather than running it, so it holds on every OS and on
paths no test exercises: a text-mode `open()` / `Path.open()`,
`read_text()` / `write_text()`, or a subprocess call with `text=True` /
`universal_newlines=True` must pass `encoding=`. Parsed, not grepped, so a
comment that mentions `encoding=` cannot satisfy it.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "pixcull"

_SUBPROCESS = {"run", "check_output", "Popen", "call", "check_call"}
# `.open()` receivers that are not files opened in text mode.
_NOT_A_TEXT_FILE = {"io", "gzip", "bz2", "lzma", "zipfile", "tarfile", "Image",
                    "webbrowser", "os", "codecs", "sqlite3", "wave", "shelve", "zf", "zip"}


def _const(node):
    return node.value if isinstance(node, ast.Constant) else None


def _mode(call: ast.Call, positional_index: int):
    for kw in call.keywords:
        if kw.arg == "mode":
            return _const(kw.value), True
    if len(call.args) > positional_index:
        return _const(call.args[positional_index]), True
    return None, False


def _kw(call: ast.Call, name: str) -> bool:
    return any(k.arg == name for k in call.keywords)


def _truthy_kw(call: ast.Call, name: str) -> bool:
    return any(k.arg == name and _const(k.value) is True for k in call.keywords)


def problems_in(source: str, filename: str = "<src>") -> tuple[list[str], int]:
    """(offending call sites, number of text-I/O call sites inspected)."""
    found, inspected = [], 0
    for node in ast.walk(ast.parse(source, filename)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        where = f"{filename}:{node.lineno}"
        if isinstance(f, ast.Name) and f.id == "open":
            mode, given = _mode(node, 1)
            if given and mode is None:
                found.append(f"{where} open() with a computed mode: name the encoding")
                continue
            if mode is not None and "b" in mode:
                continue
            inspected += 1
            if not _kw(node, "encoding"):
                found.append(f"{where} open() in text mode without encoding=")
        elif isinstance(f, ast.Attribute) and f.attr == "open":
            recv = ast.unparse(f.value)
            if recv.split(".")[0] in _NOT_A_TEXT_FILE:
                continue
            mode, _ = _mode(node, 0)
            if mode is not None and "b" in mode:
                continue
            inspected += 1
            if not _kw(node, "encoding"):
                found.append(f"{where} {recv}.open() in text mode without encoding=")
        elif isinstance(f, ast.Attribute) and f.attr in ("read_text", "write_text"):
            inspected += 1
            positional_encoding = len(node.args) > (0 if f.attr == "read_text" else 1)
            if not (_kw(node, "encoding") or positional_encoding):
                found.append(f"{where} .{f.attr}() without encoding=")
        elif (isinstance(f, ast.Attribute) and f.attr in _SUBPROCESS
              and ast.unparse(f.value) == "subprocess"):
            if _truthy_kw(node, "text") or _truthy_kw(node, "universal_newlines"):
                inspected += 1
                if not _kw(node, "encoding"):
                    found.append(f"{where} subprocess.{f.attr}(text=True) without encoding=")
    return found, inspected


def test_every_text_read_and_decode_in_the_package_names_its_encoding():
    found, inspected = [], 0
    for path in sorted(PACKAGE.rglob("*.py")):
        f, n = problems_in(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT)))
        found += f
        inspected += n
    # A scan that inspected nothing would pass; the package has hundreds.
    assert inspected > 100, f"only {inspected} text-I/O call sites inspected"
    assert not found, "\n".join(found)


def test_the_scanner_catches_each_shape():
    """The control: one offending call of every kind, one compliant twin."""
    bad = '''
import subprocess
from pathlib import Path
open("a.yaml")
open("a.csv", newline="")
open("a.txt", "w")
Path("a").open()
Path("a").read_text()
Path("a").write_text("x")
subprocess.run(["ffprobe"], capture_output=True, text=True)
subprocess.check_output(["exiftool"], universal_newlines=True)
open("a", mode)
'''
    good = '''
import subprocess
from pathlib import Path
open("a.yaml", encoding="utf-8")
open("a.bin", "rb")
Path("a").open("rb")
Path("a").read_text("utf-8")
Path("a").write_text("x", encoding="utf-8")
subprocess.run(["ffprobe"], capture_output=True, text=True, encoding="utf-8")
subprocess.run(["ffprobe"], capture_output=True)
# open("a")  — a comment cannot fail or satisfy the scan
'''
    found, _ = problems_in(bad)
    assert len(found) == 9, "\n".join(found)
    found, inspected = problems_in(good)
    # Binary opens and a subprocess without text=True are not text I/O.
    assert found == [] and inspected == 4, (found, inspected)
