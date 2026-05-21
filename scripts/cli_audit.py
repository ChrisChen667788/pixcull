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


def _emit_icc_section(
    scores_csv: Path,
    image_root: Optional[Path] = None,
) -> str:
    """P-PRO-6 — color-space consistency audit.

    Reads ICC profile + EXIF ColorSpace tag from each photo
    referenced in scores.csv (under the optional image_root, or
    using the absolute path stored in the ``path`` column when
    it exists).  Flags inconsistency (≥ 5% files in a non-majority
    color space) so the photographer can re-export before
    delivery.
    """
    lines = ["## 🎨 color-space audit  (P-PRO-6)\n"]
    if not scores_csv.exists():
        lines.append(f"_no scores.csv at {scores_csv}_\n")
        return "\n".join(lines)
    try:
        from pixcull.io.icc import audit_color_space, read_color_profile
    except ImportError as exc:
        lines.append(f"_color-space audit unavailable: {exc}_\n")
        return "\n".join(lines)

    import pandas as pd
    df = pd.read_csv(scores_csv)
    # Prefer the ``path`` column (absolute) when present; fall back
    # to image_root/filename for scan-mode runs.
    profiles = []
    n_skip = 0
    for _, row in df.iterrows():
        fn = row.get("filename")
        if not fn or pd.isna(fn):
            continue
        # Try absolute path first
        raw_path = row.get("path")
        p: Optional[Path] = None
        if isinstance(raw_path, str) and raw_path:
            p = Path(raw_path)
        elif image_root:
            p = image_root / str(fn)
        if p is None or not p.is_file():
            n_skip += 1
            continue
        profiles.append(read_color_profile(p))

    if not profiles:
        lines.append(f"_no readable image files referenced (skipped {n_skip})_\n")
        return "\n".join(lines)

    rpt = audit_color_space(profiles)
    emoji = "🟢" if rpt.is_consistent else "🔴"
    lines.append(f"- 总 audit 文件数: **{rpt.n_files}**  "
                 f"(跳过 {n_skip} 张无法解析)")
    lines.append(f"- 一致性: {emoji} **{rpt.consistency_pct:.1f}%** "
                 f"({'一致' if rpt.is_consistent else '混杂'})")
    lines.append(f"- 主色彩空间: **{rpt.canonical_majority or 'unknown'}**")
    lines.append(f"- 缺少 ICC profile 的文件: **{rpt.n_no_icc}**")
    lines.append("\n| 色彩空间 | 数量 |")
    lines.append("| --- | --- |")
    for cs, cnt in sorted(rpt.counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {cs} | {cnt} |")
    if not rpt.is_consistent:
        lines.append("\n⚠ **少数派文件(色彩空间与多数不一致):**")
        # Cap at 30 lines so the report doesn't explode on big runs
        for fn in rpt.minority_files[:30]:
            lines.append(f"  - {fn}")
        if len(rpt.minority_files) > 30:
            lines.append(f"  - ... 还有 {len(rpt.minority_files) - 30} 个")
    lines.append("")
    return "\n".join(lines)


def _emit_wedding_coverage_section(
    scores_csv: Path,
    mandatory_preset: str = "western",
) -> str:
    """P-PRO-4 — wedding moment coverage (only if any wedding rows).

    P-PRO-4.3 added the ``mandatory_preset`` arg.  Pass "western"
    (default) for the original first_dance / cake_cutting list,
    "chinese" for the tea-ceremony / kneeling-bow list, or any
    other key from MANDATORY_PRESETS.
    """
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
        MANDATORY_PRESETS, coverage_audit, moment_label_zh,
    )
    mandatory_keys = MANDATORY_PRESETS.get(mandatory_preset) \
                     if mandatory_preset != "western" else None
    rows = wedding.to_dict(orient="records")
    rpt = coverage_audit(rows, mandatory_keys=mandatory_keys)

    preset_label = {"western": "西式", "chinese": "中式"}.get(
        mandatory_preset, mandatory_preset
    )
    lines.append(f"- 婚礼总照片: **{rpt.n_rows}**")
    lines.append(f"- 已识别 moment: **{rpt.n_rows - rpt.n_unknown}**")
    lines.append(f"- 抽象 / 未识别: **{rpt.n_unknown}**")
    lines.append(f"- mandatory moment ({preset_label}) "
                 f"覆盖率: **{rpt.coverage_pct:.1f}%**")
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
    ap.add_argument("--mandatory-preset", default="western",
                    choices=("western", "chinese"),
                    help="P-PRO-4.3 — which wedding tradition's "
                         "mandatory-moment list to score against. "
                         "Default: western (first_dance, cake_cutting, "
                         "ring_exchange, ...). Use 'chinese' for "
                         "tea-ceremony / kneeling-bow / door-block "
                         "weddings.")
    ap.add_argument("--image-root", type=Path, default=None,
                    help="P-PRO-6 — root folder containing the actual "
                         "image files (used by the ICC color-space "
                         "audit).  Defaults to the run's input/ "
                         "directory if not specified.  Skipped silently "
                         "when no images are reachable.")
    args = ap.parse_args()

    if args.scores_csv:
        out_dir = args.scores_csv.parent
        run_id = out_dir.parent.name if out_dir.parent.name != "/" \
                 else "unknown"
        # P-PRO-6 fix — when --scores-csv points to a custom filename
        # (not literally "scores.csv"), use that path directly.
        # The previous code rebuilt out_dir / "scores.csv" which broke
        # callers passing e.g. predictions.csv or audit_input.csv.
        scores_csv = args.scores_csv
    elif args.run_id:
        out_dir = _resolve_run_dir(args.run_id)
        run_id = args.run_id
        scores_csv = out_dir / "scores.csv"
    else:
        ap.print_help(sys.stderr)
        sys.exit(2)
    # Default image root for the ICC audit: the run's input/ folder
    # which exists in upload-mode runs.  Scan-mode runs store
    # absolute paths in scores.csv's "path" column so image_root
    # isn't required there.
    image_root = args.image_root
    if image_root is None:
        candidate = out_dir.parent / "input"
        if candidate.is_dir():
            image_root = candidate

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = [
        f"# PixCull audit · run `{run_id}`\n",
        f"_generated: {ts}_  ",
        f"_source: `{scores_csv}`_\n",
        _emit_scene_audit_section(scores_csv),
        _emit_face_audit_section(out_dir, args.user_root),
        _emit_wedding_coverage_section(scores_csv,
                                       mandatory_preset=args.mandatory_preset),
        _emit_icc_section(scores_csv, image_root=image_root),
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
