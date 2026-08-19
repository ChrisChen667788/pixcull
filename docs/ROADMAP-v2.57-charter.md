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

---

## What actually landed (updated 2026-08-19, v2.57 → v2.62)

Written after the work, with the deviations named. The plan above was
drawn from the blind measurement; two of its slices survived contact
unchanged and two were rewritten by what the data said next.

**v2.57 — shipped as planned.** Blind number published in both READMEs,
personalization provenance gate, GitHub ⇄ ModelScope sync, screenshot
re-shot. Two corrections fell out of it: the READMEs twice claimed a
default that the code did not have, and the screenshot re-shoot exposed
a layout bug the EXIF bug had been hiding.

**v2.58 — NOT in the plan.** `vlm_authority` shipped `primary`; the
blind pass gave `primary` 1 of 10 with an interval spanning zero. It
ships `off`, the CLI gained `--vlm-authority`, and three layers that
each carried the default are pinned together — only `run_pipeline`'s
governed anything, so changing `decide()` alone would have been
decoration.

**v2.59 `calibrate` — built as planned, and the result was negative.**
Fitting the threshold to a blind pass moves 26 decisions and changes
neither the over-culling nor the recall, because all 53 of the rule's
culls fire on hard flags and none come from the boundary. A score shift
cannot reach a flag. The command reports that rather than stopping at
"this fit does nothing".

**v2.60 / v2.60.1 — the plan's P1-1 became the P0.** The lever is the
flags, not the threshold. `unknown` scenes stop hard-culling on
`no_clear_subject` (53 → 48 culls, no recall lost), and learned
(flag, scene) exemptions live in the profile rather than in the shipped
defaults. The evidence bar withheld `documentary`, which I had been
about to exempt by eye.

**v2.61 / v2.61.1 — shipped as planned.** Keyboard labelling and a
progress bar, because ~1250 frames is the real bar for a usable
interval and mouse-and-scroll does not get there.

**v2.62 — the orientation debt closed.** `counterfactual` had its own
loader; a v2.56.3 note claimed otherwise without checking. Three video
readers remain listed, each backed by a checked property rather than an
assertion: ffmpeg writes no orientation tag.

### Still open, and why

**v2.59's prompt A/B is not done.** It was scheduled to attack the
composition failure, and the calibration work displaced it: with the
rule stack over-culling 4.8x on flags, the model's prompt is not the
binding constraint. It stays on the list.

**The measurement is still underpowered.** 150 blind frames, 10 cull
positives. Nothing here has moved `vlm_authority` off `off`, and
nothing should until a pass with both classes properly represented says
otherwise. The tooling to collect one now exists; the labelling does
not.

---

## v2.63 candidate — `maybe` means "not yet", not "borderline"

Owner's framing, 2026-08-19: a frame that is not a keeper as shot may
well be one after a crop or a grade, and those originals belong in the
`maybe` band rather than being scored as near-misses on the same axis
as a genuine borderline.

This is a gap in the measurement, not only in the product. Every number
in this charter excludes `maybe` from the headline F1, on the stated
grounds that "the human used it to mean *I am not sure*". If `maybe`
actually means *recoverable*, then excluding it is discarding the
band where the tool could add the most value, and calling that band
noise.

What would have to be true, in order:

1. **The blind card has no `maybe` button.** It asks keep-or-cull on
   purpose — two answers, no scale to calibrate. A third option costs
   that, so it needs to earn its place: does the photographer's
   `maybe` predict anything the binary does not?
2. **A recoverable frame is a claim about the crop, not the frame.**
   The detectors already compute subject mask, thirds offset, lead room
   and zone clipping — enough to ask "is there a keeper inside this
   frame". `counterfactual.py` already answers a related question for
   advice; it has never been evaluated.
3. **It cannot be measured with what we have.** The 394-frame blind
   pass is keep/cull. Testing this needs a pass where the photographer
   marks *recoverable* separately, on frames they would otherwise cull.

So the honest sequencing is: finish powering the keep/cull measurement
first (that is what the current 394 frames are for), then run one
labelling pass that asks the recoverable question, and only then decide
whether the pipeline should surface it. Building the feature before the
label exists is how this project produced four circular datasets.
