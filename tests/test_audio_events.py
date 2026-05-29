"""v2.0-P1-3 — tests for pixcull.scoring.audio_events.

Synthetic signals drive the pure DSP detectors (no ffmpeg); the
ffmpeg-backed extract path skips when ffmpeg is absent.
"""

from __future__ import annotations

import shutil

import numpy as np
import pytest

from pixcull.scoring import audio_events as A

SR = 16000


def _t(seconds):
    return np.arange(int(seconds * SR)) / SR


def _music(seconds=6):
    t = _t(seconds)
    beat = 0.5 * (1 + np.sign(np.sin(2 * np.pi * 2 * t)))   # 120 BPM
    return (0.3 + 0.2 * beat) * np.sin(2 * np.pi * 440 * t)


def _applause(seconds=4):
    return np.random.default_rng(0).standard_normal(int(seconds * SR)) * 0.5


def _laughter(seconds=4):
    t = _t(seconds)
    rng = np.random.default_rng(1)
    mod = 0.5 * (1 + np.sin(2 * np.pi * 5 * t))             # 5 Hz syllables
    harm = sum(np.sin(2 * np.pi * 180 * k * t) / k for k in (1, 2, 3, 4, 5))
    return mod * (0.8 * harm + 0.4 * rng.standard_normal(t.size)) * 0.25


# --------------------------------------------------------------------------
# frame_features
# --------------------------------------------------------------------------

def test_frame_features_shapes():
    f = A.frame_features(_music(2), SR)
    n = f["times"].shape[0]
    for k in ("rms", "flatness", "centroid", "onset"):
        assert f[k].shape[0] == n
    assert np.all((f["flatness"] >= 0) & (f["flatness"] <= 1))


def test_frame_features_flatness_tone_vs_noise():
    tone = A.frame_features(np.sin(2 * np.pi * 440 * _t(2)), SR)
    noise = A.frame_features(_applause(2), SR)
    assert tone["flatness"].mean() < 0.05      # tonal
    assert noise["flatness"].mean() > 0.3      # noise-like


# --------------------------------------------------------------------------
# detectors
# --------------------------------------------------------------------------

def test_detect_music():
    evs = A.detect_music(A.frame_features(_music(), SR))
    assert evs and evs[0].kind == "music"
    assert evs[0].end_s - evs[0].start_s >= 3.0


def test_noise_is_not_music():
    assert A.detect_music(A.frame_features(_applause(), SR)) == []


def test_detect_applause():
    evs = A.detect_applause(A.frame_features(_applause(), SR))
    assert evs and evs[0].kind == "applause"


def test_tone_is_not_applause():
    assert A.detect_applause(A.frame_features(_music(), SR)) == []


def test_detect_laughter():
    evs = A.detect_laughter(A.frame_features(_laughter(), SR))
    assert evs and evs[0].kind == "laughter"


def test_steady_tone_is_not_laughter():
    assert A.detect_laughter(
        A.frame_features(np.sin(2 * np.pi * 300 * _t(4)) * 0.3, SR)) == []


def test_silence_no_events():
    f = A.frame_features(np.zeros(int(3 * SR)), SR)
    assert A.detect_music(f) == []
    assert A.detect_applause(f) == []
    assert A.detect_laughter(f) == []


# --------------------------------------------------------------------------
# tempo / beats
# --------------------------------------------------------------------------

def test_estimate_tempo_music():
    # The 120 BPM amplitude-pulsed tone drives a clear onset envelope.
    tempo, strength = A.estimate_tempo(A.frame_features(_music(), SR))
    assert 110 <= tempo <= 130
    assert strength > 0.3


def test_beat_times_spacing():
    beats = A.beat_times(A.frame_features(_music(), SR))
    assert len(beats) >= 4
    diffs = np.diff(beats)
    # 120 BPM ⇒ ~0.5 s spacing.
    assert abs(np.median(diffs) - 0.5) < 0.15


def test_beat_times_none_for_noise():
    assert A.beat_times(A.frame_features(_applause(), SR)) == []


# --------------------------------------------------------------------------
# moment boost
# --------------------------------------------------------------------------

def test_audio_moment_boost():
    evs = [A.AudioEvent("laughter", 1.0, 2.0, 0.8),
           A.AudioEvent("music", 0.0, 5.0, 1.0)]
    b = A.audio_moment_boost([0.0, 1.5, 3.0], evs)
    assert b[1] == pytest.approx(0.8)      # inside laughter
    assert b[0] == 0.0 and b[2] == 0.0     # music has weight 0


# --------------------------------------------------------------------------
# analyze_audio
# --------------------------------------------------------------------------

def test_analyze_audio_empty():
    r = A.analyze_audio(np.zeros(0))
    assert r.has_audio is False
    assert r.events == [] and r.to_dict()["summary"]["music"] == 0


def test_analyze_audio_music():
    r = A.analyze_audio(_music(), SR)
    assert r.has_audio is True
    assert r.tempo_bpm > 0
    assert any(e.kind == "music" for e in r.events)
    d = r.to_dict()
    assert d["schema_version"] == 1 and "beats_s" in d


# --------------------------------------------------------------------------
# extract_audio (ffmpeg)
# --------------------------------------------------------------------------

@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_extract_audio(tmp_path):
    import subprocess
    clip = tmp_path / "a.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=15",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(clip)], check=True, capture_output=True, timeout=60)
    samples, sr = A.extract_audio(clip)
    assert sr == A.DEFAULT_SR
    assert samples.size > SR          # ~2 s of audio
    assert float(np.abs(samples).max()) > 0.05
