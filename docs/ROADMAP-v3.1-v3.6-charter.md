# PixCull v3.1 → v3.6 charter — three competitors, read after the fact-check

Written 2026-09-02, after v3.0.3. Continues `ROADMAP-v2.79-v2.93-charter.md`,
which is closed (`BLOCK-v2.77-v2.93-CLOSE.md`).

This block has one input: the deep competitive research behind
`COMPETITIVE-2026Q3.md`, re-read at the level of the individual product entry
rather than the summary. Three products are read closely — **Capture One 16.8
Assisted Review**, **美图云修 Meitu Yunxiu**, **像素蛋糕 PixCake** — because they
are the three that sit closest to what PixCull does: one is inside the
application professional studios already tether through, and two own the Chinese
studio workflow this project's owner shoots in.

## Why this block exists separately from the research

The research pass wrote `confidence: verified` on all three of these entries.
The verification pass then overturned two of the three. A roadmap built on the
first pass would have committed engineering to features that were misattributed,
to version numbers that do not exist, and to a privacy contrast no source
supports. So the charter below states, per competitor, **what survived
verification** and builds only on that.

---

## The evidence, corrected

### Capture One 16.8 — Assisted Review (beta) · verified

Sourced to the vendor's own release page (2026-05-28). What holds:

* Tags every image in the Browser as **"Need review"**, **"Issues Detected"**, or
  **"Can't tell"**, from closed eyes, missed focus, and black/blank frames.
* The tags are **Smart Album criteria** and **combine with the photographer's
  existing star ratings** — they are added alongside the photographer's own work,
  not in place of it.
* Runs on tethered ingestion as well as existing catalogues, so the first flag
  arrives as frames land.
* Included in every subscription — no separate purchase, no separate install.
* The vendor's own documentation calls it a *first-pass assist* and warns that
  accuracy varies.

Nothing here was overturned. It is also, deliberately, a much smaller feature
than PixCull's: three buckets, no score, no rationale, no per-vertical weighting,
no burst-peak selection, no advice.

### 美图云修 Meitu Yunxiu · partially overturned

What survived: **骨相磨皮** (bone-structure skin smoothing) is a genuine shipping
differentiator, corroborated across independent coverage. Desktop and iPad are
**two separate products** — desktop v8.0 (the download page states desktop-only)
and an iPad app on a separate v1.x track whose store listing does describe
wired-camera connection with automatic import. The trade-show demonstrations were
real and publicly witnessed.

What was overturned:

* **"v8.0 has iPad tethered capture"** — version conflation of two products.
* **"Cloud upload is required; there is no on-device option"** — *no source
  supports this.* The coverage describes photos syncing to the iPad and AI
  retouching completing there, which is consistent with on-device processing.
  This was the load-bearing claim in a privacy contrast drawn in PixCull's
  favour, and it was ours, not theirs.
* Efficiency multiples, studio counts, and processed-image volumes are **vendor
  self-reported**, uncorroborated, and describe the whole platform rather than
  the tethered feature.

Also worth stating plainly for roadmap purposes: Meitu Yunxiu is a **retouching**
tool and PixCull is a **culling** tool. They are adjacent steps, not substitutes.
Treating them as head-to-head competitors distorts every comparison drawn.

### 像素蛋糕 PixCake · largely overturned

What survived, from the vendor's own site: **Sugar Engine 2.0** for
GPU-accelerated retouching, and a five-step studio workflow — shoot, retouch,
layout, select, deliver — marketed as an **ecosystem of companion products**,
not as one unified application.

What was overturned:

* The offered source was **paid promotional content** that does not mention the
  features attributed to it.
* **QR-code WeChat mini-program client selection** could not be confirmed as a
  shipping named feature of any version called "3.0" in any primary or
  independent source.
* **"All processing is cloud-based"** is unverified; the cloud appears to be a
  collaboration and transmission layer. The privacy-axis comparison to PixCull
  cannot be drawn as stated.

---

## What needed no new version

**Capture One's "first-pass assist" positioning.** Their documentation ships an
accuracy caveat next to the feature. That is the same posture as this repo's
refusal guards and its five `[owner]`-blocked versions, which exist precisely so
that no accuracy number gets published without a human having produced the labels
it is measured against. This is confirmation of existing strategy. No work item.

**Client-facing selection.** `COMPETITIVE-2026Q3.md` §gap-2 called this PixCull's
second-largest gap and proposed a static proof gallery. The owner then made a
narrower and better-informed call: keep the studio's existing motion — export to
iPad or Mac and review on-site, or send watermarked frames over WeChat and take
remote feedback — and optimise inside it. That shipped as v2.97 through v3.0.2:
客户在场模式, the burned-in index that survives a WeChat re-encode, reply parsing,
the viewable folder export, and client picks kept in their own file. The gap is
closed in a different shape than the research proposed, and the research document
has been corrected to say so.

---

## The six

### v3.1 — 「无法判断」: the verdict PixCull does not have
Capture One ships four states where PixCull ships three, and the fourth is not a
soft keep — **"Can't tell"** is the model declining to judge. In PixCull, a frame
the model could not evaluate and a frame it evaluated and found genuinely
borderline both land in `maybe`, indistinguishable to the photographer. Both
mean "you look", so the bucket is not wrong; but the *reason* differs, and so
does the review order — an unjudged frame has had nothing done for it yet.
This repo already ships the concept one layer up: `fallback_ledger` records
advice the model **withheld**, with reasons. The decision layer has no equivalent.
**Scope note:** a fourth `decision` value is a schema change reaching the CSV,
the XMP sidecar, the grid, the filters, the summary counts, and every consumer of
`decision`. The cheaper shape is a flag on `maybe` carrying the reason, plus a
filter, leaving the three-bucket vocabulary intact. Prefer the flag unless the
measurement says otherwise.
**Measure:** on real shoots, the share of `maybe` frames produced from thin or
absent axis evidence versus full evidence. **Ships only if** that share is large
enough to change a review order. Below a pre-registered threshold this version
closes as *measured and declined*, and that is a successful outcome.
**Wrong, not late:** a state that fires on a fraction of a percent of frames adds
vocabulary the photographer must learn for nothing. The measurement gates the
build; the build does not gate the measurement.

### v3.2 — the photographer's own ratings survive PixCull
The design idea in Assisted Review is not the tagging, it is that the tags are
**additive**: separate criteria that compose with the stars and colour labels the
photographer already set, feeding Smart Albums without overwriting anything.
PixCull writes XMP. No test in this repo asserts what happens to a rating or
label that was already in the sidecar.
**Measure:** a folder already starred and colour-labelled in Lightroom, run
through PixCull, re-opened in Lightroom. Every pre-existing star and label still
present is a pass; any loss is a data-loss defect that outranks everything else
in this charter.
**Wrong, not late:** this may already be correct, in which case the version is a
regression test and closes quickly. That is a fine outcome. The reason to run it
is that nothing currently asserts it, and the failure mode is silent.

### v3.3 — the live path and the finished path have drifted
Both Meitu's iPad import and Capture One's Assisted Review put the first verdict
at capture time. PixCull already has that seam and has had it since P2.2:
`tether.py` watches the tether destination folder, `tether_stream.py` picks burst
peaks as frames arrive, and `/tether` is routed and served. But it predates most
of what the last forty versions added, and carries none of it — no written
advice, no client picks, no viewable-folder export, no burst evidence panel.
It is not obvious that it *should* carry all of them. It is obvious that nobody
has decided.
**Measure:** run a tether session against a real folder drop, and inventory what
the live verdict shows against the finished run for the same frames. Publish the
list. Every row gets an explicit disposition — carried, or deliberately not
carried, with the reason.
**Wrong, not late:** this is the twin-path drift this repo hits repeatedly, and
the instinct to "fix" it by making the paths identical is the wrong one. A live
tether view that renders a full advice paragraph mid-shoot would be worse, not
better. The deliverable is an explicit divergence, not an eliminated one.

### v3.4 — after the client picks: the return leg
The verified half of PixCake is its shape: companion tools around one shared
project, where the selection step hands back to the retoucher. PixCull reached
the same instinct independently at v3.0 — client picks live in their own file and
are never merged into the photographer's record. What is not built is the return
leg. Once picks come back, the photographer still reconciles by hand: the client
wants frames the photographer culled, and ignored frames the photographer starred.
**Specific:** a reconciliation view that surfaces **only the disagreements** —
client-picked-and-photographer-culled, photographer-kept-and-client-ignored —
because those are the only rows that need a human.
**Measure:** on a shoot with real returned picks, the view surfaces every
disagreement and no agreement rows; time from picks-returned to a final export
list, against doing the same reconciliation by hand.
**Wrong, not late:** the photographer may not want these framed as disagreements
— the client is the client, and a tool that appears to argue with them is worse
than no tool. The framing must be neutral ("needs your call"), never scored, and
never phrased as the client being wrong.

### v3.5 — the claims PixCull makes about competitors, held to PixCull's own bar
Two of three headline claims in this batch were overturned, and the most damaging
one was ours: an unsourced assertion that a competitor requires cloud upload,
used to draw a privacy contrast in PixCull's favour. That is exactly the class of
claim this project refuses to publish about its own accuracy.
**Specific:** every comparative claim in the published competitive documents and
the README that asserts a *competitor's* limitation carries a source, or is
removed. The cloud-versus-local contrast is the first to audit.
**Measure:** a test that fails when a comparative table row in
`docs/COMPETITIVE-*.md` asserts a limitation without a source link on that row.
**Wrong, not late:** a linter strict enough to fire on prose would make the
document unmaintainable and would be disabled within a month. Scope it to table
rows, where the document already carries a Source column.

### v3.6 — the refresh protocol stops trusting its own confidence field
The scanning pass wrote `confidence: verified` on all three products read here.
Verification overturned two. A self-reported confidence field that is wrong two
times in three is worse than no field at all, because a downstream reader — the
next charter, the next refresh, the next release note — weights it.
**Specific:** in `COMPETITIVE-REFRESH-PROTOCOL.md` and in the fortnightly
automation, `confidence` is no longer written by the scanning pass at all. It is
written only by the verification pass, and defaults to `unverified` for every
entry verification did not reach.
**Measure:** re-run the fortnightly refresh. Every `verified` is traceable to a
verification record, and the count of `verified` entries **drops**.
**Wrong, not late:** a refresh where most entries read `unverified` looks like a
worse report than one where most read `verified`. It is a more honest one, and
the protocol document has to say that in its own text — otherwise a future reader
will helpfully "fix" the regression back.

---

## Deliberately declined

**An AI retouching engine.** Meitu's 骨相磨皮 and PixCake's Sugar Engine 2.0 are
their verified differentiators, and both are in a domain PixCull does not enter:
different dataset, different team, different market motion. The XMP sidecar is
the correct seam. This was declined in the previous charter and the closer
reading does not change it — it strengthens it, because what survived
verification for both products is retouching quality, not culling.

**A client-selection commerce platform.** Declined by the owner during the v2.97
work, and the research does not argue against that call: the specific mechanism
attributed to PixCake — QR-code WeChat mini-program selection — could not be
confirmed to exist as described in any primary source. Building against an
unverified competitor feature would be the worst possible reason to build.

**A fourth decision bucket, if v3.1 measures thin.** Written down here so that a
later reader finds the decision rather than the absence of one.

**Vendor self-reported statistics as roadmap justification.** Efficiency
multiples, studio counts, processed-image volumes, revenue effects: none are
independently corroborated, all originate in marketing repeated by press. They
may be true. They are not evidence, and no item in this charter rests on one.

---

## How this charter can fail

The specific risk in this block is different from the previous one. These six
items are small, and four of them can close by being *measured and declined* —
v3.1 if thin evidence is rare, v3.2 if the sidecar is already safe, v3.3 if the
divergence turns out to be deliberate, v3.5 if the claims are already sourced.
That makes it unusually easy to report the block closed while having built
nothing and, more importantly, having *measured* nothing. A version in this
charter closes on a published measurement, including when the measurement says
no build is needed. A version that closes because someone read the code and
formed an opinion has not closed.
