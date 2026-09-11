# PixCull — working agreement for Claude

Local-first AI photo-(and now video-)culling tool for professional
photographers.  This file is the standing contract for how to work in
this repo.  Read it before each session.

## Golden rules

1. **Always `git -C ~/Downloads/zero-basics-python/2/pixcull-restored …`.**
   The cwd can drift up to the parent `zero-basics-python` course repo
   (a *different* git repo on branch `master`).  Never run bare `git`
   from an ambiguous cwd — always pass `-C <this repo's abspath>`.
2. **Test gate before every commit:**
   `python -m pytest tests/ --ignore=tests/test_v1_1_scripts.py`
   (must be green; **5 skips expected** — 2 face-fixture + 3 zeroconf).
   Locally also `--ignore` `test_lightbox_stability.py` and
   `test_visual_smoke.py` (headless capture is killed by this host).
   **Stop any `pixcull m3 open` / `serve` first** (`pkill -f 'pixcull m3
   open'`).  A review server left running costs the suite enough headroom
   that `test_clip_cache_freeride` and `test_e2e_smoke` fail with
   `Cannot send a request, as the client has been closed` and a CLIP
   offline-load error — which reads as a real CLIP regression and is
   not one.  Verified 2026-08-16: 2 failed with it up, 1990 passed with
   it stopped, same commit.
   **The ASR real-engine lane needs its weights pointed at:** export
   `MODELSCOPE_CACHE=/Volumes/<drive>/pixcull-models/modelscope` (and
   `HF_HOME=…/hf` for MLX-Whisper) or `tests/test_transcribe_real_engine.py`
   adds 4 more skips.  With it set the count is back to 5 and those
   tests actually run — which is the point: v2.43.2's three bugs were
   all invisible until the engine was really started.
3. **Commit trailer:** end every commit message with
   `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
   (Was 4.8; the trailer names whichever model actually wrote the
   commit, so it changes when the model does.)
4. **Commit / push only when asked.**  Pushing to GitHub or ModelScope
   is publishing public content — confirm first, then run the audit
   (below) before any push.
5. **`make preflight` AFTER the release commit, before the push**
   (v3.70; the ordering is v3.72).  Twenty-one
   test files, ~21 s, no models: the version rail, both READMEs, the
   changelogs, the dependency pins, the settings registry, the docs'
   command names, repo hygiene, the skip ledger.  Eight of the last
   twenty releases needed a fixup commit and the recent ones were all
   this: the product change was right and the bookkeeping around it was
   not, learned from a runner nine minutes later.  The list is
   drift-checked by `tests/test_preflight_covers.py`, which finds
   bookkeeping gates the list has not got — it found ten the hour it was
   written.  **Order matters:** `test_release_rail.py` and
   `test_readme_style.py` measure distance from the newest release
   *commit*, so running them before committing counts one release fewer
   and they pass on a tree that CI will fail.  That happened on v3.72 —
   preflight green, push, CI red — so preflight now warns when the tree
   is dirty.

## Release & distribution sync (KEEP GITHUB ⇄ MODELSCOPE CONSISTENT)

The project is mirrored to ModelScope (`haozi667788/pixcull`).  **Every
version that changes the README, docs, or screenshots must keep both in
lockstep.**  The sync is now **self-contained** (assets hosted ON
ModelScope, not github links):

1. Update **both** `README.md` (full) and `modelscope/README.md`
   (curated/condensed, same features + same `docs/screenshots/NN-*.png`).
2. **`make modelscope-sync`** (uses `pixcull/.venv`; creds in
   `~/.modelscope/`; preview with `make modelscope-dryrun`).  Default
   self-contained mode: keeps relative `docs/...` paths, **fixes
   `.gitattributes` (README→text, images→LFS), uploads the README, then
   hosts every referenced asset on ModelScope.**
3. Sanity-check the README renders as text (not an LFS pointer) and a
   screenshot resolves:
   `curl -sIL https://www.modelscope.cn/models/haozi667788/pixcull/resolve/master/README.md`
   (must NOT be a `cdn-lfs` redirect).

**The local ModelScope credentials are STALE** (`~/.modelscope/credentials`,
last written 2026-07-21).  `api.login()` returns 400, so `make
modelscope-sync` from this machine can VERIFY assets — that is a plain
fetch — but cannot upload one.  It reports "hosted 30/32" honestly: 30
were confirmed already-current without uploading, and the 2 that needed
a real upload failed.  Rotating that token is the owner's to do and must
never be pasted into a session.  **CI's token works**, so pushing is the
way to sync.

**v3.0.3 — the sync workflow now watches `docs/screenshots/**` and
`docs/diagrams/**` too.**  It used to fire only on `modelscope/README.md`
and the sync script, so replacing an image changed nothing it watched:
the model card kept serving the old picture indefinitely, and every
local check reported the assets as "hosted" — they were, just not the
current ones.  Found the day 25/26 were replaced with real photographs.

**LFS gotcha (why this matters):** ModelScope's `HubApi.upload_file`
auto-adds a per-file `<path> filter=lfs` line to `.gitattributes`, which
turned README.md into an LFS object the model-card viewer renders as a
raw `version https://git-lfs.github.com/spec/v1 …` pointer.  The sync
script now strips `README.md`/`*.md`/`docs/` LFS rules and pins
`README.md text` before each upload.  Never use `--github-links` unless
you specifically want CDN-linked images instead of ModelScope-hosted.

New screenshots: next free number is **27** (01–26 used; 25 =
client-proof-sheet, 26 = blind-label-sheet — **re-shot 2026-09-02 from
the owner's own Canon set**, replacing the synthetic-sample versions
they first shipped with; 17 =
attribution-heatmap, 18 = video-review, 19 = video-grade, 20 =
scenes-navigator, 21 = verdict-glassbox, 22 = transparency-tools, 23 =
video-timeline, 24 = review-sheet).

**25 / 26 are shot from `100CANON/3J0A8133`–`8332`** (the same
owner-authorised 200 that 01–24 use), re-run 2026-09-02 into
`realdemo01`.  Screened by eye across four contact sheets plus a
1600 px zoom on the aerials: architecture interiors, coast, tidal
flats, sunsets — **no portraits and no resolvable faces**.  The
mudflat aerials do contain distant shellfish gatherers, roughly 40 px
tall in a 5472 px frame, back-turned and hatted; nothing facial
survives even at full resolution, and at the 278 px grid thumbnail they
are two or three pixels.  **GPS was stripped from every working copy
before the run** (all 20 sampled originals carried it; `gps_lat` is
empty on all 200 rows), and the originals were copied to a neutral
`/tmp` path first so no drive name can appear on screen.

**`24-transcript-edit.png` is real footage now** (v3.77), built by
`scripts/brand/make_demo_clip.py` from the owner's own sledding clip with
its own audio.  It was an ffmpeg test pattern for fourteen months and read
as a rendering fault on the front page.

Three things that cost time and are worth not repeating:

* **Faces are frosted, not avoided.**  Speech runs 0.5s–18.7s of a 20.7s
  clip, so trimming past the moment the subject turns to camera takes the
  audio with it, and across the whole sledding set there is no clip where
  the subject stays turned away.
* **Screen at full size.**  A 640 px pass found a 29-second "face-free"
  run in another clip; at 3840×2160 that run had bystanders with legible
  faces.  Same lesson as the aerials, learned again.
* **Do not verify a blur by re-running the face detector on it.**  It
  reported a face on 569 of 620 frosted frames — correctly, in its own
  terms, because a smooth oval in skin tones is what it looks for.  The
  check that means something is geometric: every box found in the
  original must lie inside the region that got frosted, and the script
  refuses to write the clip otherwise.

**The GoPro folder holds two different shoots.**  `GH0107xx` is a wedding
and its audio is private conversation — a transcript of it would be
readable text on a public page.  `GX01077x` is the sledding trip.  Only
the second is publishable.

**24 is shot from the owner's own reviewed frames** (owner-authorised
2026-08-16, "用我刚标注的这组真实照片截图…有人像人脸的那几张就不要了").
Three face-free frames, hand-checked at full resolution — **not** by
trusting `face_count`.  That column said 0 on a frame containing a
plainly visible face: a woman lying on snow in a 5280×3956 aerial, far
too small for the detector but perfectly resolvable to a reader.  A
300 px contact sheet missed her too.  **Screen candidates by eye at
≥1400 px; `face_count == 0` is not evidence of no face.**  **18 / 19 / 23 are shot from the owner's own GoPro
footage** (owner-authorised 2026-07-30): winter sledding, subject filmed
from behind throughout, no resolvable faces, GPMF carries no GPS
samples, and the working copy is re-encoded with `-map_metadata -1`
under a neutral name (`winter-sled.mp4`) so no drive name or original
path can appear on screen.  The earlier 18/19 used a stock clip whose
reel-candidate thumbnails had to be blurred to mush.  The deferred baby
face-Close-ups shot is still outstanding (feature verified; headless
capture is killed by this host — capture locally via
`scripts/brand/capture_real_screenshots.sh`).  The
animated architecture / sequence / data-flow diagrams live separately in
`docs/diagrams/` (SVG for GitHub, GIF for ModelScope).

## Repo hygiene — what must NOT go public

**`tests/test_repo_hygiene.py` now enforces this over the whole tree**
(v2.43.2) — run it, don't just grep.  The manual pre-push audit below is
still worth doing for judgement calls, but it is **diff-scoped**, and
that is exactly how two real wedding clients' names, the owner's
external-drive name and their client-folder layout survived in eight
public files across dozens of releases: never in a diff again, so never
re-examined.  The lint scans every tracked file on every gate.

Audit the diff before any push (`git -C <repo> diff origin/main..main`):

- **No real API keys / tokens** — MiniMax, DeepSeek, ModelScope.  Tools
  read keys from env vars / files outside the repo (e.g.
  `scripts/brand/gen_empty_state_art.py` reads `MINIMAX_API_KEY` or
  `~/.minimax_key_tmp`).  Never commit a key; rotate if one leaks.
- **No real personal email / machine-username path / key literal in any
  public file** — learned from a 2026-06-05 leak (a DeepSeek key
  test-fixture + the owner's Gmail + the `/Users/<name>` home path had
  all gone public):
  - real personal email → the role alias `hello@pixcull.dev`;
  - local home paths `/Users/<name>/…` → `~/…` / `$HOME` /
    `Path("~/…").expanduser()` (never the literal macOS username);
  - **never a key / token literal anywhere — including test fixtures.**
    Build them at runtime (e.g. `"sk-" + "0" * 32`) so secret scanners
    have nothing to match.
- **No `MARKET_ANALYSIS_V10.md`** in the public repo.
- **No `.claude/launch.json`.**
- **Eval / training data is local-only:** `out_wedding_eval/`,
  `predictions*.csv`, `goldenset/v0.11/training.csv`,
  `goldenset/v0.11/_eval_output/`, `*.npz`, `mobile/.../.build/` — all
  gitignored.  (Exception on record: `goldenset/v0.11/ground_truth.csv`
  carries Canon auto-filenames `3J0A####.JPG`; the owner reviewed and
  accepted these as non-PII / public on 2026-05-29.  Real *photographer*
  filenames must otherwise stay sha1-hashed.)
- Screenshots must come from synthetic or owner-approved real data — no
  third-party PII, faces, or GPS.

## Architecture quick map

- CLI: `pixcull/cli.py` (typer) — `scan / run / export / bench / video /
  reel / plugins / models`.  Sub-apps via `app.add_typer(...)`
  (`plugins`, `models`).  `models` = `pixcull/models_manager.py`
  (optional-model registry + sha256-verified pull into
  `~/.pixcull/models/`).
- Pipeline: `pixcull/pipeline/orchestrator.py::run_pipeline(folder,
  output, …)` → `scores.csv` + `rubric.jsonl` in the run dir.
- Web demo: `scripts/serve_demo.py` (BaseHTTPRequestHandler;
  `_DEMO_ROOT=/tmp/pixcull_demo`, env-overridable via
  `PIXCULL_DEMO_ROOT`; routes via `if path.startswith(...)`
  in `do_GET`/`do_POST`; the standalone pages — upload/verticals/admin/
  tether/history/disagreement/… — live as `templates/pages/*.html`
  (7 static ones since v2.16; v2.28 added tether [static] + history +
  disagreement [static shell + placeholder injections]), loaded via
  `_read_template`.  The remaining inline-HTML handlers
  (`_render_share_html`, `_serve_bias_audit_page`,
  `_serve_companion_page`) stay inline — heavily f-string-interleaved
  dynamic builders whose template extraction would reduce readability and
  can't be byte-verified via the empty-state route alone).  UI: `pixcull/report/templates/results.html`
  (single-file at *runtime*; since v2.5 it is a **built artifact** —
  edit `templates/src/{results.src.html,results.css,results.js}` **or a
  subsystem file in `templates/src/modules/*.js`** (v2.16: spliced back
  at `@@MODULE:` markers; `tests/test_module_boundaries.py` lints the
  seams — modules are single IIFEs talking only via `window.PixCull*`),
  then `make results-html`; `tests/test_results_build.py` golden-fails
  any hand edit to the artifact) + the dedicated video surfaces
  (`/video/<id>`, `/timeline/<id>`, templates `video_review.html` /
  `timeline.html`).
- v2.0 video stack: `io/video.py` (extract) → `scoring/temporal.py`
  (score_temporal + windows) → `scoring/reel.py` (reel candidates) →
  `io/reel_assembly.py` (cut + EDL); plus `scoring/video_quality.py`
  (shake/blur), `scoring/audio_events.py` (laughter/applause/music),
  `io/gpmf.py` (GoPro/DJI HiLight + GPS).
- Tests mirror modules in `tests/`.  When loading a module via
  `importlib`, set `sys.modules[name] = mod` **before** `exec_module`
  (needed for `@dataclass` `__module__` resolution).

## Roadmap status

v0.11 → v1.0 shipped; v0.13.1–.16 shipped; **v2.0 fully shipped — P0
(P0-1…P0-4) + P1 (P1-1…P1-5) + P2 (P2-1…P2-3).**  See
`docs/ROADMAP-v2.0-charter.md` (every slice annotated with what landed +
honest deviations) and `docs/DESIGN-AUDIT-2028Q2.md` (4.4/5).
**v2.1 fully shipped** — `docs/ROADMAP-v2.1-charter.md` +
`docs/DESIGN-AUDIT-2028Q4.md` (4.1/5): learned audio tagger (pluggable
ONNX + DSP fallback) · video-review discoverability · semantic reel
captions · real .cube LUTs · in/out trim + multi-video shoot reels ·
DJI SRT GPS + GPMF IMU shake · RAW proxy bridge.
**v2.3 "UI overhaul" shipped** — `docs/ROADMAP-v2.3-ui-charter.md`:
editorial-warm rebrand + vendored Geist + Double-Bezel cards + scroll/
spring motion + the 19-shot gallery, all on GitHub + ModelScope.  Plus
the editorial-warm animated architecture / sequence / data-flow diagrams
in `docs/diagrams/` (animated SVG on GitHub, GIF on ModelScope).
**v2.2 CLOSED** — `docs/ROADMAP-v2.2-charter.md` +
`docs/DESIGN-AUDIT-2029Q2.md` (4.3/5).  Shipped: audio tagger (P0-1 —
learned YAMNet→ONNX beats DSP, macro-F1 0.629 vs 0.075, auto-promotes
from `~/.pixcull/models/`; `scripts/convert_yamnet_to_onnx.py` +
`docs/AUDIO-TAGGER-EVAL.md`) · unified lightbox (P0-2) · IMU shake
(P1-1) · `pixcull models` manager (P1-2) · reel presets (P1-3) · GPS
travel-map (P2-1, `io/gps_map.py`) · audit (P2-2).  **Carried to
v2.4-P0-1:** VLM best-frame caption.
**v2.3.1 hotfix shipped** — purged the leaked pre-v2.3 palette (decimal
`rgba()` + separate hexes + a JS **hex-arithmetic** colour ramp only a
live-DOM probe found), warmed the attribution heatmap (`_colorize_warm`),
fixed the onboarding-coachmark/lightbox overlap, `unicode-range`-scoped
the Geist `@font-face` (CJK-safe), mid-width toolbar density; gallery
regenerated + synced.
**v2.4 SHIPPED** — `docs/ROADMAP-v2.4-charter.md` (intelligence + workflow).
All six slices done: **P0-2** personalisation-from-corrections (learn →
`~/.pixcull/personal_profile.json` → orchestrator applies the threshold
shift + "🎯 已按你调校" badge) · **P0-3** keyboard-first cull loop · **P1-2**
NL semantic search (fixed two silent transformers-5 / np.savez bugs +
real-CLIP integration test) · **P1-3** audio-threshold calibration (laughter
recall 0.25→0.85, macro-F1 0.629→0.933; packaged `scoring/data/
audio_tagger_thresholds.json`) · **P1-1** burst "折叠成堆" (peak hero + ⧉N
stack badge → compare) · **P0-1** true VLM best-frame caption
(`reel_caption.py`: opt-in `PIXCULL_REEL_VLM=on` → BLIP captions the actual
best frame; template/text-LLM fallback unchanged).  Also pulled forward the
Playwright **visual-regression smoke** (v2.5-P0-2).  Follow-ups noted in the
charter: near-dup-by-CLIP collapse, bilingual VLM rewrite, self-hosted VLM
ONNX export.

**v2.77 → v2.95 SHIPPED** — see `docs/BLOCK-v2.77-v2.93-CLOSE.md` for the
block's own closing measurement and `docs/ROADMAP-v2.79-v2.93-charter.md`
for what each version was for.  Headline: warm first-screen 971 → 316 ms,
cold 3386 → 1925 ms, idle style recalc 2420 ms/6 s → 30 ms.

The versions that found something worth remembering:

- **v2.77** a cache stampede v2.76 created (18 threads each parsing the
  same 5,069-row CSV: 141 ms alone, 3,001 ms together) and a 1.6 s
  `import torch` sitting on the first request.
- **v2.78** an infinite shimmer animating 4,969 off-screen placeholders —
  40% of a core held for as long as the tab was open, for an effect the
  materialising observer made impossible to see.
- **v2.81** the deep critique was withheld from every CULLED frame, i.e.
  from the photographs a culling tool exists to explain.
- **v2.85** hydration rebuilt 100 identical cards, which is what the four
  refuted hypotheses of v2.84 were all sitting on top of.
- **v2.86** `/thumb/` capped at 420 px whatever `?w=` asked, so a Retina
  grid was judging focus from an upscaled image.
- **v2.88** THERE ARE NO HUMAN LABELS ON THIS MACHINE.  The "608-row
  correction set" is the model's own output; measured against it,
  agreement is 100.0%.  `scoring/ground_truth.py` now refuses.
- **v2.94** the blind labelling tool wrote its results in the one shape
  that guard rejects.  Fixed both ends.
- **v2.95** the run summary counted decisions the VLM judge had already
  overturned: "Keep=6" printed under "6 decision(s) changed", with a CSV
  full of culls.

**Measurement caveat that cost a false alarm:** cold TTFB from
`scripts/measure_first_screen.py` is only comparable WITHIN one
invocation — the server builds a 3 MB page while Chromium starts beside
it (680 ms by plain HTTP, ~1400 ms through the harness, same build).
Two readings weeks apart looked like a 26% regression and were two
machine loads; back-to-back with only the server files swapped, v2.84
gives 1410 ms and HEAD 1398 ms.  The harness now flags a wide spread.
Warm TTFB is stable to ~3% and is safe to quote.

**v3.1 → v3.15 SHIPPED** — the first fifteen of that charter.  Full gate
exits 0; every version mutation-tested.

Three of the fifteen had to be RE-DERIVED because the charter's premise was
wrong, which is what the charter itself says to do:

- **v3.1** the depth harness was NOT measuring the wrong field —
  `ADVICE-DEPTH-BASELINE.md` separated `rationale` from `reading` back in
  v2.81.  Only `advice_depth.py`'s docstring was stale.  The real defect was
  that `summarise()` returned rates with nothing saying what they were over,
  which is the exact shape of the v2.81 conflation.  It now requires a
  `field`.
- **v3.9** the compare modal DOES have a "prefer this side" gesture
  (results.js:7538, since v0.7).  The real defect was worse: it wrote N-1
  near-identical siblings into `annotations.jsonl` as plain human culls, so
  every use of it flattened the keep-minus-cull gap `axis_weights` is built
  from.  Compare labels now carry `source`, and `personal_learn` drops them.
- **v3.10** a `.lrcat` is SQLite, not the "reverse-engineered binary" the
  old deferral note claimed.

Two of the fifteen were prerequisites, not features: **v3.2** (temperature
was not in the M3 cache key) and **v3.6**'s draw index (N draws at one
temperature still collided).  Without both, any self-consistency measurement
reports 100% agreement on every image forever.

**Six versions ship a mechanism and NO number.**  v3.3, v3.4, v3.5, v3.6,
v3.11 need API budget; v3.8 and v3.9 need corrections and **there is no
`annotations.jsonl` anywhere on this machine** — the fitted profile at
`~/.pixcull/personal_profile.json` records 70 blind annotations but the
examples behind it are gone, and a profile cannot be re-fitted from its own
output.  Do not report any of these as measured.

**New env switches, all default-off and all deliberately so:**
`PIXCULL_AXIS_GROUPS` (3x VLM spend), `PIXCULL_CONSISTENCY_DRAWS` (N draws),
`PIXCULL_CRITIQUE_EXEMPLARS=0` (off-switch; on by default),
`PIXCULL_ASPECT_GUARD` (changes near-dup grouping),
`PIXCULL_TETHER_XMP` (writes into a folder the host is importing from).

**Editing `templates/src/results.js` requires `python scripts/build_results_html.py`**
or `test_results_build.py::test_artifact_matches_sources` fails.

**v3.28 → v3.35 SHIPPED** — the charter read out of what the last block
found by accident.  Two sweeps found real defects: **v3.28** the embedded-IPTC
writer was doing all three things v3.23 fixed, but INSIDE the photograph and
with `-overwrite_original`; **v3.29** cloud sync wrote the peer's record
verbatim, so another photographer's corrections were learned as this one's
taste.  **v3.30** found the live tether path was thin because
`_analyze_one_file` returns a hand-written seven-key dict from P2.2 — every
metric added since was computed and discarded on that line.  Inventories:
`docs/WRITER-INVENTORY.md`, `docs/LABEL-PRODUCER-INVENTORY.md`.

**Brand redesigned** — `docs/BRAND.md`.  The mark is "the frame you marked":
crop brackets, a lit frame, the rest of the take dimmed behind.  Edit
`scripts/brand/gen_brand_svg.py`, never the SVG outputs — `_logo_group()` is
the single definition and every asset draws from it.  One accent `#e8a33c`,
for the brackets and the film-edge rule and nothing else.

**House writing style** — `docs/WRITING.md`, enforced by
`tests/test_readme_style.py`.  The READMEs keep **five** releases; older ones
go to `CHANGELOG.md` (and `modelscope/CHANGELOG.md`).  No `**vX.Y** — **bolded
headline.**` template, at most two bold runs per entry, no stock marketing
phrases.  The content was never the problem — the form was, and the numbers
are in the style note.

**BLOCK CLOSED — `docs/BLOCK-v3.1-v3.27-CLOSE.md`.**  12 of 27 closed on a
measurement actually run, 4 on an invariant, **11 ship a mechanism and no
number** with the reason stated per version.  Do not report any of those 11
as measured.  Owner-blocked by category: API budget (v3.3-v3.6, v3.11,
v3.17, v3.18), no corrections on this machine (v3.8, v3.9), needs a
photographer (v3.12), needs a real `.lrcat` (v3.10).

**v3.16 → v3.27 SHIPPED** — the charter is complete (27/27).  Full gate
exits 0.

**Two real data-loss/corruption defects were found by doing the work, not by
looking for them:**
- **v3.23** `write_xmp` built a fresh sidecar over whatever was there.  A
  photographer who had already starred, colour-labelled and keyworded a shoot
  in Lightroom lost all of it the first time they ran PixCull.  Writes are now
  additive (`preserve_existing=True`); an existing rating or label wins, their
  keywords are kept, and only PixCull's own `PixCull:*` keywords are replaced.
- **v3.9/v3.16 class:** the detector cache nearly shipped storing vectors as
  JSON lists.  `orchestrator.py` filters on `hasattr(emb, "shape")`, so every
  warm-run photo would have dropped out of semantic search silently.

**v3.16's first measurement was fake and is written down** (cold and warm in
ONE process = model warm-up; zero cache entries had been written because
`put` was failing on numpy).  Real numbers and the 1,549 MB/s hash rate are in
`docs/DETECTOR-CACHE-MEASUREMENT.md`.

**More charter premises were wrong and re-derived:** v3.17
(`resize_long_edge` is a CONSTRUCTOR arg, not per-call), v3.25 (the unsourced
comparison table was in README.md too, not just the model card — 11 rows).

**New env switches (all default-off except the cache):**
`PIXCULL_DETECTOR_CACHE=0` to disable (on by default; bump `DETECTOR_VERSION`
whenever a detector's output changes or the change appears to do nothing),
`PIXCULL_RESOLUTION_ROUTER`, `PIXCULL_BURST_MULTI_IMAGE`, `PIXCULL_TETHER_XMP`.

**New gates that fail on drift, not on style:** `test_tether_drift` (a new
pipeline column with no live-path disposition), `test_comparative_claims_are_sourced`
(a bare absolute about a competitor), `test_competitive_confidence`
(`verified` with no `verified_by`).

**`pixcull/mcp_server.py`** is a read-only MCP server over stdio, no SDK.
`tool()` refuses a handler not declared read-only — keep it that way.

**Known pre-existing red:** `test_visual_smoke::test_grid_and_lightbox_have_no_legacy_palette`
(`resolve-maybes-btn`, confirmed identical at fee978d).  It hides because the
local gate convention ignores that file.

**v3.36 → v3.65 SHIPPED** — thirty versions, and what they were mostly about
was **gates that pass without checking anything**.  Read this before writing
another one.

Five instances of *skip-as-a-pass* — a test that skips because a binary or a
module is missing, reports green, and has tested nothing: ffmpeg (v2.45,
re-found v3.48), exiftool (v3.41), the browser lane (v3.42), the design-token
ratchet (v3.46), the packaged rescorer (v3.49).  v3.51 built a ledger so a
skip has to be a decision once, and **v3.61 found the shape the ledger cannot
see**: three tests marked `@pytest.mark.slow` with every pytest invocation
saying `-m "not slow"` and no lane saying `-m slow`.  A *deselected* test emits
no SKIPPED line, so a census built on reading them is blind to it by
construction.

Seven occurrences of **a guard satisfied by its own prose** — the explanatory
comment above the check contains the string the check greps for.  Fix by
parsing YAML/AST or stripping comments before matching.  v3.65 fixup is the
newest: the hero gate asserted `"same moment"` was present, and it was — in a
stale `aria-label` describing photographs that had been replaced twice.

**Two guards had an expiry date they did not announce**, which is the same
family and the more dangerous one:
- **v3.65** `test_readme_style.py` matched release commits with `^v(2\.\d+…)`.
  v3.0 shipped eleven days after it was written; the check then reported the
  README current, forever, against a question that had stopped being asked.
  Sixty-four v3 releases with **What's new** frozen on v2.99.
- **v3.64** the numpy runtime guard still fired on 2.x and told users to
  `pip install 'numpy<2'` after the pin had moved to 2.x.
Both now have a second, deliberately independent check beside them.

**Do not trust `face_count == 0`.**  v3.64: the product's own detector reported
a candidate pool clean and it held two portraits, a readable vehicle plate, and
a girl whose face is entirely legible at native resolution — she shipped in the
hero and four screenshots.  A single-shot detector handed a downsized 5472 px
frame is looking for something ten pixels tall in what it receives.  Screening
is eyes at ≥1600 px, then a native-resolution zoom anywhere a human figure
appears; the detector is a pointer.  The rejections are recorded with reasons
in `scripts/brand/prepare_samples.py` — read it before re-adding anything.

**A sample set picked for scores cannot demonstrate the product.**  The
thirty-two highest scorers left one near-duplicate pair and every frame a
`keep`.  It is four pairs and one `maybe` now, chosen for that.

**The product did not run offline at all** (v3.64) — `transformers` contacts
the hub before using a cached model, so `pixcull run` with no network gave
`Analyzed 0/32`.  All six call sites go through
`pixcull.model_assets.from_pretrained`, which tries the network first and falls
back to disk.  Do not call `X.from_pretrained` directly; `test_runs_without_network.py`
fails if you do.

**Unbounded dependency pins are how a major version arrives unannounced.**
v3.65 fixup: `opencv-python>=4.9` let CI resolve 5.0.0.93, which changed
`HoughLinesP` from `(N, 1, 4)` to `(N, 4)` and raised IndexError on every
photograph.  Seven tests caught it in CI and none locally — this laptop still
had 4.11 from an earlier resolve, so **the machine that makes a pin change is
the one machine that cannot see its effect**.  numpy is `>=2.0,<2.5` (numba's
ceiling, not mediapipe's), mediapipe `<1.0` (1.0.1 hard-aborts on
`DrishtiMetalHelper`), opencv `>=4.9,<6`.  The same pins live in
`modelscope/requirements.txt` — twin-path, checked by
`test_dependency_pins_agree.py`.

**That gate was named for one package and enforced one package** (v3.68).
It said `numpy` as a literal, so it covered the dependency somebody had
already been bitten by and left the other fifteen alone — and `torch`,
`torchvision` and `transformers` had all drifted, each carrying a ceiling
in `pyproject.toml` and none in the Studio.  Those three are precisely
the ones whose ceiling was *earned*, so **the packages painful enough to
cap were the packages the public demo ran uncapped.**  When a guard is
written after being burned by one instance, ask what the instance is an
instance *of* before naming it in the assertion.

**The first non-circular accuracy number, 2026-09-12: 73%** (landscape 68%,
portrait 78%, n=158).  Every earlier label set was circular — the model's
verdict was on screen while the owner labelled, so `source: "auto"` and
accuracy came out at exactly 100%.  These are blind: `pixcull m3 label`
shows a photograph, a serial and two buttons, **labelled first, scored
second, joined third**, and that order is what makes them usable.
**The disagreement is one-directional — 27 frames the machine kept and the
owner culled, zero the other way** — so the rule stack is systematically
more permissive than the person it is for.  Corrections live outside the
repo at `~/pixcull_label_run/corrections_2026-09-12.jsonl`.

**"No ceiling" did not mean unbounded** (v3.79).  `plan()` refused only
against `ceiling_units`, and the block sits behind `llm_budget`'s daily cap
(which carries a default) that declines calls one at a time as they happen — so the
halfway stop the planner exists to prevent was reachable by setting no
ceiling at all, silently.  It takes `daily_cap_units` now and names which
limit bound it.  **`audit_labels` has the same shape of hole and still does:**
it reads JSONL, the blind sheet writes one object with a `verdicts` map, and
handed the blind file it returns an empty inventory that reads exactly like
"audited, nothing wrong".  Use `load_blind_sheet` to bridge.

**The per-axis attribution heatmap was removed in v3.78, not deferred.**
It produced the same PNG for all six axes (the per-axis heads moved into
the package in v3.44 and its lookup did not follow), and it could not have
worked anyway: the axis rescorers are sklearn pipelines over **29 tabular
metrics** and never see pixels, so Integrated Gradients over a CNN explains
a different model.  Its ten tests all passed the whole time — axis list,
sha determinism, cache paths, colour ramp — and not one compared two axes'
output.  **Plumbing tested, claim not.**  `tests/test_attribution.py` now
holds the rule, with an explicit exemption for the composition classifier's
saliency map, which computes a feature rather than explaining a score.

**What CI installs is not what a user installs** (v3.74).  All four lanes
pinned `torch==2.4.1` — a 2024 release — while `pyproject.toml` allows
`>=2.2,<3` and a resolve today gives 2.11, so the lane named "install +
import smoke" proved a two-year-old install works.  It resolves freely now;
the behaviour lanes stay pinned so a red run means the code changed, not the
index.  Python 3.11 was worse: advertised in `requires-python`, the PyPI
classifiers, the README badge, `README-PYPI.md` and both quickstarts, and the
matrix had never run it.  `tests/test_ci_tests_what_ships.py` holds both.

**A claim is not made adjacently in every language.**  The v3.68 gate looked
for `numpy` and `<2` next to each other; the Chinese README says
`mediapipe 把 numpy 钉死在 <2`, three characters in between, so the gate built
to catch exactly that claim missed it for ten versions while the English half
had been correct since v3.64.  **README.md is bilingual — fixing a claim means
fixing it twice.**

**A correction the photographer makes does not go into `scores.csv`** — it
is appended to `annotations.jsonl`, and the CSV keeps the machine's verdict.
So every reader of that CSV is answering "the machine's answer or the
person's?", and **fourteen call sites parse the corrections file themselves**
(ten in `serve_app`).  v3.76 gave it one implementation,
`pixcull.annotations.decision_overrides`, plus `OVERRIDE_EXEMPT` for readers
that genuinely want the untouched verdict.  The XMP exporter and the contact
sheet were reading the CSV raw: the pipeline said cull, the photographer said
keep, and Lightroom was handed cull.

**Screenshots: the capture script produces 12 of the 27 committed.**  The
other 15 are frozen at the day they were taken and
`docs/screenshot-dispositions.tsv` now says which, with a date.  A `retired`
row may not be referenced from a README — that is how a picture captioned as
an attribution overlay stayed on the front door for four months showing a UI
that had been removed.

**`.gitignore`'s bare `output/` has eaten two load-bearing directories** —
`tests/fixtures/present_run/output` (v3.51) and `samples/output` (v3.63, which
made the 示例数据 button return 500 for every visitor).  It has glob exceptions
now; add one before committing anything under a directory of that name.

**The design system was wrong about the product it describes** (v3.73).
Fifteen of the sixteen role tokens in `design-system/tokens.json` held
the warm palette v2.21 replaced with an achromatic set — `#161310` for
the page background against the shipped `#161616`, `#f3ede1` against
`#e6e6e6`.  The product changed, nothing compared the two, and the file
kept describing a PixCull that had not shipped in a long time.  Phase
A.1 was about to add a light theme to it.  **Reading the CSS could not
have caught it**: the palette is computed with relative colour
(`oklch(from var(--accent) calc(l + 0.064) c h)`), so the source holds
arithmetic and each theme runs it from a different base.  Both themes
are measured out of a rendered page now —
`scripts/measure_theme_tokens.py`, which paints each value into a 1x1
canvas because `getComputedStyle` and `canvas.fillStyle` both preserve
`oklch()` — and compared in the browser lane.

**A single-file HTML app paints in three places, not one** (v3.71).
`<style>` blocks, inline `style="…"` attributes, and JavaScript that
assembles SVG as a string — the design-token scanner read the first and
was blind to the other two, and a surprising amount of this product's
colour lives in the third.  The result was not a shortfall but an
inversion: in `video_review.html` every literal it counted was a
`--token: #hex` **definition**, the one place a literal is mandatory
because a token cannot be a var() reference to itself, while all seven
real usages were invisible.  Numbers are 131 undesigned / 81 unmigrated
now.  **When a scanner reports a low number, check what it is looking
at before believing the work is nearly done.**

**An ID selector carrying `display:` beats `[hidden] { display: none }`**, so
`el.hidden = true` is inert (v3.64, the client-present bar that was on screen
permanently saying the scores were hidden).

`pixcull 3.53.1` is on PyPI, the first release since 2.47.0.  Publishing is
`workflow_dispatch` + opt-in; a tag push used to upload, which burns a version
number irreversibly.

**Next block: `docs/ROADMAP-v3.1-v3.27-charter.md`** — twenty-seven versions read
out of the same 46-entry competitive research at the level of PixCull's own core
(decision, rubric, judge, critique, personalisation, sequence, ingestion,
compute, packaging).  24 proposals went through an adversarial refute pass; 21
survived, 3 were killed — one because the "gap" was already built three ways in
`results.js`, one on an unfounded Lightroom-SDK mechanism, one because this
repo's own benchmark table says raising the worker cap regresses.  **Two items
are instruments, not features, and everything else depends on them:** v3.1 (the
advice-depth baseline has been measured over `rationale`, a one-sentence field,
not `reading`, the 2-4 sentence critique) and v3.2 (temperature is not in the M3
cache key, so any self-consistency measurement would read the same cached answer
N times and report 100% agreement).  The earlier
`docs/ROADMAP-v3.1-v3.6-charter.md` is superseded and its §v3.1 is wrong; the
correction is at the top of that file.

**Superseded: `docs/ROADMAP-v3.1-v3.6-charter.md`** — six versions read out
of the deep competitive research at the level of the individual product
entry, after the fact-check, not out of its summary.  The research pass had
written `confidence: verified` on 美图云修, 像素蛋糕 and Capture One; the
verification pass overturned two of the three, and the worst claim was ours
(an unsourced "they require cloud upload, we are local" contrast).  Four of
the six items can legitimately close as *measured and declined*; none may
close on someone having read the code and formed an opinion.

**Five versions are OPEN and cannot close without a human** — v2.80
(advice quality, needs raters who are photographers and not the author),
v2.83 (personalisation, needs corrections across two shoots), v2.88
(accuracy baseline), v2.89 (keep/maybe boundary), v2.91 (prompt A/B,
needs an API budget).  Every harness and refusal guard is built.  Do not
report any of them as done, and never synthesise the labels — that is
the exact defect v2.88 exists to prevent.

**Competitive analysis is now on a schedule** — `docs/COMPETITIVE-2026Q3.md`,
`docs/COMPETITIVE-REFRESH-PROTOCOL.md`, snapshots in `docs/competitive/`,
and a fortnightly task.  In the 2026-Q3 edition, ten headline claims were
fact-checked and TEN FAILED.  Treat any first-pass competitive scan as
vendor marketing with a citation stapled on.
