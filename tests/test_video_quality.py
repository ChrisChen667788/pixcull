"""v2.0-P1-4 — tests for pixcull.scoring.video_quality (shake / blur)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from pixcull.scoring import video_quality as Q


# --------------------------------------------------------------------------
# laplacian_variance
# --------------------------------------------------------------------------

def test_laplacian_flat_is_zero():
    assert Q.laplacian_variance(np.full((20, 20), 128.0)) == 0.0


def test_laplacian_texture_is_large():
    checker = (np.indices((20, 20)).sum(0) % 2) * 255.0
    assert Q.laplacian_variance(checker) > 1000


# --------------------------------------------------------------------------
# shake_series
# --------------------------------------------------------------------------

def test_shake_zero_for_smooth_pan():
    # Lots of motion but perfectly coherent ⇒ not shake.
    s = Q.shake_series([5, 5, 5, 5], [1.0, 1.0, 1.0, 1.0])
    assert np.allclose(s, 0.0)


def test_shake_high_for_jitter():
    s = Q.shake_series([5, 5, 5, 5], [0.1, 0.1, 0.1, 0.1])
    assert float(s.mean()) > 0.7


def test_shake_zero_for_static():
    # No motion ⇒ no shake regardless of continuity.
    s = Q.shake_series([0, 0, 0], [1.0, 1.0, 1.0])
    assert np.allclose(s, 0.0)


# --------------------------------------------------------------------------
# blur_series
# --------------------------------------------------------------------------

def test_blur_flags_soft_frame():
    b = Q.blur_series([100, 100, 30, 100, 100])
    assert b[2] > 0.8
    assert b[0] == 0.0


def test_blur_uniformly_sharp_is_near_zero():
    # Frames within a few % of the median sharpness ⇒ negligible blur.
    assert float(Q.blur_series([100, 102, 98, 101]).max()) < 0.1


def test_blur_empty():
    assert Q.blur_series([]).size == 0


# --------------------------------------------------------------------------
# detect_segments
# --------------------------------------------------------------------------

def test_detect_segments_basic():
    ts = [0, 1, 2, 3, 4, 5]
    shake = [0.1, 0.1, 0.8, 0.9, 0.85, 0.1]
    segs = Q.detect_segments(shake, ts, kind="shake", thresh=0.45, min_dur_s=0.4)
    assert len(segs) == 1
    assert segs[0].start_s == 2.0 and segs[0].end_s == 4.0
    assert segs[0].kind == "shake"
    assert "Gyroflow" in segs[0].suggestion


def test_detect_segments_min_duration_filters():
    ts = [0.0, 0.1, 0.2, 0.3]
    # One bad frame at 0.1 ⇒ too short to flag at min_dur 0.4.
    spike = [0.0, 0.9, 0.0, 0.0]
    assert Q.detect_segments(spike, ts, kind="blur", thresh=0.45,
                             min_dur_s=0.4) == []


def test_detect_segments_merges_short_gap():
    ts = [0, 1, 2, 3, 4, 5, 6]
    # Two bad runs separated by one good frame (a 2.0s time gap at 1 fps);
    # merge_gap_s above that ⇒ merged into one segment.
    score = [0.9, 0.9, 0.1, 0.9, 0.9, 0.1, 0.1]
    segs = Q.detect_segments(score, ts, kind="shake", thresh=0.45,
                             min_dur_s=0.4, merge_gap_s=2.5)
    assert len(segs) == 1
    assert segs[0].start_s == 0.0 and segs[0].end_s == 4.0


def test_detect_segments_empty():
    assert Q.detect_segments([], [], kind="shake", thresh=0.4) == []
    assert Q.detect_segments([0.1, 0.2], [0, 1], kind="shake",
                             thresh=0.45) == []


# --------------------------------------------------------------------------
# analyze_quality
# --------------------------------------------------------------------------

def test_analyze_quality_combines_signals():
    ts = [0, 1, 2, 3, 4, 5]
    r = Q.analyze_quality(
        ts,
        sharpness=[100, 100, 20, 20, 100, 100],
        motion_mag=[1, 1, 8, 9, 8, 1],
        motion_continuity=[1, 1, 0.1, 0.1, 0.1, 1],
    )
    kinds = {s.kind for s in r.segments}
    assert "shake" in kinds and "blur" in kinds
    d = r.to_dict()
    assert d["frame_count"] == 6
    assert d["summary"]["shake_segments"] >= 1
    assert d["summary"]["blur_segments"] >= 1
    assert len(d["shake_per_frame"]) == 6


def test_analyze_quality_clean_clip_no_segments():
    ts = list(range(6))
    r = Q.analyze_quality(
        ts, sharpness=[100] * 6,
        motion_mag=[2] * 6, motion_continuity=[1.0] * 6)
    assert r.segments == []


def test_analyze_quality_missing_signals():
    # No motion/sharpness ⇒ no crash, no segments.
    r = Q.analyze_quality([0, 1, 2])
    assert r.segments == []
    assert r.frame_count == 3


def test_analyze_quality_imu_shake_blend():
    # v2.1-P1-3 — optical motion is calm, but the IMU reports rotation
    # ⇒ the IMU shake forces a flagged shake segment.
    ts = [0, 1, 2, 3, 4]
    r = Q.analyze_quality(
        ts, motion_mag=[1] * 5, motion_continuity=[1.0] * 5,
        imu_shake=[0.0, 0.9, 0.9, 0.9, 0.0])
    assert any(s.kind == "shake" for s in r.segments)
    assert r.shake[1] >= 0.9


# --------------------------------------------------------------------------
# run_quality_analysis (real frames if present, else synthetic)
# --------------------------------------------------------------------------

def _tiny_jpeg(path, fill):
    from PIL import Image
    Image.new("RGB", (96, 72), fill).save(path, "JPEG")


def test_run_quality_analysis_synthetic(tmp_path):
    # Build a minimal video run: frames + manifest (no scores.csv needed).
    fdir = tmp_path / "video_frames" / "clip1"
    fdir.mkdir(parents=True)
    frames = []
    rng = np.random.default_rng(0)
    for i in range(6):
        fn = f"frame_{i+1:06d}.jpg"
        # Frame 3 is a flat (blurry) grey; others are textured (sharp).
        if i == 3:
            _tiny_jpeg(fdir / fn, (128, 128, 128))
        else:
            from PIL import Image
            arr = (rng.random((72, 96, 3)) * 255).astype("uint8")
            Image.fromarray(arr).save(fdir / fn, "JPEG")
        frames.append({"frame_id": f"frame_{i+1:06d}",
                       "timestamp_s": float(i), "filename": fn})
    (fdir / "manifest.json").write_text(json.dumps({
        "video_id": "clip1", "frame_count": 6, "frames": frames}))

    r = Q.run_quality_analysis(tmp_path)
    assert (tmp_path / "quality_flags.json").exists()
    data = json.loads((tmp_path / "quality_flags.json").read_text())
    assert data["frame_count"] == 6
    assert "shake_per_frame" in data and "blur_per_frame" in data
    # The flat grey frame is far softer than the textured neighbours.
    assert data["blur_per_frame"][3] > 0.5
