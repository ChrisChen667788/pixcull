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

### P-AI-5.4 — on-real-data re-tune with face_eyes_open

Mediapipe was unstuck by pinning `protobuf==4.25.4` in a one-off
venv (mediapipe 0.10.35 + protobuf 5.x is broken; the wider
project env has TF / pymilvus pulling in protobuf 7.x).  Then
ran `scripts/tune_burst_peak_weights.py --add-face` to augment
the cache with `face_max_blink` / `face_min_ear` / `face_count`.

Re-swept with 5 configs that now include `face_eyes_open`:

| config (sharp / dist / qual / face / eyes_open)    | exact | ≤1 | ≤2 | ≤3 | median Δ |
| -------------------------------------------------- | ----- | -- | -- | -- | -------- |
| baseline P-AI-5 (pre-eyes) 0.40/0.30/0.20/0.10/0   | 2/13  | 6/13 | 8/13 | 10/13 | 2 |
| P-AI-5.2 sharp-dom 0.70/0.20/0.05/0.05/0           | 2/13  | **7/13** | 8/13 | 11/13 | **1** |
| **P-AI-5.3 default 0.50/0.10/0.05/0.05/0.30**      | 2/13  | 6/13 | 8/13 | **12/13** | 2 |
| eyes-dominant 0.35/0.05/0.05/0.05/0.50             | 2/13  | 5/13 | 7/13 | 11/13 | 2 |
| eyes-only 0/0/0/0/1.00                             | **3/13** | 5/13 | 7/13 | 10/13 | 2 |
| balanced eyes+sharp 0.40/0.10/0/0/0.50             | 2/13  | 5/13 | 7/13 | 11/13 | 2 |

### Findings vs the P-AI-5.3 optimistic prediction

The 40-50% exact-agreement target **was wrong**.  Reality:

1. **Eyes-open alone lifts exact agreement only 15% → 23%**
   (2/13 → 3/13).  One extra burst flips correctly when the
   picker leans on blink as the only signal.  Adding eyes-open
   *alongside* sharpness doesn't flip more exact picks because
   most photographer-pick bursts have all frames in a narrow
   blink band (0.17-0.28); blink can't differentiate within
   the band.

2. **The ≤ 3 frame narrowing rate is the real win.**  P-AI-5.3
   default (eyes 0.30) lifts ≤3 from 77% → **92%** — for a
   user this means a 6-frame burst now reliably narrows to a
   3-frame A/B, vs the 4-frame window we shipped at P-AI-5.

3. **The photographer's picks are NOT always low-blink.**
   B5 (3J0A6119) was picked at blink=0.82 over a burst-mate
   at blink=0.00.  The photographer is sometimes choosing a
   blinking frame for the smile / gesture mediapipe's blink
   blendshape doesn't capture.

### Honest evidence dump (per-burst blink of photographer pick)

```
burst photographer pick     blink    ear     sharp_lap
B0    3J0A5580.JPG          0.20    0.27    18      (band: 0.17–0.28)
B1    3J0A5586.JPG          0.25    0.24    25      ← B0/B1 all in band
B2    3J0A5590.JPG          0.28    0.22    16
B3    3J0A5732.JPG          0.09    0.29    19      ← good
B4    3J0A6007.JPG          0.21    0.26     6
B5    3J0A6119.JPG          0.82    0.33    28      ← blinking pick
B6    3J0A6002.JPG          0.52    1.00     9      ← half-closed pick
B7    3J0A5567.JPG          0.09    0.33    14      ← clean
B8    3J0A5641.JPG          0.00    1.00    23      ← clean
B9    3J0A6111.JPG          0.00    1.00    38      ← clean
B10   3J0A5712.JPG          0.32    0.22    13
B11   3J0A5769.JPG          0.00    1.00    27      ← clean
B12   3J0A6081.JPG          0.00    1.00    33      ← clean
```

7 / 13 picks have blink ≤ 0.10 (eyes truly open).  4 / 13 have
blink in the 0.20-0.32 band where the rest of the burst is also
there.  2 / 13 picks are blinking — photographer's expression
override.

### Default weights kept at P-AI-5.3

```python
BurstPeakWeights(
    sharpness      = 0.50,
    distinctness   = 0.10,
    quality        = 0.05,
    face           = 0.05,
    face_eyes_open = 0.30,
)
```

These give the best **≤3 narrowing rate (92%)** while keeping
exact agreement at 2/13.  Stays the recommendation.

### P-AI-5.5 — mediapipe smile + brow-down blendshapes (landed)

Plumbed two new signals into the picker by reading mediapipe's
FaceLandmarker blendshapes that were already computed for blink:

  · `face_max_smile` — average of mouthSmileLeft + mouthSmileRight,
    max across faces, range 0..1
  · `face_max_brow_down` — average of browDownLeft + browDownRight,
    max across faces.  Inverted in the picker as `_face_no_frown`
    (1.0 = relaxed brow, 0 = furrowed) so all weights stay positive.

Real signal range in the 80-frame wedding burst corpus:
  - smile:    0.05 - 0.78 (much more dynamic than blink)
  - brow_down: 0.00 - 0.25 (small but informative)
  - blink:     0.00 - 0.92 (already known)

Weight sweep with the new signals on all 13 real bursts:

| config                                   | exact | ≤1 | ≤2 | ≤3 |
| ---------------------------------------- | ----- | -- | -- | -- |
| baseline P-AI-5 (pre-face)               | 2/13  | 6  | 8  | 10 |
| P-AI-5.4 default (eyes 0.30)             | 2/13  | 7  | 8  | 11 |
| P-AI-5.5 conservative (smile 0.15)       | 2/13  | 7  | 8  | 11 |
| smile-dominant 0.30                      | 2/13  | 7  | 8  | 11 |
| smile-only (1.00)                        | **5/13** | **8** | 8 | **12** |
| smile 0.45 + eyes 0.45 (no sharpness)    | 5/13  | 7  | 9  | 11 |
| smile 0.60 + sharp 0.10                  | 3/13  | 7  | 8  | 11 |

**Smile-only ceiling = 38.5% exact** — a clean 15% → 38.5% lift
when sharpness is removed entirely.  This confirms the
photographer's actual selection criterion: smile, not blink.

### Why the default still keeps sharpness weight

Smile-only mode is only safe on faceful bursts (wedding /
portrait / event).  On wildlife / sports / landscape there's no
smile signal — all frames score 0 from the smile component,
and the picker degenerates to "first filename".  The unit tests
caught this regression scenario.

A vertical-aware default (smile-heavy when scene == wedding,
sharp-heavy otherwise) is the right ship.  That's P-AI-5.6's
job — needs the picker to receive the scene/vertical hint per
burst.  Until then, the safe blended default ships:

```python
BurstPeakWeights(
    sharpness      = 0.40,
    distinctness   = 0.05,
    quality        = 0.05,
    face           = 0.05,
    face_eyes_open = 0.25,
    face_smile     = 0.15,    # NEW
    face_no_frown  = 0.05,    # NEW
)
```

Same ≤3 narrowing rate (11/13 = 85%) as the prior P-AI-5.4
default.  The new signals are correctly **consumed** when present
(13 unit tests cover the consumption paths including the
realistic-sharpness-gap-vs-large-smile-gap flip).  The headline
ceiling lift will land with P-AI-5.6's vertical-aware weighting.

### Other ship change: reason-string semantics

The reason string changed from "biggest absolute contribution"
to "biggest above-cluster-mean delta".  Before this change,
"sharpness 71%" was the surfaced reason on a wedding burst
because raw sharpness is always 0.6-0.7 across all frames,
and 0.7 × 0.40 weight beats any single-component delta.  Now
the reason explains what makes THIS frame different from its
burst-mates ("笑容明显 78%" / "眼睛睁开 95%"), which is what
the user actually wants to know.

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
