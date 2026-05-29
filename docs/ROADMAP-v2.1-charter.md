# v2.1 charter — Video intelligence: learned signals + unified surface

> **Status:** scoping charter, drafted 2028-Q2 right after the v2.0
> video line shipped (P0 + P1 + P2 all landed).  Expected start: 2028
> Q3.  Source of every item below: the honest deviations recorded in
> the v2.0 charter + `docs/DESIGN-AUDIT-2028Q2.md`.

## 主题

**"Close the v2.0 honesty gaps — swap the offline heuristics for learned
signals, make the grade real, and fold the video surfaces back into the
one PixCull lightbox."**

v2.0 shipped the full photo→video parity story (import → score → reel →
review → assemble → grade) but took three deliberate shortcuts to stay
offline + dependency-light + low-risk: audio/laughter is DSP not ML, the
reel "why" is signal-level not semantic, and video review is a separate
page rather than a tab in the main grid.  v2.1 pays those down.

## v2.1 工作范围

### P0(必须做)

#### v2.1-P0-1 · Learned audio event tagging
**估时**: 2 周
- Optional YAMNet / PANNs backend behind the existing
  `audio_events.py` API; DSP heuristics stay as the offline fallback.
- laughter / applause / cheer / music / speech with calibrated
  confidence → moment-axis boost.  No regression when the model is
  absent (same interface, same `audio_events.json`).

#### v2.1-P0-2 · Unified video lightbox + in-grid Video tab
**估时**: 3 周
- Merge the dedicated `/video/<id>` review surface into the main
  `results.html` lightbox (timeline scrubber V2 becomes a lightbox mode
  for video runs).
- `/results/<id>` grid gets the 📹 Video tab (charter v2.0-P1-2's
  original target); discoverability badge on video runs.
- Keep the standalone page as a deep-link fallback.

#### v2.1-P0-3 · Semantic reel captions (VLM "why")
**估时**: 2 周
- Optional local VLM to turn signal-level `why` ("精彩瞬间 + 平稳运镜")
  into a sentence ("新郎转身拥抱,软光逆光").  Template/signal fallback
  always works (mirrors the v0.13 NL-explainer pattern).

### P1(应该做)

#### v2.1-P1-1 · Real `.cube` LUT support
**估时**: 1 周
- Load Resolve/Premiere `.cube` 3D LUTs alongside the parametric
  presets; trilinear interpolation in numpy.  Colour-managed preview.

#### v2.1-P1-2 · In/out trim + multi-video shoot reels
**估时**: 2 周
- `I`/`O` in/out marks in the scrubber → trim candidates before
  assembly; assemble a reel across **multiple** clips of one shoot
  (extends P1-1 reel-assembly to a shoot-level EDL).

#### v2.1-P1-3 · DJI GPS (SRT) + GPMF IMU scoring
**估时**: 1.5 周
- Parse DJI SRT telemetry tracks for GPS; score GPMF ACCL/GYRO IMU
  (already parsed in P1-5) into the shake signal.

### P2(锦上添花)

#### v2.1-P2-1 · RAW-video proxy bridge
**估时**: 1 周
- Detect `.braw` / `.crm` / DJI RAW-DNG and offer a guided
  transcode-to-ProRes step (call the vendor CLI if present) so the
  user stays in one flow.  Native decode remains out of scope.

#### v2.1-P2-2 · DESIGN-AUDIT-2028Q4 + v2.2 charter
**估时**: 3-4 天
- Post-v2.1 self-audit + draft the next charter.

## 不做的事(scope discipline)

- **Native RAW-video decode** (BRAW/CRM SDKs) — licensing + binary size;
  proxy bridge only.
- **Editing / motion graphics** — PixCull culls and hands an EDL to
  DaVinci/Premiere; it is not an NLE.
- **Cloud upload of footage** — local-first stays non-negotiable.

## 验收标准

- Audio tagging: with the model installed, laughter/applause precision
  beats the DSP baseline on a labelled clip set; with it absent,
  behaviour is byte-identical to v2.0.
- Unified lightbox: a video run opens in the same `/results` lightbox a
  photo run does; the standalone `/video` page still works.
- `.cube`: a known LUT renders within ΔE tolerance of Resolve's output
  on a test chart.
- Docs: `docs/VIDEO-USER-GUIDE.md` updated; `make modelscope-sync` keeps
  GitHub ⇄ ModelScope consistent (see `CLAUDE.md`).
