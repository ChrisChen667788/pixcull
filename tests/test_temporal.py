"""v2.0-P0-2 — tests for pixcull.scoring.temporal.

The numeric core is exercised with synthetic time-series (no images);
the image-motion + run-IO layers use tiny PIL-generated JPEGs and a
hand-built fake run directory, so the whole file runs without ffmpeg.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from pixcull.scoring import temporal as T


# --------------------------------------------------------------------------
# phase_correlate
# --------------------------------------------------------------------------

def test_phase_correlate_recovers_shift():
    rng = np.random.default_rng(42)
    img = rng.random((64, 64))
    shifted = np.roll(np.roll(img, 3, axis=0), -2, axis=1)
    dx, dy = T.phase_correlate(img, shifted)
    # Sign convention is internal; magnitudes must match the roll.
    assert abs(abs(dx) - 2) <= 1
    assert abs(abs(dy) - 3) <= 1


def test_phase_correlate_zero_for_identical():
    img = np.random.default_rng(1).random((32, 32))
    dx, dy = T.phase_correlate(img, img)
    assert dx == 0 and dy == 0


# --------------------------------------------------------------------------
# motion_continuity_series
# --------------------------------------------------------------------------

def test_continuity_high_for_smooth_pan():
    dx = [0, 2, 2, 2, 2, 2]
    dy = [0, 0, 0, 0, 0, 0]
    cont = T.motion_continuity_series(dx, dy)
    assert float(cont.mean()) > 0.95


def test_continuity_low_for_shake():
    dx = [0, 3, -3, 3, -3, 3]
    dy = [0, 0, 0, 0, 0, 0]
    cont = T.motion_continuity_series(dx, dy)
    assert float(cont.mean()) < 0.4


def test_continuity_high_for_static():
    cont = T.motion_continuity_series([0] * 6, [0] * 6)
    assert np.allclose(cont, 1.0)


def test_continuity_blends_spatial_coherence():
    dx = [0, 2, 2, 2]
    dy = [0, 0, 0, 0]
    # Perfect temporal coherence (1.0) blended 50/50 with bad spatial (0.0).
    cont = T.motion_continuity_series(
        dx, dy, spatial_coherence=[0.0, 0.0, 0.0, 0.0])
    assert float(cont.mean()) == pytest.approx(0.5, abs=0.05)


# --------------------------------------------------------------------------
# temporal_stability_series
# --------------------------------------------------------------------------

def test_stability_constant_luma_is_one():
    s = T.temporal_stability_series(luma=[120] * 8, n=8)
    assert np.allclose(s, 1.0)


def test_stability_flicker_is_low():
    flick = [120, 40, 120, 40, 120, 40, 120, 40]
    s = T.temporal_stability_series(luma=flick, n=8)
    assert float(s.mean()) < 0.2


def test_stability_scene_cut_lowers_boundary():
    ids = [0, 0, 0, 1, 1, 1]
    s = T.temporal_stability_series(scene_id=ids, n=6)
    # A pure single-scene clip is perfectly stable …
    s_pure = T.temporal_stability_series(scene_id=[0] * 6, n=6)
    assert float(s_pure.mean()) == pytest.approx(1.0)
    # … the cut clip is less stable around the boundary.
    assert float(s.mean()) < 1.0


def test_stability_no_signals_defaults_to_one():
    s = T.temporal_stability_series(n=5)
    assert np.allclose(s, 1.0)


def test_stability_combines_multiple_signals():
    s = T.temporal_stability_series(
        luma=[100, 100, 100, 100],
        sharpness=[500, 500, 500, 500],
        subject_fraction=[0.5, 0.5, 0.5, 0.5],
        n=4,
    )
    assert np.allclose(s, 1.0)


# --------------------------------------------------------------------------
# burst_event_series / build_salience
# --------------------------------------------------------------------------

def test_burst_detects_single_spike():
    sal = [0.2, 0.2, 0.2, 0.9, 0.2, 0.2, 0.2]
    b = T.burst_event_series(sal)
    assert int(np.argmax(b)) == 3
    assert float(b[3]) > 0.8
    assert float(b[0]) == 0.0


def test_burst_flat_is_zero():
    b = T.burst_event_series([0.5] * 10)
    assert np.allclose(b, 0.0)


def test_build_salience_weights_moment():
    n = 5
    sal = T.build_salience(
        score_moment=[0, 0, 1, 0, 0],
        appearance_change=None,
        face_count=None,
        n=n,
    )
    # Moment weight is 0.5 → the spike frame ≈0.5, others 0.
    assert sal[2] == pytest.approx(0.5, abs=1e-6)
    assert sal[0] == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------
# aggregate_windows
# --------------------------------------------------------------------------

def test_aggregate_windows_binning_and_formula():
    ts = [0.0, 0.4, 0.8, 1.2, 1.6]
    sf = [0.5, 0.6, 0.7, 0.8, 0.9]
    st = [0.1, 0.9, 0.2, 0.3, 0.4]
    ids = ["f1", "f2", "f3", "f4", "f5"]
    ws = T.aggregate_windows(ts, sf, st, ids, window_s=1.0)
    assert len(ws) == 2
    w0, w1 = ws
    assert w0.frame_ids == ["f1", "f2", "f3"]
    assert w0.mean_score_final == pytest.approx(0.6, abs=1e-4)
    assert w0.max_score_temporal == pytest.approx(0.9)
    assert w0.window_score == pytest.approx(1.5, abs=1e-4)
    assert w0.peak_frame_id == "f2"
    assert w1.frame_ids == ["f4", "f5"]
    assert w1.peak_frame_id == "f5"


def test_aggregate_windows_respects_t0_offset():
    ts = [10.0, 10.5, 11.2]
    ws = T.aggregate_windows(ts, [0.5, 0.5, 0.5], [0.1, 0.2, 0.3],
                             ["a", "b", "c"], window_s=1.0)
    assert ws[0].start_s == 10.0
    assert ws[0].frame_ids == ["a", "b"]
    assert ws[1].frame_ids == ["c"]


def test_aggregate_windows_handles_none_finals():
    ws = T.aggregate_windows(
        [0.0, 0.5], [None, None], [0.3, 0.7], ["a", "b"], window_s=1.0)
    assert ws[0].mean_score_final == 0.0
    assert ws[0].window_score == pytest.approx(0.7)


def test_aggregate_windows_invalid_window_raises():
    with pytest.raises(ValueError, match="window_s"):
        T.aggregate_windows([0.0], [0.5], [0.5], ["a"], window_s=0)


# --------------------------------------------------------------------------
# analyze_temporal
# --------------------------------------------------------------------------

def _synth_records(n=6, dt=0.5):
    return [
        {
            "frame_id": f"frame_{i+1:06d}",
            "timestamp_s": round(i * dt, 3),
            "score_final": 0.5 + 0.01 * i,
            "score_moment": 0.9 if i == 3 else 0.3,
            "mean_luma": 120.0,
            "sharpness": 500.0,
            "subject_fraction": 0.5,
            "face_count": 1,
            "scene": "event",
        }
        for i in range(n)
    ]


def test_analyze_temporal_scores_in_range():
    res = T.analyze_temporal(_synth_records())
    assert len(res.frames) == 6
    for f in res.frames:
        assert 0.0 <= f.score_temporal <= 1.0
        assert 0.0 <= f.motion_continuity <= 1.0
        assert 0.0 <= f.temporal_stability <= 1.0
        assert 0.0 <= f.burst_event <= 1.0
    assert res.windows
    # weights normalise to 1.
    assert sum(res.weights.values()) == pytest.approx(1.0)


def test_analyze_temporal_burst_at_moment_spike():
    res = T.analyze_temporal(_synth_records())
    bursts = [f.burst_event for f in res.frames]
    assert int(np.argmax(bursts)) == 3  # the score_moment spike


def test_analyze_temporal_with_motion():
    recs = _synth_records(n=5)
    motion = {
        "dx": [0, 5, 5, 5, 5], "dy": [0, 0, 0, 0, 0],
        "appearance": [0, 0.1, 0.1, 0.9, 0.1], "frame_dim": 64.0,
    }
    res = T.analyze_temporal(recs, motion=motion)
    assert res.used_motion is True
    # Smooth constant pan ⇒ high continuity.
    assert np.mean([f.motion_continuity for f in res.frames]) > 0.9


def test_analyze_temporal_empty():
    res = T.analyze_temporal([])
    assert res.frames == [] and res.windows == []
    d = res.to_dict()
    assert d["frame_count"] == 0 and d["best_window"] is None


def test_analyze_temporal_single_frame():
    res = T.analyze_temporal(_synth_records(n=1))
    assert len(res.frames) == 1
    assert len(res.windows) == 1


def test_to_dict_schema():
    res = T.analyze_temporal(_synth_records())
    d = res.to_dict()
    for key in ("schema_version", "window_s", "weights", "used_motion",
                "frame_count", "window_count", "mean_score_temporal",
                "best_window", "frames", "windows"):
        assert key in d
    assert d["frame_count"] == len(d["frames"])
    fr = d["frames"][0]
    assert set(fr) == {
        "frame_id", "timestamp_s", "score_final",
        "motion_continuity", "temporal_stability",
        "burst_event", "score_temporal",
    }


def test_normalise_weights():
    w = T._normalise_weights({"motion": 1, "stability": 1, "burst": 2})
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["burst"] == pytest.approx(0.5)
    # Unknown keys ignored, zero-sum falls back to defaults.
    assert T._normalise_weights({"bogus": 5}) == T.DEFAULT_WEIGHTS
    assert T._normalise_weights({"motion": 0, "stability": 0, "burst": 0}) \
        == T.DEFAULT_WEIGHTS


# --------------------------------------------------------------------------
# frame_motion_series (PIL images, no ffmpeg)
# --------------------------------------------------------------------------

def _write_frame(path, arr):
    from PIL import Image
    Image.fromarray(arr.astype("uint8")).save(path)


def test_frame_motion_series_recovers_pan(tmp_path):
    rng = np.random.default_rng(7)
    base = (rng.random((64, 64)) * 255).astype("uint8")
    paths = []
    for i in range(4):
        arr = np.roll(base, i * 3, axis=1)  # pan 3px/frame horizontally
        p = tmp_path / f"frame_{i+1:06d}.jpg"
        _write_frame(p, arr)
        paths.append(p)
    motion = T.frame_motion_series(paths, size=64, use_cv2=False)
    assert len(motion["dx"]) == 4
    assert motion["dx"][0] == 0.0 and motion["dy"][0] == 0.0  # first = zeros
    # Frames 1..3 show horizontal motion.
    assert max(abs(v) for v in motion["dx"][1:]) >= 2
    assert len(motion["appearance"]) == 4


def test_frame_motion_series_static_clip(tmp_path):
    arr = (np.random.default_rng(3).random((48, 48)) * 255).astype("uint8")
    paths = []
    for i in range(3):
        p = tmp_path / f"frame_{i+1:06d}.jpg"
        _write_frame(p, arr)  # identical frames
        paths.append(p)
    motion = T.frame_motion_series(paths, size=48, use_cv2=False)
    assert all(abs(v) < 1 for v in motion["dx"])
    assert all(a < 1.0 for a in motion["appearance"])  # ~no change


# --------------------------------------------------------------------------
# load_run_records + run_temporal_analysis (fake run dir)
# --------------------------------------------------------------------------

def _build_fake_run(tmp_path, n=3):
    """A minimal run dir: video_frames/<id>/{frames,manifest} + scores.csv."""
    vid = "clip_deadbeef"
    fdir = tmp_path / "video_frames" / vid
    fdir.mkdir(parents=True)
    rng = np.random.default_rng(11)
    base = (rng.random((64, 64)) * 255).astype("uint8")
    frames = []
    for i in range(n):
        fn = f"frame_{i+1:06d}.jpg"
        _write_frame(fdir / fn, np.roll(base, i * 2, axis=0))
        frames.append({"frame_id": f"frame_{i+1:06d}",
                       "timestamp_s": float(i), "filename": fn})
    (fdir / "manifest.json").write_text(json.dumps({
        "video_id": vid, "fps": 30.0, "duration_s": float(n),
        "frame_count": n, "codec": "h264", "audio_track_count": 1,
        "frames": frames,
    }))
    # scores.csv with the columns temporal reads.
    import csv
    with open(tmp_path / "scores.csv", "w", newline="") as fh:
        cols = ["filename", "score_final", "score_moment", "mean_luma",
                "laplacian_global", "subject_fraction", "face_count", "scene"]
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for i, fr in enumerate(frames):
            w.writerow({
                "filename": fr["filename"],
                "score_final": 0.5 + 0.05 * i,
                "score_moment": 0.9 if i == 1 else 0.3,
                "mean_luma": 120, "laplacian_global": 500,
                "subject_fraction": 0.5, "face_count": 1, "scene": "event",
            })
    return tmp_path, fdir


def test_load_run_records_joins_manifest_and_scores(tmp_path):
    out, fdir = _build_fake_run(tmp_path, n=3)
    records, paths = T.load_run_records(out)
    assert len(records) == 3
    assert records[0]["frame_id"] == "frame_000001"
    assert records[1]["score_moment"] == pytest.approx(0.9)
    assert records[0]["timestamp_s"] == 0.0
    assert all(p.exists() for p in paths)


def test_run_temporal_analysis_writes_json(tmp_path):
    out, fdir = _build_fake_run(tmp_path, n=3)
    res = T.run_temporal_analysis(out)
    tj = out / "temporal.json"
    assert tj.exists()
    data = json.loads(tj.read_text())
    assert data["frame_count"] == 3
    assert data["window_count"] >= 1
    assert data["used_motion"] is True
    assert len(data["frames"]) == 3
    # The moment spike (frame 2) should carry the highest burst.
    bursts = [f["burst_event"] for f in data["frames"]]
    assert int(np.argmax(bursts)) == 1


def test_run_temporal_analysis_no_motion(tmp_path):
    out, fdir = _build_fake_run(tmp_path, n=3)
    res = T.run_temporal_analysis(out, read_motion=False, write=False)
    assert res.used_motion is False
    assert len(res.frames) == 3


def test_resolve_frames_dir_ambiguous_raises(tmp_path):
    (tmp_path / "video_frames" / "a").mkdir(parents=True)
    (tmp_path / "video_frames" / "b").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="auto-resolve"):
        T.load_run_records(tmp_path)
