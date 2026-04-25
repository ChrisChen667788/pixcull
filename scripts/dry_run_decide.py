"""Dry-run eval: re-apply decide() to cached scores.csv.

Lets us validate decision-logic changes (e.g. scene-aware hard-cull exemptions)
in <1s instead of running the full 10-minute detector pipeline.

Usage:
    python scripts/dry_run_decide.py tests/fixtures
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from pixcull.config import PixCullConfig
from pixcull.detectors.duplicate import demote_mediocre_bursts
from pixcull.scoring.decision import decide

LABELS = ["keep", "maybe", "cull"]


def main(golden_dir: Path) -> None:
    gt = pd.read_csv(golden_dir / "ground_truth.csv", comment="#")
    gt = gt[gt["manual_label"].isin(LABELS)]

    scores = pd.read_csv(golden_dir / "_eval_output" / "scores.csv")
    scores["datetime"] = pd.to_datetime(scores["datetime"])
    config = PixCullConfig.load()

    # Re-decide with the current decide() implementation (fix #3).
    new_decisions = []
    new_reasons = []
    for _, row in scores.iterrows():
        flags_raw = row.get("flags", "")
        flags = [f for f in str(flags_raw).split(",") if f and f != "nan"]
        dec, rs = decide(
            float(row["score_final"]),
            flags,
            config,
            "standard",
            scene=row["scene"],
        )
        new_decisions.append(dec.value)
        new_reasons.append("; ".join(rs))

    # Apply fix #2: burst-demote. The new implementation builds its own
    # (scene, time) groups internally, so we just hand it the full df.
    scores = scores.reset_index(drop=True)
    demoted_decisions, demoted_reasons = demote_mediocre_bursts(
        scores, new_decisions, new_reasons
    )
    scores = scores.assign(new_decision=demoted_decisions)

    merged = gt.merge(
        scores[["filename", "scene", "new_decision", "decision", "flags"]],
        on="filename",
        how="inner",
        suffixes=("_gt", "_pred"),
    )

    # Before vs after accuracy.
    old_correct = (merged["manual_label"] == merged["decision"]).sum()
    new_correct = (merged["manual_label"] == merged["new_decision"]).sum()
    n = len(merged)

    print(f"\nBefore: {old_correct}/{n} = {old_correct/n:.1%}")
    print(f"After:  {new_correct}/{n} = {new_correct/n:.1%}")
    print(f"Delta:  {new_correct - old_correct:+d} photos")

    changed = merged[merged["decision"] != merged["new_decision"]]
    print(f"\n{len(changed)} files changed decision.")
    if len(changed):
        show = changed[[
            "filename", "scene_pred", "manual_label", "decision", "new_decision", "flags",
        ]]
        print(show.to_string(index=False))

    # New confusion matrix.
    print("\n=== New confusion matrix ===")
    mat = {l: Counter() for l in LABELS}
    for truth, pred in zip(merged["manual_label"], merged["new_decision"]):
        if truth in mat:
            mat[truth][pred] += 1
    cm = pd.DataFrame(mat).T.reindex(index=LABELS, columns=LABELS).fillna(0).astype(int)
    cm.index.name = "truth\\pred"
    print(cm.to_string())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: dry_run_decide.py <golden_dir>", file=sys.stderr)
        sys.exit(1)
    main(Path(sys.argv[1]).expanduser().resolve())
