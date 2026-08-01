"""v2.44.2 — rendering what the transcript editor kept.

`assemble_from_edit` is thin on purpose: it replays the saved log through
the same EditSession the CLI and the review page use, then hands the
surviving spans to the existing `assemble_reel`.  These tests pin the
decisions that are NOT thin — the crossfade default, and refusing to
produce an empty file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixcull.io.reel_assembly import (
    EDIT_CROSSFADE_S, assemble_from_edit, build_montage_filter,
)
from pixcull.scoring.edit_model import EditSession, Span
from pixcull.scoring.transcribe import Segment, Transcript, write_transcript


def _worded() -> Transcript:
    s1 = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    s2 = [(2.0, 2.2), (2.2, 2.4), (2.4, 2.6), (2.6, 2.8), (2.8, 3.0)]
    return Transcript(segments=[Segment(0.0, 1.0, "今天拍婚礼", char_spans=s1),
                                Segment(2.0, 3.0, "灯光准备好", char_spans=s2)],
                      engine="paraformer", language="zh")


@pytest.fixture(scope="module")
def tiny_video(tmp_path_factory) -> Path:
    """A real 4s clip.

    `assemble_reel` probes the source even for --edl-only, because the
    EDL needs the real fps and clip name. An empty placeholder file
    therefore does not work, and faking probe_video would test the mock
    rather than the path a user takes.
    """
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    dest = tmp_path_factory.mktemp("src") / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=s=160x120:r=25:d=4",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)],
        check=True)
    return dest


def _run(tmp_path: Path, ops: list | None = None) -> Path:
    d = tmp_path / "r"
    d.mkdir(exist_ok=True)
    write_transcript(_worded(), d)
    if ops is not None:
        (d / "edit.json").write_text(json.dumps(
            {"schema": "pixcull.edit/v1", "ops": ops}), encoding="utf-8")
    return d


# ── the crossfade decision ────────────────────────────────────────────

def test_edit_default_is_a_hard_cut():
    """A dissolve mid-sentence eats the words the photographer kept.

    Reels join separate highlights, so a fade there is deliberate. This
    is the opposite case and must not inherit that default.
    """
    assert EDIT_CROSSFADE_S == 0.0


def test_zero_crossfade_produces_concat_not_xfade():
    from pixcull.io.reel_assembly import Clip

    clips = [Clip(0.0, 1.0), Clip(2.0, 3.0)]
    filt, _v, _a = build_montage_filter(clips, crossfade_s=0.0,
                                        has_audio=True)
    assert "xfade" not in filt, "a hard cut must not emit a dissolve"
    assert "concat" in filt


# ── refusing rather than producing junk ───────────────────────────────

def test_render_refuses_when_the_edit_keeps_nothing(tmp_path):
    """ffmpeg would emit a zero-length file instead of complaining."""
    d = _run(tmp_path, ops=[{"kind": "delete",
                             "spans": [[0.0, 1.0], [2.0, 3.0]]}])
    with pytest.raises(ValueError, match="keeps nothing"):
        assemble_from_edit(d, edl_only=True)


def test_render_without_a_transcript_is_an_error(tmp_path):
    d = tmp_path / "bare"
    d.mkdir()
    with pytest.raises(FileNotFoundError, match="no transcript"):
        assemble_from_edit(d, edl_only=True)


def test_missing_source_video_names_the_path_it_wanted(tmp_path):
    d = _run(tmp_path, ops=[])
    with pytest.raises(FileNotFoundError, match="source video not found"):
        assemble_from_edit(d, edl_only=True)


# ── the spans that actually get cut ───────────────────────────────────

def test_edl_only_render_uses_the_kept_spans(tmp_path, tiny_video):
    ops = [{"kind": "delete", "spans": [[0.0, 1.0]]}]
    d = _run(tmp_path, ops=ops)
    res = assemble_from_edit(d, edl_only=True, source_video=tiny_video)
    assert [(c.start_s, c.end_s) for c in res.clips] == [(2.0, 3.0)]
    assert res.mp4_path is None
    assert res.edl_path.is_file()


def test_render_matches_the_session_it_replays(tmp_path, tiny_video):
    """The renderer and the editor must agree on what survives."""
    ops = [{"kind": "delete", "spans": [[0.0, 0.4]]}]
    d = _run(tmp_path, ops=ops)
    res = assemble_from_edit(d, edl_only=True, source_video=tiny_video)

    sess = EditSession.from_dict(
        json.loads((d / "edit.json").read_text("utf-8")), _worded())
    assert [(c.start_s, c.end_s) for c in res.clips] == \
           [(s.start, s.end) for s in sess.kept_spans()]


def test_no_edit_file_renders_the_whole_transcript(tmp_path, tiny_video):
    """An untouched run is a valid, if pointless, render."""
    d = _run(tmp_path, ops=None)
    res = assemble_from_edit(d, edl_only=True, source_video=tiny_video)
    assert [(c.start_s, c.end_s) for c in res.clips] == [(0.0, 1.0),
                                                          (2.0, 3.0)]
