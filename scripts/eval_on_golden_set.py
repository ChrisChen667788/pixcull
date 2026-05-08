"""V15 — run pipeline against a labeled golden set and report accuracy.

Expected layout::

    golden/
        ground_truth.csv     # columns: filename, scene, manual_label, [notes]
                             #          + optional: gt_<axis>_stars per axis
        images/
            *.jpg / *.cr3 / ...

Usage::

    # Quick sanity check (just print a confusion matrix)
    python scripts/eval_on_golden_set.py path/to/golden

    # Full V15 mode — compute macro-F1 + kappa + per-axis MAE, write
    # JSON + HTML reports under <golden>/_eval_output/
    python scripts/eval_on_golden_set.py path/to/golden --report

    # V1 vs V2 rescorer comparison: run with each rescorer pinned and
    # compare. (--baseline points at a previously written report.)
    python scripts/eval_on_golden_set.py path/to/golden --report \\
        --baseline path/to/golden/_eval_output/eval_v1.json \\
        --label v2

V15 outputs (under ``<golden>/_eval_output/``):

* ``eval_<label>.json``  — machine-readable metrics + raw pairs
* ``eval_<label>.html``  — self-contained styled report with confusion
                           matrix, per-class F1, kappa, optional baseline
                           delta + improvement verdict
* ``scores.csv``         — pipeline output (compatible with prior tooling)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from pixcull.pipeline.orchestrator import run_pipeline
from pixcull.scoring.eval_metrics import (
    axis_mae,
    axis_r2,
    compare_runs,
    decision_summary,
)


LABELS = ["keep", "maybe", "cull"]
AXES = ("technical", "subject", "composition", "light", "moment", "aesthetic")


def _gather_axis_metrics(merged: pd.DataFrame) -> dict[str, dict]:
    """Per-axis MAE / R² across rows that have a ``gt_<axis>_stars`` GT.

    The pipeline always writes ``rubric_<axis>_stars`` (auto rubric);
    if a V2.1 rescorer was loaded it ALSO writes
    ``model_<axis>_stars``. We compute both: how well does auto
    rubric track human GT, and how well does the trained model.
    """
    out: dict[str, dict] = {}
    for axis in AXES:
        gt_col = f"gt_{axis}_stars"
        if gt_col not in merged.columns:
            continue
        truth = merged[gt_col].tolist()

        axis_metrics: dict = {}
        for src in ("rubric", "model"):
            pred_col = f"{src}_{axis}_stars"
            if pred_col not in merged.columns:
                continue
            pred = merged[pred_col].tolist()
            axis_metrics[src] = {
                "mae": axis_mae(truth, pred),
                "r2":  axis_r2(truth, pred),
                "n":   sum(1 for t in truth
                            if t is not None and not (isinstance(t, float)
                                                       and t != t)),
            }
        if axis_metrics:
            out[axis] = axis_metrics
    return out


def _render_html(report: dict, baseline_cmp: dict | None = None) -> str:
    """Self-contained styled HTML for the eval results.

    Same dark/Inter aesthetic as the rest of the app. Renders:
    * Header: dataset size + label, run timestamp
    * Big-number band: accuracy / macro-F1 / kappa
    * Per-class precision/recall/F1 table
    * Confusion matrix (truth × pred) with color-coded cells
    * Per-axis MAE table (if any rows had axis GT)
    * Baseline delta + verdict (if --baseline was passed)
    """
    s = report["decision"]
    cm = s["confusion"]
    pr = s["per_class"]

    def fmt_pct(x):  return f"{x*100:.1f}%"
    def fmt_num(x):  return f"{x:.3f}"
    def cell_color(t, p):  # truth/pred match → green tint, else red tint
        return "var(--keep-bg)" if t == p else (
            "var(--cull-bg)" if cm[t][p] else "transparent")

    cm_rows = "".join(
        "<tr><th>" + t + "</th>" +
        "".join(
            f"<td style='background:{cell_color(t, p)}'>{cm[t][p]}</td>"
            for p in LABELS
        ) + "</tr>"
        for t in LABELS
    )

    pr_rows = "".join(
        f"<tr><th>{cls}</th>"
        f"<td>{fmt_pct(d['precision'])}</td>"
        f"<td>{fmt_pct(d['recall'])}</td>"
        f"<td>{fmt_num(d['f1'])}</td></tr>"
        for cls, d in pr.items()
    )

    axis_rows = ""
    for axis, sources in (report.get("axis_metrics") or {}).items():
        for src, m in sources.items():
            r2_v = m["r2"]
            r2_disp = "—" if r2_v != r2_v else f"{r2_v:.3f}"  # NaN → em-dash
            mae = m["mae"]
            axis_rows += (
                f"<tr><td>{axis}</td><td>{src}</td>"
                f"<td>{mae:.2f}★</td>"
                f"<td>{r2_disp}</td>"
                f"<td>{m['n']}</td></tr>"
            )
    axis_section = (
        f"<h2>Per-axis 回归</h2>"
        f"<table><thead><tr><th>轴</th><th>来源</th><th>MAE</th>"
        f"<th>R²</th><th>n</th></tr></thead>"
        f"<tbody>{axis_rows}</tbody></table>"
    ) if axis_rows else ""

    baseline_section = ""
    if baseline_cmp:
        v = baseline_cmp["verdict"]
        d = baseline_cmp
        baseline_section = (
            f"<h2>对比 baseline</h2>"
            f"<div class='verdict'>{v}</div>"
            f"<table><thead><tr><th>指标</th><th>baseline</th>"
            f"<th>本次</th><th>Δ</th></tr></thead><tbody>"
            f"<tr><th>accuracy</th><td>{fmt_pct(d['accuracy']['base'])}</td>"
            f"<td>{fmt_pct(d['accuracy']['new'])}</td>"
            f"<td class='delta'>{d['accuracy']['delta']*100:+.1f}pp</td></tr>"
            f"<tr><th>macro-F1</th><td>{fmt_num(d['macro_f1']['base'])}</td>"
            f"<td>{fmt_num(d['macro_f1']['new'])}</td>"
            f"<td class='delta'>{d['macro_f1']['delta']:+.3f}</td></tr>"
            f"<tr><th>kappa</th><td>{fmt_num(d['kappa']['base'])}</td>"
            f"<td>{fmt_num(d['kappa']['new'])}</td>"
            f"<td class='delta'>{d['kappa']['delta']:+.3f}</td></tr>"
            f"</tbody></table>"
        )

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>PixCull · 评估报告 — {report['label']}</title>
<style>
  :root {{
    --bg: #0b0d10; --bg-card: #14171c; --fg: #e9ecf2; --muted: #a8b2c1;
    --accent: #3b82f6; --border: #232830;
    --keep: #4ade80; --maybe: #d9a30c; --cull: #f87171;
    --keep-bg: rgba(74,222,128,0.18);
    --cull-bg: rgba(248,113,113,0.15);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px 24px; min-height: 100vh;
    background: var(--bg); color: var(--fg);
    font: 14px/1.55 -apple-system, "SF Pro Text", Inter,
          "Segoe UI Variable", "PingFang SC", sans-serif;
  }}
  main {{ max-width: 880px; margin: 0 auto; }}
  h1 {{ margin: 0 0 4px; font-size: 22px; font-weight: 600; }}
  h2 {{
    font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 28px 0 10px; font-weight: 600;
  }}
  .subtitle {{ color: var(--muted); margin-bottom: 24px; }}
  .big-band {{
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px;
    margin-bottom: 8px;
  }}
  .big-band .stat {{
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 8px; padding: 14px 16px;
  }}
  .big-band .stat .v {{
    font-size: 26px; font-weight: 600; font-variant-numeric: tabular-nums;
  }}
  .big-band .stat .k {{
    color: var(--muted); font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.05em;
  }}
  table {{
    width: 100%; border-collapse: collapse;
    background: var(--bg-card);
    border: 1px solid var(--border); border-radius: 8px;
    overflow: hidden;
  }}
  th, td {{
    padding: 8px 12px; text-align: left;
    border-bottom: 1px solid var(--border);
    font-variant-numeric: tabular-nums;
  }}
  th {{ color: var(--muted); font-weight: 500; font-size: 12px; }}
  tr:last-child td {{ border-bottom: 0; }}
  td.delta {{ font-weight: 500; }}
  .verdict {{
    background: rgba(59,130,246,0.08);
    border-left: 3px solid var(--accent);
    padding: 8px 14px; border-radius: 4px; font-weight: 500;
    margin-bottom: 10px;
  }}
  /* Confusion matrix specific: bold the diagonal */
  table.cm th {{ width: 80px; }}
  table.cm td {{ text-align: center; font-weight: 500; }}
  .footnote {{
    margin-top: 32px; padding-top: 14px;
    border-top: 1px solid var(--border);
    color: var(--muted); font-size: 11px;
  }}
</style></head><body>
<main>
  <h1>PixCull 评估报告</h1>
  <div class="subtitle">
    数据集 <b>{report['label']}</b> · n = {s['n']} · 生成于 {report['generated_at']}
  </div>

  <div class="big-band">
    <div class="stat"><div class="v">{fmt_pct(s['accuracy'])}</div><div class="k">准确率</div></div>
    <div class="stat"><div class="v">{fmt_num(s['macro_f1'])}</div><div class="k">macro-F1</div></div>
    <div class="stat"><div class="v">{fmt_num(s['kappa'])}</div><div class="k">Cohen κ</div></div>
  </div>

  <h2>逐类 P / R / F1</h2>
  <table>
    <thead><tr><th>类别</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead>
    <tbody>{pr_rows}</tbody>
  </table>

  <h2>Confusion (rows = truth · cols = pred)</h2>
  <table class="cm">
    <thead><tr><th></th>{
      "".join(f"<th>{l}</th>" for l in LABELS)
    }</tr></thead>
    <tbody>{cm_rows}</tbody>
  </table>

  {axis_section}
  {baseline_section}

  <div class="footnote">
    评估约定:每个图像跑完整 pipeline 一次 → 取 ``decision`` 列对比 GT。
    Per-axis 仅在 GT CSV 含 ``gt_&lt;axis&gt;_stars`` 列时计算。<br>
    Cohen κ 是不加权;若你看重 keep↔cull > keep↔maybe 的"远近差异",
    用 <code>kappa_lin</code> 字段 (json 输出含)。
  </div>
</main>
</body></html>
"""


def main(args: argparse.Namespace) -> int:
    golden_dir = Path(args.golden_dir).expanduser().resolve()
    gt_path = golden_dir / "ground_truth.csv"
    images_dir = golden_dir / "images"
    if not gt_path.exists():
        print(f"ERROR: {gt_path} not found", file=sys.stderr)
        return 2
    if not images_dir.exists():
        print(f"ERROR: {images_dir} not found", file=sys.stderr)
        return 2

    gt = pd.read_csv(gt_path, comment="#")
    gt = gt[gt["manual_label"].isin(LABELS)]

    output = golden_dir / "_eval_output"
    output.mkdir(parents=True, exist_ok=True)

    if not args.skip_pipeline:
        run_pipeline(images_dir, output)

    pred_path = output / "scores.csv"
    if not pred_path.exists():
        print(f"ERROR: pipeline did not produce {pred_path}", file=sys.stderr)
        return 3
    pred = pd.read_csv(pred_path)

    merged = gt.merge(pred, on="filename", how="inner",
                       suffixes=("_gt", ""))
    pairs = list(zip(merged["manual_label"], merged["decision"]))

    summary = decision_summary(pairs, LABELS)
    axis_metrics = _gather_axis_metrics(merged)

    # Always print the basic confusion matrix (back-compat with the
    # pre-V15 invocation pattern that piped this to a terminal).
    print("\n=== Confusion matrix ===")
    print(f"  rows = truth, cols = pred. Total: {summary['n']}")
    cm = summary["confusion"]
    header = "        " + "".join(f"{l:>8}" for l in LABELS)
    print(header)
    for t in LABELS:
        row = f"{t:>6}: " + "".join(f"{cm[t][p]:>8}" for p in LABELS)
        print(row)

    print(f"\nAccuracy: {summary['accuracy']*100:.1f}%   "
          f"macro-F1: {summary['macro_f1']:.3f}   "
          f"κ: {summary['kappa']:.3f}")

    if axis_metrics:
        print("\n=== Per-axis MAE (★) ===")
        for axis, sources in axis_metrics.items():
            for src, m in sources.items():
                r2 = "—" if m["r2"] != m["r2"] else f"{m['r2']:.3f}"
                print(f"  {axis:<12} {src:<7}  MAE={m['mae']:.2f}  R²={r2}  (n={m['n']})")

    if not args.report:
        return 0

    # Full report mode — write JSON + HTML
    report = {
        "schema":       "pixcull.eval.v1",
        "label":        args.label,
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "decision":     summary,
        "axis_metrics": axis_metrics,
        "pairs":        [{"truth": t, "pred": p} for t, p in pairs],
    }

    baseline_cmp = None
    if args.baseline:
        baseline_path = Path(args.baseline).expanduser().resolve()
        if not baseline_path.exists():
            print(f"WARN: --baseline {baseline_path} not found, skipping",
                  file=sys.stderr)
        else:
            base_data = json.loads(baseline_path.read_text("utf-8"))
            baseline_cmp = compare_runs(base_data["decision"], summary, LABELS)
            report["baseline"] = baseline_cmp
            print(f"\n=== vs baseline ({base_data.get('label', '?')}) ===")
            print(f"  accuracy:  {base_data['decision']['accuracy']*100:.1f}% → "
                  f"{summary['accuracy']*100:.1f}%  "
                  f"({baseline_cmp['accuracy']['delta']*100:+.1f}pp)")
            print(f"  macro-F1:  {base_data['decision']['macro_f1']:.3f} → "
                  f"{summary['macro_f1']:.3f}  "
                  f"({baseline_cmp['macro_f1']['delta']:+.3f})")
            print(f"  verdict:   {baseline_cmp['verdict']}")

    json_path = output / f"eval_{args.label}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"\nJSON: {json_path}")

    html_path = output / f"eval_{args.label}.html"
    html_path.write_text(_render_html(report, baseline_cmp),
                          encoding="utf-8")
    print(f"HTML: {html_path}")
    return 0


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("golden_dir", help="Directory with ground_truth.csv + images/")
    p.add_argument("--report", action="store_true",
                    help="Also write JSON + HTML reports under _eval_output/")
    p.add_argument("--label", default="latest",
                    help="Tag for this run (used in output filenames)")
    p.add_argument("--baseline",
                    help="Path to a prior eval_*.json to compute deltas against")
    p.add_argument("--skip-pipeline", action="store_true",
                    help="Don't re-run the pipeline; use existing _eval_output/scores.csv")
    return p.parse_args()


if __name__ == "__main__":
    sys.exit(main(_parse()))
