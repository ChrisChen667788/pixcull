# Show HN: PixCull — local-first AI photo culling for working photographers

*A weekend-side-project that grew into the AI culling tool I wish had
existed when I started shooting.*

## The problem

A typical wedding produces ~1,500 frames. A landscape day-hike, ~600.
A wildlife morning, easily 2,000.

Every one of those passes through the photographer's mental decision
tree twice: a fast "keep this one?" pass, then a slower "which of these
five near-identical bursts do I publish?" pass. Six hours of Lightroom's
library module is a normal post-event evening.

The first pass is where AI helps. Burst-peak picking, focus-miss
detection, eyes-closed detection, exposure sanity — solved problems if
you wire them right. There are 5+ commercial "AI culling" SaaS apps now
charging $20–50/month each.

But all of them make three trade-offs working photographers shouldn't
have to swallow.

## 1. They upload your photos

Wedding contracts often explicitly forbid third-party cloud processing
of client images. Journalism NDAs do too. Editorial sports has embargo
windows. Wildlife photographers of protected species can't legally share
location data, which embeds in EXIF, which embeds in any uploaded file.

The SaaS pitch is "your photos are safe with us." The reality is they're
on someone else's server, subject to that company's business model,
training pipeline, and legal jurisdiction. For many real workflows
that's a deal-breaker.

## 2. They give you a score, not a reason

The popular AI culling apps produce a single 0..1 confidence number per
photo, sorted descending. You're supposed to trust it.

But if your client asks "why didn't you pick this one?" — or you're
trying to internalize the rubric yourself — a 0.43 number is useless.
You need:

- Which axis is weak? Sharpness? Composition? Light? Moment?
- How does this compare to its burst-cluster neighbors?
- What's the canonical rationale? (Cartier-Bresson's decisive moment?
  Adams' Zone System exposure? Rule of space?)

A score-only system gets you to a deliverable but doesn't teach you
anything. That's a wasted opportunity per shoot.

## 3. They live outside your tooling

Lightroom, Capture One, Photo Mechanic — that's where the real work
happens. Catalog operations, develop settings, color labels, keyword
tagging, IPTC captions, client galleries.

A walled-garden web app forces a context switch every batch. The
photographer's reaction is sensible: "if the tool doesn't write XMP
sidecars and my Lr catalog won't see the decisions, I'd rather just
open Lightroom and cull manually."

## PixCull

PixCull is the alternative I built over 18 months of small commits.
**Local-first, six-axis rubric, native XMP sidecars + iOS swipe
companion + Lr/C1 tether mode + multi-user profiles + multi-shooter
event merge.** MIT-licensed. Source at
[github.com/ChrisChen667788/pixcull](https://github.com/ChrisChen667788/pixcull).

What's distinct:

- **Local-first.** RAW decode, scoring (CLIP + InsightFace + MediaPipe
  + a per-axis rescorer), faces, GPS clustering — all on-device. The
  optional DeepSeek meta-judge runs against *your* API key. Photos
  never leave your disk.
- **6-axis rubric.** Every frame scores stars on technical, subject,
  composition, light, moment, aesthetic — each with a rationale and
  a citation to canon (Adams' Zone System, Rule of Thirds,
  Cartier-Bresson decisive moment, etc). The lightbox shows a 4-source
  breakdown (auto / model / VLM / human) so you see exactly when the
  rubric is unsure.
- **Sidecar-native.** XMP files land where Lightroom expects them.
  IPTC captions auto-compose from scene + face labels + location +
  advice. Standalone HTML gallery export. iOS swipe companion. Lr/C1
  tether watcher.
- **Reasoning surfaced.** "Cull because focus_miss" is a first-class
  taxonomy. The reject-reason picker re-orders by *your* historical
  frequency. Per-axis confidence intervals show ± stddev so the user
  sees which axes are well-calibrated and which are guesses. The admin
  page surfaces *your* taste profile — which axes you actually weight
  when keeping vs culling.

## What I learned building it

**The rescorer matters less than the rubric.** I spent six weeks
training a 6-axis regressor thinking it would be the keystone. Shipped
it, but discovered the *advice envelope* — short verdict + cited
strengths/weaknesses — is what makes users trust the tool. Numbers
don't build trust; sentences that match what you'd write yourself do.

**Pro photographers are extreme power users.** I shipped keep/maybe/cull
at 1/2/3 hotkeys. Got immediate feedback from working shooters: "where's
F for flag? where's [/] for verdict up/down? where's G for cluster nav?
where's Backspace for undo+back?" Photo Mechanic has trained two
decades of muscle memory. PixCull now ships exactly those bindings.

**1:1 zoom in the lightbox is non-negotiable.** Without focus check at
100%, the tool isn't usable for serious work. Took two weeks to land
right because synced zoom across A/B compare cells needed a normalized
pan coordinate system to handle different aspect ratios.

**Open-sourcing forces clarity.** Pre-launch audit: my internal strategy
notes go. My personal photo training labels need sanitizing (sha1-hash
filenames). The exercise of "what's actually safe for public eyes"
surfaces what you should never have collected in the first place.
Honest moment.

## What's missing (deliberately)

- **Edit/develop** — Lightroom + Capture One own that. PixCull writes
  XMP that Lr's develop module respects.
- **Cloud hosting** — sync via folder mirror over iCloud/Dropbox/NAS.
  Anything more is someone else's job.
- **Multi-shooter merge across vendors** — works across PixCull runs
  (INFRA-3); cross-tool merge is a 5-year problem.
- **Auto-tagging at LAION scale** — advice is canon-cited, not
  embedding-based "automatic tags." More signal-to-noise per word,
  less coverage.

## Try it

```bash
git clone https://github.com/ChrisChen667788/pixcull.git
cd pixcull
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/serve_demo.py
# open http://127.0.0.1:8770
```

First run warms the models (~30s on Apple Silicon), then ~1s/photo on
M2 Pro. Or via Docker:

```bash
docker compose up --build
```

## What's in the v0.7-v0.8 release

Since the original draft of this post the product has shipped 22
slices across two charters. The headline additions:

- **Style clone V1 + V2** — give it 5-20 of your past keepers, it
  learns your personal style fingerprint (median per axis + scene
  mode in V1, CLIP-embedding centroid in V2). New runs surface a
  "🎨 风格距离" chip per photo + sort "像我风格的优先". Local-only:
  the model lives in `<run>/output/style_profile.json`.
- **Tethered live scoring** — point PixCull at your Lr/C1 tether
  folder, new RAWs analyze on landing, the grid refreshes live.
  Built for the second-shooter "show the client a preview during
  the shoot" workflow.
- **LAN collaboration** — host issues a token, second-shooter /
  editor opens the URL, every 5s their grid syncs your annotations.
  Conflict markers when both edit the same photo. Pure local,
  no cloud.
- **Client share links + QR** — instead of zipping a gallery, the
  host clicks 🔗 → gets a short link + a QR. Client scans with
  their phone, opens the keeps in any browser. No download, no
  install, watermark + photographer signature in the header.
- **Lightroom-Library + Lightroom-Develop UX** — left sidebar
  with 8 collapsible filter groups (decision / scene / style /
  faces / location / bursts / cull-reason / active-learning), right
  Inspector with 9 collapsible sections (★ scores / similar / AI
  judgment / matrices / etc.), mobile bottom-sheet variant.
- **i18n** — switch zh / en / ja with a single chip in the
  workspace bar. 154 strings localised; remaining migrations
  underway in v0.9.
- **Loupe RGB readout** — 1:1 zoom mode follows the cursor with
  R/G/B/Hex/Y(luminance) for the pixel underneath. LR / PS parity.
- **Hold-Space cheat sheet** (macOS Finder pattern) — press &
  hold Space for 350ms, a context-aware shortcut strip surfaces.
  Tap-Space still toggles the lightbox.
- **Structured CSV / JSON export** — beyond the raw scores.csv,
  merged with annotations + style distances per row.
- **5k+ photo stability** — IndexedDB adapter for annotation state,
  observer throttling, adaptive lazy-load. Runs comfortably on a
  16GB M2 Pro at 5000 photos.

97 unit tests across i18n / sync / style / shortlink / QR encoder
/ CLI audit / 5k smoke pass. Charter trail in `docs/ROADMAP-v0.4-
charter.md` → `-v0.7-` → `-v0.8-`.

## What I'd value feedback on

1. **Where does the rubric obviously misjudge a photo?** The per-source
   breakdown is surfaced (inconsistency badges), but I want to know
   which classes of misjudgment your verticals routinely hit so I can
   targeted-retrain.
2. **What workflow integration is missing?** The Lr round-trip reads
   xmp:Rating back into PixCull annotations. Capture One? Bridge?
   DigiKam? Tell me what you reach for and I'll write the bridge.
3. **What did you NOT see in the README that you wish it did?**
4. **Style clone V2 — does it actually learn YOUR style?** Train
   it on 10-20 of your past keeps, then run a fresh event. Tell me
   how the "风格距离" sort feels — is it surfacing keeps you'd
   actually pick, or just same-axis-stars look-alikes?

Issues at https://github.com/ChrisChen667788/pixcull/issues — bug
templates are wired.

— Chris Chen (former AI architect at Tencent / SenseTime / Hikvision,
now mostly a 视觉中国 + 图虫 signed photographer who got tired of
spending an evening per shoot in Lightroom)

---

## For platform editors / re-posters

**Short pitch** (180 chars):
> Local-first AI photo culling for working photographers. Burst-peak
> picking + style clone + tethered live scoring. No cloud upload,
> no monthly fee. Lightroom round-trip. Apache-2 / brew install.

**Tags**: `#photography` `#opensource` `#machinelearning` `#localfirst`
`#lightroom` `#wedding-photography` `#computer-vision`

**Hero image suggestion**: docs/screenshots/results-v0.8-grid.png
(showing the LR Library sidebar + grid + style-distance chips)

