# v3.1 → v3.27 — what closed on a number, and what did not

Twenty-seven versions, read out of the 2026Q3 competitive research at the level
of PixCull's own core. This page is the accounting, and the reason it exists is
that "the code landed" and "the measurement passed" are different events and
this repository has confused them before.

**12 closed on a measurement run for this page. 4 closed on an invariant that
needs no run. 11 ship a mechanism and no number, each for a stated reason.**

## Closed on a measurement

| version | what was measured | result |
|---|---|---|
| **v3.1** | advice depth over both cache fields, rebuilt with `scripts/measure_advice_depth.py` | `overall_rationale` **47.7%** both-signals over 4,138 calls; `reading` **93.0%** over 186. `advice.alternative` reported for the first time: names things in frame 93.5%, argues 18.3% |
| **v3.14** | a real 3:2 original and its reframed crop, through CLIP and the guard | cosine **0.9841** — well over the 0.92 threshold, so they group; aspect differs **38.9%**, guard splits them |
| **v3.15** | four frames dropped into a live tether destination | 4 analysed, **4 sidecars written**, `Rating=3/Label=Yellow` for maybe and `1/Red` for cull — the labels Capture One renders natively |
| **v3.16** | cold vs warm pipeline, separate processes, detectors warmed off the clock | **16.41 s → 0.01 s**, 24/24 cache hits. Hash rate measured at 1,549 MB/s; see `DETECTOR-CACHE-MEASUREMENT.md` for the projection to RAW |
| **v3.19** | `pixcull run --keep-n 6` end to end | exactly **Keep=6**, all six marked `promoted_to_target` with `prior=cull`, and the six keeps are exactly the top six by `score_final` — the count moved, the scores did not |
| **v3.20** | an MCP client over stdio against a real run | **6/6** responses: initialize, tools/list, and a live search-and-decisions round trip returning `{keep: 6, maybe: 2, cull: 14}` |
| **v3.21** | a real server, a real run, the chip and the panel | chip **rendered**; panel row `m3_advice 7/8, 13% fell back (budget_exhausted×1), 14 withheld (decision=cull×14)` |
| **v3.23** | a sidecar carrying a hand-set rating, label and keywords, before and after | **before: all four destroyed.** After: rating 5, `Purple`, `Ceremony`, `Delivered` all survive and PixCull's verdict lands in the keywords |
| **v3.24** | live-path schema against finished-path schema | **10 columns vs 73.** Every one of the 63 differences ruled on: 43 deliberate, 5 impossible, **17 gaps** |
| **v3.25** | the linter, run over the published documents | found **11 more unsourced rows** than the charter named, in README.md, which a phrase-grep had missed |
| **v3.26** | migrating both snapshots under the new contract | `verified` **25 → 0** in each. Not one entry carried a verification record |
| **v3.27** | a 22-frame delivery with recorded client picks | **5 of 22 rows** need a human (23%); all three agreed frames stayed out of the view |

## Closed on an invariant

No run needed, and the invariant is the whole point.

- **v3.2** — the deterministic cache key is asserted against a literal string, so
  the 4,324 already-paid-for entries cannot be orphaned by a widening.
- **v3.7** — the uncertainty keywords are a public contract with a third-party
  catalogue; their exact spelling is pinned.
- **v3.13** — the shortlist is a pure function; ranking, the `none_is_keep`
  flag, and the unscored-frame ordering are all asserted directly.
- **v3.22** — that nothing path-shaped survives `build()` is a property, and
  properties are better checked than sampled. It caught a real leak: `scrub`
  walked dict values only, and `judged_by_observed` is keyed by model name.

## Mechanism only — and why

None of these is "not done". Each ships the thing and refuses to publish a
number it did not earn.

**Needs an API budget the owner controls** — v3.3 (burst sibling in the
critique), v3.4 (worked-critique exemplars), v3.5 (axis-grouped prompts, 3× the
per-frame spend), v3.6 (measured self-consistency, N× the spend), v3.11
(reference-frame grounding), v3.17 (resolution routing — and its measure has to
be per-axis, because an aggregate would hide the exact regression the design
guards against), v3.18 (multi-image burst calls).

**Needs correction data that does not exist on this machine** — v3.8
(per-vertical profiles) and v3.9 (pairwise preferences). There is no
`annotations.jsonl` anywhere here. The fitted profile at
`~/.pixcull/personal_profile.json` records 70 blind-provenance annotations and
the examples behind it are gone; a profile cannot be re-fitted from its own
output.

**Needs a photographer** — v3.12 (does the burst face strip change the override
rate?). That is a question about a person's behaviour and no amount of code
answers it.

**Needs a real Lightroom catalogue** — v3.10. Every test builds its own SQLite
fixture in the shape the reader expects, which proves the reader is
self-consistent and proves nothing about Adobe's actual schema. The refusal path
is what makes it safe to ship: on a differently-shaped catalogue the user gets
the names it looked for, not silence.

## What the block actually found

Two defects that were losing or corrupting the photographer's work, neither of
which anyone went looking for:

**v3.23 — PixCull was destroying hand-set ratings.** `write_xmp` built a fresh
sidecar over whatever was there. A photographer who had already starred,
colour-labelled and keyworded a shoot in Lightroom lost all of it the first time
they pointed PixCull at the folder. No error, no warning, no test.

**v3.9 — the compare gesture was poisoning the taste profile.** "Best + cull the
rest" wrote N-1 near-identical siblings into `annotations.jsonl` as plain human
culls, feeding `aggregate_prefs`, which averages axis stars for keeps against
culls. Every use of it flattened the gap `axis_weights` is built from.

And two things this project did to itself:

**v3.16's first measurement was fake.** Cold and warm were run in one process
and reported 3.0×. That was model warm-up — zero cache entries had been written,
because `put` was failing on numpy and returning False. A plausible figure,
produced by the thing under test, from a measurement that never ran.

**v3.21's chip could never have appeared.** Wrong URL, wrong run-id source, and
an endpoint that 404s after a restart. All three silent by construction, and the
only reachability assertion was that the module is spliced into the page.

## Four charter premises were wrong

The charter says to re-derive rather than build when a cited line does not say
what it claims. That fired four times: v3.1 (the baseline was already corrected
in v2.81), v3.9 (the compare modal has had a preference gesture since v0.7),
v3.10 (a `.lrcat` is SQLite, not an undocumented binary), v3.17
(`resize_long_edge` is a constructor argument, not a per-call one).

## The gates this block leaves behind

Four that fail on drift rather than on style, which is the only kind that
survives contact with a deadline:

- `test_tether_drift` — a new pipeline column with no live-path disposition.
- `test_comparative_claims_are_sourced` — a bare absolute about a competitor.
- `test_competitive_confidence` — `verified` with no `verified_by`.
- `test_detector_cache` — content keying, `DETECTOR_VERSION`, and that vectors
  survive the round trip as arrays.

## Known red, pre-existing

`test_visual_smoke::test_grid_and_lightbox_have_no_legacy_palette` —
`resolve-maybes-btn` carries a pre-v2.3 colour. Confirmed identical at fee978d,
before this block's UI work. It hides because the local gate convention ignores
that file.
