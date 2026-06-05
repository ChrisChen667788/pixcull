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
   (must be green; 2 face-fixture skips are expected).
3. **Commit trailer:** end every commit message with
   `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
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

New screenshots: next free number is **19** (01–18 used; 17 =
attribution-heatmap, 18 = video-review).

## Repo hygiene — what must NOT go public

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
  `_DEMO_ROOT=/tmp/pixcull_demo`; routes via `if path.startswith(...)`
  in `do_GET`/`do_POST`).  UI: `pixcull/report/templates/results.html`
  (single-file vanilla JS) + the dedicated video surfaces
  (`/video/<id>`, `/timeline/<id>`).
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
**v2.2 in progress** — `docs/ROADMAP-v2.2-charter.md`.  Shipped: unified
lightbox (P0-2) · IMU→frame shake (P1-1) · Reels/Shorts export presets
(P1-3) · `pixcull models` manager (P1-2 — `list/pull/path`, cache
`~/.pixcull/models/`, sha256-verified) · **GPS travel-map overlay (P2-1
— `io/gps_map.py` projects the GoPro/DJI GPS track into a mini-map on
the `/video` timeline, playhead-synced marker)**.  Open: bundled
audio-tagger export (P0-1) · VLM caption (P0-3) — both need real model +
eval assets (the owner's external drive).
