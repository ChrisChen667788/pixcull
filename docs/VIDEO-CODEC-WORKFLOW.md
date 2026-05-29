# Video codec & 4K/8K workflow (v2.0-P2-1)

How PixCull's video pipeline (`pixcull video <path>`) handles codecs,
high resolutions, and large files — and what to do with formats ffmpeg
can't decode on its own.

## Codec support matrix

| Codec / container | Decode | Notes |
|---|---|---|
| **H.264 / AVC** (`.mp4` `.mov` `.m4v`) | ✅ native | the common delivery codec; tested |
| **H.265 / HEVC** | ✅ native | tested in the P0-1 codec suite |
| **Apple ProRes** (`.mov`) | ✅ native | 422 / 4444; tested in the P0-1 codec suite |
| **AVCHD / MTS / M2TS** | ✅ native | older camcorder masters |
| **VP9 / AV1** (`.webm` `.mkv`) | ✅ native | if the local ffmpeg was built with the decoder |
| **Blackmagic RAW** (`.braw`) | ⛔ transcode first | needs the BRAW SDK; `probe_video` raises `FFmpegError` |
| **Canon RAW Light** (`.crm`) | ⛔ transcode first | vendor RAW; same as above |
| **DJI Mavic / Inspire RAW (DNG sequences)** | ⛔ transcode first | per-frame DNG stacks, not a video stream ffmpeg reads as one clip |

**Transcode-first recipe** for the ⛔ rows (do this in your NLE or with
the vendor tool, then point `pixcull video` at the result):

```bash
# e.g. once BRAW/CRM is exported to a ProRes master:
pixcull video master_prores.mov -o ./out --max-dim 2048
```

RAW-video *native* decode is deferred to v2.1 (it needs vendor SDKs that
can't ship in an offline, dependency-light tool).

## 4K / 8K — use a proxy

Scoring full-resolution 8K frames wastes time and RAM: the 6-axis rubric
and the temporal/quality signals all downsample internally, so a smaller
frame scores identically.  Use `--max-dim` to extract a **proxy** —
frames whose longer edge is capped, aspect preserved, even dimensions:

```bash
pixcull video wedding_8k.mov -o ./out --max-dim 1920   # 4K/8K → 1080p-class proxy
```

Measured on this machine (synthetic `testsrc2`, interval 1 fps):

| Source | `--max-dim` | Frame size | Relative extract+decode cost |
|---|---|---|---|
| 1080p | (none) | 1920×1080 | 1.0× |
| 1080p | 640 | 640×360 | ~0.5× |
| 4K (scaled) | 1920 | 1920×1080 | proxy ≈ 1080p cost regardless of 4K/8K source |

The extracted JPEGs are the only copy the scorer reads, so the proxy
also bounds the run's disk + thumbnail footprint.  Originals are never
modified.

## Large files (> 50 GB)

The pipeline is **streaming by construction**:

1. ffmpeg walks the source once and writes frames to
   `<out>/video_frames/<id>/` — it never loads the whole file into RAM.
2. `--interval-s` (default 1.0) + the `--max-frames` cap (default 3000)
   bound how many frames exist; a 2-hour clip at 1 fps is ~7200 frames,
   so the cap auto-widens the interval to stay under it.
3. The scorer then processes frames **one at a time** (peak RAM ≈ one
   decoded frame, not the clip).

So a 50 GB+ master is fine: pick a sensible `--interval-s` /
`--max-frames` for how dense you need the sampling, add `--max-dim` for
4K/8K, and the working set stays small.  Use `--extract-only` first if
you want to eyeball the frame count before committing to a scoring run.

## Quick reference

```bash
pixcull video clip.mov -o ./out \
  --interval-s 1.0 \      # one frame/sec (or --mode keyframe)
  --max-dim 1920 \        # proxy for 4K/8K
  --max-frames 3000       # safety cap
# → frames + manifest.json → scores.csv → temporal.json
#   → reel_candidates.json ; review at /video/<run_id>
```
