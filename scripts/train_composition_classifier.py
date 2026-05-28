#!/usr/bin/env python3
"""v0.13.3 — Train the composition-rule classifier.

Production upgrade path for ``pixcull/scoring/composition_classifier.py``:
the heuristic classifier ships in v0.13.3; this script trains the
MobileNetV3-Small classifier that overrides the heuristic when its
``.joblib`` is present.

Expected dataset
================

A directory of labelled photos:

    dataset/
      rule_of_thirds/   2400 photos
      centered/         1100 photos
      diagonal/          800 photos
      golden_ratio/      600 photos

≈ 5,000 total.  Recommended sources:
  * 500px portfolio scrapes (publicly listed compositions)
  * Photographers' own work labelled by themselves
  * AI-augmented labels from CLIP zero-shot (then human-verified)

Schema
======

Same input shape as the heuristic — 128×128 RGB → flattened.  Output
is one of the 4 RULES.  We use a tiny sklearn pipeline (StandardScaler
+ HistGradientBoostingClassifier) on top of MobileNetV3-Small features,
matching the rescorer's "small joblib + interpretable head" pattern.

Usage
=====

    # 1. Build the feature cache (one-time, ~30s for 5k photos on M2)
    python scripts/train_composition_classifier.py \\
        --dataset path/to/dataset \\
        --features-cache /tmp/composition_features.npz

    # 2. Train + persist the classifier
    python scripts/train_composition_classifier.py \\
        --features-cache /tmp/composition_features.npz \\
        --output models/composition_classifier.joblib

    # 3. (Optional) Evaluate on a held-out set
    python scripts/train_composition_classifier.py \\
        --features-cache /tmp/composition_features.npz \\
        --eval

Exit codes
==========
* 0 — success
* 2 — dataset missing or empty
* 3 — sklearn / timm / torch not installed
* 4 — feature cache schema mismatch
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
RULES = ("rule_of_thirds", "centered", "diagonal", "golden_ratio")


def _build_features(dataset_root: Path, cache_path: Path) -> int:
    """Walk the labelled dataset, encode every image via the timm
    backbone, save features + labels into a numpy cache."""
    try:
        import numpy as np
        import torch
        import timm
        from PIL import Image
    except ImportError as exc:
        print(f"[train-comp] missing dep: {exc}", file=sys.stderr)
        print("[train-comp] install: pip install -e '.[ml]'",
              file=sys.stderr)
        return 3
    if not dataset_root.exists():
        print(f"[train-comp] dataset root not found: {dataset_root}",
              file=sys.stderr)
        return 2
    model = timm.create_model(
        "mobilenetv3_small_100", pretrained=True, num_classes=0,
    )
    model.eval()
    feats_list: list = []
    labels_list: list = []
    n_total = 0
    for rule in RULES:
        rule_dir = dataset_root / rule
        if not rule_dir.is_dir():
            print(f"[train-comp]   skip {rule}/ (no dir)", file=sys.stderr)
            continue
        n_rule = 0
        for img_path in sorted(rule_dir.glob("*.jpg")):
            try:
                img = Image.open(img_path).convert("RGB").resize((128, 128))
                arr = (np.asarray(img, dtype=np.float32) / 255.0)
                arr = (arr - np.array([0.485, 0.456, 0.406])) / \
                      np.array([0.229, 0.224, 0.225])
                t = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).float()
                with torch.no_grad():
                    feats = model(t).squeeze(0).numpy()
                feats_list.append(feats)
                labels_list.append(rule)
                n_rule += 1
                n_total += 1
            except Exception as exc:
                print(f"[train-comp]   skip {img_path.name}: {exc}",
                      file=sys.stderr)
        print(f"[train-comp] {rule}: {n_rule} photos", file=sys.stderr)
    if not feats_list:
        print(f"[train-comp] no photos found under {dataset_root}",
              file=sys.stderr)
        return 2
    feats = np.stack(feats_list)
    labels = np.array(labels_list)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache_path, features=feats, labels=labels)
    print(f"[train-comp] ✓ wrote {n_total} features to {cache_path}",
          file=sys.stderr)
    return 0


def _train_classifier(cache_path: Path, output_path: Path) -> int:
    try:
        import numpy as np
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.ensemble import HistGradientBoostingClassifier
        import joblib
    except ImportError as exc:
        print(f"[train-comp] missing dep: {exc}", file=sys.stderr)
        return 3
    if not cache_path.exists():
        print(f"[train-comp] feature cache missing: {cache_path}",
              file=sys.stderr)
        return 2
    data = np.load(cache_path, allow_pickle=True)
    feats = data["features"]
    labels = data["labels"]
    if feats.shape[0] != labels.shape[0]:
        print(f"[train-comp] cache mismatch: {feats.shape} vs {labels.shape}",
              file=sys.stderr)
        return 4
    pipe = Pipeline([
        ("scale", StandardScaler()),
        ("clf",   HistGradientBoostingClassifier(
            max_depth=4, max_iter=300, learning_rate=0.05,
            min_samples_leaf=5, random_state=42,
        )),
    ])
    pipe.fit(feats, labels)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, output_path)
    # Per-class accuracy as a sanity check
    preds = pipe.predict(feats)
    by_class: dict = {}
    for label, pred in zip(labels, preds):
        rec = by_class.setdefault(label, [0, 0])
        rec[0] += int(label == pred)
        rec[1] += 1
    print(f"[train-comp] ✓ wrote {output_path}", file=sys.stderr)
    for cls, (correct, total) in by_class.items():
        acc = correct / total if total else 0
        print(f"[train-comp]   {cls}: {correct}/{total} = {acc:.1%}",
              file=sys.stderr)
    return 0


def _eval_classifier(cache_path: Path) -> int:
    """Print 5-fold cross-validation accuracy on the cache."""
    try:
        import numpy as np
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.model_selection import cross_val_score
    except ImportError as exc:
        print(f"[train-comp] missing dep: {exc}", file=sys.stderr)
        return 3
    if not cache_path.exists():
        return 2
    data = np.load(cache_path, allow_pickle=True)
    feats, labels = data["features"], data["labels"]
    pipe = Pipeline([
        ("scale", StandardScaler()),
        ("clf",   HistGradientBoostingClassifier(
            max_depth=4, max_iter=300, learning_rate=0.05,
            min_samples_leaf=5, random_state=42,
        )),
    ])
    scores = cross_val_score(pipe, feats, labels, cv=5, scoring="accuracy")
    print(f"[train-comp] 5-fold CV accuracy: "
          f"{scores.mean():.3f} ± {scores.std():.3f}",
          file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Train the v0.13.3 composition-rule classifier."
    )
    p.add_argument(
        "--dataset", type=Path, default=None,
        help="Labelled dataset root (with rule_of_thirds/ etc. subdirs)"
    )
    p.add_argument(
        "--features-cache", type=Path,
        default=REPO_ROOT / "models" / "composition_features.npz",
        help="Numpy cache for extracted timm features"
    )
    p.add_argument(
        "--output", type=Path,
        default=REPO_ROOT / "models" / "composition_classifier.joblib",
        help="Output classifier .joblib path"
    )
    p.add_argument(
        "--eval", action="store_true",
        help="Run 5-fold cross-validation on the cache + exit"
    )
    args = p.parse_args(argv)

    if args.eval:
        return _eval_classifier(args.features_cache)

    # Step 1 — build features when --dataset given
    if args.dataset:
        rc = _build_features(args.dataset, args.features_cache)
        if rc != 0:
            return rc

    # Step 2 — train (always, when cache exists)
    if not args.features_cache.exists():
        print(f"[train-comp] no feature cache + no --dataset; nothing to train",
              file=sys.stderr)
        return 2
    return _train_classifier(args.features_cache, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
