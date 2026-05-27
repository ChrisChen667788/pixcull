# Style V2 (CLIP centroid) λ benchmark — methodology

**v0.10-P0-3** — first goldenset evaluation of the V1 (axis-MAD)
vs V2 (CLIP centroid) blend.

The /style/train endpoint produces two distance signals:

- **V1**: axis-MAD distance (median axis-star distance from the
  photographer's reference selection)
- **V2**: 1 − cosine(`row_emb`, `profile_emb`) over CLIP image
  embeddings of the reference set's centroid

The default blend is `λ·V1 + (1−λ)·V2` with λ = 0.3 since v0.8-P1-1
shipped. **That default was a guess.** This benchmark gives us
the data to pick the right default — globally and per-vertical.

## Goldenset layout

`goldenset/style_v2/ground_truth.csv` columns:

| column         | meaning                                          |
|----------------|--------------------------------------------------|
| `filename`     | matches keys in share_distances.json             |
| `vertical`     | wedding / landscape / wildlife / portrait / event |
| `manual_label` | keep / maybe / cull (photographer's truth)       |
| `is_keep_ref`  | 0 or 1 — used as a /style/train reference        |

`is_keep_ref=1` rows are the "training set" the V1+V2 distances
were computed against; we exclude them from the eval pool so we
measure transfer, not memorisation.

## How to compute the benchmark

```bash
# Step 1 — train the style profile on the goldenset's keep refs
python -c "
from pathlib import Path
import pandas as pd, requests
gt = pd.read_csv('goldenset/style_v2/ground_truth.csv')
refs = gt[gt['is_keep_ref'] == 1]['filename'].tolist()
# (Assumes you've already uploaded the goldenset as a run; replace
# RUN_ID with whatever sample_demo / upload gave you.)
r = requests.post(f'http://127.0.0.1:8770/style/train/RUN_ID',
                  json={'refs': refs, 'lam': 0.5})
print(r.json())
"

# Step 2 — find the distances JSON the host wrote
# (in ~/Library/Application Support/PixCull/runs/RUN_ID/output/share_distances.json
# or similar — see _style_distances_path in serve_demo.py)

# Step 3 — sweep λ
python scripts/eval_style_v2.py \
    --ground-truth goldenset/style_v2/ground_truth.csv \
    --distances ~/Library/Application\ Support/PixCull/runs/RUN_ID/output/share_distances.json \
    --out artifacts/STYLE-V2-RESULTS.md \
    --json-out artifacts/style_v2_sweep.json
```

The script emits both a markdown table (recall@5 per vertical ×
per λ, with each vertical's best cell **bolded**) and a JSON dump.

## Interpreting the output

For each vertical:

- **Best λ** = the value that maximised recall@5 on that
  vertical's keep set. Ties break toward **lower** λ (more weight
  on V2/CLIP, which transfers across photographers better than
  per-user axis preferences).
- **Global recommended default** = mode of per-vertical best λs.

Example output:

| vertical   | λ=0.0  | λ=0.3  | λ=0.5    | λ=0.7  | λ=1.0  |
|------------|--------|--------|----------|--------|--------|
| wedding    | 64.0%  | 71.0%  | **78.0%** | 75.0%  | 62.0%  |
| landscape  | 58.0%  | **68.0%** | 66.0% | 60.0%  | 54.0%  |
| wildlife   | 71.0%  | 76.0%  | **79.0%** | 77.0%  | 70.0%  |

→ global recommended **λ = 0.5** (wedding + wildlife agree;
landscape is one step off but within 2pp at 0.5).

## When to bump the default

Update the `lam_default` constant in `serve_demo._handle_style_train`
when:

- ✅ the **new** recommended λ improves the **average** recall@5
  across verticals by ≥ 3pp over the current default
- ✅ no single vertical regresses by > 5pp at the new λ
- ✅ the recommendation is stable across two independent
  goldenset runs (different photographer / different month)

Otherwise keep the old default. We don't chase the goldenset.

## Per-vertical override (future work)

The eval shows different verticals prefer different λs. A
v0.11-or-later slice could expose `lam_per_vertical` so the
/style/train endpoint picks the right λ automatically from the
predominant scene in the user's reference set. Not in v0.10's
scope — we just want one well-justified global default.

## Why ties break toward V2 (CLIP)

V1's axis-MAD is per-USER: it learns the *individual* photographer's
star-rating preferences. V2's CLIP centroid is per-IMAGE-CONTENT:
it learns what the photographer's keep set looks like visually
across embeddings trained on 400M (image, caption) pairs.

When the photographer's taste is well-captured by their references,
V1 wins. When the taste is novel (a new vertical, or someone trying
to extend their style to unfamiliar subject matter), V2 transfers
better because it doesn't depend on the user's prior axis ratings.

For a default we want to ship to *everyone*, the second is safer.
