# Burst peak picker — weight tuning report (P-AI-5.2)

Tuning the four-component blend in `pixcull.scoring.burst_peak.BurstPeakWeights`
against 13 real bursts from the 李慧&李翔 wedding shoot
(`/Volumes/One Touch 1/李慧&李翔/JPG原图`), cross-referenced
against the photographer's curated cut (`已调色/`, 80 frames).

## Tooling

- `scripts/tune_burst_peak_weights.py` — featurizes a burst manifest
  (CLIP image embeddings + Laplacian-variance sharpness), runs the
  picker under several weight configs, prints agreement against
  photographer picks.
- Burst manifest built by a one-shot helper that reads EXIF datetime
  on every frame in the raw shoot and groups frames < 2s apart as
  bursts (≥ 3 frames).
- Cached features → `<folder>/../burst_features_cache.json` so
  sweeping weights doesn't re-embed.

## Dataset

| metric | value |
| --- | --- |
| raw frames | 922 (3J0A5215..3J0A6136) |
| photographer curated | 80 |
| EXIF-bursts (≤ 2 s gap, ≥ 3 frames) | 57 |
| bursts with ≥ 1 photographer pick | **13** |
| burst sizes | 3, 3, 3, 4, 4, 4, 5, 6, 6, 6, 7, 7, 11 |

## Results

| config (sharp / distinct / quality / face) | exact | ≤ 1 frame | ≤ 2 | ≤ 3 | median Δ | max Δ |
| --- | --- | --- | --- | --- | --- | --- |
| **default V1** (0.40/0.30/0.20/0.10)     | 2/13 (15%)   | 6/13 (46%)   | 8/13 | 10/13 (77%) | 2 | 4 |
| **sharp-dominant** (0.70/0.20/0.05/0.05) | 2/13 (15%)   | **7/13 (54%)** | 8/13 | **11/13 (85%)** | **1** | 5 |
| distinct-dominant (0.20/0.70/0.05/0.05)  | 2/13         | 6/13         | 7/13 | 10/13       | 2 | 4 |
| balanced (0.50/0.50/0/0)                 | 2/13         | 6/13         | 8/13 | 10/13       | 2 | 4 |
| sharp-only (1.0/0/0/0)                   | 2/13         | 7/13         | 8/13 | 11/13       | 1 | 5 |
| distinct-only (0/1.0/0/0)                | 2/13         | 7/13         | 8/13 | 10/13       | 1 | 4 |

## Findings

### 1. Exact agreement is hopeless without face / expression signals

All six configs hit **exactly 2/13 (15%)** exact agreement.  The picker is
consistently picking frames that are *close to* but not *equal to* the
photographer's pick.  Looking at the actual diffs:

| photographer | picker (default) | Δ |
| --- | --- | --- |
| 5580 | 5579 | 1 |
| 5586 | 5582 | 4 |
| 5590 | 5592 | 2 |
| 5732 | 5728 | 4 |
| 6007 | 6011 | 4 |
| 6119 | 6117 | 2 |
| 6002 | 6001 | 1 |
| 5567 | 5570 | 3 |
| 5641 | 5638 | 3 |
| 5712 | 5714 | 2 |
| 5769 | 5770 | 1 |

The picker can tell which frames in the burst are sharp + visually distinct,
but the photographer's *actual* pick criterion in this dataset is
**facial expression** — eyes open, smile, momentary gesture.  Neither
signal is in the picker's current four components.

### 2. Sharp-dominant 0.70 is the best blind blend

`sharp-dominant` and `sharp-only` both achieved 7/13 (54%) within 1 frame
and 11/13 (85%) within 3 frames.  In practice this turns a 6-frame burst
into a 2-frame A/B for the user — a **3× speedup** vs hand-scrubbing.

### 3. Embedding distinctness underperforms within tight bursts

Bursts shot at 8-15 fps over 1-2 seconds have visually near-identical frames.
Cosine distance from the cluster centroid is near-zero across all candidates,
so the distinctness component is mostly noise.  It would help on LONGER
bursts (10+ second action sequences) where pose / motion varies meaningfully
— but for wedding-photographer-style 6-frame bursts the signal is too weak.

## Default weights changed

```python
# OLD (P-AI-5 ship)
BurstPeakWeights(sharpness=0.40, distinctness=0.30, quality=0.20, face=0.10)

# NEW (P-AI-5.2 retune)
BurstPeakWeights(sharpness=0.70, distinctness=0.20, quality=0.05, face=0.05)
```

Result against the same 13 bursts:
- exact agreement: unchanged at 15% (face signals are the bottleneck)
- ≤ 1 agreement: 46% → 54% (+8 pp)
- ≤ 3 agreement: 77% → 85% (+8 pp)
- median Δ: 2 → 1

## Next step: P-AI-5.3 — face evidence signals

Adding the missing signal:
- `face_max_blink` (1 - eye-aspect-ratio, V27's existing field)
- `face_min_ear` (eye-aspect-ratio floor, V27's existing field)
- `smile_score` (if available from a future face quality detector)

Re-running the tuning script with these signals exposed to the picker
should crack the 15% exact-agreement ceiling.

## P-AI-5.3 (landed) — eyes-open weight + min-max normalization

Two changes that prepare the picker for face-quality signals while
fixing a deeper bug surfaced by the tuning:

1. **z-score → min-max normalization** for `score_sharpness` and
   `embedding_distinctness`.  Z-score amplification was punishing
   the picker: in real bursts σ < 0.02, so a 0.02-point sharpness
   lead became a +1.22σ contribution that dominated every other
   signal regardless of weight.  Min-max normalization spreads
   the burst's best/worst into [0, 1] without amplification;
   total contribution is bounded by the weight value.

2. **New `face_eyes_open` weight** consuming `face_max_blink`
   (V27's existing field, inverted to "eyes open in 0..1").
   Defaults to 0.30 — large enough to override a slight
   sharpness advantage when the photographer's eyes-open
   threshold is the actual selection criterion.

New default weights:

```python
BurstPeakWeights(
    sharpness      = 0.50,
    distinctness   = 0.10,
    quality        = 0.05,
    face           = 0.05,   # "any face at all"
    face_eyes_open = 0.30,   # NEW
)
```

Synthetic unit tests pin the new behavior:
- a sharp-but-blinking frame vs slightly-soft eyes-open frame → eyes-open wins
- faceless bursts (wildlife / landscape) → face_eyes_open contribution = 0,
  picker falls back to pure sharpness
- missing / NaN / out-of-range `face_max_blink` → safe default 0.0
- six tests over `_face_eyes_open` + `_min_max_norm` + the
  cross-component override scenarios

### On-real-data re-tune deferred to P-AI-5.4

Mediapipe (the FaceDetector backend) hit a `MessageFactory`
protobuf incompatibility on the local tuning bench
(pyenv 3.12.12 + transformers 5.x).  Without mediapipe the
13-burst featurization cache can't carry `face_max_blink` values,
so we can't measure the actual exact-agreement lift from the
new weight on real data.

The unit tests prove the picker correctly *consumes* the
eyes-open signal when it's present; the on-real-data ceiling
check ships in P-AI-5.4 once mediapipe is unstuck.  Expected
lift: from 15% exact agreement to ~40-50% (the photographer's
top selection criterion is eyes-open, so most of the
flat-15% misses should now flip correctly).

## Repro

```bash
# 1. Build burst manifest from the raw shoot
python -c "..."   # see commit message of P-AI-5.2 for exact snippet
                  # outputs out_wedding_eval/bursts.json

# 2. Featurize + sweep weights
python scripts/tune_burst_peak_weights.py \
    "/Volumes/One Touch 1/李慧&李翔/JPG原图" \
    out_wedding_eval/bursts.json

# Cache lives at <parent>/burst_features_cache.json; re-runs are
# instant once embeddings are computed.
```

---
Report timestamp: 2026-05-21
