"""v2.42 — reel candidates must not span a shot cut.

DESIGN-AUDIT-2031Q1 found this by checking what the video stack actually
does rather than what its names suggest: `SceneDetector` is CLIP *scene
classification* (landscape / portrait / event), not shot-change
detection, and nothing else looked for cuts. So `sliding_windows` swept
fixed-length windows across the whole clip and a candidate could
straddle a hard cut — assemble that into a reel and it jumps mid-clip.

The load-bearing property here is the NEGATIVE one: with no cuts (i.e.
the optional [shots] extra absent, which is the default install) the
sweep must be *identical* to before.
"""

from pathlib import Path

import numpy as np
import pytest

from pixcull.scoring import shot_boundaries as SB
from pixcull.scoring.reel import sliding_windows


def _frames(n=41, step=0.5):
    return [{"timestamp_s": i * step, "frame_id": f"f{i}",
             "score_final": 0.6, "score_temporal": 0.5,
             "temporal_stability": 0.9} for i in range(n)]


# ── segments / merging (pure, no video needed) ────────────────────────

def test_no_cuts_is_one_segment():
    assert SB.segments_from_cuts(0.0, 20.0, []) == [(0.0, 20.0)]


def test_cuts_split_the_timeline():
    assert SB.segments_from_cuts(0.0, 20.0, [7.0, 13.0]) == [
        (0.0, 7.0), (7.0, 13.0), (13.0, 20.0)]


def test_cuts_outside_the_span_are_ignored():
    assert SB.segments_from_cuts(5.0, 10.0, [1.0, 7.0, 99.0]) == [
        (5.0, 7.0), (7.0, 10.0)]


def test_segments_are_contiguous_and_cover_the_span():
    segs = SB.segments_from_cuts(0.0, 12.0, [3.0, 3.4, 8.0])
    assert segs[0][0] == 0.0 and segs[-1][1] == 12.0
    for a, b in zip(segs, segs[1:]):
        assert a[1] == b[0], "a gap or overlap between shots"


@pytest.mark.parametrize("cuts,expect", [
    ([1.0, 1.2, 5.0], [1.0, 5.0]),          # 1.2 would make a 0.2s shot
    ([1.0, 1.9, 5.0], [1.0, 1.9, 5.0]),     # 0.9s apart is a real shot
    ([], []),
])
def test_close_cuts_are_merged(cuts, expect):
    """A flash or a person crossing frame shouldn't carve out a sliver
    too short to use as a clip."""
    assert SB.merge_close_cuts(cuts, min_shot_s=0.6) == expect


def test_merge_sorts_unordered_input():
    assert SB.merge_close_cuts([9.0, 1.0, 5.0]) == [1.0, 5.0, 9.0]


# ── the negative property: no cuts ⇒ nothing changes ──────────────────

@pytest.mark.parametrize("cuts", [None, []])
def test_without_cuts_the_sweep_is_unchanged(cuts):
    frames = _frames()
    assert sliding_windows(frames, cut_points=cuts) == sliding_windows(frames)


def test_windows_never_straddle_a_cut():
    frames = _frames()
    cuts = [7.0, 13.0]
    got = sliding_windows(frames, cut_points=cuts)
    straddling = [w for w in got
                  if any(w["start_s"] < c < w["end_s"] - 1e-9 for c in cuts)]
    assert not straddling, f"{len(straddling)} candidate(s) span a cut"


def test_the_bug_is_real_without_cut_points():
    """Guards the premise: if the plain sweep stopped producing
    straddling windows on its own, this whole feature would be solving
    nothing and should be revisited."""
    frames = _frames()
    cuts = [7.0, 13.0]
    plain = sliding_windows(frames)
    straddling = [w for w in plain
                  if any(w["start_s"] < c < w["end_s"] - 1e-9 for c in cuts)]
    assert straddling, "the plain sweep no longer straddles — premise gone"


def test_each_shot_still_yields_candidates():
    frames = _frames()
    got = sliding_windows(frames, cut_points=[7.0, 13.0])
    for lo, hi in ((0.0, 7.0), (7.0, 13.0), (13.0, 20.0)):
        assert any(lo - 1e-9 <= w["start_s"] and w["end_s"] <= hi + 1e-9
                   for w in got), f"shot {lo}-{hi} produced nothing"


def test_empty_frames_stay_empty():
    assert sliding_windows([], cut_points=[1.0]) == []


# ── graceful degradation ──────────────────────────────────────────────

def test_missing_extra_reports_no_cuts_rather_than_raising(monkeypatch,
                                                           tmp_path):
    """`pip install pixcull` has no [shots]; that must mean 'no cut
    info', never a crash — same contract as ONNX→DSP and VLM→template."""
    monkeypatch.setattr(SB, "available", lambda: False)
    assert SB.detect_cuts(tmp_path / "nope.mp4") == []


def test_unreadable_video_reports_no_cuts(tmp_path):
    bad = tmp_path / "broken.mp4"
    bad.write_bytes(b"not a video")
    assert SB.detect_cuts(bad) == []


# ── the real thing ────────────────────────────────────────────────────

@pytest.mark.slow
def test_detects_real_cuts_in_a_real_video(tmp_path):
    """Three visually distinct 3-second shots; cuts at 3.0s and 6.0s."""
    if not SB.available():
        pytest.skip("shot detection extra not installed (pixcull[shots])")
    import shutil
    import subprocess
    from PIL import Image

    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    if not Path(ffmpeg).exists() and not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg unavailable")

    frames_dir = tmp_path / "f"
    frames_dir.mkdir()
    i = 0
    for r, g, b in ((200, 40, 40), (40, 180, 60), (30, 60, 210)):
        for k in range(30):
            a = np.zeros((240, 320, 3), np.uint8)
            a[:, :] = (r, g, b)
            a[100:140, 20 + k * 8:60 + k * 8] = (255, 255, 255)
            Image.fromarray(a).save(frames_dir / f"{i:04d}.png")
            i += 1
    video = tmp_path / "three_shots.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-framerate", "10",
                    "-i", str(frames_dir / "%04d.png"), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(video)], check=True,
                   timeout=300)

    cuts = SB.detect_cuts(video)
    assert len(cuts) == 2, f"expected 2 cuts, got {cuts}"
    assert abs(cuts[0] - 3.0) < 0.35, cuts
    assert abs(cuts[1] - 6.0) < 0.35, cuts
