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
    # v2.54.2 — float, because stratified samples carry inverse-probability
    # weights. The corpus is 89% keep, so a 40-row uniform sample expects
    # ~2.8 culls and the owner's returned zero scoreable ones. Sampling
    # each stratum evenly and weighting by (population / sampled) is the
    # only way to measure `cull` at a budget a human will actually review.
    tp: float = 0.0
    fp: float = 0.0
    fn: float = 0.0

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
    #: error string → count. "36 errored" without saying WHY is the kind
    #: of silence this whole module exists to remove: a truncation, an
    #: auth failure and a decode error need three different fixes.
    error_reasons: dict[str, int] = field(default_factory=dict)
    elapsed_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    rule: dict[str, Confusion] = field(default_factory=dict)
    vlm: dict[str, Confusion] = field(default_factory=dict)
    #: v2.54 — the third arm, and the reason this eval stopped being a
    #: yes/no question. `primary` lets M3 overrule the rule stack in both
    #: directions; `rescue` lets it only promote a frame the rules
    #: condemned, never condemn one they kept. The owner's 51 reviewed
    #: frames say those two powers have wildly different hit rates, so
    #: measuring only `primary` was measuring a mode nobody should ship.
    rescue: dict[str, Confusion] = field(default_factory=dict)
    #: v2.54 — HOW the evaluated rows were chosen. "all" is a census;
    #: "disagreements" means the rows were selected precisely where the
    #: two systems differed, which is a sample drawn where the rule stack
    #: is most likely to be wrong. A ranking computed on it flatters the
    #: model for the same structural reason the original label set
    #: flattered the rule. Recorded rather than remembered, because the
    #: first version of this bug cost ¥8 and half a day and this one
    #: produces a *more* convincing wrong answer.
    selection: str = "all"
    #: v2.54.2 — how many rows of each scored truth the sample actually
    #: contains, and how many rows each arm decided differently from the
    #: rule stack. Both exist because a macro-F1 hides the difference
    #: between "these modes tie" and "this sample never exercised them",
    #: and those need opposite responses. The owner's 40-row random
    #: sample contained ZERO `cull` labels and put every rescue-eligible
    #: row in the unscored `maybe` bucket, so `rescue` reported +0.0 —
    #: a tie it never played.
    truth_counts: dict[str, int] = field(default_factory=dict)
    arm_changes: dict[str, int] = field(default_factory=dict)
    #: v2.55.1 — rows whose input CSV carried no `flags` column at all.
    #: Hard culls are driven ENTIRELY by flags, so a scores file without
    #: that column runs the rule stack with half its inputs missing and
    #: reports the result as the rule stack's opinion. Measured on a
    #: 200-frame shoot: `cull` F1 0.000 against 95 real cull labels, and
    #: `rescue` never fired because no hard cull ever triggered. Nothing
    #: errored; the table just said the rules never cull.
    n_missing_flags_column: int = 0
    #: v2.55.2 — per scored class: how many rows carrying that label the
    #: rule stack decided DIFFERENTLY. Zero means the rule's RECALL on
    #: that class is 1.000 by construction (and its F1 too whenever it
    #: also has no false positives there, which is the usual case when
    #: the labels were copied from it).
    #:
    #: The global check (`n_label_disagreements == 0`) cannot see this. On
    #: a 200-frame shoot the labels disagreed with the rule on 20% of rows
    #: — healthy-looking — while all 95 `cull` labels were the rule's own
    #: culls, exactly. `cull` F1 came out 1.000 and the noise in the
    #: `keep` class hid it. The class carrying the headline was the
    #: circular one.
    class_disagreements: dict[str, int] = field(default_factory=dict)
    #: v2.55 — (truth, rule, rescue, primary, weight) per scoreable row,
    #: kept so the headline delta can be resampled. A macro-F1 computed
    #: on 45 rows with 7 culls prints to three decimals and looks like a
    #: measurement; whether it survives two of those rows flipping is a
    #: different question, and the only one that matters before changing
    #: a default.
    outcomes: list[tuple[str, str, str, str, float]] = field(
        default_factory=list)
    #: arm → (low, high) percentile CI in macro-F1 points, once
    #: ``compute_cis()`` has run. The verdict refuses to recommend a mode
    #: whose interval contains zero: a tool that says SHIP on a number
    #: its own interval calls noise is worse than one that says nothing.
    ci: dict[str, tuple[float, float]] = field(default_factory=dict)
    disagreements: list[Disagreement] = field(default_factory=list)
    by_scene: dict[str, dict[str, float]] = field(default_factory=dict)

    def compute_cis(self, rounds: int = 2000) -> None:
        """Fill ``ci`` so ``verdict`` can refuse an indistinguishable win."""
        for arm in ("rescue", "vlm"):
            _, lo, hi = bootstrap_delta(self, arm, rounds=rounds)
            self.ci["primary" if arm == "vlm" else arm] = (lo, hi)

    @property
    def rule_macro_f1(self) -> float:
        return _macro(self.rule)

    @property
    def vlm_macro_f1(self) -> float:
        return _macro(self.vlm)

    @property
    def rescue_macro_f1(self) -> float:
        return _macro(self.rescue)

    @property
    def n_effective(self) -> int:
        """Rows that can make anyone right or wrong (`maybe` cannot)."""
        return sum(self.truth_counts.values())

    @property
    def unmeasurable(self) -> list[str]:
        """Scored labels with no ground-truth examples in this sample.

        Their F1 is 0.000 for every arm by construction, which drags the
        macro down uniformly and reads as three mediocre modes rather
        than as a question the sample cannot answer.
        """
        return [x for x in _SCORED if not self.truth_counts.get(x)]

    @property
    def unexercised(self) -> list[str]:
        """Arms that never changed a scored row, so were never tested."""
        return [a for a in ("rescue", "primary")
                if not self.arm_changes.get(a)]

    @property
    def best_mode(self) -> str:
        """Which `vlm_authority` the measurement actually supports.

        A tie goes to `off`: shipping a cloud call that buys nothing is
        worse than not shipping it, because it costs money and adds a
        dependency that can fail.
        """
        scores = {"off": self.rule_macro_f1,
                  "rescue": self.rescue_macro_f1,
                  "primary": self.vlm_macro_f1}
        best = max(scores, key=lambda k: scores[k])
        # 2 points is the noise floor this module already uses.
        if scores[best] - scores["off"] < 0.02:
            return "off"
        return best

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
        # v2.55.1 — before anything else: did the rule stack get its
        # inputs? Hard culls come only from `flags`, so a scores file
        # without that column cannot cull for the right reasons and the
        # comparison is against a crippled opponent, not the rule stack.
        if self.n_missing_flags_column:
            return (f"INVALID INPUT — the scores file has no `flags` "
                    f"column, so no hard cull can fire on any of "
                    f"{self.n_missing_flags_column} rows and the rule "
                    f"stack is being measured with its detectors removed. "
                    f"Re-run `pixcull run` on these photos and evaluate "
                    f"the resulting scores.csv, not a label sheet.")
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
        # v2.55.2 — per class, because a global rate hides this.
        circular = [c for c in _SCORED
                    if self.truth_counts.get(c)
                    and not self.class_disagreements.get(c)]
        if circular and self.n_label_disagreements:
            cs = "`/`".join(circular)
            return (f"CIRCULAR ON `{cs}` — the rule stack decided `{cs}` "
                    f"on every single row labelled `{cs}`, so its recall "
                    f"there is 1.000 by construction no matter how good "
                    f"either system is (F1 too, whenever it also has no "
                    f"false positives — which is what happened). Overall "
                    f"disagreement is {self.n_label_disagreements}/"
                    f"{self.n_scored}, which looks healthy and is not: the "
                    f"noise lives in the other class. These labels came "
                    f"from the rule stack.")
        if self.n_label_disagreements == 0:
            return ("INVALID — the label set never disagrees with the rule "
                    "stack, so the rule scores 1.000 by construction and "
                    "anything different scores worse. This measures "
                    "agreement-with-the-rule, not correctness. Label a set "
                    "where you overruled the model, then re-run.")
        # v2.54 — the question is no longer "M3 or not" but "which
        # authority mode". Reporting only `primary` answered a question
        # the product does not have to ask: a model can be bad at
        # overruling a keep and still be excellent at rescuing a cull,
        # and those are separate switches.
        d_pri = (self.vlm_macro_f1 - self.rule_macro_f1) * 100
        d_res = (self.rescue_macro_f1 - self.rule_macro_f1) * 100
        # v2.54.2 — before ranking anything, check the sample can rank.
        #
        # A label with no ground-truth examples scores 0.000 for every
        # arm, and an arm that never changed a scored row reports a
        # perfect tie. Both print as an ordinary number. The owner's
        # 40-row random sample hit both at once: zero `cull` labels, and
        # every rescue-eligible row landed on `maybe`, which is excluded
        # from scoring. `rescue +0.0` meant "never played", not "no gain".
        if self.unmeasurable:
            return (f"CANNOT RANK — this sample has no `"
                    f"{'`/`'.join(self.unmeasurable)}` ground truth, so "
                    f"that F1 is 0.000 for every mode by construction and "
                    f"the macro is halved for all of them equally. "
                    f"{self.n_effective} of {self.n_scored} rows are "
                    f"scoreable at all (`maybe` is excluded). Label a "
                    f"sample that contains both outcomes.")
        if self.unexercised:
            return (f"NOT MEASURED — `{'`, `'.join(self.unexercised)}` "
                    f"changed no scoreable row in this sample, so the "
                    f"reported tie is a mode that never ran. Sample rows "
                    f"where it would act.")
        # A sample drawn where the two systems disagreed cannot rank
        # them. Every row in it is a row the rule stack got wrong often
        # enough to argue about; the rule's score there is a floor, not
        # an estimate. This is the same defect as the circular label set,
        # wearing selection bias instead of label leakage — and it points
        # the other way, so believing it ships the opposite mistake.
        if self.selection == "disagreements":
            return (f"NOT A RANKING — these rows were selected because the "
                    f"two systems disagreed, so the rule stack is measured "
                    f"only where it is weakest (primary {d_pri:+.1f}, "
                    f"rescue {d_res:+.1f}). Label a RANDOM sample to get a "
                    f"number that can decide the default.")
        best = self.best_mode
        # v2.55 — a point estimate on 45 rows prints to three decimals and
        # reads as a measurement. Resampled, this one was +13.6 with a 95%
        # interval of [-12.0, +41.4]: the sample cannot tell the mode
        # apart from no change at all, and the line above it still said
        # SHIP. Changing a product default on that is exactly the mistake
        # the circular label set already caused once.
        if best != "off" and best in self.ci:
            lo, hi = self.ci[best]
            if lo <= 0 <= hi:
                d = {"rescue": d_res, "primary": d_pri}[best]
                return (f"NOT DISTINGUISHABLE — `{best}` scores {d:+.1f} "
                        f"macro-F1 points, but resampling gives 95% CI "
                        f"[{lo:+.1f}, {hi:+.1f}], which contains zero. "
                        f"{self.n_effective} scoreable rows is too few to "
                        f"move a default. Label more of the rare class.")
        if best == "off":
            return (f"KEEP M3 OPT-IN — neither mode clears the noise floor "
                    f"(primary {d_pri:+.1f}, rescue {d_res:+.1f} macro-F1 "
                    f"points on {self.n_scored} rows).")
        if best == "rescue":
            return (f"SHIP `vlm_authority=rescue` — rescue {d_res:+.1f} "
                    f"macro-F1 points, while primary is {d_pri:+.1f}. M3 "
                    f"earns the power to overturn a cull, not the power to "
                    f"overturn a keep.")
        return (f"SHIP `vlm_authority=primary` — {d_pri:+.1f} macro-F1 "
                f"points (rescue {d_res:+.1f}). M3 is better than the rule "
                f"stack in both directions.")


def _macro(cm: dict[str, Confusion]) -> float:
    vals = [cm[k].f1 for k in _SCORED if k in cm]
    return sum(vals) / len(vals) if vals else 0.0


def _tally(cm: dict[str, Confusion], truth: str, pred: str,
           w: float = 1.0) -> None:
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
            c.tp += w
        elif pred == label and truth != label:
            c.fp += w
        elif pred != label and truth == label:
            c.fn += w


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
    only: set[str] | None = None,
    selection: str = "all",
    row_weights: dict[str, float] | None = None,
) -> EvalResult:
    """Score every labelled row three ways — off / rescue / primary.

    ``rows`` are score records (a run's ``scores.csv``, or the label
    sheet itself when it carries the detector metrics).  Rows without a
    human label are skipped: an unlabelled row cannot make anyone right
    or wrong.

    ``row_weights`` maps filename → inverse-probability weight, for a
    stratified sample.  The corpus is ~89% ``keep``, so a uniform 40-row
    sample expects fewer than three ``cull`` rows and the owner's
    returned none that were scoreable; sampling each stratum evenly and
    weighting by (population / sampled) measures both outcomes at a
    budget a person will actually sit through, and stays unbiased for
    the population rather than for the sample.

    ``only`` restricts the run to a set of filenames.  v2.54 — this
    exists because the circularity that invalidated the first
    measurement does not disappear when *some* labels become
    independent, it only shrinks.  On the owner's set, 51 of 408 rows
    carry a reviewed label and the remaining 357 still hold the rule
    stack's own decision; every row a model changes there is scored as
    an error BY CONSTRUCTION.  Passing the reviewed filenames gives the
    one comparison on this data that is not partly rigged.
    """
    res = EvalResult(selection=selection)
    # "flags" absent as a COLUMN is the failure; an empty value is a
    # legitimate "this frame tripped nothing".  Distinguishing the two is
    # the whole point — the first means the detectors never ran.
    _seen_flag_col = False
    todo = [r for r in rows
            if (r.get("filename") or "").strip() in labels
            and (only is None or (r.get("filename") or "").strip() in only)]
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
        if "flags" in row:
            _seen_flag_col = True
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
            why = str(getattr(verdict, "error", "") or "no verdict returned")
            # Collapse to the shape of the failure, not its instance —
            # 36 rows with 36 distinct filenames in the message is a wall,
            # 36 rows with one reason is a finding.
            key = why.split(" — ")[0].split(":")[0].strip()[:60]
            res.error_reasons[key] = res.error_reasons.get(key, 0) + 1
            ew = (row_weights or {}).get(fn, 1.0)
            _tally(res.rule, truth, rule_dec.value, ew)
            # A row with no verdict is not a row the model got wrong — in
            # production every authority mode falls back to the rule stack
            # here. Tallying rule into `rule` alone gave the VLM arms fewer
            # rows than the rule arm and quietly compared two different
            # populations; feed all three the same outcome instead.
            _tally(res.vlm, truth, rule_dec.value, ew)
            _tally(res.rescue, truth, rule_dec.value, ew)
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
        rescue_dec, _ = decide(
            final, flags, config, strictness,  # type: ignore[arg-type]
            scene=scene, vertical=vertical,
            vlm_label=getattr(verdict, "overall_label", None),
            vlm_axes=axes, vlm_authority="rescue")

        res.n_scored += 1
        if any("vlm_incoherent" in r for r in reasons):
            res.n_incoherent += 1
        overrode = any("vlm_kept_despite" in r for r in reasons)
        if overrode:
            res.n_overrides += 1

        if rule_dec.value != truth:
            res.n_label_disagreements += 1
        if truth in _SCORED:
            res.class_disagreements[truth] = (
                res.class_disagreements.get(truth, 0)
                + (1 if rule_dec.value != truth else 0))
        w = (row_weights or {}).get(fn, 1.0)
        _tally(res.rule, truth, rule_dec.value, w)
        _tally(res.vlm, truth, vlm_dec.value, w)
        _tally(res.rescue, truth, rescue_dec.value, w)
        # Counted on SCOREABLE rows only, which is the whole point: an
        # arm that only ever acts on `maybe` rows has changed nothing
        # the metric can see, and must not be reported as a tie.
        if truth in _SCORED:
            res.truth_counts[truth] = res.truth_counts.get(truth, 0) + 1
            if vlm_dec.value != rule_dec.value:
                res.arm_changes["primary"] = res.arm_changes.get(
                    "primary", 0) + 1
            if rescue_dec.value != rule_dec.value:
                res.arm_changes["rescue"] = res.arm_changes.get(
                    "rescue", 0) + 1
        if truth in _SCORED:
            res.outcomes.append((truth, rule_dec.value, rescue_dec.value,
                                 vlm_dec.value, w))
        scene_hits.setdefault(scene or "—", []).append(
            (truth, rule_dec.value, vlm_dec.value))

        if rule_dec.value != vlm_dec.value:
            res.disagreements.append(Disagreement(
                filename=fn, truth=truth, rule=rule_dec.value,
                vlm=vlm_dec.value, scene=scene, flags=",".join(flags),
                rationale=str(getattr(verdict, "overall_rationale", ""))[:160],
                overrode_hard_cull=overrode))

    if not _seen_flag_col:
        res.n_missing_flags_column = res.n_rows
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
              "Three authority modes on the same rows. `off` is the rule "
              "stack alone; `rescue` lets M3 overturn a cull but never a "
              "keep; `primary` lets it overturn either.", "",
              "| | off (rule) | rescue | primary |",
              "|---|---|---|---|"]
    for label in _SCORED:
        r = res.rule.get(label, Confusion(label))
        s = res.rescue.get(label, Confusion(label))
        v = res.vlm.get(label, Confusion(label))
        lines.append(f"| **{label}** F1 | {r.f1:.3f} | {s.f1:.3f} | "
                     f"{v.f1:.3f} |")
    lines.append(
        f"| **macro** | **{res.rule_macro_f1:.3f}** | "
        f"**{res.rescue_macro_f1:.3f}** | **{res.vlm_macro_f1:.3f}** |")
    lines.append("")
    lines.append(f"**Supported default: `vlm_authority={res.best_mode}`**")

    if res.error_reasons:
        lines += ["", f"## Why {res.n_errors} rows produced nothing", "",
                  "| reason | rows |", "|---|---|"]
        for why, n in sorted(res.error_reasons.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {why} | {n} |")
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


def bootstrap_delta(res: EvalResult, arm: str = "vlm", *,
                    rounds: int = 2000, seed: int = 20260816
                    ) -> tuple[float, float, float]:
    """Percentile CI for (arm macro-F1 − rule macro-F1), in points.

    Resamples the scored rows with replacement.  The point estimate here
    has been wrong three times in this project's history — first from
    circular labels, then from a disagreement-selected sample, then from
    a sample with no ``cull`` ground truth at all — and each time it was
    a single confident number with nothing to say about its own
    stability.  A +13.6 that spans zero under resampling is not a reason
    to change a default; a +13.6 that does not is.

    Deterministic seed: a confidence interval that moves every time you
    run it invites re-rolling until it agrees with you.
    """
    import random

    rows = res.outcomes
    if not rows:
        return (0.0, 0.0, 0.0)
    idx = {"rule": 1, "rescue": 2, "vlm": 3}[arm]

    def _delta(sample) -> float:
        a: dict[str, Confusion] = {}
        b: dict[str, Confusion] = {}
        for truth, *preds, w in sample:
            _tally(a, truth, preds[0], w)
            _tally(b, truth, preds[idx - 1], w)
        return (_macro(b) - _macro(a)) * 100

    rng = random.Random(seed)
    n = len(rows)
    deltas = sorted(_delta([rows[rng.randrange(n)] for _ in range(n)])
                    for _ in range(rounds))
    lo = deltas[int(0.025 * rounds)]
    hi = deltas[min(rounds - 1, int(0.975 * rounds))]
    return (_delta(rows), lo, hi)
