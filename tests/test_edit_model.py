"""v2.44 — the edit-by-text state model.

Pure arithmetic over (start, end) pairs, so it is tested exhaustively
with no engine, no ffmpeg and no browser.
"""

from __future__ import annotations

import pytest

from pixcull.scoring.edit_model import (
    EditError, EditSession, Op, Span, merge_spans, subtract,
)
from pixcull.scoring.transcribe import Segment, Transcript


def _seg(a, b, text, spans=None):
    return Segment(a, b, text, char_spans=spans)


def _worded() -> Transcript:
    """Two lines with real per-character times (the Paraformer shape).

    "今天拍婚礼" over 0.0–1.0, one character each 0.2s.
    "灯光准备好" over 2.0–3.0, likewise.
    """
    s1 = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    s2 = [(2.0, 2.2), (2.2, 2.4), (2.4, 2.6), (2.6, 2.8), (2.8, 3.0)]
    return Transcript(segments=[_seg(0.0, 1.0, "今天拍婚礼", s1),
                                _seg(2.0, 3.0, "灯光准备好", s2)],
                      engine="paraformer", language="zh")


def _segment_only() -> Transcript:
    return Transcript(segments=[_seg(0.0, 1.0, "today we shoot"),
                                _seg(2.0, 3.0, "lights ready")],
                      engine="whisper", language="en")


# ── span arithmetic ───────────────────────────────────────────────────

def test_span_rejects_reversed():
    with pytest.raises(EditError):
        Span(2.0, 1.0)


def test_merge_joins_touching_and_sorts():
    got = merge_spans([Span(1.0, 2.0), Span(0.0, 0.5), Span(2.0, 3.0)])
    assert [(s.start, s.end) for s in got] == [(0.0, 0.5), (1.0, 3.0)]


def test_merge_drops_zero_length():
    assert merge_spans([Span(1.0, 1.0)]) == []


def test_subtract_punches_a_hole():
    got = subtract([Span(0.0, 10.0)], [Span(3.0, 4.0)])
    assert [(s.start, s.end) for s in got] == [(0.0, 3.0), (4.0, 10.0)]


def test_subtract_whole_span_leaves_nothing():
    assert subtract([Span(0.0, 5.0)], [Span(0.0, 5.0)]) == []


def test_subtract_ignores_non_overlapping():
    got = subtract([Span(0.0, 1.0)], [Span(5.0, 6.0)])
    assert [(s.start, s.end) for s in got] == [(0.0, 1.0)]


def test_subtract_drops_subframe_slivers():
    """A 10ms remainder is not a clip; it is a glitch in the render."""
    got = subtract([Span(0.0, 1.0)], [Span(0.01, 1.0)])
    assert got == []


# ── capability reporting ──────────────────────────────────────────────

def test_precision_is_word_when_every_segment_has_spans():
    assert EditSession(_worded()).precision == "word"


def test_precision_is_segment_without_spans():
    assert EditSession(_segment_only()).precision == "segment"


def test_precision_is_segment_when_only_some_have_spans():
    """Mixed data must not advertise a word-level UI.

    It would work on one line and mislead on the next, which is worse
    than not offering it at all.
    """
    t = _worded()
    t.segments.append(_seg(4.0, 5.0, "没有时间戳"))
    assert EditSession(t).precision == "segment"


# ── deleting ──────────────────────────────────────────────────────────

def test_source_defaults_to_the_spoken_spans():
    s = EditSession(_worded())
    assert [(x.start, x.end) for x in s.source_spans] == [(0.0, 1.0), (2.0, 3.0)]
    assert s.duration() == pytest.approx(2.0)


def test_delete_segment_removes_its_time_and_its_text():
    s = EditSession(_worded())
    s.delete_segment(0)
    assert [(x.start, x.end) for x in s.kept_spans()] == [(2.0, 3.0)]
    assert s.kept_text() == "灯光准备好"


def test_delete_chars_cuts_on_real_times():
    s = EditSession(_worded())
    s.delete_chars(0, 2, 4)          # 拍婚礼 -> 0.4..1.0
    assert [(x.start, x.end) for x in s.kept_spans()] == [(0.0, 0.4),
                                                          (2.0, 3.0)]
    assert s.kept_text() == "今天 灯光准备好"


def test_delete_chars_refuses_without_char_times():
    """The whole point: no interpolation."""
    s = EditSession(_segment_only())
    with pytest.raises(EditError, match="per-character"):
        s.delete_chars(0, 1, 2)


def test_delete_chars_out_of_range_is_an_error():
    s = EditSession(_worded())
    with pytest.raises(EditError, match="outside segment"):
        s.delete_chars(0, 0, 99)


def test_delete_segment_out_of_range():
    with pytest.raises(EditError, match="no segment"):
        EditSession(_worded()).delete_segment(7)


def test_partially_cut_segment_without_spans_loses_all_its_text():
    """Showing text the video no longer contains is the worse failure."""
    s = EditSession(_segment_only())
    s.delete_spans([Span(0.2, 0.4)])
    assert s.kept_text() == "lights ready"


# ── history ───────────────────────────────────────────────────────────

def test_undo_restores_exactly():
    s = EditSession(_worded())
    before = s.duration()
    s.delete_segment(0)
    assert s.undo() is True
    assert s.duration() == pytest.approx(before)
    assert s.kept_text() == "今天拍婚礼 灯光准备好"


def test_redo_reapplies():
    s = EditSession(_worded())
    s.delete_segment(0)
    s.undo()
    assert s.redo() is True
    assert s.kept_text() == "灯光准备好"


def test_new_edit_discards_the_redo_branch():
    s = EditSession(_worded())
    s.delete_segment(0)
    s.undo()
    s.delete_segment(1)
    assert s.can_redo is False, "a new branch must not leave a stale redo"


def test_undo_on_empty_history_is_false_not_an_error():
    assert EditSession(_worded()).undo() is False


def test_noop_delete_does_not_enter_history():
    s = EditSession(_worded())
    s.delete_spans([])
    assert s.can_undo is False


def test_restore_undoes_part_of_a_delete():
    s = EditSession(_worded())
    s.delete_spans([Span(0.0, 1.0)])
    s.restore_spans([Span(0.0, 0.4)])
    assert [(x.start, x.end) for x in s.kept_spans()] == [(0.0, 0.4),
                                                          (2.0, 3.0)]


def test_deleted_is_recomputed_not_accumulated():
    """Replaying the log is what keeps undo honest."""
    s = EditSession(_worded())
    s.delete_segment(0)
    s.delete_segment(1)
    s.undo()
    assert [(x.start, x.end) for x in s.deleted()] == [(0.0, 1.0)]


# ── export ────────────────────────────────────────────────────────────

def test_to_clips_feeds_the_existing_assembly_types():
    from pixcull.io.reel_assembly import Clip, build_edl

    s = EditSession(_worded())
    s.delete_segment(0)
    clips = s.to_clips()
    assert clips and all(isinstance(c, Clip) for c in clips)
    edl = build_edl(clips, "shoot.mp4", 25.0)
    assert "TITLE:" in edl and "shoot.mp4" in edl


def test_roundtrip_preserves_the_edit():
    s = EditSession(_worded())
    s.delete_chars(0, 0, 1)
    back = EditSession.from_dict(s.to_dict(), _worded())
    assert back.kept_text() == s.kept_text()
    assert [(x.start, x.end) for x in back.kept_spans()] == \
           [(x.start, x.end) for x in s.kept_spans()]


def test_roundtrip_keeps_undo_working():
    s = EditSession(_worded())
    s.delete_segment(0)
    back = EditSession.from_dict(s.to_dict(), _worded())
    assert back.can_undo is True
    back.undo()
    assert back.kept_text() == "今天拍婚礼 灯光准备好"


def test_unknown_schema_is_refused():
    with pytest.raises(EditError, match="schema"):
        EditSession.from_dict({"schema": "pixcull.edit/v99"}, _worded())


def test_op_roundtrip():
    o = Op("delete", [Span(1.0, 2.0)], "今天")
    assert Op.from_dict(o.to_dict()).to_dict() == o.to_dict()


# ── persistence ───────────────────────────────────────────────────────

def test_char_spans_survive_a_disk_roundtrip(tmp_path):
    """Word-level editing must not depend on staying in memory.

    Caught by the CLI journey, not by any unit test here: writing and
    reloading the very same transcript silently downgraded the session
    from word-level to segment-level, because load_transcript dropped the
    field. Every in-memory test still passed.
    """
    from pixcull.scoring.transcribe import load_transcript, write_transcript

    write_transcript(_worded(), tmp_path)
    back = load_transcript(tmp_path)
    assert back is not None
    assert EditSession(back).precision == "word"
    assert back.segments[0].char_spans == _worded().segments[0].char_spans


def test_reloaded_char_spans_are_tuples_not_lists(tmp_path):
    """JSON has no tuple; an unconverted load changes the type."""
    from pixcull.scoring.transcribe import load_transcript, write_transcript

    write_transcript(_worded(), tmp_path)
    spans = load_transcript(tmp_path).segments[0].char_spans
    assert all(isinstance(p, tuple) for p in spans)


def test_reloaded_transcript_cuts_at_the_same_times(tmp_path):
    from pixcull.scoring.transcribe import load_transcript, write_transcript

    live = EditSession(_worded())
    live.delete_chars(0, 2, 4)

    write_transcript(_worded(), tmp_path)
    reloaded = EditSession(load_transcript(tmp_path))
    reloaded.delete_chars(0, 2, 4)

    assert [(s.start, s.end) for s in reloaded.kept_spans()] == \
           [(s.start, s.end) for s in live.kept_spans()]
    assert reloaded.kept_text() == live.kept_text()


def test_transcript_without_char_spans_still_loads(tmp_path):
    """Whisper transcripts predate the field; they must keep working."""
    from pixcull.scoring.transcribe import load_transcript, write_transcript

    write_transcript(_segment_only(), tmp_path)
    back = load_transcript(tmp_path)
    assert back.segments[0].char_spans is None
    assert EditSession(back).precision == "segment"
