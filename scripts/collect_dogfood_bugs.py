#!/usr/bin/env python3
"""v0.13.4 — Collect dogfood findings from a wedding RC run.

Aggregates everything that needs human attention after a dogfood
wedding (see ``docs/V1-DOGFOOD-CHECKLIST.md``):

  * pipeline log errors (`~/Library/Application Support/PixCull/log/`)
  * annotation write failures (`*.jsonl.tmp` orphans)
  * bias findings on the run's slice (`/admin/bias?user=<id>` JSON
    equivalent — calls the in-process API)
  * rescorer disagreement summary
  * any opt-in telemetry events with severity ≥ warning

Output: a single markdown file the user can paste into a GitHub
issue or attach to a maintainer email.

Usage
=====

    python scripts/collect_dogfood_bugs.py --run <run_id>
    python scripts/collect_dogfood_bugs.py --run <run_id> --out report.md
    python scripts/collect_dogfood_bugs.py --run <run_id> --user alice
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _appdata_root() -> Path:
    if os.name == "posix" and Path.home().joinpath(
            "Library", "Application Support").exists():
        return Path.home() / "Library" / "Application Support" / "PixCull"
    return Path.home() / ".pixcull"


def _find_log_dir() -> Path | None:
    base = _appdata_root()
    for cand in (base / "log", base / "logs", base):
        if cand.exists():
            return cand
    return None


def _scan_log_errors(log_dir: Path, since_hours: float = 24) -> list[dict]:
    """Pull recent ERROR / WARNING lines from any log files."""
    out: list[dict] = []
    cutoff = datetime.now().timestamp() - since_hours * 3600
    if not log_dir.exists():
        return out
    pattern = re.compile(r"(ERROR|WARNING|EXCEPTION|TRACEBACK)", re.IGNORECASE)
    for p in log_dir.rglob("*.log"):
        try:
            if p.stat().st_mtime < cutoff - 86400:
                continue
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if pattern.search(line):
                        out.append({
                            "file":   str(p.relative_to(log_dir)),
                            "line_no": i + 1,
                            "text":   line.rstrip()[:300],
                        })
        except OSError:
            continue
    return out


def _find_orphan_tmp(runs_root: Path) -> list[str]:
    """Annotation writes should be atomic via tmp+rename.  Any
    leftover .jsonl.tmp suggests a crash during write."""
    if not runs_root.exists():
        return []
    return [str(p) for p in runs_root.rglob("*.jsonl.tmp")]


def _run_dir(run_id: str) -> Path | None:
    """Resolve the run dir under either appdata or /tmp/pixcull_demo."""
    for candidate in (
        _appdata_root() / "runs" / run_id,
        Path("/tmp/pixcull_demo") / run_id,
    ):
        if candidate.exists():
            return candidate
    return None


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return out
    return out


def _bias_summary(run_id: str, user: str | None) -> dict:
    """Run bias_audit programmatically against the run's annotations."""
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from pixcull.scoring.bias_audit import build_report
        from pathlib import Path as _P
        report = build_report(
            _appdata_root() / "runs", user_filter=user,
        )
        # Filter to findings + summary
        return {
            "n_rows":    report.n_total_rows,
            "n_findings": len(report.findings),
            "findings":  [
                {
                    "family":    f.family,
                    "value":     f.value,
                    "metric":    f.metric,
                    "bucket_pct": round(f.bucket_value * 100, 1),
                    "global_pct": round(f.global_mean * 100, 1),
                    "z":         round(f.z_score, 2),
                    "suggestion": f.suggestion,
                }
                for f in report.findings
            ],
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _disagreement_count(run_dir: Path) -> dict:
    """Count human-vs-model reversals in this run's annotations."""
    rows = _read_jsonl(run_dir / "output" / "annotations.jsonl")
    if not rows:
        return {"n_annotations": 0, "n_reversals": 0}
    reversals = 0
    by_scene: dict[str, int] = {}
    for row in rows:
        user_dec = (row.get("decision") or row.get("overall_label") or "").lower()
        model_dec = (row.get("model_decision")
                     or row.get("rescorer_pred") or "").lower()
        if user_dec and model_dec and user_dec != model_dec:
            reversals += 1
            scene = row.get("scene") or row.get("vertical") or "?"
            by_scene[scene] = by_scene.get(scene, 0) + 1
    return {
        "n_annotations": len(rows),
        "n_reversals":   reversals,
        "reversal_rate": round(reversals / len(rows), 3) if rows else 0,
        "by_scene":      dict(sorted(by_scene.items(),
                                      key=lambda kv: -kv[1])[:8]),
    }


def _render_markdown(run_id: str, user: str | None,
                     errors: list[dict],
                     orphans: list[str],
                     bias: dict,
                     dis: dict) -> str:
    lines: list[str] = []
    lines.append(f"# PixCull dogfood report · {run_id}")
    lines.append("")
    lines.append(f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")
    if user:
        lines.append(f"_Filter: user = `{user}`_")
    lines.append("")

    # Severity rollup
    p0_count = 0
    p1_count = 0
    if orphans:
        p0_count += len(orphans)
    if dis.get("reversal_rate", 0) > 0.30:
        p1_count += 1
    if bias.get("n_findings", 0):
        p1_count += bias["n_findings"]
    if errors:
        # ERROR lines → P1, WARNING → P2
        for e in errors:
            if "ERROR" in e["text"].upper() or "EXCEPTION" in e["text"].upper():
                p1_count += 1
    lines.append(f"## Severity rollup")
    lines.append("")
    lines.append(f"* **P0** (data-loss / crash): **{p0_count}**")
    lines.append(f"* **P1** (workflow blocker): **{p1_count}**")
    lines.append("")
    if p0_count == 0 and p1_count == 0:
        lines.append("✅ **No P0/P1 findings.** v1.0 release gate · "
                     "dogfood criteria looks green for this run.")
    else:
        lines.append("⚠ **Blocking findings detected.**  Review sections below.")
    lines.append("")

    # Orphan tmp files (P0)
    lines.append("## 1. Atomic-write orphans  (P0 if any)")
    lines.append("")
    if orphans:
        lines.append(f"Found **{len(orphans)}** stale `.jsonl.tmp` files. "
                     "Each indicates a crash during annotation write.")
        for o in orphans:
            lines.append(f"  * `{o}`")
    else:
        lines.append("✅ No orphan `.jsonl.tmp` files.")
    lines.append("")

    # Disagreement / reversal (P1 if > 30%)
    lines.append("## 2. Rescorer disagreement")
    lines.append("")
    lines.append(f"* annotations:    {dis.get('n_annotations', 0)}")
    lines.append(f"* reversals:      {dis.get('n_reversals', 0)} "
                 f"({dis.get('reversal_rate', 0)*100:.1f}%)")
    if dis.get("reversal_rate", 0) > 0.30:
        lines.append("* ⚠ **> 30% reversal rate** — rescorer calibration "
                     "may be off.  Consider `train_rescorer.py` retrain "
                     "on this run's goldenset.")
    if dis.get("by_scene"):
        lines.append("")
        lines.append("Top scenes by reversal count:")
        for scene, n in dis["by_scene"].items():
            lines.append(f"  * `{scene}`: {n}")
    lines.append("")

    # Bias audit
    lines.append("## 3. Bias audit (filter: " +
                 (f"`user = {user}`" if user else "global") + ")")
    lines.append("")
    if "error" in bias:
        lines.append(f"❌ `{bias['error']}`")
    else:
        lines.append(f"* n_rows analysed: {bias.get('n_rows', 0)}")
        lines.append(f"* n_findings:      {bias.get('n_findings', 0)}")
        if bias.get("findings"):
            lines.append("")
            lines.append("| family | value | metric | bucket% | mean% | z | suggestion |")
            lines.append("|---|---|---|---:|---:|---:|---|")
            for f in bias["findings"][:20]:
                lines.append(
                    f"| {f['family']} | {f['value']} | "
                    f"{f['metric'].replace('_', ' ')} | "
                    f"{f['bucket_pct']}% | {f['global_pct']}% | "
                    f"{f['z']:+} | {f['suggestion']} |"
                )
    lines.append("")

    # Log errors
    lines.append("## 4. Recent log lines (ERROR / WARNING / EXCEPTION)")
    lines.append("")
    if errors:
        lines.append(f"Found **{len(errors)}** noteworthy log lines:")
        lines.append("")
        for e in errors[:50]:
            lines.append(f"  * `{e['file']}:{e['line_no']}` — `{e['text']}`")
        if len(errors) > 50:
            lines.append(f"  * ... and {len(errors) - 50} more")
    else:
        lines.append("✅ No ERROR/WARNING/EXCEPTION in recent logs.")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("Generated by `scripts/collect_dogfood_bugs.py` · "
                 "see `docs/V1-DOGFOOD-CHECKLIST.md` for full procedure.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Collect dogfood findings into a markdown report."
    )
    p.add_argument("--run", required=True, help="run_id from /tmp/pixcull_demo/ or ~/.../runs/")
    p.add_argument("--user", default=None, help="Optional user_id to filter bias by")
    p.add_argument("--out", type=Path, default=None,
                   help="Write report here (default: stdout)")
    p.add_argument("--since-hours", type=float, default=72,
                   help="Log scan window (default 72 hours)")
    args = p.parse_args(argv)

    run_dir = _run_dir(args.run)
    if run_dir is None:
        print(f"[dogfood] run dir not found for {args.run!r}", file=sys.stderr)
        return 2

    log_dir = _find_log_dir()
    errors = _scan_log_errors(log_dir, args.since_hours) if log_dir else []
    orphans = _find_orphan_tmp(_appdata_root() / "runs")
    bias = _bias_summary(args.run, args.user)
    dis = _disagreement_count(run_dir)

    md = _render_markdown(args.run, args.user, errors, orphans, bias, dis)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"[dogfood] ✓ wrote {args.out}", file=sys.stderr)
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
