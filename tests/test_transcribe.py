"""v2.43 — transcription: SRT, shot alignment, and honest failure.

DESIGN-AUDIT-2031Q1 recommendation ④. Before this, grep for ASR /
subtitle / transcript across the codebase returned nothing.

Everything here runs with NO engine installed. That is the design: ASR
backends are enormous (FunASR declares 71 dependencies) so the model
lives behind an extra, while the parts that decide how a transcript
*behaves* — timing, SRT formatting, shot alignment — are pure functions.
"""

import json
import pathlib
import sys
import types

import pytest

import pixcull.scoring.transcribe as T
from pixcull.scoring.transcribe import (
    PARAFORMER, WHISPER, Segment, Transcript, TranscriptionUnavailable,
    align_to_shots, available_engines, load_transcript, resolve_engine,
    segments_from_char_timestamps, to_srt, write_transcript,
    _ENGINE_PROBES, _srt_timestamp, _wants_simplified,
)


# ── SRT ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("secs,expect", [
    (0.0, "00:00:00,000"),
    (0.4, "00:00:00,400"),
    (61.5, "00:01:01,500"),
    (3661.25, "01:01:01,250"),
    (-0.5, "00:00:00,000"),       # a decoder reporting negative offset
])
def test_srt_timestamps(secs, expect):
    assert _srt_timestamp(secs) == expect


def test_srt_is_well_formed():
    srt = to_srt([Segment(0.4, 2.8, "第一句"), Segment(3.2, 5.6, "second")])
    blocks = [b for b in srt.split("\n\n") if b.strip()]
    assert len(blocks) == 2
    first = blocks[0].splitlines()
    assert first[0] == "1"
    assert first[1] == "00:00:00,400 --> 00:00:02,800"
    assert first[2] == "第一句"
    assert blocks[1].splitlines()[0] == "2", "cues must renumber from 1"


def test_empty_segments_are_dropped_and_do_not_break_numbering():
    """A numbered blank cue is a player-visible artefact."""
    srt = to_srt([Segment(0, 1, "a"), Segment(1, 2, "   "),
                  Segment(2, 3, "b")])
    nums = [b.splitlines()[0] for b in srt.split("\n\n") if b.strip()]
    assert nums == ["1", "2"]
    assert "   \n" not in srt


def test_srt_of_nothing_is_empty_not_malformed():
    assert to_srt([]) == ""


# ── shot alignment (reuses v2.42) ─────────────────────────────────────

def test_alignment_tags_the_shot_a_line_starts_in():
    segs = [Segment(0.4, 2.8, "a"), Segment(3.2, 5.6, "b"),
            Segment(6.1, 8.4, "c")]
    got = align_to_shots(segs, [3.0, 6.0])
    assert [s.shot_index for s in got] == [0, 1, 2]


def test_a_line_spanning_a_cut_belongs_to_where_it_started():
    """Where an editor hunting that line expects to land."""
    got = align_to_shots([Segment(2.5, 4.5, "spans")], [3.0])
    assert got[0].shot_index == 0


def test_alignment_without_cuts_puts_everything_in_shot_zero():
    got = align_to_shots([Segment(1, 2, "x"), Segment(9, 10, "y")], [])
    assert [s.shot_index for s in got] == [0, 0]


# ── engine resolution: loud, not silent ───────────────────────────────

def test_no_engine_raises_rather_than_returning_an_empty_transcript(
        monkeypatch):
    """An empty transcript is indistinguishable from a silent clip —
    exactly the 'advertised but unreachable' failure the audit named."""
    monkeypatch.setattr("pixcull.scoring.transcribe.available_engines",
                        lambda: [])
    with pytest.raises(TranscriptionUnavailable) as ei:
        resolve_engine("auto")
    assert "pixcull[asr]" in str(ei.value), "must name the install command"


def test_requesting_an_uninstalled_engine_names_its_extra(monkeypatch):
    monkeypatch.setattr("pixcull.scoring.transcribe.available_engines",
                        lambda: [WHISPER])
    with pytest.raises(TranscriptionUnavailable) as ei:
        resolve_engine(PARAFORMER)
    assert "pixcull[asr]" in str(ei.value)


def test_unknown_engine_is_a_value_error(monkeypatch):
    monkeypatch.setattr("pixcull.scoring.transcribe.available_engines",
                        lambda: [PARAFORMER])
    with pytest.raises(ValueError):
        resolve_engine("nope")


def test_auto_prefers_paraformer(monkeypatch):
    """The owner's stated order: Mandarin-first, Whisper as fallback."""
    monkeypatch.setattr("pixcull.scoring.transcribe.available_engines",
                        lambda: [PARAFORMER, WHISPER])
    assert resolve_engine("auto") == PARAFORMER
    monkeypatch.setattr("pixcull.scoring.transcribe.available_engines",
                        lambda: [WHISPER])
    assert resolve_engine("auto") == WHISPER


def test_available_engines_is_honest_about_this_machine():
    for e in available_engines():
        assert e in (PARAFORMER, WHISPER)


# ── v2.43.2: the lazy-import lie ──────────────────────────────────────
#
# Found on a real `pip install "pixcull[asr]"`. funasr 1.4.0 imports
# torchaudio unconditionally but does not declare it, and its __init__ is
# lazy — so `import funasr` succeeded while `from funasr import
# AutoModel` raised ModuleNotFoundError. available_engines() therefore
# advertised Paraformer, resolve_engine("auto") picked it, and
# transcription died with a bare ModuleNotFoundError instead of
# TranscriptionUnavailable.
#
# Reproduced here without funasr installed, so it guards in CI too.

class _LazilyBrokenModule(types.ModuleType):
    """Imports clean, raises on first real attribute access."""

    def __getattr__(self, name):
        raise ModuleNotFoundError("No module named 'torchaudio'")


@pytest.fixture
def _funasr_that_imports_but_cannot_run(monkeypatch):
    monkeypatch.setitem(sys.modules, "funasr",
                        _LazilyBrokenModule("funasr"))
    # Keep the whisper side genuinely absent so the assertions below are
    # about Paraformer alone.
    for name in ("mlx_whisper", "faster_whisper", "whisper"):
        monkeypatch.setitem(sys.modules, name, None)


def test_engine_that_imports_but_cannot_run_is_not_advertised(
        _funasr_that_imports_but_cannot_run):
    assert "funasr" in sys.modules          # the import itself succeeds
    assert PARAFORMER not in available_engines()


def test_lazy_broken_engine_raises_the_designed_error_not_a_bare_crash(
        _funasr_that_imports_but_cannot_run):
    # auto: nothing usable at all -> the install hint
    with pytest.raises(TranscriptionUnavailable):
        resolve_engine("auto")
    # explicit: still TranscriptionUnavailable, never ModuleNotFoundError
    with pytest.raises(TranscriptionUnavailable) as ei:
        resolve_engine(PARAFORMER)
    assert "pixcull[asr]" in str(ei.value)


def test_probe_resolves_the_attribute_the_adapter_actually_calls():
    """The probe must name a real entry point, not just a package.

    A probe pointing at an attribute that doesn't exist would silently
    disable a working engine, which is the opposite failure.
    """
    for engine, probes in _ENGINE_PROBES.items():
        assert probes, f"{engine} has no probe"
        for module, attr in probes:
            assert isinstance(module, str) and module
            assert isinstance(attr, str) and attr
            mod = sys.modules.get(module)
            if mod is not None and not isinstance(mod, _LazilyBrokenModule):
                assert hasattr(mod, attr), (
                    f"{module}.{attr} is not the real entry point")


# ── v2.43.2: Paraformer's real output shape ───────────────────────────
#
# The adapter read `sentence_info`. On a real run that key is absent —
# the engine returns key / text / timestamp — so every segment came back
# timed 0.0-0.0 and the SRT was unusable. These fixtures are the actual
# measured output of a 6.66s clip, so the mapping is pinned to reality
# rather than to what the docs implied.

# "今天我们在这里拍摄婚礼，请新郎新娘站到中间灯光准备好了吗？"
_REAL_TEXT = "今天我们在这里拍摄婚礼，请新郎新娘站到中间灯光准备好了吗？"
_REAL_TS = [
    [110, 210], [210, 450], [530, 690], [690, 830], [830, 1070],
    [1130, 1290], [1290, 1490], [1490, 1690], [1690, 1930], [1950, 2110],
    [2110, 2350], [2570, 2810], [2810, 2990], [2990, 3170], [3170, 3350],
    [3350, 3590], [3590, 3770], [3770, 3950], [3950, 4190], [4250, 4430],
    [4430, 4670], [4730, 4910], [4910, 5090], [5090, 5330], [5330, 5570],
    [6150, 6330], [6330, 6535],
]


def test_char_timestamps_produce_real_times_not_zeroes():
    segs = segments_from_char_timestamps(_REAL_TEXT, _REAL_TS)
    assert len(segs) == 2
    assert segs[0].text == "今天我们在这里拍摄婚礼，"
    assert segs[0].start_s == pytest.approx(0.110)
    assert segs[0].end_s == pytest.approx(2.350)
    assert segs[1].start_s == pytest.approx(2.570)
    assert segs[1].end_s == pytest.approx(6.535)
    # The regression itself: nothing may come back timed 0.0-0.0.
    assert not any(s.start_s == 0.0 and s.end_s == 0.0 for s in segs)


def test_char_timestamps_stay_inside_the_audio():
    segs = segments_from_char_timestamps(_REAL_TEXT, _REAL_TS)
    assert segs[-1].end_s <= 6.66
    assert all(s.end_s >= s.start_s for s in segs)
    assert all(b.start_s >= a.start_s for a, b in zip(segs, segs[1:]))


def test_mismatched_counts_give_one_honest_span_not_a_guess():
    """Mixed zh/en emits one span per WORD, so the per-char map breaks.

    Measured: 19 timestamps for 29 non-punctuation characters. Guessing
    an alignment would put subtitles on the wrong frames, so the guard
    returns the whole utterance with the outer bounds the model reported.
    """
    text = "这条用be rule过渡，然后切到close up特写。Ok就这样。"
    ts = [[50, 200], [200, 400], [400, 700], [700, 1100], [1100, 1500],
          [1500, 1800], [1800, 2100], [2100, 2400], [2400, 2700],
          [2700, 3000], [3000, 3300], [3300, 3600], [3600, 3900],
          [3900, 4200], [4200, 4500], [4500, 4700], [4700, 4900],
          [4900, 5100], [5100, 5275]]
    segs = segments_from_char_timestamps(text, ts)
    assert len(segs) == 1
    assert segs[0].start_s == pytest.approx(0.050)
    assert segs[0].end_s == pytest.approx(5.275)
    assert segs[0].text == text          # nothing dropped


def test_sentence_final_always_splits_but_a_short_clause_does_not():
    # "好。" ends a sentence even though it is 2 characters.
    segs = segments_from_char_timestamps(
        "好。走吧。", [[0, 100], [200, 300], [300, 400]])
    assert [s.text for s in segs] == ["好。", "走吧。"]
    # A comma before min_clause_chars must NOT split.
    segs = segments_from_char_timestamps(
        "好，走吧。", [[0, 100], [200, 300], [300, 400]])
    assert [s.text for s in segs] == ["好，走吧。"]


def test_char_timestamps_degrade_quietly_on_empty_input():
    assert segments_from_char_timestamps("", [[0, 1]]) == []
    assert segments_from_char_timestamps("你好", []) == []
    assert segments_from_char_timestamps("", []) == []


def test_simplified_hint_fires_for_chinese_only():
    """Whisper emits Traditional Mandarin unless primed.

    Measured v2.43.2 on identical audio: "第一條被選鏡頭有點陡" without
    the hint, "第一条背选镜头有点抖" with it — CER 52.4% -> 4.8%. The
    hint must NOT fire on auto-detect, where it would bias the language
    guess toward Chinese.
    """
    for lang in ("zh", "zh-CN", "ZH", "zh-Hans", "chinese", "Mandarin"):
        assert _wants_simplified(lang), lang
    for lang in ("", "en", "ja", "en-US", None):
        assert not _wants_simplified(lang), lang


def test_paraformer_model_is_built_once_per_process(monkeypatch):
    """Rebuilding it re-read 1.6 GB of weights — 55s per call.

    Measured before the cache: three clips cost 63.5s / 59.0s / 56.0s.
    After: 60.6s / 1.3s / 1.4s.
    """
    import pixcull.scoring.transcribe as mod

    builds = []

    class _FakeAutoModel:
        def __init__(self, **kw):
            builds.append(kw)

        def generate(self, **kw):
            return [{"key": "k", "text": "好。", "timestamp": [[0, 100]]}]

    fake = types.ModuleType("funasr")
    fake.AutoModel = _FakeAutoModel
    monkeypatch.setitem(sys.modules, "funasr", fake)
    monkeypatch.setattr(mod, "_PARAFORMER_MODEL", None)

    for _ in range(3):
        mod._transcribe_paraformer(pathlib.Path("x.wav"), "zh")
    assert len(builds) == 1, f"model rebuilt {len(builds)} times"


def test_extra_declares_torchaudio_for_funasr():
    """funasr omits torchaudio from its own requirements — we add it.

    Pinned by a test because dropping it re-creates the exact install
    that shipped a crashing engine.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    body = (root / "pyproject.toml").read_text(encoding="utf-8")
    asr = body.split("asr = [", 1)[1].split("]", 1)[0]
    assert "torchaudio" in asr


# ── round-trip ────────────────────────────────────────────────────────

def test_write_then_load_round_trips(tmp_path):
    t = Transcript(
        segments=align_to_shots(
            [Segment(0.4, 2.8, "第一句"), Segment(3.2, 5.6, "second")],
            [3.0]),
        engine=PARAFORMER, language="zh")
    info = write_transcript(t, tmp_path)
    assert info["n_segments"] == 2
    assert (tmp_path / "transcript.json").is_file()
    assert (tmp_path / "transcript.srt").is_file()

    back = load_transcript(tmp_path)
    assert back is not None
    assert back.engine == PARAFORMER and back.language == "zh"
    assert [s.text for s in back.segments] == ["第一句", "second"]
    assert [s.shot_index for s in back.segments] == [0, 1]


def test_load_of_a_run_without_a_transcript_is_none(tmp_path):
    """None, not [] — the panel distinguishes 'never transcribed' from
    'transcribed and silent'."""
    assert load_transcript(tmp_path) is None


def test_load_survives_a_corrupt_transcript(tmp_path):
    (tmp_path / "transcript.json").write_text("{not json", encoding="utf-8")
    assert load_transcript(tmp_path) is None


def test_json_is_utf8_readable(tmp_path):
    write_transcript(Transcript(segments=[Segment(0, 1, "中文字幕")],
                                engine=PARAFORMER, language="zh"), tmp_path)
    d = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
    assert d["segments"][0]["text"] == "中文字幕"
    assert d["schema"] == "pixcull.transcript/v1"


def test_transcript_text_joins_the_lines():
    t = Transcript(segments=[Segment(0, 1, "a"), Segment(1, 2, "b")])
    assert t.text == "a b"


# ── the UI contract ───────────────────────────────────────────────────

def test_video_page_ships_the_transcript_panel():
    from pathlib import Path
    tpl = (Path(__file__).resolve().parent.parent / "pixcull" / "report"
           / "templates" / "video_review.html").read_text("utf-8")
    assert "txList" in tpl and "initTranscript" in tpl
    # Clicking a line must reuse the same seek primitive as the scrubber
    # and the reel list, or a transcript jump lands somewhere else.
    assert "show(nearestFrame(+el.dataset.t))" in tpl
    # …and the clicked line must be the one that lights up: frames are
    # sampled, so the nearest one can precede the line's own start.
    assert "TX_PIN" in tpl


def test_video_payload_includes_transcript_key():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "pixcull" / "report"
           / "serve_app.py").read_text("utf-8")
    assert '"transcript": transcript,' in src
    assert "load_transcript(run_dir)" in src, (
        "the first draft passed a variable that didn't exist and a bare "
        "except swallowed the NameError")


# ==========================================================================
# v2.44 — contextual biasing (hotwords)
# ==========================================================================

def test_builtin_lexicon_is_not_empty():
    """An empty lexicon is indistinguishable from the feature being off.

    That is precisely how this repo's recurring defect looks, so assert
    the file actually parses to terms rather than trusting it exists.
    """
    words = T.load_hotwords()
    assert len(words) > 80, f"lexicon parsed to only {len(words)} terms"
    # Spot-check the three the held-out measurement showed it fixing.
    for w in ("欠曝", "同期声", "畸变"):
        assert w in words, f"{w} missing from the shipped lexicon"


def test_lexicon_skips_comments_and_blanks():
    words = T.load_hotwords()
    assert not any(w.startswith("#") for w in words)
    assert all(w.strip() == w and w for w in words)


def test_caller_hotwords_append_and_dedupe():
    base = T.load_hotwords()
    got = T.load_hotwords(["海淀婚礼堂", "长焦", "", "海淀婚礼堂"])
    assert got[:len(base)] == base, "built-in terms must keep their order"
    assert got.count("海淀婚礼堂") == 1, "duplicates should collapse"
    assert got.count("长焦") == 1, "a caller repeat of a built-in is not new"
    assert "" not in got


def test_lexicon_is_ascii_free_chinese_terms():
    """A stray English word here biases decoding towards nonsense.

    One slipped in while the file was being written; this pins it.
    """
    bad = [w for w in T.load_hotwords() if w.isascii()]
    assert not bad, f"non-Chinese entries in the Mandarin lexicon: {bad}"


def test_missing_lexicon_degrades_to_caller_terms(monkeypatch, tmp_path):
    """Biasing is an improvement, not a requirement."""
    monkeypatch.setattr(T, "_HOTWORDS_FILE", tmp_path / "nope.txt")
    assert T.load_hotwords() == []
    assert T.load_hotwords(["草坪仪式"]) == ["草坪仪式"]


# ==========================================================================
# v2.44.3 — speaker diarization
# ==========================================================================

def test_all_same_speaker_label_becomes_none():
    """FunASR reports "everyone is speaker 0" in two different cases.

    One person really did all the talking, and the clip was too short for
    its clusterer to try (it hard-returns zeros under 20 embeddings,
    before looking at them). The outputs are identical, so recording
    "speaker 0" would assert a finding the model may never have made.
    """
    segs = [Segment(0, 1, "a", speaker="0"), Segment(1, 2, "b", speaker="0")]
    assert [s.speaker for s in T._drop_indistinct_speakers(segs)] == [None,
                                                                      None]


def test_real_speaker_split_is_kept():
    segs = [Segment(0, 1, "a", speaker="0"), Segment(1, 2, "b", speaker="1")]
    assert [s.speaker for s in T._drop_indistinct_speakers(segs)] == ["0", "1"]


def test_unlabelled_segments_stay_unlabelled():
    segs = [Segment(0, 1, "a"), Segment(1, 2, "b")]
    assert [s.speaker for s in T._drop_indistinct_speakers(segs)] == [None,
                                                                      None]


def test_three_speakers_survive():
    segs = [Segment(i, i + 1, "x", speaker=str(i)) for i in range(3)]
    assert [s.speaker for s in T._drop_indistinct_speakers(segs)] == \
           ["0", "1", "2"]


def test_the_funasr_threshold_is_written_down():
    """It is upstream's number and the failure it causes is silent.

    Pinned so that changing it is a deliberate act with a reason, not a
    quiet edit — the value is what the user-facing help text promises.
    """
    assert T._FUNASR_MIN_SPK_EMBEDDINGS == 20


def test_model_cache_is_keyed_by_the_speaker_setting(monkeypatch):
    """Asking for speakers must not hand back the model built without.

    A single cached slot is deliberate — two configurations resident is
    3.2 GB — but it has to notice when the configuration changed.
    """
    built = []

    class _Fake:
        def __init__(self, **kw):
            built.append("spk_model" in kw)

    mod = types.ModuleType("funasr")
    mod.AutoModel = _Fake
    monkeypatch.setitem(sys.modules, "funasr", mod)
    monkeypatch.setattr(T, "_PARAFORMER_MODEL", None)
    monkeypatch.setattr(T, "_PARAFORMER_MODEL_KEY", None)

    T._paraformer_model(False)
    T._paraformer_model(False)          # cached, no rebuild
    T._paraformer_model(True)           # different config, rebuild
    T._paraformer_model(True)           # cached again
    assert built == [False, True]


def test_adapter_actually_applies_the_speaker_guard(monkeypatch, tmp_path):
    """Testing the helper is not testing that anything calls it.

    The first mutation run here stayed green with the call site deleted,
    because every assertion above pokes _drop_indistinct_speakers
    directly. That is the guard-without-a-consumer gap this repo has hit
    before, so this drives the adapter instead.
    """
    class _Fake:
        def generate(self, **kw):
            return [{"sentence_info": [
                {"start": 0, "end": 1000, "text": "一", "spk": 0},
                {"start": 1000, "end": 2000, "text": "二", "spk": 0},
            ]}]

    monkeypatch.setattr(T, "_paraformer_model", lambda speakers=False: _Fake())
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"")

    got = T._transcribe_paraformer(wav, "zh", speakers=True)
    assert [s.speaker for s in got.segments] == [None, None], \
        "adapter did not apply the indistinct-speaker guard"


def test_adapter_keeps_a_real_split(monkeypatch, tmp_path):
    class _Fake:
        def generate(self, **kw):
            return [{"sentence_info": [
                {"start": 0, "end": 1000, "text": "一", "spk": 0},
                {"start": 1000, "end": 2000, "text": "二", "spk": 1},
            ]}]

    monkeypatch.setattr(T, "_paraformer_model", lambda speakers=False: _Fake())
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"")
    got = T._transcribe_paraformer(wav, "zh", speakers=True)
    assert [s.speaker for s in got.segments] == ["0", "1"]


def test_speakers_off_leaves_labels_untouched(monkeypatch, tmp_path):
    """Without --speakers the guard must not run at all.

    Nothing sets spk in that mode, but blanking labels the caller never
    asked about would hide a future engine that supplies them.
    """
    class _Fake:
        def generate(self, **kw):
            return [{"sentence_info": [
                {"start": 0, "end": 1000, "text": "一", "spk": 7},
            ]}]

    monkeypatch.setattr(T, "_paraformer_model", lambda speakers=False: _Fake())
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"")
    got = T._transcribe_paraformer(wav, "zh", speakers=False)
    assert got.segments[0].speaker == "7"


# ── v2.48 — --speakers must not disable word-level editing ────────────
#
# Two features that could not be used together, with nothing saying so.
# The tier-1 branch (the one that runs when a speaker model is attached)
# built Segments without char_spans, so EditSession correctly reported
# "segment only" — and the word-level UI silently went away the moment a
# user asked for diarization.
#
# The data was there all along: sentence_info entries carry `timestamp`,
# the same [start_ms, end_ms] per-character pairs tier 2 already maps.

def _fake_paraformer(monkeypatch, raw):
    """Stand in for the 1.6 GB model; returns a scripted generate()."""
    class _M:
        def generate(self, **kw):
            self.kw = kw
            return raw
    m = _M()
    monkeypatch.setattr(T, "_paraformer_model", lambda speakers: m)
    return m


def _sentence(text, ts, spk, start, end):
    return {"text": text, "timestamp": ts, "spk": spk,
            "start": start, "end": end}


def test_speaker_branch_carries_char_spans(monkeypatch, tmp_path):
    """The regression itself: --speakers used to cost word-level cuts."""
    text = "今天我们在这里拍摄婚礼"
    ts = _REAL_TS[:len(text)]
    _fake_paraformer(monkeypatch, [{"sentence_info": [
        _sentence(text, ts, 0, 110, 2350)]}])
    tr = T._transcribe_paraformer(tmp_path / "a.wav", speakers=True)
    assert len(tr.segments) == 1
    seg = tr.segments[0]
    # NB the speaker label is None here, not "0": with a single label
    # across the whole clip, _drop_indistinct_speakers nulls it because
    # FunASR's clusterer reports "everyone is speaker 0" both when that
    # is true and when it had too little audio to tell (v2.44.3). That
    # is unrelated to the times, which is what this test is about.
    assert seg.char_spans, "speaker branch dropped the per-character times"
    assert len(seg.char_spans) == len(text)


def test_speakers_still_allows_word_level_editing(monkeypatch, tmp_path):
    """End of the chain — what the user actually loses or keeps."""
    from pixcull.scoring.edit_model import EditSession
    text = "今天我们在这里拍摄婚礼"
    _fake_paraformer(monkeypatch, [{"sentence_info": [
        _sentence(text, _REAL_TS[:len(text)], 0, 110, 2350)]}])
    tr = T._transcribe_paraformer(tmp_path / "a.wav", speakers=True)
    assert EditSession(tr).precision == "word", (
        "turning on diarization must not turn off word-level editing")


def test_speaker_labels_are_still_carried(monkeypatch, tmp_path):
    """The fix must not cost the feature the branch exists for."""
    _fake_paraformer(monkeypatch, [{"sentence_info": [
        _sentence("你好", _REAL_TS[:2], 0, 110, 450),
        _sentence("再见", _REAL_TS[2:4], 1, 530, 830)]}])
    tr = T._transcribe_paraformer(tmp_path / "a.wav", speakers=True)
    assert [s.speaker for s in tr.segments] == ["0", "1"]


def test_speaker_branch_degrades_when_times_do_not_line_up(monkeypatch,
                                                           tmp_path):
    """Mixed zh/en emits one span per WORD, so the per-char map breaks.

    Guessing an alignment would cut on the wrong frames. Falling back to
    segment precision is the honest answer, and it must not raise.
    """
    _fake_paraformer(monkeypatch, [{"sentence_info": [
        _sentence("hello 世界 everyone", [[0, 100], [100, 200]], 0, 0, 2000)]}])
    tr = T._transcribe_paraformer(tmp_path / "a.wav", speakers=True)
    assert tr.segments[0].char_spans is None
    assert tr.segments[0].text == "hello 世界 everyone"


def test_speaker_branch_survives_a_missing_timestamp_key(monkeypatch,
                                                         tmp_path):
    """Not every FunASR build emits `timestamp` inside sentence_info."""
    _fake_paraformer(monkeypatch, [{"sentence_info": [
        {"text": "你好", "spk": 0, "start": 0, "end": 500}]}])
    tr = T._transcribe_paraformer(tmp_path / "a.wav", speakers=True)
    assert tr.segments[0].char_spans is None
    assert tr.segments[0].start_s == 0.0


def test_speaker_branch_refuses_partial_spans_when_the_sentence_splits(
        monkeypatch, tmp_path):
    """The guard's real job — and the one a survivor mutation exposed.

    sentence_info gives ONE record per sentence, but the tier-2 mapper
    splits on punctuation and can return several. Taking ``derived[0]``'s
    spans would apply the FIRST clause's timeline to the WHOLE sentence:
    every span after the comma would point at the wrong audio, and a
    word-level cut would land on the wrong frames while still looking
    perfectly well-formed.

    Degrading to segment precision is the honest answer. A first pass of
    this test only covered the count-mismatch case, where the mapper
    already returns char_spans=None — so dropping the guard entirely
    changed nothing observable and the mutation survived.
    """
    assert len(segments_from_char_timestamps(_REAL_TEXT, _REAL_TS)) > 1, (
        "fixture no longer splits — this test would prove nothing")
    _fake_paraformer(monkeypatch, [{"sentence_info": [
        _sentence(_REAL_TEXT, _REAL_TS, 0, 110, 6535)]}])
    tr = T._transcribe_paraformer(tmp_path / "a.wav", speakers=True)
    assert len(tr.segments) == 1
    assert tr.segments[0].char_spans is None, (
        "a multi-clause sentence must not inherit clause 1's timeline")
