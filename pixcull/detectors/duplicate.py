from datetime import datetime
from functools import cache
from typing import Optional

import numpy as np
import pandas as pd
import torch
from PIL import Image

from pixcull.detectors.base import DetectionResult, Detector


@cache
def _dino():
    from transformers import AutoImageProcessor, AutoModel

    device = (
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )
    proc = AutoImageProcessor.from_pretrained("facebook/dinov2-base")
    model = AutoModel.from_pretrained("facebook/dinov2-base").to(device).eval()
    return proc, model, device


class DuplicateDetector(Detector):
    """Computes DINOv2 embedding for each image; clustering happens in bulk after."""

    name = "duplicate"

    @torch.no_grad()
    def analyze(self, img: Image.Image, **_: object) -> DetectionResult:
        proc, model, device = _dino()
        inputs = proc(images=img, return_tensors="pt").to(device)
        out = model(**inputs).last_hidden_state[:, 0]
        out = torch.nn.functional.normalize(out, dim=-1)
        emb = out.cpu().numpy()[0].astype(np.float32)
        result = DetectionResult()
        result.extras["embedding"] = emb
        return result


# Per-scene overrides for burst detection. Stilllife product shoots take minutes,
# not seconds; wildlife bursts fire 20-30fps so the window is tight; event bursts
# are somewhere in between. These defaults override scene_templates.yaml when the
# template doesn't set them — see eval_findings.md §V0.5 for calibration.
_SCENE_BURST_DEFAULTS: dict[str, dict[str, float]] = {
    "stilllife":   {"time_gap_s": 300.0, "sim_thr": 0.90},  # 5-min product-shoot windows
    "wildlife":    {"time_gap_s": 1.0,   "sim_thr": 0.96},
    "event":       {"time_gap_s": 1.0,   "sim_thr": 0.94},
    "portrait":    {"time_gap_s": 2.0,   "sim_thr": 0.93},
    "landscape":   {"time_gap_s": 5.0,   "sim_thr": 0.94},
    "street":      {"time_gap_s": 2.0,   "sim_thr": 0.94},
}


def cluster_bursts(
    df: pd.DataFrame,
    time_gap_s: float = 2.0,
    sim_thr: float = 0.93,
    time_col: str = "datetime",
    emb_col: str = "embedding",
    scene_col: str = "scene",
    scene_overrides: Optional[dict[str, dict[str, float]]] = None,
) -> pd.DataFrame:
    """Assign cluster_id per row. Same cluster = same scene AND close time AND high embedding cosine.

    Thresholds are per-scene: wildlife uses a tight time window (fast burst rate),
    stilllife a loose one (multi-minute product shoots). Falls back to the
    `time_gap_s` / `sim_thr` args for scenes not in the override table.
    """
    overrides = {**_SCENE_BURST_DEFAULTS, **(scene_overrides or {})}

    def _thr_for(scene: object) -> tuple[float, float]:
        s = str(scene) if scene is not None else ""
        cfg = overrides.get(s)
        if cfg is None:
            return time_gap_s, sim_thr
        return float(cfg.get("time_gap_s", time_gap_s)), float(cfg.get("sim_thr", sim_thr))

    df = df.sort_values(time_col, na_position="last").reset_index(drop=True)
    cids: list[int] = [0]
    for i in range(1, len(df)):
        prev, cur = df.iloc[i - 1], df.iloc[i]
        same_scene = prev.get(scene_col) == cur.get(scene_col)
        t_gap, s_thr = _thr_for(cur.get(scene_col))
        time_close = (
            pd.notna(prev[time_col]) and pd.notna(cur[time_col])
            and (cur[time_col] - prev[time_col]).total_seconds() <= t_gap
        )
        sim = float(np.dot(prev[emb_col], cur[emb_col]))
        cids.append(cids[-1] if (same_scene and time_close and sim >= s_thr) else cids[-1] + 1)
    df["cluster_id"] = cids
    return df


def _time_bucket_groups(
    df: pd.DataFrame,
    scene_col: str,
    time_col: str,
    time_gap_s: float,
) -> list[list[int]]:
    """Group row indices by (same scene, time-adjacent within `time_gap_s`).

    Independent of embedding-similarity clustering because we want this to fire
    even when DINOv2 cosine sim between adjacent product shots falls below the
    `cluster_bursts` threshold (which happens when the photographer changes
    composition, zoom, or angle between takes).
    """
    ordered = df.sort_values(time_col, na_position="last")
    groups: list[list[int]] = []
    cur: list[int] = []
    prev_scene: object = None
    prev_t: object = None
    for idx, row in ordered.iterrows():
        scene = row.get(scene_col)
        t = row.get(time_col)
        same = scene == prev_scene
        close = (
            pd.notna(prev_t) and pd.notna(t)
            and (t - prev_t).total_seconds() <= time_gap_s
        )
        if same and close and cur:
            cur.append(idx)
        else:
            if cur:
                groups.append(cur)
            cur = [idx]
        prev_scene = scene
        prev_t = t
    if cur:
        groups.append(cur)
    return groups


def demote_mediocre_bursts(
    df: pd.DataFrame,
    decisions: list[str],
    reasons: list[str],
    *,
    scene_col: str = "scene",
    time_col: str = "datetime",
    min_cluster_size: int = 3,
    scene_rules: Optional[dict[str, dict[str, float]]] = None,
) -> tuple[list[str], list[str]]:
    """Cluster-level quality gate: demote entire bursts that look like a mediocre take.

    Rationale: when a photographer takes 5-10 similar product shots and the whole
    take has low aesthetic scores, they typically cull all of them — even though
    any single frame might pass the per-image `keep_min_score` threshold.

    Groups are built from (scene, datetime) proximity alone — we deliberately do
    NOT reuse `cluster_bursts` output here because product shoots often have
    DINOv2 cosine sim < 0.90 between adjacent takes (the photographer is
    exploring framings, not duplicating). Time + scene co-occurrence is the
    honest burst signal for this rule.

    Scope: currently only stilllife (product/food/studio) bursts — the golden set
    shows event/portrait bursts follow a different pattern (photographer wants
    diversity). Widen later once we have eval coverage for other scenes.

    Returns updated (decisions, reasons) lists of the same length as df.
    """
    rules = scene_rules or {
        "stilllife": {"clipiqa_median_floor": 0.55, "time_gap_s": 300.0},
    }

    decisions = list(decisions)
    reasons = list(reasons)

    if "clipiqa" not in df.columns:
        return decisions, reasons

    # Build per-scene groups (rules-scoped) and evaluate each.
    for scene, rule in rules.items():
        time_gap = float(rule.get("time_gap_s", 300.0))
        floor = float(rule.get("clipiqa_median_floor", 0.55))
        scene_df = df[df[scene_col] == scene]
        if scene_df.empty:
            continue

        groups = _time_bucket_groups(scene_df, scene_col, time_col, time_gap)
        for idx_list in groups:
            if len(idx_list) < min_cluster_size:
                continue
            grp = df.loc[idx_list]
            if float(grp["clipiqa"].median()) >= floor:
                continue
            # Mediocre take: demote every member to cull.
            tag = f"mediocre_burst[scene={scene},n={len(idx_list)}]"
            for idx in idx_list:
                if decisions[idx] == "cull":
                    continue
                decisions[idx] = "cull"
                reasons[idx] = f"{tag}; {reasons[idx]}" if reasons[idx] else tag

    return decisions, reasons
