#!/usr/bin/env python3
"""v0.10-P0-3 — CI gate: rescorer V3 must not regress vs the
previous shipped version by more than 1% recall@5.

Reads two ``eval_rescorer.py --json-out`` artifacts and exits
non-zero when the candidate dropped > --tolerance recall@5
compared to the baseline.  Designed for the GitHub Actions
workflow at ``.github/workflows/ci.yml``:

    - run: |
        python scripts/eval_rescorer.py \\
            artifacts/eval_v3.csv artifacts/eval_v2.csv \\
            --ground-truth goldenset/ground_truth.csv \\
            --json-out artifacts/rescorer_eval.json
    - run: |
        python scripts/ci_rescorer_regression.py \\
            artifacts/rescorer_eval.json

Exit codes:
  0 → candidate ≥ baseline (or no baseline yet)
  2 → candidate regressed > tolerance
  3 → eval JSON malformed / missing keys
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def gate(eval_json: dict, tolerance: float = 0.01) -> tuple[int, str]:
    """Returns (exit_code, message).  tolerance is in absolute
    recall units (0.01 = 1 percentage point)."""
    cand = eval_json.get("candidate")
    base = eval_json.get("baseline")
    if not isinstance(cand, dict):
        return 3, "missing 'candidate' block in eval JSON"
    if base is None:
        # First-time eval — no regression possible.
        return 0, "no baseline provided — skipping regression check"
    if not isinstance(base, dict):
        return 3, "'baseline' present but malformed"
    c = (cand.get("recall_at") or {}).get("k=5")
    b = (base.get("recall_at") or {}).get("k=5")
    if c is None or b is None:
        return 3, "recall@5 missing from one of the eval blocks"
    delta = c - b
    if delta + tolerance < 0:
        return 2, (
            f"REGRESSION: recall@5 candidate {c:.3f} < baseline {b:.3f}"
            f" (delta {delta * 100:+.2f}pp,"
            f" tolerance {tolerance * 100:.1f}pp)"
        )
    return 0, (
        f"OK: recall@5 candidate {c:.3f} vs baseline {b:.3f}"
        f" (delta {delta * 100:+.2f}pp)"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="CI gate: enforce no rescorer recall@5 regression."
    )
    p.add_argument("eval_json", type=Path,
                   help="JSON output of eval_rescorer.py --json-out")
    p.add_argument("--tolerance", type=float, default=0.01,
                   help="max allowed recall@5 drop (default 1pp)")
    args = p.parse_args(argv)

    try:
        doc = json.loads(args.eval_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[ci-rescorer] read failed: {exc}", file=sys.stderr)
        return 3
    code, msg = gate(doc, tolerance=args.tolerance)
    print(f"[ci-rescorer] {msg}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
