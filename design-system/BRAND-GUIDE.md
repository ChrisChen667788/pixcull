# PixCull Brand Guide · v0.10 AI draft

> **STATUS: AI-AUTHORED FIRST DRAFT.**  This document is Phase B
> deliverable #1, written by AI as a baseline.  A commissioned
> brand designer (see [Brief 01](briefs/01-brand-guide-brief.md))
> will replace this Markdown with a designed PDF that supersedes
> everything below.  Until then, this is the operational guide.
>
> Anyone using this in Phase B should treat it as **a checklist
> of decisions that need to be made**, not the final design
> language.

---

## 1 · Brand essence

**PixCull is the photographer's tool that gives them their
evening back.**

A wedding shoot is 1,500 photos and one shot at being there
for them.  PixCull doesn't replace the photographer's eye — it
replaces the part where the photographer culls 1,500 RAWs at
2 AM on the Tuesday after the wedding.

| Quality          | Word                | Anti-word              |
|------------------|---------------------|------------------------|
| Approach         | Local-first         | Cloud-AI               |
| Voice            | Photographer-peer   | Software-vendor        |
| Speed            | Coffee-time         | Magical                |
| Trust            | Auditable           | Black-box              |
| Aesthetic        | Editorial           | Generated              |
| Sound            | Quiet               | Buzzy                  |

These words are the test — every typographic / palette /
illustration / copy decision should resolve toward the left
column.

---

## 2 · Brand mark

### 2.1 · The visual concept

> *Five circles in a row.  Four small, muted.  One large, brand-
> gradient.  The fifth one is the keep.*

This is PixCull's job in one shape: from a row of similar
moments, surface the one frame that matters.

Current SVG sources live in [docs/brand/](../docs/brand/) — a
PHASE B brand designer should refine the curves + spacing but
preserve the metaphor.

### 2.2 · Variants required (Phase B designer to produce)

- **Primary** — full color, brand gradient on the 5th circle
- **Inverse** — same composition on light-theme background
- **Monochrome** — 1-color (currentColor) for embed / favicon
- **Mark-only** (the 5 circles, no wordmark) — for favicons + small UI
- **Wordmark-only** — "PixCull" text, with the "C" optionally
  styled to subtly nod at the spotlight metaphor

### 2.3 · Minimum sizes + clear space

| Variant | Min size  | Clear-space (every side) |
|---------|-----------|--------------------------|
| Mark-only | 16 × 16 px | = stroke-width |
| Wordmark-only | 60 × 14 px | = cap height |
| Full lockup | 120 × 30 px | = cap height × 2 |

### 2.4 · Anti-patterns

The brand mark is NEVER:
- Stretched non-uniformly
- Tilted off horizontal baseline (the 5 circles run horizontally;
  rotation breaks the "row of frames" metaphor)
- Filled with anything other than the brand gradient or
  monochrome
- Placed in patterns / tessellations
- Used as an icon adjacent to other-brand icons (the
  "spotlight" reads as a brand mark, not a generic glyph)

---

## 3 · Color system

### 3.1 · Dark theme (canonical)

PixCull is **dark by default** — photographers cull in dim
rooms; bright UI fatigues the eye on a Tuesday at 11 PM.

Surfaces — 4 elevation tiers:

| Token | Hex     | Use |
|-------|---------|-----|
| `--color-surface-bg`         | `#1a1c20` | App background (workspace gray, LR-inspired) |
| `--color-surface-bg-card`    | `#23262c` | Cards, tiles, modals |
| `--color-surface-bg-card-hi` | `#2a2e35` | Hover / raised state |
| `--color-surface-surface-3`  | `#34383f` | Inset blocks (inspector cells, code) |

Text — 4 levels:

| Token | Hex     | Use |
|-------|---------|-----|
| `--color-fg-primary`   | `#f1f3f7` | Body text, primary content |
| `--color-fg-secondary` | `#c5cad4` | Secondary labels |
| `--color-fg-muted`     | `#a8b2c1` | Captions, helper text |
| `--color-fg-muted-soft`| `#7a8696` | Disabled, subtle metadata |

Accent (the indigo workhorse, NOT the brand gradient):

| Token | Hex     | Use |
|-------|---------|-----|
| `--color-accent-default` | `#6366f1` | Primary CTAs, focused state |
| `--color-accent-hi`      | `#818cf8` | Hover state |
| `--color-accent-soft`    | `rgba(99,102,241,0.14)` | Tint backgrounds |
| `--color-accent-glow`    | `rgba(99,102,241,0.40)` | Drop-shadow accents |

Semantic — 5 states, each with base / tint / border:

| State    | Base    | Use |
|----------|---------|-----|
| success  | `#34d399` | Keep decisions, positive feedback |
| warn     | `#fbbf24` | Maybe decisions, soft warnings |
| danger   | `#ef6363` | Cull decisions, destructive actions |
| info     | `#38bdf8` | Helper info, neutral status |
| neutral  | `#a8b2c1` | Disabled, generic |

> **Phase B designer**: please refine these against WCAG AA on
> every text/surface pair.  Current values were chosen by feel,
> not measured.

### 3.2 · Light theme (companion)

Light theme is the warm-paper alternative for daytime work
(v0.9-P2-1 sand/cream palette):

| Token | Hex     |
|-------|---------|
| `--color-surface-bg` (light) | `#fbf9f5` |
| `--color-surface-surface-2` (light) | `#f0ebe1` |
| `--color-surface-surface-3` (light) | `#e6dfd2` |
| Border (light) | `#e3ddcf` (muted khaki) |
| Shadows (light) | `rgba(89, 54, 18, X)` — warm burnt-sienna |

> **Phase B designer**: these aren't yet in `tokens.json` ——
> migrate during the Phase A.1 light-theme lift, then
> tokens.json carries both themes as named theme-sets.

### 3.3 · Brand gradient · **the signature**

```css
linear-gradient(135deg, #6E56CF 0%, #A855F7 55%, #EC4899 100%);
```

Where it goes:
- Brand mark's 5th circle (always)
- Primary CTA on light theme (subtle)
- Score numerals when rendered hero-sized (`.ai-num` class)
- Loading bar fill
- QR code outer frame
- Executive PDF cover title

Where it NEVER goes:
- Body text
- Surfaces (it would be loud)
- Multiple places on the same screen (one signature moment per
  view, like Linear's lesson)
- Buttons that aren't the primary CTA

### 3.4 · The "Linear gradient" concern

The current stops are close to Linear / Stripe gradients.
Phase B designer should consider:
- **Option A** — keep current stops, lean into the
  recognisability of indigo→violet→pink as a category signal
- **Option B** — shift indigo stop cooler (`#5841C7`) +
  violet to royal-violet (`#9F3FD9`) + pink to peony
  (`#EE3F8A`) for a slightly more distinctive feel
- **Option C** — radical re-mix (a designer's choice — they
  may surprise us)

**Recommendation**: Option B in Phase B; Option C in Phase C
alongside the typeface refresh.

---

## 4 · Typography

### 4.1 · Current stack (system-only)

| Token | Stack |
|-------|-------|
| `--font-family-display` | Inter Display, Inter, -apple-system, BlinkMacSystemFont, Segoe UI Variable, PingFang SC |
| `--font-family-body`    | Inter, -apple-system, BlinkMacSystemFont, Segoe UI, PingFang SC |
| `--font-family-mono`    | ui-monospace, SF Mono, JetBrains Mono, Menlo |
| `--font-family-serif`   | Charter, Iowan Old Style, PT Serif, Source Serif Pro, Cambria, Georgia, Songti SC |

### 4.2 · Phase B target stack

Replace `Charter` system-fallback with a real downloadable serif:

```css
--font-family-serif:
  "Editorial New", "Charter", "Iowan Old Style", "PT Serif", serif;
```

[Editorial New](https://www.pangrampangram.com/products/editorial-old) is
free for commercial use via [Fontshare](https://fontshare.com/);
designer should verify license + commit a self-hosted woff2
under `static/fonts/`.

### 4.3 · Size + line-height ramp

| Token | Size  | Use |
|-------|-------|-----|
| `--font-size-hero`  | 28 px | h1, hero numerals (consider 32-36 px in serif for `/share` portfolio) |
| `--font-size-h2`    | 18 px | Section heads |
| `--font-size-h3`    | 14 px | Sub-section heads, modal titles |
| `--font-size-body`  | 13 px | Body text |
| `--font-size-small` | 11.5 px | Labels, chips |
| `--font-size-tiny`  | 10.5 px | Footnotes, micro-meta |

| Token | Value | Use |
|-------|-------|-----|
| `--font-lineheight-tight`  | 1.25 | Headlines (h1, h2) |
| `--font-lineheight-normal` | 1.55 | Body |
| `--font-lineheight-loose`  | 1.7  | Long paragraphs (advice text in inspector) |

### 4.4 · Numerals — the brand's quiet asset

PixCull is a numbers-heavy product (recall@5, score_final,
keep ratio, 6-axis stars).  **Make the numerals carry weight.**

Rules:
- Every number column uses `font-feature-settings: "tnum" 1;`
  (tabular numerals — no width jitter)
- Hero numerals (score_final on `/share` portfolio + executive
  PDF cover) use the serif font + `font-weight: 600` + the brand
  gradient as `background-clip: text` fill
- "AI number" class (`.ai-num` in results.html) — already
  defined in tokens; reuse aggressively, don't reinvent
- Slashed-zero (`zero` OpenType feature) at sizes < 12 px to
  disambiguate 0 from O

### 4.5 · CJK companion (Phase C scope)

For Chinese / Japanese / Korean script coverage at v1.0:

- Chinese: `PingFang SC` (Apple, ships free with macOS/iOS) +
  `Noto Sans SC` (Google, free) fallback
- Japanese: `Hiragino Sans` (Apple) + `Noto Sans JP` fallback
- Korean: `Apple SD Gothic Neo` (Apple) + `Noto Sans KR`
  fallback
- Spanish: covered by Latin Extended-A in any of the above

Phase C deliverable (Brief 04) bundles a custom `PixCull Sans`
that ships all 5 scripts in one variable font — eliminating
the cross-platform fallback maze.

---

## 5 · Motion identity

### 5.1 · The signature curve · `pixcull-overshoot`

```css
/* Use this 99% of the time */
cubic-bezier(0.34, 1.56, 0.64, 1)
```

What it does: lands the transition with ~6% overshoot at y ≈ 1.04
then settles back to 1.0.  Same family as Linear, Stripe,
Apple Photos.  Makes every UI element feel "alive" rather than
"competent".

Where to use:
- Modal entrance + exit (yes, both directions)
- Filter chip toggle
- Card hover lift
- Score radial fill
- Sidebar open/close
- Lightbox open
- Any "show me you noticed I clicked" moment

Where NOT to use:
- Loading bars / progress fills (overshoot misleads — use
  `pixcull-overshoot-flat` = `cubic-bezier(0.16, 1, 0.3, 1)`)
- Data-bar widths (overshooting a 45% bar to 47% lies about data)
- Continuous animations (heartbeat loops, etc.)

### 5.2 · Duration scale

| Token | Value | Use |
|-------|-------|-----|
| `--motion-duration-fast`   | 120 ms | Micro-interactions (chip toggle, hover) |
| `--motion-duration-normal` | 220 ms | Modal entrance, drawer open |
| `--motion-duration-slow`   | 320 ms | Hero reveal stage transitions |

**Two-second budget for any single "moment"** — beyond 2s the
user starts to feel slow.  v0.9-P0-2 hero reveal is 2.0s with
4 staggered stages; that's the ceiling.

### 5.3 · Reduced motion

Every animation respects `prefers-reduced-motion: reduce`:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 1ms !important;
    transition-duration: 1ms !important;
  }
}
```

Already wired in results.html.  Maintain in any new component.

---

## 6 · Voice & tone

See [VOICE-AND-TONE.md](VOICE-AND-TONE.md) — companion document
with 30+ DO/DO-NOT examples.  Short version:

| Quality | DO write | DON'T write |
|---------|----------|-------------|
| Greeting | "你的 1,500 张照片在分析…" | "Hello! Welcome to PixCull™!" |
| Tooltips | "按 1 标 keep" | "Click to set decision to keep" |
| Error states | "DeepSeek 没回应,这次先跳过解释" | "An error occurred. Please try again." |
| Loading | "正在过 6 轴评分" | "Loading…" / "Processing…" |
| Empty state | "上传第一批照片,这里就有片单了" | "No data available" |
| Confirmation | "把 12 张放进 '婚礼-keep' 桶?" | "Are you sure you want to proceed?" |
| Settings | "DeepSeek API key(可选)" | "Configure your DeepSeek API integration" |

### Anti-patterns to grep + reject

Words that should NEVER appear in PixCull UI:
- "powered by AI" / "AI-powered"
- "magical" / "magic"
- "intelligent" / "smart"
- "next-generation"
- "revolutionary"
- "seamless"
- "leverage" / "utilize" (use "use")
- "Welcome to" / "Get started with"

The product speaks the same way a photographer who happens to
write code would speak — never the other direction.

---

## 7 · Iconography

### 7.1 · Phosphor as baseline

[Phosphor Icons](https://phosphoricons.com/) — 1.5–2 px stroke,
24 px nominal, MIT-licensed.  Phase B should standardise on
`stroke-width: 1.8` for all UI icons.

Replace ALL of these:
- `🪣` `📡` `🏆` `📷` `✎` `✓` `?` `✕` etc.
- Every inline `<svg>` that's a UI icon (not an illustration)
- Every emoji that survived v0.9-MARKETING

With matching Phosphor glyphs:

| Current | Replace with Phosphor |
|---------|----------------------|
| 🪣 buckets | `<ph-bucket weight="duotone">` |
| 📡 协作中 | `<ph-broadcast weight="bold">` |
| 🏆 burst peak | `<ph-medal weight="bold">` |
| 📷 photographer | `<ph-camera weight="duotone">` |
| ✎ editor | `<ph-pencil-line weight="bold">` |
| ✓ keep | `<ph-check-circle weight="fill">` |
| ✕ cull | `<ph-x-circle weight="fill">` |
| ? maybe | `<ph-question-mark weight="bold">` |

### 7.2 · Custom (5 only)

Reserved for **strictly brand-essential** glyphs that don't
exist in Phosphor:

1. **The spotlight brand mark** (the 5-circle row)
2. **Score radial dial** (the v0.9-P1-4 .score-radial)
3. **Share link / QR brand frame**
4. **AI sparkline glyph** (mini version for use in inline text)
5. **Portfolio arrow** (the "→ next chapter" in /share)

All five live as custom `<symbol id="icon-pixcull-*">` blocks
defined once at the top of results.html.

---

## 8 · Photography

When PixCull renders photography in marketing material
(screenshots, press kit), the photography itself should be
on-brand:

- **Light**: natural, late-afternoon golden hour OR morning
  blue hour — never harsh midday flash
- **Subject**: real human moments (a kiss, a laugh, a quiet
  observation) — never staged or stocky
- **Composition**: editorial — wide breathing room, decisive
  framing, not centered
- **Color**: warm but not orange-graded (Z-gen "muted vintage"
  trend is overdone)
- **Diversity**: real-world ethnic / age / venue diversity ;
  PixCull users shoot global weddings

Phase C Brief 06 (Press kit) commissions a small photo
shoot for marketing visuals.  Until then, use the 2022
川西行 + the user's own wedding photos (consented).

---

## 9 · Layout grid + spacing

8 px base grid.  All spacing on multiples of 8 (with sub-grid
of 4 for chip-internal padding).

| Token | Value | Use |
|-------|-------|-----|
| `--spacing-1` | 4 px  | Sub-grid (chip internal) |
| `--spacing-2` | 8 px  | Tight gap |
| `--spacing-3` | 12 px | Default gap |
| `--spacing-4` | 16 px | Card padding |
| `--spacing-5` | 20 px | Section gap |
| `--spacing-6` | 24 px | Major section gap |
| `--spacing-7` | 32 px | Hero spacing |
| `--spacing-8` | 48 px | Page-level top padding |

### Touch targets

44 × 44 px minimum (Apple HIG).  Smaller is acceptable on
desktop hover-able UI but never on mobile / iPad.  v0.7-P1-2
inspector bottom-sheet redesign honored this; future work
must too.

---

## 10 · Component preview gallery

See `design-system/figma/` for the visual gallery (Phase B
Brief 03 deliverable).  Until that lands, the live product
at `/results/<run_id>` is the gallery — see
[docs/screenshots/](../docs/screenshots/).

---

## 11 · Decision matrix · when this guide doesn't say

If you're making a UI / visual decision the guide doesn't cover:

1. **Does it reinforce "photographer-peer" voice?** YES → ship it
2. **Does it stay "local-first / quiet"?** YES → ship it
3. **Would Linear / Stripe do this?** YES → reconsider; we want
   to be next-door to them, not copies
4. **Would Apple Photos do this?** YES → ship it (Apple Photos
   is our spiritual sibling)
5. **Default**: ship the option that requires the fewer pixels
   on screen.  Quietness is the brand.

---

## 12 · Phase B handoff checklist

When the human brand designer takes this brief over:

- [ ] Replace this Markdown with `BRAND-GUIDE.pdf` (designed PDF,
      60-100 pages)
- [ ] Refine palette options A/B/C above; commit chosen one to
      `tokens.json`
- [ ] Select Phase B serif (Editorial New or alternative)
- [ ] Decide on Phase C custom typeface roadmap
- [ ] Audit all current UI for "AI-vocabulary" anti-patterns
- [ ] Document brand mark variants + lockups; deliver SVG sources
- [ ] Photo-shoot direction for press kit
- [ ] Standardise Phosphor stroke-width across all UI icons
- [ ] Render Figma component gallery matching this guide

---

*v0.10-AI draft · 2026 Q4 · expected to be superseded by Phase
B's commissioned brand-guide PDF in v0.12.*
