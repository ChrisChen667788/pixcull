"""Text files must be read as UTF-8, not with the locale's encoding.

On a Windows machine with a non-UTF-8 locale (cp950 on Traditional Chinese)
`open(path)` decodes with that codec, so the bundled scene templates and any
scores.csv with a non-ASCII filename failed with UnicodeDecodeError (#5).
The subprocess turns EncodingWarning into an error, so a read that relies on
the locale fails on every platform, not only on such a machine.
"""

import subprocess
import sys
import textwrap


def _run_strict(code: str, tmp_path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "warn_default_encoding", "-W", "error::EncodingWarning",
         "-c", textwrap.dedent(code)],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
    )


def test_default_config_loads_without_the_locale_encoding(tmp_path):
    proc = _run_strict("""
        from pixcull.config import PixCullConfig
        assert PixCullConfig.load().scenes
    """, tmp_path)
    assert proc.returncode == 0, proc.stderr


def test_reel_reads_scores_csv_as_utf8(tmp_path):
    (tmp_path / "scores.csv").write_text(
        "filename,scene,face_count\n婚禮_001.jpg,portrait,2\n",
        encoding="utf-8", newline="",
    )
    proc = _run_strict("""
        from pathlib import Path
        from pixcull.scoring.reel import _load_scene_face
        out = _load_scene_face(Path("."))
        assert "婚禮_001" in out, out
    """, tmp_path)
    assert proc.returncode == 0, proc.stderr
