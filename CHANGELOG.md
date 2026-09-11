# Changelog

Everything before the five most recent releases, moved out of the README
by v3.36.  Nothing here was rewritten — this is the record as it was
written at the time, kept in one place instead of occupying the first
third of the file a new reader opens.

The most recent releases stay in the README under **What's new**.

---

## Upgrading from 2.47.0 — read this first

2.47.0 was the last version on PyPI, and 3.53.1 is the next one. A
hundred and six releases sit between them. Five of the changes alter
what the same command does to the same photographs, and none of them
announce themselves at run time.

**The cull boundary moved, so old shoots re-cull differently.** Under
the default `standard` strictness, `cull_max_score` went from 4.0 to
5.75. Every frame scoring in that band used to come back `maybe` and now
comes back `cull`. Re-running a shoot you have already reviewed will not
reproduce your old decisions. `--strictness lenient` (3.0) is the
closest thing to the old default if you want fewer culls.

**Detector flags no longer cull on their own.** Blur, closed eyes and
no-clear-subject used to force a `cull` outright; since v2.68 a flag
demotes a `keep` to `maybe` and never decides alone. Frames that were
discarded automatically now come back for review. Combined with the
threshold above, the net effect on a given shoot is not predictable
without running it.

**A cloud judge exists, and whether it runs depends on your machine.**
With no MiniMax key present, `pixcull run` is entirely on-device and
nothing is sent — the same as 2.47.0. With a key in your environment or
macOS keychain, cloud judging becomes the default: PixCull asks once
before the first upload, declining keeps you local, and a recorded
consent means later runs upload without asking again. The endpoint is
MiniMax's China region. `--vlm-mode off` forces the local path outright,
and since v2.72 a test holds the socket layer shut to prove it.

One detail worth knowing before you test this: clearing the
`MINIMAX_API_KEY` environment variable does not force a local run on
macOS, because the key is also read from the keychain. `--vlm-mode off`
is the switch that holds.

**`pixcull export` stopped overwriting your own metadata.** XMP ratings,
colour labels and non-PixCull keywords you set by hand now survive an
export; only prior `PixCull:*` keywords are replaced. This is almost
always what you want, but if you built a workflow on "export always
wins", it no longer does, and there is no flag to restore it.

**Three new required dependencies:** `scikit-learn>=1.6,<1.9`,
`joblib>=1.3`, `openai>=1.40`. The scikit-learn ceiling is not
cosmetic — the rescorer artifacts this package ships are pickles that
1.9 cannot load. An environment already pinning `openai<1.40` or
`scikit-learn>=1.9` will fail to resolve and the upgrade will abort
without installing anything.

---

## v2.94 – v3.76

The same hole as the one below, dug a second time. v3.53 found that
**What's new** had stopped at v2.45 while eighty-five releases shipped, and
built a gate so it could not happen again. The gate reads release commits with
`^v(2\.\d+…)` — the series that was current when it was written — so the
moment the next major arrived it went quiet, and stayed quiet through
sixty-four v3 releases while every test in the file passed.

The lesson is not "remember to update the regex". A guard pinned to the
shape of today's data has an expiry date it does not announce. There is a test
beside it now asserting the guard can still see the newest release in the log,
which is the thing that was actually false.

One line each, exactly as the release was titled at the time.

**v3.76** — three places the product showed you something that had stopped being true

**v3.75** — four things the product told you it would do

**v3.74** — the install-smoke lane was rehearsing an install nobody performs

**v3.73** — Phase A.1, and the file it was going to extend was wrong

**v3.72** — the unmigrated literals were light-theme bugs, not cosmetic debt

**v3.71** — the migration counter counted the one thing nobody can migrate

**v3.70** — the checks that only ever ran too late, and a sweep with a hole in it

**v3.69** — a setting that decides whether photographs upload, and did nothing

**v3.68** — the parity gate named one package, so it protected one package

**v3.67** — the README named a command that has never existed

**v3.66** — three things flagged for a human, and two of the three questions
were wrong

**v3.65** — the gate that catches a stale README was pinned to the version
series that had ended

**v3.64** — a face in the cover picture, and numpy pinned to a reason that had
expired

**v3.63** — real photographs, and the demo button that returned 500

**v3.62** — a hero with photographs in it, and a star history chart

**v3.61** — `[sync]` closed the gap ledger, and "slow" had become a place
things went rather than a description

**v3.60** — `pip install pixcull` also installed pytest, ruff and yapf

**v3.59** — a journey for the eighteen commands that had none

**v3.58** — the delivery folder crashed when there was nothing to deliver

**v3.57** — the PyPI quickstart told people to run a flag that does not exist

**v3.55** — four fixes the artifact needed before it goes somewhere permanent

**v3.54** — 3.53.0, and a tag push that no longer publishes irreversibly

**v3.53** — the product description had stopped 85 releases ago

**v3.52** — the same claim, corrected on one front door and not the other

**v3.51** — a skip has to be a decision, once

**v3.50** — faces are a README claim with no CI coverage anywhere

**v3.49** — the rescorer ships, and nothing installed could open it

**v3.48** — ffmpeg arrived one step too late, for thirty-nine tests

**v3.47** — the leftovers, and a test fixture that lived on one laptop

**v3.46** — the design system's own gate had never been run

**v3.45** — the README hero was 921,600 pixels of black, and nothing was looking

**v3.44** — ship the rescorer, so pip install stops meaning rule-only

**v3.43** — two style-guide rules that had never fired once

**v3.42** — the browser tests were green because they never ran

**v3.41** — the effect test goes in CI, so nobody has to install anything

**v3.40** — the missing module was deleted on purpose, and nobody said so

**v3.39** — the deferral comments, and the census was wrong first

**v3.38** — every README claim checked, and one of them is unreachable

**v3.37** — the axis weighting the README promised and the scorer never did

**v3.36** — v2.91 was waiting on a decision the owner would already have made

**v3.33** — v3.33–v3.35: the three remaining owner asks, made cheap to answer

**v3.32** — seven waiting measurements, one budget, one refusal

**v3.31** — the numbers on screen, checked against the file the client gets

**v3.30** — the live path was thin because of one dict literal

**v3.29** — sync was pouring another photographer's taste into your profile

**v3.28** — the same defect as v3.23, inside the photograph this time

**v3.27** — the return leg, and refusing to keep score on the client

**v3.26** — the refresh stops writing a confidence it did not earn

**v3.25** — the same bar outward: a claim about a competitor carries a source

**v3.24** — the live path's 63 missing columns, each one now somebody's decision

**v3.23** — PixCull was silently destroying the photographer's own ratings

**v3.22** — the export says how it was produced, and leaks nothing saying it

**v3.21** — the run's health was computed every time and shown never

**v3.20** — PixCull addressable by an assistant, for questions only

**v3.19** — "deliver 400 selects", as an instruction the tool can take

**v3.18** — the judge finally sees two frames of the burst at once

**v3.17** — route resolution, and be allowed to be wrong in one direction only

**v3.16** — the incremental cache orchestrator.py has promised since its first commit

**v3.15** — the tether verdict finally reaches the application on the screen

**v3.14** — a deliberate reframe is not a duplicate

**v3.13** — this stretch's best five, and whether any of them is any good

**v3.12** — the burst winner, checkable at a glance instead of on faith

**v3.11** — reference frames the photographer judged, never ones the system scored

**v3.10** — seed the cold start from the catalogue, without letting it vote

**v3.9** — the compare modal had the gesture all along; it threw away the comparison

**v3.8** — one taste profile for a photographer who shoots two different jobs

**v3.7** — the verdict reached Lightroom; the doubt behind it did not

**v3.6** — the confidence on the card is self-reported; this measures it instead

**v3.5** — ask about two axes at a time, and refuse to merge a partial answer

**v3.4** — the prompt has principles; now it also has a finished critique

**v3.3** — the critique now knows the frame lost a comparison

**v3.2** — temperature was not in the cache key, so self-consistency was unmeasurable

**v3.1** — a depth figure that does not name its field is how the last one went wrong

**v3.0.3** — a re-shot screenshot never reached ModelScope, and nothing said so

**v3.0.2** — the filter that was designed and not built, and two screenshots that were not real

**v3.0.1** — the on-site half: `p` records what the client points at

**v3.0** — what the client chose, kept out of what the photographer judged

**v2.99** — the folder you hand a client, with the structure still in it

**v2.98** — over WeChat the only identifier that survives is the pixels

**v2.97** — 客户在场模式: the client was reading the machine's verdict on their own wedding

**v2.96** — the one open item was not a regression; it was two machine loads

**v2.95** — the run summary reported the decisions the judge had already overturned

**v2.94** — the only tool that makes real labels wrote them in the one shape the guard rejects

---

## v2.44 – v2.93

These never appeared in the README. The **What's new** section stopped being
updated after v2.45 and eighty-five releases went by, so there was nothing to
move down here when v3.36 split this file out — the record existed only in the
commit log.

Restored from it, one line each, exactly as the release was titled at the time.
The titles are the record; they are not summaries written afterwards.

**v2.93** — closing the block: two defects that only appear when the versions meet

**v2.92** — 3.13 MB went out uncompressed to a browser that asked for gzip

**v2.91** — the guards a prompt A/B needs, built; the run is the owner's to authorise

**v2.90** — 97.6% of frames are "burst peaks", and the number is empty

**v2.89** — one metric was answering two questions; the boundary is still unobservable

**v2.88** — the accuracy baseline cannot be computed, and now it cannot be faked either

**v2.87** — a proof sheet the client opens, with no account anywhere

**v2.86** — a sharpness tool was serving soft thumbnails to Retina screens

**v2.85** — a hundred identical cards, torn down and rebuilt, to append placeholders

**v2.84** — warm first-screen: four hypotheses measured, four refuted, nothing shipped

**v2.83** — "we could not measure" was printing as "personalisation does nothing"

**v2.82** — four more passes wired, and a guard so the fifth cannot be forgotten

**v2.81** — the deep critique was withheld from every photograph being thrown away

**v2.80** — the machinery for asking photographers, built; the asking is not mine to do

**v2.79** — "too shallow" becomes 45.7%

**v2.78** — 40% of a core, held forever, for an animation nobody could see

**v2.77** — the first open, which is the one that was never measured

**v2.76** — a photograph gets one name, and that name gets that photograph

**v2.75** — 774 photographs the product could not show, and the render fix that wasn't

**v2.74** — Scenes — name the stretch from what is in it, never guess the event

**v2.73** — counterfactual measured, then deleted — and the user guide was promising it

**v2.72** — `--vlm-mode off` uploaded the photographs anyway

**v2.71** — a silent fallback has to be counted — and the counter found another one

**v2.70** — which flags are evidence — and the answer is "we cannot drop any of them"

**v2.69** — the filter panel spoke to a Chinese photographer in enum values

**v2.68.6** — the advice pass had never run — seventeen versions of an unreachable feature

**v2.68.5** — the photographer had never seen model-written advice

**v2.68.4** — NaN reached the photographer's screen, and the advice never said who wrote it

**v2.68.3** — closing the lightbox locked the tab; the next-photo arrow sat on the inspector

**v2.68.2** — the de-materialiser was reading layout while it mutated

**v2.68.1** — the MutationObserver feedback loop that froze Safari

**v2.68** — a hard-cull flag stops deleting photographs

**v2.67.1** — the release tooling leaked a token, and reported no-ops as failures

**v2.67** — the A/B, run — the evidence block earns its place, and more of it does not

**v2.66** — the evidence A/B, framework and guards (not yet run)

**v2.65.1** — input validation does not need a key, and my test never ran

**v2.65** — a stratified sample carries its own weights, or it is refused

**v2.64** — `primary` ships — and the metric had been guessing what `maybe` means

**v2.63** — the tool said SHIP for the first time, and it was wrong

**v2.62.1** — document calibrate, in both READMEs

**v2.62** — orientation debt closed, and the charter says what actually happened

**v2.61.1** — a 1250-frame pass has to be legible, not just resumable

**v2.61** — keyboard labelling, because 1250 frames is the actual bar

**v2.60.1** — learned exemptions live in the profile, not in the defaults

**v2.60** — an unfounded claim is not grounds for a cull

**v2.59** — pixcull calibrate — and it says the threshold is the wrong lever

**v2.58** — the judge no longer gets authority just for being switched on

**v2.57.2** — correct a false default I published thirty minutes earlier

**v2.57.1** — four tests that only ever ran on the author's laptop

**v2.57** — personalization was tuned to the rule stack, and said "tuned to you"

**v2.56.5** — the orientation debt closed, with the exceptions verified

**v2.56.4** — CLIP embeds the upright frame; the heatmap points at the photo

**v2.56.3** — traced the orientation debt — no score is affected

**v2.56.2** — the flags predict nothing, and 45% of frames were shown sideways

**v2.56.1** — the first non-circular measurement, and two holes it found

**v2.56** — label blind, then score — the only structural fix in the family

**v2.55.2** — circularity is per class, and a global rate cannot see it

**v2.55** — the first rankable number, and why it still cannot move the default

**v2.54.3** — a busy port names the squatter instead of printing a traceback

**v2.54.2** — a sample that cannot answer the question must say so

**v2.54.1** — an agreement row cannot be asked which system was right

**v2.54** — three authority modes, and the second shape of the circularity bug

**v2.53.2** — the save button that saved nothing

**v2.53.1** — sample the disagreements, and let each card carry its own answer

**v2.53** — your 17-of-18 verdict, and the mechanism that produced it

**v2.52.6** — the video wire format is verified, and 36 silent rows get a reason

**v2.52.5** — M3 works, the eval ran, and the answer is that it cannot answer

**v2.52.4** — one region sweep, because I got the same one wrong three times

**v2.52.3** — tell the two MiniMax failures apart, in the message

**v2.52.2** — MiniMax has two regions, and I picked the wrong one

**v2.52.1** — wire up the five modules I shipped without connecting

**v2.52** — M3 watches the clip, so reel ranking stops being pure proxy

**v2.51** — M3 writes the advice, having actually looked at the photo

**v2.50** — cloud judging ships on, and the product finally says so

**v2.49.1** — check the join and the photos before spending anything

**v2.49** — measure whether M3 actually decides better — and let it say no

**v2.48** — P0: MiniMax M3 adapter — correct contract, and proof it is correct

**v2.47** — measure the review page; nearly report a bug that was not there

**v2.46** — speaker chips in the review panel; two correct fixes that broke each other

**v2.45.1** — tell people the last five versions happened; fix an undo that only half-worked

**v2.45** — put the video chain in the end-to-end smoke

**v2.44.3** — speaker diarization: verified, fixed, and stopped from lying

**v2.44.2** — one-click render: text edit through to a finished cut

**v2.44.1** — edit by text in the review page; fix CSS that never applied

**v2.44** — a domain lexicon for Mandarin ASR; the edit-by-text state model

---

**v2.43.4** — **every published wheel contained no Python code.** The sdist
allowlist had no `*.py` pattern and `python -m build` builds the wheel *from*
the sdist, so nine releases shipped 35 data files and nothing else; the smoke
test passed because it ran `import pixcull` from the checkout root and picked
up the source tree. Nothing was ever installed from PyPI, so only direct
Release downloads were affected. `tests/test_packaging.py` now builds both
artifacts and looks inside them.

**v2.43** — **transcription** (`pixcull transcribe`): Paraformer or Whisper
behind an extra, `transcript.json` + an SRT sidecar, and click-a-line-to-seek
in the video review page.

**v2.42** — **shot-boundary detection** (`pixcull[shots]`, PySceneDetect,
BSD-3), so a reel candidate no longer spans a hard cut.

**v2.41** — **the end-to-end smoke test** the 2031Q1 audit put first: one
journey through `run → serve → export`, driving the real CLI and a real HTTP
server. All four of the audit's cited outages replay as red against it.

**v2.40.2** — **dead stubs removed, plus a fresh design audit**
([`docs/DESIGN-AUDIT-2031Q1.md`](docs/DESIGN-AUDIT-2031Q1.md)). v2.40's guard
only looked for `typer.Exit`, so three V0.3-era `NotImplementedError` stubs
survived — including `pixcull.report.export_html`, which sat in `__all__` as
public API guaranteed to crash. All three were deleted rather than implemented:
each had long been overtaken by something real (the HTML report is the review
workspace; `scripts/bench.py` is now `pixcull bench`). The guard now covers both
shapes. The audit scores **3.9/5** (2030Q4: 3.4) and names the pattern behind
this repo's most common defect: *advertised but unreachable* — cross-run search
that indexed nothing, video runs that wouldn't load, light theme that never
applied, an export command that exited silently. All four were live features
with one real user path that couldn't reach them, and all four would have been
caught by a single end-to-end smoke test, which is now the top engineering
recommendation. It also surveys the AI-editing OSS landscape and gates it on
licence first: **OpenChatCut is AGPL-3.0 and therefore cannot be vendored** into
an MIT project, while **FunClip (MIT) and PySceneDetect (BSD-3)** can — and they
fill verified gaps, since `SceneDetector` is CLIP *scene classification* rather
than shot-cut detection, and there is no ASR anywhere in the codebase.

**v2.40.1** — **the last linear cost in library indexing, solved without adding
a file** (see [`docs/ROADMAP-v2.40.1-charter.md`](docs/ROADMAP-v2.40.1-charter.md)).
v2.39 deferred this as "needs a key-index file, not worth it". Profiling showed
that framing was wrong: on a 300,000-row manifest the cost wasn't a missing
index, it was `json.loads` — 0.525s of 0.720s — parsing rows that could never
match. The dedup key starts with `run_id` and `append_run` handles one run at a
time, so rows from other runs are irrelevant by construction; a raw substring
pre-filter (0.013s for all 300k lines) keeps them out of the parser. Appending a
2,000-photo shoot: **0.159s → 0.062s** at 50k, **0.697s → 0.068s** at 300k, and
flat in library size instead of linear — ~48x faster than v2.38 at that scale.
The pre-filter is deliberately a superset test, with `run_id` re-checked after
parsing, so a filename that happens to contain the needle costs one wasted parse
and never a wrong answer — there's a test that plants exactly such a filename.
The degenerate case (re-indexing a run that *is* the whole library) still costs
0.708s and is documented rather than glossed over.

**v2.40** — **the gate stops lying, and the CLI does what the box says** (see
[`docs/ROADMAP-v2.40-charter.md`](docs/ROADMAP-v2.40-charter.md)). Real-model
tests used to guard themselves with a blanket `except Exception: skip`, which
conflates "the model isn't on this machine" with "the model is right here and
failed to load". During the v2.39 gate that let Hub rate-limiting silently stop
three tests — including the one pinning v2.34's `image_embeds ≡
get_image_features`, the sole guard on every cached vector the pipeline writes.
Now: if the weights are on disk the test **runs**, loaded with
`HF_HUB_OFFLINE=1` so the network can't turn a cached model into a failure, and
anything after that is a failure rather than a skip. Following the same
question — *what does green actually cover?* — a new guard asserting no command
is a silent `raise typer.Exit(1)` found two that had been stubs since V0.5.
`pixcull export` was one of them: no output, exit 1, while the package blurb
advertised "XMP/IPTC export, Lightroom & Capture One ready". Export existed, but
only inside the web workspace, so the CLI path v2.31 opened for pip users
dead-ended. It now runs the same code the server does — verified by writing
sidecars for real JPEGs and reading them back: keep→5★/Green, maybe→3★/Yellow,
cull→1★/Red all round-trip. `pixcull bench` was the other, now reporting real
throughput translated into shoot sizes — and running it immediately showed it
was filing its throwaway scratch sample into the user's cross-run library, where
every row would become a permanently stale hit.

**v2.39** — **switch the theme where you are, and stop rewriting the whole
library on every cull** (see
[`docs/ROADMAP-v2.39-charter.md`](docs/ROADMAP-v2.39-charter.md)). v2.35 made
the standalone pages *obey* the theme; they still had no way to change it, so
opening /library directly meant going back to the review workspace to switch.
The control is injected once in `_read_template` as a fixed-position pill
rather than wired into each page's header — three of them have no header, and
per-page wiring is exactly how ten of eleven pages missed the boot script
before. It mirrors the workspace toggle's contract exactly (dark → light →
system, same storage key), with a test pinning the two implementations
together. One deliberate exception: `/share/<run>/<token>` still obeys the
theme but carries **no** app chrome — that page is the photographer's delivery
to a client, not the application. Second half: `append_run` used to `np.vstack`
the entire index and rewrite `vectors.npy`, which measured 0.37s → 1.08s →
**3.30s** as the library grew 50k → 150k → 300k photos — and since v2.34
auto-index runs that after *every* cull, i.e. a 614 MB rewrite each time.
Vectors now live in a headerless float32 file appended in O(new); the row count
lives in `meta.json`, which is also what makes it crash-safe (bytes and
manifest are fsynced first, meta is swapped in last, so a torn tail is inert
rather than corrupt). Same three sizes: **0.159s / 0.380s / 0.697s**. What
remains linear is the manifest dedup scan (0.556s of that 0.697s), not the
vector write (0.005s) — documented rather than papered over as O(1).

**v2.38** — **contrast audit of the light theme I'd just rolled out** (see
[`docs/ROADMAP-v2.38-charter.md`](docs/ROADMAP-v2.38-charter.md)). v2.35 and
v2.37 brought light theme to a dozen surfaces that had never rendered light
before, and nobody had checked what that did to legibility. Measured against
the real tokens: the palette is healthy — every text tier clears WCAG AA on
both themes — with one exception. `--muted-soft` was **3.01:1** in light and
3.65:1 in dark while colouring 9.5–11px text (timestamps, hints, input
placeholders, hotkey labels); WCAG's "large text" allowance starts at 18.66px
bold, so that text needed the full 4.5:1. Solving for a compliant value showed
there's no room for a tier *softer* than `--muted` that still passes on deeper
surfaces, so this became a design decision rather than a colour tweak:
`--muted-soft` is now decoration-only (dividers, chevrons, dots, borders, SVG
strokes — the 3:1 graphical bar) and all 16 text uses moved to `--muted`. The
static token analysis nearly missed the point: the review workspace derives its
surfaces via OKLCH, not hex, so the same check was re-run in a real browser by
rasterising each colour to a canvas — the two agree, but only measurement could
say so. This release also **reverts an optimisation of its own**: batching the
per-row XMP sidecar probe into one `scandir` was 3–5% *slower* in both tested
shapes, so it was dropped rather than kept on an untested "it'd help on network
storage" rationale.

**v2.37** — **big shoots open 3x faster, and the page your client sees finally
looks like this product** (see
[`docs/ROADMAP-v2.37-charter.md`](docs/ROADMAP-v2.37-charter.md)). v2.33's cache
only helped from the second request on; the *first* open of a 20,000-photo
shoot still took 8.5s. Profiling found the loop touching ~58 cells per row, and
against a pandas Series every one is an `Index.get_loc` hash lookup —
**1.22M `Series.get()` calls, 43% of the build**, versus 9% doing the actual
work. Switching to `df.to_dict("records")` took the build **6.59s → 1.66s** and
the cold page **8.55s → 2.85s**. Because `iterrows()` silently upcasts int
columns to float and `to_dict` doesn't, the bar for that change was a
field-by-field diff of all 20,000 rows × 52 fields, not a stopwatch — identical.
Separately, `/share/<run>/<token>` — the gallery a photographer *sends to their
client* — turned out to be running on a third, unrelated palette
(`#0a0a1e`/`#1a1230`, purple-navy) with `color-scheme: dark` hard-locked, so it
could never follow the theme and looked like different software; the bias-audit
and companion windows were still on the pre-v2.21 gold. All three now use the
shared tokens. Finding the last of it needed a real browser: the sticky brand
bar was `rgba(10,10,30,0.85)`, invisible to a hex grep — the same failure mode
as the v2.3.1 palette leak — so the new lint checks both notations.

**v2.36** — **real video footage on stage, and a bug it flushed out** (see
[`docs/ROADMAP-v2.36-charter.md`](docs/ROADMAP-v2.36-charter.md)). The task was
just to close an owner action: publishable video footage. The owner authorised
their own GoPro clips, and every frame was vetted before publishing — GPMF
carries **no GPS samples**, 38 sampled frames through PixCull's own
`FaceDetector` flagged 14 which visual review confirmed were **all false
positives** (fur trim and knit patterning; the subject faces away throughout), a
wedding-motorcade clip with plates and bystanders was dropped, and the working
copy is re-encoded with `-map_metadata -1` under a neutral name so no drive name
or original path can appear on screen. Worth swapping because the old shots used
a stock clip whose reel-candidate thumbnails had to be **blurred to mush** —
hiding the very thing that panel exists to show. **Shooting it flushed out a
real bug**: `/timeline` rendered 50 broken images with 50 `/thumb` 404s, because
`_reload_run_from_disk` demanded either a `manifest.json` or an `input/` dir and
`pixcull video` produces neither (its frames live in `video_frames/`) — so a
video run never reloaded at all. Compounded by `_resolve_image_source` also
ignoring scores.csv's `path` column, the **same root cause as v2.34's**. Now
scores.csv is the marker of "this is a run", both output layouts are accepted,
and the path map is mtime-cached because that resolver runs **once per
thumbnail**. Re-verified: thumbnails **50/50, zero 4xx**.

**v2.35** — **near-dup grouping stops recomputing itself, and light theme
finally works everywhere** (see
[`docs/ROADMAP-v2.35-charter.md`](docs/ROADMAP-v2.35-charter.md)). Both items
came off the roadmap with a plan attached, and measurement killed both plans.
The near-dup plan said "prune by time window" — wrong: that grouping exists
precisely to catch near-duplicates `cluster_bursts` missed *because* they
aren't time-adjacent, and the real cost wasn't the pipeline but a
**per-request** handler with a user-adjustable threshold, so every nudge of the
slider re-paid the whole O(N²). Profiling found the surprise: `np.nonzero` cost
nearly as much as the matmul (1.15s vs 1.35s at 20k) because it walks all N²
booleans, while the Python union loop everyone suspects was 0.01s. Computing
only the upper triangle — the old code did every pair twice and threw half away
*after* paying — gives **2.69s → 1.50s** at 20k and **14.7s → 7.7s** at 50k
with provably identical grouping, and caching the result on the vector file's
mtime makes repeat requests free. For theming, a real-browser sweep found the
problem was bigger than "nobody sets `data-theme`": five pages never injected
the shared tokens at all, because their module constants are built *above*
where `_DESIGN_TOKENS_CSS` was defined — so the replace would have raised
NameError and was simply never written, leaving them on a hand-rolled
pre-v2.21 palette where the light-theme rule didn't exist. Both injections now
happen once inside `_read_template`, verified across 9 routes × 2 preferences.

**v2.34** — **cross-run search works out of the box now** (see
[`docs/ROADMAP-v2.34-charter.md`](docs/ROADMAP-v2.34-charter.md)). The task was
"auto-index a shoot after culling", but the investigation found v2.32's library
was **empty for real CLI users no matter what they ran**: the pipeline never
wrote `embeddings.npz` (it was lazily built only if you'd already searched that
shoot), and the path resolver consulted `manifest.json` and an `input/` dir but
never `scores.csv`'s own `path` column — the one source a plain `pixcull run`
actually produces. So `pixcull library index` reported "nothing resolvable" and
indexed zero photos. Both fixed, and the first fix turned out to be free:
scene detection already runs the full CLIP forward on every photo, and that
pass must project and L2-normalize the image tower before it can form
`logits_per_image` — so `out.image_embeds` *is* the 512-d vector semantic
search was re-encoding the whole shoot to obtain (verified cosine **1.000000**
against `get_image_features`, pinned by a real-model test). The pipeline now
persists those vectors at **zero extra inference cost**, which also means a
shoot's first semantic query no longer re-encodes it. Culling then files the
shoot into the library automatically — on by default, because searching
everything is the point of the page; the index is local-only in
`~/.pixcull/library/`, never synced, and `PIXCULL_NO_AUTO_INDEX=1` turns it
off.

**v2.33** — **big shoots stop re-rendering themselves** (see
[`docs/ROADMAP-v2.33-charter.md`](docs/ROADMAP-v2.33-charter.md)). This one
started by *disproving* its own roadmap: the design audit predicted the DOM
was the bottleneck on huge runs, but a 20,000-row measurement found only 700
placeholder nodes / 7,362 total / 30 MB heap — v2.18 chunked hydration already
bounds it. The real cost was on the server: `_build_results()` re-parsed the
entire CSV, re-merged annotations and re-derived all six rubric axes **on
every request**, and one page load calls it 5+ times. Caching it on the mtimes
of its only two inputs took the page from **6.2s → 0.055s** and each
hydration chunk from **6.3s → 0.045s** (~140x); cold start is unchanged
because the CSV has to be parsed once. Invalidation piggybacks on the
discipline `_JSONL_CACHE` already uses — a re-score or a saved annotation
changes an mtime, so writers never need to know the cache exists. The care
went into correctness, not speed: the cached rows are handed back by
reference, so all 18 call sites and every helper they forward rows into were
AST-audited as read-only (that contract is now written above the function),
and the nine regression tests were **mutation-verified** — blanking the
annotation mtime out of the key turns exactly the two invalidation tests red.

**v2.32** — **cross-run library search: ask your whole archive at once** (see
[`docs/ROADMAP-v2.32-charter.md`](docs/ROADMAP-v2.32-charter.md)). Per-run
semantic search answered "in THIS shoot, where is the backlit shot"; the new
`/library` page and `pixcull library` commands answer it across every shoot
you've ever culled. Architecture is measurement-driven
([the eval](docs/VECTOR-INDEX-EVAL.md)): **no ANN index** — brute-force is 8ms
at 100k photos and 34.5ms at 1M, still ~2x the 17.4ms CLIP text encoding every
query already pays, and memory (not speed) is the wall that arrives first, so
compression is the eventual optimisation and pure numpy keeps `pip install`
free of compiled deps. One merged `vectors.npy` opened via mmap beats stacking
per-run caches 18ms vs 174ms. Indexing **reuses each run's existing
`embeddings.npz`** — a copy, not a re-encode — keyed on
`(run_id, filename, mtime)` so it's idempotent and a re-scored photo
re-indexes by itself. Liveness is first-class: a hit whose file is gone comes
back flagged **stale**, never silently dropped — when an external drive is
unplugged, "found it, but it's not reachable" is the honest answer. Results
group by shoot with a jump back into the run. The index stores real absolute
paths, so it lives only in `~/.pixcull/library/`.


**v2.29** — **the frosted-glass system lands (adopt-scoped, as the audit
ruled)** (see [`docs/ROADMAP-v2.29-charter.md`](docs/ROADMAP-v2.29-charter.md)).
The ~30 ad-hoc `backdrop-filter` uses scattered through the UI (blur
2/4/6/8/10/12/20px + saturate 140/180% all hand-written) converge into **one
tokenized material**: `--glass-filter` (blur 16px · saturate 130% — pulled
back from the neon-vibrating 180%, the same retreat Apple made with Liquid
Glass in 2026) for frosted panels, `--glass-scrim-filter` (blur 4px) for modal
backdrops, and `--glass-edge` — the 1px top highlight that makes chrome read
as real glass (8% white in dark, 65% in light where a faint highlight is
invisible). Seven panels + seven scrims converged; three of the panels
(compare header, RGB readout, key cheat-sheet) had **opaque backgrounds that
made their old blur a silent no-op** — now translucent chrome films so the
glass is real. Three photo-top micro-glass sites stay deliberately untokenized
(reviewed keeps). The whole system honors
`@media (prefers-reduced-transparency: reduce)` — every glass surface falls
back to solid chrome (the codebase previously had **zero** such fallback), and
a new lint fails any raw `backdrop-filter:` outside the keeps so the material
can't fragment again. Photo surround and thumbnail mat: untouched —
Studio-Neutral color-judgment discipline holds.

**DESIGN-AUDIT 2030Q4** — **post v2.21–v2.28 recheck + a frosted-glass
direction verdict** (see [`docs/DESIGN-AUDIT-2030Q4.md`](docs/DESIGN-AUDIT-2030Q4.md)).
Overall **3.4/5 (Q3: 3.1)** — every dimension moved up (UX 3.9, intelligence
3.6, reach+release 2.4→2.9, architecture+perf 3.2→3.6), with reach still the
laggard behind owner-only actions. The audit answers the frosted-glass
(毛玻璃) question with an **adopt-scoped** verdict: the UI already carries ~30
ad-hoc `backdrop-filter` uses with inconsistent values and zero
`prefers-reduced-transparency` fallback, so the move is to *systematize* glass
into a tokenized, accessible layer on chrome / panels / overlays / modals —
**never** on the photo surround or thumbnail mat (that would break the v2.21
Studio-Neutral color-judgment discipline; even Apple pulled back Liquid Glass's
transparency in 2026 for legibility). Ranked v2.29 candidates: frosted-glass
system · results.js modularization · packaged `pixcull serve` · near-dup CLIP
collapse.

**v2.28** — **serve_demo inline-HTML extraction (the v2.27 deferral, done
right)** (see [`docs/ROADMAP-v2.28-charter.md`](docs/ROADMAP-v2.28-charter.md)).
v2.27 assessed and deferred this; here it lands behind a byte-identical
route-diff safety net — capture each route's rendered bytes before, extract,
restart, capture after, `diff` must be empty. Three cleanly static-shell-shaped
handlers move out to `templates/pages/*.html`: `_serve_tether_page` (fully
static, 219 lines), `_serve_history_page` and `_serve_disagreement_page` (static
shell + a few placeholder injections). Templates are generated mechanically via
source-block eval (dynamic operands swapped for placeholder literals, then
evaluated — zero hand-transcription). **serve_demo.py drops 12,909 → 12,518
lines**; all three routes verified byte-identical after extraction. The other
three handlers (`_render_share_html`, `_serve_bias_audit_page`,
`_serve_companion_page`) stay inline **on purpose** — they're heavily
f-string-interleaved dynamic builders (up to ~40 interpolations) whose template
extraction would hurt readability, and whose dynamic paths (e.g. bias's inline
annotator-chip generator) can't be byte-verified from the empty-state route
alone. The rationale now lives in CLAUDE.md so it isn't re-litigated.

**v2.27** — **results.css modularization continues** (see
[`docs/ROADMAP-v2.27-charter.md`](docs/ROADMAP-v2.27-charter.md)). Building on
the v2.22 `@@CSS:` splice infrastructure, five more cohesive blocks move out of
the results.css monolith into `src/modules/*.css`: card (557 lines), modal
(283), chips (1,398 — the unified chip system + legacy aliases), marquee (183),
and the left library panel (142). **results.css drops 4,812 → 2,268 lines**
(from 5,797 originally; seven CSS modules now: tokens / lightbox / card / modal
/ chips / marquee / library-panel), artifact byte-identical (same hash), marker
discipline + brace balance linted. The remaining serve_demo inline-HTML methods
(`_render_share_html` and five others) were assessed and deferred: unlike the
static pages v2.16 extracted, these are heavily dynamic f-string handlers
(15–55 interpolations each), whose safe extraction needs a placeholder-not-
format templating pass plus per-route byte-identical verification with real
data fixtures — a dedicated slice, not something to bundle into a low-risk CSS
refactor unverified.

**v2.26** — **true de-materialization: card DOM stays bounded on any run size**
(see [`docs/ROADMAP-v2.26-charter.md`](docs/ROADMAP-v2.26-charter.md)). v2.24
bounded decoded-image RAM; this bounds the card DOM node count too, completing
windowed virtual scroll. P-UX-18 materialized placeholders on scroll but never
recycled them — scroll a 10k wedding through and you'd accrete ~10k card DOM
subtrees. Now a card that recedes past ~5 viewports (a 300% hysteresis gap over
the ~200% materialize margin, so no boundary thrash) is torn back to a
placeholder of its measured height and re-materialized on re-approach. The
correctness-critical part: re-materialization renders **from the current row**
(`renderCard(segRows[idx])`, not the frozen segment string), so a decision made
while a card was live survives the recycle — `rows[]` is the source of truth and
every decision path mutates it. Verified on a 600-row run: scrolling through all
600 kept the card count at **172** (not 600), back at top it recycled to 100,
order and filenames intact, zero JS errors; a cull decision persisted across a
scroll-away-and-back. Together v2.24 + v2.26 decouple both image RAM and DOM
node count from run size.

**v2.25** — **n-way A/B compare: line up 3–5 near-dups, not just pairs** (see
[`docs/ROADMAP-v2.25-charter.md`](docs/ROADMAP-v2.25-charter.md)). The compare
modal was already n-cell internally, but the free-pick entry point opened the
instant you picked a second photo — a pro comparing 4–5 near-identical frames
across two burst clusters had to do repeated 2-way rounds (a 2030Q3-audit UX
gap). Picks now **accumulate into a set**: each pick toggles a photo in or out,
the tray shows the running count with a **Compare (N)** button, and Enter / the
button open the whole set in one n-cell compare (Esc clears). The lightbox `c`
key keeps its fast 1:1-check-then-pair flow. Eight new locale keys wire the
tray and toasts through `_t()`, and the compare modal's own title/meta join
them (they were hardcoded Chinese). Verified: three picks → "Compare 3" → a
3-cell modal; re-picking one toggles it back out.

**v2.24** — **image-memory virtualization: decoded thumbnails stay bounded**
(see [`docs/ROADMAP-v2.24-charter.md`](docs/ROADMAP-v2.24-charter.md)). P-UX-18
bounded the *initial* card DOM on huge runs, but once a placeholder
materialized its thumbnail lived forever — scroll a 10k wedding to the bottom
and you'd decoded 10k JPEGs into RAM (`loading="lazy"` only defers the first
load, it never reclaims). A second IntersectionObserver now keeps decoded
thumbnails to a window around the viewport: a card that recedes past ~3
viewports **parks** its `<img>` (src → `data-parked-src`, src cleared, so the
browser drops the decode) and restores it on re-approach. The card element,
its decision badge, keyboard index and focus are untouched — only the
`<img src>` toggles, and `.thumb-wrap`'s aspect-ratio holds the layout so the
scrollbar never jumps. Measured on a 600-row run: as materialized cards grew
100 → 352, **live thumbnails stayed pinned at ~48–76** (parked climbed to
276) — image RAM now decouples from run size, deliberately without touching
the fragile decision/render path.

**v2.23** — **`pip install pixcull` gets its rails + the audit queue closes**
(see [`docs/ROADMAP-v2.23-charter.md`](docs/ROADMAP-v2.23-charter.md)). Three
threads land together. **PyPI rail**: the package metadata is PyPI-ready with
a dedicated `README-PYPI.md` (the repo README's relative-path screenshots
render broken on pypi.org), the 13 locale JSONs now ship inside the wheel
(they load at runtime — without them `_t()` falls back to keys), `twine check`
passes on both wheel and sdist, and `release.yml` gains a token-gated
`Publish to PyPI` step so a `v*` tag auto-publishes once the owner adds a
`PYPI_API_TOKEN` secret (clean skip until then). **English-first first-run**
(2030Q3 audit): a fresh non-Chinese browser used to be forced into Chinese —
now `_getStoredLang()` detects `navigator.language` (with a `_normalizeLang()`
that mirrors the server's fold, parity-tested), the switcher cycle expands
from 3 to all 13 locales (+ RTL for Arabic), and the onboarding card — a new
user's very first interaction — speaks every locale via `_t()`. Verified: an
en-US browser boots to English onboarding ("Getting started"), review chip
("To review N"), the lot. **Shadow-queue unlock** (audit): the shadow
rescorer's model↔rule disagreements — the highest-value correction labels,
computed every run but never routed anywhere — now have a **⚖ Review
disagreements** button that opens a queue sorted most-confident-split-first;
deciding there writes straight to the correction set. (Flipping the rescorer
to *adjudicate* stays owner-gated — it needs those real disagreement labels
first; this ships the flow that collects them.)

**v2.22** — **the audit queue lands + the gallery wears the new skin** (see
[`docs/ROADMAP-v2.22-charter.md`](docs/ROADMAP-v2.22-charter.md)). The three
2030Q3-audit themes ship in one release: **i18n gap-fill** — the v2.15
session-close flow (待审 counter, completion chip, resolve-maybes queue,
hydration chips, four end-of-session toasts) finally speaks all 13 locales
(9 new keys × 13 files, native translations), and fixing it surfaced a
boot-order bug that would have voided the whole fix (dynamic strings rendered
before the async locale fetch resolved — now rebuilt after apply); the
born-dead `20-undo-stack` module (wrapped a `window.setDecision` nothing ever
assigned) is deleted. **Release rail** — a tag-triggered `release.yml` builds
the wheel, smoke-tests it in a clean venv and creates a GitHub Release using
only the built-in token; `sync-modelscope` stops failing red when the secret
is absent (warn + skip); the PyInstaller spec reads its version from
pyproject (it hardcoded "4.0.0" against pyproject's 2.19.0); version bumps
to 2.22.0 in lockstep. **CSS split** — `_assemble_css()` joins its JS twin
in the build: design tokens (370 lines) and the lightbox block (651 lines)
now live as `src/modules/*.css` behind `@@CSS:` markers, byte-identical
artifact, marker-discipline linted. And the **19-shot gallery is recaptured
on the Studio Neutral skin** with the real museum-artifact run rebuilt from
the source drive — every screenshot below except the two video frames (18/19,
pending owner-approved footage) now shows the current design.

**v2.21** — **"Studio Neutral": the research-driven design overhaul** (see
[`docs/ROADMAP-v2.21-design-charter.md`](docs/ROADMAP-v2.21-design-charter.md)).
A six-lens survey of the field (Narrative Select, Aftershoot, Imagen,
FilterPixel, Photo Mechanic, Lightroom, Capture One, plus Linear/Raycast-class
tool design and dark-UI color science) converged on one hard fact: **a
warm-tinted surround skews color judgment of the photos themselves**
(ISO 3664 viewing-surround guidance — every top tool judges on neutral gray;
PixCull's espresso brown was an industry outlier). The whole UI moves to an
achromatic studio ramp (#161616 → #1d1d1d → #242424 → #2e2e2e, c=0 in OKLCH)
with brand warmth concentrated in ONE champagne-gold accent (#d5b584, 3× the
old brass chroma) reserved strictly for selection/focus/CTA. The v2.3
"Double-Bezel tray" cards are retired — photos now fill the card edge-to-edge
with a hairline border, like every reference tool; the every-card amber
"needs-review" ring is demoted to a whisper; score numbers switch from
editorial serif to mono tabular; motion returns to flat ease-out (the 6%
overshoot spring now reserved for signature moments); radii tighten to the
pro register. The swap ran as a full-tree palette migration (~430
replacements across 24 files incl. the video surfaces' stray navy
mini-palette and three latent bugs: a dead `--surface-1` fallback, Tailwind
amber literals bypassing the semantic system, and the last hex-arithmetic
score ramp). Both themes stay; light mode becomes neutral paper. The 19-shot
gallery below still shows the previous skin — recapture is queued.

**DESIGN-AUDIT 2030Q3** — **the post-v2.14–v2.20 full-body recheck** (see
[`docs/DESIGN-AUDIT-2030Q3.md`](docs/DESIGN-AUDIT-2030Q3.md)). Five lenses
re-read the code and regrade every dimension: **3.1/5 overall (Q2: 3.0)** —
core UX 3.5→3.8, intelligence 3.1→3.5, architecture 2.5→3.2, reach 2.5→2.8,
plus a new release-&-CI-hygiene lens at 2.0 (no tag, no GitHub Release, no
published artifact since v0.7.0). The sharpest pure-code finding: the v2.15
session-close flow — Q2's own declared top-gap fix — renders entirely in
hardcoded Chinese for non-Chinese users, bypassing the mature 13-locale
`_t()` shim. Four ranked v2.21 candidates (i18n gap-fill · release rail ·
English-first first-run · CSS module split) plus the owner-only unlock list.

**v2.20** — **the video theme closes its loop + three long-standing tails**
(see [`docs/ROADMAP-v2.20-charter.md`](docs/ROADMAP-v2.20-charter.md)). Reel
candidates' `why` now mentions overlapping audio events (现场笑声/掌声/配乐);
and the review page's Keep/Cull — localStorage-only until now — persists
server-side and **teaches a reel taste profile** (keep-vs-cull signal contrast,
≥20-decision activation gate, ranking tilt capped at ±15%) that `pixcull reel`
applies next run: the video side finally learns like the photo side does.
Tails: the per-axis why-low reads real moment/aesthetic signals (blink,
non-peak burst frame, smile strength, CLIP-IQA/LAION scores); the Lr-sync
reload restores scroll+focus instead of dumping you at the top; and the ⌘K
palette becomes the 29th boundary-linted module.

**v2.19** — **audio reaches the timelines + the first shippable artifact**
(see [`docs/ROADMAP-v2.19-charter.md`](docs/ROADMAP-v2.19-charter.md)). The
learned audio tagger's events (laughter / applause / music) have been computed
since v2.1 and never drawn — both timelines now carry a bottom event lane
(kind-colored bands, emoji labels, span+confidence tooltips) on the /video
review page and the lightbox scrubber, riding along in /video/data and
PAYLOAD.video with graceful absence. And the distribution theme gets its first
concrete step: **`make wheel`** builds a verified `pixcull-2.19.0` wheel
(all templates/calibration data packaged, entry point intact, clean-venv
import smoke-tested; version single-sourced with a lockstep guard test) —
publishing to PyPI / a GitHub Release is a one-command owner action.

**v2.18** — **the 5k performance debt is paid** (see
[`docs/ROADMAP-v2.18-charter.md`](docs/ROADMAP-v2.18-charter.md)). The /rows
pagination endpoint was built in v0.13.5 "as the foundation for virtual
scroll" and never wired — big runs still inlined every row as JSON in the
HTML. Now the server inlines only the first slice (default 800,
`PIXCULL_INLINE_ROWS`) with full-run counts still computed server-side, and
the page hydrates the remainder in background chunks into the same rows
array every module shares — a live progress chip, a full sidebar/grid
rebuild on completion, and an honest degraded state on failure. Measured on
a 2,500-row run: **HTML 6.45MB → 2.53MB (−60%)**, all 2,500 cards rendered
post-hydration, zero JS errors. Also unearthed and routed around a latent
shadowing bug: the iOS slim /api/v1 rows alias had made the full-shape
endpoint unreachable since P2.1 — hydration gets its own `/results_rows/`
route (one row in the v2.16 table), the slim alias keeps serving iOS.

**v2.17** — **the glass box reaches video** (see
[`docs/ROADMAP-v2.17-charter.md`](docs/ROADMAP-v2.17-charter.md)). Photos have
had per-axis "why-low" prose since v2.9–v2.12; reel candidates only showed a
score. Each candidate now carries its **per-window sub-signal breakdown**
(camera-motion smoothness / content stability as window means, peak-instant as
window max) plus a deterministic **why-low line naming the signal that drags it
below the clip median** ("运镜平稳度拖分:0.32,低于全片中位 0.78") — computed
at generation time from the window's own signals, no models. The review panel
renders three labelled mini-bars + the amber why-low under each candidate,
ternary-guarded so old runs' JSON degrades gracefully. Same contract as the
photo side's `_axisWhyLow`.

**v2.16** — **paying down the monolith, slice 1** (see
[`docs/ROADMAP-v2.16-charter.md`](docs/ROADMAP-v2.16-charter.md)). The audit's
top-recommended theme, promised back in v2.4 and deferred for 11 releases:
serve_demo.py's seven inline HTML page blobs (~5,300 lines of raw
upload/verticals/admin/… markup inside Python strings) now live as real files
under `templates/pages/`, loaded through the same `_read_template` mechanism as
video_review/timeline — **18,225 → 12,884 lines (−29%)** with an AST-driven
extraction (shared design-tokens CSS re-spliced via a placeholder) and the only
acceptance bar that matters for a refactor: **all seven routes byte-identical
before vs after** (curl-diff), guarded by a new template test. **Slice 2 —
results.js modules**: eight clean-boundary subsystems (undo stack, Selects
mode, Smart Collections, bookmark/conflicts, marquee select, WebRTC,
onboarding, transparency hint — 802 lines) now live in `src/modules/*.js`,
re-spliced at build time via `@@MODULE:` markers with the artifact hash
**unchanged**, and a machine-enforced boundary lint (each module a single
self-contained IIFE; cross-module talk via `window.PixCull*` only) — cutting
off a stretch of the "one broken invariant → nine simultaneous bugs"
propagation path. **Slices 3+4**: twenty more mid-file subsystems (multi-tab sync, confidence modal, EXIF overlay, tour, …) extracted the same hash-preserving way — 28 modules / 2,160 lines total, results.js core down to 9.6k — and do_GET's 258-line if/elif over 65 paths became a declarative route table (31 exact + 30 ordered prefixes + 5 hand-written compounds), verified by a 31-route sweep: 28 byte-identical, 3 dynamic same-status. Adding an endpoint is now one table row.

**v2.15** — **the culling pass finally has a finish line** (see
[`docs/ROADMAP-v2.15-charter.md`](docs/ROADMAP-v2.15-charter.md)). The workspace
bar gains a live **待审 N** counter (photos still without a human-confirmed
decision — re-confirming the model also counts); at zero it flips to a
**"全部已审 ✓ · 导出 XMP"** completion chip that triggers the (previously
buried) XMP export with one click, and the state survives reload. A new
**◐ 决议 maybe** button enters a maybe-resolution queue — filtered to the maybe
band, sorted **most-ambiguous-first** (|P(keep)−0.5| from the v2.14 shadow
rescorer, score-based fallback), focus pre-placed on the hardest frame — and
auto-exits restoring your filter+sort when the last maybe is decided. The
keep↔maybe overrides this queue produces are exactly the corrective labels the
v2.14 gate ③ still needs — UX and the training loop close into one circle.
Also fixes a latent bulk-marquee bug (decisions patched only card DOM; rows[]
and header tallies went stale until the next repaint silently reverted them).

**v2.14** — **real-data learning: de-stub the "moment" axis so it can actually
be learned** (see [`docs/ROADMAP-v2.14-charter.md`](docs/ROADMAP-v2.14-charter.md) +
[`docs/DESIGN-AUDIT-2030Q2.md`](docs/DESIGN-AUDIT-2030Q2.md)). The audit found the
"moment" axis — the decisive-moment axis the product most loudly markets — was a
**constant 0.5 placeholder for every photo** in fusion, plus two of its three
rubric checks always returned `None`. A constant feature carries zero information,
so the rescorer could *never* learn it. Now `moment_score` is a real signal where
one honestly exists (wedding-moment confidence; face smile/eyes), left neutral
where no signal exists (landscapes unchanged); `emotion_present` is evaluated from
wedding-moment confidence **and** the face smile blendshape; and `action_at_peak`
now resolves from the burst-peak ranker — within a real burst, the crowned frame
*is* the captured action moment (singletons honestly stay unscored). The
once-constant "moment" axis is finally a learnable, non-degenerate feature. An end-to-end A/B regression caught a latent
**NaN→1.0 bug** (a pandas `None`→`NaN` slipped past an `is None` check and clamped
`score_final` to 1.0 = always-keep for every no-signal frame) — now fixed and
guarded by a test. The 400-sample real-label training session + flipping the
rescorer to adjudicate mode is owner-gated (fabricated labels poison the model —
the RESCORER-V3 lesson). Also wires **axis-aware personalization**: once you have
≥50 corrections, fusion's per-axis weights now *tilt* toward the axes you
demonstrably value (a composition-lover's runs reward composition-strong frames
and demote weak ones), not just a global threshold nudge — clamped to a gentle
±2× and a no-op without a profile (generic runs stay byte-identical, verified by
an A/B regression). Adds an **aerial scene** for DJI/drone footage: detected
deterministically from the drone camera's EXIF model code (DJI `FC####`; the
Mavic 2 Pro/3's Hasselblad `L1D-20c`/`L2D-20c`) — matching the *model*, not the
make, so a genuine Hasselblad body isn't mistaken for a drone — with a `DJI_`
filename fallback. Non-drone frames are untouched (16 real aerials → aerial,
10 Canon frames byte-identical in an A/B).

**v2.13** — **root-caused the "screenshot hang" and fixed a real UI bug**
(see [`docs/ROADMAP-v2.13-charter.md`](docs/ROADMAP-v2.13-charter.md)). The v2.12
"body-not-delivered to headless chromium" theory was **wrong**: the similarity
**slider simply never mounted** — `render()` only repaints the grid, never the
sidebar `#viewToggles` group that the slider lives in, and nothing called
`buildViewToggles()` after the fold toggle (this reproduces in a real browser, not
just headless). Fixed, then an adversarial review pass swept the **same bug class**
across the frontend and fixed **8 more**: preset-apply / ⌘K-reset / "reset all
filters" / Smart-Collection restore all left sidebar pills visually stale (and
"reset all" was silently *keeping* face/location/burst filters active; Smart-
Collection restore's `window.render()` was a dead no-op that never repainted at
all). The same dead-`window.render()` pattern also left **Selects mode (⌘1)**
completely inert — it set the filter sentinel but never re-rendered, and the
"keep + maybe only" filter was never actually wired into `render()`; it now
filters for real, with a brass top-rule cue. Plus a module-level debounce fix +
detached-node guards. A new DRY helper `_rebuildFilterControls()` keeps the
sidebar in sync with `filterState`.

**v2.12** — explanation goes one level deeper + local discoverability metrics
(see [`docs/ROADMAP-v2.12-charter.md`](docs/ROADMAP-v2.12-charter.md)). The verdict
glass box no longer just *names* the weakest axis — it says **why it's low**,
mapped from the row's own signals ("光线偏低 · 高光过曝 12%", "构图偏低 · 地平线倾斜
5°", "主体偏低 · 无明确主体"). And the transparency tools now record **local-only**
usage counts (`localStorage.pixcull_metrics`, never sent anywhere) so you can see
whether near-dup / Scenes / glass box actually get used. (The deferred
slider/face-Close-ups screenshots are best captured locally — the headless
capture is killed by the dev host; the features themselves are verified.)

**v2.11** — **discoverability + explanation** for the v2.9/v2.10 transparency
features (see [`docs/ROADMAP-v2.11-charter.md`](docs/ROADMAP-v2.11-charter.md) /
[`docs/DESIGN-AUDIT-2030Q1.md`](docs/DESIGN-AUDIT-2030Q1.md)). The near-dup fold +
Scenes toggles were buried in a burst-only sidebar group that **vanished on
burst-less runs** — they now live in an always-visible **「整理 · 折叠」** group, so
the tools are findable on every run (this also un-broke the similarity slider,
whose CSS had been mis-scoped since v2.9). A one-time **coachmark** introduces the
transparency trio, and the verdict glass box's one-liner is now a **per-axis
driver** — "构图 4.8★ 撑分,光线 2.5★ 拖后腿" straight from the rubric.

**v2.10** — polish on the v2.9 transparency slices: **Scenes** now also renders
**inline section headers** in the grid (time-ordered, header per scene — not just
the navigator strip), and a **face Close-up click locates that face on the main
photo** (a pulsing box maps the crop back onto the full frame). Small-batch grids
(≤200) get the inline sections; larger keep the navigator.

**v2.9** — **transparency + content-first viewing** (the deferred competitor
patterns from the v2.8 reflection — see [`docs/ROADMAP-v2.9-charter.md`](docs/ROADMAP-v2.9-charter.md)
and [`docs/DESIGN-AUDIT-2029Q3.md`](docs/DESIGN-AUDIT-2029Q3.md)): a
**similarity slider** turns the near-dup fold from a fixed-threshold black box
into a glass box — drag 0.80–0.99 and the grouping re-folds live (Peakto-style) ·
a **face Close-ups rail** in the lightbox shows a zoomed crop of every detected
face so you can check eyes / expression without manual zoom (Narrative Select) ·
a **Scenes** navigator segments a shoot by capture-time gaps (adaptive median+MAD)
into a time-grouped narrative · a **verdict glass box** makes the inspector's
default read a single line — "why this decision" — and folds the per-axis
breakdown behind one tap (progressive disclosure).

**v2.8** — UI/UX **subtraction** + colour-system pass: grid cards shed the badge
wall, decision badges go **outline** (not solid fills), the lightbox gains a
discoverable **"zen" toggle** (`i` key / button → photo claims the full
viewport), header stats + toolbar move to **progressive disclosure / grouping**,
and the palette becomes an **OKLCH three-variable system** (base / accent /
contrast → relative-colour-derived surfaces, with a hex fallback for older
engines). Two lightbox **freeze** root-causes fixed. Editorial restraint after
Linear / Narrative Select — see
[`docs/DESIGN-REFLECTION-v2.8.md`](docs/DESIGN-REFLECTION-v2.8.md).

**v2.7** — four intelligence slices: **bilingual reel captions** (zh + en,
locale-selected) · **cross-shoot dedup** (`pixcull dedup-across` — the same
frame recurring across separate sessions) · **video duplicate-frame trimming**
(`pixcull trim-dupes` — dHash near-static runs) · **self-hosted VLM ONNX**
(BLIP → onnxruntime; real-export captions match transformers, no transformers
needed at inference).

**v2.6** — CLIP **visual near-duplicate fold** (catches the re-shot composition
that time-bucketed bursts miss; ≈N badge → side-by-side compare) + lightbox-
freeze & thumbnail-starvation stability fixes.

**v2.5** — single-file frontend split into a **build artifact**
(`templates/src` + `make results-html`) · **contact-sheet / client-proof PDF**
export (`pixcull contact-sheet`).

**v2.4** — intelligence + workflow: **personalisation-from-corrections**
(threshold shift learned from your edits) · keyboard-first cull loop ·
**natural-language semantic search** (CLIP) · audio-threshold calibration
(laughter recall 0.25→0.85) · burst **"collapse to peak"** + ⧉N stack · true
**VLM best-frame caption** (opt-in BLIP).

**v2.0–v2.3** — **video culling + reel pipeline** (temporal scoring / shake-blur
cull / audio-event tagging / GoPro·DJI GPMF / reel auto-assembly + export
presets) · **editorial-warm** rebrand (espresso + brass, vendored Geist).

**v1.0** — learned **rescorer** · **bias-audit dashboard** · per-axis
**attribution heatmap**.

**v0.9** *(in flight)* — Brand identity refresh (signature gradient
+ logo redo + serif accent) · Hero reveal "first 2 seconds" signature
moment · soft-bounce motion curve project-wide · ⌘K command palette
(27 actions, fuzzy match, recent-used). See
[`docs/ROADMAP-v0.9-charter.md`](docs/ROADMAP-v0.9-charter.md).

**v0.8** — i18n 中 / EN / 日 · LAN collaboration (event token + 5s
polling + conflict markers) · style clone V2 (CLIP embedding
centroid) · short links + QR + share-URL modal · structured CSV /
JSON export (annotations + style distances joined) ·
[`docs/ROADMAP-v0.8-charter.md`](docs/ROADMAP-v0.8-charter.md).

**v0.7** — A/B compare modal redesign · annotation rubric modal
redesign · 5k+ photo stability (IndexedDB adapter) · Loupe RGB
readout · Inspector mobile bottom-sheet · view-preset v2 ·
`/share/<run>/<token>` · style clone V1 · tethered live · Sparkle
auto-update infra · `/history`. See
[`docs/RELEASE_NOTES-v0.7.md`](docs/RELEASE_NOTES-v0.7.md).

---

