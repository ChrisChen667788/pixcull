# v2.2 charter — Ship the models + unify the lightbox

> **Status:** scoping charter, drafted 2028-Q4 after v2.1 shipped (P0 +
> P1 + P2).  Expected start: 2029 Q1.  Source: the gaps recorded in
> `docs/DESIGN-AUDIT-2028Q4.md`.

## 主题

**"v2.1 built the seams for learned backends + format bridges; v2.2
fills them — ship a small bundled audio tagger, a vision caption path,
and finally merge the video scrubber into the one PixCull lightbox."**

Every v2.1 "optional" feature degrades to a tested fallback, which kept
the tool dependency-light but left the learned paths unexercised by
default.  v2.2 makes the high-value ones real, and pays down the last
big v2.0 deferral (the separate video review surface).

## v2.2 工作范围

### P0(必须做)

#### v2.2-P0-1 · Bundle + evaluate a small audio tagger — ✅ DONE
**估时**: 2 周
- Quantise/export a compact audio-event model (YAMNet-lite / PANNs-CNN10)
  to ONNX, ship it (or a `pixcull models pull` fetch), wire into the
  P0-1 `OnnxTagger`.
- Eval on a labelled laughter/applause/music clip set; the learned path
  must beat the DSP baseline before it becomes default.
- **Done:** `scripts/eval_audio_tagger.py` (folder-per-class eval →
  per-kind detection P/R/F1 via `eval_metrics.binary_prf`, DSP-vs-learned
  + promote/keep verdict) and a measured DSP baseline on a real ESC-50
  subset — **macro-F1 0.075** (applause F1 0.00, laughter 0.15), recorded
  in `docs/AUDIO-TAGGER-EVAL.md`. The weak baseline is the honest case
  for a learned tagger; the model slot is ready via P1-2
  (`pixcull models` → `~/.pixcull/models/audio_tagger.onnx`).
- **Learned model:** Google YAMNet (AudioSet, Apache-2.0) →
  `scripts/convert_yamnet_to_onnx.py` (freeze vars → tf2onnx, single
  `waveform` input). `OnnxTagger` gained a waveform-in branch + cached
  sessions; the 521 AudioSet classes map to our kinds via `labels.json`.
- **Result on a real ESC-50 subset (64 clips):** learned **macro-F1
  0.629 vs DSP 0.075** (applause F1 0.00 → 0.86, laughter 0.15 → 0.40) →
  **auto-promoted to default** when the model sits at `~/.pixcull/models/`
  (DSP stays the offline fallback).  Full numbers + repro in
  `docs/AUDIO-TAGGER-EVAL.md`.  Model ~16 MB, not committed — reproduced
  by the script (or `pixcull models pull audio-tagger`).

#### v2.2-P0-2 · Unified lightbox (merge the video scrubber)
**估时**: 3 周
- Fold the `/video/<id>` timeline-scrubber lightbox into the main
  `results.html` lightbox as a "video mode" (the v2.0-P0-4 / v2.1-P0-2
  deferral).  Standalone page stays as a deep link.

#### v2.2-P0-3 · Vision caption path (VLM)
**估时**: 2 周
- Optional local VLM (e.g. a small Qwen-VL / moondream export) captions
  the reel's best frame; signal/LLM template fallback stays.

### P1(应该做)

#### v2.2-P1-1 · End-to-end IMU→frame shake
**估时**: 1 周
- Resample GPMF ACCL/GYRO to frame timestamps automatically and feed
  `analyze_quality(imu_shake=…)` inside the video run, no caller wiring.

#### v2.2-P1-2 · `pixcull models` manager — ✅ DONE
**估时**: 1 周
- `pixcull models list/pull/path` for the optional audio/LLM/VLM models
  (cached under `~/.pixcull/models`), with checksums.
- **Shipped:** `pixcull/models_manager.py` — a `ModelSpec` registry +
  sha256-verified fetch (`http(s)://` and `file://`), atomic temp→move
  install, idempotent (skip when present + checksum-valid), sidecar
  (labels.json) support — plus the `pixcull models` sub-app
  (`list`/`pull`/`path`) and `tests/test_models_manager.py` (whole fetch
  path exercised over `file://`).  Catalogue rows for `audio-tagger` /
  `vlm-caption` are **"unpublished"** (no URL) until their exports land
  in P0-1 / P0-3 — `pull` says so cleanly instead of 404-ing.  The cache
  path matches what `scoring/audio_tagger.py` already searches, so a
  pulled model is picked up with no extra wiring.

#### v2.2-P1-3 · Reel export presets (Reels / Shorts / 16:9)
**估时**: 1.5 周
- One-click aspect/length presets on the assembled reel (9:16 1080×1920
  crop-to-subject, ≤90 s) + loudness-normalised audio.

### P2(锦上添花)

#### v2.2-P2-1 · GPMF GPS map overlay — ✅ DONE
**估时**: 1 周
- Plot the GoPro/DJI GPS track on the timeline (mini map) for the
  travel-story view.
- **Shipped:** `pixcull/io/gps_map.py` — pure `project_track()`
  (equirectangular, cos-lat aspect, north-up, fit-to-box) +
  `haversine_km` / `track_length_km` + `gps_points_for_video()` reusing
  the existing `parse_telemetry` (GPMF GPS5 → DJI-SRT fallback).
  `_serve_video_data` lazy-extracts + caches `gps.json` and ships a
  projected track; the `/video` review page draws an editorial-warm
  mini-map (track + start/end dots + a brass marker that follows the
  playhead) in the reel rail, hidden when a clip has no GPS.
  `tests/test_gps_map.py` covers projection geometry + telemetry mapping;
  screenshot-verified on a synthetic track (real GoPro/DJI clip pending).

#### v2.2-P2-2 · DESIGN-AUDIT-2029Q2 + v2.3 charter

## 不做的事(scope discipline)

- **Native RAW-video decode** — still bridge-only (vendor SDK / NLE).
- **Cloud / upload** — local-first stays non-negotiable.
- **Becoming an NLE** — PixCull culls + hands off an EDL/reel.

## 验收标准

- Audio model: bundled, ≥ DSP-baseline precision on the eval set, and a
  clean no-model fallback.
- Unified lightbox: a video run opens video-mode in the `/results`
  lightbox; the standalone `/video` page still works.
- VLM caption: renders a sentence on the eval clips; template fallback
  unchanged when absent.
- Docs + `make modelscope-sync` keep GitHub ⇄ ModelScope consistent
  (see `CLAUDE.md`).
