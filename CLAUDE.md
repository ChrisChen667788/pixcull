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

**`24-transcript-edit.png` is STILL synthetic** — ffmpeg test pattern
plus macOS TTS, and the README says so at the image.  Replacing it needs
footage with speech in it; the owner's `winter-sled.mp4` working copy is
no longer on this machine and the Canon clips on the card are ambient
only.  Declared, not quietly left.

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
