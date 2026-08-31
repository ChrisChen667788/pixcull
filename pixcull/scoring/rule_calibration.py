"""v2.68 — recalibrate the rule stack against blind labels, honestly.

The evidence A/B (v2.67) settled that the judge is the strong half.  The
consequence nobody had costed is that **the rule stack is now the weak
half**, and it is the whole product for anyone running ``--vlm-mode
off`` — a documented, supported, privacy-motivated mode.

Measured alone on 493 blind frames it scores macro-F1 0.321, against the
judge's 0.695.  Its single worst behaviour is ``flag ⇒ cull``: dropping
that one rule is worth +15.5 points on its own, which is not surprising
once you have the number — the detector flags carry **0.9x lift**
against this photographer's culls, i.e. worse than chance.  The stack
auto-deletes on a signal anti-correlated with the thing it deletes for.

Why this module exists rather than a threshold sweep in a notebook
======================================================================

A sweep that picks the best thresholds on the frames it then reports on
is measuring a fit, not a system.  This project has produced four
circular datasets already and each one looked like a result.  So:

* **Fitting and scoring never see the same row.**  K-fold, thresholds
  fitted on the training folds, every row predicted exactly once by a
  model that never saw it, and the reported number computed over those
  pooled out-of-fold predictions.
* **The real ``decide()`` is what gets calibrated.**  Not a
  reimplementation of it.  A tuned model of the product is not the
  product, and the difference shows up exactly where it costs most —
  in the scene exemptions and vertical policies a reimplementation
  would quietly drop.
* **Refusals are results.**  A fold with no cull positives cannot score
  recall; a grid whose winner does not beat the shipped configuration
  on held-out data means nothing ships.  Both say so out loud rather
  than returning a number.

``flags_hard_cull=False`` is expressed by passing ``flags=[]`` into
``decide()``.  That is equivalent because ``flags`` reaches exactly two
places there — the ``triggered`` set, and the cosmetic ``rule_reasons``
strings — and ``test_flags_only_reach_the_hard_cull_path`` is the guard
that keeps it equivalent.  If a future change makes a flag move the
score, this module would silently start calibrating something else.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace as _dc_replace
from typing import Iterable, Sequence

from pixcull.scoring.decision import decide
from pixcull.scoring.vlm_eval import _macro, _tally

#: Fitting below this many cull positives in a training fold is fitting
#: noise.  Chosen before looking at the blind set's split, so it cannot
#: have been picked to make a fold pass.
_MIN_CULL_PER_FOLD = 3


@dataclass(frozen=True)
class RuleThresholds:
    """The rule stack's two score cut-points, plus whether flags veto.

    Scores are on the 0–10 scale the config uses, not the 0–1 scale
    ``decide()`` compares against, so that a fitted value can be written
    straight into ``fusion.strictness_presets`` without a conversion
    step somebody will eventually get wrong.
    """

    keep_min_score: float
    cull_max_score: float
    #: What a hard-cull flag does.  Three values, not a boolean, because
    #: the boolean framed the question wrongly: the measurement says the
    #: flags should not *delete*, and says nothing against them asking
    #: for a second look.
    #:
    #:   "cull"   — today's behaviour: a flag deletes the photograph.
    #:   "maybe"  — a flag demotes a KEEP to MAYBE.  Same attention, no
    #:              destruction.
    #:   "ignore" — the flag changes nothing.
    flags_policy: str = "cull"

    @property
    def flags_hard_cull(self) -> bool:
        return self.flags_policy == "cull"

    def __post_init__(self) -> None:
        if self.flags_policy not in ("cull", "maybe", "ignore"):
            raise ValueError(f"unknown flags_policy: {self.flags_policy!r}")
        if self.cull_max_score > self.keep_min_score:
            raise ValueError(
                f"cull_max_score ({self.cull_max_score}) above keep_min_score "
                f"({self.keep_min_score}) inverts the bands")


@dataclass(frozen=True)
class Row:
    """One blind-labelled frame, everything the rule stack needs."""

    truth: str
    score_final: float
    flags: tuple[str, ...]
    scene: str = ""
    weight: float = 1.0


@dataclass(frozen=True)
class CVResult:
    thresholds: tuple[RuleThresholds, ...]   # one per fold, as fitted
    held_out_macro: float
    baseline_macro: float
    delta: float
    ci: tuple[float, float]
    n: int
    refusal: str | None = None
    #: Parameters the data could not distinguish at all — reported, and
    #: pinned to the shipped value rather than to the grid's arbitrary
    #: pick.  See ``unidentifiable`` for why this is not a formality.
    unidentified: tuple[str, ...] = ()

    @property
    def ships(self) -> bool:
        """Only a held-out interval clear of zero is a reason to change."""
        return self.refusal is None and self.ci[0] > 0


def _config_with(config, thr: RuleThresholds, strictness: str):
    """A copy of ``config`` whose active strictness preset is ``thr``.

    Copied rather than mutated: a calibration run that leaves the
    process-wide config changed would make every later call in the same
    process report on thresholds nobody chose.
    """
    fusion = dict(config.fusion)
    presets = dict(fusion.get("strictness_presets") or {})
    presets[strictness] = {
        "keep_min_score": float(thr.keep_min_score),
        "cull_max_score": float(thr.cull_max_score),
    }
    fusion["strictness_presets"] = presets
    fusion["decision"] = {**presets[strictness],
                          "flags_policy": thr.flags_policy}
    return _dc_replace(config, fusion=fusion) if hasattr(config, "__dataclass_fields__") \
        else config.model_copy(update={"fusion": fusion})


def predict(row: Row, thr: RuleThresholds, config,
            strictness: str = "standard") -> str:
    """What the rule stack alone would decide, with ``vlm_authority`` off."""
    # v2.68 — the policy travels in the config and ``decide()`` applies
    # it.  An earlier draft re-implemented the demotion here, and the
    # product's own version applied it in a different place: this
    # module measured a rule that demoted BEFORE the score check (so a
    # flag could rescue a frame the score would have culled) while the
    # product did it after.  The measurement described a system that was
    # never going to run.  There is now one implementation, and it is
    # the shipped one.
    d, _ = decide(
        row.score_final,
        list(row.flags),
        _config_with(config, thr, strictness),
        strictness,
        scene=row.scene or None,
        vlm_authority="off",
    )
    return d.value


def score(rows: Iterable[Row], thr: RuleThresholds, config,
          strictness: str = "standard", *, three_way: bool = False) -> float:
    """Macro-F1 of the rule stack against the labels.

    ``three_way`` scores ``maybe`` as its own class instead of folding it
    into ``keep``.

    v2.89 — the default stays two-way and that is correct FOR ITS
    QUESTION. It was measured, not assumed: on frames the photographer
    kept, 58 of 60 maybes were worth another look (97% right); on frames
    they culled, 13 of 16 were a genuine miss. Scoring a maybe as a keep
    is what that evidence says, when the question is "how good is the
    model".

    But it is the wrong metric for a DIFFERENT question, and the module
    used one metric for both. `keep_min_score` decides which frames
    become maybe rather than keep. Under the two-way metric those are the
    same prediction, so the parameter moves rows between two buckets the
    score cannot tell apart: sweeping it from 6.5 to 10.0 moved 409
    frames and changed macro-F1 by nothing at four decimal places, while
    five folds "agreed" on 6.75 — agreement about an arbitrary tie-break.

    Three-way exists so the boundary is visible to the metric that tunes
    it. It is NOT the headline number and must never be reported as one:
    it answers "can this parameter be identified", not "is the model
    good".
    """
    cm: dict = {}
    for r in rows:
        pred = predict(r, thr, config, strictness)
        if three_way:
            _tally3(cm, r.truth, pred, r.weight)
        else:
            _tally(cm, r.truth, pred, r.weight)
    return _macro(cm)


def _tally3(cm: dict, truth: str, pred: str, w: float = 1.0) -> None:
    """Three-class tally: keep, maybe and cull are distinct predictions.

    Unlike the two-way tally this does NOT drop rows whose truth is
    `maybe` — under three-way scoring a maybe label is an answer, not a
    shrug, and dropping it would leave the parameter as invisible as
    before while looking like it had been fixed.
    """
    from pixcull.scoring.vlm_eval import Confusion
    labels = ("keep", "maybe", "cull")
    if truth not in labels or pred not in labels:
        return
    for label in labels:
        c = cm.setdefault(label, Confusion(label))
        if pred == label and truth == label:
            c.tp += w
        elif pred == label and truth != label:
            c.fp += w
        elif pred != label and truth == label:
            c.fn += w


def outcomes(rows: Iterable[Row], thr: RuleThresholds, config,
             strictness: str = "standard") -> tuple[float, float]:
    """(keepers destroyed, culls found), weighted.  The two axes a
    photographer actually feels."""
    killed = found = 0.0
    for r in rows:
        p = predict(r, thr, config, strictness)
        if p != "cull":
            continue
        if r.truth == "keep":
            killed += r.weight
        elif r.truth == "cull":
            found += r.weight
    return killed, found


def asymmetric_score(rows: Iterable[Row], thr: RuleThresholds, config,
                     strictness: str = "standard") -> float:
    """Culls found minus keepers destroyed.

    macro-F1 is symmetric and this product is not.  ``decision.py`` has
    said so since long before this module existed — "a missed cull costs
    thirty seconds, a wrong cull costs the photograph" — and optimising
    a symmetric metric against an asymmetric loss produced exactly the
    configuration you would predict: the macro-F1 fit walked ``cull_max``
    up to the top of its allowed range, destroying 82 weighted keepers to
    find 21 culls, and would have gone further if the grid had let it.

    This objective is the most cull-friendly reading of the doctrine that
    is still consistent with it: one destroyed photograph must buy at
    least one correct deletion, and subject to that, find as many as you
    can.  It is deliberately not a tuned exchange rate — a rate fitted
    here would be one more parameter the blind labels cannot identify.

    The second clause is not decoration.  The first draft returned
    ``found - killed`` alone, which scores "cull nothing" (0 - 0) and
    "find four, destroy four" (4 - 4) **identically at zero** — so the
    folds split between them, half the run fitting a stack that deletes
    nothing at all.  A tie between doing the job badly and not doing it
    is not a tie.
    """
    killed, found = outcomes(rows, thr, config, strictness)
    if found >= killed:
        return found
    # Infeasible: ranked below every feasible option, but still ordered
    # among themselves so a grid with no feasible point degrades to the
    # least-bad rather than to whichever candidate came first.
    return found - killed - 1e6


_OBJECTIVES = {"macro": score, "asymmetric": asymmetric_score}


def default_grid(step: float = 0.25,
                 pin_keep_min: float | None = None
                 ) -> tuple[RuleThresholds, ...]:
    """Candidate thresholds, both flag policies.

    The step is coarse on purpose.  A finer grid does not find a better
    rule stack, it finds a better fit to 493 frames — and the whole
    point of the cross-validation below is that those are different
    things.

    ``pin_keep_min`` holds the keep/maybe boundary at the shipped value
    and searches only below it.  That is the honest default and the
    caller should almost always pass it, for two reasons that turned up
    the first time this ran without it:

    * The metric cannot see that boundary at all (``unidentifiable``),
      so anything the grid picks there is a tie-break dressed up as a
      measurement.
    * Left free, the fit put ``cull_max`` at 6.75 — *above* the shipped
      ``keep_min`` of 6.5.  Those two cannot both hold, so the search
      had wandered into configurations the product cannot express, and
      the crash that revealed it was the validation doing its job.
    """
    out = []
    lo = 0.0
    while lo <= 10.0 + 1e-9:
        his = [pin_keep_min] if pin_keep_min is not None else None
        if his is None:
            his, hi = [], lo
            while hi <= 10.0 + 1e-9:
                his.append(hi)
                hi += step
        for hi in his:
            if lo > hi:
                continue
            for pol in ("cull", "maybe", "ignore"):
                out.append(RuleThresholds(keep_min_score=hi,
                                          cull_max_score=lo,
                                          flags_policy=pol))
        lo += step
    return tuple(out)


def unidentifiable(rows: Sequence[Row], thr: RuleThresholds, config,
                   strictness: str = "standard", *,
                   three_way: bool = False) -> tuple[str, ...]:
    """Which of ``thr``'s parameters the data cannot see at all.

    Not a formality.  The first run of this module fitted
    ``keep_min_score`` to 6.75, and all five folds agreed — which reads
    exactly like a stable, well-identified estimate.  It was not.  The
    metric scores ``maybe`` as ``keep`` (measured: 97% of ``maybe``s on
    kept frames were recoverable), so MAYBE and KEEP are the *same
    prediction*, and ``keep_min_score`` only moves rows between them.
    Sweeping it from 6.5 to 10.0 changed macro-F1 by nothing at four
    decimal places while moving 409 frames between keep and maybe.

    The fold agreement was agreement about an arbitrary tie-break.
    Shipping it would have published an unmeasured constant with a
    cross-validated number standing behind it, which is worse than
    publishing no number at all.

    So: vary each parameter alone, and if the score never moves, say so.
    """
    base = score(rows, thr, config, strictness, three_way=three_way)
    dead: list[str] = []
    sweeps = {
        "keep_min_score": [x / 4 for x in range(0, 41)],
        "cull_max_score": [x / 4 for x in range(0, 41)],
        "flags_policy": ["cull", "maybe", "ignore"],
    }
    for name, alts in sweeps.items():
        moved = False
        for v in alts:
            if getattr(thr, name) == v:
                continue
            try:
                cand = _dc_replace(thr, **{name: v})
            except ValueError:
                continue        # inverted bands are not evidence either way
            if abs(score(rows, cand, config, strictness,
                         three_way=three_way) - base) > 1e-9:
                moved = True
                break
        if not moved:
            dead.append(name)
    return tuple(dead)


def fit(rows: Sequence[Row], config, *,
        grid: Sequence[RuleThresholds] | None = None,
        strictness: str = "standard",
        pin_to: RuleThresholds | None = None,
        objective: str = "macro") -> RuleThresholds:
    """Best thresholds on THESE rows.  Never call with rows you will score.

    ``pin_to`` supplies the shipped configuration.  Any parameter the
    data cannot identify (see ``unidentifiable``) is taken from there
    instead of from the grid's arbitrary winner, so a fit can only
    change a number it actually measured.
    """
    grid = grid or default_grid()
    obj = _OBJECTIVES[objective]
    best, best_m = None, float("-inf")
    for thr in grid:
        m = obj(rows, thr, config, strictness)
        if m > best_m:
            best, best_m = thr, m
    if pin_to is not None:
        dead = unidentifiable(rows, best, config, strictness)
        if dead:
            try:
                best = _dc_replace(
                    best, **{k: getattr(pin_to, k) for k in dead})
            except ValueError:
                # Pinning an unidentified parameter back to the shipped
                # value would invert the bands, which means the fit has
                # moved an *identified* parameter past it.  Leave the fit
                # alone and let the caller see it: silently keeping the
                # grid's tie-break here would ship exactly the unmeasured
                # constant this guard exists to catch.
                pass
    return best


def cross_validate(rows: Sequence[Row], config, *, k: int = 5,
                   seed: int = 20260821,
                   grid: Sequence[RuleThresholds] | None = None,
                   pin_keep_min: bool = True,
                   objective: str = "macro",
                   strictness: str = "standard",
                   bootstrap: int = 2000) -> CVResult:
    """Out-of-fold macro-F1 for a fitted rule stack, against the shipped one.

    Every row is predicted exactly once, by thresholds fitted without
    it.  The returned delta is therefore an estimate of what
    recalibration buys on frames nobody tuned against — which is the
    only number that has any bearing on shipping.
    """
    rows = list(rows)
    n = len(rows)
    shipped = RuleThresholds(
        keep_min_score=float((config.fusion.get("strictness_presets") or {})
                             .get(strictness, {}).get("keep_min_score", 6.5)),
        cull_max_score=float((config.fusion.get("strictness_presets") or {})
                             .get(strictness, {}).get("cull_max_score", 4.0)),
        flags_policy="cull",
    )

    def _refuse(msg: str) -> CVResult:
        return CVResult((), 0.0, 0.0, 0.0, (0.0, 0.0), n, refusal=msg)

    if k < 3:
        return _refuse(f"k={k}: fewer than 3 folds cannot estimate variance")
    if n < k * 2:
        return _refuse(f"{n} rows across {k} folds leaves folds too small to fit")

    if grid is None:
        grid = default_grid(
            pin_keep_min=shipped.keep_min_score if pin_keep_min else None)

    rng = random.Random(seed)
    order = list(range(n))
    rng.shuffle(order)
    folds = [order[i::k] for i in range(k)]

    for i, f in enumerate(folds):
        held = [rows[j] for j in f]
        train = [rows[j] for j in order if j not in set(f)]
        n_held_cull = sum(1 for r in held if r.truth == "cull")
        n_train_cull = sum(1 for r in train if r.truth == "cull")
        if n_held_cull == 0:
            return _refuse(
                f"fold {i} holds no cull positives — recall is undefined "
                f"there, and a mean over undefined folds is not a number")
        if n_train_cull < _MIN_CULL_PER_FOLD:
            return _refuse(
                f"fold {i} trains on {n_train_cull} cull positives "
                f"(< {_MIN_CULL_PER_FOLD}) — that is fitting noise")

    fitted: list[RuleThresholds] = []
    dead_seen: set[str] = set()
    oof: list[tuple[str, str, str, float]] = []   # truth, base_pred, cv_pred, w
    for f in folds:
        held = [rows[j] for j in f]
        train = [rows[j] for j in order if j not in set(f)]
        thr = fit(train, config, grid=grid, strictness=strictness,
                  pin_to=shipped, objective=objective)
        fitted.append(thr)
        dead_seen.update(unidentifiable(train, thr, config, strictness))
        for r in held:
            oof.append((r.truth,
                        predict(r, shipped, config, strictness),
                        predict(r, thr, config, strictness),
                        r.weight))

    def _m(sample, idx: int) -> float:
        cm: dict = {}
        for truth, base, cv, w in sample:
            _tally(cm, truth, base if idx == 0 else cv, w)
        return _macro(cm)

    n_cv_culls = sum(1 for _, _, cv, _ in oof if cv == "cull")
    if n_cv_culls == 0:
        return _refuse(
            "the fitted stack culls nothing at all — 0 of "
            f"{sum(1 for r in rows if r.truth == 'cull')} true culls found. "
            "That is a disablement wearing a calibration's clothes, and it "
            "scores well only because the metric rewards not destroying "
            "keepers. Refused the same way v2.67 refuses a zero-recall arm.")

    base_m, cv_m = _m(oof, 0), _m(oof, 1)
    rng2 = random.Random(seed + 1)
    deltas = []
    for _ in range(bootstrap):
        bs = [oof[rng2.randrange(len(oof))] for _ in range(len(oof))]
        deltas.append((_m(bs, 1) - _m(bs, 0)) * 100)
    deltas.sort()
    lo = deltas[int(0.025 * len(deltas))]
    hi = deltas[int(0.975 * len(deltas))]
    return CVResult(tuple(fitted), cv_m, base_m, (cv_m - base_m) * 100,
                    (lo, hi), n, unidentified=tuple(sorted(dead_seen)))
