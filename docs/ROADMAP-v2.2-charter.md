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

#### v2.2-P0-1 · Bundle + evaluate a small audio tagger
**估时**: 2 周
- Quantise/export a compact audio-event model (YAMNet-lite / PANNs-CNN10)
  to ONNX, ship it (or a `pixcull models pull` fetch), wire into the
  P0-1 `OnnxTagger`.
- Eval on a labelled laughter/applause/music clip set; the learned path
  must beat the DSP baseline before it becomes default.

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

#### v2.2-P1-2 · `pixcull models` manager
**估时**: 1 周
- `pixcull models list/pull/path` for the optional audio/LLM/VLM models
  (cached under `~/.pixcull/models`), with checksums.

#### v2.2-P1-3 · Reel export presets (Reels / Shorts / 16:9)
**估时**: 1.5 周
- One-click aspect/length presets on the assembled reel (9:16 1080×1920
  crop-to-subject, ≤90 s) + loudness-normalised audio.

### P2(锦上添花)

#### v2.2-P2-1 · GPMF GPS map overlay
**估时**: 1 周
- Plot the GoPro/DJI GPS track on the timeline (mini map) for the
  travel-story view.

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
