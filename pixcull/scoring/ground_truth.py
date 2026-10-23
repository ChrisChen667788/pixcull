"""v2.88 — refuse to measure accuracy against the model's own output.

Auditing this machine for the "608-row correction set" the roadmap
planned to publish an accuracy figure from turned up something worse
than a missing file. The labels are there. They are the model's.

  ~/pixcull_label_run/*/output/rubric.jsonl   415 records, source="auto"
  runs/*/output/vlm_verdicts.jsonl           1,114 records, carry model_name
  runs/*/output/meta_verdicts.jsonl          1,114 records, carry model_name

Human-produced labels on this machine: zero.

The 415 rubric records match `scores.csv` exactly — 369 keep, 29 cull,
17 maybe on both sides — because they ARE scores.csv, written back out.
An accuracy computed from them is the model agreeing with itself, and it
comes out at 100%. Nobody would have published that on purpose; the
danger is that the arithmetic runs without complaint and produces a
plausible number for a subtly different comparison.

So this module makes the circular measurement fail rather than trusting
anyone to notice. `accuracy()` refuses unless the truth labels are
attested human, and the refusal says which file and why.

WHAT COUNTS AS HUMAN. A record is human-labelled only if it says so:
`source` is one of HUMAN_SOURCES, or a human identifier is present. A
record with no provenance at all is NOT assumed human — that assumption
is exactly how a model's output becomes a ground truth two versions
later, and every model verdict on this machine would qualify under it.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

HUMAN_SOURCES = frozenset({"human", "owner", "photographer", "rater",
                           "manual", "ui", "annotation"})
MODEL_MARKERS = ("model_name", "elapsed_s", "raw_text")


def label_provenance(rec: dict) -> str:
    """"human", "model", or "unknown". Never guesses upward."""
    if not isinstance(rec, dict):
        return "unknown"
    src = str(rec.get("source") or "").strip().lower()
    if src in HUMAN_SOURCES:
        return "human"
    if src in ("auto", "model", "vlm", "meta", "rule", "pipeline"):
        return "model"
    if any(k in rec for k in MODEL_MARKERS):
        return "model"
    if rec.get("rater") or rec.get("annotator") or rec.get("user"):
        return "human"
    return "unknown"


@dataclass
class LabelInventory:
    counts: Counter = field(default_factory=Counter)
    by_file: dict[str, Counter] = field(default_factory=dict)
    #: path -> why it contributed nothing. Without it a file the audit
    #: could not read and a file it read and found clean look the same.
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def human(self) -> int:
        return self.counts["human"]

    @property
    def usable_for_accuracy(self) -> bool:
        return self.human > 0

    def summary(self) -> str:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items()))
        out = f"{sum(self.counts.values())} labels ({parts})"
        if self.skipped:
            out += f"; {len(self.skipped)} file(s) contributed none"
        return out


def audit_labels(paths) -> LabelInventory:
    """Count label records by provenance across label files.

    Reads both shapes this project writes: JSONL, one record per line
    (annotations, client picks, rubric dumps), and the single object
    `pixcull m3 label` saves, whose `verdicts` map goes through the same
    conversion as `load_blind_sheet`, so `source` comes from the file.

    v3.95 — it used to read JSONL only. Handed the blind sheet, the one
    tool that produces human labels, it found no record on any line and
    returned an empty inventory, which reads exactly like "audited,
    nothing wrong". A file that contributes nothing is now listed in
    `skipped` with the reason.
    """
    inv = LabelInventory()
    for p in paths:
        p = Path(p)
        if not p.is_file():
            inv.skipped[str(p)] = "not a file"
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            inv.skipped[str(p)] = f"unreadable: {exc}"
            continue
        doc = _whole_document(text)
        # A one-line JSONL file parses as one object too. If it carries a
        # label of its own it is a record, whatever other keys it has.
        records = (None if isinstance(doc, dict) and _label_of(doc)
                   else _blind_sheet_records(doc))
        if records is None:
            records = []
            for line in text.splitlines():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        local: Counter = Counter()
        for rec in records:
            # The key being present is not a label: a sheet saves an
            # unanswered photograph as null, and counting it made a sheet
            # of nulls "usable" while accuracy() then measured nothing.
            if not _label_of(rec):
                continue
            local[label_provenance(rec)] += 1
        if local:
            inv.by_file[str(p)] = local
            inv.counts.update(local)
        else:
            inv.skipped[str(p)] = "no label records"
    return inv


def _label_of(rec) -> str:
    """The label a record carries, read the way accuracy() reads it, or ""."""
    if not isinstance(rec, dict):
        return ""
    label = rec.get("overall_label") or rec.get("decision")
    return label.strip() if isinstance(label, str) else ""


def _whole_document(text: str):
    """The file parsed as one JSON value, or None if it is not one (JSONL
    with more than one line is not)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _blind_sheet_records(doc) -> list[dict] | None:
    """Label records from a parsed blind sheet; None if `doc` is not one.

    A sheet is an object carrying `verdicts`. One whose `verdicts` is the
    wrong type is still a sheet, with no usable records in it."""
    if not isinstance(doc, dict) or "verdicts" not in doc:
        return None
    verdicts = doc["verdicts"]
    if not isinstance(verdicts, dict):
        return []
    src = doc.get("source")
    out = []
    for fn, label in verdicts.items():
        rec = {"filename": fn, "overall_label": label,
               "selection": doc.get("selection"),
               "reviewed_at": doc.get("reviewed_at")}
        if src:
            rec["source"] = src
        out.append(rec)
    return out


def load_blind_sheet(path) -> list[dict]:
    """Read what `pixcull m3 label` saved into label records.

    v2.94 — the blind sheet writes one object with a `verdicts` map, not
    one record per photograph, so `audit_labels` saw a file with no label
    records in it at all. The provenance guard and the only tool that
    produces legitimate human labels could not talk to each other.

    `source` is taken from the FILE, never assumed. A sheet saved before
    v2.94 has no such field and its rows come back "unknown", which is
    the correct answer: nothing in that file says a person made it, and
    this module's whole job is to stop that being assumed.
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    return _blind_sheet_records(doc) or []


class CircularMeasurement(RuntimeError):
    """Raised when the 'truth' being measured against is model output."""


def accuracy(predictions: dict[str, str], truth_records: list[dict], *,
             strict: bool = True) -> dict:
    """Agreement between predictions and HUMAN labels.

    ``truth_records`` are the raw label records, not a stripped mapping,
    so provenance can be checked here rather than trusted from the
    caller. Passing a plain dict of filename->label would make the check
    impossible, which is why the signature is shaped this way.
    """
    prov = Counter(label_provenance(r) for r in truth_records)
    # v3.95 — a human record with no label in it is not a human label. A
    # blind sheet saves an unanswered photograph as null; a sheet of those
    # used to pass this guard and come back as n=0, agreement 0.0.
    human = [r for r in truth_records
             if label_provenance(r) == "human" and _label_of(r)]
    if strict and not human:
        raise CircularMeasurement(
            "no human-labelled records in the truth set "
            f"({dict(prov)}). Measuring against model output reports the "
            "model agreeing with itself. Label a sample by hand first.")

    use = human if strict else truth_records
    n = agree = 0
    confusion: Counter = Counter()
    for r in use:
        fn = r.get("filename")
        t = r.get("overall_label") or r.get("decision")
        if not fn or not t or fn not in predictions:
            continue
        n += 1
        p = predictions[fn]
        confusion[(t, p)] += 1
        if p == t:
            agree += 1
    return {
        "n": n,
        "agreement": (agree / n) if n else 0.0,
        "provenance": dict(prov),
        "confusion": {f"{t}->{p}": c for (t, p), c in confusion.items()},
        "strict": strict,
    }
