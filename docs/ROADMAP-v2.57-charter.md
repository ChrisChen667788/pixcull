# PixCull v2.57 → v2.62 charter — make the culling actually work

Written 2026-08-19, after the first measurement in this project's
history that cannot be circular.

## The finding this whole plan answers

150 frames from an untouched card, labelled **blind** — the card showed
the photograph, a serial number and two buttons, and nothing else. Then
scored. In that order, so the labels cannot echo any system.

| | frames the photographer would delete, found |
|---|---|
| rule stack | **2 of 10** |
| `vlm_authority=primary` | 1 of 10 |
| `vlm_authority=rescue` | 0 of 10 |

The rule stack also culls **53 of 150 while the photographer culls 10** —
over-culling by 5.3x. Both authority modes' macro-F1 deltas have 95%
confidence intervals spanning zero.

**The product's headline job is unvalidated, and the available evidence
is negative.** Everything below follows from that, and nothing below is
a new feature.

Two supporting facts that shape the work:

* **The detector flags carry no signal for this photographer's culls.**
  Against a 6.7% baseline: `no_clear_subject` 6.0% (0.9x — worse than
  chance), `severely_underexposed` 0%, `severely_blurry` 0%. Frames with
  **no flag at all** are the most-culled group at 8.3%.
* **The culls are not defective frames.** They are sharper than average
  (+0.70σ laplacian), pass technical more often, and none are in a
  burst. The single discriminator is composition (-0.82σ). The
  photographer deletes editorially weak pictures, which is precisely
  what a detector cannot see.

## v2.57 — stop shipping conclusions we cannot support

**P0-1 Publish the blind number.** The README's "what it found" section
quotes results from disagreement-sampled passes. Replace with the blind
census, including 2-of-10. Uncomfortable and true; the alternative is a
public claim the repo's own gate contradicts.

**P0-2 Personalization provenance.** *(landed early — see below.)*

**P0-3 GitHub ⇄ ModelScope sync.** 42 commits are unpushed and the
mirror is that far behind. Needs the owner's go-ahead: pushing is
publishing.

**P0-4 Screenshot re-shoot.** 24-review-sheet.png predates the EXIF fix.
Any portrait frame in it rendered sideways.

## v2.58 — make one shoot's threshold fittable

The rule over-culls 5.3x on this shoot and the personalization that was
supposed to correct that had been learning from the rule's own output.
With provenance now enforced, the mechanism is inert until a blind
profile exists — so build the path that produces one.

**P0-1 `pixcull calibrate <folder>`** — blind-label N frames from THIS
shoot, fit `keep_threshold_shift` to the result, write a profile stamped
`label_provenance: "blind"`. The existing `apply_threshold_shift` is
reused; only the input changes.

**P0-2 Report the fit, not just apply it.** How much did the boundary
move, how many frames change decision, and what does that do to the
2-of-10. A calibration that cannot show its own effect is a badge.

**P1-1 Per-scene shift.** The corpus is 89% keep overall but the cull
rate varies by scene; one global shift is the coarsest possible fit.

## v2.59 — attack the composition failure directly

M3 was handed the measurements and still found 1 of 10. The frames it
misses are compositionally weak and technically clean, so the question
is whether the prompt's evidence block biases it toward the technical.

**P0-1 Prompt A/B under the eval harness.** Evidence-block-first vs
picture-first vs no evidence. The harness already refuses to rank an
underpowered sample, so this is a measurement, not a vibe check.

**P0-2 Ask the right question.** The rubric asks for six axis scores and
an overall label. Try asking only "would a working photographer delete
this frame, and why" — closer to the labelled question.

**P1-1 Feed composition, not exposure.** The evidence block currently
carries blur/clipping/blink — the three signals measured at 0x lift.

## v2.60 — make ground truth cheap enough to have enough of

150 blind frames yielded 10 cull positives; the CI needs ~84 scoreable
rows with both classes represented. At 6.7% that is ~1250 frames, and
the current page is mouse-only.

**P0-1 Keyboard labelling.** `J`/`K` or `←`/`→`, one keystroke per
frame, no scrolling. Sub-second per frame makes 1000 frames a sitting.

**P0-2 Resume and progress.** localStorage already survives a reload;
surface "312 / 1000" and let a batch span days.

**P1-1 Stratified blind batches.** `m3 label --scores` exists; make the
weights flow into the eval automatically rather than by hand.

## v2.61 — re-measure, then decide the default

Re-run the three arms on ~1000 blind frames. If an interval clears zero,
flip `vlm_authority` and rewrite the public claims to match. If it does
not, say so publicly and keep the cloud judge opt-in.

**This version is allowed to conclude that the model does not help.**

## v2.62 — close the residual debt

Four `UNREVIEWED` orientation entries: `counterfactual` (its loader is
fixed; confirm and drop) and three video readers (verified to need
nothing; convert the exception into a positive assertion).

## What is deliberately NOT here

* New detectors. Eight of them measured at 0x lift on the only
  non-circular data we have.
* Ranking folders by rule-cull rate to find "cull-rich" material. The
  flags do not predict this photographer's culls, so it would find
  folders the detectors dislike.
* Anything that improves a number without a blind label behind it.
