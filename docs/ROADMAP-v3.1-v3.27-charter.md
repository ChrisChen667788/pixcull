# PixCull v3.1 → v3.27 charter — the core, read against the competition

Written 2026-09-02. **Supersedes `ROADMAP-v3.1-v3.6-charter.md`**, which read the
same research at the level of one workflow step (the client hand-off) and
renumbered v3.1 on a premise that turned out to be false — see *The correction
that reordered this charter*, below.

The input is the same deep competitive research behind `COMPETITIVE-2026Q3.md`,
re-read entry by entry: **46 competitor and model entries across five research
lenses**, plus the fact-check pass that overturned 10 of 10 audited headline
claims. This time the question asked of it was the right one: not *what does
PixCull not do for the client*, but **what do these products and papers do inside
the culling engine itself** — the decision core, the rubric, the judge, the
critique, the personalisation, the sequence handling, the ingestion, the compute,
and the way the whole thing is packaged and claimed.

## Method, and why it is stated here

Eight capability dimensions were each read by an analyst pass and then handed to
an **adversarial reviewer** whose instruction was to refute, defaulting to
refuted under uncertainty, with three specific checks: *is this already built*
(verify in code, do not trust the analyst), *is the competitor claim one the
fact-check overturned*, and *is this in a declined domain*.

**24 proposals; 21 survived; 3 were refuted.** All three refutations are recorded
below, because each one is more useful than the proposal it killed. The
adversarial pass also corrected the framing of six survivors — in two cases
finding a blocker the proposing analyst had missed, which is why v3.1 and v3.2
below are prerequisites rather than features.

---

## The correction that reordered this charter

`ROADMAP-v3.1-v3.6-charter.md` §v3.1 proposed a "can't tell" state on the
argument that PixCull gives the photographer no uncertainty signal — that a
`maybe` the model was unsure about and a `maybe` it examined and found borderline
"look identical in the grid". **That is false, and it was false when it was
written.** The report UI already ships all three of these:

* `results.js:2427-2433` — a `⌬ K 85%` badge on the card carrying the meta-judge's
  label and confidence, with the inconsistencies in its tooltip.
* `results.js:1855-1862` — an `uncertain` sort ordering by `|P(keep) − 0.5|`.
* `results.js:2058-2072` — a one-click **决议模式** that filters to `maybe` and
  applies that sort, toasting "最拿不准的排最前".

What is actually missing is narrower and more interesting: the confidence the
badge displays is **self-reported by the model about itself**
(`meta_judge.py:197-202` reads `parsed['confidence']`), it is never written to the
XMP sidecar, and nothing measures whether it predicts anything. That is v3.6 and
v3.7 below, and it is a better item than the one it replaces.

---

## The three refutations

**A confidence annotation in the primary grid** — refuted: already built, three
ways, above. The surviving residue is the XMP gap and the fact that the
confidence is unvalidated.

**An in-Lightroom docked tether panel (LrWebView).** The gap is real — the plugin
declares only `LrLibraryMenuItems` and `LrHelpMenuItems`, and no `.lua` file
mentions a panel. But the proposed mechanism does not hold up: the claim about
what the Lightroom SDK will render in a docked panel was not established, and a
version built on it would fail late. Excire and Narrative do ship in-Lightroom
panels; *how* they do it needs to be established before this becomes a version.

**RAM-aware worker auto-scaling.** Refuted for solving the wrong bottleneck. The
cap at `min(4, cpu-1)` in `parallel.py:120-130` was not a memory decision — the
module's own benchmark table shows 4 workers × 3 threads was *slower* than 4 × 2
at identical RAM, because of Metal/GPU contention. Adding a memory check would
raise the worker count into a regression. This is a good example of why the
adversarial pass exists: the proposal was reasonable and the code said no.

---

# The versions

## Block A — the instruments are pointing at the wrong things

These two are first because every later measurement depends on them. Neither is
a feature; both are the reason a later feature's number would be a lie.

### v3.1 — the depth harness has been measuring the wrong field
`advice_depth.py`'s baseline is stated in its own docstring as a **median of 71
characters over 3,929 cached rationales** — one sentence. But the field the M3
prompt asks for a 2–4 sentence photographic analysis in is `reading`, not
`rationale`. So the "advice depth" number this project has been quoting, and
`ADVICE-DEPTH-BASELINE.md` with it, describes a one-line summary field and says
nothing about the critique the owner called too shallow. `summarise()` is already
field-agnostic; the defect is in what was fed to it, not in the function.
**Measure:** re-run the baseline over `reading` and publish both numbers side by
side. **Ships when** the baseline document names the field it measured.
**Wrong, not late:** if `reading` turns out to be sparsely populated in the cache,
the new baseline will be thin — that is a finding about coverage, and it must be
reported rather than backfilled.

### v3.2 — temperature is not in the cache key
`m3.py`'s `_content_hash` keys on image content, model, prompt version, scene,
vertical and the evidence block — **not on sampling temperature**. Any future
work that samples the same frame more than once to see whether the model agrees
with itself would get the same cached answer three times and measure 100%
agreement, on every image, forever. The deterministic cache is correct and should
stay; what is needed is temperature in the key plus a separate consistency-pass
slot that does not pollute it.
**Measure:** a test that scores one frame twice at different temperatures and
asserts two distinct cache entries. **Wrong, not late:** widening a cache key
invalidates every existing entry. The consistency slot must be additive, or the
first run after this version re-pays for a whole library.

## Block B — the critique, which is the live complaint

### v3.3 — the burst sibling is a number, not a sentence
When a frame loses to its burst sibling, `nl_explain.py:110-115` renders
`"same-group neighbor is {delta:.2f} sharper; consider it instead"`. The
photographer is told a float. The M3 advice prompt (`m3_advice.py:43-82`) has no
burst section at all, so the model writing the critique does not know a sibling
exists. **Design idea** (from NTIRE 2026's pairwise IQA track and Narrative's
side-by-side survey mode): pass the winning sibling into the critique context so
the sentence can say what is better *in the other frame*, not by how much.
**Measure:** depth over the `reading` field (needs v3.1) on culled burst members,
against the current output. **Wrong, not late:** a critique that constantly
compares may read as excuse-making on frames that are simply weak on their own.

### v3.4 — one worked critique per vertical, in the prompt
`photography_canon.py` injects principles — Cartier-Bresson, the Zone System — as
abstract text. It never shows the model a finished critique. AtelierJudge's
System-1 half is exemplar retrieval: ground a subjective judgement in a concrete
reference before generating. **Design idea:** a small `critique_exemplars.json`
with 3–5 worked critiques per major vertical, injected into the M3 system prompt.
**Measure:** depth and blind preference against the current output on the same
frames. **Wrong, not late:** exemplars are a strong stylistic attractor; the
model may start producing paraphrases of the examples. The measure must include
frames where the exemplar does not apply.
**Provenance note:** AtelierJudge's reported correlation is from structured
creative-writing evaluation, **not photo culling**. This is a transfer
hypothesis, and the version must not cite that figure as if it were about photos.

### v3.5 — one prompt is asking for six axes at once
`vlm_judge.py:114-203` builds a single prompt requesting all six axes in one
response. The NTIRE 2026 second-place IQA architecture routed each dimension to a
specialist. The prompt-only version of that idea is 2–3 grouped calls
(technical+light share detector evidence; subject+moment share face data;
composition+aesthetic), consolidated by the meta-judge that already ships.
**Measure:** per-axis Spearman against the correction set, single-pass vs
grouped, through the existing `prompt_ab.py` harness. **Wrong, not late:** this
multiplies VLM calls per frame by 2–3× against an unproven benefit, and the
per-axis gain may be swamped by the meta-judge's consolidation. Also — grouping
prompts is **not** what the Pi Group paper did; it is an engineering derivation
from it, and the version must be described that way.

## Block C — uncertainty that is measured instead of asserted

### v3.6 — does the model's confidence predict anything? (needs v3.2)
The `⌬ 85%` on the card is the model's own claim about itself. Sample the same
frame N times at non-zero temperature and use **inter-pass agreement** as a
measured uncertainty, then test both signals against the same question.
**Measure:** on the existing corrections, precision@k of measured agreement vs
self-reported confidence as predictors of human disagreement. No new labels.
**Wrong, not late:** N× the VLM spend on every frame is not viable as a default;
this has to be a gate that fires only on frames already flagged uncertain.

### v3.7 — the verdict travels to Lightroom; the doubt does not
`decision_to_xmp` (`io/xmp.py:345-360`) maps keep/maybe/cull to star ratings and
Green/Yellow/Red labels, which Capture One and Lightroom render natively. The
confidence behind that verdict is never written. Capture One's own design is
instructive here: their "Can't tell" is a *tag*, and tags are Smart Album
criteria — the uncertainty is a filterable object in the host app, not a
decoration in a separate window.
**Measure:** a round-trip test — export, open in Lightroom, build a smart
collection on the keyword, assert the expected frames appear. **Wrong, not
late:** an XMP keyword is a public contract with a third-party catalogue;
renaming it later is a migration.

## Block D — personalisation

### v3.8 — one taste profile across every kind of shoot
`personal_learn.Example` (`:42-43`) carries axes, decision and run_id — **no
vertical** — and `aggregate_prefs` pools everything. So a photographer who shoots
weddings and wildlife gets one blended profile, and the wedding corrections that
say "forgive soft technical for emotion" are averaged against wildlife
corrections that say the opposite. The scene is already read from `scores.csv`
during gathering; it is simply not attached.
**Measure:** k-fold keep-F1, pooled profile vs per-vertical profile, on the
existing corrections. **Wrong, not late:** splitting the corrections by vertical
divides an already-small dataset. The version needs a minimum-count guard per
vertical and must fall back to the pooled profile below it.

### v3.9 — the A/B compare modal throws its answer away
The compare modal ships (`shortcuts.py:135-139`). Nothing records which side the
photographer preferred — a grep for `compare_pairs` / `pairwise` / `winner` in
the Python sources returns nothing. Pairwise preference is exactly the data
format the personalised-DPO line of work consumes, and it is the cheapest
high-quality taste signal a culling tool can collect.
**Measure:** the pairs accumulate and reload; then k-fold keep-F1 with and
without them. **Wrong, not late:** there is currently **no "prefer this side"
gesture** in the modal — navigating away is not a preference. This version has to
add an explicit gesture first, and inferring preference from navigation would
manufacture labels, which is the one thing this project does not do.

### v3.10 — cold start: the photographer's own catalogue already holds the answer
`personalized.is_active()` requires ≥50 annotations with TRUSTED provenance, so a
new user gets the generic model for a long time. Imagen and Aftershoot both seed
from existing work. `serve_app.py:10867-10869` already carries a deferral comment
for Lightroom catalogue import ("undocumented, reverse-engineered binary").
**Measure:** on a catalogue with existing picks/rejects, seeded-profile keep-F1
against the generic model on held-out corrections. **Wrong, not late:** an
imported pick is not the same act as a PixCull correction — it may mean
"delivered", not "best". The provenance guard exists precisely for this: imported
labels must carry their own provenance value and must not silently satisfy the
TRUSTED gate.

### v3.11 — the canon is words; the exemplar bank would be pictures
Per-axis few-shot grounding: attach one high and one low exemplar image from the
photographer's own corrections to the axis prompt.
**Measure:** per-axis Spearman, canon-only vs exemplar-augmented, split by
vertical. **Wrong, not late — and this one is close to fatal:** `annotations.jsonl`
stores the photographer's keep/maybe/cull, **not per-axis stars**. The axis stars
come from `rubric_decompose` with `source="auto"`. So an exemplar bank keyed on
axis stars would calibrate the model against *its own detector output*, dressed
as the photographer's judgement. That is the circularity this repo has a whole
labelling protocol to prevent. Either the exemplars are selected on the decision
the human actually made, or this version does not ship.

## Block E — sequences and subjects

### v3.12 — the burst winner is asserted; the faces are not shown side by side
`burst_peak.rank_burst_peak` picks the winner using blink, smile and brow
blendshapes, and `burst_peak_reason` is serialised as text. A per-image face-crop
endpoint exists (`serve_app.py:4154`), but nothing assembles the same face across
a cluster into one strip. Narrative's Close-Ups Panel and Lightroom's Face View
both do exactly this, and it is the one comparison a human makes faster than any
model. **Measure:** override rate on burst winners, with and without the strip.
**Wrong, not late:** on a 40-frame cluster the strip is a lot of crops; it needs
a cap and an ordering, or it becomes the thing the photographer scrolls past.

### v3.13 — the scenes API returns a flat list
`scenes.py` segments a run chronologically and the endpoint
(`serve_app.py:4025-4100`) returns `filenames` as an unsorted flat list — no
ranking, no top-N. Narrative's Scenes View ranks within the scene, which is what
makes "show me this scene's best five" a single interaction.
**Measure:** the endpoint returns the top-N by `score_final` per scene, and the
report can render a per-scene shortlist. **Wrong, not late:** ranking inside a
scene rewards the same qualities the global ranking does, so a scene of uniformly
weak frames still yields five "best" ones. The UI must not imply they are keeps.

### v3.14 — a tighter crop is not a duplicate
`near_dup.py:23` collapses on CLIP cosine ≥ 0.92 with connected components, and
nothing distinguishes *the same frame twice* from *a deliberate reframe of the
same subject*. A 16:9 crop of a 3:2 original is the photographer's decision, and
collapsing it hides one of the two things they wanted to compare.
**Measure:** on a set containing known intentional crop variants, count how many
survive grouping before and after an aspect-ratio/focal-length guard.
**Wrong, not late:** the Aftershoot mechanism this is drawn from is *unconfirmed*
— only the headline "tighter duplicate detection" survived fact-check. This is
PixCull's own hypothesis and must be labelled as one.

## Block F — ingestion and compute

### v3.15 — the tether verdict never reaches the host application
This is the block's clearest instance of the repo's signature defect. `tether.py`
analyses each new file and appends a row — and **never calls `write_xmp`** (grep:
zero hits). Meanwhile `decision_to_xmp` exists and is documented as producing the
colour labels *Capture One renders natively*. Both Capture One's Assisted Review
and Meitu's iPad import put the first verdict in front of the photographer at
capture time; PixCull has every piece needed to do the same and does not connect
them. **Measure:** during a tether session, assert a sidecar appears next to each
new frame with the mapped label. **Wrong, not late:** writing sidecars into a
live tether destination while the host application is importing is a real
collision risk. This needs to be opt-in and to survive a host that holds a lock.

### v3.16 — every re-run re-does yesterday's work
`orchestrator.py:3-4` says "V0.3 will add multi-process workers and incremental
runs via the cache layer". The workers shipped; **the incremental cache did not**
— no content-hash skip exists in the analysis path. Re-running a folder re-executes
CLIP, MediaPipe, aesthetics and segmentation on every frame.
**Measure:** wall-clock of a second identical run over a fixed folder, warm vs
cold. **Wrong, not late:** a stale cache that returns a verdict for an edited file
is worse than a slow run; the key must include content, not just path and mtime.

### v3.17 — one resolution for every frame
`VLM_RESIZE_LONG_EDGE = 1024` (`vlm_judge.py:77`) is applied uniformly, while
`resize_long_edge` is already a per-call argument on both judges — so routing is a
function call away. Lightroom's Assisted Culling runs inference on Smart Previews
rather than full RAW for the same reason.
**Measure:** cost and per-axis agreement at routed vs fixed resolution.
**Wrong, not late:** the axes most likely to need pixels — technical, and eye
sharpness inside a face — are exactly the ones a router would downgrade on a
"simple" frame. The measure has to be per-axis, not aggregate.
**Provenance note:** InternVL3.5's ViR token-reduction figure survived
fact-check; its benchmark and Apple-Silicon deployability claims did **not**.
Only the principle is being borrowed.

### v3.18 — the judge never sees two burst frames together
The local Qwen3-VL path calls the model with `num_images=1`
(`vlm_judge.py:335-341`), with a comment noting multi-image templates exist. Burst
demotion happens afterwards, on scores produced independently. So the model that
could say "this one, because the eyes are open here and not there" is never shown
both. **Measure:** burst-winner agreement with the photographer, single-image vs
multi-image call. **Wrong, not late:** multi-image prompts are markedly harder to
keep on a schema, and this path already has a repair-or-fall-back contract to
honour.

### v3.19 — target count: "give me 400"
Event work is contracted in counts. PixCull has strictness presets and a personal
shift, all of which move a *threshold*; none of them hit a number, and strictness
is blind to set size — the same preset yields wildly different counts on a
300-frame and a 3,000-frame shoot. A rank-then-cut pass over the scored CSV is a
small, self-contained addition.
**Measure:** a unit test asserting exactly N keeps (plus boundary ties) with no
`score_final` mutated. **Wrong, not late:** a forced count promotes frames the
rubric rejected. The output must stay honest about that — a target-count keep is
a different claim from a threshold keep, and the report should say which it is.
**Provenance note:** Aftershoot's equivalent is confirmed **beta, not GA**;
Imagen's exists but its introduction date is unverified.

## Block G — how the tool is packaged and how it speaks about itself

### v3.20 — a read-only MCP server over the API that already exists
Zero hits for `mcp` in first-party code. Meanwhile `serve_app.py` already exposes
scan, semantic search, decisions and tether control over HTTP. A thin read-only
MCP wrapper makes PixCull addressable by any MCP-capable assistant — which is the
integration shape the Firefly-agent and Lightroom-MCP entries in the research all
point at, and it is a fraction of the cost of a plugin per host.
**Measure:** an MCP client lists the tools and completes a search-and-decisions
round trip against a fixture run. **Wrong, not late:** read-only is the whole
point. A write path here would let an assistant re-decide a photographer's shoot,
and this project's position is that the machine proposes and the human decides.
**Provenance note:** the community Lightroom-MCP claim was partially overturned;
this version does not depend on it.

### v3.21 — the session's health is computed and never shown
`fallback_ledger` records, per pass, how many candidates there were, how many
were attempted, what was withheld and why — and `serve_app.py:9699,9717` put it
in the run JSON. `results.html` never reads it. The bias audit has routes and
handlers and lives at `/admin`. So the run that silently fell back to templates
on 40% of frames looks, in the report, exactly like the run that did not.
**Measure:** a run with an induced fallback shows it in the report without the
photographer opening `/admin`. **Wrong, not late:** health telemetry in the main
view can read as self-flagellation; it belongs where it is checkable and out of
the way, not next to every photo.

### v3.22 — the export says what it is, not just what it decided
XMP sidecars and a CSV go out with no record of *how* they were produced — model,
prompt version, strictness, whether personalisation was active, what fell back.
Every serious competitor's delivery carries some provenance; more to the point,
this project refuses to publish accuracy numbers without provenance, and then
ships decisions without any.
**Measure:** the export includes a session record, and a test asserts it names
the model and prompt version actually used. **Wrong, not late:** a provenance
file that ships alongside client deliverables must contain no local paths, no
drive names and no client identifiers — the repo hygiene gate applies to
generated artifacts too, not only to the source tree.

## Block H — carried over from the superseded charter

These five are not core-capability items and so were not produced by this pass.
They were correct in the superseded charter, none is duplicated above, and they
are renumbered here so that one document carries the whole live plan.

### v3.23 — do the photographer's own ratings survive PixCull's XMP write?
The transferable half of Capture One's Assisted Review is that its tags are
*additive* — they compose with the stars and colour labels the photographer
already set, and feed Smart Albums, without overwriting anything. PixCull writes
XMP. **No test in this repo asserts what happens to a rating or label already in
the sidecar.** **Measure:** a folder already starred and labelled in Lightroom,
run through PixCull, reopened — every pre-existing star and label still present.
**Wrong, not late:** it may already be correct, and then this is a regression
test that closes in an hour. Run it anyway: the failure mode is silent data loss
in a file the photographer did not know PixCull would touch.

### v3.24 — the live path and the finished path have diverged
Broader than v3.15. `tether.py` and `tether_stream.py` date from P2.2 and carry
none of what the last forty versions added — no written advice, no client picks,
no viewable-folder export, no burst evidence panel. It is not obvious the live
path *should* carry all of them. It is obvious nobody has decided.
**Measure:** run a tether session against a real folder drop; inventory live
verdict vs finished run for the same frames; publish the list with a disposition
per row — carried, or deliberately not carried, with the reason. **Wrong, not
late:** the deliverable is an explicit divergence, not an eliminated one. A live
tether view rendering a full critique paragraph mid-shoot would be worse.

### v3.27 — after the client picks: the return leg
The verified half of 像素蛋糕 is its shape — companion tools around one shared
project, where the selection step hands back to the retoucher. PixCull reached
the same instinct at v3.0: client picks live in their own file and are never
merged into the photographer's record. The return leg is not built. Once picks
come back the photographer reconciles by hand — the client wants frames the
photographer culled, and ignored frames the photographer starred.
**Specific:** a reconciliation view surfacing **only the disagreements**, because
those are the only rows that need a human. **Measure:** on a shoot with real
returned picks, every disagreement surfaces and no agreement rows do; time to a
final export list against doing it by hand. **Wrong, not late:** the photographer
may not want these framed as disagreements — the client is the client, and a tool
that appears to argue with them is worse than no tool. Neutral framing ("needs
your call"), never scored, never phrased as the client being wrong.

### v3.25 — every comparative claim PixCull makes carries a source
The fact-check overturned two of three headline claims in this batch, and the
worst was ours: an unsourced assertion that a competitor requires cloud upload,
used to draw a privacy contrast in PixCull's favour. The model card's version of
that claim was corrected on 2026-09-02; the two adjacent rows in the same table
("0..1 黑盒数字", "Web App 独立运行") are blanket claims of the same shape and have
not been audited. **Measure:** a test that fails when a comparative table row in
`docs/COMPETITIVE-*.md` or the READMEs asserts a competitor limitation with no
source on that row. **Wrong, not late:** a linter strict enough to fire on prose
would be disabled within a month. Scope it to table rows.

### v3.26 — the refresh protocol stops trusting its own confidence field
The scanning pass wrote `confidence: verified` on all three closely-read
products; verification overturned two. A self-reported confidence wrong two times
in three is worse than none, because the next charter weights it. **Specific:**
`confidence` is written only by the verification pass, and defaults to
`unverified` for anything verification did not reach. **Measure:** re-run the
fortnightly refresh; every `verified` traces to a verification record, and the
count of `verified` entries drops. **Wrong, not late:** a refresh where most
entries read `unverified` looks like a worse report. It is a more honest one, and
the protocol document has to say so in its own text, or a future reader will
helpfully "fix" it back.

---

## Deliberately declined, restated after the closer read

**An AI retouching engine.** What survived fact-check for both 美图云修 and
像素蛋糕 is retouching quality — 骨相磨皮, Sugar Engine 2.0. That is the strongest
version of the case for staying out: their moat is in a domain PixCull does not
enter, and the XMP sidecar remains the correct seam.

**A client-selection commerce platform.** Declined by the owner, and the specific
mechanism attributed to PixCake could not be confirmed to exist as described.

**Per-genre model zoos.** Deepen the rubric (Block B) rather than multiply models.

**An in-Lightroom docked panel, for now.** Refuted on mechanism, not on value —
it returns when someone establishes how Excire and Narrative actually do it.

**Raising the worker cap.** Refuted by this repo's own benchmark table.

**Vendor self-reported statistics as justification.** No item above rests on one.

---

## How this charter can fail

The previous version of this document renumbered a whole block around a gap that
was already filled, and it took an adversarial pass over the *rendering code* —
not the docs, not the Python — to catch it. Twenty-two items is a lot of surface
for that same error.

So: **every version above states what it found in the code, with a line number.**
If a version is picked up and the cited line no longer says what the charter
claims, the correct response is to re-derive the item, not to build it. And four
of these — v3.1, v3.2, v3.16, v3.21 — are not features at all. They are the
project discovering that an instrument was pointing at the wrong thing. Those are
the ones most likely to be skipped for looking unglamorous, and they are the ones
the rest of the block's numbers depend on.
