"""v2.31 — the review workspace must be reachable from a pip install.

Until v2.31 the server lived at ``scripts/serve_demo.py`` and resolved
every asset via ``Path(__file__).parent.parent`` — i.e. "there is a repo
root above me", which is false in a wheel. A pip user could run the
scoring CLI but never open the culling UI (README-PYPI said "git clone").

These guard the packaging contract without needing a full install:
the server module ships inside the package, resolves REQUIRED assets
through the package root, and the CLI exposes `serve`.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_IMPL = _REPO / "pixcull" / "report" / "serve_app.py"


def test_server_module_ships_inside_the_package():
    assert _IMPL.is_file(), "serve_app.py must live in the package"
    assert _IMPL.stat().st_size > 100_000, "serve_app looks truncated"


def test_required_assets_resolve_through_package_root():
    """results.html + locale are REQUIRED at runtime, so they must go
    through _pkg_root() (always correct), never a repo-root guess."""
    src = _IMPL.read_text("utf-8")
    assert "def _pkg_root()" in src and "def _repo_root()" in src
    assert '_pkg_root() / "report" / "templates" / "results.html"' in src, (
        "results.html path no longer resolves through the package root")
    assert '_pkg_root() / "locale"' in src, (
        "locale dir no longer resolves through the package root")
    # No bare repo-root assumption may remain outside _repo_root() itself.
    offenders = [
        f"{i}: {ln.strip()[:70]}"
        for i, ln in enumerate(src.split("\n"), 1)
        if ("Path(__file__).resolve().parent.parent" in ln
            or "Path(__file__).parent.parent" in ln)
        and not ln.strip().startswith("#")
        and "cand = " not in ln          # the _repo_root() detector itself
    ]
    assert not offenders, (
        "repo-root path assumption left in the packaged server "
        "(breaks pip installs):\n  " + "\n  ".join(offenders))


def test_repo_root_detection_is_honest():
    """_repo_root() must return None when there's no checkout above —
    that's what makes the optional-asset fallbacks kick in."""
    src = _IMPL.read_text("utf-8")
    assert '(cand / "pyproject.toml").is_file()' in src, (
        "_repo_root() no longer verifies an actual checkout")


def test_cli_exposes_serve():
    """`pixcull serve --help` must advertise --port / --host.

    Terminal-independent on purpose: typer/rich renders help into a box
    sized to the terminal and colours it with ANSI escapes, so on CI's
    80-column runner the flag names were being wrapped mid-token and the
    naive substring check failed even though the options exist.  Pin a
    wide COLUMNS, ask rich for no colour, and strip any escapes that
    survive — the assertion is about the CLI's surface, not about how a
    given terminal happens to wrap it.
    """
    env = {**os.environ, "COLUMNS": "200", "NO_COLOR": "1",
           "TERM": "dumb", "TERMINAL_WIDTH": "200"}
    out = subprocess.run(
        [sys.executable, "-m", "pixcull", "serve", "--help"],
        capture_output=True, text=True, timeout=180, cwd=_REPO, env=env)
    assert out.returncode == 0, out.stderr[-500:]
    plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", out.stdout)
    for flag in ("--port", "--host"):
        assert flag in plain, (
            f"{flag} not advertised by `pixcull serve --help`; got:\n"
            f"{plain[:800]}")


def test_dev_shim_still_forwards():
    """scripts/serve_demo.py stays the dev entry point (docs, launch.json,
    muscle memory) — it must forward, not carry a second copy."""
    shim = (_REPO / "scripts" / "serve_demo.py").read_text("utf-8")
    assert "from pixcull.report.serve_app import main" in shim
    assert len(shim.split("\n")) < 60, "shim grew a second implementation"


# ── v2.32-P1 — /library page + API ────────────────────────────────────
def test_library_page_and_api_are_wired():
    src = _IMPL.read_text("utf-8")
    for route in ('"/library": "_serve_library_page"',
                  '"/api/v1/library/status"', '"/api/v1/library/search"'):
        assert route in src, f"library route missing: {route}"
    assert '_read_template("pages/library.html")' in src, (
        "library page no longer loads its extracted template")
    tmpl = _REPO / "pixcull" / "report" / "templates" / "pages" / "library.html"
    assert tmpl.is_file() and "/*__DESIGN_TOKENS_CSS__*/" in tmpl.read_text("utf-8")


def test_shared_design_tokens_carry_glass():
    """v2.29 put the glass tokens in results.css's token module only, so
    standalone pages (/library, /tether, /history, upload, admin) rendered
    chrome with no frost. One material means BOTH token sources define it —
    including the reduced-transparency fallback."""
    src = _IMPL.read_text("utf-8")
    for tok in ("--glass-filter:", "--glass-scrim-filter:", "--glass-edge:"):
        assert tok in src, f"shared design-tokens blob missing {tok}"
    assert "prefers-reduced-transparency" in src, (
        "standalone pages lost the reduced-transparency fallback")
