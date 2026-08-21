# What the other culling tools do, and what PixCull should take from it

Researched 2026-08-21, after the owner's note that the AI's commentary
"is still too shallow — it doesn't read as photographic or aesthetic
expertise."

## The finding that reframes everything else

DPReview's Aftershoot Pro review — Aftershoot being the market leader —
tested the AI and found closed-eye detection essentially perfect,
duplicate grouping solid, and then this:

> **Aftershoot provides zero reasoning for decisions.** No explanatory
> text, no confidence scores, no decision rationale — only categorical
> labels and visual context clues. This opacity undermines photographer
> confidence, especially when decisions seem arbitrary.

And the decisions *do* seem arbitrary: the same review found blur
detection "hit-and-miss", and keeper selection making "decidedly strange
decisions", rating frames with subjects' heads cut off as five stars —
the AI "didn't always seem aware of what the subjects were."

So the leader is strong at measuring and weak at *seeing*, and says
nothing about either. **Explaining the call is the open ground in this
market, and it is the one thing PixCull is built around.** The owner's
complaint is therefore not a polish request. It is a report that the
product's only real moat is not landing.

## Narrative Select — the one to study

Narrative's positioning is the opposite of Aftershoot's: it does not
take over, it "surfaces the information you need in the moment you need
it." Three mechanisms are worth taking seriously:

- **Scenes View** — groups a shoot chronologically into its parts
  (ceremony, cocktail hour, reception) so you cull in story order rather
  than image by image. Reviewers call this unique to Narrative.
- **Close-ups Panel** — auto-zooms every face in the frame at once, so
  spotting the best expression needs no manual zoom per subject.
- **Survey Mode** — near-identical frames side by side, rather than
  toggling between them from memory.

Plus: arrow-key navigation with *no* preview delay, by reading the RAW's
embedded JPEG locally.

PixCull already has close-ups and A/B compare. It does not have scenes,
and its keyboard navigation is fast but its first-scroll is not.

## What actually makes the commentary read as shallow

Measured on the owner's own run rather than guessed at.

**1. The template and the observation are indistinguishable in the UI.**
`photo_advice.py` is 1,576 lines of templates with zero model calls;
`m3_advice.py` replaces them with commentary from a model that has
actually looked at the frame. Both render identically — same panel, same
canon citations, same styling. On the screenshot the owner sent, the
strengths read:

> 捕捉到动物的神情**或**动作

That "或" is the tell. A model looking at the picture says "企鹅侧头看向
画面外"; only a template hedges between two possibilities it cannot
distinguish. The photographer had no way to know they were reading a
canned phrase, and every canned phrase spends the credibility that the
real ones earn.

**2. `nan` reaches the screen.** `vlm_overall_label` on that run is the
*string* `"nan"` — a pandas NaN serialised through CSV — and the pane
renders it because a non-empty string is truthy. The inspector shows
"VLM 视觉 / nan". Same defect family as the v2.13 bug where NaN bypassed
an `is None` check and clamped every score to 1.0.

**3. The output shape caps the depth.** The prompt asks a "资深摄影指导"
for at most three one-sentence strengths, three weaknesses, two
suggestions. A senior director reviewing a frame does not speak in three
detached bullets; they say what the picture is doing, what it is doing
wrong, and what they would have done differently — and the connection
between those is most of the value. The schema forbids the connection.

## What to build, in order

**P0 — say which voice is speaking.** Template advice and looked-at-the-
frame advice must be visibly different in the inspector. This costs
almost nothing and it is an honesty fix before it is a UX one: a reader
who cannot tell the two apart has to discount both.

**P0 — no NaN reaches a human.** At the serialisation boundary, not with
a defensive check in each of the three consumers.

**P1 — let the critique be a critique.** Replace the bullet schema with
one that has room for a reading of the frame: what the photograph is
doing, the strongest specific observation for and against, and one
concrete alternative framing. Keep the canon citation, drop the
requirement that every line carry one — a forced citation is where
"作品塔·图底关系" comes from.

**P1 — measure it.** Advice quality has never been evaluated. A blind
pass where the photographer scores paragraphs without knowing which came
from the template and which from the model, on a rubric they set. If the
model's advice does not beat the template blind, the depth problem is
not where we think it is. This is v2.75 in the standing charter and it
should move up.

**P2 — Scenes.** Chronological grouping is the one competitor feature
PixCull lacks outright, and EXIF timestamps are already read. It changes
culling from a 5,000-frame list into a handful of named stretches.

**P2 — first-scroll cost.** v2.68.2 removed the steady-state jank; the
first descent through an un-materialised run still blocks ~1.8s. Reading
"no delay" as a headline competitor feature is a reminder that this is
table stakes, not polish.

## Deliberately not taken

CapCut's transferable ideas — progressive disclosure, a contextual
inspector, micro-interaction polish — are already this product's
existing pattern, and the search turned up no specific interaction worth
copying that PixCull does not already do. Recording that rather than
inventing a finding to justify the search.
