"""Unified post-run audit CLI.

Bundles the three v0.2 quality audits into one Markdown report:

  · P-AI-4  · face library quality (per-cluster precision +
              library fragmentation + cross-run continuity)
  · P-CORE-2 · scene-classifier abstain + distribution audit
  · P-PRO-4 · wedding-moment coverage (only when scene == wedding)

Useful as a smoke test after a release (run on the goldenset,
diff the report against the previous release's report) and as a
per-shoot delivery checklist.

Usage:
    python scripts/cli_audit.py <run_id> [--user-root PATH] [--out PATH]
    python scripts/cli_audit.py --scores-csv <path-to-scores.csv> [--out PATH]

The first form discovers a run from the standard PixCull output
location.  The second form takes any scores.csv (useful for
auditing a CI run / a goldenset run that lives outside the
standard run directory).

The wedding-moment section only renders when the run has any
rows with scene == "wedding".
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


def _emit_face_audit_section(
    out_dir: Path,
    user_root: Optional[Path],
) -> str:
    """Run the P-AI-4 audits, render as a markdown section."""
    lines = ["## 👤 face library audit  (P-AI-4)\n"]

    try:
        from pixcull.pipeline.face_audit import (
            CLUSTER_PAIR_OUTLIER_SIM,
            cluster_precision_audit,
            cross_run_continuity_audit,
            library_fragmentation_audit,
        )
        from pixcull.pipeline.face_library import (
            load_library,
            load_run_centroids,
        )
    except ImportError as exc:
        lines.append(f"_face audit unavailable: {exc}_\n")
        return "\n".join(lines)

    # ---- per-cluster precision -------------------------------------
    scores_csv = out_dir / "scores.csv"
    if not scores_csv.exists():
        lines.append(f"_no scores.csv at {scores_csv} — skipping cluster precision_\n")
        cluster_reports = []
    else:
        import pandas as pd
        df = pd.read_csv(scores_csv)
        if "face_cluster_id" not in df.columns or \
           "face_embeddings" not in df.columns:
            lines.append("_scores.csv missing face_cluster_id / "
                         "face_embeddings — skipping cluster precision_\n")
            cluster_reports = []
        else:
            by_cluster: dict[int, list[list[float]]] = {}
            for _, row in df.iterrows():
                cid = row.get("face_cluster_id")
                if cid is None or pd.isna(cid):
                    continue
                raw = row.get("face_embeddings")
                try:
                    embs = json.loads(raw) if isinstance(raw, str) else []
                except (ValueError, TypeError):
                    embs = []
                for e in embs:
                    if isinstance(e, list) and e:
                        by_cluster.setdefault(int(cid), []).append(e)
            cluster_reports = [
                cluster_precision_audit(embs, cluster_id=cid)
                for cid, embs in by_cluster.items()
            ]

    n_total = len(cluster_reports)
    n_polluted = sum(1 for r in cluster_reports if r.polluted)
    lines.append(f"- 簇精度: **{n_polluted} / {n_total} 污染**  "
                 f"(离群阈值 {CLUSTER_PAIR_OUTLIER_SIM:.2f})")
    if cluster_reports:
        lines.append("\n| cluster | 成员 | min 对相似度 | mean | 状态 |")
        lines.append("| ------- | ---- | -------------- | ---- | ---- |")
        for r in sorted(cluster_reports, key=lambda r: r.min_pair_sim):
            flag = "⚠ 污染" if r.polluted else "✓ 干净"
            lines.append(f"| {r.cluster_id} | {r.n_members} | "
                         f"{r.min_pair_sim:.3f} | {r.mean_pair_sim:.3f} | "
                         f"{flag} ({len(r.outlier_indices)} 离群) |")
    lines.append("")

    # ---- library fragmentation -------------------------------------
    if user_root is None:
        lines.append("_no user_root supplied — skipping library "
                     "fragmentation + continuity_\n")
        return "\n".join(lines)
    try:
        labels, lib_centroids = load_library(user_root)
    except OSError as exc:
        lines.append(f"_library load failed: {exc}_\n")
        return "\n".join(lines)

    by_label: dict[str, list[list[float]]] = {}
    for lab, c in zip(labels, lib_centroids):
        by_label.setdefault(str(lab), []).append(list(c))
    frag_reports = library_fragmentation_audit(by_label) if by_label else []

    n_frag = sum(1 for r in frag_reports if r.fragmented)
    lines.append(f"- 库碎片化: **{n_frag} / {len(frag_reports)} 接近上限**")
    if frag_reports:
        lines.append("\n| 标签 | centroid 数 | 状态 |")
        lines.append("| --- | --- | --- |")
        for r in frag_reports:
            flag = "⚠ 接近上限" if r.fragmented else "✓ 充裕"
            lines.append(f"| {r.label} | {r.n_centroids} | {flag} |")
    lines.append("")

    # ---- cross-run continuity --------------------------------------
    try:
        this_run = load_run_centroids(out_dir)
    except OSError as exc:
        lines.append(f"_run centroids load failed: {exc}_\n")
        return "\n".join(lines)
    if this_run is None or len(lib_centroids) == 0:
        lines.append("- 跨 run 连续性: 无足够数据(库或本 run 没有 centroid)\n")
    else:
        _, cur_centroids = this_run
        cur_list = [list(c) for c in cur_centroids]
        lib_list = [list(c) for c in lib_centroids]
        cont = cross_run_continuity_audit(cur_list, lib_list)
        emoji = "🟢" if cont.match_rate >= 70 else \
                ("🟡" if cont.match_rate >= 40 else "🔴")
        lines.append(f"- 跨 run 连续性: {emoji} **{cont.match_rate:.1f}%** "
                     f"({cont.n_matched_to_library} / "
                     f"{cont.n_current_clusters} 簇匹配到历史身份)\n")
    return "\n".join(lines)


def _emit_scene_audit_section(scores_csv: Path) -> str:
    """P-CORE-2 — scene classifier distribution + abstain audit."""
    lines = ["## 📷 scene classifier audit  (P-CORE-2)\n"]
    if not scores_csv.exists():
        lines.append(f"_no scores.csv at {scores_csv}_\n")
        return "\n".join(lines)
    import pandas as pd
    df = pd.read_csv(scores_csv)
    if "scene" not in df.columns:
        lines.append("_scene column missing_\n")
        return "\n".join(lines)

    n = len(df)
    scenes = Counter(df["scene"].dropna().tolist())

    # Abstain count: scene == "unknown" (P-CORE-2's abstain sentinel)
    n_abstain = int(scenes.get("unknown", 0))
    lines.append(f"- 总行数: **{n}**")
    lines.append(f"- abstain (scene=unknown): **{n_abstain}** "
                 f"({100.0*n_abstain/n:.1f}%)")
    lines.append("")
    lines.append("| scene | 数量 | 占比 |")
    lines.append("| ----- | ---- | ---- |")
    for sc, cnt in scenes.most_common():
        pct = 100.0 * cnt / n
        lines.append(f"| {sc} | {cnt} | {pct:.1f}% |")
    lines.append("")

    # Sanity: any scene at > 40% suggests over-firing
    top_scene, top_n = scenes.most_common(1)[0]
    if top_n / n > 0.40:
        lines.append(f"> ⚠ **{top_scene}** 占比 {100*top_n/n:.1f}% 超过 40% — "
                     "可能存在 prior 还需收紧或者样本本身就是单一场景。\n")
    return "\n".join(lines)


def _emit_wedding_coverage_section(scores_csv: Path) -> str:
    """P-PRO-4 — wedding moment coverage (only if any wedding rows)."""
    lines = []
    if not scores_csv.exists():
        return ""
    import pandas as pd
    df = pd.read_csv(scores_csv)
    wedding = df[df.get("scene") == "wedding"] if "scene" in df.columns \
              else pd.DataFrame()
    if wedding.empty:
        return ""   # silently omit on non-wedding runs

    lines.append("## 💒 wedding moment coverage  (P-PRO-4)\n")
    if "wedding_moment" not in df.columns:
        lines.append("_wedding_moment column missing — re-run pipeline_\n")
        return "\n".join(lines)

    from pixcull.scoring.wedding_moments import (
        coverage_audit, moment_label_zh,
    )
    rows = wedding.to_dict(orient="records")
    rpt = coverage_audit(rows)
    lines.append(f"- 婚礼总照片: **{rpt.n_rows}**")
    lines.append(f"- 已识别 moment: **{rpt.n_rows - rpt.n_unknown}**")
    lines.append(f"- 抽象 / 未识别: **{rpt.n_unknown}**")
    lines.append(f"- mandatory moment 覆盖率: **{rpt.coverage_pct:.1f}%**")
    if rpt.missing_mandatory:
        lines.append("\n⚠ **未覆盖的 mandatory moment:**")
        for k in rpt.missing_mandatory:
            lines.append(f"  - {k} ({moment_label_zh(k)})")
    lines.append("\n| moment | 数量 |")
    lines.append("| --- | --- |")
    for k, cnt in sorted(rpt.moment_counts.items(),
                         key=lambda kv: -kv[1]):
        if cnt == 0: continue
        lines.append(f"| {k} ({moment_label_zh(k)}) | {cnt} |")
    lines.append("")
    return "\n".join(lines)


def _resolve_run_dir(run_id: str) -> Path:
    """Look for a run output dir under the standard PixCull location."""
    candidates = [
        Path("/tmp/pixcull_demo") / run_id / "output",
        Path.home() / "Library/Application Support/PixCull/runs" / run_id / "output",
    ]
    for c in candidates:
        if c.exists():
            return c
    sys.exit(f"can't find run output for {run_id} — tried {[str(c) for c in candidates]}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Unified PixCull post-run audit (face / scene / wedding).")
    ap.add_argument("run_id", nargs="?",
                    help="PixCull run id (looks under /tmp/pixcull_demo or "
                         "~/Library/Application Support/PixCull/runs).")
    ap.add_argument("--scores-csv", type=Path, default=None,
                    help="Bypass run discovery; audit this scores.csv "
                         "directly.")
    ap.add_argument("--user-root", type=Path, default=None,
                    help="User app-data root (for face library audit). "
                         "If omitted, face-library + continuity sections "
                         "are skipped.")
    ap.add_argument("--out", type=Path, default=None,
                    help="Write the markdown report to this file. "
                         "Default: stdout.")
    args = ap.parse_args()

    if args.scores_csv:
        out_dir = args.scores_csv.parent
        run_id = out_dir.parent.name if out_dir.parent.name != "/" \
                 else "unknown"
    elif args.run_id:
        out_dir = _resolve_run_dir(args.run_id)
        run_id = args.run_id
    else:
        ap.print_help(sys.stderr)
        sys.exit(2)

    scores_csv = out_dir / "scores.csv"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = [
        f"# PixCull audit · run `{run_id}`\n",
        f"_generated: {ts}_  ",
        f"_source: `{scores_csv}`_\n",
        _emit_scene_audit_section(scores_csv),
        _emit_face_audit_section(out_dir, args.user_root),
        _emit_wedding_coverage_section(scores_csv),
    ]
    report = "\n".join(p for p in parts if p)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(report)


if __name__ == "__main__":
    main()
