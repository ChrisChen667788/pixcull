"""v2.77 — pre-warming must never delay the thing it speeds up.

The first /results request paid 1.6 s for ``import torch``, reached
through _build_face_clusters_info -> pixcull.pipeline.face_library ->
pixcull.pipeline.__init__ -> orchestrator -> duplicate -> torch. Nothing
on the results path looks like a machine-learning import; the cost just
appeared in TTFB.

The first attempt at this started the prewarm before the socket was
bound. The prewarm thread holds Python's import lock while pulling in
torch, the main thread's own imports queued behind it, and the server
took over 90 s to accept a connection under memory pressure — a startup
regression introduced by an optimisation. Hence the ordering test.
"""
import ast
import threading
import time
from pathlib import Path

from pixcull.report.serve_app import _prewarm_heavy_imports

SRC = Path(__file__).resolve().parents[1] / "pixcull" / "report" / "serve_app.py"


def _code_only(path: Path) -> str:
    """Source with comments and docstrings stripped.

    Lints here have repeatedly matched their own prose and passed code
    that was still broken.
    """
    text = path.read_text(encoding="utf-8")
    docs = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docs.add(d)
    lines = []
    for line in text.splitlines():
        lines.append("" if line.lstrip().startswith("#") else line.split("#", 1)[0])
    body = "\n".join(lines)
    for d in docs:
        body = body.replace(d, "")
    return body


def test_prewarm_returns_immediately(monkeypatch):
    """It must hand control straight back — the caller is the startup path."""
    import importlib

    started = threading.Event()

    def slow(_name):
        started.set()
        time.sleep(2.0)
        return None

    monkeypatch.setattr(importlib, "import_module", slow)
    t0 = time.perf_counter()
    _prewarm_heavy_imports()
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.5, f"prewarm blocked the caller for {elapsed:.2f}s"
    assert started.wait(timeout=5), "prewarm never actually ran"


def test_prewarm_survives_a_missing_dependency(monkeypatch):
    """torch is an optional accelerator. A machine without it still serves."""
    import importlib

    calls = []

    def boom(name):
        calls.append(name)
        raise ImportError("no module named torch")

    unhandled = []
    monkeypatch.setattr(threading, "excepthook", lambda a: unhandled.append(a))
    monkeypatch.setattr(importlib, "import_module", boom)
    _prewarm_heavy_imports()          # must not raise
    for _ in range(50):
        if calls:
            break
        time.sleep(0.05)
    assert calls, "prewarm never attempted the import"
    # Letting it escape the thread does not break the server, but it
    # prints a traceback to the console on every start on a machine
    # without torch — which reads as a crash and is not one.
    time.sleep(0.3)
    assert not unhandled, f"prewarm let {unhandled[0].exc_type.__name__} escape its thread"


def test_prewarm_thread_is_a_daemon(monkeypatch):
    """A non-daemon prewarm keeps the process alive after Ctrl-C."""
    import importlib

    seen = {}
    real_thread = threading.Thread

    class Spy(real_thread):
        def __init__(self, *a, **kw):
            seen["daemon"] = kw.get("daemon")
            super().__init__(*a, **kw)

    monkeypatch.setattr(importlib, "import_module", lambda _n: None)
    monkeypatch.setattr(threading, "Thread", Spy)
    _prewarm_heavy_imports()
    assert seen.get("daemon") is True


def test_prewarm_starts_only_after_the_socket_is_listening():
    """The ordering that the 90-second startup taught us.

    Read from code with comments and docstrings stripped, so the mention
    of the call in its own explanation cannot satisfy the check.
    """
    code = _code_only(SRC)
    i = code.find("def main(")
    assert i > 0
    body = code[i:]
    bind = body.find("ThreadingHTTPServer(")
    warm = body.find("_prewarm_heavy_imports()")
    assert bind > 0, "could not find the server construction"
    assert warm > 0, "main() never pre-warms"
    assert warm > bind, (
        "pre-warming starts before the port is bound; the import lock it "
        "holds makes the main thread's own imports queue behind torch"
    )
