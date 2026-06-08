#!/usr/bin/env python3
"""v2.2-P0-1 — evaluate the learned audio tagger vs the DSP baseline.

Walks a labelled clip dir laid out folder-per-class::

    <eval-dir>/laughter/*.wav
    <eval-dir>/applause/*.wav
    <eval-dir>/none/*.wav        # negatives (no target event)

decodes each clip (ffmpeg, via ``scoring.audio_events.extract_audio``),
runs BOTH the always-on DSP detector (``analyze_audio``) and — when
``--model`` points at an ONNX — the learned ``OnnxTagger``, and reports
per-kind *detection* precision/recall/F1 for each, plus the macro-F1
delta and a promote/keep verdict.

Eval data is local-only (never committed).  The default dir is an ESC-50
subset fetched under /tmp; ESC-50 is CC BY-NC 3.0 (Piczak, 2015) and is
used here for evaluation only — not redistributed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TARGET_KINDS = ("laughter", "applause", "music")


def _grid(lo: float = 0.05, hi: float = 0.95, step: float = 0.05) -> list[float]:
    n = int(round((hi - lo) / step)) + 1
    return [round(lo + i * step, 3) for i in range(n)]


def _clips(eval_dir: Path):
    for kdir in sorted(p for p in eval_dir.iterdir() if p.is_dir()):
        for wav in sorted(kdir.glob("*.wav")):
            yield kdir.name, wav


def run_eval(eval_dir: Path, model: str | None = None) -> dict:
    from pixcull.scoring.audio_events import analyze_audio, extract_audio
    from pixcull.scoring.eval_metrics import binary_prf

    tagger = None
    if model:
        from pixcull.scoring.audio_tagger import OnnxTagger
        tagger = OnnxTagger(model_path=str(model))
        if not tagger.available():
            print(f"[warn] model {model} unusable (missing labels.json or "
                  f"onnxruntime) — evaluating DSP only", file=sys.stderr)
            tagger = None

    records = []   # (true_kind, dsp_kinds:set, learned_kinds:set|None)
    for true_kind, wav in _clips(eval_dir):
        try:
            samples, sr = extract_audio(wav)
        except Exception as exc:                       # noqa: BLE001
            print(f"[skip] {wav.name}: {exc}", file=sys.stderr)
            continue
        dsp = {e.kind for e in analyze_audio(samples, sr).events}
        learned = ({e.kind for e in tagger.tag(samples, sr)}
                   if tagger else None)
        records.append((true_kind, dsp, learned))

    def prf(which: str) -> dict:                        # "dsp" | "learned"
        rows = [r for r in records if which == "dsp" or r[2] is not None]
        out = {}
        for K in TARGET_KINDS:
            y_true = [r[0] == K for r in rows]
            if not any(y_true):       # kind not represented in this set
                continue
            y_pred = [K in (r[1] if which == "dsp" else r[2]) for r in rows]
            out[K] = binary_prf(y_true, y_pred)
        return out

    return {
        "n_clips": len(records),
        "model": str(model) if tagger else None,
        "dsp": prf("dsp"),
        "learned": prf("learned") if tagger else {},
    }


def _macro_f1(prf: dict) -> float:
    return sum(v["f1"] for v in prf.values()) / len(prf) if prf else 0.0


def format_report(res: dict, eval_dir: Path) -> str:
    out = ["# Audio tagger eval — DSP baseline vs learned (v2.2-P0-1)\n",
           f"- Eval set: `{eval_dir}` · {res['n_clips']} clips "
           "(ESC-50 subset, CC BY-NC 3.0 — eval only, not redistributed)",
           f"- Learned model: `{res['model'] or '(none — DSP baseline only)'}`\n",
           "| kind | DSP P | DSP R | DSP F1 | learned P | learned R | "
           "learned F1 | ΔF1 |",
           "|---|---|---|---|---|---|---|---|"]
    for K in sorted(set(res["dsp"]) | set(res["learned"])):
        d, l = res["dsp"].get(K), res["learned"].get(K)
        cells = [
            f"{d['precision']:.2f}" if d else "—",
            f"{d['recall']:.2f}" if d else "—",
            f"{d['f1']:.2f}" if d else "—",
            f"{l['precision']:.2f}" if l else "—",
            f"{l['recall']:.2f}" if l else "—",
            f"{l['f1']:.2f}" if l else "—",
            f"{l['f1'] - d['f1']:+.2f}" if (d and l) else "—",
        ]
        out.append(f"| {K} | " + " | ".join(cells) + " |")
    md, ml = _macro_f1(res["dsp"]), _macro_f1(res["learned"])
    line = f"\n- **macro-F1:** DSP `{md:.3f}`"
    if res["learned"]:
        line += f" · learned `{ml:.3f}` · Δ `{ml - md:+.3f}`"
    out.append(line)
    if res["learned"]:
        ok = ml >= md
        out.append("- **verdict:** " + ("✅ learned ≥ DSP — promote to "
                   "default" if ok else "❌ learned < DSP — keep DSP default"))
    else:
        out.append("- learned path not evaluated (no model supplied)")
    return "\n".join(out) + "\n"


def calibrate(eval_dir: Path, model: str, grid: list[float] | None = None) -> dict:
    """v2.4-P1-3 — sweep per-kind detection thresholds on the eval set and
    pick the F1-max operating point per kind.

    The default 0.5 blanket threshold is precision-heavy (laughter recall
    0.25 @ P 1.0); a lower per-kind threshold trades a little precision for
    a lot of recall.  We run the model ONCE per clip (``infer_probs``),
    cache the probs, then sweep thresholds through the **real**
    :func:`probs_to_events` detection path (min-duration merging included),
    so the chosen point is faithful to what the pipeline will do.

    Returns ``{kind: {threshold, f1, recall, precision, f1_at_0.5,
    recall_at_0.5}}`` (kinds with no positive in the set are skipped).
    """
    from pixcull.scoring.audio_events import extract_audio
    from pixcull.scoring.audio_tagger import (
        OnnxTagger, best_threshold, probs_to_events)
    from pixcull.scoring.eval_metrics import binary_prf

    grid = grid or _grid()
    tagger = OnnxTagger(model_path=str(model))
    if not tagger.available():
        raise SystemExit(f"model {model} unusable (labels.json / onnxruntime)")

    cache = []   # (true_kind, probs, times)
    for true_kind, wav in _clips(eval_dir):
        try:
            samples, sr = extract_audio(wav)
        except Exception as exc:                       # noqa: BLE001
            print(f"[skip] {wav.name}: {exc}", file=sys.stderr)
            continue
        probs, times = tagger.infer_probs(samples, sr)
        cache.append((true_kind, probs, times))
    labels, hop = tagger._labels(), tagger.hop_s

    def detect(probs, times, t, K) -> bool:
        return K in {e.kind for e in probs_to_events(
            probs, times, labels, hop_s=hop, thresh=t)}

    result: dict = {}
    for K in TARGET_KINDS:
        truth = [tk == K for tk, _, _ in cache]
        if not any(truth):
            continue

        def scorer(t, K=K):
            return [detect(p, ti, t, K) for _, p, ti in cache]

        thr, f1 = best_threshold(truth, scorer, grid=grid)
        base = binary_prf(truth, scorer(0.5))
        best = binary_prf(truth, scorer(thr))
        result[K] = {
            "threshold": round(thr, 3),
            "f1": round(best["f1"], 3),
            "recall": round(best["recall"], 3),
            "precision": round(best["precision"], 3),
            "f1_at_0.5": round(base["f1"], 3),
            "recall_at_0.5": round(base["recall"], 3),
        }
    return result


def format_calibration(cal: dict) -> str:
    out = ["# Audio tagger threshold calibration — v2.4-P1-3\n",
           "Per-kind F1-max operating point swept on the ESC-50 subset "
           "(CC BY-NC 3.0 — eval only).\n",
           "| kind | thresh | F1 @0.5 → F1\\* | recall @0.5 → recall\\* | "
           "precision\\* |",
           "|---|---|---|---|---|"]
    for K in sorted(cal):
        c = cal[K]
        out.append(
            f"| {K} | {c['threshold']:.2f} | "
            f"{c['f1_at_0.5']:.2f} → {c['f1']:.2f} | "
            f"{c['recall_at_0.5']:.2f} → {c['recall']:.2f} | "
            f"{c['precision']:.2f} |")
    if cal:
        mb = sum(c["f1_at_0.5"] for c in cal.values()) / len(cal)
        ma = sum(c["f1"] for c in cal.values()) / len(cal)
        out.append(f"\n- **macro-F1:** `{mb:.3f}` → **`{ma:.3f}`** "
                   f"(Δ `{ma - mb:+.3f}`)")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval-dir", type=Path,
                    default=Path("/tmp/pixcull_audio_eval"))
    ap.add_argument("--model", default=None, help="ONNX audio model (optional)")
    ap.add_argument("--out", type=Path, default=None,
                    help="write the markdown report here")
    ap.add_argument("--calibrate", action="store_true",
                    help="v2.4-P1-3: sweep per-kind thresholds → F1-max "
                         "operating point (requires --model)")
    ap.add_argument("--write-thresholds", type=Path, default=None,
                    help="write the calibrated {kind: threshold} sidecar "
                         "JSON here (pair with --calibrate)")
    a = ap.parse_args()
    if not a.eval_dir.is_dir():
        ap.error(f"eval dir not found: {a.eval_dir}")

    if a.calibrate:
        if not a.model:
            ap.error("--calibrate requires --model")
        cal = calibrate(a.eval_dir, a.model)
        report = format_calibration(cal)
        print(report)
        if a.write_thresholds:
            payload = {k: v["threshold"] for k, v in cal.items()}
            a.write_thresholds.write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(f"[written] {a.write_thresholds}", file=sys.stderr)
        if a.out:
            a.out.write_text(report, encoding="utf-8")
            print(f"[written] {a.out}", file=sys.stderr)
        return 0

    res = run_eval(a.eval_dir, a.model)
    report = format_report(res, a.eval_dir)
    print(report)
    if a.out:
        a.out.write_text(report, encoding="utf-8")
        print(f"[written] {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
