"""Open the actual file, not the 1600px render the page serves.

PixCull never copies originals; the only pointer to a frame is the
``path`` column in ``scores.csv``. These tests hold the lookup to that
column, refuse anything that is not in the run, and check the three
platform command lines.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

from pixcull.report.reveal import (
    reveal_command,
    reveal_in_file_manager,
    source_path_for,
)


def _run_dir(tmp_path: Path, rows: list[dict]) -> Path:
    out = tmp_path / "run" / "output"
    out.mkdir(parents=True)
    fields = ["path", "filename", "decision"]
    with (out / "scores.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return out


def test_finds_the_source_from_the_path_column(tmp_path):
    shot = tmp_path / "DCIM" / "A.JPG"
    shot.parent.mkdir()
    shot.write_bytes(b"x")
    out = _run_dir(tmp_path, [{"path": str(shot), "filename": "A.JPG",
                               "decision": "keep"}])

    assert source_path_for(out, "A.JPG") == shot


def test_relative_paths_resolve_against_the_base(tmp_path):
    base = tmp_path / "repo"
    shot = base / "samples" / "input" / "B.JPG"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"x")
    out = _run_dir(tmp_path, [{"path": "samples/input/B.JPG",
                               "filename": "B.JPG", "decision": "cull"}])

    assert source_path_for(out, "B.JPG", base=base) == shot


def test_unknown_filename_is_not_resolved(tmp_path):
    out = _run_dir(tmp_path, [{"path": "/nope/A.JPG", "filename": "A.JPG",
                               "decision": "keep"}])
    assert source_path_for(out, "B.JPG") is None


def test_traversal_in_the_query_never_reaches_the_filesystem(tmp_path):
    out = _run_dir(tmp_path, [{"path": "/nope/A.JPG", "filename": "A.JPG",
                               "decision": "keep"}])
    assert source_path_for(out, "../../etc/passwd") is None


def test_missing_run_returns_none(tmp_path):
    assert source_path_for(tmp_path / "gone", "A.JPG") is None


@pytest.mark.parametrize("platform,expected", [
    ("darwin", ["open", "-R", "/shots/A.JPG"]),
    ("linux", ["xdg-open", "/shots"]),
    ("win32", ["explorer", "/select,/shots/A.JPG"]),
])
def test_command_per_platform(platform, expected, monkeypatch):
    monkeypatch.setattr(sys, "platform", platform)
    assert reveal_command(Path("/shots/A.JPG")) == expected


def test_reveal_runs_the_command(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: seen.setdefault("cmd", cmd))
    reveal_in_file_manager(tmp_path / "A.JPG")
    assert seen["cmd"][:2] == ["open", "-R"]


def test_cli_reveals_a_frame(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from pixcull.cli import app
    from pixcull.report import reveal as reveal_mod

    shot = tmp_path / "A.JPG"
    shot.write_bytes(b"x")
    out = _run_dir(tmp_path, [{"path": str(shot), "filename": "A.JPG",
                               "decision": "keep"}])
    calls = []
    monkeypatch.setattr(reveal_mod, "reveal_in_file_manager",
                        lambda p: calls.append(p))
    result = CliRunner().invoke(app, ["reveal", str(out), "A.JPG"])
    assert result.exit_code == 0, result.output
    assert calls == [shot]


def test_cli_refuses_a_frame_from_another_run(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from pixcull.cli import app
    from pixcull.report import reveal as reveal_mod

    out = _run_dir(tmp_path, [{"path": "/nope/A.JPG", "filename": "A.JPG",
                               "decision": "keep"}])
    monkeypatch.setattr(reveal_mod, "reveal_in_file_manager",
                        lambda p: pytest.fail("should not reveal"))
    result = CliRunner().invoke(app, ["reveal", str(out), "B.JPG"])
    assert result.exit_code == 1
