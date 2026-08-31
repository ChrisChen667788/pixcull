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

    @property
    def human(self) -> int:
        return self.counts["human"]

    @property
    def usable_for_accuracy(self) -> bool:
        return self.human > 0

    def summary(self) -> str:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items()))
        return f"{sum(self.counts.values())} labels ({parts})"


def audit_labels(paths) -> LabelInventory:
    """Count label records by provenance across JSONL files."""
    inv = LabelInventory()
    for p in paths:
        p = Path(p)
        if not p.is_file():
            continue
        local: Counter = Counter()
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if "overall_label" not in rec and "decision" not in rec:
                continue
            local[label_provenance(rec)] += 1
        if local:
            inv.by_file[str(p)] = local
            inv.counts.update(local)
    return inv


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
    human = [r for r in truth_records if label_provenance(r) == "human"]
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
