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

**Measure:** on Windows the browser lists the drives that exist and
navigates into one; on macOS and Linux nothing changes. The server
should enumerate real drives rather than the page guessing eleven
letters, so the list is true on a machine with two.

**Decision needed first:** take the reporter's PR, or implement here and
credit them. It is their fix either way.

### v3.92 — `pixcull video` has never listened to the audio

Found while fixing v3.88. `run_audio_analysis` was added in v2.0-P1-3 on
2026-05-29 and **nothing in the package has ever called it**.
`audio_events.json` has two readers — the reel caption and the review
page — and no writer. The learned tagger of v2.1 and v2.2 ("auto-promotes
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

### v3.93 — Python 3.13 is refused at install

`requires-python = ">=3.11,<3.13"`. The ceiling exists because
`serve_app.py` parses multipart uploads with `cgi.FieldStorage` in two
places and 3.13 removed the module. 3.13 has been out for two years.

**Measure:** both call sites replaced; a 3.13 lane in the CI matrix
installs and passes the hermetic suite. **May close as measured and
declined** if a hard dependency has no 3.13 wheel — in which case the
ceiling stays and the README says why, which it does not today.

### v3.94 — the first release since 3.53.1

Not a code change. v3.54 through v3.93 on GitHub as a tagged release,
which is reversible, and PyPI as a deliberate second step, which is not.
Issue #3 is not fixed for the person who reported it until `pip install
pixcull` installs the fix.

**Owner:** say go for the tag; `gh secret set PYPI_API_TOKEN` for PyPI.

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
