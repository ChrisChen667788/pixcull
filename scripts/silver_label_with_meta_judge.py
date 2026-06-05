"""V6.0: generate silver labels by running the canon-grounded
hybrid judge (Qwen3-VL local + DeepSeek meta) on a labeled
golden set, then export an axis training CSV that's strictly
better than the V5.0 auto-rubric warm-start.

Why this beats the warm-start
=============================
The V2.1 trainer's warm-start data was the V5.0 ``rubric_decompose``
auto-rubric — which is a check-list with hand-tuned thresholds. The
silver labels here come from V5.0+V5.1 canon + Qwen3-VL pixel
analysis + DeepSeek V4-Flash reasoning + the goldenset's true
manual_label as ground truth context. The meta judge sees ALL of
this and produces 6 axis stars per image that:

* Reference specific photographic principles ('Zone IX clipping')
* Cross-check VLM bias against detector metrics
* Match the photographer's actual reasoning more closely than
  '5/3/1 collapsed from manual_label' or 'auto check-list median'

What this script does
=====================
1. For each row in the goldenset eval CSV:
     - Build a packet (V3.1 build_packet): rule scores + V2.1 model
       stars + V5.0 auto rubric + detector metrics + flags +
       VLM verdict (loaded from the pre-existing vlm_verdicts.jsonl
       OR optionally re-run inline if --rerun-vlm given)
     - ADD the photographer's manual_label as a hint to the meta-judge
       (anchors the silver label to ground truth)
     - Call DeepSeek V4-Flash → MetaVerdict
2. Write to a fresh axis_training_silver.csv with target_<axis>_silver
   columns that the V2.1 trainer can ingest as a higher-quality
   target.

Output
======
  scripts/silver_labels.jsonl     audit trail (every meta-judge
                                  call, full text)
  training_axis_silver.csv        ready for train_axis_rescorers.py

Cost (default goldenset, 131 images, all human-labeled):
  ~131 × ¥0.003 = ~¥0.4 total
  ~131 × 10s VLM + 15s meta = 55 min wall-clock if no cached vlm_verdicts.jsonl
  ~131 × 15s meta = 33 min if vlm_verdicts.jsonl present

Usage
=====
    DEEPSEEK_API_KEY=sk-... python scripts/silver_label_with_meta_judge.py \\
        --goldenset ~/Pictures/pixcull-goldenset \\
        --vlm-verdicts ~/Pictures/pixcull-goldenset/_eval_output/vlm_verdicts.jsonl \\
        --out training_axis_silver.csv

    # Use lower-cost mode without VLM (skip Stage 1, just run meta on
    # detector signals — faster but loses pixel-grounded perception):
    DEEPSEEK_API_KEY=sk-... python scripts/silver_label_with_meta_judge.py \\
        --goldenset ~/Pictures/pixcull-goldenset \\
        --skip-vlm --out training_axis_silver.csv
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

from pixcull.scoring.rubric import RUBRIC_AXES
from pixcull.scoring.meta_judge import (
    DeepseekMetaJudge,
    build_packet,
    DEFAULT_DEEPSEEK_MODEL,
)
from pixcull.scoring.vlm_judge import VlmAxisScore, VlmVerdict


def _load_vlm_verdicts(path: Path) -> dict[str, VlmVerdict]:
    """Read vlm_verdicts.jsonl into {filename: VlmVerdict}."""
    out: dict[str, VlmVerdict] = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            fn = rec.get("filename")
            if not fn:
                continue
            v = VlmVerdict(
                filename=fn,
                axes={k: VlmAxisScore(**ax) for k, ax in
                      (rec.get("axes") or {}).items()},
                overall_label=rec.get("overall_label", ""),
                overall_rationale=rec.get("overall_rationale", ""),
                model_name=rec.get("model_name", "unknown"),
                error=rec.get("error"),
            )
            out[fn] = v
    return out


def _packet_with_gt_hint(
    row: dict[str, Any],
    vlm: VlmVerdict | None,
    manual_label: str,
) -> dict[str, Any]:
    """Like build_packet but appends a 'photographer_label' hint that
    anchors the silver label to ground truth without leaking it as
    the answer (meta judge still has to produce 6 axis stars)."""
    p = build_packet(row, vlm)
    p["photographer_label"] = manual_label
    p["instructions_hint"] = (
        "摄影师本人对此图的最终判断是 '%s'。请基于这个判断 + 上面的所有信号,"
        "给出 6 轴评分,使其和 '%s' 这个最终判断在逻辑上自洽。"
        % (manual_label, manual_label)
    )
    return p


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--goldenset", type=Path,
        default=Path("~/Pictures/pixcull-goldenset").expanduser(),
        help="Goldenset root containing ground_truth.csv + _eval_output/scores.csv",
    )
    parser.add_argument(
        "--vlm-verdicts", type=Path, default=None,
        help="Path to vlm_verdicts.jsonl (default: <goldenset>/_eval_output/vlm_verdicts.jsonl)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("training_axis_silver.csv"),
    )
    parser.add_argument(
        "--audit", type=Path, default=Path("scripts/silver_labels.jsonl"),
    )
    parser.add_argument(
        "--skip-vlm", action="store_true",
        help="Don't include VLM verdicts in the meta-judge packet "
             "(cheaper / faster but loses pixel-grounded perception)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Stop after N rows (for dry runs)",
    )
    parser.add_argument(
        "--model", default=DEFAULT_DEEPSEEK_MODEL,
        help="DeepSeek model to use (default: deepseek-v4-flash)",
    )
    args = parser.parse_args()

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("ERROR: DEEPSEEK_API_KEY env var not set", file=sys.stderr)
        return 2

    gt_path = args.goldenset / "ground_truth.csv"
    scores_path = args.goldenset / "_eval_output" / "scores.csv"
    if not gt_path.exists() or not scores_path.exists():
        print(f"ERROR: missing {gt_path} or {scores_path}", file=sys.stderr)
        return 2

    gt = pd.read_csv(gt_path, comment="#")
    gt = gt[gt["manual_label"].isin(["keep", "maybe", "cull"])]
    scores = pd.read_csv(scores_path)
    df = scores.merge(
        gt[["filename", "manual_label"]],
        on="filename", how="inner",
    )

    if args.limit:
        df = df.head(args.limit)
    print(f"Generating silver labels for {len(df)} rows…")

    vlm_path = args.vlm_verdicts or (
        args.goldenset / "_eval_output" / "vlm_verdicts.jsonl"
    )
    vlm_by_fn = {} if args.skip_vlm else _load_vlm_verdicts(vlm_path)
    if args.skip_vlm:
        print("  --skip-vlm: not using VLM verdicts")
    else:
        print(f"  loaded {len(vlm_by_fn)} VLM verdicts from {vlm_path}")

    judge = DeepseekMetaJudge(model=args.model)
    audit_f = open(args.audit, "w", encoding="utf-8")

    rows_out: list[dict[str, Any]] = []
    n_ok = 0
    n_err = 0
    t0 = time.time()
    for i, (_, r) in enumerate(df.iterrows(), start=1):
        fn = str(r["filename"])
        row = r.to_dict()
        vlm = vlm_by_fn.get(fn)
        packet = _packet_with_gt_hint(row, vlm, str(r["manual_label"]))
        try:
            mv = judge.consolidate(packet)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}/{len(df)}] {fn} → ERROR: {exc}", file=sys.stderr)
            n_err += 1
            continue

        audit_f.write(json.dumps(mv.to_dict(), ensure_ascii=False) + "\n")
        audit_f.flush()

        if mv.error:
            n_err += 1
            print(f"  [{i}/{len(df)}] {fn} → meta error: {mv.error}",
                  file=sys.stderr)
            continue
        n_ok += 1

        out_row: dict[str, Any] = {"filename": fn}
        # Bring all features the trainer needs (FEATURE_COLS_NUMERIC +
        # FEATURE_COLS_CATEGORICAL) from the original scores row
        for col in scores.columns:
            out_row[col] = r.get(col)
        # Targets come from the meta judge's per-axis stars.
        for axis in RUBRIC_AXES:
            ax_data = mv.axes.get(axis.name)
            if ax_data and ax_data.stars is not None:
                out_row[f"target_{axis.name}"] = float(ax_data.stars)
                out_row[f"target_{axis.name}_source"] = "silver_meta"
            else:
                out_row[f"target_{axis.name}"] = None
                out_row[f"target_{axis.name}_source"] = None
        # Bonus: meta verdict overall + confidence + photographer label
        out_row["meta_overall_label"] = mv.overall_label
        out_row["meta_confidence"] = mv.confidence
        out_row["manual_label"] = r.get("manual_label")
        rows_out.append(out_row)

        eta = (time.time() - t0) / i * (len(df) - i)
        if i % 5 == 0 or i == len(df):
            print(f"  [{i}/{len(df)}] ok={n_ok} err={n_err} eta={eta/60:.1f}min")

    audit_f.close()

    if not rows_out:
        print("ERROR: no rows produced", file=sys.stderr)
        return 1

    out_df = pd.DataFrame(rows_out)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(args.out, index=False)
    print(f"\n✓ Wrote {len(out_df)} rows × {len(out_df.columns)} cols → {args.out}")
    print(f"  audit trail: {args.audit}")
    print(f"\nNext: train V6 axis rescorer:")
    print(f"  python scripts/train_axis_rescorers.py {args.out} --out-dir models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
