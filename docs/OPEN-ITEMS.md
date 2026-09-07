# What is still open, and who it is waiting on

Written 2026-09-08, before starting the next block. Two blocks of work have
closed since the last time anyone counted, and the open items were spread across
three documents in two different shapes. This page is the count.

**Sixteen versions are nominally open. They are four requests.** Every one of
them is waiting on a person, and the harness for each is built — the work left
is not engineering.

---

## The four asks

### 1. One API spend ceiling — unblocks 8 measurements

v2.91, v3.3, v3.4, v3.5, v3.6, v3.11, v3.17, v3.18.

All eight wait on the same decision. `pixcull/scoring/measurement_plan.py`
estimates the whole block, refuses before the first call if it would exceed the
ceiling, and prices the three-calls-per-frame arms as three so the refusal lands
early rather than at 300% of the estimate.

> **v2.91 was outside this until v3.36.** It had waited since the v2.77–v2.95
> block on the same single thing, kept its own harness because the planner did
> not exist yet, and was listed separately in the v3.1–v3.27 close. An owner who
> set a ceiling and ran "the block" would still have had one measurement sitting
> outside it, waiting on a decision they had already made. It is in the planner
> now; the run still goes through `prompt_ab.plan`, which enforces the
> arms-differ-only-in-the-prompt rule this planner deliberately relaxes.

### 2. A correction set with the shoot type recorded — unblocks 3

v2.83, v3.8, v3.9.

There is no `annotations.jsonl` anywhere on this machine. The fitted profile at
`~/.pixcull/personal_profile.json` records 70 blind-provenance annotations and
the examples behind it are gone; a profile cannot be re-fitted from its own
output.

`personal_learn.readiness()` says how many more are needed and by which
vertical, counting the cheapest route to two eligible verticals rather than
every vertical that exists. `pixcull m3 label` is the session that produces
them.

### 3. Human judgement — unblocks 4

**v2.80, v2.88, v2.89** need raters who are working photographers and are not
the author. `blind_eval.py` and `ground_truth.py` hold the protocol and the
refusal guard that declines to publish a headline number when inter-rater
agreement falls below threshold. **Never synthesise these labels** — that is the
exact defect v2.88 exists to prevent.

**v3.12** is different in kind: it asks whether the burst face strip changes the
override rate, which is a question about the owner's own behaviour rather than
about a third party's opinion. `strip_effect.py` records it as a side effect of
ordinary use — off unless asked for, written to the run's own directory, never
transmitted, and refusing to report a rate below five observations per side.

### 4. One real Lightroom catalogue — unblocks 1

v3.10. Every test builds its own SQLite fixture in the shape the reader expects,
which proves the reader is self-consistent and nothing about Adobe's schema.
`pixcull import-catalog <file.lrcat>` is dry-run by default and prints the
refusal with the tables and columns it wanted when the shape differs — which is
a result, not a failure.

---

## Three gaps that are NOT waiting on a person

Recorded because "waiting on the owner" is a comfortable place to put something
that is actually unfinished.

**v3.28's fix is construction-tested, not effect-tested.** exiftool is not
installed here, so the command line is asserted through `build_args` as a pure
function. That proves the arguments are right and does not prove exiftool does
what the arguments say. Installing it is a change to the machine and is the
owner's call, but nothing else blocks it.

**v3.29's second half did not run.** The charter asked for `evaluate()` re-run
with and without the non-human rows, so that if the delta is material every
published personalisation figure could be marked as computed over polluted
labels. That needs the same correction set as ask 2. The provenance fix shipped;
the impact measurement did not.

**`24-transcript-edit.png` is still synthetic**, and declared as such. It needs
footage with speech in it; the owner's working copy of the source clip is no
longer on this machine.

---

## Closed since the last count

Six items that had been sitting as "NOT MEASURED" turned out to be perfectly
runnable once someone tried — v3.14, v3.15, v3.19, v3.20, v3.21, v3.27, measured
during the v3.1–v3.27 close. Two of them were only unmeasured because nobody had
attempted the measurement, which is a different and less comfortable reason than
"we are waiting on the owner".

`BLOCK-v3.1-v3.27-CLOSE.md` has those numbers. The lesson is on this page
because it will apply again: before recording something as blocked, try it.

---

## Known red, pre-existing and now fixed

`test_visual_smoke::test_grid_and_lightbox_have_no_legacy_palette` had flagged
the disagreement-review button since before v3.20. It stayed hidden because the
local gate convention skips that file — it needs a real browser render. Fixed on
`fix/info-token-runtime-palette-guard`: the button never hard-coded a colour, the
dark-theme `--c-info` value itself sat in the one-step gap between the static
guard (`b >= 190`) and the runtime one (`b > 180`).
