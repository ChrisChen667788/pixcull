#!/usr/bin/env python3
"""v3.98 — does a taste profile learned on some shoots predict another?

v2.83 asked it and could not answer: every correction came from one
shoot, so a held-out fold sat beside the frames it was learned from — same
light, same day — and a good figure showed memory, not taste. The owner's
blind labels now span several shoots. This learns on all but one, predicts
the one left out, and does that for each; then the same within each shoot,
which is the memorisation figure and is printed as such.

    scripts/measure_generalisation.py \\
        --shoot "portrait 2023" portrait SHEET.json SCORES.csv \\
        --shoot "Zhangye"       landscape SHEET.json SCORES.csv \\
        --shoot "Zhangye"       landscape OTHER_SHEET.json OTHER_SCORES.csv ...

A shoot may be given more than once, one blind sheet with the scores of
the run that scored it each time. A photograph is `filename@datetime`,
because the shutter counter wraps and shoots reuse names: labelled twice
with the same answer it is kept once, with different answers it is left
out and counted, and the agreement between the two passes is printed — it
is how consistent the labeller is with themself, which no model of their
taste can beat.

Two decisions are measured. `evaluate()` is personal_learn's own: the mean
of the axis stars against a threshold, the acceptance test v2.4 defined.
The product's is `decision.decide` on `score_final`, which is where a
profile's threshold shift actually lands; that section learns the shift on
the other shoots and applies it to the held-out one, and `--profile` scores
a saved profile on every photograph. Both report cull recall beside keep-F1,
because keep-F1 rewards keeping more.

What it found the first time (2026-10-28, the owner's 728 photographs in
five shoots): learned on four and tested on the fifth, the profile lowers
evaluate()'s keep-F1 by 0.027 on average, and by 0.178 within portrait. In
the product's decision the learned shift is negative on every split, because
it compares the photographer's keep rate with a fixed 65% and not with what
the machine already keeps; it raises keep-F1 0.743 to 0.777 and halves cull
recall, 7.7% to 3.6%.
"""
from __future__ import annotations

import argparse
import csv
import random
import statistics
import sys
from collections import Counter, defaultdict

from pixcull.scoring.personal_learn import (
    DECISIONS, Example, evaluate, examples_from_blind_sheet, learn_profile,
)


def assemble(specs) -> tuple[list[Example], dict, dict]:
    """One example per photograph, what deduplication found, and the score
    row behind each photograph (for the product's own decision)."""
    seen: dict[str, list[Example]] = defaultdict(list)
    rows: dict[str, dict] = {}
    for name, genre, sheet, scores in specs:
        with open(scores, newline="", encoding="utf-8") as fh:
            by_name = {r["filename"]: r for r in csv.DictReader(fh)}
        for e in examples_from_blind_sheet(sheet, scores, shoot=name):
            e.vertical = genre
            seen[e.key].append(e)
            # The first spec's row, like the example kept below: a photo in
            # two specs is judged from the run its kept label belongs to.
            rows.setdefault(e.key, by_name[e.key.rsplit("@", 1)[0]])
    kept, twice, agree, dropped = [], 0, 0, 0
    for exs in seen.values():
        if len(exs) > 1:
            twice += 1
            if len({e.decision for e in exs}) == 1:
                agree += 1
            else:
                dropped += 1
                continue
        kept.append(exs[0])
    return kept, {"labelled_twice": twice, "agreed": agree, "dropped": dropped}, rows


def _f1_line(label: str, ev: dict) -> str:
    if ev.get("refused"):
        return f"  {label:<34} not measured: {ev['refused']}"
    line = (f"  {label:<34} n={ev['n']:<4} generic {ev['generic_f1']:.3f}  "
            f"personal {ev['personal_f1']:.3f}  Δ {ev['delta']:+.3f}")
    if ev.get("generic_cull_recall") is not None:
        line += (f"  cull recall {ev['generic_cull_recall']:.0%} → "
                 f"{ev['personal_cull_recall']:.0%}")
    return line


def product_scores(pairs) -> tuple[float, float | None]:
    """keep-F1 and cull recall of (truth, verdict) pairs."""
    tp = sum(t == "keep" and p == "keep" for t, p in pairs)
    fp = sum(t != "keep" and p == "keep" for t, p in pairs)
    fn = sum(t == "keep" and p != "keep" for t, p in pairs)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    culls = [p for t, p in pairs if t == "cull"]
    return ((2 * prec * rec / (prec + rec)) if prec + rec else 0.0,
            (sum(p == "cull" for p in culls) / len(culls)) if culls else None)


def _product_verdict(row: dict, shift: float, cfg) -> str:
    from pixcull.scoring.decision import decide
    from pixcull.scoring.vlm_eval import _flags_of
    try:
        score = float(row.get("score_final") or 0)
    except (TypeError, ValueError):
        score = 0.0
    verdict, _ = decide(score, _flags_of(row), cfg, "standard",
                        scene=str(row.get("scene") or ""), personal_shift=shift)
    return verdict.value


def product_leave_one_shoot_out(exs, rows, cfg) -> list[str]:
    """The learned threshold shift, in the product's decision, on a shoot
    it was not learned from. Beside it, what a shift measured against the
    machine's own keep rate on the same frames would have done — reported,
    not shipped. The threshold shift only: the learned axis weights also
    tilt `fuse_score` in the product and are not re-applied here."""
    from pixcull.scoring.personalized import MAX_THRESHOLD_SHIFT
    clamp = lambda x: max(-MAX_THRESHOLD_SHIFT, min(MAX_THRESHOLD_SHIFT, x))
    shoots = sorted({e.run_id for e in exs})
    out, acc = [], defaultdict(list)
    for held in shoots:
        train = [e for e in exs if e.run_id != held]
        test = [e for e in exs if e.run_id == held]
        shift = learn_profile(train).keep_threshold_shift
        owner_keep = sum(e.decision == "keep" for e in train) / len(train)
        machine_keep = sum(_product_verdict(rows[e.key], 0.0, cfg) == "keep"
                           for e in train) / len(train)
        rel = clamp(-(owner_keep - machine_keep) * 0.5)
        res = {k: product_scores([(e.decision, _product_verdict(rows[e.key], s, cfg))
                                  for e in test])
               for k, s in (("none", 0.0), ("learned", shift), ("relative", rel))}
        for k, v in res.items():
            acc[k].append(v)
        fmt = lambda t: f"{t[0]:.3f}/{'—' if t[1] is None else format(t[1], '.0%')}"
        out.append(f"    held out {held:<26} learned shift {shift:+.3f}: "
                   f"{fmt(res['none'])} → {fmt(res['learned'])}   "
                   f"vs-machine shift {rel:+.3f}: {fmt(res['relative'])}")
    head = []
    for k, label in (("none", "no shift"), ("learned", "learned shift"),
                     ("relative", "shift vs machine (hypothetical)")):
        f1 = statistics.mean(v[0] for v in acc[k])
        crs = [v[1] for v in acc[k] if v[1] is not None]
        head.append(f"  mean, {label:<32} keep-F1 {f1:.3f}  cull recall "
                    f"{statistics.mean(crs):.1%}" if crs else "")
    return head + ["  (keep-F1/cull recall per held-out shoot)"] + out


def score_saved_profile(path, exs, rows, cfg) -> list[str]:
    """A saved profile's threshold shift on every photograph. Its axis
    weights are not re-applied: they tilt `fuse_score`, which would mean
    re-fusing every frame, and an equal-weight profile is a no-op there by
    construction (`fusion._personalize_weights`)."""
    from pathlib import Path

    from pixcull.scoring.personal_learn import axis_weights
    from pixcull.scoring.personalized import load_profile
    path = Path(path).expanduser()
    prof = load_profile(path)
    if prof is None:
        return [f"  {path}: no profile"]
    w = axis_weights(prof)
    equal = len({round(v, 6) for v in w.values()}) <= 1
    out = [f"  {path.name}: shift {prof.keep_threshold_shift:+.3f} from "
           f"{prof.n_annotations} corrections, active={prof.is_active()}, "
           f"axis weights {'equal (no effect on fusion)' if equal else 'not equal (not re-applied here)'}"]
    for label, s in (("without it", 0.0), ("with it", prof.keep_threshold_shift)):
        verdicts = [_product_verdict(rows[e.key], s, cfg) for e in exs]
        f1, cr = product_scores(list(zip((e.decision for e in exs), verdicts)))
        out.append(f"    {label:<11} keep-F1 {f1:.3f}  cull recall "
                   f"{'—' if cr is None else format(cr, '.1%')}  "
                   f"verdicts {dict(Counter(verdicts))}")
    return out


def leave_one_shoot_out(exs: list[Example]) -> list[str]:
    ev = evaluate(exs)
    if ev.get("refused"):
        return [_f1_line("leave one shoot out", ev)]
    if not ev["grouped"]:
        # One shoot, or examples without one: evaluate() fell back to
        # stride folds, which is the within-shoot figure, not this one.
        return ["  not measured: fewer than two shoots, so there is no "
                "unseen shoot to predict"]
    out = [_f1_line(f"mean over {ev['folds']} held-out shoots", ev)]
    for shoot, d, n in zip(ev["fold_groups"], ev["fold_deltas"], ev["fold_n"]):
        out.append(f"    held out {shoot:<26} n={n:<4} Δ {d:+.3f}")
    return out


def within_shoot(exs: list[Example], redraws: int) -> list[str]:
    """Stride folds inside one shoot: memorisation, with the spread over
    redrawn folds, since a stride figure from one file order is one draw."""
    flat = [Example(axes=e.axes, decision=e.decision) for e in exs]
    ev = evaluate(flat)
    if ev.get("refused"):
        return [_f1_line("within the shoot", ev)]
    ds = []
    for seed in range(redraws):
        xs = flat[:]
        random.Random(seed).shuffle(xs)
        r = evaluate(xs)
        if not r.get("refused"):
            ds.append(r["delta"])
    line = _f1_line("within the shoot (memorisation)", ev)
    if ds:
        line += (f"  | redrawn ×{len(ds)}: Δ {min(ds):+.3f}…{max(ds):+.3f}, "
                 f"mean {statistics.mean(ds):+.3f}")
    return [line]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shoot", nargs=4, action="append", required=True,
                    metavar=("NAME", "GENRE", "SHEET", "SCORES"))
    ap.add_argument("--redraws", type=int, default=200)
    ap.add_argument("--profile", help="also score a saved personal_profile.json "
                                      "on every photograph, in the product's decision")
    a = ap.parse_args(argv)
    exs, dup, rows = assemble(a.shoot)
    by_shoot = defaultdict(list)
    for e in exs:
        by_shoot[e.run_id].append(e)
    print(f"{len(exs)} photographs in {len(by_shoot)} shoots; "
          f"{dup['labelled_twice']} labelled twice, {dup['agreed']} the same both times"
          + (f" ({dup['agreed'] / dup['labelled_twice']:.0%})" if dup["labelled_twice"] else "")
          + f", {dup['dropped']} left out for disagreeing")
    for shoot, xs in by_shoot.items():
        mix = Counter(e.decision for e in xs)
        print(f"  {shoot:<28} {xs[0].vertical:<10} n={len(xs):<4} "
              + " ".join(f"{k}={mix[k]}" for k in DECISIONS if mix[k]))
    print("\nacross shoots, every genre:")
    print("\n".join(leave_one_shoot_out(exs)))
    for genre in sorted({e.vertical for e in exs}):
        same = [e for e in exs if e.vertical == genre]
        if len({e.run_id for e in same}) >= 2:
            print(f"\nacross shoots, {genre} only:")
            print("\n".join(leave_one_shoot_out(same)))
    print("\nwithin each shoot:")
    for shoot, xs in by_shoot.items():
        print(f" {shoot}")
        print("\n".join(within_shoot(xs, a.redraws)))
    from pixcull.config import PixCullConfig
    cfg = PixCullConfig.load()
    if len(by_shoot) >= 2:
        print("\nthe product's decision, leave one shoot out:")
        print("\n".join(product_leave_one_shoot_out(exs, rows, cfg)))
    if a.profile:
        print("\na saved profile, in the product's decision:")
        print("\n".join(score_saved_profile(a.profile, exs, rows, cfg)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
