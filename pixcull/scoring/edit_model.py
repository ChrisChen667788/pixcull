"""v2.44 — edit by text: delete words, get a cut.

The transcript surfaces (v2.43) let a photographer *find* the line they
want.  This is what turns finding into cutting: strike text, and the
matching stretch of video goes away.

Design
------
**The source is never modified.**  An edit is a set of deleted spans
layered over an immutable transcript, and everything the caller asks for
— what text remains, what video remains, an EDL — is *derived* from that
set.  The alternative (mutating a working copy of the segments) needs the
kept-spans and the visible text kept in step by hand, and every undo is
another chance for them to drift apart.

**Operations are logged, not snapshotted.**  Undo pops the log and the
state is recomputed.  For a transcript this is cheap, and it means undo
cannot restore a state that no sequence of operations could produce.

**Granularity follows the data, and says so.**  Paraformer reports a real
time span per character, so a word-level cut lands on real times
(``Segment.char_spans``, added in v2.44).  Whisper reports segment times
only.  Rather than interpolate inside a segment — which invents precision
the model never gave and puts cuts on the wrong frames — a request to cut
part of a span-less segment is refused, and :attr:`EditSession.precision`
tells the UI which mode it is in so it can offer word selection or not.

Nothing here imports a model, ffmpeg or a web framework: the whole thing
is arithmetic over ``(start, end)`` pairs, which is why it can be tested
exhaustively without weights.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Iterable, Literal, Sequence

from pixcull.scoring.transcribe import Segment, Transcript

logger = logging.getLogger(__name__)

# Cuts closer together than this are merged: a sub-frame gap produces a
# zero-length clip that ffmpeg and most NLEs either drop or choke on.
MIN_GAP_S = 0.04            # ~1 frame at 25fps

Precision = Literal["word", "segment"]


class EditError(ValueError):
    """A requested edit cannot be honoured exactly.

    Raised rather than approximated: silently cutting somewhere near
    where the user pointed is worse than saying the data does not
    support it.
    """


@dataclass(frozen=True)
class Span:
    """A half-open time range ``[start, end)`` on the source timeline."""

    start: float
    end: float

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise EditError(f"span ends before it starts: {self}")

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass
class Op:
    """One user action, replayable."""

    kind: Literal["delete", "restore"]
    spans: list[Span]
    label: str = ""          # what the UI showed, for an undo menu

    def to_dict(self) -> dict:
        return {"kind": self.kind, "label": self.label,
                "spans": [[s.start, s.end] for s in self.spans]}

    @classmethod
    def from_dict(cls, d: dict) -> "Op":
        return cls(kind=d["kind"],
                   spans=[Span(float(a), float(b)) for a, b in d["spans"]],
                   label=d.get("label", ""))


def merge_spans(spans: Iterable[Span], *, min_gap: float = MIN_GAP_S) -> list[Span]:
    """Union of spans, with near-touching ones joined."""
    ordered = sorted((s for s in spans if s.duration > 0),
                     key=lambda s: (s.start, s.end))
    out: list[Span] = []
    for s in ordered:
        if out and s.start - out[-1].end <= min_gap:
            if s.end > out[-1].end:
                out[-1] = Span(out[-1].start, s.end)
        else:
            out.append(s)
    return out


def subtract(base: Sequence[Span], holes: Sequence[Span]) -> list[Span]:
    """``base`` minus ``holes`` — what survives the cuts."""
    cuts = merge_spans(holes)
    out: list[Span] = []
    for b in base:
        cursor = b.start
        for h in cuts:
            if h.end <= cursor or h.start >= b.end:
                continue
            if h.start > cursor:
                out.append(Span(cursor, min(h.start, b.end)))
            cursor = max(cursor, h.end)
            if cursor >= b.end:
                break
        if cursor < b.end:
            out.append(Span(cursor, b.end))
    return [s for s in out if s.duration > MIN_GAP_S]


@dataclass
class EditSession:
    """A transcript plus the edits made to it.

    ``source_spans`` is the material available to cut from — by default
    the union of the transcript's segments, so silence between lines is
    already excluded.
    """

    transcript: Transcript
    source_spans: list[Span] = field(default_factory=list)
    ops: list[Op] = field(default_factory=list)
    _redo: list[Op] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if not self.source_spans:
            self.source_spans = merge_spans(
                Span(s.start_s, s.end_s) for s in self.transcript.segments
                if s.end_s > s.start_s)

    # ── capability ────────────────────────────────────────────────────

    @property
    def precision(self) -> Precision:
        """Finest cut this transcript actually supports.

        ``"word"`` only when every segment carries per-character times;
        one segment without them means a word-level UI would work in some
        places and mislead in others, which is worse than not offering it.
        """
        segs = self.transcript.segments
        if segs and all(s.char_spans for s in segs):
            return "word"
        return "segment"

    # ── queries ───────────────────────────────────────────────────────

    def deleted(self) -> list[Span]:
        """Net deletions after replaying the log."""
        cur: list[Span] = []
        for op in self.ops:
            if op.kind == "delete":
                cur = merge_spans(cur + op.spans)
            else:
                cur = subtract(cur, op.spans)
        return cur

    def kept_spans(self) -> list[Span]:
        """What remains, in source order."""
        return subtract(self.source_spans, self.deleted())

    def duration(self) -> float:
        return sum(s.duration for s in self.kept_spans())

    def kept_text(self) -> str:
        """The transcript as it now reads.

        A segment is dropped when its whole span is gone; a partially cut
        segment keeps the characters whose own spans survive, which is
        what makes the text panel agree with the video.
        """
        gone = self.deleted()
        parts: list[str] = []
        for seg in self.transcript.segments:
            keep = self._surviving_text(seg, gone)
            if keep:
                parts.append(keep)
        return " ".join(parts).strip()

    @staticmethod
    def _surviving_text(seg: Segment, gone: Sequence[Span]) -> str:
        span = Span(seg.start_s, seg.end_s)
        if not any(span.overlaps(g) for g in gone):
            return seg.text
        if not seg.char_spans:
            # No per-character times: the segment is all-or-nothing, and
            # any overlap at all removes it. Keeping it would show text
            # the video no longer contains.
            return ""
        out, ci = [], 0
        for ch in seg.text:
            if _is_punct(ch):
                out.append(ch)
                continue
            pair = seg.char_time(ci)
            ci += 1
            if pair is None:
                continue
            c = Span(*pair)
            if not any(c.overlaps(g) for g in gone):
                out.append(ch)
        return "".join(out).strip(" ，,。.！!？?、；;：:")

    # ── editing ───────────────────────────────────────────────────────

    def delete_spans(self, spans: Sequence[Span], *, label: str = "") -> None:
        self._apply(Op("delete", merge_spans(spans), label))

    def restore_spans(self, spans: Sequence[Span], *, label: str = "") -> None:
        self._apply(Op("restore", merge_spans(spans), label))

    def delete_segment(self, index: int) -> None:
        """Strike a whole transcript line."""
        try:
            seg = self.transcript.segments[index]
        except IndexError:
            raise EditError(f"no segment {index}") from None
        self.delete_spans([Span(seg.start_s, seg.end_s)],
                          label=seg.text[:24])

    def delete_chars(self, index: int, first: int, last: int) -> None:
        """Strike characters ``[first, last]`` of segment ``index``.

        Indices count non-punctuation characters, matching ``char_spans``.
        Refuses when the segment has no per-character times rather than
        interpolating a plausible-looking cut.
        """
        try:
            seg = self.transcript.segments[index]
        except IndexError:
            raise EditError(f"no segment {index}") from None
        if not seg.char_spans:
            raise EditError(
                f"segment {index} has no per-character times "
                f"(engine {self.transcript.engine!r}); delete the whole "
                "line instead")
        if first > last:
            raise EditError(f"empty character range {first}..{last}")
        a, b = seg.char_time(first), seg.char_time(last)
        if a is None or b is None:
            raise EditError(
                f"characters {first}..{last} outside segment {index} "
                f"({len(seg.char_spans)} characters)")
        self.delete_spans([Span(a[0], b[1])],
                          label="".join(_body(seg.text)[first:last + 1])[:24])

    # ── history ───────────────────────────────────────────────────────

    def _apply(self, op: Op) -> None:
        if not op.spans:
            return                       # a no-op should not enter history
        self.ops.append(op)
        self._redo.clear()               # a new branch discards the old one

    @property
    def can_undo(self) -> bool:
        return bool(self.ops)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self.ops:
            return False
        self._redo.append(self.ops.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self.ops.append(self._redo.pop())
        return True

    # ── export ────────────────────────────────────────────────────────

    def to_clips(self) -> list:
        """Kept spans as ``reel_assembly.Clip`` — feeds the existing EDL,
        ffmpeg montage and export presets rather than a parallel path."""
        from pixcull.io.reel_assembly import Clip
        return [Clip(start_s=s.start, end_s=s.end, rank=i)
                for i, s in enumerate(self.kept_spans())]

    def to_dict(self) -> dict:
        return {"schema": "pixcull.edit/v1",
                "precision": self.precision,
                "source": [[s.start, s.end] for s in self.source_spans],
                "ops": [o.to_dict() for o in self.ops]}

    @classmethod
    def from_dict(cls, d: dict, transcript: Transcript) -> "EditSession":
        got = d.get("schema")
        if got and got != "pixcull.edit/v1":
            raise EditError(f"unknown edit schema {got!r}")
        return cls(transcript=transcript,
                   source_spans=[Span(float(a), float(b))
                                 for a, b in d.get("source", [])],
                   ops=[Op.from_dict(o) for o in d.get("ops", [])])

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=1)


_PUNCT = "，,。.！!？?、；;：: \t\n"


def _is_punct(ch: str) -> bool:
    return ch in _PUNCT


def _body(text: str) -> list[str]:
    """Non-punctuation characters, i.e. the ones ``char_spans`` indexes."""
    return [c for c in text if not _is_punct(c)]
