"""P-AI-5.2 — tune burst peak picker weights against a real
shoot's photographer-confirmed picks.

Reads ``out_wedding_eval/bursts.json`` (one entry per burst, each
with a list of frame filenames + the photographer's pick(s)),
computes per-frame sharpness + CLIP embedding, runs the picker
under several weight configurations, prints agreement rates.

The two heavyweight signals are:
  · score_sharpness  — Laplacian variance, normalized within burst
  · embedding         — CLIP image features

score_final and face_evidence are zeroed for this experiment
because they require the full pipeline (rescorer + face detector)
to compute; the sharpness + distinctness blend carries 70% of the
default weights so we can still meaningfully sweep them.

Usage:
    python scripts/tune_burst_peak_weights.py /Volumes/.../JPG原图
                                              out_wedding_eval/bursts.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from PIL import Image


def _laplacian_var(pil_img: Image.Image) -> float:
    """Lightweight sharpness proxy via OpenCV Laplacian variance.

    Higher = sharper. Returns the raw variance — caller normalizes
    within burst.
    """
    import cv2
    arr = np.array(pil_img.convert("L"))
    return float(cv2.Laplacian(arr, cv2.CV_64F).var())


@torch.no_grad()
def _embed_one(pil_img: Image.Image, clip_tools) -> list[float]:
    proc, model, device = clip_tools
    # transformers 5.x changed `get_image_features` to return the
    # vision-model's BaseModelOutputWithPooling instead of a tensor.
    # Use the joint forward with a placeholder text input — the joint
    # model returns image_embeds (projected + L2-normalized) directly,
    # which is what the V22 face-clustering pipeline relies on too.
    inputs = proc(text=[""], images=pil_img,
                  return_tensors="pt", padding=True).to(device)
    out = model(**inputs)
    feats = out.image_embeds   # already L2-normalized in the projection head
    return feats.cpu().numpy()[0].tolist()


def featurize_burst(
    folder: Path, frames: list[str], clip_tools,
) -> list[dict]:
    out = []
    for fn in frames:
        p = folder / fn
        if not p.is_file():
            # Try jpg/JPG case-insensitively
            cand = [c for c in folder.iterdir()
                    if c.name.lower() == fn.lower()]
            if not cand: continue
            p = cand[0]
        try:
            img = Image.open(p).convert("RGB")
        except Exception as exc:
            print(f"  skip {fn}: {exc}", file=sys.stderr)
            continue
        sharp = _laplacian_var(img)
        emb = _embed_one(img, clip_tools)
        out.append({
            "filename":        fn,
            "score_sharpness": sharp,
            "score_final":     0.0,
            "embedding":       emb,
            "face_bboxes":     [],
        })
    return out


def evaluate_picker_weights(
    bursts: list[dict],
    folder: Path,
    weight_configs: list[tuple[str, dict]],
) -> None:
    from transformers import CLIPModel, CLIPProcessor
    from pixcull.scoring.burst_peak import (
        BurstPeakWeights, rank_burst_peak,
    )

    device = (
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )
    proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    model = CLIPModel.from_pretrained(
        "openai/clip-vit-base-patch32").to(device).eval()
    clip_tools = (proc, model, device)

    # Cache featurized bursts so we don't re-embed when sweeping
    # weights. ~1 min per burst on MPS, sweep over ~6 configs.
    cache_path = folder.parent / "burst_features_cache.json"
    if cache_path.exists():
        print(f"loading cached features from {cache_path}", file=sys.stderr)
        with cache_path.open() as f:
            featurized = json.load(f)
    else:
        print(f"featurizing {len(bursts)} bursts (CLIP image embeddings)...",
              file=sys.stderr)
        featurized = []
        for i, b in enumerate(bursts):
            print(f"  burst {i+1}/{len(bursts)} ({len(b['frames'])} frames)",
                  file=sys.stderr)
            rows = featurize_burst(folder, b["frames"], clip_tools)
            featurized.append({"rows": rows,
                               "photographer_pick": b["photographer_pick"]})
        with cache_path.open("w") as f:
            json.dump(featurized, f)
        print(f"  cached → {cache_path}", file=sys.stderr)

    # Sweep configs
    print()
    print(f"{'config':<24s} {'agreement':>12s}  per-burst pick vs photographer")
    print("-" * 90)
    for name, w in weight_configs:
        weights = BurstPeakWeights(**w)
        agree = 0
        total = 0
        burst_results = []
        for b in featurized:
            rows = b["rows"]
            if len(rows) < 2:
                continue
            result = rank_burst_peak(rows, weights=weights)
            picks = set(b["photographer_pick"])
            ok = result.winner_filename in picks
            agree += int(ok)
            total += 1
            burst_results.append(
                ("✓" if ok else "✗",
                 result.winner_filename,
                 b["photographer_pick"][0] if b["photographer_pick"] else "?")
            )
        rate = 100.0 * agree / total if total else 0
        print(f"{name:<24s} {agree:>4d}/{total:<4d} = {rate:5.1f}%")
        for ok, our, theirs in burst_results:
            print(f"  {ok}  ours={our}  photographer={theirs}")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path,
                    help="Folder containing the raw JPG burst frames.")
    ap.add_argument("bursts", type=Path,
                    help="bursts.json (output of the burst-detection helper).")
    args = ap.parse_args()
    with args.bursts.open() as f:
        bursts = json.load(f)
    if not bursts:
        sys.exit("no bursts in input")
    print(f"loaded {len(bursts)} bursts", file=sys.stderr)

    # Weight configs to sweep.  All sum to 1.0 so the picker scoring
    # comparison is apples-to-apples.
    configs = [
        ("default (P-AI-5)",  {"sharpness": 0.40, "distinctness": 0.30,
                               "quality": 0.20,   "face": 0.10}),
        ("sharp-dominant",    {"sharpness": 0.70, "distinctness": 0.20,
                               "quality": 0.05,   "face": 0.05}),
        ("distinct-dominant", {"sharpness": 0.20, "distinctness": 0.70,
                               "quality": 0.05,   "face": 0.05}),
        ("balanced",          {"sharpness": 0.50, "distinctness": 0.50,
                               "quality": 0.00,   "face": 0.00}),
        ("sharp-only",        {"sharpness": 1.00, "distinctness": 0.00,
                               "quality": 0.00,   "face": 0.00}),
        ("distinct-only",     {"sharpness": 0.00, "distinctness": 1.00,
                               "quality": 0.00,   "face": 0.00}),
    ]
    evaluate_picker_weights(bursts, args.folder, configs)


if __name__ == "__main__":
    main()
