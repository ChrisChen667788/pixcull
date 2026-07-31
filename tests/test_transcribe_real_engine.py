"""v2.43.2 — run the ASR engine for real, because pure tests missed three bugs.

`tests/test_transcribe.py` covers the pure functions with no engine
installed, which is right and is how CI runs.  But the first time this
engine was actually started on a machine, three separate defects fell
out that no amount of pure testing could have found:

1. ``import funasr`` succeeded while ``from funasr import AutoModel``
   raised, so PixCull advertised an engine that crashed on use;
2. the adapter read ``sentence_info``, a key this configuration never
   returns — every segment came back timed 0.0-0.0 and the SRT was
   unusable;
3. the model was rebuilt on every call, re-reading 1.6 GB of weights
   (measured: 59 s per clip instead of 1.3 s).

Each of those was, from a unit test's point of view, working code.  So
this module exists to start the real thing.  It is marked ``slow`` and
skips cleanly wherever the engine or its weights are absent — including
CI, which is why the fast lane runs ``-m "not slow"``.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests._model_gate import require_paraformer   # noqa: E402

pytestmark = pytest.mark.slow

SPOKEN = "今天我们在这里拍摄婚礼。请新郎新娘站到中间。"


@pytest.fixture(scope="module")
def speech_wav(tmp_path_factory) -> Path:
    """Real speech, synthesised locally — no recording of a real person.

    macOS `say` is the only dependency-free source of genuine speech
    here. Where it is missing the test skips rather than falling back to
    a tone: a sine wave would exercise the plumbing while proving
    nothing about transcription.
    """
    if not shutil.which("say") or not shutil.which("ffmpeg"):
        pytest.skip("needs macOS `say` + ffmpeg to synthesise test speech")
    d = tmp_path_factory.mktemp("asr")
    aiff, wav = d / "s.aiff", d / "s.wav"
    if subprocess.run(["say", "-v", "Tingting", "-o", str(aiff), SPOKEN],
                      capture_output=True).returncode != 0:
        pytest.skip("`say` has no Mandarin voice installed on this machine")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(aiff),
                    "-ac", "1", "-ar", "16000", str(wav)], check=True)
    return wav


def _duration(wav: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(wav)], capture_output=True, text=True)
    return float(out.stdout.strip())


def test_paraformer_returns_segments_with_real_timestamps(speech_wav):
    """The regression: every segment used to come back timed 0.0-0.0."""
    require_paraformer()
    from pixcull.scoring.transcribe import transcribe

    tr = transcribe(speech_wav, engine="paraformer", language="zh")
    dur = _duration(speech_wav)

    assert tr.segments, "no segments at all"
    assert not all(s.start_s == 0.0 and s.end_s == 0.0 for s in tr.segments), (
        "every segment is timed 0.0-0.0 — the sentence_info regression is "
        "back; see segments_from_char_timestamps")
    for s in tr.segments:
        assert 0.0 <= s.start_s <= s.end_s <= dur + 0.5, (
            f"segment [{s.start_s}, {s.end_s}] outside 0..{dur:.2f}s")
    starts = [s.start_s for s in tr.segments]
    assert starts == sorted(starts), "segments out of order"


def test_paraformer_hears_the_words_that_were_spoken(speech_wav):
    """Not a WER benchmark — just proof it is transcribing, not echoing."""
    require_paraformer()
    from pixcull.scoring.transcribe import transcribe

    heard = transcribe(speech_wav, engine="paraformer", language="zh").text
    for word in ("拍摄", "婚礼", "新郎", "新娘"):
        assert word in heard, f"{word!r} missing from {heard!r}"


def test_paraformer_model_is_not_rebuilt_between_calls(speech_wav):
    """A rebuild re-reads 1.6 GB. Measured 59s vs 1.3s per clip."""
    require_paraformer()          # first build happens here
    from pixcull.scoring.transcribe import transcribe

    transcribe(speech_wav, engine="paraformer", language="zh")   # warm
    t0 = time.time()
    transcribe(speech_wav, engine="paraformer", language="zh")
    warm = time.time() - t0
    # The full build took ~55s on the reference machine; anything near
    # that means the cache is gone. 15s is generous enough to survive a
    # loaded CI box without letting a real rebuild through.
    assert warm < 15.0, (
        f"warm call took {warm:.1f}s — the model is being rebuilt per call")


def test_srt_from_a_real_transcript_has_distinct_timestamps(speech_wav):
    require_paraformer()
    from pixcull.scoring.transcribe import to_srt, transcribe

    srt = to_srt(transcribe(speech_wav, engine="paraformer",
                            language="zh").segments)
    assert "00:00:00,000 --> 00:00:00,000" not in srt, (
        "SRT carries the zero-duration cue that made every line unseekable")
    assert "-->" in srt
