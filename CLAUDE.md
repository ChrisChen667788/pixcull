# PixCull — working agreement for Claude

Local-first AI photo-(and now video-)culling tool for professional
photographers.  This file is the standing contract for how to work in
this repo.  Read it before each session.

## Golden rules

1. **Always `git -C /Users/chenhaorui/Downloads/zero-basics-python/2/pixcull-restored …`.**
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
lockstep:**

1. Update **both** `README.md` (full) and `modelscope/README.md`
   (curated/condensed, same features + same screenshot set).  They need
   not be byte-identical, but must cover the **same features and
   reference the same `docs/screenshots/NN-*.png`**.
2. Commit, then **`git -C <repo> push origin main`** — the ModelScope
   README rewrites image paths to
   `raw.githubusercontent.com/ChrisChen667788/pixcull/main/docs/...`, so
   screenshots only render *after* the repo is pushed to GitHub `main`.
3. **`make modelscope-sync`** (uses `pixcull/.venv`; creds in
   `~/.modelscope/`).  Preview first with `make modelscope-dryrun`.
4. Sanity-check a new screenshot URL returns HTTP 200 on
   `raw.githubusercontent.com/.../main/docs/screenshots/<file>`.

New screenshots: next free number is **19** (01–18 used; 17 =
attribution-heatmap, 18 = video-review).

## Repo hygiene — what must NOT go public

Audit the diff before any push (`git -C <repo> diff origin/main..main`):

- **No real API keys / tokens** — MiniMax, DeepSeek, ModelScope.  Tools
  read keys from env vars / files outside the repo (e.g.
  `scripts/brand/gen_empty_state_art.py` reads `MINIMAX_API_KEY` or
  `~/.minimax_key_tmp`).  Never commit a key; rotate if one leaks.
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
  reel / plugins`.
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
**Next: v2.1** — `docs/ROADMAP-v2.1-charter.md` (learned audio tagging ·
unified lightbox + in-grid Video tab · VLM semantic captions · real
.cube LUTs · in/out trim + multi-video reels · DJI SRT GPS).
