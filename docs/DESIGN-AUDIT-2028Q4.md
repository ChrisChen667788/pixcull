# Design audit — 2028 Q4 (post-v2.1)

## Method

Same depth / craft / hero rubric as the 2026-Q3 → 2028-Q2 sequence
(1–5 each).  This covers the v2.1 "video intelligence" line, which set
out to pay down the v2.0 honesty gaps (DSP-only audio, signal-only
captions, separate video surface, no real LUTs, single-clip reels,
GoPro-only telemetry).

## Scorecard — where v2.1 lands

| Surface | depth | craft | hero | notes |
|---|:--:|:--:|:--:|---|
| Learned audio tagging (P0-1) | 5 | 4 | 3 | pluggable ONNX backend + DSP fallback; no model ⇒ identical to v2.0 |
| Video-review discoverability (P0-2) | 4 | 4 | 3 | 🎬 badge on /results + /history; links to /video + /timeline |
| Semantic reel captions (P0-3) | 4 | 4 | 3 | optional GGUF LLM rewrite; always-on richer template |
| Real .cube 3D LUT (P1-1) | 5 | 5 | 4 | Resolve/Premiere LUTs, numpy trilinear, drop-in luts/ dir |
| Multi-video shoot reels (P1-2) | 5 | 4 | 4 | in/out trim + cross-clip EDL; `pixcull reel --add` |
| DJI SRT GPS + GPMF IMU (P1-3) | 4 | 4 | 3 | DJI telemetry GPS + gyro-shake blended into the shake signal |
| RAW proxy bridge (P2-1) | 4 | 3 | 3 | detect + guided transcode; auto-invoke a configured tool |

**Average:** 4.1 / 5.  Lower than v2.0's 4.4 by design — v2.1 is mostly
*plumbing for optionality* (pluggable model/LLM backends, format
bridges) where the always-on path is a sensible default and the
high-craft win (real LUTs) is one surface, not the theme.  Every
"optional" backend degrades to a tested, identical-to-before fallback.

## Where the audit still finds gaps (→ v2.2 candidates)

### Gap 1 — Optional backends ship no model
P0-1 (audio ONNX) and P0-3 (caption LLM) are *architectures* with
fallbacks; no model is bundled, so the learned path is unexercised by
default.  v2.2 should ship/quantise one small audio tagger + evaluate it.

### Gap 2 — Captions are signal-rewrite, not vision
P0-3 rewrites signals into a sentence; a true VLM looking at the best
frame ("新娘回眸,逆光") is still future work.

### Gap 3 — Video review is still a separate surface
P0-2 added discoverability, but the scrubber lightbox isn't yet merged
into the unified results.html lightbox (deferred from v2.0-P0-4).

### Gap 4 — RAW decode is bridge-only
P2-1 detects + guides + auto-invokes a *configured* transcoder; no
native ``.braw``/``.crm``/RAW-DNG decode (needs vendor SDKs).

### Gap 5 — IMU↔frame resampling is caller-supplied
P1-3 blends a per-frame IMU shake when handed one; the GPMF-sample→frame
resampling isn't automated end-to-end yet.

## Verdict

v2.1 closes the *structural* v2.0 gaps (learned-backend seams, real
LUTs, multi-clip reels, non-GoPro telemetry) while keeping the
local-first, dependency-light, always-has-a-fallback contract.  The
remaining gaps are about *shipping the models* and the unified lightbox
— the v2.2 charter.
