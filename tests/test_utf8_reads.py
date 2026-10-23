"""Text files must be read as UTF-8, not with the locale's encoding.

On a Windows machine with a non-UTF-8 locale (cp950 on Traditional Chinese)
`open(path)` decodes with that codec, so the bundled scene templates and any
scores.csv with a non-ASCII filename failed with UnicodeDecodeError (#5).
The subprocess turns EncodingWarning into an error, so a read that relies on
the locale fails on every platform, not only on such a machine.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run_strict(code: str, tmp_path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "warn_default_encoding", "-W", "error::EncodingWarning",
         "-c", textwrap.dedent(code)],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
        # The child runs from tmp_path, so it must be told where this
        # checkout is: otherwise it imports whatever `pixcull` the
        # interpreter has installed, which need not be the code under test.
        env={**os.environ,
             "PYTHONPATH": str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")},
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


# v3.94.4 — the same defect one step removed. ffprobe and exiftool write
# UTF-8 whatever the locale, and `subprocess.run(text=True)` decoded what
# they wrote with the locale, so on a cp950 machine a clip or a photograph
# with Chinese in its name or metadata failed the same way. The stand-ins
# below write UTF-8 bytes as the real tools do.

def _fake_tool(tmp_path, name: str, doc) -> str:
    import json
    path = tmp_path / name
    path.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"sys.stdout.buffer.write({json.dumps(doc, ensure_ascii=False)!r}"
        ".encode('utf-8'))\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return str(path)


def test_ffprobe_output_is_decoded_as_utf8(tmp_path):
    clip = tmp_path / "婚禮_台北_001.mp4"
    clip.write_bytes(b"\0")
    _fake_tool(tmp_path, "ffprobe", {
        "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920,
                     "height": 1080, "avg_frame_rate": "30/1"}],
        "format": {"filename": str(clip), "duration": "10.0",
                   "tags": {"title": "新娘進場"}},
    })
    proc = _run_strict(f"""
        from pathlib import Path
        from pixcull.io.video import probe_video
        meta = probe_video(Path({str(clip)!r}), ffprobe={str(tmp_path / "ffprobe")!r})
        assert (meta.width, meta.height) == (1920, 1080), meta
    """, tmp_path)
    assert proc.returncode == 0, proc.stderr


def test_embedded_keywords_are_decoded_as_utf8(tmp_path):
    """read_embedded() answers {} when the read fails, and the writer takes
    {} as "nothing to preserve", so this one failed silently: the
    photographer's own rating and label were overwritten inside the file."""
    (tmp_path / "bin").mkdir()
    _fake_tool(tmp_path / "bin", "exiftool", [{
        "SourceFile": "婚禮_001.jpg", "Rating": 4, "Label": "精選",
        "Keywords": ["婚禮", "新娘"]}])
    proc = _run_strict(f"""
        import os
        os.environ["PATH"] = {str(tmp_path / "bin")!r} + os.pathsep + os.environ["PATH"]
        from pixcull.io.iptc_embed import read_embedded
        got = read_embedded("婚禮_001.jpg")
        assert got.get("keywords") == ["婚禮", "新娘"], got
        assert got.get("color_label") == "精選", got
    """, tmp_path)
    assert proc.returncode == 0, proc.stderr
