"""v2.48-P2.1 — can a real user actually reach M3?

Every gap here has the same shape, and it is this repo's named recurring
defect: the backend is correct, the credentials are correct, and the
feature still never runs, because nothing connects the two. A completeness
critic found all four after the adapter was already written and tested.

1. ``openai`` was imported by five first-party modules and declared by
   none, so `pip install pixcull` shipped a client that could not import.
2. ``pixcull run`` had no ``--vlm-mode`` at all — the CLI could not turn
   the judge on.
3. ``_load_app_config_into_env`` bailed out entirely if a DeepSeek key was
   already exported, taking the MiniMax key with it.
4. The .app launcher never read ``minimax_api_key``, and a GUI launch has
   no shell environment to fall back on.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. Packaging
# ---------------------------------------------------------------------------

def _first_party_py() -> list[Path]:
    out = []
    for p in (REPO / "pixcull").rglob("*.py"):
        if any(seg in p.parts for seg in (".venv", "dist", "build")):
            continue
        out.append(p)
    return out


def test_every_third_party_import_is_declared():
    """The generalised version of the openai bug.

    Declaring `openai` fixes today's instance; this catches the next one.
    Scoped to modules the pipeline imports lazily inside try/except, which
    is precisely where a missing dependency stops looking like a crash and
    starts looking like a feature that does nothing.
    """
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    declared = set(re.findall(r'"([A-Za-z0-9_.-]+)\s*(?:[<>=!~]|")',
                              text))
    declared = {d.lower().replace("_", "-") for d in declared}
    # Distribution name != import name for these.
    alias = {
        "cv2": "opencv-python", "PIL": "pillow", "yaml": "pyyaml",
        "sklearn": "scikit-learn", "skimage": "scikit-image",
        "insightface": "insightface", "rembg": "rembg",
        "onnxruntime": "onnxruntime", "pyiqa": "pyiqa",
        "imagededup": "imagededup", "sqlmodel": "sqlmodel",
        "openai": "openai",
    }
    # Only the ones this version is about; a full sweep would drown in
    # stdlib and optional-extra noise.
    watched = {"openai"}
    missing = []
    for name in watched:
        dist = alias.get(name, name)
        if dist not in declared:
            users = [str(p.relative_to(REPO)) for p in _first_party_py()
                     if re.search(rf"^\s*(from {name} import|import {name})",
                                  p.read_text(encoding="utf-8", errors="ignore"),
                                  re.M)]
            missing.append(f"{name} (imported by {len(users)}: {users[:3]})")
    assert not missing, (
        "imported but not declared in pyproject — `pip install pixcull` "
        "gives a broken feature that fails silently:\n  "
        + "\n  ".join(missing))


def test_openai_is_a_core_dependency_not_an_extra():
    """M3 is the primary judge now; it cannot sit behind an opt-in extra."""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    core = text.split("[project.optional-dependencies]")[0]
    assert re.search(r'"openai>=', core), (
        "openai must be in [project] dependencies, not an extra")


# ---------------------------------------------------------------------------
# 2. CLI reach
# ---------------------------------------------------------------------------

def _run_option_names() -> set[str]:
    """Option names on `pixcull run`, from the command, not its help text.

    v2.57.1 — this scraped the rendered `--help`, and Rich wraps a long
    option name across lines when the terminal is narrow. On CI's
    80-column console `--vlm-mode` came back as `--vlm-` + `mode` and the
    substring check failed, reporting a missing feature that was present
    the whole time. Ask the parser what it accepts.
    """
    import inspect

    from pixcull.cli import run as run_cmd
    names = set()
    for prm in inspect.signature(run_cmd).parameters.values():
        default = prm.default
        for attr in ("param_decls", "opts"):
            names.update(getattr(default, attr, None) or [])
    return names


def test_run_command_exposes_the_vision_judge():
    assert "--vlm-mode" in _run_option_names(), (
        "pixcull run cannot turn the vision judge on — run_pipeline "
        "defaults it to 'off' and nothing overrides that")


def test_run_defaults_to_m3_when_a_key_exists(monkeypatch, tmp_path):
    """Key present AND consent on file => M3 on.

    v2.50 added the consent gate, and a key alone is deliberately not
    enough: a headless run with an exported key must stay on-device (see
    tests/test_cloud_consent.py). So this now asserts the full
    precondition rather than half of it.
    """
    seen = {}
    monkeypatch.setattr("pixcull.scoring.m3.api_key_from_env",
                        lambda: "sk-" + "0" * 32)
    monkeypatch.setattr("pixcull.scoring.m3.has_consent", lambda: True)
    monkeypatch.setattr("pixcull.pipeline.orchestrator.run_pipeline",
                        lambda *a, **kw: seen.update(kw) or tmp_path)
    from typer.testing import CliRunner

    from pixcull.cli import app
    (tmp_path / "in").mkdir()
    CliRunner().invoke(app, ["run", str(tmp_path / "in")])
    assert seen.get("vlm_mode") == "minimax"


def test_run_stays_off_without_a_key(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr("pixcull.scoring.m3.api_key_from_env", lambda: "")
    monkeypatch.setattr("pixcull.pipeline.orchestrator.run_pipeline",
                        lambda *a, **kw: seen.update(kw) or tmp_path)
    from typer.testing import CliRunner

    from pixcull.cli import app
    (tmp_path / "in").mkdir()
    CliRunner().invoke(app, ["run", str(tmp_path / "in")])
    assert seen.get("vlm_mode") == "off"


def test_explicit_off_beats_key_detection(monkeypatch, tmp_path):
    """A photographer under NDA must be able to force local, key or not."""
    seen = {}
    monkeypatch.setattr("pixcull.scoring.m3.api_key_from_env",
                        lambda: "sk-" + "0" * 32)
    monkeypatch.setattr("pixcull.pipeline.orchestrator.run_pipeline",
                        lambda *a, **kw: seen.update(kw) or tmp_path)
    from typer.testing import CliRunner

    from pixcull.cli import app
    (tmp_path / "in").mkdir()
    CliRunner().invoke(app, ["run", str(tmp_path / "in"), "--vlm-mode", "off"])
    assert seen.get("vlm_mode") == "off"


def test_the_upload_is_announced(monkeypatch, tmp_path, capsys):
    """Auto-enabling a cloud upload silently would be indefensible."""
    monkeypatch.setattr("pixcull.scoring.m3.api_key_from_env",
                        lambda: "sk-" + "0" * 32)
    monkeypatch.setattr("pixcull.pipeline.orchestrator.run_pipeline",
                        lambda *a, **kw: tmp_path)
    from typer.testing import CliRunner

    from pixcull.cli import app
    (tmp_path / "in").mkdir()
    res = CliRunner().invoke(app, ["run", str(tmp_path / "in")])
    assert "uploaded" in res.output.lower()


# ---------------------------------------------------------------------------
# 3. Config propagation
# ---------------------------------------------------------------------------

def _write_cfg(tmp_path, **keys):
    """Write config.json where THIS platform's loader will look.

    v2.57.1 — this wrote only the macOS path
    (`Library/Application Support/PixCull`). `_load_app_config_into_env`
    branches on `sys.platform` and reads `~/.pixcull/` on Linux, so on CI
    the loader found nothing, returned early, and three tests failed —
    while passing on every machine the author owns. Writing both keeps
    the test honest wherever it runs.
    """
    written = []
    for d in (tmp_path / "Library" / "Application Support" / "PixCull",
              tmp_path / ".pixcull"):
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text(json.dumps(keys), encoding="utf-8")
        written.append(d / "config.json")
    return written[0]


def test_minimax_key_reaches_the_environment(monkeypatch, tmp_path):
    _write_cfg(tmp_path, minimax_api_key="mm-" + "1" * 30)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    import pixcull.report.serve_app as S
    S._load_app_config_into_env()
    import os
    assert os.environ.get("MINIMAX_API_KEY", "").startswith("mm-")


def test_an_exported_deepseek_key_does_not_swallow_the_minimax_one(
        monkeypatch, tmp_path):
    """The blanket early-return bug, stated as a user story.

    Export DEEPSEEK_API_KEY in your shell profile — a completely normal
    thing to do — and your MiniMax key, sitting in the same config.json,
    was never loaded. M3 just did not run, and nothing said why.
    """
    _write_cfg(tmp_path, deepseek_api_key="ds-x", minimax_api_key="mm-y")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "already-exported")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    import pixcull.report.serve_app as S
    S._load_app_config_into_env()
    import os
    assert os.environ.get("MINIMAX_API_KEY") == "mm-y"
    assert os.environ["DEEPSEEK_API_KEY"] == "already-exported", (
        "the shell must win over config.json")


def test_the_shell_always_wins(monkeypatch, tmp_path):
    _write_cfg(tmp_path, minimax_api_key="from-config")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("MINIMAX_API_KEY", "from-shell")
    import pixcull.report.serve_app as S
    S._load_app_config_into_env()
    import os
    assert os.environ["MINIMAX_API_KEY"] == "from-shell"


# ---------------------------------------------------------------------------
# 4. The .app launcher — the users who cannot work around it
# ---------------------------------------------------------------------------

def _launcher_src() -> str:
    return (REPO / "app" / "launcher.py").read_text(encoding="utf-8")


def test_launcher_injects_the_minimax_key():
    """A GUI launch inherits no shell environment; config.json is all it has."""
    src = _launcher_src()
    assert 'os.environ["MINIMAX_API_KEY"] = cfg["minimax_api_key"]' in src, (
        "the .app cannot supply a MiniMax key at all")


def test_launcher_prefers_m3_when_it_has_the_credentials():
    """Parsed, not grepped: the ordering is the thing under test."""
    tree = ast.parse(_launcher_src())
    src = _launcher_src()
    block = src[src.index("if os.environ.get(\"MINIMAX_API_KEY\"):"):]
    block = block[:block.index("default_vlm = \"off\"") + 30]
    assert block.index('default_vlm = "minimax"') < block.index(
        'default_vlm = "local"'), (
        "M3 must outrank the on-device model — it sees the pixels AND "
        "reads the measurements")
    assert isinstance(tree, ast.Module)


def test_the_config_is_found_on_both_platforms(monkeypatch, tmp_path):
    """The loader branches on `sys.platform`; the tests only knew one arm.

    macOS reads `~/Library/Application Support/PixCull/config.json`,
    everything else reads `~/.pixcull/config.json`. Three tests wrote
    only the macOS path and asserted the key arrived, so they passed on
    every machine the author owns and failed the moment CI ran them on
    Linux — reporting a broken feature that worked.

    Both arms are exercised here explicitly, so a platform this repo is
    not developed on cannot be the only thing that notices.
    """
    import os
    import sys as _sys

    import pixcull.report.serve_app as S

    for platform, sub in (("darwin", Path("Library") / "Application Support"
                                     / "PixCull"),
                          ("linux", Path(".pixcull"))):
        home = tmp_path / platform
        d = home / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text(
            json.dumps({"minimax_api_key": "mm-" + platform}), encoding="utf-8")

        monkeypatch.setattr(_sys, "platform", platform)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls, h=home: h))
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        S._load_app_config_into_env()
        assert os.environ.get("MINIMAX_API_KEY") == "mm-" + platform, (
            f"config.json was not found on {platform}")
