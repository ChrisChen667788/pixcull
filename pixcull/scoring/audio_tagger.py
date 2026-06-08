"""v2.1-P0-1 — Learned audio event tagging (pluggable, DSP fallback).

Charter ``docs/ROADMAP-v2.1-charter.md`` § v2.1-P0-1.  The v2.0
``audio_events`` module detects laughter / applause / music with pure
DSP heuristics; this adds an **optional learned backend** behind a small
``AudioTagger`` interface, while keeping the heuristics as the always-
available offline default.

* :class:`HeuristicTagger` — wraps the existing ``audio_events``
  detectors.  No model, no network, always available.
* :class:`OnnxTagger` — runs an optional audio-event ONNX model
  (e.g. a YAMNet/PANNs export) when one is present + ``onnxruntime`` is
  installed.  Per-frame class probabilities are mapped to our kinds
  (laughter / applause / music) via a sidecar ``<model>.labels.json``
  and merged into segments.  Absent model ⇒ ``available() is False``.
* :func:`get_tagger` returns the learned tagger when usable, else the
  heuristic one — so behaviour is **byte-identical to v2.0 when no model
  is installed** (no regression).

The probability→event post-processing (:func:`probs_to_events`) and the
confidence calibration (:func:`calibrate_confidence`) are pure functions,
unit-tested without any model; only ``session.run`` needs a real ONNX.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

import numpy as np

from pixcull.scoring.audio_events import (
    DEFAULT_SR,
    AudioEvent,
    analyze_audio,
    audio_moment_boost,  # re-exported for callers
)

# Where an optional audio-event model is looked up (first hit wins).
_MODEL_SEARCH = [
    os.environ.get("PIXCULL_AUDIO_MODEL", ""),
    str(Path.home() / ".pixcull" / "models" / "audio_tagger.onnx"),
    "models/audio_tagger.onnx",
]
# Canonical class-name → our kind.  A model's labels.json maps its raw
# class names through here (case-insensitive substring match).
_KIND_SYNONYMS = {
    "laughter": "laughter", "laugh": "laughter", "giggle": "laughter",
    "applause": "applause", "clap": "applause", "cheer": "applause",
    "music": "music", "singing": "music", "instrument": "music",
}
_MIN_EVENT_S = 0.6


@runtime_checkable
class AudioTagger(Protocol):
    name: str
    def available(self) -> bool: ...
    def tag(self, samples: np.ndarray, sr: int) -> list[AudioEvent]: ...


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------

def calibrate_confidence(p: float | np.ndarray, *, temperature: float = 1.5):
    """Soften a raw model probability toward 0.5 so it sits on the same
    scale as the heuristic detector's confidence.  ``T>1`` pulls
    over-confident scores toward the middle; ``T=1`` is identity."""
    p = np.clip(np.asarray(p, dtype=np.float64), 0.0, 1.0)
    if temperature <= 0:
        return float(p) if p.ndim == 0 else p
    out = np.clip(0.5 + (p - 0.5) / temperature, 0.0, 1.0)
    return float(out) if out.ndim == 0 else out


def map_label_to_kind(label: str) -> str | None:
    """Map a raw model class name to laughter/applause/music (or None)."""
    lab = (label or "").strip().lower()
    for key, kind in _KIND_SYNONYMS.items():
        if key in lab:
            return kind
    return None


def probs_to_events(
    probs: np.ndarray,
    frame_times: Sequence[float],
    labels: Sequence[str],
    *,
    hop_s: float,
    thresh: float | Mapping[str, float] = 0.5,
    min_dur_s: float = _MIN_EVENT_S,
    temperature: float = 1.5,
) -> list[AudioEvent]:
    """Per-frame class probs → merged :class:`AudioEvent` segments.

    ``probs`` is ``[n_frames, n_classes]``; ``labels`` names the classes.
    Classes that don't map to a kind are ignored.  Per kind, frames above
    ``thresh`` are run-length-merged into ≥ ``min_dur_s`` segments with a
    calibrated mean confidence.

    ``thresh`` is either a single float applied to every kind, or a
    per-kind mapping (``{"laughter": 0.3, "applause": 0.55}``) — the
    v2.4-P1-3 calibrated operating point.  Kinds missing from the mapping
    fall back to ``0.5``.
    """
    probs = np.asarray(probs, dtype=np.float64)
    times = np.asarray(frame_times, dtype=np.float64)
    if probs.ndim != 2 or probs.shape[0] == 0:
        return []
    # Collapse classes into per-kind max prob per frame.
    kinds = ("laughter", "applause", "music")
    kind_prob = {k: np.zeros(probs.shape[0]) for k in kinds}
    for ci, lab in enumerate(labels):
        if ci >= probs.shape[1]:
            break
        k = map_label_to_kind(lab)
        if k:
            kind_prob[k] = np.maximum(kind_prob[k], probs[:, ci])

    out: list[AudioEvent] = []
    n = probs.shape[0]
    for k in kinds:
        kp = kind_prob[k]
        kt = thresh.get(k, 0.5) if isinstance(thresh, Mapping) else thresh
        mask = kp > kt
        i = 0
        while i < n:
            if mask[i]:
                j = i
                while j + 1 < n and mask[j + 1]:
                    j += 1
                start = float(times[i])
                end = float(times[j]) + hop_s
                if end - start + 1e-9 >= min_dur_s:
                    conf = calibrate_confidence(
                        float(kp[i:j + 1].mean()), temperature=temperature)
                    out.append(AudioEvent(kind=k, start_s=round(start, 3),
                                          end_s=round(end, 3),
                                          confidence=round(float(conf), 3)))
                i = j + 1
            else:
                i += 1
    out.sort(key=lambda e: e.start_s)
    return out


def best_threshold(truth, scorer, *, grid) -> tuple[float, float]:
    """Pick the threshold in ``grid`` that maximises detection F1.

    ``truth`` is the per-clip boolean ground truth for one kind; ``scorer``
    is a callable ``t -> list[bool]`` giving that kind's prediction for
    every clip at threshold ``t`` (the v2.4-P1-3 calibrator passes a closure
    that re-runs :func:`probs_to_events` on cached probs, so the sweep is
    faithful to the real detection path — min-duration merging and all).

    Returns ``(threshold, f1)``.  ``grid`` is swept ascending, so on an F1
    tie the **smaller** threshold wins — deliberately biasing toward recall,
    which is the operating point this calibration is meant to recover
    (laughter recall was 0.25 at the blanket 0.5).  Degenerate input
    (empty grid / no positives) → ``(0.5, 0.0)``.
    """
    from pixcull.scoring.eval_metrics import binary_prf
    truth = list(truth)
    if not grid or not any(truth):
        return 0.5, 0.0
    best_t, best_f1 = 0.5, -1.0
    for t in sorted(grid):
        f1 = binary_prf(truth, list(scorer(t)))["f1"]
        if f1 > best_f1:
            best_t, best_f1 = float(t), float(f1)
    return best_t, max(0.0, best_f1)


# --------------------------------------------------------------------------
# Taggers
# --------------------------------------------------------------------------

class HeuristicTagger:
    """The v2.0 DSP detectors behind the tagger interface (default)."""
    name = "heuristic-dsp"

    def available(self) -> bool:
        return True

    def tag(self, samples: np.ndarray, sr: int = DEFAULT_SR) -> list[AudioEvent]:
        return analyze_audio(samples, sr).events


@lru_cache(maxsize=4)
def _load_session(model_path: str):
    """Cache ONNX sessions by path (avoids reloading the model per clip)."""
    import onnxruntime as ort
    return ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])


@dataclass
class OnnxTagger:
    """Optional learned backend (YAMNet/PANNs-style ONNX).

    ``model_path`` points to an ONNX whose input is a batch of mono audio
    frames ``[N, frame_samples]`` and output is ``[N, n_classes]`` probs;
    ``<model_path>.labels.json`` lists the class names.  Missing model or
    ``onnxruntime`` ⇒ :meth:`available` is ``False``.
    """
    model_path: str
    name: str = "onnx"
    frame_s: float = 0.96
    hop_s: float = 0.48
    thresh: float = 0.5
    apply_calibrated_defaults: bool = True

    def _labels(self) -> list[str]:
        lp = Path(str(self.model_path) + ".labels.json")
        if not lp.exists():
            lp = Path(self.model_path).with_suffix(".labels.json")
        try:
            return list(json.loads(lp.read_text("utf-8")))
        except (OSError, ValueError):
            return []

    def available(self) -> bool:
        if not self.model_path or not Path(self.model_path).exists():
            return False
        if not self._labels():
            return False
        try:
            import onnxruntime  # noqa: F401
        except Exception:
            return False
        return True

    def _frames(self, samples: np.ndarray, sr: int) -> tuple[np.ndarray, list[float]]:
        x = np.asarray(samples, dtype=np.float32).ravel()
        fl = max(1, int(self.frame_s * sr))
        hop = max(1, int(self.hop_s * sr))
        if x.size < fl:
            x = np.pad(x, (0, fl - x.size))
        starts = list(range(0, x.size - fl + 1, hop)) or [0]
        frames = np.stack([x[s:s + fl] for s in starts]).astype(np.float32)
        times = [s / sr for s in starts]
        return frames, times

    def _thresholds(self) -> float | dict[str, float]:
        """Per-kind detection thresholds — the v2.4-P1-3 calibrated operating
        point.  Resolution order:

        1. a per-model ``<model>.thresholds.json`` sidecar (a user's own or
           a published-model override) — always honoured, else
        2. the packaged default (``scoring/data/audio_tagger_thresholds.json``
           — the F1-max sweep on the ESC-50 subset: laughter recall
           0.25 → 0.85, macro-F1 0.629 → 0.933) when
           ``apply_calibrated_defaults`` (the production path: the only
           catalogued audio model is the YAMNet export these were tuned
           for), else
        3. the scalar ``self.thresh`` (0.5).

        Kinds missing from the chosen mapping fall back to 0.5 inside
        :func:`probs_to_events` (e.g. ``music`` has no calibrated point yet).
        A caller feeding a *different* model's probs (or a synthetic test
        signal) sets ``apply_calibrated_defaults=False`` to get the raw 0.5.
        """
        cands = [Path(str(self.model_path) + ".thresholds.json")]
        if self.apply_calibrated_defaults:
            cands.append(Path(__file__).parent / "data"
                         / "audio_tagger_thresholds.json")
        for cand in cands:
            if cand.exists():
                try:
                    d = json.loads(cand.read_text("utf-8"))
                    if isinstance(d, dict) and d:
                        return {str(k): float(v) for k, v in d.items()}
                except (OSError, ValueError, TypeError):
                    continue
        return self.thresh

    def infer_probs(self, samples: np.ndarray, sr: int = DEFAULT_SR
                    ) -> tuple[np.ndarray, list[float]]:
        """Run the model → ``([n_frames, n_classes] probs, frame_times)``.

        The raw, pre-threshold output.  Used by :meth:`tag` and by the
        v2.4-P1-3 threshold calibration (which sweeps thresholds on these
        cached probs).  Empty ``(0, 0)`` array when unavailable.
        """
        if not self.available():
            return np.zeros((0, 0)), []
        sess = _load_session(self.model_path)
        inp = sess.get_inputs()[0]
        if len(inp.shape) == 1:
            # Waveform-in model (e.g. YAMNet): feed the whole 16 kHz signal;
            # it does its own 0.96 s / 0.48 s framing → [n_frames, n_classes].
            x = np.asarray(samples, dtype=np.float32).ravel()
            if sr != 16000 and x.size:
                n = max(1, round(x.size * 16000 / sr))
                x = np.interp(np.linspace(0, x.size, n, endpoint=False),
                              np.arange(x.size), x).astype(np.float32)
            probs = np.asarray(sess.run(None, {inp.name: x})[0], dtype=np.float64)
            if probs.ndim == 1:
                probs = probs[None, :]
            times = [i * self.hop_s for i in range(probs.shape[0])]
        else:
            # Framed-in model: [N, frame_samples] → [N, n_classes].
            frames, times = self._frames(samples, sr)
            probs = np.asarray(sess.run(None, {inp.name: frames})[0],
                               dtype=np.float64)
            if probs.ndim == 1:
                probs = probs[None, :]
        return probs, times

    def tag(self, samples: np.ndarray, sr: int = DEFAULT_SR) -> list[AudioEvent]:
        if not self.available():
            return []
        probs, times = self.infer_probs(samples, sr)
        return probs_to_events(probs, times, self._labels(),
                               hop_s=self.hop_s, thresh=self._thresholds())


def find_model() -> str | None:
    for cand in _MODEL_SEARCH:
        if cand and Path(cand).exists():
            return cand
    return None


def get_tagger(*, prefer_model: bool = True) -> AudioTagger:
    """Return the learned tagger when a model is installed + usable,
    else the always-available heuristic tagger."""
    if prefer_model:
        mp = find_model()
        if mp:
            t = OnnxTagger(model_path=mp)
            if t.available():
                return t
    return HeuristicTagger()


def tag_audio(samples: np.ndarray, sr: int = DEFAULT_SR,
              tagger: AudioTagger | None = None) -> list[AudioEvent]:
    """Tag audio events with the best available backend."""
    return (tagger or get_tagger()).tag(samples, sr)


__all__ = [
    "AudioTagger", "HeuristicTagger", "OnnxTagger", "get_tagger",
    "tag_audio", "find_model", "probs_to_events", "map_label_to_kind",
    "calibrate_confidence", "audio_moment_boost",
]
