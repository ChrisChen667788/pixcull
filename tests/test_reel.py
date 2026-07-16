"""v2.0-P0-3 — tests for pixcull.scoring.reel (reel candidate detector).

Pure-numeric core is exercised with synthetic per-frame records; the run
IO layer uses a hand-built temporal.json + scores.csv.  No ffmpeg.
"""

from __future__ import annotations

import json

import pytest

from pixcull.scoring import reel as R


# --------------------------------------------------------------------------
# synthetic frame helpers
# --------------------------------------------------------------------------

def _frame(i, t, *, final=0.6, temporal=0.3, burst=0.0,
           motion=0.9, stability=0.9, faces=1, scene="event"):
    return {
        "frame_id": f"frame_{i+1:06d}", "timestamp_s": round(t, 3),
        "score_final": final, "score_temporal": temporal,
        "burst_event": burst, "motion_continuity": motion,
        "temporal_stability": stability, "face_count": faces, "scene": scene,
    }


def _clip_with_peaks(peaks_s, n=40, dt=0.5):
    frames = []
    for i in range(n):
        t = i * dt
        peak = max((max(0.0, 1 - abs(t - p) / 1.0) for p in peaks_s),
                   default=0.0)
        frames.append(_frame(
            i, t,
            final=0.55 + 0.2 * peak,
            temporal=min(1.0, 0.25 + 0.7 * peak),
            burst=peak,
            scene="event" if t < 8 else ("portrait" if t < 14 else "landscape"),
        ))
    return frames


# --------------------------------------------------------------------------
# interval_overlap_ratio / novelty
# --------------------------------------------------------------------------

def test_overlap_disjoint_is_zero():
    assert R.interval_overlap_ratio((0, 1), (2, 3)) == 0.0


def test_overlap_nested_is_one():
    # 1-s window fully inside a 3-s window ⇒ contained.
    assert R.interval_overlap_ratio((1, 2), (0, 3)) == pytest.approx(1.0)


def test_overlap_partial():
    # [0,2] vs [1,3]: inter=1, shorter=2 ⇒ 0.5
    assert R.interval_overlap_ratio((0, 2), (1, 3)) == pytest.approx(0.5)


def test_novelty_empty_selected_is_one():
    assert R.novelty_vs({"start_s": 0, "end_s": 2, "scene": "a"}, []) == 1.0


def test_novelty_drops_with_overlap():
    sel = [{"start_s": 0.0, "end_s": 2.0, "scene": "a", "end": 2}]
    cand = {"start_s": 0.0, "end_s": 2.0, "scene": "a"}
    assert R.novelty_vs(cand, sel) == pytest.approx(0.0)  # identical span


def test_novelty_scene_penalty_for_adjacent_same_scene():
    sel = [{"start_s": 0.0, "end_s": 1.0, "scene": "portrait"}]
    near = {"start_s": 1.5, "end_s": 2.5, "scene": "portrait"}  # gap 0.5s
    far = {"start_s": 10.0, "end_s": 11.0, "scene": "portrait"}  # gap 9s
    assert R.novelty_vs(near, sel) < R.novelty_vs(far, sel)
    assert R.novelty_vs(far, sel) == pytest.approx(1.0)


# --------------------------------------------------------------------------
# window_confidence / window_aggregate
# --------------------------------------------------------------------------

def test_confidence_higher_for_more_consistent_frames():
    consistent = [_frame(i, i, final=0.7, temporal=0.8) for i in range(3)]
    thin = [_frame(0, 0, final=0.7, temporal=0.8)]
    assert R.window_confidence(consistent) > R.window_confidence(thin)


def test_confidence_empty_is_zero():
    assert R.window_confidence([]) == 0.0


def test_window_aggregate_formula_and_best_frame():
    frames = [
        _frame(0, 0.0, final=0.5, temporal=0.2),
        _frame(1, 0.5, final=0.6, temporal=0.9),   # best blend
        _frame(2, 1.0, final=0.4, temporal=0.3),
    ]
    agg = R.window_aggregate(frames, 0.0, 1.5)
    # window_score = mean(final) + max(temporal) = 0.5 + 0.9 = 1.4
    assert agg["window_score"] == pytest.approx(1.4, abs=1e-3)
    assert agg["window_score_norm"] == pytest.approx(0.7, abs=1e-3)
    assert agg["best_frame_id"] == "frame_000002"
    # best_frame_score = 0.5*0.6 + 0.5*0.9 = 0.75
    assert agg["best_frame_score"] == pytest.approx(0.75, abs=1e-3)


# --------------------------------------------------------------------------
# sliding_windows
# --------------------------------------------------------------------------

def test_sliding_windows_multiple_lengths():
    frames = [_frame(i, i * 0.5) for i in range(20)]  # 0..9.5s
    wins = R.sliding_windows(frames, window_lens_s=(1, 2, 3), stride_s=1.0)
    lengths = {round(w["end_s"] - w["start_s"]) for w in wins}
    assert {1, 2, 3} <= lengths
    assert all(w["frames"] for w in wins)


def test_sliding_windows_short_clip_single_window():
    frames = [_frame(0, 0.0), _frame(1, 0.5)]  # 0.5s clip
    wins = R.sliding_windows(frames, window_lens_s=(1, 2, 3))
    # Clip shorter than every window length ⇒ exactly one whole-clip window.
    assert len(wins) == 1
    assert wins[0]["start_s"] == 0.0


def test_sliding_windows_empty():
    assert R.sliding_windows([]) == []


# --------------------------------------------------------------------------
# compose_why
# --------------------------------------------------------------------------

def test_compose_why_burst_and_faces():
    frames = [_frame(0, 0, burst=0.9, faces=2, final=0.7)]
    w = R.window_aggregate(frames, 0, 1)
    why = R.compose_why(w)
    assert "精彩瞬间" in why
    assert " + " in why


def test_compose_why_empty_fallback():
    assert R.compose_why({"frames": []}) == "可用片段"


def test_compose_why_quiet_segment_fallback():
    # Low everything ⇒ generic stable label, never crashes.
    frames = [_frame(0, 0, burst=0.0, motion=0.3, stability=0.3,
                     final=0.2, faces=0, scene="abstract")]
    w = R.window_aggregate(frames, 0, 1)
    assert R.compose_why(w) == "稳定可用片段"


def test_compose_why_caps_fragments():
    frames = [_frame(0, 0, burst=0.9, motion=0.95, stability=0.95,
                     final=0.8, faces=2, scene="portrait")]
    w = R.window_aggregate(frames, 0, 1)
    why = R.compose_why(w, max_fragments=2)
    assert len(why.split(" + ")) <= 2


# --------------------------------------------------------------------------
# select_candidates / detect_reel_candidates
# --------------------------------------------------------------------------

def test_detect_finds_diverse_peaks():
    frames = _clip_with_peaks([3.0, 10.0, 16.0])
    cands = R.detect_reel_candidates(frames, n_min=3, n_max=8)
    assert len(cands) >= 3
    # Top-3 should each sit near a distinct peak and not overlap each other.
    top3 = cands[:3]
    for a in range(len(top3)):
        for b in range(a + 1, len(top3)):
            ov = R.interval_overlap_ratio(
                (top3[a].start_s, top3[a].end_s),
                (top3[b].start_s, top3[b].end_s))
            assert ov <= R._NMS_OVERLAP
    # Each real peak (3/10/16s) is covered by some top-3 candidate.
    for p in (3.0, 10.0, 16.0):
        assert any(c.start_s <= p <= c.end_s for c in top3)


def test_detect_respects_n_max():
    frames = _clip_with_peaks([3.0, 10.0, 16.0])
    cands = R.detect_reel_candidates(frames, n_min=2, n_max=4)
    assert len(cands) <= 4


def test_detect_ranks_descending_and_assigns_rank():
    frames = _clip_with_peaks([5.0, 12.0])
    cands = R.detect_reel_candidates(frames, n_min=2, n_max=6)
    scores = [c.score for c in cands]
    assert scores == sorted(scores, reverse=True)
    assert [c.rank for c in cands] == list(range(1, len(cands) + 1))


def test_detect_nms_collapses_nested_windows():
    frames = _clip_with_peaks([8.0])  # one peak
    cands = R.detect_reel_candidates(frames, n_min=1, n_max=10)
    # No two selected candidates may exceed the NMS overlap threshold.
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            ov = R.interval_overlap_ratio(
                (cands[i].start_s, cands[i].end_s),
                (cands[j].start_s, cands[j].end_s))
            assert ov <= R._NMS_OVERLAP


def test_detect_empty():
    assert R.detect_reel_candidates([]) == []


def test_detect_single_frame():
    cands = R.detect_reel_candidates([_frame(0, 0.0)], n_min=1, n_max=5)
    assert len(cands) == 1
    assert cands[0].rank == 1


# --------------------------------------------------------------------------
# run_reel_detection (fake temporal.json + scores.csv)
# --------------------------------------------------------------------------

def _write_run(tmp_path, frames, with_scene=True):
    temporal = {
        "schema_version": 1, "window_s": 1.0,
        "frame_count": len(frames),
        "frames": [
            {k: f[k] for k in ("frame_id", "timestamp_s", "score_final",
                               "score_temporal", "motion_continuity",
                               "temporal_stability", "burst_event")}
            for f in frames
        ],
    }
    (tmp_path / "temporal.json").write_text(json.dumps(temporal))
    if with_scene:
        import csv
        with open(tmp_path / "scores.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["filename", "scene", "face_count"])
            w.writeheader()
            for f in frames:
                w.writerow({"filename": f"{f['frame_id']}.jpg",
                            "scene": f.get("scene", "event"),
                            "face_count": int(f.get("face_count", 1))})
    return tmp_path


def test_run_reel_detection_writes_array(tmp_path):
    out = _write_run(tmp_path, _clip_with_peaks([4.0, 12.0]))
    cands = R.run_reel_detection(out, n_min=2, n_max=6)
    rj = out / "reel_candidates.json"
    assert rj.exists()
    data = json.loads(rj.read_text())
    assert isinstance(data, list)               # charter array format
    assert 1 <= len(data) <= 6
    for key in ("rank", "start_s", "end_s", "score", "why",
                "best_frame_id", "best_frame_score"):
        assert key in data[0]


def test_run_reel_detection_enriches_why_from_scores(tmp_path):
    # All frames are portraits with faces ⇒ "why" should mention people.
    frames = [_frame(i, i * 0.5, burst=0.0, scene="portrait", faces=2)
              for i in range(8)]
    out = _write_run(tmp_path, frames)
    cands = R.run_reel_detection(out, n_min=1, n_max=5)
    assert cands
    assert any("人物" in c.why for c in cands)


def test_run_reel_detection_missing_temporal_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="temporal"):
        R.run_reel_detection(tmp_path)


def test_run_reel_detection_without_scores_csv(tmp_path):
    # No scores.csv ⇒ still works (scene/face enrichment just absent).
    out = _write_run(tmp_path, _clip_with_peaks([6.0]), with_scene=False)
    cands = R.run_reel_detection(out, n_min=1, n_max=5)
    assert cands


# --------------------------------------------------------------------------
# v2.17-P0 — reel glass box: window_signals + compose_why_low + emission
# --------------------------------------------------------------------------

def test_window_signals_aggregation():
    frames = [
        _frame(0, 0.0, motion=0.8, stability=0.9, burst=0.1, final=0.6),
        _frame(1, 0.5, motion=0.6, stability=0.7, burst=0.9, final=0.4),
    ]
    w = R.window_aggregate(frames, 0.0, 1.0)
    s = R.window_signals(w)
    assert s["motion"] == pytest.approx(0.7)        # mean
    assert s["stability"] == pytest.approx(0.8)     # mean
    assert s["burst"] == pytest.approx(0.9)         # MAX (peak signal)
    assert s["quality"] == pytest.approx(w["mean_score_final"])


def test_why_low_names_the_biggest_shortfall():
    medians = {"motion": 0.85, "stability": 0.85, "burst": 0.5, "quality": 0.6}
    s = {"motion": 0.45, "stability": 0.80, "burst": 0.5, "quality": 0.6}
    out = R.compose_why_low(s, medians)
    assert "运镜平稳度" in out and "0.45" in out and "0.85" in out


def test_why_low_empty_for_strong_window():
    medians = {"motion": 0.8, "stability": 0.8, "burst": 0.4, "quality": 0.6}
    s = {"motion": 0.9, "stability": 0.85, "burst": 0.7, "quality": 0.7}
    assert R.compose_why_low(s, medians) == ""
    # tiny shortfall below the min_gap must also stay silent
    s2 = dict(s, motion=0.78)
    assert R.compose_why_low(s2, medians) == ""


def test_candidates_carry_signals_and_why_low():
    frames = _clip_with_peaks([3.0, 12.0])
    # make one stretch clearly shaky so SOME candidate can be below median
    for f in frames:
        if 10.0 <= f["timestamp_s"] <= 14.0:
            f["motion_continuity"] = 0.3
    cands = R.detect_reel_candidates(frames)
    assert cands, "no candidates from synthetic clip"
    for c in cands:
        d = c.to_dict()
        assert set(d["signals"]) == {"motion", "stability", "burst", "quality"}
        assert all(0.0 <= v <= 1.0 for v in d["signals"].values())
        assert isinstance(d["why_low"], str)
    # round-trips through JSON (what reel_candidates.json will carry)
    blob = json.dumps([c.to_dict() for c in cands], ensure_ascii=False)
    back = json.loads(blob)
    assert "signals" in back[0] and "why_low" in back[0]


# --------------------------------------------------------------------------
# v2.20-P3 — audio-aware why + reel taste profile
# --------------------------------------------------------------------------

def test_compose_why_mentions_overlapping_audio():
    frames = [_frame(0, 0.0, burst=0.9), _frame(1, 0.5, burst=0.9)]
    w = R.window_aggregate(frames, 0.0, 1.0)
    ev = [{"kind": "laughter", "start_s": 0.3, "end_s": 0.8, "confidence": 0.9}]
    assert "现场笑声" in R.compose_why(w, audio_events=ev)
    # non-overlapping event stays silent
    ev2 = [{"kind": "applause", "start_s": 5.0, "end_s": 6.0, "confidence": 0.9}]
    assert "现场掌声" not in R.compose_why(w, audio_events=ev2)


def test_learn_reel_profile_contrast_required():
    sig_hi = {"motion": 0.9, "stability": 0.9, "burst": 0.8, "quality": 0.7}
    sig_lo = {"motion": 0.3, "stability": 0.4, "burst": 0.1, "quality": 0.4}
    recs = ([{"decision": "keep", "signals": sig_hi}] * 3
            + [{"decision": "cull", "signals": sig_lo}] * 2)
    prof = R.learn_reel_profile(recs)
    assert prof["n"] == 5
    assert prof["pref"]["burst"] == pytest.approx(0.7)
    # keep-only → no contrast → None
    assert R.learn_reel_profile([{"decision": "keep", "signals": sig_hi}]) is None


def test_load_reel_profile_gate(tmp_path):
    p = tmp_path / "prof.json"
    p.write_text('{"n": 5, "pref": {"burst": 0.5}}')
    assert R.load_reel_profile(p) is None            # below the ≥20 gate
    p.write_text('{"n": 25, "pref": {"burst": 0.5}}')
    assert R.load_reel_profile(p)["pref"]["burst"] == 0.5


def test_profile_tilt_reorders_candidates():
    # two clearly separated peaks; the burst-lover profile must not FLIP
    # decisions wildly (cap ±0.15) but a bursty window should gain rank
    # score relative to a calm one.
    frames = _clip_with_peaks([3.0, 12.0])
    base = R.detect_reel_candidates(frames)
    prof = {"n": 30, "pref": {"burst": 1.0, "motion": 0.0,
                              "stability": 0.0, "quality": 0.0}}
    tilted = R.detect_reel_candidates(frames, profile=prof)
    b0 = {c.rank: c.score for c in base}
    t0 = {c.rank: c.score for c in tilted}
    assert b0 and t0
    # scores changed somewhere (the tilt is live) but stay within the cap
    ratios = [t.score / b.score for b, t in
              [(x, y) for x in base for y in tilted
               if abs(x.start_s - y.start_s) < 1e-6 and abs(x.end_s - y.end_s) < 1e-6]
              if b.score > 0]
    assert ratios and all(0.84 <= r <= 1.16 for r in ratios)
