# Ground truth — what exists, audited 2026-08-31

The roadmap planned to publish an accuracy figure from "the 608-row correction
set". This is the audit of what that set actually contains.

## The finding

**There are no human labels on this machine.**

| file | records | provenance |
|---|---|---|
| `pixcull_label_run/*/output/rubric.jsonl` | 415 | `source: "auto"` |
| `runs/*/output/vlm_verdicts.jsonl` | 1,114 | carry `model_name` |
| `runs/*/output/meta_verdicts.jsonl` | 1,114 | carry `model_name` |
| **human-produced** | **0** | |

The 415 rubric records match `scores.csv` exactly — 369 keep, 29 cull, 17 maybe
on both sides — because they *are* `scores.csv`, written back out.

Measured with the guard disabled, agreement between the model and that "truth"
is **100.0%**. The number is the proof of circularity, not a result.

## Why this matters more than a missing file

A missing correction set is obvious the moment someone looks for it. A correction
set full of the model's own output is not: the arithmetic runs, nothing errors,
and a plausible figure comes out. On a subtly different comparison — a changed
threshold, a new fusion weight — it would come out at 94% instead of 100% and
look like a real measurement.

Every published accuracy claim in this space is vendor-reported. PixCull's
advantage was supposed to be that its number came with a disclosed method. A
number derived this way would have been worse than having none, because the
method would have been disclosed and still wrong.

## The guard

`pixcull/scoring/ground_truth.py` refuses. `accuracy()` raises
`CircularMeasurement` unless the truth records are attested human, and the
message names the provenance it found.

Provenance is never assumed upward. A record with no `source` field is
`unknown`, not `human` — every model verdict on this machine lacks that field,
so the generous reading would convert 2,228 model verdicts into a ground truth.

The signature takes the raw records rather than a `filename -> label` mapping,
so provenance can be checked here instead of trusted from the caller. A mapping
would make the check impossible, and a test pins the shape.

## What unblocks it

A sample of photographs labelled by a person, with `source` set, before they see
the model's verdict. That is the whole requirement. Three versions wait on it:

- **v2.88** the accuracy baseline, this one
- **v2.89** the keep/maybe boundary, which is unidentifiable to any metric until
  real reclassifications exist
- **v2.80** the blind advice evaluation, which needs raters who are working
  photographers and not the author

The harnesses and the refusals for all three are built. The labels are not
something an agent can produce, and producing them synthetically would recreate
exactly the defect this version exists to prevent.
