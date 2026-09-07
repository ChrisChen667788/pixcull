# PixCull v3.28 → v3.35 charter — the two accidents, made systematic

Written 2026-09-07, after `BLOCK-v3.1-v3.27-CLOSE.md`.

The previous block was read out of competitive research. This one is read out of
**what that block found by accident**, because both accidents were instances of
a class and nobody has swept for the rest of the class.

## The two accidents

**v3.23 — PixCull was destroying hand-set ratings.** `write_xmp` built a fresh
sidecar over whatever was there. A photographer who had already starred,
colour-labelled and keyworded a shoot in Lightroom lost all of it. Found while
answering a charter item that said "it may already be correct".

**v3.9 — the compare gesture was poisoning the taste profile.** "Best + cull the
rest" wrote N−1 near-identical siblings into `annotations.jsonl` as plain human
culls, and `aggregate_prefs` averages axis stars for keeps against culls. Found
while building something else.

Neither was looked for. Both are one instance of a general question that this
repository has never asked:

1. **What else overwrites something a human made?**
2. **What else writes a human-looking label that no human produced?**

Eight versions. Four are sweeps, four are the work the previous block could not
finish without the owner — stated here as the specific ask rather than left as
eleven scattered "NOT MEASURED" lines.

---

## Block A — the sweeps

### v3.28 — everything that writes where the photographer already wrote
`write_xmp` was one writer. There are others: the C1 `.cos` path, the embedded
XMP target, the collected-sidecar target, `proof_sheet`, `view_folder`, and
whatever the iOS app does on sync. Each one puts a file somewhere a photographer
may already have a file.
**Measure:** an inventory, one row per writer, each with the answer to "if
something is already there, what happens to it" — demonstrated by a test that
puts something there first. Every destructive one gets the v3.23 treatment or an
explicit reason it is allowed to overwrite.
**Wrong, not late:** some overwrites are correct — a derivative PixCull itself
produced last run should be replaced, not merged. The inventory has to
distinguish "the photographer's file" from "our file", and the distinction is
not always obvious from the path.

### v3.29 — every label in `annotations.jsonl`, and who actually made it
v3.9 added `source` and taught `personal_learn` to drop `compare_rejected`. That
was one producer. `annotations.jsonl` is written from the lightbox, the compare
modal, the Lr round-trip, the blind-labelling tool, the API and the iOS app, and
before v3.9 every one of them wrote `"source": "human"` because it was hard-coded.
**Measure:** enumerate the writers, assert each stamps a provenance that is true,
and re-run `evaluate()` with and without the non-human rows. If the delta is
material, every published personalisation figure was computed over polluted
labels and the baseline documents have to say so.
**Wrong, not late:** the correct fix for some producers is not exclusion but a
weight. Dropping a label the photographer really did make, because its producer
was mislabelled, would be the same defect facing the other way.

### v3.30 — the seventeen gaps in the live path, sized
v3.24 ruled on all 63 columns and named 17 gaps. The shape of that list is the
finding: almost every one is **exposure** or **the face** — `highlight_clip_pct`,
`mean_luma`, `horizon_tilt_deg`, `face_max_blink`, `face_region_lap_var`. Those
are the two things a tethered photographer is actually watching for and the two
the live path is silent about. It reports a verdict and withholds the number that
would let them fix the next frame.
**Measure:** carry them, and time the tether loop before and after. The per-frame
budget is the shutter interval; a live path that falls behind the camera is worse
than one that says less.
**Wrong, not late:** ten more columns in a live view is a table, and the v3.24
disposition file says a table is not glanceable. This version is about the four
or five that change what the photographer does in the next thirty seconds, not
about closing the list.

### v3.31 — the report's own numbers, checked against the file
v2.95 found the run summary counting a list built during scoring while the CSV
was written from a dataframe the judge had rewritten — two sources, one stale.
The same shape is available anywhere the UI shows a count.
**Measure:** for every number the report renders — decision counts, keep rate,
n_human_labeled, the client-pick and reconcile counts — assert it equals the same
number recomputed from `scores.csv` on disk.
**Wrong, not late:** some numbers legitimately differ from the file because they
are live (an unsaved annotation). Those need naming, not fixing, and a test that
pins which ones are allowed to drift.

---

## Block B — the eleven, turned into four asks

The previous block left eleven versions with a mechanism and no number. They are
not eleven problems. They are four requests, and each version below is the work
of *making that request cheap to answer*, not of answering it.

### v3.32 — one API budget, seven measurements **[owner]**
v3.3, v3.4, v3.5, v3.6, v3.11, v3.17 and v3.18 all wait on the same thing: the
owner setting a spend ceiling. Today each would be run by hand.
**Deliverable:** one command that runs all seven arms against a fixed frame set,
refuses before the first call if the estimate exceeds the ceiling, and writes a
single comparison table. **Measure:** the estimate matches the actual spend
within a stated tolerance on a small run.
**Wrong, not late:** `prompt_ab.py` already refuses on budget. This must reuse it,
not grow a second budget guard that disagrees with the first.

### v3.33 — the correction set that does not exist **[owner]**
v3.8 and v3.9 need corrections with a vertical recorded, and there is no
`annotations.jsonl` anywhere on this machine. The profile at
`~/.pixcull/personal_profile.json` records 70 blind annotations whose examples
are gone.
**Deliverable:** a labelling session that produces corrections across at least
two verticals, with provenance, resumable, and a check that says how many more
are needed before `evaluate_by_vertical` will stop refusing.
**Wrong, not late:** the temptation is to synthesise. The refusal in
`evaluate_by_vertical` exists to make that pointless and it must not be relaxed
to let this version "close".

### v3.34 — the questions only a photographer can answer **[owner]**
v3.12 asks whether the burst face strip changes the override rate. That is a
question about behaviour.
**Deliverable:** the strip instrumented so the answer falls out of ordinary use —
override rate on burst winners, with and without the panel open, recorded
locally and never transmitted.
**Wrong, not late:** instrumenting a photographer's workflow to measure them is a
different act from instrumenting a model. It has to be opt-in, local, and
inspectable, or it should not exist.

### v3.35 — the Lightroom catalogue this reader has never seen **[owner]**
v3.10's tests all build their own SQLite fixture, which proves the reader is
self-consistent and nothing about Adobe's schema.
**Deliverable:** run it against one real `.lrcat` and record what the refusal path
said. **Ships as:** either a confirmation or a corrected schema — both are
results.
**Wrong, not late:** a catalogue is the photographer's working database and often
the only copy. Read-only is already enforced; this version must not be the one
that relaxes it for convenience.

---

## Deliberately declined

**Closing the live-path gap list.** v3.30 takes the four or five that change what
happens in the next thirty seconds. The other twelve stay in
`TETHER-DIVERGENCE.md` as decided-and-not-done, which is a different state from
forgotten and the file exists to hold it.

**A second budget guard, a second hash, a second XMP writer.** Three times in the
last block a near-duplicate implementation was avoided by importing the existing
one. That is the standing rule, not a preference.

---

## How this charter can fail

Block A is four sweeps, and a sweep's failure mode is finding nothing and
reporting that as clean. Both accidents this charter is built on were found by
someone doing something else — which means the sweeps are looking for things
that have already evaded ordinary attention. **A sweep that reports zero
findings must publish its inventory anyway**, so the next reader can see what
was looked at rather than only that somebody looked.

Block B is four owner asks. None of them closes by an agent deciding it is close
enough.
