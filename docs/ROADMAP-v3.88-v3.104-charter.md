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

The review of this version (five lenses, every finding handed to a
second reader told to refute it) confirmed five and refuted one. Three
were fixed before release: the face notice reached only the terminal, so
a run analysed through the browser — most of them — said nothing; it is
on the results page now, decided from the run's own `face_count` column
rather than from the server's install. "MediaPipe is installed" was
decided by `find_spec`, which never runs the package, so one that could
not load passed; the check imports it now. And bounded by `docs/`, a
sideways step such as `/docs/brand/../ARCHITECTURE.md` stayed inside the
bound and was served from a checkout; each prefix reads its own folder.
The other two were declined: a reviewer recounted the commit message's
gate line with a different set of excluded files (the local gate leaves
out three, as CLAUDE.md says; CI leaves out two) and got a different
number, which is not a defect; and four failures in
`tests/test_v1_1_scripts.py`, a file every gate excludes and this
version did not touch.

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

### v3.93.2 — PR #4 lands, with the brace it was missing

Not planned. gxfc9867 answered the review of 2026-10-02 on 2026-10-04:
the three remaining commits, rebased on v3.92, each with the fix and the
test asked for. The PR's CI had two red lanes and both were real.

* **Browser lane.** The drag-CSS fix restored `.buckets-toggle {` and not
  its `}`. Chrome reads CSS nesting, so the sheet parsed: every later rule
  became a rule inside the toggle and matched nothing on the page. The
  brand mark, the wordmark and the export button fell back to the
  browser's dark-mode link blue (`test_visual_smoke`), and client-present
  mode showed verdicts and scores (`test_client_present`). The PR's test
  looked for `cursor: grab` within 900 characters of the selector — text
  present, rule unbound. Reproduced locally: the client-present test
  fails with the brace missing and passes with it.
* **Hermetic lane.** The font-order test replaced `ImageFont.truetype`
  with one that always fails. Pillow 12's `load_default(size=…)` — the
  lookup's last resort — calls `truetype` itself, with the bundled font
  as a file object, so the test broke the fallback it ends on. A test
  defect, not a product one; reproduced on Pillow 12.2.

Landed as the contributor's three commits, cherry-picked with authorship
and `-x`, and one commit of ours: the brace, the test's interception
narrowed to the lookup's own paths, and `tests/test_stylesheets_are_well_formed.py`,
which counts braces in every stylesheet the product serves — the source
CSS, every `<style>` in the built page and the page templates, and the
proof sheet's template.

Reviewed before pushing (three lenses, each finding handed to a second
reader told to refute it): three stood, none refuted. The numbered-line
parsing the PR added read everything after "12. " as a label, so a reply
of "12. 3-5" returned photograph 12 and dropped 3 to 5 without a problem
reported — the failure `parse_picks`' own docstring forbids; a rest made
only of numbers and ranges is read as picks now. The sheet's items are
JSON inside a `<script>`, and a filename containing `</script>` ended the
block (older than the PR). And the stylesheet gate read template files
only, missing eleven `<style>` blocks written inside Python; it reads
those too, and names its sources instead of counting them.

### v3.94 — Python 3.13 is refused at install

`requires-python = ">=3.11,<3.13"`. The ceiling exists because
`serve_app.py` parses multipart uploads with `cgi.FieldStorage` in two
places and 3.13 removed the module. 3.13 has been out for two years.

**Measure:** both call sites replaced; a 3.13 lane in the CI matrix
installs and passes the hermetic suite. **May close as measured and
declined** if a hard dependency has no 3.13 wheel — in which case the
ceiling stays and the README says why, which it does not today.

**Measured first, then shipped.** On a standalone CPython 3.13.15 with
the ceiling lifted in a copy of the tree: every core and dev dependency
installed, and so did the `[face]` extra — MediaPipe 0.10.35 publishes
`py3-none` wheels, so the README's "0.10.x ships no wheel above 3.12"
had stopped being true. Importing the package, only
`pixcull.report.serve_app` failed (`No module named 'cgi'`), and no other
module removed by PEP 594 is imported anywhere in it. With `cgi`
replaced, the whole suite passed on 3.13: 3161 passed, the eight failures
all from that copy having no git history.

`multipart` 2.0.1 (MIT, no dependencies) replaces `cgi.FieldStorage` at
both sites. Two defaults are set on purpose: the part limit of 128,
raised to the server's file limit plus headroom (an upload may carry
500), and spooling — parts over 64 KB go to temporary files, as before.
Spooled parts are closed after use. The upload had never been tested
over HTTP; `tests/test_runs_on_python_313.py` sends real bodies.

The floor cannot run on 3.13: torchvision 0.20.1 has no cp313 wheel; the
oldest pair that installs there is torch 2.6 / torchvision 0.21. So the
hermetic lane is a matrix — 3.12 pinned at the floor, 3.13 floating — and
`tests/test_torch_floor.py` reads pins from the matrix and requires the
newest advertised Python to run the whole suite. `requires-python` is
`>=3.11,<3.14`: 3.14 is not run anywhere yet, so it is not promised.

Reviewed before pushing (three lenses, each finding handed to a second
reader told to refute it; the first run died on a usage limit with
nothing examined and was rerun in full). Four stood, none refuted:

* **A blocker in the vertical upload.** It passed a missing
  `Content-Length` to the parser as -1, which reads until the client
  closes the connection; a keep-alive client never does, so the server
  thread waited forever. The photo upload already refused that; the
  vertical one does now, and `_multipart_parts` refuses an unknown length
  for any caller. Tested over a raw socket left open.
* The 8 MB default on in-memory parts, found by measuring before the
  review ran: 300 photographs of 60 KB were refused and reported as too
  many files. The cap is sized from the part limit now.
* The test said a 3 MB RAW "must not be read back whole" and checked only
  hashes; a handler reading it whole passed. It checks the copy now.
* "The package the standard library's deprecation notice names" was
  loose: the name is in the documentation's `cgi` deprecation note ("the
  email.message module or multipart for POST and PUT"), not in the
  module, and beside an alternative. The wording says so.

**Fixup, after the push: the floor lane went red, and it was not us.**
transformers 5.19.0 was uploaded at 16:38 UTC on 2026-10-06; the push's
CI installed it at 16:59. It still declares `torch>=2.5` and
`is_torch_available()` still accepts 2.5.1, then `get_device_type()`
calls `torch.accelerator`, which torch added in 2.6, so `CLIPModel`
cannot be imported. The 3.13 lane (torch 2.14) and every floating lane
were green; only the lane pinned to the floor saw it, and only through
`test_a_model_class_can_be_reached` — the assertion that asks transformers
whether it will use the installed torch said yes.

The first fix raised the floor to 2.6, checked on this Mac: 2.5.1 failed,
2.6.0 passed. CI failed it again. In torch 2.6
`current_accelerator()` raises when there is no accelerator — its own
docstring says so — and a Mac has one (MPS), so the check could not see
it; from 2.7 it returns None, which is what transformers expects. The
second check ran where CI does, in a CPU-only Linux container, with 2.6
as the control: 2.6.0 fails there, 2.7.1 passes. The floor is 2.7 in
`pyproject.toml`, both pinned lanes, the Dockerfile and the Studio, and
the upgrade notes say so — before 3.94.0 went to PyPI, which is the
point of having the lane.

The same push also carried the 30-second film (`docs/video/`), which
found two gates narrower than their descriptions — the ModelScope sync
hosted images only and its trigger test kept its own pattern — and one
that assumed every README image was an SVG. GitHub does not play an mp4
from the repository, so README.md links jsDelivr's copy.

### v3.94.1 — on Windows, Python 3.13 needed a compiler to install it

Found while checking whether issue #3 could close. Trying the released
3.94.0 in a clean Linux container failed before PixCull ran:
`imagededup` would not build. It is a base dependency that nothing in the
package imports (near-duplicates are CLIP and DINOv2), with wheels for
Python 3.9-3.12 only and a mandatory C++ extension. Resolved for Windows,
Python 3.13, binaries only, 3.94.0 stops at "No matching distribution
found for imagededup"; every CI runner has a compiler, so nothing saw it.

- `imagededup` removed from the package, the Studio requirements and the
  app spec. Removing it found `scipy` imported (detectors/canon.py) and
  guaranteed only by that tree; it is declared now (>=1.13, the first
  built against numpy 2).
- `tests/test_declared_dependencies.py`: a declared dependency nothing
  imports fails, and so does an import nothing declares, each exception
  named with its reason (`safetensors`, `jinja2`; the guarded optional
  imports).
- `scripts/check_installs_without_compiler.py` and a CI job: resolve the
  whole tree for Windows x64, Apple Silicon and Linux x86_64 on every
  advertised Python with `--only-binary=:all:`, from PEP 658 metadata,
  and build any sdist-only dependency to prove it is pure (`openai-clip`,
  under pyiqa, is). Its first Linux run reported safetensors as needing a
  compiler: pip does not expand a PEP 600 manylinux tag, so given
  manylinux_2_28 alone it refused every manylinux2014 wheel. The Linux
  target lists the whole glibc-2.28 tag set now, and a test holds it.
- Holding the README to that list: the platform badge claimed Intel Macs,
  for which torch has published no wheel since 2.2.2. It says Apple
  Silicon.
- The headless-Linux `libGL.so.1` requirement is in the install notes
  (also found in the container), and the socket-level offline test covers
  DINOv2 and the aesthetic axis's pyiqa models; the real-model lane
  fetches their weights through the product's loaders.

**Fixup: the aesthetic axis was missing from fresh installs.** The new offline test for the aesthetic metrics failed in both
hermetic lanes — not for want of weights, but on `import clip` before it
reached for any: openai-clip 1.0.1 does `from pkg_resources import
packaging` (line 6), setuptools 82 (2026-02-08) removed pkg_resources, and
torch 2.13+ requires setuptools>=77.0.3, so CI and every fresh install since
2026-07-08 got 84 — every PyPI release of PixCull postdates that. (torch 2.11
and 2.12 pinned setuptools<82, so installs from 03-23 to 07-08 were spared;
from 02-08 to 03-23 torch 2.10 pulled the newest setuptools on Python 3.12+.)
`AestheticScorer` caught the ImportError (v3.60's "missing pyiqa costs one
axis, not the run"), so the run went on with five axes and a warning telling
the user to `pip install pyiqa`. Reproduced on the released 3.94.0 in a fresh
Python 3.13 venv: no aesthetic metrics. This laptop never saw it — its venv
has setuptools 81. `_pkg_resources_for_openai_clip` supplies `packaging`
under that name for the import only and removes it after; tested against the
real openai-clip with pkg_resources blocked, control included. After the fix
the same venv scores laion_aes 4.232, clipiqa 0.437.

The same CI run failed the new install check on Windows and macOS with
nvidia-nccl-cu12 / cuda-bindings: `pip --platform` changes the accepted tags
but evaluates environment markers for the runner, so torch's Linux-only CUDA
dependencies were pulled into the other platforms' resolutions. It resolves
with `uv pip compile --python-platform` now, which evaluates markers for the
target (and does all nine in about 15 s).

Released the same day as **3.94.1**: tag, GitHub Release, PyPI. The wheel
PyPI serves has the sha256 of the Release asset (841d0fc9…); the published
version resolves without a compiler on all nine targets; installed from
pypi.org into a fresh Python 3.13 venv with setuptools 84 it scores
laion_aes 4.232 and clipiqa 0.437, where 3.94.0 scored nothing. The
real-model lane, dispatched on the fixup, fetched both pyiqa models through
`_metrics()` on a fresh runner and passed all three socket-level tests with
weights required. The fixup's own review left two nits, taken afterwards:
the premise test now requires `packaging` to be the only name clip takes
from pkg_resources, and the CI job pins uv below 1.0 (a reworded hint would
fail loudly, not pass). Checking the published version also showed uv's
index cache can hide a release minutes old, so a spec is resolved with
`--refresh-package` for the package under test.

Reviewed before committing (three lenses and a refuting fourth): nothing
in the dependency change or the docs; two latent holes in the new check,
both of the kind this block keeps finding. With no Python classifiers it
checked nothing and exited 0, and it counted `cp312-none-any` as pure,
which only one Python accepts. Both fixed, both with tests. Measured on the
released 3.94.0 as a control: Windows, macOS and Linux all fail on Python
3.13 at imagededup and pass on 3.11/3.12; the 3.94.1 tree passes all nine.

**v3.94.2 — the contributor's reports, re-run instead of re-read.** Every
problem gxfc9867 reported (#2 ×2, #3 ×4 including the setuptools one, PR #4's
four commits and the review's findings on them) was reproduced against
`main` by one agent per group and then attacked by a second. Held: the
picker (simulated Windows; os.listdrives first, 30 s cache), offline loading
and the 425, the review sheet (copy-list round trip, `12. 3-5`, 44 px
targets, keyboard rating, `</script>` in a filename), the brace gate, and the
delivery-audit route from an installed wheel. Not fully landed, all from
PR #4: CJK watermarks (a font was taken because it opened — Korean on a
Mac, everything in the slim Docker image, and the contact sheet's
Latin-only list), the buckets toggle's grab cursor (overridden by a later
`pointer` rule; the test read the first rule — the indexOf-anchor shape
again), and the a11y toggle's light "on" state at 4.03:1. Measured in
python:3.12-slim before and after: no CJK font → every character boxed;
fonts-wqy-microhei (5 MB) covers zh/zh-Hant/ja/ko and punctuation, so the
image ships it rather than fonts-noto-cjk (90 MB).

Found on the way, and worse than anything reported: every contact-sheet cell
had said "(image unavailable)" since v2.56.2 (`ImageOps` imported inside
another function; NameError swallowed per cell). ruff's undefined-name rules
over the package found that and `m3 eval --review`'s UnboundLocalError, and
now run as a test and a preflight gate. Mutation-checked: each fix reverted
turns its test red, and the real-font test was rewritten after the first
draft passed with the choice broken (it read the chooser's own bookkeeping).

**v3.94.3 — transformers 5.20.0 and the torch floor, again.** Pushing v3.94.2
turned the floor-pinned 3.12 lane red at `test_a_model_class_can_be_reached`,
the test added for 5.19.0. 5.20.0 (2026-10-15) imports
`torch.distributed.checkpoint.hf_storage` behind a `torch>=2.7` check; the
module is in torch 2.8.0 and absent from 2.7.0/2.7.1 (pytorch tags checked), so
on 2.7.x every model import fails while 2.6 skips the branch. Reproduced on
macOS with torch 2.7.1 (distributed is available there too); the declared spec
`transformers>=4.40,<6,!=5.20.0` resolves 5.19.0 and CLIPModel is reachable.
Excluding one release rather than raising the floor to 2.8: the upstream fix
(huggingface/transformers#49651 / #49652, approved) is a one-word version bump,
and users on 2.7 lose nothing.

**v3.94.4 — issue #5 and its twelve siblings.** PR #6 (@mayuriphad) fixed the
three `open()` calls that decoded UTF-8 files in the locale's encoding; it was
reproduced first in `python:3.12-slim` with `localedef -i zh_TW -f BIG5`
(config load and the CJK-named `scores.csv` both raise before, pass after).
Sweeping for the class by parsing rather than grepping found twelve
`subprocess.run(text=True)` calls with no `encoding=`, which decode a child's
output with the same locale. Same container, stand-in tools writing UTF-8:
`probe_video` raised `UnicodeDecodeError` on a CJK-named clip, and
`read_embedded` returned `{}` for a photograph carrying Chinese keywords, which
`build_args` reads as "no rating to preserve" and so overwrites the
photographer's own `XMP:Rating` in place. Both read correctly after.
`tests/test_text_io_names_its_encoding.py` parses the package (268 text-I/O
sites) and fails any text-mode `open`, `read_text`/`write_text` or
`text=True` subprocess without an encoding; its control is the pre-PR tree,
where it names all fifteen. `tests/test_utf8_reads.py` now pins its children to
this checkout (from `tmp_path` they imported the interpreter's installed
pixcull, here a 2.19 copy) and runs both readers under
`-W error::EncodingWarning`. Reverting the fix turns all three red.

### The first release since 3.53.1 — done at v3.92, not after v3.94

Planned for after v3.94; the owner asked for it on 2026-10-02 so that
issue #3's fix would reach `pip install`. `v3.92.0` is tagged, on GitHub
as a release with its wheel and sdist, and on PyPI. Before the upload
the PyPI page lost a sentence that was not true (audio events) and
`CHANGELOG.md` gained "Upgrading from 3.53.1": twenty candidate changes
drawn from thirty-six versions of history, each checked against the code
at the tag and at HEAD.

That release did not contain v3.93 or v3.93.1, so the delivery-audit
page was still 500 there and face detection still could not run. The
owner asked for a patch release on 2026-10-06, after v3.93.1 and its
review fixes: `v3.93.1` is tagged, released on GitHub and on PyPI, and
the wheel pip fetches from pypi.org has the same hash as the one checked
on the release page — real face models inside, the static assets, the
audit module. Its release notes open with the `[face]` users, for whom
face detection had never worked from an install.

3.94.0 followed on 2026-10-07, at the owner's request, carrying v3.93.2
(PR #4) and v3.94 (Python 3.13). It waited for the torch floor: the
lane pinned to it went red on transformers 5.19.0, and 3.94.0 ships
torch >= 2.7 rather than a floor that cannot load a model. Before the
tag, a three-reviewer pass with a refuting fourth read the commits since
the v3.94 review and the release notes: the notes said uploads were
unchanged, and the industry-sample upload is not (it refuses a request
without a Content-Length, and takes at most 1,024 parts), and the public
docs said "no GPU" where torch means "no accelerator". Both fixed before
publishing. The wheel on PyPI has the same sha256 as the Release asset
(b0ba508a…), was smoke-tested on a fresh Python 3.13 outside the
checkout, and installs from pypi.org with both face models inside.

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

**Shipped.** Measured on the owner's files in `~/pixcull_label_run/`:
`landscape.json` + `portrait.json` audit as 0 labels before and 158 human
after; all six sheets in `blind_2026-09-12/` as 0 before and 756 human after;
`corrections_2026-09-12.jsonl` as 158 human both times. A sheet with no
`source` audits as unknown and one saying `auto` as model, and neither makes
the inventory usable, so `accuracy()` refuses them as before. Every file that
contributes nothing is in `inv.skipped` with its reason, which is the part
that would have made the original hole visible. The parse now lives once
(`_blind_sheet_records`), shared by the audit and `load_blind_sheet`.
`vlm_eval.load_labels` and `calibrate` still read sheets their own way (they
gate on `selection`, not `source`); that is a twin path left as is, recorded
here. Three of the four new tests fail on the old module.

**v3.95 fixup — what the pre-push review found** (three reviewers, one
refuter; all three confirmed by reproduction). A one-line JSONL record that
happened to carry a `verdicts` key was read as an empty sheet and lost; it is
a record when it carries a label of its own. A sheet saves an unanswered
photograph as `null`, and the audit counted key presence, so a sheet of nulls
was "usable" and `accuracy()` then passed its guard and reported n=0; both
now read a label the way `accuracy()` does and skip records without one. And
v3.94.4 had put `errors="replace"` on the macOS keychain read of the API key,
which turns a corrupt entry into a key of U+FFFD and a stream of 401s instead
of "no key"; that read is strict again. Each fix was reverted in turn and its
test went red.

**Released as 3.95.0** on 2026-10-23, the first PyPI release since 3.94.1:
tag `v3.95.0` on `ff2670a`, GitHub Release with written notes (checked
sentence by sentence against the code by a separate pass, no problems), then
the opt-in PyPI dispatch. The wheel PyPI serves has the sha256 of the Release
asset (947041af…), and it is byte-identical to the wheel the tag run built.
It lists every file 3.94.1 did plus `pixcull/utils/fonts.py`. Installed
from pypi.org into a fresh Python 3.13 venv (transformers 5.20.2, torch
2.14.1, setuptools 84), with `-W error::EncodingWarning` it loads the scene
templates and probes a CJK-named clip through a UTF-8 stand-in ffprobe, and
`CLIPModel` imports.

### v3.96 — v3.29's second half: what the non-human rows did to the numbers

`evaluate()` with and without the rows v3.29 learned to exclude. If the
difference is material, every personalisation figure published before
v3.29 was computed over polluted labels and should say so.

**Measure:** the delta, with its sample size. No threshold decided in
advance turns a small delta into "fine".

**Shipped — and the delta the charter asked for is zero, for a reason that
matters more than the number.** Neither kind of row v3.29 excludes
(`compare_rejected` siblings, `synced` corrections) occurs in any label set
on the owner's machine: not in `corrections_2026-09-12.jsonl` (158 rows, all
`source: human`), and not in the 608-row sheet, which predates both producers
and never lived in an `annotations.jsonl`. So with and without are the same
rows, n=158 and n=608. The figure published before v3.29 — held-out keep-F1
0.801 personal vs 0.799 generic (v2.14 charter, DESIGN-AUDIT-2030Q3) — was
not touched by those exclusions. It was polluted by something else, and the
measurement that shows it is a split of the same sheet:

| label set | n | generic | personal | Δ as the file is sorted | Δ per fold | Δ over 200 reorderings |
|---|---|---|---|---|---|---|
| the 608-row sheet (as published) | 608 | 0.799 | 0.801 | +0.002 | −0.018 … +0.018 | −0.005 … +0.005, mean +0.001 |
| its 408 rows endorsed with the verdict on screen | 408 | 0.869 | 0.854 | −0.015 | −0.026 … −0.007 | −0.016 … −0.008, mean −0.014 |
| its 200 v0.11 rows (95 real cull disagreements) | 200 | 0.459 | 0.564 | +0.105 | +0.000 … +0.166 | +0.069 … +0.126, mean +0.100 |
| the 158 blind corrections, stride folds | 158 | 0.807 | 0.849 | +0.041 | +0.004 … +0.074 | **−0.279 … +0.065, mean −0.048** |

All four-fold stride, the method that produced the published figure, which
reproduces to the third decimal from `training_combined.csv` joined to the
rubric stars in `scores_for_baseline.csv`. Its folds straddle zero, and
redrawing them moves it only between −0.005 and +0.005: the published
"personal ≥ generic" was no measurable effect, not a small one. Two thirds
of its rows were endorsements, on which personalisation loses however the
folds are drawn; the third that carries disagreement is where it gains.

**The last column was added after review, and it changed the blind row.**
Stride folds are drawn by position, so one sort order of a file is one draw
of the folds. As the blind file happens to be sorted (one shoot, then the
other), stride gives +0.041 with every fold above zero; redrawn 200 times it
averages −0.048 and ranges from −0.279 to +0.065. The first draft of this
entry, the README and the commit reported +0.041 as a result; it is an
accident of sorting, and there is no stable stride answer on these 158
labels. The 408 and 200 rows keep their sign under every redraw, but "in
every fold" did not survive it either (all four folds negative in 15 of 200
redraws of the 408), so the claims above are about the mean. The blind
set's whole-shoot figure (+0.033 over two shoots) does not depend on order
and belongs to v3.98. **`evaluate()`'s stride folds are order-dependent and
the CLI's per-fold range cannot show it**; whether `evaluate()` should report
a redrawn spread itself is left to v3.98, which is the version that reads
these numbers. n=158 and n=200 are small; these are directions, not effect
sizes.

What changed in the product, so the next figure can say what it was over:
`excluded_reason` is the one statement of the rule; `gather_examples_from_runs`
and the new `load_corrections` take a Counter that receives what the rule
left out and `include_excluded=True` for the "with" half; `evaluate()`
returns `fold_deltas` beside the mean; `pixcull personalize learn` prints
both. `scripts/measure_label_provenance.py` is the measurement, rerunnable,
and reports the redrawn spread beside every stride figure (`--reorder N`,
200 by default):

    scripts/measure_label_provenance.py \
        --corrections ~/pixcull_label_run/corrections_2026-09-12.jsonl \
        --labels ~/pixcull_label_run/training_combined.csv \
        --scores ~/pixcull_label_run/scores_for_baseline.csv \
        --subset endorsed=~/pixcull_label_run/training_v2.14.csv \
        --subset v011=~/pixcull_label_run/training_v011.csv

The two documents that quoted 0.801 carry a dated note pointing here.
Nine mutations (counting removed, `include_excluded` ignored, a later label
not un-counting, unscored frames counted, an unlabelled excluded record that
ends a label not counted, `fold_deltas` dropped, the axes check removed, the
BOM-tolerant read reverted, the CLI row removed) each turn a test red.
The pre-push review (three reviewers, one refuter) re-derived every number
from the previous module with its own joins, and confirmed the blind row's
order dependence, the uncounted unlabelled record and the BOM; all three are
fixed in this version.

### v3.97 — the singleton analysis, with the right vectors

Three of four blocks showed a frame with no near-duplicate is culled more
often. The test of the one remaining explanation was withdrawn because
it fed CLIP vectors to a function that groups on DINOv2.
`burst_embeddings.npz` has existed since v3.84.

**Measure:** the scene-misclassification hypothesis confirmed or
eliminated. Either result closes the entry; no rule ships on
three-of-four.

**Shipped — eliminated.** Rerun 2026-10-28 on `burst_embeddings.npz`
(`dinov2-base`, 768-d), after re-clustering each block and checking the
partition matches the `cluster_id` its run recorded; it does in all four.

| block | classified as | label changes | as run: singletons, cull single / burst, OR | one label, that scene | one label, its genre |
|---|---|---|---|---|---|
| landscape, Zhangye | landscape 136/149 | 4 | 22, 50.0% / 15.7%, 5.35 (p<0.001) | 20, 55.0% / 15.5%, 6.66 | (same) |
| event, iron-flower | abstract 59, event 46, … | 75 | 104, 67.3% / 45.7%, 2.45 (p=0.018) | abstract: 61, 67.2% / 56.2%, 1.60 | event: 71, 70.4% / 51.9%, 2.21 |
| portrait, mid-shoot | **landscape 119/150** | 34 | 70, 10.0% / 10.0%, 1.00 (p=1) | landscape: 56, 5.4% / 12.8%, 0.39 | portrait: **45, 0.0% / 14.3%, 0.00 (p=0.006)** |
| portrait, opening | portrait 119/150 | 23 | 27, 29.6% / 7.4%, 5.29 (p=0.003) | 15, 33.3% / 9.0%, 5.08 | (same) |

The premise was right: the exception block, from the same portrait shoot as
the opening block, was classified landscape on 119 of 150 frames. The
mechanism was not. Landscape thresholds are wider in time (5 s against 2 s)
but stricter in similarity (0.94 against 0.93), and a scene label that
changes between neighbours splits a burst outright, which it did 34 times.
Together they made **more** singletons, not fewer. Each correction toward
the real genre lowers the odds ratio: 1.00 as run, 0.39 under one landscape
label, 0.00 under portrait, where none of 45 singletons was culled against
15 of 105 in bursts. The mechanism run the other way agrees: the opening
block, which replicates, relabelled entirely landscape goes to an odds ratio
of 12.5, not toward 1. So misclassification cannot have produced the
exception, and correcting it makes the exception sharper. The exception
stands, unexplained, and nothing ships on three blocks of four. Under each
block's own genre the other three keep their direction (6.66, 2.21, 5.08).

It is not a threshold artefact either. With every frame under one label, the
exception block's odds ratio is at most 0.40 under each of the six scenes'
thresholds and the defaults, and across a grid of time windows (1, 2, 5, 10,
30 s) by similarity thresholds (0.90, 0.92, 0.93, 0.94, 0.96). Only the
as-run clustering, with its label changing 34 times, lifts it to 1.00. No
clustering of that block puts it beside the other three.

Two corrections to the record. The table in OPEN-ITEMS was computed from
the runs made before v3.84 made clustering deterministic (`contig_event`,
`contig_portrait`, `contig_portrait2` reproduce its cull rates exactly; the
landscape block clustered the same way before and after). Its odds ratios
add 0.5 to every cell (5.24 = 11.5 × 107.5 / (11.5 × 20.5)); the plain odds
ratios of the same tables are 5.35, 2.99, 0.89 and 4.44, and on the fixed
runs 5.35, 2.45, 1.00 and 5.29, the same three-of-four. Every odds ratio in
this entry is the plain one.
And the scene classifier is badly wrong on two of the four blocks — most of
a portrait shoot called landscape, an event shoot called abstract, event,
documentary and unknown in turn — which matters beyond this question (the
burst thresholds and every scene-specific default read it). Recorded in
OPEN-ITEMS, not acted on here.

What changed in the product, so the next analysis cannot repeat September's
mistake: `burst_embeddings.npz` had a writer and no reader, and the CLIP
cache beside it has the same `filenames` / `vectors` keys.
`pixcull.detectors.duplicate.load_burst_vectors` refuses any file not
stamped `dinov2-base` with an `emb_col`; `recluster` re-runs the clustering
on a run's own rows and reports whether it reproduces the recorded
partition, with an optional one-scene override. `scripts/measure_singletons.py`
is the measurement, and refuses a block whose vectors do not reproduce its
clusters (the pre-v3.84 runs, which wrote none, are refused). The pre-push
review (three reviewers, one refuter) re-derived every number with its own
code and confirmed three defects, fixed here: a vector file naming the same
basename twice (two folders each holding a `DSC_0001.JPG`) lost one vector
without a word, and a `scores.csv` doing the same could not be matched to
vectors at all, so both are now refused; a block with nothing to compare
printed an odds ratio of `nan`, and now says why there is none; and the
September odds ratios were Haldane-corrected, as above. Ten mutations each
turn a test red.

### v3.98 — v2.83: does the personal profile generalise

**Measure:** `evaluate()` across the two shoots in the correction set.
One shoot is memorisation and is reported as such.

**Shipped — it does not generalise, and the profile active on the owner's
machine pushes the wrong way.** Measured 2026-10-28 with
`scripts/measure_generalisation.py`, on more than the charter asked for: the
owner's blind labels cover five shoots, not two.

| shoot | genre | photographs | keep / cull |
|---|---|---|---|
| 2023-09-30 – 10-02 | portrait | 79 | 67 / 12 |
| 2023-10-03, Zhangye | landscape | 200 | 158 / 42 |
| 2024-10-01 | portrait | 149 | 132 / 17 |
| 2024-10-04 | portrait | 150 | 135 / 15 |
| 2025-02-01, iron-flower | event | 150 | 59 / 91 |

A photograph is `filename@datetime`. The Canon shutter counter wraps at 9999,
and six names in the 2023 portrait set recur in the 2024-10-04 block as
different frames a year apart; joined on the filename they would have been
counted as one photograph labelled twice. The 24 Zhangye frames that really
were labelled in two blind passes agree 20 times (83%), which is how
consistent this labeller is with themself; the four that disagree are left
out. The 2024-10-01 and 10-04 blocks are three days apart and OPEN-ITEMS
calls them one shoot; they are kept separate here, and the figures below are
given both ways where the boundary matters.

**In `evaluate()`'s own terms** (personal_learn's axis-mean decision, keep-F1,
the acceptance test v2.4 defined): the charter's two shoots, which are also
two genres, give +0.033 (+0.031 and +0.034). Over all five, learned on four
and tested on the fifth, the profile lowers keep-F1 from 0.708 to 0.681
(−0.027; per held-out shoot −0.027, −0.020, −0.001, −0.118, +0.030). Taking
the two 2024 portrait blocks as one shoot, the mean is −0.009 (−0.027,
−0.020, −0.018, +0.030): smaller, the same direction, and most of the
five-shoot figure is the 10-04 block. Within portrait alone it lowers keep-F1
by 0.178 over three shoots (−0.327, +0.007, −0.213), or 0.158 over two
(−0.327, +0.010). Within a single shoot, which is memorisation, the
mean over 200 redrawn folds is +0.038, −0.068, −0.134, −0.353 and +0.384:
it does not reliably help even on the frames beside the ones it learned from.

**In the product's decision** (`decision.decide` on `score_final`, the
threshold shift alone; the axis weights also tilt `fuse_score` and are not
re-applied), learned on four shoots and applied to the fifth:

| | keep-F1 | cull recall |
|---|---|---|
| no shift | 0.743 | 7.7% |
| the learned shift | 0.777 | 3.6% |
| a shift measured against the machine's own keep rate (hypothetical) | 0.734 | 10.4% |

With the two 2024 portrait blocks as one shoot: 0.695 / 9.7%, 0.735 / 4.4%,
0.684 / 13.0%, and the learned shift is still negative on every split.

The learned shift is negative on every split (−0.035 to −0.080): it keeps
more. That is the formula, not the data. `profile_from_preferences` sets
`shift = −(keep_rate − 0.65) × 0.5`, comparing the photographer's keep rate
with a fixed 65% rather than with what the machine keeps on the same frames.
This photographer keeps about 76% and is stricter than the machine on the
frames that matter (v3.81: 27 the machine kept and the owner culled, none the
other way), so the profile is told they are permissive and moves the bar the
wrong way. keep-F1 rewards it, because on keep-heavy shoots keeping more
raises keep-F1 while the culls slip through. A shift against the machine's
own keep rate stays near zero and helps cull recall a little; no threshold
can do more, because the rubric does not separate this owner's keeps from
their culls (v3.81).

**The profile active on this machine** (`~/.pixcull/personal_profile.json`,
last written 2026-08-19 by its file time, since it records no date of its
own; from 70 blind annotations with a 97% keep rate; shift
−0.080, the cap; axis weights equal, so the shift is its whole effect) on all
728 photographs: keep-F1 0.847 → 0.844, cull recall 12.4% → 1.7%, culls 32
→ 3. `run_pipeline` — `pixcull run` and the web app's analysis — applies an
active profile, so every run through it here since 2026-08-19 has had it.
The live tether path does not: `tether._analyze_one_file` calls `decide()`
with no `personal_shift`, so a tethered session is judged without the profile
and the same photograph can get a different verdict there. Found by the
review of this version; recorded in OPEN-ITEMS, not changed here.

**Decisions left to the owner, not taken here:** whether to reset that
profile (`pixcull personalize reset`); whether the shift should be measured
against the machine's keep rate; and whether a profile should switch itself
on without a cross-shoot measurement behind it. Each changes verdicts.

What changed so the next figure cannot hide this: `evaluate()` names the
shoot each fold held out (`fold_groups`, `fold_n`) and reports cull recall
beside keep-F1; `pixcull personalize learn` prints cull recall and says when
the profile scores higher by keeping more; `Example.key` and
`examples_from_blind_sheet` join a blind sheet to the run that scored it and
refuse a `scores.csv` that names a file twice. The script's leave-one-shoot-
out section first crashed on a single shoot, which a test found; it now says
there is no unseen shoot to predict. Eleven mutations each turn a test red.
Public text corrected: README item 15 said the personalised model "improves
silently as you label" (both languages), and README-PYPI said the profile
tilts toward "what you demonstrably value".

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
