"""v2.43-P0 — speech transcription: what was actually *said* in a clip.

DESIGN-AUDIT-2031Q1 recommendation ④.  Before this, ``grep`` for ASR /
subtitle / transcript across the whole codebase returned nothing: PixCull
could tell you a clip was sharp, stable and had a laugh in it, but not a
word of what was said.  For anyone shooting interviews, speeches or
vows, that is the difference between "which take was good" and "which
take had the line I need".

Design
------
**The engine is pluggable and everything else works without one.**  ASR
backends are enormous (FunASR declares 71 dependencies; both it and
Whisper leave numpy unpinned, the same trap that pulled numpy 2.x in
v2.42 and broke mediapipe).  So the model lives behind an extra, and the
parts that decide *how a transcript behaves* — segment timing, SRT
formatting, alignment to shot boundaries — are ordinary pure functions
with no model in sight.  They are fully tested with no engine installed,
which is also how CI exercises them.

Engine choice was measured on the target machine, not assumed
(v2.43.1, Apple M1 Max / 32 GB, both disks nearly full — 17 GiB internal,
31 GiB external):

* marginal install: **FunASR pulls 28 new packages** (aliyun SDKs,
  hydra, librosa, umap-learn, cryptography …) vs **mlx-whisper's 2**,
  because ``mlx`` and most of Whisper's deps were already present;
* MLX runs on the **Metal GPU**, which is the native path on this chip.

So on Apple Silicon the Whisper engine runs through ``mlx_whisper``.
Measured with ``whisper-large-v3-turbo`` weights on the external drive:
first call in a process **12.2s** (loading 1.5 GB over USB), every call
after **1.0s for 5s of audio ≈ 5x realtime**.  Accuracy on real TTS
speech was exact in both Mandarin and English, punctuation included.

Two engines, in the order the owner asked for:

* ``paraformer`` — FunASR's Paraformer-Large, the model FunClip (MIT,
  Alibaba TONGYI) is built on.  Strongest on Mandarin, and its weights
  live on ModelScope, which PixCull already mirrors to.
* ``whisper`` — broader language coverage, weaker on Mandarin than
  Paraformer in published comparisons.

``engine="auto"`` prefers Paraformer and falls back to Whisper.

Unlike shot detection (v2.42), a missing engine here is an **error**, not
a silent degradation: `pixcull transcribe` does nothing else, so quietly
producing an empty transcript would be the "advertised but unreachable"
failure DESIGN-AUDIT-2031Q1 named.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

PARAFORMER = "paraformer"
WHISPER = "whisper"
ENGINES = (PARAFORMER, WHISPER)

# Paraformer wants 16 kHz mono; Whisper resamples internally but is happy
# with the same input, so one extraction serves both.
_SAMPLE_RATE = 16_000


class TranscriptionUnavailable(RuntimeError):
    """No ASR engine installed. Raised rather than returning nothing —
    an empty transcript is indistinguishable from silence."""


@dataclass
class Segment:
    """One timed utterance."""

    start_s: float
    end_s: float
    text: str
    speaker: str | None = None
    shot_index: int | None = None      # filled by align_to_shots

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Transcript:
    segments: list[Segment] = field(default_factory=list)
    engine: str = ""
    language: str = ""

    def to_dict(self) -> dict:
        return {"schema": "pixcull.transcript/v1",
                "engine": self.engine,
                "language": self.language,
                "segments": [s.to_dict() for s in self.segments]}

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments if s.text).strip()


# ==========================================================================
# Engine availability
# ==========================================================================

# v2.43.1 — on Apple Silicon, MLX runs Whisper on the Metal GPU and costs
# two packages (mlx is usually already present) against FunASR's 28.  On
# the maintainer's M1 Max with both disks nearly full, that decided it.
# Model weights are large, so point HF_HOME at roomier storage:
#   export HF_HOME=/Volumes/<drive>/pixcull-models/hf
MLX_DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"


def _has(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:      # noqa: BLE001 — any import failure means "no"
        return False


def available_engines() -> list[str]:
    """Which ASR backends this machine can actually run, best first."""
    out = []
    if _has("funasr"):
        out.append(PARAFORMER)
    if _has("mlx_whisper") or _has("faster_whisper") or _has("whisper"):
        out.append(WHISPER)
    return out


def resolve_engine(engine: str = "auto") -> str:
    """Pick a concrete engine or explain precisely what to install."""
    have = available_engines()
    if engine != "auto":
        if engine not in ENGINES:
            raise ValueError(f"unknown engine {engine!r} (auto|{'|'.join(ENGINES)})")
        if engine not in have:
            raise TranscriptionUnavailable(
                f"engine {engine!r} is not installed — "
                f"{'pip install \"pixcull[asr]\"' if engine == PARAFORMER else 'pip install \"pixcull[asr-whisper]\"'}")
        return engine
    if not have:
        raise TranscriptionUnavailable(
            "no ASR engine installed. Mandarin-first: "
            'pip install "pixcull[asr]" (Paraformer / FunASR). '
            'Broader languages: pip install "pixcull[asr-whisper]".')
    return have[0]


# ==========================================================================
# Audio extraction
# ==========================================================================

def extract_audio(video_path: Path, dest: Path, *,
                  ffmpeg: str | None = None) -> Path:
    """16 kHz mono WAV — what both engines want."""
    exe = ffmpeg or shutil.which("ffmpeg")
    if not exe:
        raise TranscriptionUnavailable(
            "ffmpeg not found; it is needed to pull audio out of a video")
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [exe, "-v", "error", "-y", "-i", str(video_path),
         "-vn", "-ac", "1", "-ar", str(_SAMPLE_RATE), "-f", "wav", str(dest)],
        capture_output=True, text=True)
    if proc.returncode != 0 or not dest.is_file():
        raise TranscriptionUnavailable(
            f"could not extract audio from {video_path.name}: "
            f"{proc.stderr.strip()[:300]}")
    return dest


# ==========================================================================
# SRT — pure, no model needed
# ==========================================================================

def _srt_timestamp(seconds: float) -> str:
    """``HH:MM:SS,mmm``.

    Negative values clamp to zero: a decoder that reports a slightly
    negative offset shouldn't produce a file no player will open.
    """
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: Sequence[Segment]) -> str:
    """SubRip, the format Premiere / Resolve / YouTube all read.

    Segments with no text are dropped — a numbered blank cue is a
    player-visible artefact, not a subtitle.
    """
    lines: list[str] = []
    n = 0
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        n += 1
        lines.append(str(n))
        lines.append(f"{_srt_timestamp(seg.start_s)} --> "
                     f"{_srt_timestamp(seg.end_s)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


# ==========================================================================
# Alignment to shots (reuses v2.42)
# ==========================================================================

def align_to_shots(segments: Sequence[Segment],
                   cut_points: Sequence[float]) -> list[Segment]:
    """Tag each segment with the shot it starts in.

    Uses the *start* deliberately: a sentence that runs across a cut
    belongs to the shot where it began, which is where an editor looking
    for that line will expect to land.
    """
    bounds = sorted(float(c) for c in cut_points)
    out = []
    for seg in segments:
        idx = 0
        for b in bounds:
            if seg.start_s >= b:
                idx += 1
            else:
                break
        out.append(Segment(seg.start_s, seg.end_s, seg.text,
                           speaker=seg.speaker, shot_index=idx))
    return out


# ==========================================================================
# Engines
# ==========================================================================

def _transcribe_paraformer(wav: Path, language: str = "zh") -> Transcript:
    from funasr import AutoModel

    model = AutoModel(model="paraformer-zh", vad_model="fsmn-vad",
                      punc_model="ct-punc", disable_update=True)
    raw = model.generate(input=str(wav), batch_size_s=300)
    segments: list[Segment] = []
    for item in raw or []:
        for s in item.get("sentence_info") or []:
            segments.append(Segment(
                start_s=float(s.get("start", 0)) / 1000.0,
                end_s=float(s.get("end", 0)) / 1000.0,
                text=str(s.get("text", "")).strip(),
                speaker=(str(s["spk"]) if s.get("spk") is not None else None),
            ))
        if not (item.get("sentence_info")) and item.get("text"):
            segments.append(Segment(0.0, 0.0, str(item["text"]).strip()))
    return Transcript(segments=segments, engine=PARAFORMER, language=language)


def _transcribe_whisper(wav: Path, language: str = "") -> Transcript:
    # MLX first on Apple Silicon: same weights, Metal GPU, and it is
    # already installed here. Falls through to the portable runtimes
    # elsewhere.
    if _has("mlx_whisper"):
        import os

        import mlx_whisper

        res = mlx_whisper.transcribe(
            str(wav),
            path_or_hf_repo=os.environ.get("PIXCULL_MLX_WHISPER_MODEL",
                                           MLX_DEFAULT_MODEL),
            language=language or None,
            word_timestamps=False,
        )
        segments = [Segment(float(s["start"]), float(s["end"]),
                            str(s["text"]).strip())
                    for s in res.get("segments", [])
                    if str(s.get("text", "")).strip()]
        return Transcript(segments=segments, engine=WHISPER,
                          language=res.get("language", language) or "")
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segs, info = model.transcribe(str(wav),
                                      language=language or None)
        segments = [Segment(float(s.start), float(s.end), s.text.strip())
                    for s in segs]
        return Transcript(segments=segments, engine=WHISPER,
                          language=getattr(info, "language", language) or "")
    except ImportError:
        pass
    import whisper

    model = whisper.load_model("base")
    res = model.transcribe(str(wav), language=language or None)
    segments = [Segment(float(s["start"]), float(s["end"]),
                        str(s["text"]).strip())
                for s in res.get("segments", [])]
    return Transcript(segments=segments, engine=WHISPER,
                      language=res.get("language", language) or "")


_ENGINE_FUNCS = {PARAFORMER: _transcribe_paraformer,
                 WHISPER: _transcribe_whisper}


def transcribe(
    media_path: Path,
    *,
    engine: str = "auto",
    language: str = "",
    cut_points: Sequence[float] | None = None,
) -> Transcript:
    """Transcribe a video (or audio file), optionally aligned to shots."""
    media_path = Path(media_path)
    chosen = resolve_engine(engine)

    with tempfile.TemporaryDirectory(prefix="pixcull_asr_") as td:
        if media_path.suffix.lower() in (".wav",):
            wav = media_path
        else:
            wav = extract_audio(media_path, Path(td) / "audio.wav")
        result = _ENGINE_FUNCS[chosen](wav, language)

    if cut_points:
        result.segments = align_to_shots(result.segments, cut_points)
    return result


def write_transcript(transcript: Transcript, output_dir: Path) -> dict:
    """Write ``transcript.json`` + ``transcript.srt`` into a run dir."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    j = output_dir / "transcript.json"
    s = output_dir / "transcript.srt"
    j.write_text(json.dumps(transcript.to_dict(), ensure_ascii=False,
                            indent=2), encoding="utf-8")
    s.write_text(to_srt(transcript.segments), encoding="utf-8")
    return {"json": j, "srt": s, "n_segments": len(transcript.segments)}


def load_transcript(output_dir: Path) -> Transcript | None:
    """Read a previously written transcript, or None."""
    p = Path(output_dir) / "transcript.json"
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return Transcript(
        segments=[Segment(float(s.get("start_s", 0)),
                          float(s.get("end_s", 0)),
                          str(s.get("text", "")),
                          speaker=s.get("speaker"),
                          shot_index=s.get("shot_index"))
                  for s in d.get("segments", [])],
        engine=d.get("engine", ""), language=d.get("language", ""))
