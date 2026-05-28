# Rescorer V3 — Eval Results (v0.11-P0-1)

> **Status:** infrastructure shipped, retrain pending the goldenset
> being built on a checkout that has actual human labels.
> See "How to fill this in" below.

## Background

V0.8 rule stack: 66.4% exact / 87.5% within-one on the original 128-photo
goldenset.  V1.1 learned rescorer (`models/rescorer_v1.joblib`) improved
recall@5 modestly on landscape but plateaued for the same reason as
the rules: 128 samples is too small for cross-vertical generalisation.

V0.10-P0-3 shipped the eval harness (`eval_rescorer.py`,
`eval_style_v2.py`) + a CI gate (`ci_rescorer_regression.py`).
V0.10 also shipped the multi-vertical taste-aggregation work which
threw off ~22k labels across the user base waiting to be folded in.

## V0.11 plan

1. **Build the goldenset** from every available human-labeled source
   in this checkout:
   ```bash
   make goldenset           # writes goldenset/v0.11/ground_truth.csv
   make goldenset-dryrun    # preview without writing
   ```
2. **Retrain rescorer V3** on the new goldenset.  Reuses the existing
   `scripts/train_rescorer.py` pipeline (sklearn Imputer + Scaler +
   GradientBoosting):
   ```bash
   python scripts/export_training_set.py \
       --goldenset goldenset/v0.11/ground_truth.csv \
       --out goldenset/v0.11/training.csv
   python scripts/train_rescorer.py \
       goldenset/v0.11/training.csv \
       models/rescorer_v3.joblib
   ```
3. **Eval V3 vs V2** on the same goldenset:
   ```bash
   python scripts/eval_on_golden_set.py goldenset/v0.11 --label v2 \
       --rescorer models/rescorer_v1.joblib   # V2 baseline
   cp goldenset/v0.11/_eval_output/scores.csv eval_v2.csv
   python scripts/eval_on_golden_set.py goldenset/v0.11 --label v3 \
       --rescorer models/rescorer_v3.joblib
   cp goldenset/v0.11/_eval_output/scores.csv eval_v3.csv
   python scripts/eval_rescorer.py eval_v3.csv eval_v2.csv \
       --ground-truth goldenset/v0.11/ground_truth.csv \
       --out docs/RESCORER-V3-RESULTS.md   # overwrites this file
   ```

## V0.11 target

`recall@5 ≥ baseline + 3%` on the v0.11 goldenset.

If the goldenset has > 2000 rows and ≥ 5 verticals with ≥ 100 rows each,
also stratify the eval per-vertical and require:
- No vertical regresses by more than 2% recall@5
- At least 3 verticals improve by ≥ 3%

## Why we can't bake numbers in here yet

The goldenset rows reference real photographer filenames from the
川西行 / 李慧&李翔 wedding runs — those filenames are gitignored
(see `.gitignore: out_wedding_eval/`, `predictions*.csv`,
`burst_features_cache.json`).  Training is reproducible from
those local files but the model artefact + eval output stay
out of the public repo per privacy contract.

When you run the steps above on the host that has the real data,
this file will be overwritten by `eval_rescorer.py --out` with the
actual numbers.

## Acceptance checklist

- [x] `scripts/build_goldenset.py` shipped + 12 tests passing
- [x] `make goldenset` / `make goldenset-dryrun` targets wired
- [ ] **`goldenset/v0.11/ground_truth.csv` built** (run `make goldenset`)
- [ ] **`models/rescorer_v3.joblib` trained**
- [ ] **`docs/RESCORER-V3-RESULTS.md` regenerated** with real numbers
- [ ] CI gate `ci_rescorer_regression.py` updated to compare V3 vs V2

## Predecessor docs

- `docs/eval_findings.md` — V0.9 hypothesis tests that motivated V1
- `docs/STYLE-V2-BENCHMARK.md` — multi-vertical λ sweep (v0.10)
- `docs/ROADMAP-v0.11-charter.md` § P0-1 — this slice's spec
