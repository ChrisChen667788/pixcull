"""Main pipeline: list files → analyze each → cluster → score → decide → export.

V0.1 runs sequentially (tqdm progress). V0.3 will add multi-process workers and
incremental runs via the cache layer.
"""

from collections import Counter
from pathlib import Path
from typing import Callable

import pandas as pd
from rich.console import Console
from tqdm import tqdm

from pixcull.config import PixCullConfig
from pixcull.detectors.duplicate import cluster_bursts, demote_mediocre_bursts
from pixcull.io.loader import list_images
from pixcull.pipeline.burst_peak import rank_burst_peaks
from pixcull.pipeline.face_clustering import cluster_faces_across_rows
from pixcull.pipeline.location_clustering import cluster_locations_across_rows
from pixcull.pipeline.parallel import parallel_analyze
from pixcull.pipeline.worker import analyze_one
from pixcull.scoring.decision import Decision, decide
from pixcull.scoring.fusion import fuse_score
from pixcull.scoring.rescorer import load_rescorer, score_row
from pixcull.scoring.rubric import RUBRIC_AXES
from pixcull.scoring.rubric_decompose import decompose_row
from pixcull.scoring.axis_rescorer import (
    load_axis_rescorers, score_row_per_axis,
)

console = Console()


def run_pipeline(
    folder: Path,
    output: Path,
    scene_override: str | None = None,
    strictness: str = "standard",
    rescorer_mode: str | None = None,
    rescorer_path: str | None = None,
    progress_cb: Callable[[int, int, str], None] | None = None,
    vlm_mode: str = "off",
    meta_mode: str = "off",
    vertical: str | None = None,
) -> Path:
    """Run the full culling pipeline on `folder` and write `scores.csv`.

    V1.2 additions:
        rescorer_mode: if provided, overrides ``config.rescorer.mode``.
            Values: "off" | "shadow" | "adjudicate". See RescorerConfig
            docstring for semantics.
        rescorer_path: if provided, overrides ``config.rescorer.model_path``.

    Web-demo addition (not a versioned feature; just plumbing):
        progress_cb: optional callback ``(done, total, message)`` invoked
            once per image during the analyze loop and again at each major
            phase boundary (cluster / score / export). Used by
            ``scripts/serve_demo.py`` to drive a browser progress bar. No-op
            when None — CLI users see only the tqdm bar as before.
    """
    output.mkdir(parents=True, exist_ok=True)
    config = PixCullConfig.load()
    if rescorer_mode is not None:
        config.rescorer.mode = rescorer_mode
    if rescorer_path is not None:
        config.rescorer.model_path = rescorer_path

    paths = list_images(folder)
    console.print(f"[cyan]Found {len(paths)} images under {folder}[/]")
    total = len(paths)
    if progress_cb is not None:
        progress_cb(0, total, f"找到 {total} 张图,开始分析…")

    # V21 — multiprocess analyze. ``parallel_analyze`` falls back to a
    # serial loop when workers == 1 or paths <= 2, so smoke tests and
    # tiny batches don't pay the forkserver startup cost. Defaults to
    # min(4, cpu-1); override with PIXCULL_WORKERS env var. On a 10-core
    # M1 Max this brings a 1000-image batch from ~33 min serial to
    # ~8 min with 4 workers.
    records = parallel_analyze(
        paths, progress_cb=progress_cb, desc="分析中",
    )
    # Tqdm progress in CLI mode (parallel_analyze prints its own
    # one-line summary on completion; tqdm is purely for the bar UX
    # in the serial code path. We leave a single-line completion
    # message here so CLI users still get a "done" signal.)
    if total > 0:
        console.print(f"[cyan]Analyzed {len(records)}/{total} images[/]")
    # Apply scene_override after the parallel pass — single-process
    # mutation, no race.
    if scene_override:
        for r in records:
            r["scene"] = scene_override

    # V22.0 — face clustering across the batch. Each row carries
    # ``face_embeddings`` from the worker; we DBSCAN them in the main
    # process and write back ``face_clusters`` (list of int cluster IDs
    # per face). Drops the raw embeddings after to keep scores.csv lean.
    # No-op when no row has any face — DBSCAN is skipped, all rows
    # get ``face_clusters = []``.
    if progress_cb is not None:
        progress_cb(total, total, "跨照片人脸聚类…")
    records = cluster_faces_across_rows(records, drop_embeddings=True)

    # V23 — GPS clustering for the travel-persona "one per location"
    # picker. haversine DBSCAN with radius=100m. Photos without EXIF
    # GPS get ``gps_cluster_id=None`` (UI shows them under "未知位置").
    if progress_cb is not None:
        progress_cb(total, total, "按 GPS 地点聚类…")
    records = cluster_locations_across_rows(records)

    df = pd.DataFrame(records)
    if df.empty:
        console.print("[red]No analyzable images.[/]")
        if progress_cb is not None:
            progress_cb(total, total, "没有可分析的图片")
        return output

    if progress_cb is not None:
        progress_cb(total, total, "聚类与连拍检测…")
    df = cluster_bursts(df)

    # V1.2: optionally load the learned rescorer once per run. Failures are
    # logged to stderr inside load_rescorer(); we treat a None result as
    # "fall back to rule-only" and report that in the run summary below.
    rescorer_art = None
    if config.rescorer.mode in ("shadow", "adjudicate"):
        rescorer_art = load_rescorer(config.rescorer.model_path)
        if rescorer_art is not None:
            console.print(
                f"[cyan]Rescorer[/] mode=[bold]{config.rescorer.mode}[/] "
                f"model={rescorer_art.model_name} "
                f"trained_on={rescorer_art.train_rows} rows "
                f"({rescorer_art.source_path})"
            )
        else:
            console.print(
                f"[yellow]Rescorer[/] mode={config.rescorer.mode} requested "
                f"but model unavailable — running rule-only"
            )

    # V2.1: optionally load per-axis rescorers. Independent of the
    # binary rescorer above — these run whenever the joblibs exist
    # (no config flag), since adding signal is always safe and the
    # results are display-only at this stage. ``axis_models`` is an
    # empty dict when nothing's trained, which makes the per-row loop
    # below a clean no-op.
    axis_model_dir = Path(config.rescorer.model_path).parent if config.rescorer.model_path else Path("models")
    axis_models = load_axis_rescorers(axis_model_dir)
    if axis_models:
        console.print(
            f"[cyan]Axis rescorers[/] loaded: "
            f"{', '.join(sorted(axis_models.keys()))} "
            f"({len(axis_models)}/{len(RUBRIC_AXES)} axes)"
        )

    if progress_cb is not None:
        progress_cb(total, total, "评分与决策…")
    decisions, dim_scores, reasons_all = [], [], []
    rescorer_preds: list[str | None] = []
    rescorer_probs: list[float | None] = []
    for _, row in df.iterrows():
        row_dict = row.to_dict()
        dims = fuse_score(row_dict, row["flags"], row["scene"], config)

        # Score the rescorer *before* decide() so adjudicate mode can consume
        # its output. We pass dims' fusion scores back into row_dict since the
        # rescorer was trained on the post-fusion feature set.
        r_pred: str | None = None
        r_prob: float | None = None
        if rescorer_art is not None:
            row_with_scores = {
                **row_dict,
                "score_final": dims["final"],
                "score_sharpness": dims["sharpness"],
                "score_composition": dims["composition"],
                "score_exposure": dims["exposure"],
                "score_aesthetic": dims["aesthetic"],
            }
            r_out = score_row(rescorer_art, row_with_scores)
            if r_out is not None:
                r_pred = r_out["pred"]
                r_prob = r_out["prob_keep"]

        dec, reasons = decide(
            dims["final"],
            row["flags"],
            config,
            strictness,  # type: ignore[arg-type]
            scene=row["scene"],
            rescorer_prob_keep=r_prob,
            vertical=vertical,           # V17.2 — per-batch override
        )

        # Rescorer's keep/maybe verdict is meaningless for rule-CULL rows
        # (the classifier wasn't trained on cull labels). Suppress to keep
        # the CSV schema honest and the review viewer's "≠ rule" filter clean.
        if dec is Decision.CULL:
            r_pred, r_prob = None, None

        decisions.append(dec.value)
        dim_scores.append(dims)
        reasons_all.append("; ".join(reasons))
        rescorer_preds.append(r_pred)
        rescorer_probs.append(r_prob)

    # Cluster-level post-process: stilllife product shoots where the whole take
    # scores mediocre get demoted to cull even though individual frames clear
    # the per-image keep threshold. See demote_mediocre_bursts docstring.
    decisions, reasons_all = demote_mediocre_bursts(df, decisions, reasons_all)

    df["decision"] = decisions
    df["reason"] = reasons_all
    df["score_final"] = [d["final"] for d in dim_scores]
    for dim in ("sharpness", "composition", "exposure", "aesthetic", "moment"):
        df[f"score_{dim}"] = [d[dim] for d in dim_scores]

    # V27 — rank action peaks within each burst cluster. Needs
    # score_final + score_sharpness + face_max_blink + face_min_ear,
    # all of which exist on df at this point. Adds ``peak_rank`` and
    # ``is_burst_peak`` columns. No-op when all clusters are size 1
    # (no recurring frames → nothing to rank against).
    if progress_cb is not None:
        progress_cb(total, total, "连拍峰值排名…")
    df = rank_burst_peaks(df)

    # V1.2: rescorer columns — always emitted when mode != off so downstream
    # tooling (scripts/pick_next_to_label.py, the review viewer, future
    # analyses) can read them without an extra join. All None when mode=off.
    if rescorer_art is not None:
        # If demote_mediocre_bursts promoted a non-cull row to cull at the
        # cluster level, null out the rescorer prediction there too (same
        # invariant as above, just at a later stage).
        for i, d in enumerate(decisions):
            if d == Decision.CULL.value:
                rescorer_preds[i] = None
                rescorer_probs[i] = None
        df["rescorer_pred"] = rescorer_preds
        df["rescorer_prob_keep"] = rescorer_probs

    # V2.0 rubric pass: auto-decompose every row into 6-axis stars +
    # rationale BEFORE we drop the rich row dict for CSV export. The
    # rubric file is a sibling JSONL so the demo UI can render
    # per-image stars without re-deriving them from CSV columns each
    # request, and the human-annotation flow can append new lines as
    # the user grades images. See pixcull.scoring.rubric for design.
    if progress_cb is not None:
        progress_cb(total, total, "rubric 多维评分…")
    import json as _json
    rubric_scores: list = []
    for _, row in df.iterrows():
        rubric_scores.append(decompose_row(row.to_dict()))
    rubric_path = output / "rubric.jsonl"
    with open(rubric_path, "w", encoding="utf-8") as f:
        for rs in rubric_scores:
            f.write(_json.dumps(rs.to_dict(), ensure_ascii=False) + "\n")
    # Mirror the per-axis stars onto df so they end up in scores.csv
    # as ``rubric_<axis>_stars`` columns. Keeps every consumer
    # (training script, future eval script, the review viewer)
    # working without parsing the JSONL.
    for axis in RUBRIC_AXES:
        df[f"rubric_{axis.name}_stars"] = [
            rs.axes[axis.name].stars for rs in rubric_scores
        ]
        df[f"rubric_{axis.name}_pass"] = [
            rs.axes[axis.name].checklist_pass for rs in rubric_scores
        ]

    # V2.1: per-axis model predictions (`model_<axis>_stars`). Display-only
    # for now — UI shows them next to the auto-decomposed stars so the
    # photographer can compare. Falls through silently when no models
    # are trained.
    if axis_models:
        for axis in RUBRIC_AXES:
            df[f"model_{axis.name}_stars"] = None
        for i, (_, row) in enumerate(df.iterrows()):
            preds = score_row_per_axis(axis_models, row.to_dict())
            for axis_name, stars in preds.items():
                df.at[df.index[i], f"model_{axis_name}_stars"] = stars

    # V3.0: VLM-as-judge. Optional fourth opinion from a vision-language
    # model — slower (~3-10s/image) so opt-in via vlm_mode="local".
    # Persists per-axis stars + a per-image rationale to the CSV and
    # vlm_verdicts.jsonl. Skips rule-CULL rows to save time (a CULL is
    # already a CULL — VLM disagreement on culls isn't actionable).
    # Cache VLM verdicts per filename so the meta-judge stage can read
    # them without re-querying. None = no VLM ran for that row.
    vlm_verdicts_by_fn: dict[str, "object"] = {}
    if vlm_mode and vlm_mode != "off":
        if progress_cb is not None:
            progress_cb(total, total, f"VLM ({vlm_mode}) 评分中…")
        from pixcull.scoring.vlm_judge import load_judge
        judge = load_judge(vlm_mode)
        if judge is not None:
            for axis in RUBRIC_AXES:
                df[f"vlm_{axis.name}_stars"] = None
            df["vlm_overall_label"] = None
            df["vlm_overall_rationale"] = ""
            df["vlm_elapsed_s"] = None
            verdicts_path = output / "vlm_verdicts.jsonl"
            with open(verdicts_path, "w", encoding="utf-8") as vf:
                for i, (_, row) in enumerate(df.iterrows()):
                    if str(row.get("decision", "")) == "cull":
                        # Skip culls — saves ~30% time on rough batches
                        continue
                    img_path = Path(row["path"])
                    if progress_cb is not None:
                        progress_cb(i + 1, total,
                                    f"VLM {i+1}/{total}: {img_path.name}")
                    # V8.0: detect style modes from rule outputs, build a
                    # style-aware prompt section, pass to the VLM so it
                    # grades a B&W / low-key / long-exposure photo
                    # against THAT style's canon, not the generic one.
                    from pixcull.scoring.style_modes import (
                        detect_style_modes, render_style_section_zh,
                    )
                    style_profile = detect_style_modes(row.to_dict())
                    style_section = render_style_section_zh(style_profile)
                    verdict = judge.score(
                        img_path,
                        scene=str(row.get("scene") or ""),
                        style_section=style_section,
                    )
                    vf.write(_json.dumps(verdict.to_dict(),
                                         ensure_ascii=False) + "\n")
                    vlm_verdicts_by_fn[img_path.name] = verdict
                    if verdict.error:
                        continue
                    for axis_name, ax in verdict.axes.items():
                        if ax.stars is not None:
                            df.at[df.index[i],
                                  f"vlm_{axis_name}_stars"] = ax.stars
                    df.at[df.index[i], "vlm_overall_label"] = verdict.overall_label
                    df.at[df.index[i], "vlm_overall_rationale"] = verdict.overall_rationale
                    df.at[df.index[i], "vlm_elapsed_s"] = verdict.elapsed_s
            console.print(
                f"[cyan]VLM[/] {judge.model_name} scored "
                f"{(df['vlm_elapsed_s'].notna()).sum()} non-cull images"
            )

    # V3.1: Meta-judge stage. DeepSeek V4 (text-only) reads ALL the
    # signals — rule scores, V2.1 model stars, VLM verdict, detector
    # metrics, flags — and produces a calibrated final verdict +
    # explicit inconsistency report. Catches VLM over-confidence
    # (e.g. 5★ subject when no_clear_subject flag is set).
    if meta_mode and meta_mode != "off":
        if progress_cb is not None:
            progress_cb(total, total, f"Meta judge ({meta_mode}) 并发综合中…")
        from pixcull.scoring.meta_judge import load_meta_judge, build_packet
        mjudge = load_meta_judge(meta_mode)
        if mjudge is not None:
            for axis in RUBRIC_AXES:
                df[f"meta_{axis.name}_stars"] = None
            df["meta_overall_label"] = None
            df["meta_overall_rationale"] = ""
            df["meta_confidence"] = None
            df["meta_inconsistencies"] = ""
            df["meta_elapsed_s"] = None
            meta_path = output / "meta_verdicts.jsonl"

            # V11.0 — concurrent meta-judge calls.
            # Each call is a network round-trip to DeepSeek (~5-15s
            # blocked on I/O). With 8 concurrent workers a 50-image
            # batch goes from 50 × 10s = 500s down to ~80s.
            # DeepSeek allows generous concurrency on V4-Flash; use
            # ThreadPoolExecutor (the OpenAI client is thread-safe).
            from concurrent.futures import ThreadPoolExecutor, as_completed

            # Pre-build packets and indices for all non-cull rows
            tasks: list[tuple[int, str, dict]] = []  # (df_idx, fn, packet)
            for i, (_, row) in enumerate(df.iterrows()):
                if str(row.get("decision", "")) == "cull":
                    continue
                fn = str(row.get("filename", ""))
                packet = build_packet(row.to_dict(),
                                      vlm_verdicts_by_fn.get(fn))
                tasks.append((i, fn, packet))

            n_meta_done = 0
            n_meta_total = len(tasks)
            mf = open(meta_path, "w", encoding="utf-8")
            try:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    future_to_task = {
                        pool.submit(mjudge.consolidate, pkt): (i, fn)
                        for (i, fn, pkt) in tasks
                    }
                    for fut in as_completed(future_to_task):
                        i, fn = future_to_task[fut]
                        try:
                            mv = fut.result()
                        except Exception as exc:  # noqa: BLE001
                            console.print(f"[yellow]meta error[/] {fn}: {exc}")
                            continue
                        n_meta_done += 1
                        if progress_cb is not None:
                            progress_cb(n_meta_done, n_meta_total,
                                        f"Meta {n_meta_done}/{n_meta_total}: {fn}")
                        mf.write(_json.dumps(mv.to_dict(),
                                             ensure_ascii=False) + "\n")
                        if mv.error:
                            continue
                        for axis_name, ax in mv.axes.items():
                            if ax.stars is not None:
                                df.at[df.index[i],
                                      f"meta_{axis_name}_stars"] = ax.stars
                        df.at[df.index[i], "meta_overall_label"] = mv.overall_label
                        df.at[df.index[i], "meta_overall_rationale"] = mv.overall_rationale
                        df.at[df.index[i], "meta_confidence"] = mv.confidence
                        df.at[df.index[i], "meta_inconsistencies"] = (
                            " | ".join(mv.inconsistencies or [])[:500]
                        )
                        df.at[df.index[i], "meta_elapsed_s"] = mv.elapsed_s
            finally:
                mf.close()
            console.print(
                f"[cyan]Meta-judge[/] {mjudge.model_name} consolidated "
                f"{n_meta_done} non-cull rows (concurrent x8)"
            )

    # Export CSV (drop embedding to keep file small)
    df_export = df.drop(columns=["embedding"]).copy()
    df_export["scene_probs"] = df_export["scene_probs"].apply(str)
    df_export["flags"] = df_export["flags"].apply(lambda x: ",".join(x) if x else "")
    csv_path = output / "scores.csv"
    df_export.to_csv(csv_path, index=False)

    counts = Counter(decisions)
    console.print(
        f"[green]✓ Done. "
        f"Keep=[bold]{counts.get('keep', 0)}[/] "
        f"Maybe=[bold]{counts.get('maybe', 0)}[/] "
        f"Cull=[bold]{counts.get('cull', 0)}[/][/]"
    )
    console.print(f"[cyan]CSV:[/] {csv_path}")
    if progress_cb is not None:
        progress_cb(total, total, "完成")
    return output
