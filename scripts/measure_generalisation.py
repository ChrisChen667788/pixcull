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

v3.99 asks v3.8's question, one profile or one per kind of shoot:
`evaluate_by_vertical` keyed by the genre given here and by each frame's scene
label (what `gather_examples_from_runs` records), held out by shoot where a
kind was shot twice and as the stride it shipped with; where each arm's
verdicts go; and the per-kind threshold shift in the product's decision. On
the same 728 only portrait was shot more than once. Held out a shoot at a
time, the portrait profile agrees with the owner on 63.8% against 75.1% for
one profile and 83.9% for none, culls at about the rate culls occur, and
changes two verdicts in 728 in the product's decision.

v3.99 also applies a profile whole, as `run_pipeline` does: the shift, and the
axis weights tilting the fusion, by recomputing `score_final` from the
per-dimension scores a run keeps — only where, untilted, they give it back.
v3.98's figures were the shift alone; whole, the learned profile culls less
still, 2.5% against 7.7% with none.

From v3.99.1 `learn_profile` measures the shift against the machine's keep
rate, so the evaluate() sections report the new formula (−0.055 across five
shoots; v3.98's −0.027 was the fixed-65% one). The product section reports
both: the fixed-65% shift by `_fixed_shift`, and the learned one.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import random
import statistics
import sys
from collections import Counter, defaultdict

from pixcull.scoring.personal_learn import (
    DECISIONS, MIN_PER_VERTICAL, Example, evaluate, evaluate_by_vertical,
    examples_from_blind_sheet, learn_profile,
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


_DIMS = ("sharpness", "composition", "exposure", "aesthetic", "moment")


def _refuse(row: dict, axis_pref: dict | None, cfg) -> float:
    """`score_final` again from the per-dimension scores the run kept, with a
    profile's axis weights tilting the fusion as `run_pipeline` tilts it
    (`fuse_score(..., axis_pref=...)`). Only trusted once `refuses()` has
    shown that with no tilt it gives back the recorded `score_final`."""
    from pixcull.scoring.fusion import _personalize_weights
    from pixcull.scoring.vlm_eval import _flags_of
    tpl = cfg.template_for(str(row.get("scene") or ""))
    w = tpl.weights or cfg.defaults.get("weights", {})
    if axis_pref:
        w = _personalize_weights(w, axis_pref)
    final = sum(float(row[f"score_{k}"]) * w.get(k, 0.0) for k in _DIMS)
    flags = _flags_of(row)
    for flag, delta in (tpl.bonuses or {}).items():
        if flag in flags:
            final += float(delta)
    for flag, delta in (tpl.penalties or {}).items():
        if flag in flags:
            final -= abs(float(delta))
    return max(0.0, min(1.0, final))


def refuses(rows: dict, cfg) -> bool:
    """Does every row's recorded `score_final` come back from its
    per-dimension scores? If not, the axis weights cannot be measured from
    this run and nothing is reported for them."""
    try:
        return all(abs(_refuse(r, None, cfg) - float(r["score_final"])) < 1e-6
                   for r in rows.values())
    except (KeyError, TypeError, ValueError):
        return False


def _product_verdict(row: dict, shift: float, cfg, axis_pref: dict | None = None) -> str:
    from pixcull.scoring.decision import decide
    from pixcull.scoring.vlm_eval import _flags_of
    if axis_pref:
        score = _refuse(row, axis_pref, cfg)
    else:
        try:
            score = float(row.get("score_final") or 0)
        except (TypeError, ValueError):
            score = 0.0
    verdict, _ = decide(score, _flags_of(row), cfg, "standard",
                        scene=str(row.get("scene") or ""), personal_shift=shift)
    return verdict.value


def _relative_shift(train, rows, cfg) -> float:
    """The shift measured against the machine's own keep rate on the same
    frames, rather than against a fixed 65%: −(owner − machine) × 0.5,
    under the same cap."""
    from pixcull.scoring.personalized import MAX_THRESHOLD_SHIFT
    owner_keep = sum(e.decision == "keep" for e in train) / len(train)
    machine_keep = sum(_product_verdict(rows[e.key], 0.0, cfg) == "keep"
                       for e in train) / len(train)
    x = -(owner_keep - machine_keep) * 0.5
    return max(-MAX_THRESHOLD_SHIFT, min(MAX_THRESHOLD_SHIFT, x))


def _fixed_shift(train) -> float:
    """The shift as `profile_from_preferences` measured it until v3.99.1:
    against a fixed 65% keep rate. Kept so the change can be reported."""
    from pixcull.scoring.personalized import BASELINE_KEEP_RATE, MAX_THRESHOLD_SHIFT
    owner_keep = sum(e.decision == "keep" for e in train) / len(train)
    x = -(owner_keep - BASELINE_KEEP_RATE) * 0.5
    return round(max(-MAX_THRESHOLD_SHIFT, min(MAX_THRESHOLD_SHIFT, x)), 4)


def _confusion_line(label: str, pairs) -> str:
    """Where one arm's verdicts went over every held-out photograph."""
    n = len(pairs)
    agree = sum(t == p for t, p in pairs) / n
    culled = sum(p == "cull" for _t, p in pairs)
    hit = sum(t == p == "cull" for t, p in pairs)
    culls = sum(t == "cull" for t, _p in pairs)
    kept = sum(t == "cull" and p == "keep" for t, p in pairs)
    maybe = sum(t == "cull" and p == "maybe" for t, p in pairs)
    return (f"    {label:<34} agrees {agree:.1%}  culls {culled:<3} of which the owner "
            f"culled {hit}  owner's culls kept {kept}/{culls}, left at maybe {maybe}")


def product_leave_one_shoot_out(exs, rows, cfg) -> list[str]:
    """A learned profile in the product's decision, on a shoot it was not
    learned from: its threshold shift, and (since v3.99) the whole profile,
    the shift and the axis weights that tilt `fuse_score` in a run, where
    this run's score_final comes back from its per-dimension scores
    (`refuses`). Two shifts: the fixed-65% one `profile_from_preferences`
    used until v3.99.1 (the v3.98 finding), and the one it learns now,
    measured against the machine's own keep rate on the same frames."""
    from pixcull.scoring.personal_learn import axis_weights
    whole = refuses(rows, cfg)
    arms = [("none", "no shift"), ("fixed", "fixed 65% shift (before v3.99.1)"),
            ("fixed_w", "fixed 65% shift and axis weights"),
            ("learned", "learned shift (vs machine)"),
            ("learned_w", "learned shift and axis weights")]
    out, acc, pairs = [], defaultdict(list), defaultdict(list)
    for held in sorted({e.run_id for e in exs}):
        train = [e for e in exs if e.run_id != held]
        test = [e for e in exs if e.run_id == held]
        prof = learn_profile(train)
        w = axis_weights(prof) if whole else None
        fixed, learned = _fixed_shift(train), prof.keep_threshold_shift
        setting = {"none": (0.0, None), "fixed": (fixed, None), "fixed_w": (fixed, w),
                   "learned": (learned, None), "learned_w": (learned, w)}
        res, verdicts = {}, {}
        for k, (shift, aw) in setting.items():
            if k.endswith("_w") and not whole:
                continue
            ps = [(e.decision, _product_verdict(rows[e.key], shift, cfg, aw)) for e in test]
            pairs[k] += ps
            verdicts[k] = [p for _t, p in ps]
            res[k] = product_scores(ps)
            acc[k].append(res[k])
        fmt = lambda t: f"{t[0]:.3f}/{'—' if t[1] is None else format(t[1], '.0%')}"
        moved = "learned_w" if "learned_w" in verdicts else "learned"
        changed = sum(a != b for a, b in zip(verdicts["none"], verdicts[moved]))
        truth = [e.decision for e in test]

        def found(k):       # the owner's culls it culls, and their keeps it culls
            return (sum(t == p == "cull" for t, p in zip(truth, verdicts[k])),
                    sum(t == "keep" and p == "cull" for t, p in zip(truth, verdicts[k])),
                    sum(t == p for t, p in zip(truth, verdicts[k])) / len(test))
        (h0, k0, a0), (h1, k1, a1) = found("none"), found(moved)
        out.append(f"    held out {held:<26} none {fmt(res['none'])}   "
                   f"fixed 65% {fixed:+.3f}: {fmt(res['fixed'])}   "
                   f"learned {learned:+.3f}: {fmt(res['learned'])}")
        out.append(f"      the learned profile{' applied whole' if moved == 'learned_w' else ''} "
                   f"changes {changed}/{len(test)} verdicts; of the owner's "
                   f"{truth.count('cull')} culls it finds {h1} (none {h0}), culls {k1} "
                   f"frames they kept (none {k0}), agrees {a1:.1%} (none {a0:.1%})")
    head = []
    for k, label in arms:
        if not acc[k]:
            head.append(f"  mean, {label:<34} not measured: score_final does not "
                        "come back from this run's per-dimension scores")
            continue
        f1 = statistics.mean(v[0] for v in acc[k])
        crs = [v[1] for v in acc[k] if v[1] is not None]
        head.append(f"  mean, {label:<34} keep-F1 {f1:.3f}  cull recall "
                    f"{statistics.mean(crs):.1%}" if crs else "")
    head.append("  over every held-out photograph:")
    head += [_confusion_line(label, pairs[k]) for k, label in arms if pairs[k]]
    return head + ["  (keep-F1/cull recall per held-out shoot)"] + out


def by_vertical(exs, rows, redraws) -> list[str]:
    """v3.99 — `evaluate_by_vertical`, keyed two ways: by the genre of the
    shoot as the owner gave it, and by the scene label on each frame, which
    is what `gather_examples_from_runs` reads (`vertical` or else `scene`).
    Grouped by shoot where a vertical has two; then the stride it shipped
    with, which is memorisation, with its spread over redrawn orders."""
    out = []
    keyings = (("by genre", exs),
               ("by scene label", [dataclasses.replace(
                   e, vertical=str(rows[e.key].get("scene") or "")) for e in exs]))
    for label, xs in keyings:
        mix = Counter(e.vertical for e in xs)
        out.append(f"  {label}: " + ", ".join(f"{v} {n}" for v, n in mix.most_common()))
        ev = evaluate_by_vertical(xs)
        out += _vertical_lines(ev)
        flat = [dataclasses.replace(e, run_id="") for e in xs]
        ds = []
        for seed in range(redraws):
            ys = flat[:]
            random.Random(seed).shuffle(ys)
            r = evaluate_by_vertical(ys)
            if not r.get("refused"):
                ds.append(r["delta"])
        st = evaluate_by_vertical(flat)
        if not st.get("refused"):
            line = (f"    stride, shoots ignored (memorisation): pooled {st['pooled_f1']:.3f} "
                    f"per-vertical {st['per_vertical_f1']:.3f} Δ {st['delta']:+.3f}")
            if ds:
                line += (f"  | redrawn ×{len(ds)}: Δ {min(ds):+.3f}…{max(ds):+.3f}, "
                         f"mean {statistics.mean(ds):+.3f}")
            out.append(line)
    return out


def _vertical_lines(ev: dict) -> list[str]:
    if ev.get("refused"):
        return [f"    not measured: {ev['refused']}"]
    cr = ""
    if ev.get("pooled_cull_recall") is not None:
        cr = (f"  cull recall {ev['pooled_cull_recall']:.0%} → "
              f"{ev['per_vertical_cull_recall']:.0%}")
    out = [f"    {'held-out shoots' if ev['grouped'] else 'stride folds'} ×{ev['folds']}: "
           f"pooled {ev['pooled_f1']:.3f}  per-vertical {ev['per_vertical_f1']:.3f}  "
           f"Δ {ev['delta']:+.3f}{cr}"]
    if ev["grouped"]:
        # Folds here can be a handful of frames (a scene label one shoot
        # barely used), and the plain mean weighs them like a whole shoot.
        w = sum(d * n for d, n in zip(ev["fold_deltas"], ev["fold_n"])) / sum(ev["fold_n"])
        out[0] += f"  (weighted by frames: Δ {w:+.3f})"
        for (v, shoot), d, n in zip(ev["fold_groups"], ev["fold_deltas"], ev["fold_n"]):
            out.append(f"      held out {shoot:<24} ({v}) n={n:<4} Δ {d:+.3f}")
        if ev["verticals_unmeasured"]:
            out.append(f"      shot once, nothing to compare: {', '.join(ev['verticals_unmeasured'])}")
    return out


def vertical_confusion(exs) -> list[str]:
    """Where each arm's verdicts go on the held-out shoots of the genres shot
    more than once, summed: no profile, pooled, per genre, built the way
    `evaluate_by_vertical` builds them. "Of what it culls, the owner culled"
    beside the share of culls in those shoots says whether a profile that
    culls more is finding the culls or drawing them."""
    from pixcull.scoring.personal_learn import decide
    arms = ("no profile", "pooled", "per genre")
    tot = {a: Counter() for a in arms}
    for genre in sorted({e.vertical for e in exs}):
        same = [e for e in exs if e.vertical == genre]
        for held in sorted({e.run_id for e in same}):
            tv = [e for e in same if e.run_id != held]
            if not tv:
                continue
            test = [e for e in same if e.run_id == held]
            pooled = learn_profile([e for e in exs if e.run_id != held])
            per = learn_profile(tv) if len(tv) >= MIN_PER_VERTICAL else pooled
            for arm, prof in zip(arms, (None, pooled, per)):
                tot[arm].update((e.decision, decide(e.axes, profile=prof)) for e in test)
    if not any(tot.values()):
        return ["  not measured: no genre was shot more than once"]
    c0 = tot[arms[0]]
    n = sum(c0.values())
    culls = sum(v for (t, _p), v in c0.items() if t == "cull")
    out = [f"  held-out shoots of the genres shot more than once: {n} frames, "
           f"{culls} culled by the owner ({culls / n:.1%})"]
    for arm in arms:
        c = tot[arm]
        agree = sum(v for (t, p), v in c.items() if t == p) / n
        culled = sum(v for (_t, p), v in c.items() if p == "cull")
        hit = c[("cull", "cull")]
        out.append(f"    {arm:<11} agrees {agree:.1%}  culls {culled:<3} of which the owner "
                   f"culled {hit} ({hit / culled:.1%})" if culled else
                   f"    {arm:<11} agrees {agree:.1%}  culls nothing")
        out[-1] += f"  owner's culls kept {c[('cull', 'keep')]}/{culls}"
    return out


def product_by_vertical(exs, rows, cfg) -> list[str]:
    """v3.99 — the threshold shift per kind of shoot, in the product's
    decision, on a shoot it was not learned from. A kind with fewer than
    MIN_PER_VERTICAL frames in the training shoots gets no shift of its own
    and uses the pooled one, as `learn_profiles` would. Both formulas."""
    from pixcull.scoring.personal_learn import axis_weights
    keyings = {"pooled": lambda e: "",
               "per genre": lambda e: e.vertical,
               "per scene label": lambda e: str(rows[e.key].get("scene") or "")}
    # The shift alone, and the whole profile as run_pipeline applies it
    # (shift plus axis weights tilting the fusion), if this run's
    # score_final comes back from its per-dimension scores.
    variants = ("shift", "whole") if refuses(rows, cfg) else ("shift",)
    acc = defaultdict(list)
    changed = Counter()                  # verdicts unlike the pooled arm's
    per_shoot = []

    def learned(g):
        prof = learn_profile(g)
        return {"fixed 65%": _fixed_shift(g),
                "vs machine": _relative_shift(g, rows, cfg), "w": axis_weights(prof)}

    for held in sorted({e.run_id for e in exs}):
        train = [e for e in exs if e.run_id != held]
        test = [e for e in exs if e.run_id == held]
        pooled = learned(train)
        cells = []
        base = {}
        for arm, key_of in keyings.items():
            groups = defaultdict(list)
            for e in train:
                groups[key_of(e)].append(e)
            own = {k: learned(g) for k, g in groups.items()
                   if k and len(g) >= MIN_PER_VERTICAL}
            for variant in variants:
                for formula in ("fixed 65%", "vs machine"):
                    pairs = []
                    for e in test:
                        prof = own.get(key_of(e), pooled)
                        pairs.append((e.decision, _product_verdict(
                            rows[e.key], prof[formula], cfg,
                            prof["w"] if variant == "whole" else None)))
                    verdicts = [p for _t, p in pairs]
                    base.setdefault((variant, formula), verdicts)
                    changed[(variant, arm, formula)] += sum(
                        a != b for a, b in zip(base[(variant, formula)], verdicts))
                    res = product_scores(pairs)
                    acc[(variant, arm, formula)].append(res)
                    if variant == "shift":
                        cells.append(f"{res[0]:.3f}/{'—' if res[1] is None else format(res[1], '.0%')}")
            used = sum(key_of(e) in own for e in test)
            if arm != "pooled":
                cells.append(f"{used}/{len(test)} own")
        per_shoot.append(f"    held out {held:<24} " + "  ".join(cells))
    out = []
    for variant in variants:
        if variant == "whole":
            out.append("  the whole profile, shift and axis weights, as run_pipeline applies it:")
        for formula in ("fixed 65%", "vs machine"):
            for arm in keyings:
                v = acc[(variant, arm, formula)]
                crs = [x[1] for x in v if x[1] is not None]
                out.append((f"  {formula:<11} {arm:<16} keep-F1 {statistics.mean(x[0] for x in v):.3f}"
                            f"  cull recall {statistics.mean(crs):.1%}" if crs else "")
                           + ("" if arm == "pooled" else
                              f"  verdicts unlike pooled: {changed[(variant, arm, formula)]}"))
    if len(variants) == 1:
        out.append("  the whole profile: not measured, score_final does not come back "
                   "from this run's per-dimension scores")
    head = ("    (per held-out shoot: pooled 65%, pooled vs-machine, genre 65%, genre "
            "vs-machine, frames with their own, scene 65%, scene vs-machine, frames with their own)")
    return out + [head] + per_shoot


def score_saved_profile(path, exs, rows, cfg) -> list[str]:
    """A saved profile on every photograph, in the product's decision: its
    threshold shift, and its axis weights tilting the fusion when this run's
    score_final can be recomputed (v3.99). An equal-weight profile is a no-op
    in the fusion by construction (`fusion._personalize_weights`)."""
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
           f"axis weights {'equal (no effect on fusion)' if equal else 'not equal'}"]
    tilt = None if equal else w
    if tilt and not refuses(rows, cfg):
        out.append("    its axis weights not applied: score_final does not come back "
                   "from this run's per-dimension scores")
        tilt = None
    for label, s, aw in (("without it", 0.0, None), ("with it", prof.keep_threshold_shift, tilt)):
        verdicts = [_product_verdict(rows[e.key], s, cfg, aw) for e in exs]
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
    print("\none profile, or one per kind of shoot (v3.99), evaluate()'s decision:")
    print("\n".join(by_vertical(exs, rows, a.redraws)))
    print("\n".join(vertical_confusion(exs)))
    if len(by_shoot) >= 2:
        print("\none profile, or one per kind of shoot, in the product's decision:")
        print("\n".join(product_by_vertical(exs, rows, cfg)))
    if a.profile:
        print("\na saved profile, in the product's decision:")
        print("\n".join(score_saved_profile(a.profile, exs, rows, cfg)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
