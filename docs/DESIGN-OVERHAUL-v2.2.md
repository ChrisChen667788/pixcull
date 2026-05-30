# UI/UX overhaul — "Taste" pass (v2.2)

A ground-up taste upgrade so PixCull *looks like a photographer made it*.
Synthesises two references:

* **Taste Skill** (`Leonxlnx/taste-skill`) — the anti-slop frontend
  framework.  We adopt its **soft / editorial** direction (calm,
  expensive, whitespace, premium type, spring motion) and its three
  dials — **DESIGN_VARIANCE**, **MOTION_INTENSITY**, **VISUAL_DENSITY**.
* **ByteDance design** — Semi Design's refined neutral palettes + density
  control, CapCut's media-first frosted-glass editor, Douyin/TikTok's
  "content is the hero, chrome recedes".

## Principles

1. **The photo/video is the hero.** Chrome recedes into a deep, calm
   gallery ground; surfaces sit *behind* the imagery, never competing.
2. **Calm & expensive, not loud.** Softer contrast, generous whitespace,
   layered soft shadows, refined violet accent that resolves into the
   brand gradient — no "bootstrap indigo", no flat gray dashboard.
3. **Editorial type.** Serif display for titles / hero numbers (magazine
   feel), refined system sans for UI.  Zero webfonts (offline-first).
4. **Frosted depth.** Translucent panels with `backdrop-blur` (header /
   transport / scrubber / side panels) — CapCut/iOS glass.
5. **Spring motion.** One signature overshoot curve
   (`cubic-bezier(.34,1.56,.64,1)`) on hover / selection / open; tasteful,
   not busy.  Honors `prefers-reduced-motion`.
6. **Three dials, user-tunable** (rollout): density (comfortable ↔
   compact), motion (calm ↔ rich), layout variance.

## What landed in this slice (✅)

Token-level refresh at the cascade point — `results.html :root`
(cascades through the whole 15k-line grid + lightbox via `var(--*)`):

| Token | before | after |
|---|---|---|
| `--bg` | `#1a1c20` flat gray | `#0d0e12` deep calm gallery ground |
| `--bg-card` / tiers | `#23262c` | `#16181f` + clearer elevation |
| `--accent` | `#6366f1` stock indigo | `#7c6cf5` refined violet (→ brand gradient) |
| `--radius-*` | 4/6/10/14 | 6/9/13/18 (softer, Semi/CapCut) |
| `--shadow-*` | tight | softer + wider "expensive" elevation |

The **video review surface** (`/video/<id>`) restyled to match: deep
ground + violet radial glow, **editorial serif title**, **frosted**
header / transport / scrubber / reel panels, spring-eased transport
buttons.

**Light theme parity** — the light `:root` was already a deliberately
warm paper-and-ink editorial palette, but its accent was still the old
bootstrap indigo (`#4f46e5`/`#6366f1`).  Moved it onto the brand violet
family: `--accent #5b4ee6` (a deeper violet, ~5.7:1 on white → AA body
text) with `--accent-hi` lifting to the exact dark-theme `#7c6cf5`, so
hover / borders / the hero gradient read as the *same* brand hue in both
themes.  Radii + motion already cascade from the shared `:root`; the
warm-amber light shadows are intentional and kept.  Re-shot
`12-light-theme.png` on the live Xiapu run (accent verified `#5b4ee6`).

**Other surfaces** — the shared `_DESIGN_TOKENS_CSS` block in
`serve_demo.py` (used by upload / history / admin / storage / face-audit)
still carried the *old* pre-overhaul palette (`--bg #1a1c20`, stock
indigo).  Moved it onto the same v2.2 tokens — deep `#0d0e12` ground,
violet `#7c6cf5` accent, softer radii/shadows, a warm-paper + violet
light override, plus a `--font-serif` token.  Retuned the standalone
roots too: the photo+video **timeline** (`#0a0b0d`/`#6E56CF` →
ground+violet) and four off-brand **`#3b82f6` blue** utility pages
(first-run / privacy / sample-collection / batch-classify → violet), the
landing-page "⚡ 示例数据" CTA (blue → violet), the PWA install-splash
`background_color`, and the internal audit/admin page backgrounds.  The
client-facing **share / portfolio** page keeps its signature purple→pink
brand-gradient (deliberately distinct, already premium).  Re-shot
`05-upload` / `07-history` / `10-admin-perf` / `15-bias` on the live run
(accent `#7c6cf5`, ground `#0d0e12` verified).

**Motion pass** — the app was already motion-rich (hero-reveal card
stagger via `--idx`, spring-eased card hover, frosted modal animations),
so this was surgical: the **lightbox / modal open** used the *flat*
curve, not the signature spring — switched `modalContentIn` to
`cubic-bezier(.34,1.56,.64,1)` (250ms, scale 0.97→1) so opening a photo
"pops" with a gentle overshoot (principle #5: one signature curve on
open).  The **lightbox scrubber thumb** now springs up (scale 0.6→1)
when the bar wakes on hover/active instead of just fading, and its glow
moved off hardcoded old-indigo onto `--accent-glow`.  All
`prefers-reduced-motion`-safe (durations already cut under that query).
*Bonus bug found while wiring this up:* `_buildLbFilmstrip` referenced an
undefined `visible` (line ~8958) → an uncaught `ReferenceError` on
**every** lightbox open that also aborted scrubber sync; fixed to
`_updateLbScrubber(_lbVisibleFns(), …)` (the same source `lightboxStep()`
uses).  Verified: the 934 KB inline script passes `node --check`; render
+ token validators green.

## Rollout (next slices)

- **Comfortable density default** — the grid card currently shows every
  axis chip at once (busy).  Default to a calm card (thumb + decision +
  score), reveal the 6-axis + canon chips on hover / selection; expose
  the VISUAL_DENSITY dial in settings.
- **The 3 dials as real settings** — persist per-user.
- **`03-lightbox` re-shoot** — the desktop lightbox screenshot is still
  pre-overhaul; programmatic capture is flaky against the demo server's
  HTTP/1.0 keep-alive (5 attempts stalled).  `13-lightbox-ipad` already
  shows the new-design lightbox; a fresh `03` is a follow-up.

## Verification

The whole README screenshot gallery (`docs/screenshots/01-19`) was
**regenerated on the live new design** from the real 200-photo Xiapu run
(grid / cmd-k / history / mobile / admin / light-theme / buckets /
marquee / confidence / attribution) + the 16-frame video run
(`18-video-review`, `19-video-grade`).  Pure CSS-token changes —
`test_5k_scale` (renders results.html) + `test_video_review` stay green.

(Lightbox `03` / tether `09` re-capture is flaky to automate — the
token cascade restyles them at render time; a fresh shot is a follow-up.)
