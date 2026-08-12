"""Main pipeline: list files → analyze each → cluster → score → decide → export.

V0.1 runs sequentially (tqdm progress). V0.3 will add multi-process workers and
incremental runs via the cache layer.
"""

import os
from collections import Counter
from pathlib import Path
from typing import Callable

import pandas as pd
from rich.console import Console
from tqdm import tqdm

from pixcull.config import PixCullConfig
from pixcull.detectors.duplicate import cluster_bursts, demote_mediocre_bursts
from pixcull.io.loader import list_images
from pixcull.pipeline.burst_peak import (
    annotate_burst_peak_reasons,
    rank_burst_peaks,
)
from pixcull.pipeline.face_clustering import cluster_faces_across_rows
from pixcull.pipeline.location_clustering import cluster_locations_across_rows
from pixcull.pipeline.parallel import parallel_analyze
from pixcull.pipeline.worker import analyze_one
from pixcull.scoring.decision import Decision, decide
from pixcull.scoring.fusion import fuse_score
from pixcull.scoring.rescorer import load_rescorer, score_row
from pixcull.scoring.rubric import RUBRIC_AXES
from pixcull.scoring.rubric_decompose import decompose_row


def _reapply_decisions_with_vlm(df, verdicts_by_fn: dict,
                                decide_args: list[dict], config, *,
                                strictness: str, vertical, personal_shift,
                                authority: str) -> int:
    """Re-run ``decide`` now that the judge has actually seen the photos.

    The ordering here is forced, not chosen: the VLM stage needs
    ``decision`` to know which rows to skip, so it must run after the
    first decision pass — which is exactly why, before v2.48, a verdict
    could never change anything.  Recomputing is cheaper and far less
    fragile than trying to interleave the two.

    Returns how many decisions actually moved.
    """
    if authority == "off" or not verdicts_by_fn:
        return 0
    changed = 0
    for i, args in enumerate(decide_args):
        if i >= len(df.index):
            break
        fn = str(df.at[df.index[i], "filename"])
        verdict = verdicts_by_fn.get(fn)
        if verdict is None or getattr(verdict, "error", None):
            # No usable verdict — the API was down, the row was skipped,
            # the JSON was malformed. Leave the rule's decision standing.
            # A cloud outage must degrade to a usable cull, not to chaos.
            continue
        axes = {name: ax.stars
                for name, ax in (getattr(verdict, "axes", {}) or {}).items()}
        dec, reasons = decide(
            args["final"], args["flags"], config, strictness,  # type: ignore[arg-type]
            scene=args["scene"], rescorer_prob_keep=args["r_prob"],
            vertical=vertical, personal_shift=personal_shift,
            vlm_label=getattr(verdict, "overall_label", None),
            vlm_axes=axes, vlm_authority=authority,
        )
        before = str(df.at[df.index[i], "decision"])
        if dec.value != before:
            changed += 1
        df.at[df.index[i], "decision"] = dec.value
        df.at[df.index[i], "reasons"] = "; ".join(reasons)
    if authority == "primary":
        console.print(
            f"[cyan]VLM authority[/] primary — {changed} decision(s) "
            f"changed by the judge")
    else:
        console.print(
            f"[dim]VLM authority: shadow — recorded only, "
            f"{changed} decision(s) would have changed[/dim]")
    return changed


def run_vlm_stage(df, judge, output: Path, *, progress_cb=None,
                  score_culls: bool = False) -> dict:
    """Score every non-cull row with ``judge``; return verdicts by filename.

    Extracted from ``run_pipeline`` in v2.48-P2 so the concurrency has
    somewhere to be tested.  Nothing covered this stage before — the only
    two tests that touch ``run_pipeline`` never enable a VLM — which is
    the "advertised but unreachable" shape this repo keeps rediscovering.

    Writes ``vlm_verdicts.jsonl`` into ``output`` and annotates ``df``
    in place with ``vlm_<axis>_stars`` / ``vlm_overall_*`` /
    ``vlm_elapsed_s``.
    """
    import json as _json
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from pixcull.scoring.style_modes import (
        detect_style_modes, render_style_section_zh,
    )

    verdicts_by_fn: dict = {}
    for axis in RUBRIC_AXES:
        df[f"vlm_{axis.name}_stars"] = None
    df["vlm_overall_label"] = None
    df["vlm_overall_rationale"] = ""
    df["vlm_elapsed_s"] = None

    # V8.0: detect style modes from rule outputs and build a style-aware
    # prompt section, so a B&W / low-key / long-exposure frame is graded
    # against THAT style's canon rather than the generic one.  Done up
    # front on this thread: it is pure CPU over a dict, and it keeps the
    # workers doing nothing but I/O.
    tasks: list[tuple[int, Path, dict]] = []
    for i, (_, row) in enumerate(df.iterrows()):
        if not score_culls and str(row.get("decision", "")) == "cull":
            # Skip culls — saves ~30% of the calls on rough batches.
            # Sound for a *second* opinion (a cull is already a cull) and
            # nonsense for a first one, so v2.48-P1's primary mode passes
            # score_culls=True: those are the frames the rule stack most
            # often gets wrong.
            continue
        row_d = row.to_dict()
        tasks.append((i, Path(row["path"]), {
            "scene": str(row.get("scene") or ""),
            "style_section": render_style_section_zh(detect_style_modes(row_d)),
            "row": row_d,
        }))

    def _score_one(img_path: Path, kw: dict):
        # `row` carries the local detector readings the judge folds into
        # its prompt as evidence (v2.48-P0).  Backends that predate it
        # do not accept the kwarg.
        try:
            return judge.score(img_path, **kw)
        except TypeError:
            return judge.score(img_path,
                               **{k: v for k, v in kw.items() if k != "row"})

    # v2.48-P2 — concurrency.
    #
    # This was serial: one blocking round-trip per photo.  For a local
    # MLX model that is correct — the GPU is already saturated by one
    # request and threads only add contention — but a cloud judge is pure
    # network I/O, and serial is then the dominant cost of a run: ~2100
    # non-cull photos at ~3 s/call is 105 minutes, long enough that the
    # run *will* be interrupted.
    #
    # The load-bearing detail, copied from the meta-judge stage: results
    # are applied to the DataFrame inside the `as_completed` loop, which
    # runs on ONE thread.  Calling df.at[] from the workers would race,
    # and pandas would not raise — it would silently lose verdicts.
    workers = _vlm_workers(judge)
    n_done = 0
    n_total = len(tasks)
    with open(Path(output) / "vlm_verdicts.jsonl", "w",
              encoding="utf-8") as vf:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fut_to_task = {pool.submit(_score_one, p, kw): (i, p)
                           for (i, p, kw) in tasks}
            for fut in as_completed(fut_to_task):
                i, img_path = fut_to_task[fut]
                try:
                    verdict = fut.result()
                except Exception as exc:  # noqa: BLE001
                    console.print(
                        f"[yellow]VLM error[/] {img_path.name}: {exc}")
                    continue
                n_done += 1
                if progress_cb is not None:
                    progress_cb(n_done, n_total,
                                f"VLM {n_done}/{n_total}: {img_path.name}")
                vf.write(_json.dumps(verdict.to_dict(),
                                     ensure_ascii=False) + "\n")
                verdicts_by_fn[img_path.name] = verdict
                if verdict.error:
                    continue
                for axis_name, ax in verdict.axes.items():
                    if ax.stars is not None:
                        df.at[df.index[i], f"vlm_{axis_name}_stars"] = ax.stars
                df.at[df.index[i], "vlm_overall_label"] = verdict.overall_label
                df.at[df.index[i], "vlm_overall_rationale"] = verdict.overall_rationale
                df.at[df.index[i], "vlm_elapsed_s"] = verdict.elapsed_s

    n_err = sum(1 for v in verdicts_by_fn.values()
                if getattr(v, "error", None))
    console.print(
        f"[cyan]VLM[/] {getattr(judge, 'model_name', '?')} scored "
        f"{int(df['vlm_elapsed_s'].notna().sum())} non-cull images "
        f"(concurrent x{workers})"
        + (f" [yellow]— {n_err} errored[/]" if n_err else ""))
    if n_total and n_err == n_total:
        # Every call failed.  That is not a rough batch, it is a broken
        # configuration — stale endpoint, expired key, wrong model
        # string — and the CSV it produces is indistinguishable from a
        # good run with a shy model.  This is the exact failure the
        # `m3 doctor` command exists for, so name it.
        console.print(
            "[red]VLM: every call failed[/] — this is a configuration "
            "problem, not a hard batch. Run `pixcull m3 doctor`. First "
            f"error: {next(iter(verdicts_by_fn.values())).error}")
    return verdicts_by_fn


def _vlm_workers(judge) -> int:
    """How many VLM calls to have in flight.

    The right answer depends entirely on where the model runs, and
    getting it backwards is a real regression rather than a missed
    optimisation:

    * **Local (MLX / ONNX)** — the GPU is the bottleneck and it is
      already saturated by one request. Threads add contention and
      memory pressure and make it *slower*, so: 1. This is why the loop
      was serial before v2.48 and why concurrency could not simply be
      switched on for everybody.
    * **Cloud (M3 and friends)** — pure network I/O. Wall-clock is
      round-trip latency divided by workers, until the provider's rate
      limit binds. The judge does its own 200 RPM limiting, so workers
      only need to be enough to keep that window full: at ~3 s/call,
      8 workers sustain ~160 rpm and 12 saturate it.

    ``PIXCULL_VLM_WORKERS`` overrides, mostly so a slow uplink can be
    tuned down without a code change.
    """
    raw = os.environ.get("PIXCULL_VLM_WORKERS", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    # `model_name` is "<provider>:<model>" for API backends and a bare
    # repo id for local ones — the only signal available without the
    # judge classes knowing about each other.
    name = str(getattr(judge, "model_name", ""))
    is_cloud = any(name.startswith(p + ":")
                   for p in ("minimax", "deepseek", "openai", "custom"))
    return 8 if is_cloud else 1
from pixcull.scoring.axis_rescorer import (
    load_axis_rescorers, score_row_per_axis,
)

console = Console()


def _write_clip_cache(df: pd.DataFrame, output: Path) -> int:
    """Write ``output/embeddings.npz`` from the run's CLIP vectors.

    Best-effort by design: this is a free by-product, so a failure here
    must never fail a cull that otherwise succeeded — the worst case is
    that semantic search re-encodes later, exactly as it did before.

    Returns how many vectors were written (0 = nothing to write).
    """
    if "clip_embedding" not in df.columns:
        return 0
    try:
        import numpy as np

        names, vecs = [], []
        for fn, emb in zip(df["filename"], df["clip_embedding"], strict=True):
            # A photo whose scene detector errored out has no vector; a
            # row must be dropped rather than zero-filled, or it would
            # rank as equally-unlike-everything in every future query.
            if emb is None or not hasattr(emb, "shape"):
                continue
            arr = np.asarray(emb, dtype=np.float32).reshape(-1)
            if arr.size == 0 or not np.isfinite(arr).all():
                continue
            names.append(str(fn))
            vecs.append(arr)
        if not vecs:
            return 0
        if len({v.shape[0] for v in vecs}) != 1:
            console.print("[yellow]CLIP cache skipped: ragged vector dims[/]")
            return 0

        arr = np.stack(vecs, axis=0)
        n = np.linalg.norm(arr, axis=1, keepdims=True)
        arr = arr / np.where(n == 0, 1.0, n)

        cache_path = output / "embeddings.npz"
        # NB: np.savez APPENDS ".npz" to a target not already ending in
        # it, so a ".npz.tmp" temp would land at ".npz.tmp.npz" and the
        # rename would FileNotFound. Write through a handle — the same
        # trap semantic_search.py and library_index.py both document.
        tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
        output.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as fh:
            np.savez(fh, filenames=np.array(names), vectors=arr,
                     model=np.array("clip-vit-base-patch32"))
        tmp.rename(cache_path)
        console.print(f"[cyan]CLIP cache:[/] {len(names)} vectors "
                      f"→ {cache_path.name} [dim](semantic search + "
                      f"library index reuse this)[/dim]")
        return len(names)
    except Exception as exc:  # noqa: BLE001 — never fail the run for this
        console.print(f"[yellow]CLIP cache skipped: {exc}[/]")
        return 0


def _auto_index_library(output: Path) -> None:
    """File this run into the cross-run library index (``/library``).

    v2.34 — closes the gap v2.32 left: the library only ever had content
    if the user happened to know to run ``pixcull library index``, so
    ``/library`` looked broken on a fresh install.  Now that the CLIP
    vectors are a free by-product of culling (see ``_write_clip_cache``),
    filing them is a copy measured in milliseconds.

    ON by default because searching *everything* is the entire point of
    the page, and the index is local-only — ``~/.pixcull/library/``,
    never synced, never in the repo.  It does record real absolute
    paths, which is exactly why it stays on this machine.  Opt out with
    ``PIXCULL_NO_AUTO_INDEX=1``.

    Best-effort like the cache: a cull that succeeded must not report
    failure because a bonus index write didn't land.
    """
    if os.environ.get("PIXCULL_NO_AUTO_INDEX", "").strip().lower() in (
            "1", "true", "yes", "on"):
        return
    try:
        from pixcull.scoring import library_index as LX
        from pixcull.scoring.semantic_search import load_embeddings_cache

        cache = load_embeddings_cache(output / "embeddings.npz")
        if cache is None or cache["vectors"].shape[0] == 0:
            return

        # run_id must match what `pixcull library index` derives when it
        # walks the runs directory, or the same shoot would land twice
        # under two names: <root>/<run_id>/output for the demo-server
        # layout, else the output dir's own name.
        run_id = (output.parent.name if output.name == "output"
                  else output.name)

        from pixcull.cli import _run_path_map
        path_map = _run_path_map(output)
        entries, rows = [], []
        for i, fn in enumerate(str(x) for x in cache["filenames"]):
            p = path_map.get(fn)
            if p is None:
                continue
            try:
                entries.append((fn, str(p), p.stat().st_mtime))
            except OSError:
                continue
            rows.append(i)
        if not entries:
            return

        # library_dir passed EXPLICITLY, not left to append_run's default:
        # that default was bound to LIBRARY_DIR at import, so it ignores
        # any later reassignment of the module attribute — which silently
        # sent a test's writes into the real ~/.pixcull/library.
        res = LX.append_run(run_id, entries, cache["vectors"][rows],
                            library_dir=LX.LIBRARY_DIR,
                            model=cache.get("model", ""))
        if res["added"]:
            console.print(
                f"[cyan]Library:[/] +{res['added']} photos indexed as "
                f"'{run_id}' [dim](search every shoot at /library or "
                f"`pixcull library search`)[/dim]")
    except Exception as exc:  # noqa: BLE001 — never fail the run for this
        console.print(f"[yellow]auto-index skipped: {exc}[/]")


def run_pipeline(
    folder: Path,
    output: Path,
    scene_override: str | None = None,
    strictness: str = "standard",
    rescorer_mode: str | None = None,
    rescorer_path: str | None = None,
    progress_cb: Callable[[int, int, str], None] | None = None,
    vlm_mode: str = "off",
    # v2.50 — cloud judging ships on. Authority only means anything
    # when a judge is actually running, so vlm_mode="off" still
    # produces a fully local run: there is no verdict to defer to.
    vlm_authority: str = "primary",
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
    # V22.2 — pass output_dir so face_clustering can persist per-cluster
    # centroids; cross-run label inheritance reads them back.
    records = cluster_faces_across_rows(records, drop_embeddings=True,
                                          output_dir=output)

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
    # v2.4-P0-2b — apply the user's learned taste profile (no-op until they
    # have ≥ MIN_ANNS_FOR_PERSONALIZATION corrections). Shifts the keep/cull
    # boundary inside decide().
    # v2.14-P1 — ALSO tilt the per-axis fusion weights toward the axes the user
    # demonstrably values (axis_weights from their keep-vs-cull gap), passed
    # into fuse_score. Both are no-ops without an active profile, so generic
    # runs are byte-identical (verified by an A/B regression).
    _personal_shift = 0.0
    _axis_pref: dict[str, float] | None = None
    try:
        from pixcull.scoring.personalized import load_profile
        _pp = load_profile(Path.home() / ".pixcull" / "personal_profile.json")
        if _pp is not None and _pp.is_active():
            from pixcull.scoring.personal_learn import axis_weights
            _personal_shift = float(_pp.keep_threshold_shift)
            _axis_pref = axis_weights(_pp)
            _top = max(_axis_pref, key=lambda a: _axis_pref[a]) if _axis_pref else "—"
            console.print(
                f"[cyan]Personalized[/] keep/cull boundary shifted "
                f"{_personal_shift:+.3f} + axis-weighted toward [b]{_top}[/] "
                f"(from {_pp.n_annotations} of your corrections; cares most "
                f"about {_pp.most_cared_axis or '—'})")
    except Exception:
        _personal_shift = 0.0
        _axis_pref = None
    decisions, dim_scores, reasons_all = [], [], []
    _decide_args: list[dict] = []      # v2.48-P1 — for the re-decide pass
    rescorer_preds: list[str | None] = []
    rescorer_probs: list[float | None] = []
    for _, row in df.iterrows():
        row_dict = row.to_dict()
        dims = fuse_score(row_dict, row["flags"], row["scene"], config,
                          axis_pref=_axis_pref)

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

        # v2.48-P1 — remember what this row was decided on, so the
        # verdict can be recomputed once the vision judge has actually
        # seen the photo.  The VLM stage necessarily runs later (it needs
        # `decision` to know which rows to skip), so a judge with real
        # authority cannot be consulted here on the first pass.
        _decide_args.append({
            "final": dims["final"],
            "flags": row["flags"],
            "scene": row["scene"],
            "r_prob": r_prob,
        })
        dec, reasons = decide(
            dims["final"],
            row["flags"],
            config,
            strictness,  # type: ignore[arg-type]
            scene=row["scene"],
            rescorer_prob_keep=r_prob,
            vertical=vertical,           # V17.2 — per-batch override
            personal_shift=_personal_shift,   # v2.4-P0-2b — your taste
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
    # P-AI-5.1 — attach the explanation string ("最锐 +1.6σ" /
    # "动作差异最大 +2.1σ") to each cluster's winner.  Pure post-hoc
    # commentary; does NOT change is_burst_peak.
    df = annotate_burst_peak_reasons(df)

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
            # v2.48-P1 — with real authority the judge must see the rows
            # the rule would have thrown away. Skipping culls is a sound
            # economy for a second opinion (a cull is already a cull) and
            # nonsense for a first one: those are exactly the frames a
            # rule stack gets wrong, and the ones a photographer notices.
            vlm_verdicts_by_fn = run_vlm_stage(
                df, judge, output, progress_cb=progress_cb,
                score_culls=(vlm_authority == "primary"))
            if vlm_authority != "off":
                _reapply_decisions_with_vlm(
                    df, vlm_verdicts_by_fn, _decide_args, config,
                    strictness=strictness, vertical=vertical,
                    personal_shift=_personal_shift,
                    authority=vlm_authority)

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

    # v2.34 — persist the CLIP vectors that scene detection already
    # produced, in the exact format semantic_search.load_embeddings_cache
    # reads.  Before this, the first semantic query on a shoot re-encoded
    # every photo (minutes per thousand) and `pixcull library index`
    # silently skipped runs with no cache — which is every fresh run.
    # Now the cache is a by-product of culling, at zero extra inference.
    _write_clip_cache(df, output)

    # Export CSV (drop embeddings to keep file small)
    # (auto-index runs after the CSV lands — _run_path_map reads it)
    df_export = df.drop(columns=["embedding"], errors="ignore").copy()
    if "clip_embedding" in df_export.columns:
        df_export = df_export.drop(columns=["clip_embedding"])
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
    # After the CSV: _run_path_map reads its ``path`` column to resolve
    # each photo, so this has to follow the export, not precede it.
    _auto_index_library(output)
    if progress_cb is not None:
        progress_cb(total, total, "完成")
    return output
