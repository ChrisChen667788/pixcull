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

**Done: the prior is opt-in and corrections beat it.** `primary_axes` reaches
the scorer through `verticals.axis_weight_prior`, behind
`PIXCULL_VERTICAL_AXIS_PRIOR=1`, and `orchestrator` applies it only when
`_axis_pref is None` — so a photographer who has corrected anything gets their
own weights, not the curated guess. Ten hand-authored judgements that had been
read by a serialiser and a phrase generator now do something.

The README was the half that was wrong, and it was corrected rather than
defended: naming a vertical shifts thresholds and tolerates the flags that genre
forgives; axis *weighting* comes from corrections, with the curated prior as an
opt-in cold start. That sentence is what v3.38's inventory then checked, and it
is the one claim of eighteen that the sweep had to fix.

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

**Done: `docs/README-CLAIMS.md`, nineteen rows for eighteen claims.** Seventeen
hold. The code column was the easy half; the reachability column is what found
the one that does not.

**The rescorer is not in the published package.** `RescorerConfig.model_path`
defaults to `models/rescorer_v1.joblib` — relative to the working directory —
and the eight artifacts under `models/` (1.8 MB) are tracked in git and absent
from the wheel. Measured on the built artifact, from `/tmp`:

```
default rescorer path : models/rescorer_v1.joblib
resolves from cwd /tmp: False
joblibs inside pkg    : []
```

Anyone who installed from PyPI has been running rule-only. It is not silent —
`load_rescorer` prints `— running rule-only` to stderr — but claim 1 states the
learned head as something you get, and claim 15's queue leans on it for its top
two priorities. → v3.44.

Four claims are true only behind an extra or a flag, and in every one of those
four the README already says so (`pixcull[face]`, `pixcull[shots]`,
`pixcull[asr]`, `PIXCULL_VERTICAL_AXIS_PRIOR`). One is source-only and did not
say so: the iOS companion is a Swift package you build in Xcode, not something
`pip install` gives you. The inventory says it now.

`tests/test_readme_claims_inventory.py` fails when a claim is added without a
row, when a row names a file that is not in the repository, and when the
measured failure above is quietly dropped from the document.

### v3.39 — the deferral comments, revisited once
Eight in the code. `orchestrator.py`'s "V0.3 will add … incremental runs"
waited until v3.16; `serve_app.py`'s "LR's catalog schema is undocumented,
reverse-engineered binary" was wrong (it is SQLite) and is now superseded by
v3.10 and v3.35 — the comment is still there.
**Measure:** each gets a disposition — done, superseded, still deferred with a
reason, or wrong. The stale ones are edited, not left as archaeology.
**Wrong, not late:** deleting a deferral comment because it is old loses the
reason somebody wrote it. Superseded ones say what superseded them.

**Six, not eight, and the census itself was the first thing wrong.** Two of
the eight were not deferrals: `sync.py`'s "not yet downloaded" describes an
iCloud state, and `verticals.py`'s `primary_axes` note was rewritten by v3.37
the week before. Re-running the scan found one the list had missed —
`verticals.py`'s "V17.3 will let users override per-vertical from the admin
panel".

| site | disposition |
|---|---|
| `orchestrator.py` "display-only for now" | **wrong now.** It stopped being true when the meta judge shipped: `build_packet` reads every `model_<axis>_stars` into the packet as `rubric_model`, so they are evidence in a judgement the photographer sorts their queue by. They still do not overwrite `decision`. |
| `rubric_decompose.py` "treat as passing … for now skip" | **wrong as written.** The line below returns `None`, and always has. A checklist item nobody can measure reported as *passed* is a claim about the photograph. Still deferred — nothing can see pose — but the comment now says what the code does. |
| `style_guide.py` "analyze_one doesn't emit those today" | **worse than it reads.** Nothing emits `img_width`/`img_height` anywhere, so this is not "skips on some rows", it is "has never fired once" — and the same is true of `face_center`. Two of the module's three rule types, including the one its own schema example leads with, are unreachable, and a missing field returns None rather than a violation, so a studio's aspect rule reads as satisfied. → v3.43. |
| `serve_app.py` "scoring still uses the RAW for now" | **undecided, not pending.** Scoring the developed preview means judging the photographer's own correction back at them; scoring the RAW means a frame they already rescued in Lr can come back flagged dark. Nobody has measured either. The comment no longer promises a change. |
| `serve_app.py` "V22.2+ will add cross-run inheritance" | **done.** V22.2 shipped it in `pixcull/pipeline/face_library.py`, wired from `_build_face_clusters_info` and written back by `add_to_library`. |
| `serve_app.py` "LR's catalog schema is … reverse-engineered binary" | **wrong, superseded.** A `.lrcat` is SQLite; v3.10 opens it with the standard library in `pixcull/io/lrcat.py`. |
| `verticals.py` "V17.3 will let users override per-vertical" | **done.** `/verticals/tune/<key>` writes `policy_override.json` through `policy_tuner`, and `decide()` reads it. It arrived as tune-from-samples rather than type-the-number. |
| `serve_app.py` `todo` in the fallback ledger | **not a promise.** `todo` is a filter key. |

The dispositions live in `pixcull/data/deferrals.tsv` rather than only in this
charter, because the point is that the next reader should not have to redo the
audit. `tests/test_deferrals_are_dispositioned.py` fails when a promise-shaped
comment is not in the inventory, and also when a dispositioned comment is
*edited* — the key is a hash of the comment text, so touching a deferral is
the moment to re-state what it is waiting for.

Found while writing that file: `pixcull/data/` had no pattern in the packaging
allowlist, so `tether_drift.py` shipped in every wheel and the
`finished_run_columns.txt` it opens did not. Same shape as the v2.44 hotword
lexicon, found the same way.

**v3.43 — the two style-guide rules that had never fired.** `img_width` /
`img_height` now come out of `analyze_one`, so `require_aspect` works. It took a
second fix to make `face_center` work: it read `face_bboxes` off the row, and
the clustering pass drops that key from every row before the DataFrame is built,
so it had nothing to read even once the width existed. The worker derives
`face_max_center_offset` instead, where the boxes and the frame width are both
in hand.

Refreshing `finished_run_columns.txt` for the two new columns meant running the
real pipeline, and that run caught a regression v3.44 had just shipped: the
first cut of the model resolver asked whether `models/` *existed* rather than
whether the file did, and in a checkout that directory exists holding only a
`.gitkeep` — so it shadowed all six packaged per-axis models and the run came
back with no `model_<axis>_stars` columns at all. Resolution is per file now.
No unit test found that; diffing a real CSV header did.

The snapshot itself is worth a note: it lags. It is a copy of one run's header,
so a column added to the pipeline is invisible to the gate until somebody
refreshes it. It now carries the union — this run's 84 columns plus
`face_region_lap_var`, which only appears when a frame has a face.

### v3.40 — a charter that discusses a module nobody can find
`ROADMAP-v2.71-charter.md` names `counterfactual.py` and quotes its docstring,
and evaluates `best_variant()` against 493 blind frames. Neither exists in the
repository.
**Measure:** find out which it is — deleted after the charter, or proposed and
never built — and say so in the charter. **Ships as either answer.**
**Wrong, not late:** if the module was deleted, whatever depended on it may
still be claimed somewhere, which makes this a v3.38 row as well.

**Answered: deleted, on purpose, after measuring.** Commit `3a7b6e3` — "v2.73:
counterfactual measured, then deleted — and the user guide was promising it".
On 100 blind frames the proposed crop's gain did not separate the
photographer's culls from their keeps, and the chip showed on 52% of kept
frames against 32% of culled ones, backwards from what it was for. So the v2.71
charter's own instruction ("ship one of two things, not neither") was carried
out correctly, and nothing is owed here except a signpost: three charters still
send a reader looking for the file, and none of them said where it went. Each
now carries the outcome at the top, and the two whose mention sits far below the
fold carry it inline as well.

`composition_classifier.py`, which fed it, survives and declares its own state
in its docstring: no consumer in the product, kept because nothing has measured
IT and v2.70's rule stands. That docstring had been truncated mid-sentence at
some point; it is repaired. Not a v3.38 row after all — nothing in the README
or the user guide claims the deleted module; v2.73 removed the guide's promise
in the same commit that removed the code.

`tests/test_docs_resolve_missing_modules.py` keeps the next one from going
unanswered: a doc that names a `pixcull` module the repository no longer
contains has to say what happened to it, within reading distance of the
mention. The word list is not proof — "delete" appears in v2.71 as a
*proposal* — so those three files are pinned by name to the actual outcome and
the general rule catches the ones nobody remembers.

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
