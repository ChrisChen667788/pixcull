# Rescorer V3 evaluation methodology

**v0.10-P0-3** — first goldenset-evaluated rescorer retrain since v0.6.

The rescorer is the lightweight ML head that converts the per-axis
rubric stars + scene + style modes into the keep/maybe boundary
decision. v0.6 trained the V1 logistic regression on 128 hand-labeled
photos; v0.10 trains V3 on the accumulated **22k+ photographer
annotations** captured since v0.6 ship.

This doc is the *methodology* — how to run the eval, what metrics
mean, where the goldenset lives. The **last-run results** live in
the JSON written by `scripts/eval_rescorer.py --json-out`, not
inline here, so the doc stays evergreen as we ship new versions.

## The goldenset

Lives at `goldenset/v0.10/`:

```
goldenset/v0.10/
├── ground_truth.csv          # filename, vertical, manual_label, gt_<axis>_stars
└── images/                   # the photos (gitignored — too big)
    ├── wedding/
    ├── landscape/
    ├── wildlife/
    ├── portrait/
    └── event/
```

Required columns in `ground_truth.csv`:

| column         | meaning                                     |
|----------------|---------------------------------------------|
| `filename`     | as in `output/scores.csv`                   |
| `vertical`     | wedding / landscape / wildlife / ...        |
| `manual_label` | keep / maybe / cull (photographer's truth)  |

Optional but useful for per-axis MAE:

| column                | meaning                              |
|-----------------------|--------------------------------------|
| `gt_technical_stars`  | photographer's 1–5 star on this axis |
| `gt_subject_stars`    | ...                                  |
| `gt_composition_stars`| ...                                  |
| `gt_light_stars`      | ...                                  |
| `gt_moment_stars`     | ...                                  |
| `gt_aesthetic_stars`  | ...                                  |

## How to run an eval

### One-shot — compare a candidate rescorer to the previous baseline

```bash
# 1. Cut a scores.csv with the candidate rescorer pinned
python scripts/eval_on_golden_set.py goldenset/v0.10/ --report --label v3
cp goldenset/v0.10/_eval_output/scores.csv artifacts/eval_v3.csv

# 2. Same with the baseline (v0.9-shipped rescorer)
python scripts/eval_on_golden_set.py goldenset/v0.10/ --report --label v2
cp goldenset/v0.10/_eval_output/scores.csv artifacts/eval_v2.csv

# 3. Compare
python scripts/eval_rescorer.py \
    artifacts/eval_v3.csv \
    artifacts/eval_v2.csv \
    --ground-truth goldenset/v0.10/ground_truth.csv \
    --candidate-label v3 \
    --baseline-label v2 \
    --out artifacts/RESCORER-V3-RESULTS.md \
    --json-out artifacts/rescorer_eval.json
```

The markdown out is human-readable; the JSON is what CI consumes.

### CI gate — block release if recall@5 dropped > 1%

```bash
python scripts/ci_rescorer_regression.py artifacts/rescorer_eval.json
echo "exit code: $?"     # 0 = OK, 2 = REGRESSION, 3 = malformed
```

Wire into `.github/workflows/ci.yml`:

```yaml
- name: Rescorer regression gate
  run: |
    python scripts/eval_rescorer.py \
        artifacts/eval_v3.csv artifacts/eval_v2.csv \
        --ground-truth goldenset/v0.10/ground_truth.csv \
        --json-out artifacts/rescorer_eval.json
    python scripts/ci_rescorer_regression.py artifacts/rescorer_eval.json
```

## Metrics

### recall@k

> recall@k = |top-k predictions ∩ GT keeps| / |GT keeps|

The most actionable single number: "did the rescorer surface the
photographer's actual top picks at the top of the sort?" We report
**k=5, k=10, k=20** — k=5 is the demanding "first scroll
without a tab"; k=20 is "by the time the user has scrolled once
or twice".

The CI gate uses **recall@5** — a regression there is felt
immediately by the user. Larger k regressions are softer.

### Per-vertical recall@5

Recall@5 split by vertical (wedding / landscape / ...). A
regression on the overall number might hide a wedding-only
collapse offset by a landscape gain. We never want the new
rescorer to be "average +1pp but wedding -8pp".

### Per-axis MAE

When the goldenset has `gt_<axis>_stars`, we compute per-axis
mean-absolute-error between `rubric_<axis>_stars` (auto rubric)
and the GT. Useful for catching "the model went *worse* at
composition while gaining on the global recall" failures.

### Confusion @ 0.65

Predicted decision (from `score_final` at the canonical 0.65 keep
threshold) × GT manual_label. The diagonal should grow; the
keep→cull cells should stay near zero.

## Reading the per-vertical breakdown

When V3 ships **+3pp recall@5 overall but -2pp on wedding**, that's
a deliberate trade — only acceptable if (a) the wedding regression
is within the per-vertical CI tolerance (not yet wired; planned for
v0.11) AND (b) wedding represents < 30% of the training mix.
Otherwise the wedding-only metric is the canary.

## Tolerance defaults

| metric        | CI tolerance | rationale                          |
|---------------|--------------|------------------------------------|
| recall@5      | 1 pp         | hardest-felt regression by the user |
| recall@10     | 2 pp         | softer, but still notable           |
| per-axis MAE  | 0.10 stars   | bigger than rubric noise floor      |
| per-vertical  | (not gated yet) | planned v0.11 — needs ≥ 100 rows per vertical |

## When to push V3 over V2

- ✅ recall@5 ≥ baseline + 3pp (charter target)
- ✅ no per-vertical regression > 2pp
- ✅ axis MAE either improved OR within 0.10 of baseline on every axis
- ✅ training cost stayed under 30 min on M2 Pro (development friction)
- ✅ inference time stayed under 8ms per row at batch 1000

If any of these fail, V3 stays parked; V2 ships another release.

## Where the goldenset comes from

`goldenset/v0.10/` is built from three sources:

1. **`out_wedding_eval/`** — the photographer's hand-labels on the
   2022 川西行 + 婚礼 batches (gitignored; ~3k rows after dedup)
2. **`annotations.jsonl` aggregate** — every run's `rubric_human_labeled`
   rows pooled, with the photographer's manual override taken as truth
3. **synthetic adversarial** — `scripts/build_axis_training_set.py`
   emits ~500 rows with deliberately mixed signals to stress the
   border cases

The aggregate is regenerated by:

```bash
python scripts/build_goldenset.py \
    --output goldenset/v0.10/ground_truth.csv \
    --include-runs ~/Library/Application\ Support/PixCull/runs \
    --include-wedding-eval out_wedding_eval/
```

(That script is on the todo list to write — once we have 5+ wedding
runs with full rubric_human_labeled rows.)
