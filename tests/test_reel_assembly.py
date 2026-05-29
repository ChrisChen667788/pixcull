"""v2.0-P1-1 — tests for pixcull.io.reel_assembly.

Pure functions (timecode / EDL / selection / filter graph) run without
ffmpeg; the assemble path uses a tiny lavfi clip and skips when ffmpeg
is absent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pixcull.io import reel_assembly as A

_HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


# --------------------------------------------------------------------------
# seconds_to_timecode
# --------------------------------------------------------------------------

def test_timecode_zero():
    assert A.seconds_to_timecode(0, 30) == "00:00:00:00"


def test_timecode_frames():
    assert A.seconds_to_timecode(12.5, 30) == "00:00:12:15"
    assert A.seconds_to_timecode(3661.5, 25) == "01:01:01:13"


def test_timecode_fps_fallback_and_clamp():
    assert A.seconds_to_timecode(-5, 0) == "00:00:00:00"   # fps 0 → 25 default
    assert A.seconds_to_timecode(1.0, 25) == "00:00:01:00"


# --------------------------------------------------------------------------
# build_edl
# --------------------------------------------------------------------------

def test_build_edl_structure():
    clips = [A.Clip(4.5, 7.5, 1), A.Clip(11.0, 13.0, 2)]
    edl = A.build_edl(clips, "demo.mp4", 30.0)
    assert edl.startswith("TITLE: PixCull Reel")
    assert "FCM: NON-DROP FRAME" in edl
    assert edl.count("FROM CLIP NAME: demo.mp4") == 2
    assert "001  AX" in edl and "002  AX" in edl
    # record TC accumulates: clip1 is 3s → clip2 rec_in is 00:00:03:00.
    assert "00:00:03:00" in edl


def test_build_edl_empty():
    edl = A.build_edl([], "x.mp4", 30.0)
    assert "TITLE" in edl


# --------------------------------------------------------------------------
# select_for_assembly
# --------------------------------------------------------------------------

_CANDS = [
    {"rank": 1, "start_s": 10.0, "end_s": 12.0, "score": 0.9},
    {"rank": 2, "start_s": 2.0, "end_s": 5.0, "score": 0.8},
    {"rank": 3, "start_s": 20.0, "end_s": 21.0, "score": 0.7},
]


def test_select_explicit_ranks_time_ordered():
    clips = A.select_for_assembly(_CANDS, ranks=[1, 2])
    assert [c.rank for c in clips] == [2, 1]   # sorted by start_s
    assert clips[0].start_s == 2.0


def test_select_auto_by_target():
    clips = A.select_for_assembly(_CANDS, target_s=4.0)
    # Highest score first (rank1, 2s) then rank2 (3s) crosses 4s → 2 clips.
    assert len(clips) == 2
    # Returned in time order.
    assert clips == sorted(clips, key=lambda c: c.start_s)


def test_select_max_clips():
    clips = A.select_for_assembly(_CANDS, target_s=999, max_clips=1)
    assert len(clips) == 1


def test_select_skips_zero_duration():
    bad = [{"rank": 1, "start_s": 5.0, "end_s": 5.0, "score": 1.0}]
    assert A.select_for_assembly(bad, target_s=10) == []


# --------------------------------------------------------------------------
# build_montage_filter
# --------------------------------------------------------------------------

def test_filter_crossfade_chain():
    clips = [A.Clip(0, 3), A.Clip(5, 8), A.Clip(10, 13)]
    filt, vout, aout = A.build_montage_filter(
        clips, crossfade_s=0.5, has_audio=True)
    assert "xfade=transition=fade" in filt
    assert "acrossfade" in filt
    assert vout == "vout" and aout == "aout"
    assert "trim=start=0.000:end=3.000" in filt


def test_filter_hard_cut_when_crossfade_zero():
    clips = [A.Clip(0, 2), A.Clip(4, 6)]
    filt, vout, aout = A.build_montage_filter(
        clips, crossfade_s=0.0, has_audio=False)
    assert "concat=n=2:v=1:a=0" in filt
    assert "xfade" not in filt
    assert aout is None


def test_filter_short_clips_fall_back_to_concat():
    # Clips shorter than the crossfade can't xfade ⇒ hard cut.
    clips = [A.Clip(0, 0.2), A.Clip(1, 1.2)]
    filt, vout, aout = A.build_montage_filter(
        clips, crossfade_s=0.5, has_audio=False)
    assert "concat=" in filt and "xfade" not in filt


def test_filter_single_clip():
    filt, vout, aout = A.build_montage_filter(
        [A.Clip(0, 3)], crossfade_s=0.5, has_audio=False)
    assert "concat=n=1" in filt
    assert vout == "vout"


def test_filter_empty_raises():
    with pytest.raises(ValueError):
        A.build_montage_filter([], crossfade_s=0.5, has_audio=False)


# --------------------------------------------------------------------------
# assemble_reel / assemble_from_run (ffmpeg)
# --------------------------------------------------------------------------

pytestmark_ff = pytest.mark.skipif(
    not _HAS_FFMPEG, reason="ffmpeg not installed")


def _make_clip(dest: Path, duration=12):
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=duration={duration}:size=320x240:rate=30",
        "-f", "lavfi", "-i", f"sine=frequency=600:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(dest)], check=True, capture_output=True, timeout=120)
    return dest


@pytestmark_ff
def test_assemble_reel_renders(tmp_path):
    src = _make_clip(tmp_path / "src.mp4")
    clips = [A.Clip(1.0, 4.0), A.Clip(6.0, 9.0)]
    res = A.assemble_reel(src, clips, tmp_path, reel_id="r1", crossfade_s=0.5)
    assert res.mp4_path and res.mp4_path.exists()
    assert res.edl_path.exists()
    # Two 3s clips with a 0.5s crossfade ≈ 5.5s.
    assert 4.5 <= res.duration_s <= 6.5


@pytestmark_ff
def test_assemble_reel_edl_only_no_mp4(tmp_path):
    src = _make_clip(tmp_path / "src.mp4", duration=6)
    res = A.assemble_reel(src, [A.Clip(0, 3)], tmp_path,
                          reel_id="r2", edl_only=True)
    assert res.mp4_path is None
    assert res.edl_path.exists()


@pytestmark_ff
def test_assemble_from_run(tmp_path):
    src = _make_clip(tmp_path / "src.mp4")
    fdir = tmp_path / "video_frames" / "clipX"
    fdir.mkdir(parents=True)
    (fdir / "manifest.json").write_text(json.dumps({
        "video_id": "clipX", "fps": 30.0, "source_path": str(src),
        "frames": []}))
    (tmp_path / "reel_candidates.json").write_text(json.dumps([
        {"rank": 1, "start_s": 1.0, "end_s": 4.0, "score": 0.9},
        {"rank": 2, "start_s": 6.0, "end_s": 9.0, "score": 0.7},
    ]))
    res = A.assemble_from_run(tmp_path, target_s=10, crossfade_s=0.5)
    assert res.mp4_path.exists() and res.edl_path.exists()
    assert len(res.clips) == 2


def test_assemble_from_run_missing_reel(tmp_path):
    with pytest.raises(FileNotFoundError, match="reel"):
        A.assemble_from_run(tmp_path)
