"""V19.2 — diff per-axis R²/MAE between two rescorer_axis_meta.json files.

Usage:
    python scripts/compare_axis_rescorers.py \\
        models/rescorer_axis_meta.json \\
        /tmp/models_v19_2/rescorer_axis_meta.json

Pretty-prints a table with the per-axis Δ R² and Δ MAE. Calls out
axes that crossed a threshold (≥0.05 R² gain = "win", ≤-0.05 = "regression").
Exit code 0 if any axis improved, 1 otherwise — useful in CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load(p: Path) -> dict[str, dict]:
    d = json.loads(p.read_text("utf-8"))
    return {a["axis"]: a for a in d.get("axes", [])}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("before", type=Path)
    p.add_argument("after", type=Path)
    p.add_argument("--win-threshold", type=float, default=0.05,
                    help="ΔR² ≥ this counts as a win (default 0.05)")
    args = p.parse_args()

    if not args.before.exists():
        print(f"ERROR: missing {args.before}", file=sys.stderr)
        return 2
    if not args.after.exists():
        print(f"ERROR: missing {args.after}", file=sys.stderr)
        return 2

    before = _load(args.before)
    after = _load(args.after)
    axes = sorted(set(before) | set(after))
    if not axes:
        print("no axes in either meta", file=sys.stderr)
        return 2

    print(f"\nBEFORE: {args.before}")
    print(f"AFTER:  {args.after}\n")
    print(f"  {'axis':12s}  {'rows':>14s}  {'CV R²':>16s}  {'CV MAE':>16s}  {'verdict':>10s}")
    print("  " + "-" * 80)

    any_win = False
    for axis in axes:
        b = before.get(axis, {})
        a = after.get(axis, {})
        rb, ra = b.get("rows", 0), a.get("rows", 0)
        r2b, r2a = b.get("cv_r2", float("nan")), a.get("cv_r2", float("nan"))
        mb, ma = b.get("cv_mae", float("nan")), a.get("cv_mae", float("nan"))
        dr2 = (r2a - r2b) if (r2b == r2b and r2a == r2a) else float("nan")
        dmae = (ma - mb) if (mb == mb and ma == ma) else float("nan")

        verdict = "—"
        if dr2 == dr2:
            if dr2 >= args.win_threshold:
                verdict = "🏆 win"
                any_win = True
            elif dr2 <= -args.win_threshold:
                verdict = "📉 regr"
            else:
                verdict = "≈"

        print(f"  {axis:12s}  {rb:>5d} → {ra:<5d}  "
              f"{r2b:>6.3f} → {r2a:.3f} ({dr2:+.3f})  "
              f"{mb:>6.3f} → {ma:.3f} ({dmae:+.3f})  {verdict:>10s}")

    print()
    return 0 if any_win else 1


if __name__ == "__main__":
    raise SystemExit(main())
