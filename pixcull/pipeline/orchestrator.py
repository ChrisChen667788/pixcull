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
from pixcull.pipeline.worker import analyze_one
from pixcull.scoring.decision import Decision, decide
from pixcull.scoring.fusion import fuse_score
from pixcull.scoring.rescorer import load_rescorer, score_row

console = Console()


def run_pipeline(
    folder: Path,
    output: Path,
    scene_override: str | None = None,
    strictness: str = "standard",
    rescorer_mode: str | None = None,
    rescorer_path: str | None = None,
) -> Path:
    """Run the full culling pipeline on `folder` and write `scores.csv`.

    V1.2 additions:
        rescorer_mode: if provided, overrides ``config.rescorer.mode``.
            Values: "off" | "shadow" | "adjudicate". See RescorerConfig
            docstring for semantics.
        rescorer_path: if provided, overrides ``config.rescorer.model_path``.
    """
    output.mkdir(parents=True, exist_ok=True)
    config = PixCullConfig.load()
    if rescorer_mode is not None:
        config.rescorer.mode = rescorer_mode
    if rescorer_path is not None:
        config.rescorer.model_path = rescorer_path

    paths = list_images(folder)
    console.print(f"[cyan]Found {len(paths)} images under {folder}[/]")

    records = []
    for p in tqdm(paths, desc="analyzing"):
        r = analyze_one(p)
        if r:
            if scene_override:
                r["scene"] = scene_override
            records.append(r)

    df = pd.DataFrame(records)
    if df.empty:
        console.print("[red]No analyzable images.[/]")
        return output

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
    return output
