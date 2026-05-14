"""V21.1 — auto-route scan candidates into empty vertical sample buckets.

ROADMAP P0.1: after V18 we still had 4 verticals with one empty bucket:

    wildlife: good=0     ← can't even tune (need ≥1 good + ≥1 bad)
    bird:     bad=0
    cosplay:  bad=0
    pet:      bad=0

V17.4's F1 grid-search is blocked on these; V17.5's DeepSeek phrase
generator also produces weaker output when one bucket has no examples
to contrast against.

This script reads ``<scan>.features.csv`` files (the rich-feature
output of scan_multi.py since V19.2) and routes the best matching
candidates into each empty / under-target bucket using per-vertical
heuristics. Output: actual JPGs copied into

    ~/Library/Application Support/PixCull/verticals/<key>/<bucket>/

via ``pixcull.verticals.save_sample`` so metadata.json updates
through the existing audit path.

Why heuristics, not LLM
-----------------------
Selecting "what makes a good wildlife shot" via an LLM would be
slower, more expensive, and harder to audit when the inevitable
mis-selection happens. The heuristics below encode what V17.4's
"clear good / clear bad" router already had to learn about — the
flags + score thresholds the rule stack itself uses.

Per-vertical routing rules
==========================
Each entry has:
  * ``scene``: scenes to draw candidates from
  * ``decision``: which rule-stack decision class to require
  * ``score_op`` / ``score_thresh``: min/max score_final
  * ``flags_required``: list of (substring, mode) — mode "all" or "none"
  * ``extra``: free-form pandas-query string for vertical-specific gates

Designed to be conservative — better to route 5 great candidates than
20 mediocre ones (the sample bank is meant to be the photographer's
style anchor, not the maximum). Cap per run via ``--max-per-bucket``.

Usage
-----
    python scripts/auto_seed_vertical_buckets.py \\
        /tmp/scan_v19_3/*.features.csv \\
        [--scan-jsons /tmp/scan_v19_3/*.json]   # for src_path lookup
        [--max-per-bucket 20]
        [--dry-run]                              # preview, don't copy
        [--vertical wildlife,bird]               # subset (default: all empty)

Notes
-----
* features.csv only has filenames; ``src_path`` lives in the sister
  ``<basename>.json``. Script reads both to find the actual file on
  disk.
* Re-runs are idempotent: ``save_sample`` content-hashes the filename
  so the same source file routed twice produces the same destination
  and overwrites itself.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from pixcull import verticals as vmod


# ---------------------------------------------------------------------------
# Per-vertical heuristics. Conservative on purpose.
# ---------------------------------------------------------------------------

# Each rule: (vertical, bucket, query string, score range, extra notes)
# The query operates on a merged dataframe with columns from features.csv
# (filename, scene, decision, laplacian_*, score_*, clipiqa, face_count,
# subject_fraction, ...).
ROUTING_RULES: dict[tuple[str, str], dict[str, Any]] = {
    ("wildlife", "good"): {
        "query": (
            "scene == 'wildlife' "
            "and decision == 'keep' "
            "and clipiqa > 0.55 "
            "and subject_fraction > 0.10 "
            "and score_final > 0.7 "
            "and score_sharpness > 0.7"
        ),
        "rationale": (
            "Wildlife keep with clean technicals: sharp, well-isolated "
            "subject (≥10% of frame), high CLIP-IQA + score. Excludes "
            "low-confidence cases — better to seed 5 great than 20 OK."
        ),
    },
    ("bird", "bad"): {
        "query": (
            "scene == 'wildlife' "
            "and decision == 'cull' "
            "and (score_sharpness < 0.5 or laplacian_subject < 100) "
            "and score_final < 0.5"
        ),
        "rationale": (
            "Wildlife culled by rule stack with soft subject — typical "
            "bird-shot fails (motion blur, missed focus, hand shake)."
        ),
    },
    ("cosplay", "bad"): {
        "query": (
            "scene in ('portrait', 'fashion', 'event') "
            "and decision == 'cull' "
            "and score_final < 0.45 "
            "and (face_count > 0 or subject_fraction > 0.15)"
        ),
        "rationale": (
            "Portrait/fashion/event culls with a clear human subject. "
            "Cosplay-relevant negatives: missed focus on costume detail, "
            "blown-out highlights on bright costumes, closed-eye/blink "
            "moments."
        ),
    },
    ("pet", "bad"): {
        "query": (
            "scene == 'wildlife' "
            "and decision in ('cull', 'maybe') "
            "and (face_count >= 1 or subject_fraction < 0.05) "
            "and score_final < 0.55"
        ),
        "rationale": (
            "Wildlife-scene rows that either tripped face detection on "
            "a pet's muzzle (face_count≥1 is suspicious for wildlife) "
            "OR have very small subject — pet shots gone wrong."
        ),
    },
    # V21.1 nice-to-have: also seed the under-target travel bad bucket
    # (currently 2 bad samples; want ≥10).
    ("travel", "bad"): {
        "query": (
            "scene in ('landscape', 'street', 'portrait') "
            "and decision == 'cull' "
            "and score_final < 0.5 "
            "and (highlight_clip_pct > 5 or shadow_clip_pct > 10)"
        ),
        "rationale": (
            "Travel-relevant culls with exposure faults — characteristic "
            "harsh-light or backlit travel fails."
        ),
    },
}


# Verticals that need attention right now (counts < target). Computed
# dynamically — this list is a doc-only hint of what's empty as of V21.1.
DEFAULT_TARGET_PER_BUCKET = 20


def _load_features(csv_paths: list[Path]) -> pd.DataFrame:
    """Concat all features.csv inputs into a single dataframe."""
    frames = []
    for p in csv_paths:
        if not p.exists():
            print(f"  SKIP missing: {p}", file=sys.stderr)
            continue
        df = pd.read_csv(p)
        df["__source_csv"] = str(p)
        frames.append(df)
    if not frames:
        raise SystemExit("ERROR: no features.csv inputs found")
    return pd.concat(frames, ignore_index=True)


def _load_src_paths(json_paths: list[Path]) -> dict[str, str]:
    """Read sister JSONs to recover {filename: src_path}.

    scan_multi.py writes both ``<basename>.json`` (slim, with src_path)
    and ``<basename>.features.csv`` (rich features, no src_path). The
    actual disk file lookup needs the join.
    """
    out: dict[str, str] = {}
    for p in json_paths:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for it in data.get("items", []):
            fn = it.get("filename")
            sp = it.get("src_path")
            if fn and sp:
                out[fn] = sp
    return out


def _route_one_bucket(
    vertical: str,
    bucket: str,
    rule: dict,
    feats: pd.DataFrame,
    src_paths: dict[str, str],
    current_count: int,
    target_count: int,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply one routing rule, return summary dict."""
    needed = max(0, target_count - current_count)
    if needed == 0:
        return {"vertical": vertical, "bucket": bucket,
                "needed": 0, "added": 0, "candidates": 0,
                "status": "already-at-target"}

    try:
        cands = feats.query(rule["query"])
    except Exception as exc:
        return {"vertical": vertical, "bucket": bucket,
                "needed": needed, "added": 0, "candidates": 0,
                "status": f"query-error: {exc}"}

    if len(cands) == 0:
        return {"vertical": vertical, "bucket": bucket,
                "needed": needed, "added": 0, "candidates": 0,
                "status": "no-candidates-in-pool"}

    # Sort: highest score_final first for "good" picks, lowest first
    # for "bad" picks — most representative ends of the distribution.
    if bucket == "good":
        cands = cands.sort_values("score_final", ascending=False)
    else:
        cands = cands.sort_values("score_final", ascending=True)
    cands = cands.head(needed)

    added = 0
    skipped_no_path = 0
    skipped_no_file = 0
    for _, row in cands.iterrows():
        fn = row["filename"]
        sp = src_paths.get(fn)
        if not sp:
            skipped_no_path += 1
            continue
        p = Path(sp)
        if not p.exists() or not p.is_file():
            skipped_no_file += 1
            continue
        if dry_run:
            added += 1
            continue
        try:
            content = p.read_bytes()
            vmod.save_sample(vertical, bucket, p.name, content)
            added += 1
        except Exception as exc:  # noqa: BLE001
            print(f"    save_sample failed for {fn}: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)

    return {
        "vertical":          vertical,
        "bucket":            bucket,
        "needed":            needed,
        "candidates":        len(cands),
        "added":             added,
        "skipped_no_path":   skipped_no_path,
        "skipped_no_file":   skipped_no_file,
        "status":            "done" if added > 0 else "no-files-found",
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("feature_csvs", nargs="+",
                    help="One or more <basename>.features.csv files "
                         "(typically /tmp/<scan_dir>/*.features.csv)")
    p.add_argument("--scan-jsons", nargs="*", default=None,
                    help="Sister JSON paths for src_path lookup. "
                         "Default: replace .features.csv with .json on "
                         "the inputs above.")
    p.add_argument("--max-per-bucket", type=int,
                    default=DEFAULT_TARGET_PER_BUCKET,
                    help=f"Target sample count per bucket "
                         f"(default {DEFAULT_TARGET_PER_BUCKET})")
    p.add_argument("--vertical",
                    help="Comma-separated subset of (vertical:bucket) "
                         "pairs to route. Default: all rules in "
                         "ROUTING_RULES whose target bucket is below "
                         "--max-per-bucket.")
    p.add_argument("--dry-run", action="store_true",
                    help="Print the routing plan without copying any files")
    args = p.parse_args()

    feature_paths = [Path(g) for arg in args.feature_csvs for g in glob.glob(arg)]
    if not feature_paths:
        # Direct paths (no glob expansion needed)
        feature_paths = [Path(arg) for arg in args.feature_csvs]
    json_paths: list[Path]
    if args.scan_jsons:
        json_paths = [Path(g) for arg in args.scan_jsons for g in glob.glob(arg)]
        if not json_paths:
            json_paths = [Path(arg) for arg in args.scan_jsons]
    else:
        json_paths = [p.with_suffix("").with_suffix(".json")
                      for p in feature_paths]

    feats = _load_features(feature_paths)
    print(f"loaded {len(feats)} feature rows from {len(feature_paths)} CSVs",
          file=sys.stderr)
    src_paths = _load_src_paths(json_paths)
    print(f"loaded {len(src_paths)} src_path entries from {len(json_paths)} "
          f"JSONs", file=sys.stderr)

    # Determine which rules to run.
    if args.vertical:
        wanted = set()
        for entry in args.vertical.split(","):
            entry = entry.strip()
            if ":" in entry:
                k, b = entry.split(":", 1)
                wanted.add((k.strip(), b.strip()))
            else:
                # Default to both buckets if just a vertical name
                wanted.add((entry, "good"))
                wanted.add((entry, "bad"))
        rules_to_run = {kv: r for kv, r in ROUTING_RULES.items() if kv in wanted}
    else:
        rules_to_run = ROUTING_RULES

    summaries = []
    for (vertical, bucket), rule in rules_to_run.items():
        counts = vmod.count_samples(vertical)
        current = counts.get(bucket, 0)
        print(f"\n[{vertical}/{bucket}] current={current} "
              f"target={args.max_per_bucket}", file=sys.stderr)
        if current >= args.max_per_bucket:
            print("  already at target, skipping.", file=sys.stderr)
            summaries.append({"vertical": vertical, "bucket": bucket,
                              "status": "skipped-at-target", "added": 0})
            continue
        print(f"  rule: {rule['query']}", file=sys.stderr)
        print(f"  rationale: {rule['rationale']}", file=sys.stderr)
        s = _route_one_bucket(
            vertical, bucket, rule, feats, src_paths,
            current_count=current, target_count=args.max_per_bucket,
            dry_run=args.dry_run,
        )
        print(f"  {s['status']}: added {s['added']} / "
              f"needed {s.get('needed', '-')} "
              f"(candidates pool: {s.get('candidates', '-')})",
              file=sys.stderr)
        summaries.append(s)

    print("\n=== summary ===", file=sys.stderr)
    total_added = 0
    for s in summaries:
        print(f"  {s['vertical']}/{s['bucket']:5s}: "
              f"added={s.get('added', 0)} status={s['status']}",
              file=sys.stderr)
        total_added += s.get("added", 0)
    print(f"\ntotal added: {total_added}{' (dry-run)' if args.dry_run else ''}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
