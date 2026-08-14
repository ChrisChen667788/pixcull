"""v2.49 — does the cloud judge actually decide better than the rules?

Nobody knows.  v2.48 built a judge that *can* decide; it produced no
evidence that it decides *well*.  Flipping the default — and rewriting
47 public promises to match — on an unmeasured assumption would be a
bet, and the thing being bet is the sentence PyPI users read before they
install.

This module answers the question against the owner's 608-row corrected
label set, and it is deliberately built so the answer is allowed to be
"no".

What it measures
----------------
* **Agreement with the human**, per decision, for the rule stack and for
  M3 — precision / recall / F1 on ``keep`` and ``cull`` separately,
  because they fail differently.  A missed keep is a lost photo; a
  missed cull is thirty seconds of the photographer's time.
* **Where they disagree**, listed by filename, so the owner can look at
  the actual frames rather than at a number.
* **The overrides**: every row where M3 kept something the rule stack
  hard-culled.  This is the entire premise of evidence fusion — if these
  are mostly wrong, the premise is wrong.
* **The incoherence guard's real firing rate.**  Below ~1% it is dead
  code; above ~10% the prompt is bad.  Either way it is a finding.
* **Cost and wall-clock**, measured rather than estimated.

The eval never mutates ``decision`` anywhere; it recomputes into its own
columns.  Running it against a real run directory has to be safe.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from pixcull.scoring.decision import Decision, decide

#: Labels we score against. ``maybe`` is deliberately excluded from the
#: headline F1: the human used it to mean "I am not sure", so counting a
#: model as wrong for disagreeing with an explicit shrug measures
#: nothing. It is still reported separately.
_SCORED = ("keep", "cull")


@dataclass
class Confusion:
    """One label's confusion counts against the human's verdict."""

    label: str
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 0.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self) -> dict[str, float | int | str]:
        return {"label": self.label, "tp": self.tp, "fp": self.fp,
                "fn": self.fn, "precision": round(self.precision, 4),
                "recall": round(self.recall, 4), "f1": round(self.f1, 4)}


@dataclass
class Disagreement:
    filename: str
    truth: str
    rule: str
    vlm: str
    scene: str = ""
    flags: str = ""
    rationale: str = ""
    overrode_hard_cull: bool = False


@dataclass
class EvalResult:
    n_rows: int = 0
    n_scored: int = 0            # rows with a usable verdict
    n_errors: int = 0
    n_incoherent: int = 0
    n_overrides: int = 0
    #: rows where the rule stack and the human label already disagreed.
    #: Zero means the labels cannot adjudicate between two systems.
    n_label_disagreements: int = 0
    elapsed_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    rule: dict[str, Confusion] = field(default_factory=dict)
    vlm: dict[str, Confusion] = field(default_factory=dict)
    disagreements: list[Disagreement] = field(default_factory=list)
    by_scene: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def rule_macro_f1(self) -> float:
        return _macro(self.rule)

    @property
    def vlm_macro_f1(self) -> float:
        return _macro(self.vlm)

    @property
    def verdict(self) -> str:
        """The sentence the owner actually needs.

        Deliberately blunt, and deliberately willing to say no. A margin
        under 2 points on 608 rows is noise, not an improvement, and
        acting on noise here means rewriting the product's public
        promises for nothing.
        """
        if not self.n_scored:
            return ("NO DATA — every call failed. This is a configuration "
                    "problem; run `pixcull m3 doctor`.")
        # v2.49.3 — the labels have to be able to disagree with the rule
        # stack, or this comparison is circular.
        #
        # Found the expensive way. training_combined.csv's `manual_label`
        # is byte-identical to the rule stack's own `decision` on all 408
        # rows — the owner reviewed the sheet and endorsed every decision
        # as-is, which is a real review but not an independent judgement.
        # The rule stack therefore scores exactly 1.000 BY CONSTRUCTION,
        # and any model that differs at all is guaranteed to look worse.
        # The run reported "M3 WORSE by 63.9 points" and that number
        # measured disagreement-with-the-rule, not correctness. ¥8 and
        # twenty minutes to learn it.
        if self.n_label_disagreements == 0:
            return ("INVALID — the label set never disagrees with the rule "
                    "stack, so the rule scores 1.000 by construction and "
                    "anything different scores worse. This measures "
                    "agreement-with-the-rule, not correctness. Label a set "
                    "where you overruled the model, then re-run.")
        delta = (self.vlm_macro_f1 - self.rule_macro_f1) * 100
        if delta >= 2.0:
            return (f"M3 BETTER by {delta:+.1f} macro-F1 points — the "
                    f"positioning rewrite is justified.")
        if delta <= -2.0:
            return (f"M3 WORSE by {delta:+.1f} macro-F1 points — do NOT "
                    f"flip the default. Keep M3 opt-in.")
        return (f"NO MEANINGFUL DIFFERENCE ({delta:+.1f} macro-F1 points). "
                f"On {self.n_scored} rows this is noise. Flipping the "
                f"default buys nothing and costs the local-first claim.")


def _macro(cm: dict[str, Confusion]) -> float:
    vals = [cm[k].f1 for k in _SCORED if k in cm]
    return sum(vals) / len(vals) if vals else 0.0


def _tally(cm: dict[str, Confusion], truth: str, pred: str) -> None:
    # A row the human marked `maybe` cannot make anyone right or wrong.
    # Counting a "keep" prediction against it as a false positive would
    # penalise the model for disagreeing with an explicit shrug — and
    # with 16 of the 608 rows labelled that way it moved the number
    # enough to matter.
    if truth not in _SCORED:
        return
    for label in _SCORED:
        c = cm.setdefault(label, Confusion(label))
        if pred == label and truth == label:
            c.tp += 1
        elif pred == label and truth != label:
            c.fp += 1
        elif pred != label and truth == label:
            c.fn += 1


def load_labels(path: Path) -> dict[str, dict[str, str]]:
    """filename → row, from the owner's corrected label sheet.

    ``utf-8-sig``: the sheet round-trips through Excel and carries a BOM,
    which silently renames the first column to ``\\ufefffilename`` and
    makes every lookup miss.
    """
    out: dict[str, dict[str, str]] = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            fn = (row.get("filename") or "").strip()
            label = (row.get("manual_label") or "").strip().lower()
            if fn and label:
                out[fn] = {**row, "manual_label": label}
    return out


def _flags_of(row: dict[str, Any]) -> list[str]:
    raw = row.get("flags")
    if isinstance(raw, str):
        return [f for f in raw.replace("|", ",").split(",") if f.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(f) for f in raw]
    return []


def evaluate(
    rows: Iterable[dict[str, Any]],
    labels: dict[str, dict[str, str]],
    judge: Any,
    config: Any,
    *,
    strictness: str = "standard",
    vertical: str | None = None,
    limit: int | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    workers: int = 8,
) -> EvalResult:
    """Score every labelled row twice — rule stack, then M3 — and compare.

    ``rows`` are score records (a run's ``scores.csv``, or the label
    sheet itself when it carries the detector metrics).  Rows without a
    human label are skipped: an unlabelled row cannot make anyone right
    or wrong.
    """
    res = EvalResult()
    todo = [r for r in rows
            if (r.get("filename") or "").strip() in labels]
    if limit:
        todo = todo[:limit]
    res.n_rows = len(todo)
    scene_hits: dict[str, list[tuple[str, str, str]]] = {}

    t0 = time.time()

    def _judge_one(row: dict):
        """The network part, and only the network part.

        v2.49.2 — this loop was serial. Measured on the real set: ~37 s
        per photo (M3 is a reasoning model and thinks before answering),
        so 408 rows would have taken 4.2 hours and the owner would
        reasonably have killed it. Tallying stays on the caller's thread:
        Confusion counters and the disagreement list are shared state, and
        a race there produces a plausible-looking wrong F1 — the exact
        failure this eval exists to rule out.
        """
        img = row.get("path")
        if img and Path(str(img)).exists():
            return judge.score(Path(str(img)),
                               scene=str(row.get("scene") or ""), row=row)
        if hasattr(judge, "score_row"):
            return judge.score_row(row)      # test doubles, dry runs
        return None

    verdicts: dict[int, Any] = {}
    if todo and workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_judge_one, r): i for i, r in enumerate(todo)}
            done = 0
            for fut in as_completed(futs):
                i = futs[fut]
                try:
                    verdicts[i] = fut.result()
                except Exception:  # noqa: BLE001
                    verdicts[i] = None
                done += 1
                if progress is not None:
                    progress(done, len(todo),
                             str(todo[i].get("filename", "")))

    for n, row in enumerate(todo, 1):
        fn = str(row.get("filename", "")).strip()
        truth = labels[fn]["manual_label"]
        scene = str(row.get("scene") or "")
        flags = _flags_of(row)
        try:
            final = float(row.get("score_final") or 0.0)
        except (TypeError, ValueError):
            final = 0.0

        rule_dec, _ = decide(final, flags, config, strictness,  # type: ignore[arg-type]
                             scene=scene, vertical=vertical)

        verdict = (verdicts.get(n - 1) if verdicts
                   else _judge_one(row))

        if verdict is None or getattr(verdict, "error", None):
            res.n_errors += 1
            _tally(res.rule, truth, rule_dec.value)
            continue

        usage = getattr(verdict, "usage", None)
        if usage:
            res.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            res.completion_tokens += int(
                getattr(usage, "completion_tokens", 0) or 0)

        axes = {k: a.stars for k, a in (getattr(verdict, "axes", {}) or {}).items()}
        vlm_dec, reasons = decide(
            final, flags, config, strictness,  # type: ignore[arg-type]
            scene=scene, vertical=vertical,
            vlm_label=getattr(verdict, "overall_label", None),
            vlm_axes=axes, vlm_authority="primary")

        res.n_scored += 1
        if any("vlm_incoherent" in r for r in reasons):
            res.n_incoherent += 1
        overrode = any("vlm_kept_despite" in r for r in reasons)
        if overrode:
            res.n_overrides += 1

        if rule_dec.value != truth:
            res.n_label_disagreements += 1
        _tally(res.rule, truth, rule_dec.value)
        _tally(res.vlm, truth, vlm_dec.value)
        scene_hits.setdefault(scene or "—", []).append(
            (truth, rule_dec.value, vlm_dec.value))

        if rule_dec.value != vlm_dec.value:
            res.disagreements.append(Disagreement(
                filename=fn, truth=truth, rule=rule_dec.value,
                vlm=vlm_dec.value, scene=scene, flags=",".join(flags),
                rationale=str(getattr(verdict, "overall_rationale", ""))[:160],
                overrode_hard_cull=overrode))

    res.elapsed_s = time.time() - t0

    for scene, hits in scene_hits.items():
        rc: dict[str, Confusion] = {}
        vc: dict[str, Confusion] = {}
        for truth, r, v in hits:
            _tally(rc, truth, r)
            _tally(vc, truth, v)
        res.by_scene[scene] = {
            "n": len(hits),
            "rule_f1": round(_macro(rc), 4),
            "vlm_f1": round(_macro(vc), 4),
            "delta": round((_macro(vc) - _macro(rc)) * 100, 1),
        }
    return res


def estimated_cost_yuan(res: EvalResult) -> float:
    from pixcull.llm_budget import estimate_cost
    return estimate_cost("minimax-m3", res.prompt_tokens,
                         res.completion_tokens)


def render_report(res: EvalResult, *, labels_path: str = "",
                  model: str = "minimax-m3") -> str:
    """A Markdown report whose headline is the decision, not the data."""
    lines: list[str] = [
        "# M3 vs the rule stack — measured",
        "",
        f"**{res.verdict}**",
        "",
        f"- rows evaluated: **{res.n_scored}** "
        f"(of {res.n_rows} labelled; {res.n_errors} errored)",
        f"- model: `{model}`",
        f"- wall-clock: {res.elapsed_s:.0f}s",
    ]
    if res.prompt_tokens:
        lines.append(
            f"- tokens: {res.prompt_tokens:,} in / "
            f"{res.completion_tokens:,} out → "
            f"**¥{estimated_cost_yuan(res):.2f}** "
            f"(¥{estimated_cost_yuan(res) / max(1, res.n_scored) * 3000:.2f} "
            f"per 3000-photo wedding)")
    if labels_path:
        lines.append(f"- labels: `{labels_path}`")
    if res.n_scored and not res.n_label_disagreements:
        lines += ["", "> **Read no further for a ranking.** The rule stack "
                  "and the label set agree on every single row, so the "
                  "table below shows the rule at a perfect 1.000 because "
                  "it was scored against its own answers. The M3 column is "
                  "a disagreement rate, not an error rate.", ""]
    lines += ["", "## Agreement with the human", "",
              "| | rule P | rule R | rule F1 | M3 P | M3 R | M3 F1 |",
              "|---|---|---|---|---|---|---|"]
    for label in _SCORED:
        r = res.rule.get(label, Confusion(label))
        v = res.vlm.get(label, Confusion(label))
        lines.append(
            f"| **{label}** | {r.precision:.3f} | {r.recall:.3f} | "
            f"{r.f1:.3f} | {v.precision:.3f} | {v.recall:.3f} | {v.f1:.3f} |")
    lines.append(
        f"| **macro** | | | **{res.rule_macro_f1:.3f}** | | | "
        f"**{res.vlm_macro_f1:.3f}** |")

    lines += ["", "## The guard rails", "",
              f"- `vlm_incoherent` fired **{res.n_incoherent}** times "
              f"({100 * res.n_incoherent / max(1, res.n_scored):.1f}%) — "
              + ("below 1% suggests dead code"
                 if res.n_incoherent / max(1, res.n_scored) < 0.01
                 else "above 10% suggests a bad prompt"
                 if res.n_incoherent / max(1, res.n_scored) > 0.10
                 else "a plausible rate"),
              f"- M3 overrode a hard-cull flag **{res.n_overrides}** times. "
              f"**These need eyes on them** — evidence fusion stands or "
              f"falls on whether these overrides are right."]

    if res.by_scene:
        lines += ["", "## By scene", "",
                  "| scene | n | rule F1 | M3 F1 | Δ |", "|---|---|---|---|---|"]
        for scene, d in sorted(res.by_scene.items(),
                               key=lambda kv: -kv[1]["n"]):
            lines.append(f"| {scene} | {d['n']} | {d['rule_f1']:.3f} | "
                         f"{d['vlm_f1']:.3f} | {d['delta']:+.1f} |")

    if res.disagreements:
        lines += ["", f"## Disagreements ({len(res.disagreements)})", "",
                  "| file | human | rule | M3 | override | why M3 said so |",
                  "|---|---|---|---|---|---|"]
        for d in res.disagreements[:200]:
            who = ("✅ rule" if d.rule == d.truth else
                   "✅ M3" if d.vlm == d.truth else "✗ both")
            lines.append(
                f"| `{d.filename}` | {d.truth} | {d.rule} | {d.vlm} | "
                f"{'⚠️' if d.overrode_hard_cull else ''} {who} | "
                f"{d.rationale.replace('|', '/')} |")
        if len(res.disagreements) > 200:
            lines.append(f"\n_…and {len(res.disagreements) - 200} more "
                         f"(truncated; full list in the JSON sidecar)._")
    return "\n".join(lines) + "\n"
