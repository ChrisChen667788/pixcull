"""v2.43 — transcription: SRT, shot alignment, and honest failure.

DESIGN-AUDIT-2031Q1 recommendation ④. Before this, grep for ASR /
subtitle / transcript across the codebase returned nothing.

Everything here runs with NO engine installed. That is the design: ASR
backends are enormous (FunASR declares 71 dependencies) so the model
lives behind an extra, while the parts that decide how a transcript
*behaves* — timing, SRT formatting, shot alignment — are pure functions.
"""

import json

import pytest

from pixcull.scoring.transcribe import (
    PARAFORMER, WHISPER, Segment, Transcript, TranscriptionUnavailable,
    align_to_shots, available_engines, load_transcript, resolve_engine,
    to_srt, write_transcript, _srt_timestamp,
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
