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


def _emit_exif_section(
    scores_csv: Path,
    image_root: Optional[Path] = None,
) -> str:
    """P-PRO-7 — EXIF completeness audit.

    Mirrors the ICC audit shape — same image-resolution path + same
    graceful-skip semantics when files aren't reachable.
    """
    lines = ["## 📸 EXIF completeness audit  (P-PRO-7)\n"]
    if not scores_csv.exists():
        lines.append(f"_no scores.csv at {scores_csv}_\n")
        return "\n".join(lines)
    try:
        from pixcull.io.exif_audit import (
            EXIF_FIELDS_TO_AUDIT,
            audit_exif_completeness,
            read_exif_fields,
        )
    except ImportError as exc:
        lines.append(f"_EXIF audit unavailable: {exc}_\n")
        return "\n".join(lines)

    import pandas as pd
    df = pd.read_csv(scores_csv)
    profiles = []
    n_skip = 0
    for _, row in df.iterrows():
        fn = row.get("filename")
        if not fn or pd.isna(fn):
            continue
        raw_path = row.get("path")
        p: Optional[Path] = None
        if isinstance(raw_path, str) and raw_path:
            p = Path(raw_path)
        elif image_root:
            p = image_root / str(fn)
        if p is None or not p.is_file():
            n_skip += 1
            continue
        profiles.append(read_exif_fields(p))

    if not profiles:
        lines.append(f"_no readable image files referenced (skipped {n_skip})_\n")
        return "\n".join(lines)

    rpt = audit_exif_completeness(profiles)
    lines.append(f"- 总 audit 文件数: **{rpt.n_files}**  "
                 f"(跳过 {n_skip} 张无法解析)")
    lines.append(f"- 关键字段缺失文件: **{len(rpt.missing_critical)}** "
                 f"(GPS / 镜头 / 拍摄时间)")
    lines.append("\n| 字段 | 标签 | 覆盖率 | 缺失数 |")
    lines.append("| --- | --- | ---: | ---: |")
    # Sort fields by ascending presence (worst-first) so the report
    # surfaces problems quickly.
    sorted_fields = sorted(
        EXIF_FIELDS_TO_AUDIT.items(),
        key=lambda kv: rpt.presence_pct(kv[0]),
    )
    for key, label in sorted_fields:
        pct = rpt.presence_pct(key)
        missing = rpt.n_files - rpt.per_field_present.get(key, 0)
        emoji = "🔴" if pct < 50 else ("🟡" if pct < 95 else "🟢")
        lines.append(f"| {key} | {label} | {emoji} {pct:.1f}% | {missing} |")
    if rpt.missing_critical:
        lines.append("\n⚠ **关键字段缺失的文件(最严重的前 30):**")
        for fn, missing in rpt.missing_critical[:30]:
            zh = [EXIF_FIELDS_TO_AUDIT.get(k, k) for k in missing]
            lines.append(f"  - `{fn}` 缺: {', '.join(zh)}")
        if len(rpt.missing_critical) > 30:
            lines.append(f"  - … 还有 {len(rpt.missing_critical) - 30} 个")
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


def _emit_delivery_gate(
    scores_csv: Path,
    out_dir: Path,
    user_root: Optional[Path],
    mandatory_preset: str,
    image_root: Optional[Path],
) -> str:
    """P-PRO-8 — aggregate the 5 audits into a single pass/fail line.

    Thresholds per category (each is a "PASS" / "WARN" / "FAIL"):

      · SCENE — over-firing warning (one scene > 60%) → WARN.
        Abstain > 50% → WARN.  Neither → PASS.
      · FACE  — any polluted cluster → WARN.  > 30% clusters
        polluted → FAIL.  No clusters / no data → PASS (neutral).
      · WEDDING — mandatory coverage < 80% → WARN.  < 50% → FAIL.
        Coverage 100% → PASS.  No wedding rows → skipped from
        the gate.
      · ICC   — consistency < 95% → WARN.  < 80% → FAIL.
      · EXIF  — > 10% files missing a critical field → WARN.
        > 50% → FAIL.

    Overall:
      PASS — every category is PASS (or N/A)
      WARN — at least one WARN, no FAIL
      FAIL — at least one FAIL

    Used as a release gate — CI / pre-delivery scripts can grep
    for "Overall: PASS" or check exit code.
    """
    import json as _json
    from collections import Counter
    lines = ["## 🚦 delivery gate (P-PRO-8)\n"]

    if not scores_csv.exists():
        lines.append("_no scores.csv — gate cannot run_\n")
        return "\n".join(lines)
    import pandas as pd
    df = pd.read_csv(scores_csv)

    statuses: list[tuple[str, str, str]] = []  # (category, status, why)

    # SCENE
    if "scene" in df.columns and len(df) >= 10:
        c = Counter(df["scene"].dropna().tolist())
        n = len(df)
        top_pct = (c.most_common(1)[0][1] / n) if c else 0
        unk_pct = (c.get("unknown", 0) / n)
        if unk_pct > 0.50:
            statuses.append(("scene", "WARN",
                             f"abstain rate {unk_pct*100:.0f}% > 50%"))
        elif top_pct > 0.60:
            statuses.append(("scene", "WARN",
                             f"single scene {c.most_common(1)[0][0]} {top_pct*100:.0f}% > 60%"))
        else:
            statuses.append(("scene", "PASS", ""))
    else:
        statuses.append(("scene", "N/A", "no scene column"))

    # FACE — count clusters + polluted clusters
    try:
        from pixcull.pipeline.face_audit import cluster_precision_audit
        polluted = total = 0
        if "face_cluster_id" in df.columns \
           and "face_embeddings" in df.columns:
            by_cluster: dict[int, list[list[float]]] = {}
            for _, row in df.iterrows():
                cid = row.get("face_cluster_id")
                if cid is None or pd.isna(cid):
                    continue
                raw = row.get("face_embeddings")
                try:
                    embs = _json.loads(raw) if isinstance(raw, str) else []
                except (ValueError, TypeError):
                    embs = []
                for e in embs:
                    if isinstance(e, list) and e:
                        by_cluster.setdefault(int(cid), []).append(e)
            for cid, embs in by_cluster.items():
                rpt = cluster_precision_audit(embs, cluster_id=cid)
                total += 1
                if rpt.polluted:
                    polluted += 1
        if total == 0:
            statuses.append(("face", "N/A", "no clusters"))
        elif polluted == 0:
            statuses.append(("face", "PASS", ""))
        elif polluted / total > 0.30:
            statuses.append(("face", "FAIL",
                             f"{polluted}/{total} clusters polluted"))
        else:
            statuses.append(("face", "WARN",
                             f"{polluted}/{total} clusters polluted"))
    except (ImportError, OSError, ValueError):
        statuses.append(("face", "N/A", "audit unavailable"))

    # WEDDING (only if any wedding rows)
    wedding_rows = df[df.get("scene") == "wedding"] \
                   if "scene" in df.columns else None
    if wedding_rows is None or len(wedding_rows) == 0:
        statuses.append(("wedding", "N/A", "no wedding rows"))
    elif "wedding_moment" not in df.columns:
        statuses.append(("wedding", "N/A", "no moment classifier output"))
    else:
        from pixcull.scoring.wedding_moments import (
            MANDATORY_PRESETS, coverage_audit,
        )
        mand_keys = MANDATORY_PRESETS.get(mandatory_preset) \
                    if mandatory_preset != "western" else None
        rpt = coverage_audit(wedding_rows.to_dict(orient="records"),
                             mandatory_keys=mand_keys)
        pct = rpt.coverage_pct
        if pct < 50:
            statuses.append(("wedding", "FAIL",
                             f"mandatory coverage {pct:.0f}% < 50%"))
        elif pct < 80:
            statuses.append(("wedding", "WARN",
                             f"mandatory coverage {pct:.0f}% < 80%"))
        else:
            statuses.append(("wedding", "PASS", ""))

    # ICC — re-use the audit logic so the gate doesn't drift from
    # the per-section thresholds.
    try:
        from pixcull.io.icc import audit_color_space, read_color_profile
        profiles = []
        for _, row in df.iterrows():
            fn = row.get("filename")
            if not fn or pd.isna(fn): continue
            raw_p = row.get("path")
            p: Optional[Path] = None
            if isinstance(raw_p, str) and raw_p:
                p = Path(raw_p)
            elif image_root:
                p = image_root / str(fn)
            if p is None or not p.is_file(): continue
            profiles.append(read_color_profile(p))
        if not profiles:
            statuses.append(("icc", "N/A", "no images reachable"))
        else:
            rpt = audit_color_space(profiles)
            pct = rpt.consistency_pct
            if pct < 80:
                statuses.append(("icc", "FAIL",
                                 f"{pct:.0f}% consistency"))
            elif pct < 95:
                statuses.append(("icc", "WARN",
                                 f"{pct:.0f}% consistency"))
            else:
                statuses.append(("icc", "PASS", ""))
    except (ImportError, OSError, ValueError):
        statuses.append(("icc", "N/A", "audit unavailable"))

    # EXIF — same pattern.
    try:
        from pixcull.io.exif_audit import (
            audit_exif_completeness, read_exif_fields,
        )
        profiles = []
        for _, row in df.iterrows():
            fn = row.get("filename")
            if not fn or pd.isna(fn): continue
            raw_p = row.get("path")
            p: Optional[Path] = None
            if isinstance(raw_p, str) and raw_p:
                p = Path(raw_p)
            elif image_root:
                p = image_root / str(fn)
            if p is None or not p.is_file(): continue
            profiles.append(read_exif_fields(p))
        if not profiles:
            statuses.append(("exif", "N/A", "no images reachable"))
        else:
            rpt = audit_exif_completeness(profiles)
            missing_pct = (len(rpt.missing_critical) /
                           rpt.n_files if rpt.n_files else 0) * 100
            if missing_pct > 50:
                statuses.append(("exif", "FAIL",
                                 f"{missing_pct:.0f}% files missing critical EXIF"))
            elif missing_pct > 10:
                statuses.append(("exif", "WARN",
                                 f"{missing_pct:.0f}% files missing critical EXIF"))
            else:
                statuses.append(("exif", "PASS", ""))
    except (ImportError, OSError, ValueError):
        statuses.append(("exif", "N/A", "audit unavailable"))

    # Overall
    has_fail = any(s == "FAIL" for _, s, _ in statuses)
    has_warn = any(s == "WARN" for _, s, _ in statuses)
    overall = "FAIL" if has_fail else ("WARN" if has_warn else "PASS")
    emoji = {"PASS": "🟢", "WARN": "🟡", "FAIL": "🔴", "N/A": "⚪"}

    lines.append(f"### Overall: {emoji[overall]} **{overall}**\n")
    lines.append("| 类别 | 状态 | 详情 |")
    lines.append("| --- | --- | --- |")
    for cat, status, why in statuses:
        cat_zh = {"scene": "场景", "face": "人脸库",
                  "wedding": "婚礼覆盖",
                  "icc": "色彩空间", "exif": "EXIF 完整性"}.get(cat, cat)
        lines.append(f"| {cat_zh} | {emoji[status]} {status} | {why} |")
    lines.append("")
    return "\n".join(lines)


def _markdown_to_print_html(md: str, run_id: str) -> str:
    """v0.4 P2 (4/4) — minimal Markdown → print-ready HTML.

    Same regex-based converter shape as the admin /delivery page
    uses, but with A4 / Letter print stylesheet so the output
    prints cleanly when fed to Chrome headless or the user's
    browser Save-as-PDF flow.  Branded header + footer.
    """
    import html as _html
    import re as _re

    def _md_to_html(text: str) -> str:
        out = _html.escape(text)
        out = _re.sub(r"^## +(.+)$", r"<h2>\1</h2>", out, flags=_re.MULTILINE)
        out = _re.sub(r"^# +(.+)$",  r"<h1>\1</h1>", out, flags=_re.MULTILINE)
        out = _re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", out)
        out = _re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)
        out = _re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"<i>\1</i>", out)
        def _tablize(block: str) -> str:
            lines = block.strip().splitlines()
            if len(lines) < 2:
                return block
            head = [c.strip() for c in lines[0].strip("|").split("|")]
            rows = []
            for ln in lines[2:]:
                cells = [c.strip() for c in ln.strip("|").split("|")]
                tds = "".join(f"<td>{c}</td>" for c in cells)
                rows.append(f"<tr>{tds}</tr>")
            ths = "".join(f"<th>{c}</th>" for c in head)
            return ("<table><thead><tr>" + ths + "</tr></thead>"
                    "<tbody>" + "".join(rows) + "</tbody></table>")
        out = _re.sub(r"(?:^\|.*\|$\n){2,}",
                      lambda m: _tablize(m.group(0)), out, flags=_re.MULTILINE)
        out = _re.sub(r"^( {0,4})- +(.+)$",
                      r"\1<li>\2</li>", out, flags=_re.MULTILINE)
        out = _re.sub(r"(?:<li>.+</li>\n)+",
                      lambda m: "<ul>" + m.group(0) + "</ul>", out)
        return out

    body = _md_to_html(md)
    return (
        "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
        f"<title>PixCull audit · {_html.escape(run_id)}</title>"
        "<style>"
        "@page { size: A4; margin: 18mm 16mm 22mm; }"
        # Use print-friendly light theme regardless of system pref
        "@media print {"
        "  body { background: white !important; color: #1a1d24 !important; }"
        "  table, th, td { background: white !important; color: #1a1d24 !important; }"
        "  .page-header, .page-footer { display: none !important; }"
        "  thead { display: table-header-group; }"
        "  tr, table { page-break-inside: avoid; }"
        "  h1, h2 { page-break-after: avoid; }"
        "  .pixcull-page-meta { display: block !important; }"
        "}"
        # Screen styles match the design system
        "body { font: 11pt/1.55 -apple-system, BlinkMacSystemFont, "
        "       'Segoe UI', 'PingFang SC', sans-serif;"
        "       color: #1a1d24; background: #f8f9fb;"
        "       margin: 0; padding: 24px; max-width: 780px; "
        "       margin-left: auto; margin-right: auto; }"
        ".pixcull-page-head {"
        "  display: flex; align-items: center; gap: 10px;"
        "  margin-bottom: 16px; padding-bottom: 10px;"
        "  border-bottom: 1.5px solid #e0e3e8;"
        "}"
        ".pixcull-mark {"
        "  width: 24px; height: 24px; color: #4f46e5;"
        "}"
        ".pixcull-wordmark {"
        "  font-weight: 700; font-size: 14pt;"
        "  letter-spacing: -0.02em;"
        "}"
        ".pixcull-wordmark b { color: #4f46e5; font-weight: 700; }"
        ".pixcull-page-meta {"
        "  font-size: 9pt; color: #6b7280;"
        "  margin-left: auto;"
        "}"
        "h1 { font-size: 20pt; font-weight: 700; letter-spacing: -0.02em; margin: 12px 0 6px; }"
        "h2 { font-size: 12pt; color: #6b7280; text-transform: uppercase;"
        "     letter-spacing: 0.04em; margin: 22px 0 8px; "
        "     padding-bottom: 4px; border-bottom: 1px solid #e0e3e8; }"
        "b { color: #1a1d24; }"
        "i { color: #6b7280; font-style: normal; font-size: 9.5pt; }"
        "code { font-family: ui-monospace, 'SF Mono', Menlo, monospace;"
        "       font-size: 9.5pt; padding: 1px 5px; background: #f0f2f5;"
        "       border-radius: 3px; color: #4f46e5; }"
        "table { width: 100%; border-collapse: collapse; font-size: 9.5pt;"
        "        margin: 4px 0 12px; border: 1px solid #e0e3e8;"
        "        border-radius: 6px; overflow: hidden; }"
        "th { text-align: left; padding: 6px 10px; background: #f0f2f5;"
        "     color: #6b7280; font-weight: 600; font-size: 8pt;"
        "     letter-spacing: 0.04em; text-transform: uppercase;"
        "     border-bottom: 1px solid #e0e3e8; }"
        "td { padding: 5px 10px; border-bottom: 1px solid #ebedf0; }"
        "tr:last-child td { border-bottom: none; }"
        "ul { margin: 4px 0 12px; padding-left: 18px; }"
        "li { margin: 1px 0; }"
        ".pixcull-foot { margin-top: 24px; padding-top: 12px;"
        "                border-top: 1px solid #e0e3e8; font-size: 8.5pt;"
        "                color: #9ca3af; text-align: center; }"
        "</style></head><body>"
        # Header
        "<div class='pixcull-page-head'>"
        "<svg class='pixcull-mark' viewBox='0 0 24 24' fill='none' "
        "stroke='currentColor' stroke-width='1.6' stroke-linecap='round' "
        "stroke-linejoin='round'>"
        "<circle cx='12' cy='12' r='10'/>"
        "<path d='M14.31 8 20.05 17.94'/><path d='M9.69 8h11.48'/>"
        "<path d='M7.38 12 13.12 2.06'/><path d='M9.69 16 3.95 6.06'/>"
        "<path d='M14.31 16H2.83'/><path d='M16.62 12 10.88 21.94'/>"
        "</svg>"
        "<span class='pixcull-wordmark'>Pix<b>Cull</b></span>"
        f"<span class='pixcull-page-meta'>delivery audit · {_html.escape(run_id)}</span>"
        "</div>"
        # Body
        f"<main>{body}</main>"
        # Footer
        "<div class='pixcull-foot'>"
        "Generated by PixCull cli_audit.py · all checks run locally · "
        "no photo data left this machine"
        "</div>"
        "</body></html>"
    )


def _resolve_thumb_path(
    row_filename: str,
    out_dir: Path,
    image_root: Path | None,
    row: dict | None = None,
) -> Path | None:
    """Best-effort lookup of a photo's image file.

    Tries — in order — the absolute `path` column (scan-mode runs),
    image_root / filename (upload-mode runs with a user-supplied
    root), out_dir.parent / "input" / filename (the canonical
    upload-mode location), and the run's own `thumbs/<filename>`
    cache (always present after a finished run).
    """
    if row is not None:
        abs_p = row.get("path")
        if isinstance(abs_p, str) and abs_p:
            p = Path(abs_p)
            if p.is_file():
                return p
    if image_root is not None:
        p = image_root / row_filename
        if p.is_file():
            return p
    # Standard upload-mode layout
    p = out_dir.parent / "input" / row_filename
    if p.is_file():
        return p
    # Cached thumbnail (always present after a finished pipeline)
    for sub in ("thumbs", "thumb"):
        p = out_dir / sub / row_filename
        if p.is_file():
            return p
        # Some runs cache as <stem>.jpg regardless of source extension
        p_jpg = (out_dir / sub / Path(row_filename).with_suffix(".jpg").name)
        if p_jpg.is_file():
            return p_jpg
    return None


def _build_executive_html_for_print(
    scores_csv: Path,
    out_dir: Path,
    image_root: Path | None,
    run_id: str,
    audit_md: str,
    *,
    photographer: str = "",
    client: str = "",
    event: str = "",
    event_date: str = "",
) -> str:
    """v0.9-P1-3 entry point.

    Reads scores.csv → rolls up the dashboard → picks best 5 +
    inconsistencies → embeds thumbnails → hands the whole thing to
    pixcull.report.executive_pdf to render the print-ready HTML.
    Falls back gracefully when scores.csv is missing (rare, but
    the unit test does it on purpose).
    """
    try:
        import pandas as pd
    except ImportError:
        # Pandas is a core dep; this branch only fires in extreme
        # test envs.  Render an empty dashboard rather than crash
        # the whole --pdf flow.
        rows: list[dict] = []
    else:
        try:
            df = pd.read_csv(scores_csv)
            # Coerce NaN → "" so the renderer's `or ""` patterns
            # work without spraying None into the HTML.
            rows = [{k: ("" if pd.isna(v) else v) for k, v in r.items()}
                    for _, r in df.iterrows()]
        except (FileNotFoundError, ValueError):
            rows = []

    from pixcull.report.executive_pdf import (
        build_executive_html, compute_dashboard, inline_thumb,
        pick_best_n, pick_inconsistencies,
    )

    dashboard = compute_dashboard(rows)
    best   = pick_best_n(rows, n=5)
    incons = pick_inconsistencies(rows, n=3)

    def _to_card(r: dict, badge: str, note: str = "") -> dict:
        fn = str(r.get("filename") or "")
        thumb_path = _resolve_thumb_path(fn, out_dir, image_root, row=r)
        return {
            "thumb":  inline_thumb(thumb_path),
            "fn":     fn,
            "badge":  badge,
            "score":  r.get("score_final"),
            "note":   note,
        }

    best_cards = [_to_card(r, "BEST") for r in best]
    incon_cards = []
    for r in incons:
        decision = str(r.get("decision") or "—").upper()
        sf = r.get("score_final")
        try:
            sf_n = float(sf)
            note = f"模型决定 {decision} · 综合分 {round(sf_n * 100)}%"
        except (TypeError, ValueError):
            note = f"模型决定 {decision}"
        incon_cards.append(_to_card(r, "WATCH", note=note))

    # Render the markdown audit body as a fragment (no <html>/<head>)
    # so it can be embedded inside the executive shell.
    audit_body_fragment = _markdown_to_body_fragment(audit_md)

    return build_executive_html(
        cover={
            "photographer": photographer,
            "client":       client,
            "event":        event,
            "event_date":   event_date,
        },
        dashboard=dashboard,
        best_cards=best_cards,
        inconsistency_cards=incon_cards,
        cull_top=list(dashboard.get("cull_reasons_top") or []),
        body_html=audit_body_fragment,
        run_id=run_id,
    )


def _markdown_to_body_fragment(md: str) -> str:
    """Same regex pipeline as :func:`_markdown_to_print_html` but
    without the surrounding <html>/<head>/<body> chrome — so the
    output can be embedded inside another document.
    """
    import html as _html
    import re as _re
    out = _html.escape(md)
    out = _re.sub(r"^## +(.+)$", r"<h2>\1</h2>", out, flags=_re.MULTILINE)
    out = _re.sub(r"^# +(.+)$",  r"<h1>\1</h1>", out, flags=_re.MULTILINE)
    out = _re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", out)
    out = _re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)
    out = _re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"<i>\1</i>", out)
    def _tablize(block: str) -> str:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            return block
        head = [c.strip() for c in lines[0].strip("|").split("|")]
        rows = []
        for ln in lines[2:]:
            cells = [c.strip() for c in ln.strip("|").split("|")]
            tds = "".join(f"<td>{c}</td>" for c in cells)
            rows.append(f"<tr>{tds}</tr>")
        ths = "".join(f"<th>{c}</th>" for c in head)
        return ("<table><thead><tr>" + ths + "</tr></thead>"
                "<tbody>" + "".join(rows) + "</tbody></table>")
    out = _re.sub(r"(?:^\|.*\|$\n){2,}",
                  lambda m: _tablize(m.group(0)), out, flags=_re.MULTILINE)
    out = _re.sub(r"^( {0,4})- +(.+)$",
                  r"\1<li>\2</li>", out, flags=_re.MULTILINE)
    out = _re.sub(r"(?:<li>.+</li>\n)+",
                  lambda m: "<ul>" + m.group(0) + "</ul>", out)
    return out


def _try_chrome_headless_pdf(html: str, out_pdf: Path) -> bool:
    """Try to print the HTML to PDF via Chrome headless.

    Looks for chromium / google-chrome / Chrome.app on PATH or in
    macOS default locations.  Returns True on success, False if
    no compatible browser is reachable.
    """
    import shutil
    import subprocess
    import tempfile
    candidates = []
    # macOS canonical paths
    for app in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Arc.app/Contents/MacOS/Arc",
    ):
        if Path(app).exists():
            candidates.append(app)
    # PATH fallbacks
    for bin_name in ("chromium", "chrome", "google-chrome", "chromium-browser"):
        p = shutil.which(bin_name)
        if p:
            candidates.append(p)
    if not candidates:
        return False
    chrome = candidates[0]
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False,
                                      mode="w", encoding="utf-8") as f:
        f.write(html)
        html_path = f.name
    try:
        result = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu",
             "--no-pdf-header-footer",
             f"--print-to-pdf={out_pdf}", f"file://{html_path}"],
            capture_output=True, timeout=60,
        )
        return out_pdf.exists() and out_pdf.stat().st_size > 0
    except (subprocess.TimeoutExpired, OSError):
        return False
    finally:
        try: Path(html_path).unlink()
        except OSError: pass


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
    ap.add_argument("--pdf", type=Path, default=None,
                    help="v0.4 P2 (4/4) — also export the report as a "
                         "PDF at this path.  Uses Chrome / Chromium / "
                         "Edge headless (auto-detected).  If no browser "
                         "is reachable, writes the print-ready HTML "
                         "instead and tells you to Cmd+P / Ctrl+P it.")
    # v0.9-P1-3 — executive-summary PDF mode.  Adds cover + ToC +
    # Strava-style key-numbers dashboard + thumbnail walls in front
    # of the existing audit body.  Only takes effect alongside --pdf.
    ap.add_argument("--executive", action="store_true",
                    help="v0.9-P1-3 — prepend a brand cover + ToC + "
                         "Strava-style key-numbers dashboard + thumbnail "
                         "walls to the --pdf output.  Use this for the "
                         "client-facing delivery report; the plain --pdf "
                         "remains the engineering audit format.")
    ap.add_argument("--client", default="",
                    help="v0.9-P1-3 — client name for the executive "
                         "cover page (e.g. '李慧 & 李翔').  Ignored "
                         "unless --executive is set.")
    ap.add_argument("--event", default="",
                    help="v0.9-P1-3 — event title for the cover "
                         "(e.g. '婚礼 · 仪式 + 草坪宴').")
    ap.add_argument("--event-date", default="",
                    help="v0.9-P1-3 — event date for the cover, "
                         "free-text (e.g. '2026-06-15').  Defaults to "
                         "today when omitted.")
    ap.add_argument("--photographer", default="",
                    help="v0.9-P1-3 — photographer / studio name shown "
                         "in the cover eyebrow.")
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
        # P-PRO-8 — top-of-report pass/fail summary so CI / pre-
        # delivery scripts can grep for "Overall: PASS" without
        # parsing the full body.
        _emit_delivery_gate(scores_csv, out_dir, args.user_root,
                            args.mandatory_preset, image_root),
        _emit_scene_audit_section(scores_csv),
        _emit_face_audit_section(out_dir, args.user_root),
        _emit_wedding_coverage_section(scores_csv,
                                       mandatory_preset=args.mandatory_preset),
        _emit_icc_section(scores_csv, image_root=image_root),
        _emit_exif_section(scores_csv, image_root=image_root),
    ]
    report = "\n".join(p for p in parts if p)

    # v0.4 P2 (4/4) — optional PDF render via Chrome headless.
    # v0.9-P1-3 — when --executive is set, swap in the executive-
    # summary HTML (cover + ToC + dashboard + thumbnail walls) and
    # pass the existing audit HTML as the trailing body.
    if args.pdf:
        args.pdf.parent.mkdir(parents=True, exist_ok=True)
        if args.executive:
            html_for_print = _build_executive_html_for_print(
                scores_csv, out_dir, image_root, run_id, report,
                photographer=args.photographer,
                client=args.client,
                event=args.event,
                event_date=args.event_date,
            )
        else:
            html_for_print = _markdown_to_print_html(report, run_id)
        if _try_chrome_headless_pdf(html_for_print, args.pdf):
            print(f"wrote {args.pdf}", file=sys.stderr)
        else:
            # No Chrome — drop the HTML next to the requested PDF
            # path with a .print.html suffix; tell the user how
            # to finish manually.
            html_path = args.pdf.with_suffix(".print.html")
            html_path.write_text(html_for_print, encoding="utf-8")
            print(f"⚠ no Chrome/Chromium/Edge found — wrote print-ready HTML to:",
                  file=sys.stderr)
            print(f"  {html_path}", file=sys.stderr)
            print(f"  Open it in your browser → File → Print → Save as PDF",
                  file=sys.stderr)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    elif not args.pdf:
        sys.stdout.write(report)


if __name__ == "__main__":
    main()
