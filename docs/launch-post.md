# Why I open-sourced an AI photo culling tool I spent 18 months on

*A working photographer's pitch — and what's missing in every SaaS culling app.*

## The problem nobody admits

A typical wedding shoot produces 1,500 frames. A landscape day-hike,
maybe 600. A wildlife morning, easily 2,000 if there's anything moving.

To get to delivery, every one of those frames passes through the
photographer's mental decision tree at least twice:

1. **First pass** — "do I keep this one?" The decision is fast (a
   few hundred ms per frame) but exhausting. Six hours straight
   in Lightroom's library module is a normal post-event evening.
2. **Second pass** — once "keep" is settled, "which ONE of these
   five identical-looking burst frames do I publish?" This is the
   harder one. You're making a per-moment aesthetic call.

The first pass is what AI is genuinely good at today. Burst-peak
selection, sharp-focus detection, eyes-closed detection, exposure
sanity — solved problems if you wire them together right. The
market has noticed: there are 5+ commercial "AI culling" SaaS apps,
each charging $20-50/month.

But every one of them makes three trade-offs working photographers
shouldn't have to swallow:

### 1. They require uploading your photos to a cloud you don't control

Wedding contracts often explicitly forbid third-party cloud
processing of client images. Journalism NDAs forbid it more
strictly. Editorial sports has embargo windows. Wildlife shooters
of protected species CANNOT legally share location data, which
embeds in EXIF, which embeds in any uploaded file.

The SaaS pitch is "your photos are safe with us." The reality is:
they're on someone else's server, subject to that company's
business model, training pipeline, and legal jurisdiction. For
many real workflows that's a deal-breaker.

### 2. They give you a score, not a reason

The popular AI culling apps produce a single 0..1 confidence
number per photo, sorted descending. You're supposed to trust it.

But if your client asks "why didn't you pick this one?" — or you're
a self-teaching photographer trying to internalize the rubric —
a 0.43 number is useless. You need:

- Which axis is weak? Sharpness? Composition? Light? Moment?
- How does this compare to its burst-cluster neighbors?
- What's the canonical rationale? (Cartier-Bresson's decisive
  moment? Adams' Zone System exposure? Rule of space?)

A score-only system gets the photographer to a deliverable, but
it doesn't teach them anything along the way. That's a wasted
opportunity per shoot.

### 3. They live outside your tooling

Lightroom, Capture One, Photo Mechanic — that's where the real
work happens. Catalog operations, develop settings, color labels,
keyword tagging, IPTC captions, client galleries.

A walled-garden web app forces a context switch every batch. The
photographer's reaction is sensible: "if the tool doesn't write
XMP sidecars and my Lr catalog won't see the decisions, I'd
rather just open Lightroom and cull manually."

## PixCull

PixCull is the alternative I built, 18 months of small commits later.
**Local-first, six-axis rubric, native XMP sidecars + iOS swipe
companion + Lr/C1 tether mode + multi-user profiles + multi-shooter
merge.** MIT licensed. Source at
[github.com/ChrisChen667788/pixcull](https://github.com/ChrisChen667788/pixcull).

What's distinct:

- **Local-first.** RAW decode, scoring (CLIP + InsightFace + MediaPipe
  + a per-axis rescorer), faces, GPS clustering — all on-device.
  The optional DeepSeek meta-judge runs against *your* API key.
  Photos never leave your disk.

- **6-axis rubric.** Every frame scores stars on technical, subject,
  composition, light, moment, aesthetic — each with a rationale and
  (V5.2+) a citation to canon (Adams' Zone System, Rule of Thirds,
  Cartier-Bresson decisive-moment, etc). The lightbox shows
  4-source breakdown (auto / model / VLM / human) so you can see
  exactly when the rubric isn't sure.

- **Sidecar-native.** XMP files land where Lightroom expects them.
  IPTC captions auto-compose from scene + face labels + location
  + advice. Standalone HTML gallery as a zip you can email to a
  client. iOS swipe companion. Lr/C1 tether watcher.

- **Reasoning surfaced.** "Cull because focus_miss" is a first-class
  taxonomy now (P-UX-4). The picker re-orders by *your* historical
  frequency (P-UX-9). Per-axis confidence intervals (P-UX-11) show
  ± stddev so the user sees which axes are well-calibrated and
  which are guesses. The admin page surfaces *your* taste profile
  (P-UX-12) — which axes you actually weight when keeping vs culling.

## What I learned building it

A few things that surprised me along the way:

**The rescorer matters less than the rubric.** Spent six weeks
training a 6-axis regressor (V2.1) thinking it would be the
keystone. Ended up shipping it but discovering the V20 *advice*
envelope — short verdict + cited strengths/weaknesses — is what
makes users *trust* the tool. Numbers don't build trust; sentences
that match what you'd write yourself do.

**Pro photographers are extreme power users.** I shipped
keep/maybe/cull at 1/2/3 hotkeys in V2.0. Got immediate feedback
from working photographers: "where's F for flag? where's [/] for
verdict up/down? where's G for cluster nav? where's Backspace for
undo+back?" Photo Mechanic has trained two decades of muscle
memory. P-UX-13 ships exactly those bindings.

**1:1 zoom in the lightbox is non-negotiable.** Without focus-
check at 100%, the tool isn't usable for serious work. P-UX-2
adds click-to-zoom centered on the click point, drag to pan,
mouse-wheel to fine-tune, hi-res image swap on first zoom. Sounds
small; took two weeks to land right because synced zoom across
the A/B compare cells (P-UX-7) needed a normalized pan coordinate
system to handle different aspect ratios.

**Open-sourcing it forces clarity.** I had a MARKET_ANALYSIS_V10.md
in the repo (internal strategy notes, fine for solo work). Pre-
launch audit: that file goes. So do my personal photo training
labels (sanitized via sha1 hash IDs before pushing). The exercise
of "what's actually safe for public eyes" is uncomfortable but
*surfaces what you should never have collected in the first
place*. Honest moment.

## What's missing (deliberately)

PixCull is small on purpose. It doesn't do:

- **Edit/develop** — Lightroom + Capture One own that. PixCull
  writes XMP that LR's develop module respects.
- **Cloud hosting** — INFRA-2 syncs via folder mirror over
  iCloud / Dropbox / NAS. Anything more is someone else's job.
- **Multi-shooter merge across vendors** — INFRA-3 does it across
  PixCull runs; cross-tool merge is a 5-year problem.
- **Auto-tagging at LAION scale** — V20 advice is canon-cited,
  not embedding-based "automatic tags." More signal-to-noise per
  word, less coverage.

## How to try it

```bash
git clone https://github.com/ChrisChen667788/pixcull.git
cd pixcull
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/serve_demo.py
# open http://127.0.0.1:8770
```

First run warms the models (~30s on Apple Silicon), then ~1s per
photo on M2 Pro. Drag a folder of JPG / RAW / HEIC into the
upload page; pick a vertical (wedding / wildlife / sports /
landscape / etc.); get verdicts in 5-10 minutes for a typical
batch.

The full V0.1 release notes — including 8 separate P-UX
milestones (sticky decision toolbar, A/B compare with synced zoom,
cull-reason taxonomy, inconsistency badges, per-user taste profile,
Photo Mechanic-grade hotkeys, exposure-consistency check, Lr/C1
round-trip) and INFRA-3 multi-shooter merge — are in
[the GitHub README](https://github.com/ChrisChen667788/pixcull#readme).

## What I'd value feedback on

If you try it on your own shoots, what would help me most:

1. **Where does the rubric obviously misjudge a photo?** I have
   the per-source breakdown surfaced (P-UX-10), but I want to
   know which classes of misjudgment your verticals routinely
   hit so I can targeted-retrain.

2. **What workflow integration is still missing?** The
   Lightroom-side round-trip is V0.1 (read xmp:Rating back into
   PixCull annotations). Capture One? Bridge? DigiKam? Tell me
   what you reach for after PixCull and I'll write the bridge.

3. **What did you NOT see in the README that you wish it did?**

[GitHub issues](https://github.com/ChrisChen667788/pixcull/issues)
are open and bug templates are wired. Find me on
[X](https://x.com) / [即刻](https://okjike.com) if you'd rather
have a direct conversation.

— Chris Chen
[@ChrisChen667788](https://github.com/ChrisChen667788) ·
[@haozi667788 on ModelScope](https://www.modelscope.cn/profile/haozi667788)
