"""P-AI-5.7 — per-blendshape feature-importance analysis.

The FaceDetector currently exposes 3 of mediapipe's 52 blendshape
channels: ``eyeBlink``, ``mouthSmile``, ``browDown``.  P-AI-5.5 showed
those three lift the picker's exact-agreement ceiling from 15% to
38.5% on the wedding tuning corpus.  The remaining 49 channels
might carry more signal — but we don't know which without measuring.

This script does the measurement.  For each of the 13 tuning bursts:

  1. Run mediapipe FaceLandmarker on each frame
  2. Pull all 52 blendshape scores
  3. Compute per-channel "delta from burst average" for the
     photographer's pick(s) vs everyone else
  4. Average that delta across all bursts → a per-channel
     "selection bias"

Channels with the largest positive bias are signals the
photographer was reading and the picker could leverage.

Output: a ranked CSV that anybody can eyeball before deciding which
channels to wire into BurstPeakWeights as full picker components.

Usage:
    /tmp/p_ai_54_venv/bin/python \\
        scripts/analyze_blendshape_importance.py \\
        /Volumes/.../李慧&李翔/JPG原图 \\
        out_wedding_eval/bursts.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image


# The 52 mediapipe Face Blendshape channel names.  Order matches the
# `mediapipe.tasks.python.vision.FaceLandmarkerResult.face_blendshapes`
# index ordering.
BLENDSHAPE_NAMES = [
    "_neutral", "browDownLeft", "browDownRight", "browInnerUp",
    "browOuterUpLeft", "browOuterUpRight", "cheekPuff",
    "cheekSquintLeft", "cheekSquintRight", "eyeBlinkLeft",
    "eyeBlinkRight", "eyeLookDownLeft", "eyeLookDownRight",
    "eyeLookInLeft", "eyeLookInRight", "eyeLookOutLeft",
    "eyeLookOutRight", "eyeLookUpLeft", "eyeLookUpRight",
    "eyeSquintLeft", "eyeSquintRight", "eyeWideLeft", "eyeWideRight",
    "jawForward", "jawLeft", "jawOpen", "jawRight",
    "mouthClose", "mouthDimpleLeft", "mouthDimpleRight", "mouthFrownLeft",
    "mouthFrownRight", "mouthFunnel", "mouthLeft", "mouthLowerDownLeft",
    "mouthLowerDownRight", "mouthPressLeft", "mouthPressRight",
    "mouthPucker", "mouthRight", "mouthRollLower", "mouthRollUpper",
    "mouthShrugLower", "mouthShrugUpper", "mouthSmileLeft",
    "mouthSmileRight", "mouthStretchLeft", "mouthStretchRight",
    "mouthUpperUpLeft", "mouthUpperUpRight", "noseSneerLeft",
    "noseSneerRight",
]


def extract_all_blendshapes(
    img,
    landmarker,
) -> dict[str, float]:
    """Run the mediapipe FaceLandmarker on a PIL image, return all
    52 blendshapes as a dict.  Missing detection → empty dict
    (caller treats as no signal)."""
    import mediapipe as mp
    import numpy as np

    rgb = np.array(img.convert("RGB"))
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = landmarker.detect(mp_image)
    if not res.face_blendshapes:
        return {}
    # Largest-face mode: take blendshapes from the first face
    bs = res.face_blendshapes[0]
    return {b.category_name: b.score for b in bs}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", type=Path,
                    help="Folder containing burst frames.")
    ap.add_argument("bursts", type=Path,
                    help="bursts.json (output of the burst detector).")
    ap.add_argument("--out", type=Path,
                    default=Path("out_wedding_eval/blendshape_importance.csv"))
    args = ap.parse_args()

    # Use pixcull's existing FaceDetector — already wired to the
    # bundled face_landmarker.task model + blendshapes enabled.
    # FaceDetector lazy-inits on first analyze() call; force it
    # here by analyzing a dummy black frame.
    from pixcull.detectors.face import FaceDetector
    fd = FaceDetector()
    fd.analyze(Image.new("RGB", (256, 256)))   # trigger _lazy_init
    landmarker = fd._landmarker
    if landmarker is None:
        sys.exit("pixcull FaceDetector didn't initialize a landmarker — "
                 "check that pixcull/detectors/_models/face_landmarker.task "
                 "exists + mediapipe is importable.")

    with args.bursts.open() as f:
        bursts = json.load(f)

    # For each burst, compute per-channel pick-vs-non-pick deltas
    per_channel_deltas: dict[str, list[float]] = defaultdict(list)
    n_processed = 0
    for i, b in enumerate(bursts):
        pick_set = set(b.get("photographer_pick") or [])
        if not pick_set:
            continue
        frame_blendshapes: list[tuple[str, dict[str, float]]] = []
        for fn in b["frames"]:
            p = args.folder / fn
            if not p.is_file():
                cand = [c for c in args.folder.iterdir()
                        if c.name.lower() == fn.lower()]
                if not cand: continue
                p = cand[0]
            try:
                img = Image.open(p)
                bs = extract_all_blendshapes(img, landmarker)
                if bs:
                    frame_blendshapes.append((fn, bs))
            except Exception as exc:
                print(f"  skip {fn}: {exc}", file=sys.stderr)
        if not frame_blendshapes:
            continue
        # For each channel, compute pick mean − non-pick mean within
        # this burst.  Skip if either subset is empty.
        all_channels = set()
        for _, bs in frame_blendshapes:
            all_channels.update(bs.keys())
        for ch in all_channels:
            pick_vals = [bs.get(ch, 0.0) for fn, bs in frame_blendshapes
                         if fn in pick_set]
            other_vals = [bs.get(ch, 0.0) for fn, bs in frame_blendshapes
                          if fn not in pick_set]
            if not pick_vals or not other_vals:
                continue
            pick_mean  = sum(pick_vals) / len(pick_vals)
            other_mean = sum(other_vals) / len(other_vals)
            per_channel_deltas[ch].append(pick_mean - other_mean)
        n_processed += 1
        print(f"  [{i+1}/{len(bursts)}] burst {b['frames'][0]} → "
              f"{len(pick_set)} pick(s) / {len(frame_blendshapes) - len(pick_set)} other",
              file=sys.stderr)

    print(f"processed {n_processed} bursts", file=sys.stderr)

    # Aggregate: average + n samples + count of positive bursts
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for ch, deltas in per_channel_deltas.items():
        n = len(deltas)
        avg = sum(deltas) / n if n else 0.0
        n_pos = sum(1 for d in deltas if d > 0)
        rows.append((ch, avg, n_pos, n))
    rows.sort(key=lambda r: abs(r[1]), reverse=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["channel", "avg_pick_minus_other",
                    "n_positive_bursts", "n_bursts"])
        for r in rows:
            w.writerow([r[0], f"{r[1]:+.4f}", r[2], r[3]])

    print(f"\nwrote {args.out}", file=sys.stderr)
    print("\nTop-15 channels by abs(avg pick - other):", file=sys.stderr)
    print(f'{"channel":<22s}  {"avg Δ":>8s}  {"+bursts":>8s}', file=sys.stderr)
    for ch, avg, n_pos, n in rows[:15]:
        print(f"  {ch:<22s}  {avg:+8.4f}  {n_pos:>3d}/{n}", file=sys.stderr)


if __name__ == "__main__":
    main()
