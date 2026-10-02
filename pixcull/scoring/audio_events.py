"""v2.0-P1-3 — Audio content awareness for video.

Charter ``docs/ROADMAP-v2.0-charter.md`` § v2.0-P1-3: extend the
v0.10 audio-photo sync to a clip's *original* audio — detect **laughter**
and **applause** (boost the moment axis), and **music** (mark BGM ranges
+ beat grid so a reel cut never lands mid-phrase).

Numpy-only DSP (no audio-ML dependency).  Per-frame features over short
windows:

* **rms** — energy.
* **spectral flatness** (Wiener entropy) — high = noise-like (applause),
  low = tonal (music / sustained tone).
* **spectral centroid** — brightness.
* **onset envelope** (half-wave-rectified spectral flux) — transients,
  used for applause density + music tempo.

Detectors:

* **applause** = sustained high-flatness + high-energy (broadband noise
  burst).
* **music** = sustained low-flatness + steady energy + a clear tempo
  peak in the onset autocorrelation (distinguishes BGM from speech).
* **laughter** = energy-envelope amplitude modulation in the 3–8 Hz
  band inside voiced regions (a heuristic proxy).

:func:`audio_moment_boost` turns laughter+applause regions into a
per-frame ``[0,1]`` boost for the moment axis; :func:`beat_times` gives
the BGM beat grid (uncuttable points).

The feature + detector functions are pure (numpy arrays) and unit-test
without ffmpeg; :func:`extract_audio` shells out to ffmpeg.

Honest deviation: robust laughter/applause/music tagging really wants an
audio event model (YAMNet / PANNs).  These DSP heuristics are the
offline, dependency-light baseline; an ML tagger is the upgrade path.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

DEFAULT_SR = 16000
DEFAULT_WIN_S = 0.05
DEFAULT_HOP_S = 0.05

# Detection thresholds (tuned on synthetic + a handful of real clips).
_APPLAUSE_FLATNESS = 0.30
_MUSIC_FLATNESS = 0.12
_LAUGH_AM_LO, _LAUGH_AM_HI = 3.0, 8.0   # Hz, laughter syllable rate
_MIN_EVENT_S = 0.6
_MUSIC_MIN_S = 3.0
# Onset-autocorrelation peak below this ⇒ no real beat (noise sits ~0.18,
# steady music ~0.9), so we don't emit a tempo / beat grid.
_TEMPO_MIN_STRENGTH = 0.30


@dataclass
class AudioEvent:
    kind: str            # "laughter" | "applause" | "music"
    start_s: float
    end_s: float
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Feature extraction (pure numpy)
# --------------------------------------------------------------------------

def frame_features(
    samples: np.ndarray,
    sr: int = DEFAULT_SR,
    *,
    win_s: float = DEFAULT_WIN_S,
    hop_s: float = DEFAULT_HOP_S,
) -> dict:
    """Short-time features.  Returns equal-length arrays keyed by name."""
    x = np.asarray(samples, dtype=np.float64).ravel()
    win = max(8, int(win_s * sr))
    hop = max(1, int(hop_s * sr))
    if x.size < win:
        x = np.pad(x, (0, win - x.size))
    n_frames = 1 + (x.size - win) // hop
    window = np.hanning(win)
    rms = np.zeros(n_frames)
    flatness = np.zeros(n_frames)
    centroid = np.zeros(n_frames)
    flux = np.zeros(n_frames)
    freqs = np.fft.rfftfreq(win, d=1.0 / sr)
    prev_mag = None
    for i in range(n_frames):
        seg = x[i * hop:i * hop + win] * window
        rms[i] = np.sqrt(np.mean(seg ** 2)) if seg.size else 0.0
        mag = np.abs(np.fft.rfft(seg))
        psd = mag ** 2 + 1e-12
        gmean = np.exp(np.mean(np.log(psd)))
        amean = np.mean(psd)
        flatness[i] = float(np.clip(gmean / amean, 0.0, 1.0))
        centroid[i] = float(np.sum(freqs * psd) / np.sum(psd))
        if prev_mag is not None:
            flux[i] = float(np.sum(np.maximum(0.0, mag - prev_mag)))
        prev_mag = mag
    times = np.arange(n_frames) * hop_s
    # Normalise flux to [0,1] for an onset envelope.
    onset = flux / (np.percentile(flux, 95) + 1e-9)
    onset = np.clip(onset, 0.0, 1.0)
    return {
        "times": times, "rms": rms, "flatness": flatness,
        "centroid": centroid, "onset": onset, "hop_s": hop_s, "sr": sr,
    }


# Below this peak RMS the clip is treated as effectively silent.
_SILENCE_RMS = 0.01


def _rms_floor(rms: np.ndarray, frac: float = 0.2) -> float:
    """Energy floor as a fraction of the clip's peak RMS (so an all-music
    or all-applause clip still passes — a percentile-relative floor would
    sit mid-signal and only flag the louder half)."""
    if rms.size == 0:
        return 0.0
    return max(frac * float(rms.max()), 0.5 * _SILENCE_RMS)


def _is_silent(rms: np.ndarray) -> bool:
    return rms.size == 0 or float(rms.max()) < _SILENCE_RMS


def _segments_from_mask(
    mask: np.ndarray, times: np.ndarray, hop_s: float, *,
    min_dur_s: float, kind: str, conf: np.ndarray,
) -> list[AudioEvent]:
    out: list[AudioEvent] = []
    n = mask.shape[0]
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            start = float(times[i])
            end = float(times[j]) + hop_s
            if end - start + 1e-9 >= min_dur_s:
                out.append(AudioEvent(
                    kind=kind, start_s=round(start, 3), end_s=round(end, 3),
                    confidence=round(float(np.mean(conf[i:j + 1])), 3)))
            i = j + 1
        else:
            i += 1
    return out


# --------------------------------------------------------------------------
# Detectors
# --------------------------------------------------------------------------

def detect_applause(features: dict) -> list[AudioEvent]:
    rms, flat = features["rms"], features["flatness"]
    if _is_silent(rms):
        return []
    floor = _rms_floor(rms, 0.35)
    mask = (flat > _APPLAUSE_FLATNESS) & (rms > floor)
    conf = np.clip((flat - _APPLAUSE_FLATNESS) / (1 - _APPLAUSE_FLATNESS), 0, 1)
    return _segments_from_mask(mask, features["times"], features["hop_s"],
                               min_dur_s=_MIN_EVENT_S, kind="applause", conf=conf)


def detect_music(features: dict) -> list[AudioEvent]:
    rms, flat = features["rms"], features["flatness"]
    if _is_silent(rms):
        return []
    floor = _rms_floor(rms, 0.12)
    tonal = flat < _MUSIC_FLATNESS
    energetic = rms > floor
    mask = tonal & energetic
    # Require a tempo peak somewhere (steady beat ⇒ music, not speech).
    tempo, strength = estimate_tempo(features)
    if strength < _TEMPO_MIN_STRENGTH:
        # No clear beat — likely speech / single tone; suppress unless very
        # sustained + steady energy.
        steady = rms.std() < 0.5 * (rms.mean() + 1e-9)
        if not steady:
            return []
    conf = np.clip((_MUSIC_FLATNESS - flat) / _MUSIC_FLATNESS, 0, 1)
    return _segments_from_mask(mask, features["times"], features["hop_s"],
                               min_dur_s=_MUSIC_MIN_S, kind="music", conf=conf)


def detect_laughter(features: dict) -> list[AudioEvent]:
    """Energy-envelope AM in 3–8 Hz inside voiced regions (heuristic)."""
    rms = features["rms"]
    flat = features["flatness"]
    hop_s = features["hop_s"]
    n = rms.size
    if n < 8:
        return []
    env_sr = 1.0 / hop_s
    # Sliding ~1s window AM strength in the laughter band.
    w = max(8, int(round(1.0 / hop_s)))
    am = np.zeros(n)
    freqs = np.fft.rfftfreq(w, d=1.0 / env_sr)
    band = (freqs >= _LAUGH_AM_LO) & (freqs <= _LAUGH_AM_HI)
    for i in range(n):
        a = max(0, i - w // 2)
        b = min(n, a + w)
        seg = rms[a:b]
        if seg.size < w:
            seg = np.pad(seg, (0, w - seg.size))
        seg = seg - seg.mean()
        if not np.any(seg):
            continue
        mag = np.abs(np.fft.rfft(seg * np.hanning(w)))
        total = np.sum(mag) + 1e-9
        am[i] = float(np.sum(mag[band]) / total)
    if _is_silent(rms):
        return []
    floor = _rms_floor(rms, 0.2)
    # Laughter energy is *itself* modulated at the syllable rate, so a
    # per-frame energy gate would flicker at that rate and never form a
    # segment.  Smooth energy + flatness over the AM window first.
    kernel = np.ones(w) / w
    local_rms = np.convolve(rms, kernel, mode="same")
    local_flat = np.convolve(flat, kernel, mode="same")
    voiced = (local_flat > 0.02) & (local_flat < 0.6)
    mask = (am > 0.45) & (local_rms > floor) & voiced
    return _segments_from_mask(mask, features["times"], hop_s,
                               min_dur_s=_MIN_EVENT_S, kind="laughter", conf=am)


# --------------------------------------------------------------------------
# Tempo / beats
# --------------------------------------------------------------------------

def estimate_tempo(features: dict) -> tuple[float, float]:
    """(tempo_bpm, strength 0..1) from onset-envelope autocorrelation."""
    onset = np.asarray(features["onset"], dtype=np.float64)
    hop_s = features["hop_s"]
    if onset.size < 16:
        return 0.0, 0.0
    o = onset - onset.mean()
    ac = np.correlate(o, o, mode="full")[o.size - 1:]
    if ac[0] <= 0:
        return 0.0, 0.0
    ac = ac / ac[0]
    # Search lags for 60–180 BPM.
    lo = max(1, int(round((60.0 / 180.0) / hop_s)))
    hi = min(ac.size - 1, int(round((60.0 / 60.0) / hop_s)))
    if hi <= lo:
        return 0.0, 0.0
    lag = lo + int(np.argmax(ac[lo:hi]))
    strength = float(np.clip(ac[lag], 0.0, 1.0))
    tempo = 60.0 / (lag * hop_s)
    return round(tempo, 1), strength


def beat_times(features: dict, *, max_beats: int = 2000) -> list[float]:
    """Beat grid (seconds) from the estimated tempo, phase-aligned to the
    strongest onset.  Empty when no clear tempo."""
    tempo, strength = estimate_tempo(features)
    if tempo <= 0 or strength < _TEMPO_MIN_STRENGTH:
        return []
    onset = np.asarray(features["onset"])
    times = np.asarray(features["times"])
    if onset.size == 0:
        return []
    period = 60.0 / tempo
    phase = float(times[int(np.argmax(onset))]) % period
    end = float(times[-1])
    beats = []
    t = phase
    while t <= end and len(beats) < max_beats:
        beats.append(round(t, 3))
        t += period
    return beats


# --------------------------------------------------------------------------
# Moment boost
# --------------------------------------------------------------------------

def audio_moment_boost(
    timestamps: Sequence[float],
    events: Sequence[AudioEvent],
    *,
    weights: dict[str, float] | None = None,
) -> np.ndarray:
    """Per-frame ``[0,1]`` moment boost from laughter/applause regions."""
    w = {"laughter": 1.0, "applause": 0.8, "music": 0.0}
    if weights:
        w.update(weights)
    ts = np.asarray(timestamps, dtype=np.float64)
    out = np.zeros(ts.shape[0])
    for ev in events:
        gain = w.get(ev.kind, 0.0) * float(ev.confidence)
        if gain <= 0:
            continue
        inside = (ts >= ev.start_s) & (ts <= ev.end_s)
        out = np.maximum(out, np.where(inside, gain, 0.0))
    return np.clip(out, 0.0, 1.0)


# --------------------------------------------------------------------------
# Audio extraction + orchestration
# --------------------------------------------------------------------------

def extract_audio(
    path: Path, *, sr: int = DEFAULT_SR, ffmpeg: str | None = None,
) -> tuple[np.ndarray, int]:
    """Decode mono PCM via ffmpeg → (float32 array in [-1,1], sr).  Empty
    array when there's no audio track or ffmpeg is missing."""
    ff = shutil.which(ffmpeg or "ffmpeg") or ffmpeg
    if not ff:
        return np.zeros(0, dtype=np.float64), sr
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-i", str(path),
           "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "pipe:1"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return np.zeros(0, dtype=np.float64), sr
    if proc.returncode != 0 or not proc.stdout:
        return np.zeros(0, dtype=np.float64), sr
    pcm = np.frombuffer(proc.stdout, dtype="<i2").astype(np.float64) / 32768.0
    return pcm, sr


#: The name of the DSP detectors as a tagger. Defined here, not in
#: ``audio_tagger`` (which imports this module), so both can name it.
HEURISTIC_TAGGER = "heuristic-dsp"


@dataclass
class AudioResult:
    events: list[AudioEvent]
    beats_s: list[float]
    tempo_bpm: float
    has_audio: bool
    #: v3.93 — what produced ``events``. ``None`` means nothing listened
    #: for events at all, which is not the same as "listened and heard
    #: none"; ``note`` says which, in a sentence a person can act on.
    tagger: str | None = HEURISTIC_TAGGER
    note: str | None = None
    #: The same thing as ``note`` for a program: one of ``NOT_LISTENED``.
    reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "has_audio": self.has_audio,
            "tagger": self.tagger,
            "reason": self.reason,
            "note": self.note,
            "tempo_bpm": self.tempo_bpm,
            "events": [e.to_dict() for e in self.events],
            "beats_s": self.beats_s,
            "summary": {
                k: sum(1 for e in self.events if e.kind == k)
                for k in ("laughter", "applause", "music")
            },
        }


def analyze_audio(samples: np.ndarray, sr: int = DEFAULT_SR) -> AudioResult:
    """Run all detectors on a mono float audio array (pure; no ffmpeg)."""
    if samples is None or len(samples) == 0:
        return AudioResult([], [], 0.0, has_audio=False)
    feats = frame_features(samples, sr)
    events = (detect_laughter(feats) + detect_applause(feats)
              + detect_music(feats))
    events.sort(key=lambda e: e.start_s)
    tempo, _ = estimate_tempo(feats)
    return AudioResult(events=events, beats_s=beat_times(feats),
                       tempo_bpm=tempo, has_audio=True)


def analyze_audio_file(path: Path, *, ffmpeg: str | None = None) -> AudioResult:
    samples, sr = extract_audio(Path(path), ffmpeg=ffmpeg)
    return analyze_audio(samples, sr)


#: Why nothing listened for events, as ``reason`` -> the sentence in
#: ``note``. The review page keys its own wording on the reason.
NOT_LISTENED = {
    "no-model": (
        "no audio event model is installed, so laughter / applause / music "
        "were not listened for. `pixcull models pull audio-tagger` (16 MB) "
        "adds them."),
    "model-failed": (
        "the audio event model failed on this clip, so no events were "
        "recorded."),
    "no-source": (
        "the source video is no longer where this run recorded it, so "
        "there was nothing to listen to."),
    "no-track": "the video has no audio track.",
    "undecodable": (
        "ffmpeg could not decode an audio track from the source video."),
}


def _silent(reason: str) -> AudioResult:
    return AudioResult([], [], 0.0, has_audio=False, tagger=None,
                       reason=reason, note=NOT_LISTENED[reason])


def run_audio_analysis(output_dir: Path, *, write: bool = True,
                       tagger=None, frames_dir: Path | None = None
                       ) -> AudioResult:
    """Listen to the run's source video and write ``audio_events.json``.

    v3.93 — this function had no caller from the day it was written
    (v2.0-P1-3). Three readers were built on its output — the reel
    detector's ``why``, the review page's event lane, the lightbox
    scrubber — and `pixcull video` never produced the file they read.

    **Events come from the learned tagger or not at all.** The DSP
    detectors above are what ``get_tagger`` falls back to, and wiring
    that fallback into the product would have put them in front of
    everyone who has not pulled the optional model. On this project's
    own evaluation (``docs/AUDIO-TAGGER-EVAL.md``, 64 real clips) they
    found none of 20 applause clips and were right about laughter 12%
    of the time. The readers print what they are given — "现场笑声" in a
    reel caption, a green bar under the frames it was "heard" at — so a
    detector that is wrong seven times in eight becomes a product that
    says so with confidence. Without the model the file records that
    nothing listened, and says how to change that.

    The tempo and beat grid still come from the DSP path: they are a
    different measurement (onset autocorrelation with its own strength
    floor) and no learned model here replaces them.

    ``tagger`` is for tests; ``None`` asks ``get_tagger`` for the learned
    one. ``frames_dir`` is the clip's ``video_frames/<id>/``; without it
    the directory is found by looking, which only works while the output
    holds one clip — `pixcull video` knows which one it just extracted
    and says so.
    """
    from pixcull.scoring.temporal import _resolve_frames_dir
    output_dir = Path(output_dir)
    frames_dir = _resolve_frames_dir(output_dir, frames_dir)
    manifest = json.loads((frames_dir / "manifest.json").read_text("utf-8"))
    source = manifest.get("source_path")
    if not source or not Path(source).exists():
        result = _silent("no-source")
    elif manifest.get("audio_track_count") == 0:
        result = _silent("no-track")
    else:
        samples, sr = extract_audio(Path(source))
        if len(samples) == 0:
            result = _silent("undecodable")
        else:
            result = analyze_audio(samples, sr)
            _tag_events(result, samples, sr, tagger)
    if write:
        (output_dir / "audio_events.json").write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8")
    return result


def _tag_events(result: AudioResult, samples: np.ndarray, sr: int,
                tagger) -> None:
    """Replace the DSP events on ``result`` with the learned tagger's, or
    with nothing — see :func:`run_audio_analysis` for why not the DSP's."""
    if tagger is None:
        # Imported here: audio_tagger imports this module.
        from pixcull.scoring.audio_tagger import get_tagger
        tagger = get_tagger()
    if getattr(tagger, "name", HEURISTIC_TAGGER) == HEURISTIC_TAGGER:
        result.events, result.tagger = [], None
        result.reason, result.note = "no-model", NOT_LISTENED["no-model"]
        return
    try:
        events = list(tagger.tag(samples, sr))
    except Exception as exc:  # noqa: BLE001 — a model failing must not cost the reel
        why = (str(exc).splitlines() or [""])[0][:160]
        result.events, result.tagger = [], None
        result.reason = "model-failed"
        result.note = (f"{NOT_LISTENED['model-failed']} "
                       f"({type(exc).__name__}: {why})")
        return
    events.sort(key=lambda e: e.start_s)
    result.events, result.tagger = events, tagger.name
    result.reason = result.note = None
