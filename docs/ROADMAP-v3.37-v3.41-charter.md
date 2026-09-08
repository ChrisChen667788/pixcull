# PixCull v3.37 → v3.41 charter — the claims we make about ourselves

Written 2026-09-08, after `OPEN-ITEMS.md`.

v3.25 made every claim this project publishes **about a competitor** carry a
source, because the fact-check had overturned one of ours: an unsourced
assertion that a named competitor requires cloud upload, used to draw a privacy
contrast in PixCull's favour.

This block turns the same bar inward. **A claim about our own software should
carry a code path.**

## The material was measured before this page was written

Four seams were probed. Two are rich, one is nearly empty, one is a single
dangling reference. The empty one is recorded because a charter built on a seam
nobody measured is how a block spends a week finding nothing.

| seam | probe | result |
|---|---|---|
| deferral comments in code | grep across `pixcull/` | **8**, of which ~5 are real and at least one is already stale |
| README feature claims vs code | opened the first list and checked it | **1 of 5 unsupported**, verified in the code |
| doc references to code that no longer exists | 369 backticked identifiers checked | **16 hits, almost all false positives** (`rgba()`, `alert()`) — this seam is clean, and no version below is built on it |
| charters referencing missing modules | same probe | **1 real**: `counterfactual.py` and `best_variant()` |

## The one already found

**The README says each vertical "adjusts the keep/maybe thresholds and weights
the axes to taste", with a worked example.** `decision.py` does apply a
per-vertical policy — threshold shifts and tolerated flags, V17.2. It does not
weight the axes.

The axis weighting exists as data: `verticals.primary_axes`, hand-authored for
all ten verticals, a curated statement of which axes each kind of shoot cares
about. Its own comment says "not yet wired into scoring", and it is read by
exactly two callers — a serialiser and a phrase generator.

Ten hand-made judgements, in the data model, feeding nothing. Same class as
v3.30, where the live tether path was thin because a seven-key dict literal
threw away every metric the pipeline computed.

---

## The five

### v3.37 — the axis weighting the README promises and the scorer never does
Decide it, do not leave it. Two honest outcomes and this version picks between
them rather than shipping the ambiguity for another forty versions.

**What ships now:** the claim and the code are made to agree. Either
`primary_axes` reaches `fuse_score`, or the README stops saying "weights the
axes to taste" — and a test pins whichever is true, so the two cannot drift
apart again.

**The connection worth keeping:** v3.8 learns per-vertical axis weights from the
photographer's corrections and refuses until two verticals clear the bar.
`primary_axes` is the cold start for exactly that — a hand-curated prior for a
photographer who has corrected nothing yet. The two have been sitting three
files apart doing halves of one job.

**Measure:** per-vertical keep-F1 with and without the prior, which needs the
correction set (`OPEN-ITEMS.md` ask 2). Until then the version closes on the
claim-and-code agreement, and says so.

**Wrong, not late:** a hand-curated prior that overrides a learned weight is a
downgrade the moment the learned weight exists. Precedence has to be decided
here, not discovered later: corrections beat the prior, always.

### v3.38 — every feature claim, checked against a code path
The sweep. One in five failed on the first list opened; the rest held, including
one that names a specific model (`InsightFace ArcFace`) and is accurate down to
the fallback.
**Measure:** an inventory, one row per claim, each with the file that makes it
true or the note that it is unsupported. **Published even where clean** — that
rule is now three blocks old and it exists because both defects the last block
was built on had already evaded ordinary attention.
**Wrong, not late:** a claim can be true and unreachable, which is this
repository's signature defect and not the same thing as false. The inventory
needs a third column: reachable from the shipped default, or only behind a flag.

### v3.39 — the deferral comments, revisited once
Eight in the code. `orchestrator.py`'s "V0.3 will add … incremental runs"
waited until v3.16; `serve_app.py`'s "LR's catalog schema is undocumented,
reverse-engineered binary" was wrong (it is SQLite) and is now superseded by
v3.10 and v3.35 — the comment is still there.
**Measure:** each gets a disposition — done, superseded, still deferred with a
reason, or wrong. The stale ones are edited, not left as archaeology.
**Wrong, not late:** deleting a deferral comment because it is old loses the
reason somebody wrote it. Superseded ones say what superseded them.

### v3.40 — a charter that discusses a module nobody can find
`ROADMAP-v2.71-charter.md` names `counterfactual.py` and quotes its docstring,
and evaluates `best_variant()` against 493 blind frames. Neither exists in the
repository.
**Measure:** find out which it is — deleted after the charter, or proposed and
never built — and say so in the charter. **Ships as either answer.**
**Wrong, not late:** if the module was deleted, whatever depended on it may
still be claimed somewhere, which makes this a v3.38 row as well.

### v3.41 — the effect test v3.28 could not run
v3.28 fixed the embedded-IPTC writer, which was destroying hand-set ratings and
keywords **inside the photograph**, with `-overwrite_original` so exiftool kept
no backup. The fix is asserted through `build_args` as a pure function: the
arguments are right, and nothing proves exiftool does what they say.
**Measure:** one real file with a rating, a colour label and two keywords; run
the writer; read it back.

~~**[owner]**~~ **Not an owner ask after all.** v2.45 had already set the
precedent — `apt-get install ffmpeg` in CI, because without it four journey
tests reported green having tested nothing. exiftool is the same shape and goes
the same place: one apt line, running on every push, instead of one run on
somebody's laptop.
**Wrong, not late:** a construction test that passes while the effect test fails
is worse than no test, because it reads as coverage. This version exists to
close that gap, not to widen the construction tests.

---

## Deliberately declined

**A sweep of doc references to code.** Measured at 369 identifiers, 16 hits,
almost all false positives. The seam is clean and building a version on it would
manufacture work.

**Rewriting the remaining 44 release notes.** They are in `CHANGELOG.md` now,
which is where a record of what was written at the time belongs. Rewriting the
record would make it a record of this week's taste.

**The twelve remaining live-path gaps.** Decided-and-not-done in
`TETHER-DIVERGENCE.md`, which is a different state from forgotten, and the file
exists to hold it.

---

## How this charter can fail

Three of the five are inventories, and an inventory's failure mode is finding
nothing and reporting that as clean. The seam probe above is the guard: it says
what was measured and what the hit rate was *before* the work started, so a
sweep that comes back empty can be checked against an expectation instead of
being taken on trust.

The other failure mode is v3.37 shipping the ambiguity again — wiring nothing,
correcting nothing, and adding a comment that says the two mechanisms should
probably be unified one day. That is what the last forty versions did.
