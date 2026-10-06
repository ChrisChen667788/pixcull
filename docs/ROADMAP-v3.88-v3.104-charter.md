# PixCull v3.88 → v3.104 charter — seventeen days nobody was looking

Written 2026-10-01. v3.87 shipped on 2026-09-13 and then nothing did.

Work stopped on a usage limit in the middle of a sweep for unfinished
items, and the sweep itself died with twenty-one of its checks unrun. In
the seventeen days after that:

| | |
|---|---|
| scheduled CI | red on 2026-09-21 and again on 2026-09-28, unanswered |
| issue #2 | Windows users cannot change drive in the folder browser — opened 09-28, no reply |
| issue #3 | offline, every model cached, 149 s and 0 of 23 analysed — opened 09-28, no reply |
| fortnightly competitive refresh | ran 09-16 with no permission to search the web and produced nothing; did not run 09-29 or 10-01 |
| releases | 51 commits past v3.53.1, the last tag and the last version on PyPI |

None of it needed the owner. That is the finding of this block before it
has a first version: the open-items ledger sorted work into "waiting on a
person" and "not waiting on a person", and the second list sat as still
as the first. `docs/OPEN-ITEMS.md` already says *before recording
something as blocked, try it*. This block is that sentence applied to the
things nobody had recorded at all.

Two tracks. The first is what a stranger hits: a red build, two issues, a
Python version that cannot install, a feature the PyPI page advertises
and the product never runs. The second is the measurements the blind
correction set unblocked on 2026-09-12 and that are still unmeasured.
Owner-gated work is listed at the end with the exact thing each is
waiting for, and is not scheduled.

---

## Shipped while this was being written

### v3.88 — the scheduled run was red for nine days on a three-node model

CI resolved `onnx` 1.23 (writes IR 14) beside `onnxruntime` 1.30 (reads
13). One test had pinned the IR version by hand; its sibling had not.
Test models are built in one place now and a test fails any built
elsewhere. The product side of the same refusal: `OnnxTagger.available()`
said yes to a model the runtime would not open; it decides by loading.

### v3.89 — with every model on disk, the run still asked the network first

Issue #3, first half. v3.64 fell back to the disk *after* the hub
attempt failed, so an offline run worked and paid one connect timeout
per model load per worker. Measured with the socket layer blocked,
loopback included: 48 attempts on 32 photos before, none after, every
verdict the same. Two things the investigation predicted and the
measurement did not find — pyiqa and rembg open no connection on a warm
cache — are recorded as measured and left alone.

**The review found what the gate could not.** The new test's skip reason
was not in the CI skip ledger, which only a real CI run audits; it would
have gone red on the push.

### v3.90 — a run that had died was reported as still running

Issue #3, second half. Failure reasons went to stderr and were kept
nowhere; `run_pipeline` returning was recorded as `done`; eleven routes
answered 425 "pipeline may still be running" for any missing result.
Reasons are kept and summarised beside the run, a run that produced
nothing is an error with its cause, and one function decides when 425 is
true.

---

## What a stranger hits

### v3.91 — a Windows user cannot leave the C: drive

Issue #2. The folder browser's quick links are `~`, Pictures, Desktop,
Downloads and `/Volumes`. The server already accepts any absolute path —
the reporter verified `{"path": "F:/"}` — so the defect is that the page
offers no way to ask. The reporter attached a working patch (drive
letters A–K, shown by user agent) and offered a PR.

**Shipped 2026-10-02, and the decision made itself.** While this charter
was being written the reporter opened PR #4, four commits that each stand
alone. The second is this fix, and it already does what the measure below
asked for: `/browse` reports the drives that exist rather than the page
guessing eleven letters. It was cherry-picked with its author intact.

**Measure, met:** on Windows the browser lists the drives that exist and
navigates into one — verified by the author on a real machine with nine;
on macOS and Linux nothing changes. Added here: the enumeration in a
function that can be tested without drive letters, the wiring through
`/browse`, and a real-browser pass with two pretend drives.

**Still open on that PR:** three more commits, each read by a reviewer and
a skeptic, none mergeable as written.

* *CJK watermark fonts.* The list tries `C:/Windows/Fonts/arial.ttf`
  before any CJK font, and on a Mac with Arial installed Pillow resolves
  that path by name — so the watermark is Arial, which has no CJK glyphs,
  and the tofu the commit fixes is still there. Reproduced here.
* *Client review sheet.* The copy list now reads `1. DSCF1234 ★★★` and
  `parse_picks` was not taught it: every line comes back with two "could
  not read" warnings. Reproduced here. Two touch targets are 40 and 42 px
  against the 44 it claims.
* *Light-theme overlays.* The drag properties sit in `results.css` with
  no selector around them, so `touch-action: none` applies to nothing and
  the toggle cannot be dragged by touch.

None of the three brings a test, and the description puts "Closes #3"
under the overlay fix; #3 is the offline issue.

### v3.91.1 — the lane that runs the real models had run nothing

Not planned; found on the way. After v3.89 was pushed the weekly
"real-model integration" lane was dispatched by hand, to see the new
offline test run where the skip ledger said it would. The lane went
green. Its log was five `SKIPPED` lines and no test: nothing in it
downloads the weights its tests wait for, and it has read that way on
every scheduled run looked at. v3.61 had written, in that lane's own
comment, that "covered elsewhere" is only true if somewhere covers it —
and checked that the lane named the test.

**Measure, met:** the lane downloads CLIP, BLIP and DINOv2 before
testing, missing weights fail there instead of skipping, and its log
shows tests that ran — five passed and one deliberate skip, on torch
2.14 and transformers 5.18, against a hub it reached for real.

It took two tries. The first run that reached a model died on the lane's
own pin: `torch==2.4.1` under a transformers that will not use a torch
older than 2.5. The skips had been hiding that too.

### v3.92 — the oldest torch we promised was one we could not use

Not planned; found when v3.91.1 made the real-model lane run.
`pyproject.toml` declared `torch>=2.2,<3` beside `transformers>=4.40,<6`.
transformers raises its own torch requirement as it goes — 5.6 wants
2.4, 5.18 wants 2.5 — and below it does not fail: it disables PyTorch and
every model class then says "PyTorch was not found", with torch
installed. A fresh install never sees it. An environment that upgrades
one and not the other does, and the Dockerfile pinned 2.4.1 beside an
unpinned transformers.

**Measure, met:** the floor is 2.5 in the package, the image and the
Studio; the hermetic and browser lanes are pinned to exactly the floor,
so the oldest torch promised is one that is run; and
`tests/test_torch_floor.py` asks transformers whether it will use the
torch it finds. That last one is the point — the bar will move again,
and it will move in that lane first.

### v3.93 — two things the package describes and cannot reach

**`pixcull video` has never listened to the audio.** Found while fixing
v3.88. `run_audio_analysis` was added in v2.0-P1-3 on
2026-05-29 and **nothing in the package has ever called it**.
`audio_events.json` has three readers — the reel caption, the review
page's event lane and the lightbox scrubber — and no writer. The learned tagger of v2.1 and v2.2 ("auto-promotes
from `~/.pixcull/models/`") is reachable only from its own eval script.
`README-PYPI.md` lists "audio events (laughter / applause / music)" as
something you get.

The shape is this repository's most-repeated one: capability built,
tested in isolation, never wired, and described in public as present.

**Measure:** `pixcull video` on a clip with sound writes
`audio_events.json`; the reel candidate's reason and the review page
show what it found; with a model installed the learned tagger runs, and
without one the DSP detectors do. A wiring gate fails if
`run_audio_analysis` loses its caller again. **Wrong, not late:** if
wiring it is declined, the PyPI line is removed instead — one of the two
has to stop being false.

**Shipped, with one clause of that measure re-derived.** The PyPI line
came out for the 3.92.0 upload and went back, conditioned, with the
wiring. On a ten-second clip of a synthesised chord progression the
installed model marks music from 0.0 to 9.6 s, the file is written, and
all seven reel candidates' reasons carry it.

"Without one the DSP detectors do" was wrong, and this charter wrote it.
`docs/AUDIO-TAGGER-EVAL.md` is the only audio measurement the project
has: on 64 real clips the DSP detectors found none of 20 applause clips
and were right about laughter 12% of the time (macro-F1 0.075, against
0.933 for the learned model at its calibrated thresholds). The model is
optional, so the DSP path is what most installs would have run, and the
readers print what they are given. Events come from the learned tagger
or the file records that nothing listened, with one of five reasons the
review page has words for. The DSP tempo and beat grid are still
written; nothing reads them yet.

Still unwired and now written down: `audio_moment_boost`, which would
feed events into the moment axis. That changes reel ranking and wants a
measurement before it wants a caller.

**The review found what a first writer brings with it** (fixup). Five
lenses, each finding handed to a second reader told to refute it; nine
stood and none was refuted. The first run of that review died on a usage
limit with nothing examined and reported zero findings, and was run
again in full. What changed:

* `--no-audio` and a failed pass left the previous run's
  `audio_events.json` in place, and all three readers take whatever is
  there. Neither could happen while nothing wrote the file.
* The pass found its clip by there being exactly one directory under
  `video_frames/`, so a second clip imported into the same output made
  it raise — and then caption the second clip with the first one's
  events. The command passes the directory it just extracted.
* The explanation for an empty lane was written into the review page
  and not the lightbox, which reads the same file through a different
  payload. It is worded once in the server and sent to both.
* The audit subprocess's `PYTHONPATH` was joined with a literal `":"`.

Two findings were declined as stated: ledger rows for "node not
installed" and "ffmpeg not installed". The ledger records reasons a CI
run prints, and a row would pre-approve a skip nobody has seen; the node
test went away with the JavaScript it ran, and the ffmpeg reason is the
one three older files already use on a lane that installs ffmpeg first.

**And the delivery-audit page looks for a script that is not there.**
Reported by gxfc9867 in PR #4. `serve_app.py` resolves
`Path(__file__).parent / "cli_audit.py"`; the script is
`scripts/cli_audit.py`, which is not in the package at all. The path it
builds does not exist in a checkout either — the reporter saw the page
answer 500 — and from `pip install` there is nothing it could find.
The same shape as the audio pass, from the other side: that one was built
and never called, this one is called and was never shipped.

**Measure:** the page renders from an installed wheel, and the packaging
test fails if a module `serve_app` loads by path is not in the wheel.

**Shipped, first half.** The audit is `pixcull.report.cli_audit`, run by
module name; the route is exercised through the real handler and a real
subprocess, and the audit is run with a copy of the package alone on the
path. The second half — a gate over everything the package loads by path
— is v3.93.1, because looking for it found five more.

### v3.93.1 — what else the wheel does not carry

Not planned; found by sweeping for v3.93's defect class instead of its
instance. Four search angles over the package, each finding re-checked
against the published 3.92.0 wheel by a second reader told to refute it.
Nine findings stood, one was refuted (`composition_classifier`'s model
path has no caller in the pipeline). Beyond the audit script:

* **Face detection cannot work from a wheel.** `detectors/face.py` loads
  two MediaPipe model files from `pixcull/detectors/_models/`. They are
  tracked in git and the build allowlist has no pattern for them, so the
  wheel has neither. `_lazy_init` returns False and `analyze` returns an
  empty result — "silently no-op", in its own comment. `pip install
  'pixcull[face]'` installs MediaPipe and still detects no face:
  `face_count`, blink, closed-eyes and face-blur are absent on every
  installed copy. The largest of the five and the least visible.
* **`/retrain` fails on every installed copy.** It imports
  `build_axis_training_set` and `train_axis_rescorers` from `scripts/`.
  The auto-retrain after ten corrections reaches the same worker.
* **The vendored font and the PWA icons are 404.** `/docs/brand/*`
  resolves against the repository root; from a wheel that is
  `site-packages/docs/`. Pages fall back to system fonts.
* **User LUTs have nowhere to go.** `color_grade.LUTS_DIR` is the
  repository's `luts/`; from a wheel it is `site-packages/luts`.
* **The sample-data button answers 500.** It says "samples/ not bundled
  with this build", which is accurate, under a button that is still shown.

**Measure:** each of the five either works from a wheel or says, where
the user is, that it needs a checkout; and a packaging test fails when a
file the package opens relative to itself is missing from the built
wheel — the test v3.93 was chartered to leave behind.

**Shipped, measure met.** Checked from a built wheel unpacked on its own,
with nothing of the checkout on the path: the detector finds the face in
the public-domain astronaut image; the font, the four illustrations and
the icon answer 200; the sample run and retraining report themselves
unavailable. The face models, the font and the art move the wheel from
1.9 MB to 6.9 MB. Three of the five work from an install (faces, assets,
LUTs in `~/.pixcull/luts` or `PIXCULL_LUTS_DIR`); two say they need a
checkout (retraining, the sample run), and the tenth-correction
auto-retrain no longer starts where it can only fail.

The gate is two tests in `tests/test_packaging.py`: every path the
package builds from its own location resolves to something in the wheel,
and every `/docs/brand|illustrations/…` URL a page asks for is shipped.
Five paths that climb out of the package on purpose are listed with the
reason an install does not need them; an exemption whose path is no
longer built fails too.

Found on the way and also fixed: from an install, `/docs/…` fell back to
the directory above the package — site-packages — and would serve any
file under it. It reads the package's `report/static/` and, in a
checkout only, the repository's `docs/`.

Not done, and written down: retraining *from an install* is a feature,
not a fix. The pipeline reads per-axis heads from the working directory
and then the packaged copies, so a head trained into `~/.pixcull/models`
would be trained and never read; making it work means a third place the
pipeline looks, which changes scoring for anyone who retrains. The PWA
manifest now names one SVG icon at any size; whether every browser
accepts that for installation was not tested. And
`scripts/brand/gen_brand_svg.py` no longer reproduces the committed
`pixcull-vertical-poster.svg` (three fill colours differ) — left as it
was, for the documentation-truth versions below.

### v3.94 — Python 3.13 is refused at install

`requires-python = ">=3.11,<3.13"`. The ceiling exists because
`serve_app.py` parses multipart uploads with `cgi.FieldStorage` in two
places and 3.13 removed the module. 3.13 has been out for two years.

**Measure:** both call sites replaced; a 3.13 lane in the CI matrix
installs and passes the hermetic suite. **May close as measured and
declined** if a hard dependency has no 3.13 wheel — in which case the
ceiling stays and the README says why, which it does not today.

### The first release since 3.53.1 — done at v3.92, not after v3.94

Planned for after v3.94; the owner asked for it on 2026-10-02 so that
issue #3's fix would reach `pip install`. `v3.92.0` is tagged, on GitHub
as a release with its wheel and sdist, and on PyPI. Before the upload
the PyPI page lost a sentence that was not true (audio events) and
`CHANGELOG.md` gained "Upgrading from 3.53.1": twenty candidate changes
drawn from thirty-six versions of history, each checked against the code
at the tag and at HEAD.

What that release does not contain is v3.93 and v3.93.1 — so on PyPI
today the delivery-audit page is still 500 and face detection still
cannot run. The next upload is the owner's call.

---

## What the correction set unblocked and nobody measured

158 blind corrections arrived on 2026-09-12 with `readiness()` reporting
ready. OPEN-ITEMS recorded that they unblock v2.83, v3.8 and the second
half of v3.29. All three are still unmeasured.

### v3.95 — `audit_labels` reads a blind sheet as an empty inventory

It iterates JSONL; the blind sheet is one object with a `verdicts` map;
so handed the blind file the provenance guard returns nothing, which
reads exactly like "audited, nothing wrong". `load_blind_sheet` is the
bridge and nothing calls it from there. Recorded in v3.79, not fixed.

**Measure:** the blind file audits as 158 human labels; a sheet with a
non-human row is refused.

### v3.96 — v3.29's second half: what the non-human rows did to the numbers

`evaluate()` with and without the rows v3.29 learned to exclude. If the
difference is material, every personalisation figure published before
v3.29 was computed over polluted labels and should say so.

**Measure:** the delta, with its sample size. No threshold decided in
advance turns a small delta into "fine".

### v3.97 — the singleton analysis, with the right vectors

Three of four blocks showed a frame with no near-duplicate is culled more
often. The test of the one remaining explanation was withdrawn because
it fed CLIP vectors to a function that groups on DINOv2.
`burst_embeddings.npz` has existed since v3.84.

**Measure:** the scene-misclassification hypothesis confirmed or
eliminated. Either result closes the entry; no rule ships on
three-of-four.

### v3.98 — v2.83: does the personal profile generalise

**Measure:** `evaluate()` across the two shoots in the correction set.
One shoot is memorisation and is reported as such.

### v3.99 — v3.8: one taste profile for two different jobs

**Measure:** per-vertical k-fold F1 on 79 landscape and 79 portrait
corrections, against the single profile. Needs a loader for a
corrections file, about fifteen lines.

---

## What the documents say that the code does not

### v3.100 — the README disagrees with itself about its own default

One paragraph says `vlm_authority` ships `primary`. Eighty lines on,
another says it ships `off`. `cli.py` says `primary`. Also: "614 tests passing", "1,200+ tests
across 88 files" and "240+ 用例" in one file, against 2,852 test
functions in 242; `CONTRIBUTING.md` says 240+ and points at a path that
moved.

**Measure:** each number generated or gated, both languages. A count
written by hand is wrong by the next release.

### v3.101 — the user guide teaches a feature removed in v3.78

`docs/USER-GUIDE.md` lists `A` for the attribution heatmap and has a
section and a screenshot for it. The retired-screenshot gate reads the
READMEs and not the guide.

**Measure:** the section is gone and the gate reads every document that
embeds a screenshot.

### v3.102 — "the faces are frosted" after v3.87 found the guard cannot certify it

**Measure:** the caption claims what v3.87 established and no more, in
the README and the ModelScope card.

### v3.103 — thirty-nine colours written as literals where a token exists

Mechanical. Not ratcheted, blocks nothing, and has been "still open"
since v3.71.

### v3.104 — the ledger, and the competitive refresh that did not run

Close the OPEN-ITEMS rows that are closed in the code (three skip-ledger
gaps, the `import-catalog` traceback, the synthetic `24-transcript-edit`
that v3.77 replaced). Run the refresh the schedule missed twice, by hand,
under `docs/COMPETITIVE-REFRESH-PROTOCOL.md`.

**Owner:** the scheduled task has no web-search permission, which is why
its 09-16 run produced nothing. Granting it is a settings change.

---

## Waiting on a person, and for what

Not scheduled. Each names the one thing that moves it.

| what | waiting for |
|---|---|
| PyPI release | `gh secret set PYPI_API_TOKEN`, then `workflow_dispatch` with the opt-in |
| v2.49 M3 eval → v2.50 default and 47 public claims → v2.51, v2.52 | a new MiniMax key — the old one was pasted into a session and must be revoked |
| v2.91 prompt A/B; v3.3, v3.4, v3.5, v3.6, v3.11, v3.17, v3.18; the 2,400-call block | the same key, and `PIXCULL_LLM_BUDGET_YUAN` raised past the estimate |
| v2.80, v2.88, v2.89 | raters who are working photographers and not the author |
| v3.9 | real use of the compare view, accumulating preferences |
| v3.12 | the owner reviewing with `PIXCULL_MEASURE_STRIP=1`, five bursts per arm |
| seven stale screenshots (04, 14, 21, 22, 24-review-sheet, 25, 26) | a person at the machine; 14 cannot be scripted (v3.86) |
| `proof_sheet` / `view_folder` overwrite | a decision: refuse without `--force`, or document |
| signed installers | Apple Developer, SignPath, a published GPG key |
| ModelScope uploads from this machine | a rotated token (`CI`'s works) |

Two things the labels showed that are not on any list, because they are
product questions and not engineering ones. The rule stack keeps what
this photographer culls and never the reverse — 27 to 0. And nothing the
rubric measures separates those frames: what is visible in them is a
coach, a railing, a walkway. A dimension the rubric does not have cannot
be weighted.
