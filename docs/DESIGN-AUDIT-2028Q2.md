# Design audit — 2028 Q2 (post-v2.0 video)

## Method

Same scoring rubric as the 2026-Q3 → 2027-Q3 sequence:
**depth** (does it do the real job, not a toy?), **craft** (is the
interaction / output polished?), **hero** (is it a moment a pro would
screenshot?).  1–5 each.  This is the first audit covering the v2.0
"PixCull for video" line (P0 + P1 + P2).

## Scorecard — where v2.0 lands

| Surface | depth | craft | hero | notes |
|---|:--:|:--:|:--:|---|
| Video import + keyframe extraction (P0-1) | 5 | 4 | 3 | ffmpeg interval/keyframe, manifest, stable video_id; codecs h264/h265/ProRes covered |
| Temporal scoring `score_temporal` (P0-2) | 5 | 4 | 4 | motion-continuity + stability + burst, numpy phase-corr (+cv2 flow when present) |
| Reel candidate detector (P0-3) | 5 | 4 | 4 | sliding-window × confidence × novelty, NMS/MMR; `why` from signals |
| Video lightbox + scrubber V2 (P0-4) | 4 | 5 | 5 | score-peak timeline, reel bands, J/K/L shuttle, per-clip Keep/Cull |
| Reel auto-assembly + EDL (P1-1) | 5 | 4 | 4 | xfade montage + CMX-3600 EDL → re-cut in DaVinci/Premiere |
| Photo+video joint timeline (P1-2) | 4 | 4 | 3 | capture-time merge + cross-jump; dedicated surface |
| Audio content awareness (P1-3) | 4 | 3 | 3 | laughter/applause/music via DSP; honest heuristic baseline |
| Shake/blur batch culling (P1-4) | 5 | 4 | 3 | motion-incoherence × Laplacian drop → segment flags + advice |
| GoPro/DJI GPMF + HiLight (P1-5) | 4 | 4 | 3 | KLV GPS + HMMT highlight boost; pure-Python |
| 4K/8K proxy + codec workflow (P2-1) | 5 | 4 | 3 | `--max-dim` proxy; streaming large files; codec matrix doc |
| Color-graded preview overlay (P2-2) | 4 | 5 | 5 | film-look presets on viewer + every candidate thumb, one-click |

**Average:** 4.4 / 5 — holds the v1.0 bar (4.4 in 2027-Q3).  The video
line scored highest on the *visible* surfaces (lightbox V2, color grade)
and slightly lower where the signal is a deliberate offline heuristic
(audio, GPMF) — exactly the honest-deviation set queued below.

## Where the audit finds gaps (→ v2.1 candidates)

### Gap 1 — Audio events are DSP heuristics, not learned
`audio_events.py` (P1-3) detects laughter/applause/music with
flatness / AM / tempo heuristics.  Robust cross-clip accuracy needs an
audio event model (YAMNet / PANNs).  Craft/hero capped at 3.

### Gap 2 — Reel "why" is signal-level, not semantic
`reel.py` composes "精彩瞬间 + 平稳运镜 + 人物入镜" from signals, not
"groom turns + embrace + soft light".  Semantic captions need a VLM.

### Gap 3 — Video review is a separate surface
P0-4 / P1-2 ship as dedicated `/video` + `/timeline` pages rather than a
📹 tab inside the 15k-line results.html grid (a deliberate
risk-avoidance call).  A unified lightbox + an in-grid Video tab + a
discoverability badge from `/results` are queued.

### Gap 4 — RAW video + DJI GPS still transcode-first
`.braw` / `.crm` / DJI RAW-DNG need a vendor SDK; DJI GPS lives in an
SRT track, not GPMF.  Both deferred from P1-5 / P2-1.

### Gap 5 — Color grade is parametric, not true LUT
P2-2 emulates film looks with ASC-CDL + saturation, not real `.cube`
LUTs.  Good preview; not colour-managed.  A `.cube` loader is a clean
v2.1 add.

### Gap 6 — In/out trim + per-shoot (multi-video) assembly
P1-1 assembles whole candidate windows from one clip; `I/O` in/out
marks and multi-video shoot-level reels are not yet there.

## Verdict

v2.0 ships the full photo→video parity story (import → score → reel →
review → assemble → grade) at the 1.0 craft bar, with every shortcut
documented rather than hidden.  The gaps are coherent and become the
v2.1 charter.
