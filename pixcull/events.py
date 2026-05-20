"""INFRA-3 — multi-shooter event merge (MVP).

Combines two or more PixCull runs into a single merged "event" run
that the existing /results UI can render as one batch. Each source
run keeps its identity (the merged scores.csv adds a ``source_run``
column) so the UI can show "by: alice" / "by: bob" badges.

What this module does today:

  * concatenates source runs' scores.csv files into a new run
  * renames cluster_id to ``{source_run}:{cluster_id}`` so the
    burst-clustering passes from different shooters don't collide
  * builds a manifest.json that points each merged filename back to
    its original on-disk path, so the existing _resolve_image_source
    can serve thumbnails without copying anything
  * emits a small ``event_meta.json`` describing the source runs +
    timestamp

What it explicitly does NOT do (deferred to v0.2 — see
docs/INFRA-3-multi-shooter-merge.md):

  * cross-camera face cluster reconciliation
  * time-aligned "moments" detection
  * smart "best per moment" picker
  * UI for resolving face_label conflicts between shooters
"""
from __future__ import annotations

import csv
import json
import secrets
import time
from pathlib import Path

DEMO_ROOT = Path("/tmp/pixcull_demo")


def _new_merged_id() -> str:
    return f"event_{secrets.token_hex(5)}"


def merge_runs(source_run_ids: list[str],
                name: str | None = None,
                demo_root: Path | None = None) -> str:
    """Concatenate the source runs' scores.csv into a new merged run.

    Returns the new run_id. Caller is responsible for any subsequent
    re-clustering or face reconciliation passes.

    The merged scores.csv:
      * contains every column from every source (union of headers)
      * adds ``source_run`` column carrying the originating run_id
      * rewrites ``cluster_id`` to ``{source_run}:{cluster_id}``
        so cluster-burst grouping stays meaningful per-shooter
        without colliding numerically

    Raises FileNotFoundError if any source run lacks scores.csv.
    """
    root = demo_root or DEMO_ROOT
    if len(source_run_ids) < 2:
        raise ValueError("need at least 2 source runs to merge")

    # Verify each source has a scores.csv
    source_paths: dict[str, Path] = {}
    for rid in source_run_ids:
        csv_path = root / rid / "output" / "scores.csv"
        if not csv_path.is_file():
            raise FileNotFoundError(f"no scores.csv for run {rid}")
        source_paths[rid] = csv_path

    # Build the merged run directory
    merged_id = _new_merged_id()
    merged_dir = root / merged_id / "output"
    merged_dir.mkdir(parents=True, exist_ok=True)
    merged_csv = merged_dir / "scores.csv"
    merged_manifest: dict[str, str] = {}

    # Two-pass: first pass collects the union of headers; second
    # writes rows. Lets us tolerate schema drift between source runs
    # (older runs may lack newer columns like ``peak_rank``).
    all_headers: list[str] = []
    seen_headers: set[str] = set()
    for rid, csv_path in source_paths.items():
        with open(csv_path, encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for h in (rdr.fieldnames or []):
                if h not in seen_headers:
                    all_headers.append(h)
                    seen_headers.add(h)
    if "source_run" not in seen_headers:
        all_headers.append("source_run")

    # Second pass: write the merged CSV + build manifest. We resolve
    # each row's absolute on-disk source path from the SOURCE run's
    # output/manifest.json if it exists, otherwise from the row's
    # ``path`` column (scan-mode runs ship it directly).
    with open(merged_csv, "w", encoding="utf-8", newline="") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=all_headers)
        writer.writeheader()
        for rid, csv_path in source_paths.items():
            # Load source manifest if it exists
            src_manifest_path = csv_path.parent / "manifest.json"
            src_manifest: dict[str, str] = {}
            if src_manifest_path.is_file():
                try:
                    src_manifest = json.loads(
                        src_manifest_path.read_text("utf-8"))
                except (OSError, json.JSONDecodeError):
                    src_manifest = {}

            with open(csv_path, encoding="utf-8") as f:
                rdr = csv.DictReader(f)
                for row in rdr:
                    fn = (row.get("filename") or "").strip()
                    if not fn:
                        continue
                    # Disambiguate filenames if two shooters happened
                    # to give the same basename (rare but possible
                    # with default camera-serial sequences).
                    merged_fn = (
                        fn if fn not in merged_manifest
                        else f"{rid}__{fn}"
                    )
                    row["filename"] = merged_fn
                    row["source_run"] = rid
                    # Prefix the cluster_id so source runs' burst
                    # clusters stay distinct in the merged view.
                    cid = (row.get("cluster_id") or "").strip()
                    if cid and cid not in ("", "nan", "None"):
                        row["cluster_id"] = f"{rid}:{cid}"
                    writer.writerow(row)

                    # Resolve absolute path for the manifest.
                    src_path = (
                        src_manifest.get(fn)
                        or row.get("path")
                        or ""
                    ).strip()
                    if src_path:
                        merged_manifest[merged_fn] = src_path

    # Emit the merged manifest.json so _resolve_image_source can
    # serve thumbnails without copying any photos.
    if merged_manifest:
        with open(merged_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(merged_manifest, f, ensure_ascii=False, indent=2)

    # Sidecar metadata so the UI can show "merged from N runs by M
    # users on YYYY-MM-DD".
    meta = {
        "schema":       "pixcull.event_merge.v1",
        "merged_id":    merged_id,
        "source_runs":  source_run_ids,
        "name":         name or "merged event",
        "created_at":   time.time(),
    }
    with open(merged_dir.parent / "event_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return merged_id
