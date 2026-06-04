# v2.3 — UI overhaul charter (grounded in the *real* taste-skill)

> Status: **PLAN** (not yet executed).  Written after actually cloning
> `github.com/Leonxlnx/taste-skill` (20.3k★, MIT) this session and
> reading its `skills/*/SKILL.md`, not just the README.

## 0. Which skill actually applies (and which does NOT)

The repo ships several skills.  Picking the right one is the whole game:

| Skill | Use here? | Why |
|---|---|---|
| **`redesign-skill`** (redesign-existing-projects) | ✅ **master protocol** | "Audit an existing app, fix generic patterns, keep the stack, *small targeted improvements over big rewrites*." Has an explicit fix-priority order. PixCull is an existing vanilla-CSS app — this is exactly our case. |
| **`soft-skill`** (high-end-visual-design) | ⚠️ **borrow component craft only** | Premium fonts, Double-Bezel nested cards, tinted shadows, spring motion, scroll-entry, magnetic hover — yes. Its *layout* (full-screen hero, `py-40`, asymmetric Bento, Z-axis cascade with rotations) is a **$150k marketing-agency** language that would actively hurt a 200-photo culling tool — **no**. |
| **`minimalist-skill`** (Notion/Linear editorial) | ✅ secondary reference | The calm/editorial register is the right *tool* aesthetic. |
| **`taste-skill`** (default v2) | ◑ dials + discipline only | Its own header says: *"Not dashboards, not data tables, not multi-step product UI."* PixCull's grid **is** that. Take its **3 dials** + brief-inference discipline; ignore its landing-page rules. |

**Design read** (taste-skill §0.B):
> *Reading PixCull as a **local-first professional photo/video culling tool** for working photographers (data-dense product UI, not a marketing site), with a **calm editorial — Lightroom-meets-Linear** language, leaning toward **the existing vanilla CSS + redesign-skill audit + soft-skill component craft**.*

## 1. Dials (taste-skill §1 — "redesign · overhaul" row = VARIANCE +2, MOTION +2, DENSITY match)

| Dial | Value | Rationale |
|---|---|---|
| `DESIGN_VARIANCE` | **4** | A culling tool must stay scannable and predictable; the *photo* is the content. Modest asymmetry (offset headers, varied radii) — not artsy chaos (the soft-skill default of 8 is for agency sites). |
| `MOTION_INTENSITY` | **5** | Spring on hover/select/open + staggered scroll-entry. Not cinematic/physics — that slows a fast cull pass. |
| `VISUAL_DENSITY` | **4** grid / **6** 详尽 | redesign-skill explicitly: *"dense layouts work for data dashboards."* The v2.2 calm card is already ~3; the 详尽 dial is ~6. Keep both, default calm. |

## 2. Audit (redesign-skill) — what's *actually* generic in PixCull today

Honest, including what my v2.2 token pass kept or introduced:

- **TYPE — Inter everywhere.** `--font-display` and `--font-body` are both Inter. This is soft-skill's **#1 banned font** and redesign-skill's **#1 fix** ("biggest instant improvement, lowest risk"). Scores/counts aren't consistently tabular.
- **COLOR — the purple→pink brand gradient (`#6E56CF → #A855F7 → #EC4899`) + violet accent is the "AI gradient fingerprint"** redesign-skill names as *"the most common AI design fingerprint."* We also run **more than one accent** (violet + tri-stop gradient + 6 semantic colors). The audit prescribes: pick **one** considered accent, desaturate (<80% sat), tint shadows, and retire the tri-stop gradient from app chrome.
- **SURFACE — generic cards** = background + 1px gray border + shadow (redesign-skill: "cards should exist only when elevation communicates hierarchy"). Shadows are pure-black-at-low-opacity, not tinted.
- **LAYOUT — always-left-sidebar dashboard** (explicitly flagged). Defensible for LR-style culling, but: no max-width container on ultrawide, symmetrical vertical padding, uniform radii.
- **MOTION — linear/ease transitions still exist**; entry is a one-shot hero reveal, not scroll-driven; no magnetic hover.
- **ICONS** — mixed inline SVGs; standardize stroke weight, move toward Phosphor-light.
- **STATES** — some spinners instead of skeleton loaders; empty states are good (MiniMax art); confirm no `alert()` error paths remain.
- **COPY** — scan for AI clichés ("Seamless/Elevate/Next-Gen"), exclamation marks in success toasts, Title Case headers.

## 3. Plan — in redesign-skill's fix-priority order (lowest-risk first)

**P0 — biggest win, lowest risk**
1. **Font swap.** Vendor an **OFL/OSS** premium family *offline* (PixCull is offline-first, zero webfonts): **Geist** or **Outfit** (both SIL-OFL — vendorable as woff2 in-repo, ~30–80 KB each). Avoid Satoshi/Cabinet/Clash (restrictive licenses). Pair: a variable **serif display** (Charter is already system-available) for hero numbers/titles + Geist/Outfit for UI. Add `font-variant-numeric: tabular-nums` to every score/count.
2. **Color cleanup.** Choose **one** restrained, desaturated accent; neutralize the base to a single gray family; **tinted** shadows (carry the bg hue). Retire the tri-stop purple→pink gradient from app chrome (confine to the client-facing share page at most). Evaluate an **Editorial-Luxury** option (warm espresso/cream + one ink accent) — it suits a photography brand and is the furthest from the AI-purple tell.

**P1 — component craft (soft-skill, tool-appropriate)**
3. **Hover / active / focus** — spring transitions; `active:scale(.98)`; visible focus rings everywhere (a11y, not optional).
4. **Card craft** — Double-Bezel (outer shell + inner core, concentric radii) on the lightbox/inspector + bucket/share cards; drop the generic grid-card border; tinted shadows; varied radii (tighter inner, softer outer).
5. **Motion** — `IntersectionObserver` staggered blur-fade scroll-entry (replace the one-shot hero reveal); magnetic hover on primary CTAs; spring lightbox/scrubber (already shipped in v2.2).

**P2 — polish**
6. **Layout** — max-width container (1440px) on ultrawide; optical (asymmetric) vertical padding; offer a collapsible-sidebar / ⌘K command-menu alternative to the permanent left panel; semantic-HTML pass (`<nav>/<main>/<aside>`).
7. **Type scale** — display tracking (negative on big headers), sentence case, `text-wrap: balance` on headings.
8. **States** — skeleton loaders shaped like the card; audit loading/empty/error coverage.

## 4. Honest tensions — owner decisions before building

1. **Brand vs anti-slop.** redesign-skill flags the purple→pink gradient as *the* AI fingerprint, but it was PixCull's entire brand identity. **DECIDED (owner, this session): option (b) — re-brand to an Editorial-Luxury warm palette: cream / espresso surfaces + a single restrained ink/brass accent; retire the tri-stop purple→pink gradient and the violet accent entirely.** This is the furthest from the AI-purple tell and reads as paper-and-ink / film — a photographer's register.
   - **Dark (primary — photos live on a dark ground):** warm espresso-charcoal base (not cool neutral black), cream-tinted text, one warm accent (brass/cream), warm-tinted shadows.
   - **Light:** true cream paper + espresso ink text + the same single accent.
   - Semantic keep/maybe/cull stay (functional), but desaturated to sit in the warm system.
2. **Offline-first vs premium webfonts.** The skill assumes Geist/Satoshi are network-available. PixCull ships offline. → **vendor a woff2 in-repo** (small size cost) or stay on a premium *system* stack. Recommend vendoring Geist (OFL).
3. **Tool density vs agency whitespace.** We deliberately reject soft-skill's `py-40`/hero/Bento — those are for landing pages and would break a dense culling workflow. The dials above keep it tool-appropriate.

## 5. Sequencing & guardrails

- Ship as **v2.3 "UI overhaul"**, slices P0 → P2, each: keep the vanilla stack, **test gate green**, **screenshot-verify** on the live 200-photo Xiapu run, no functional regressions.
- **Regenerate the README/ModelScope screenshot gallery ONCE at the end** (batch sync — the gallery is currently stale vs the v2.2 calm cards already).
- redesign-skill rule we honor throughout: *"Do not break existing functionality. Small, targeted, reviewable changes over big rewrites."*

## Reference

`github.com/Leonxlnx/taste-skill` — MIT.  Cloned and read this session
(`skills/redesign-skill`, `skills/soft-skill`, `skills/taste-skill`,
`skills/minimalist-skill`).  Install path for future sessions:
`npx skills add https://github.com/Leonxlnx/taste-skill --skill redesign-skill`.

## Status & handoff (resume here in a fresh session)

**DONE + pushed to main:**
- **P0 colour** — editorial-warm rebrand: `ae479f5` (espresso surfaces +
  retire purple→pink gradient) + `e34fb70` (accent gold→warm graphite /
  espresso ink).  Both results.html + serve_demo.py; 0 purple literals.
- **P0-1 type** — `bd29228`: vendored **Geist** (OFL woff2 at
  `docs/brand/geist-variable.woff2`, served via `/docs/brand/` route,
  `.woff2`→`font/woff2` mime added), `@font-face` in results.html +
  shared `_DESIGN_TOKENS_CSS`; stacks lead with "Geist Variable"; 0 Inter.
- **P1 craft** — `4e2af25`: Double-Bezel cards (photo inset in a tray,
  concentric radius + inset edge) + `:active` press scale + global
  `:focus-visible` ring.
- **P1 motion** — `2f9f142`: blur-fade card entry (heroCardUp blur 5→0,
  one-shot/reduced-motion-gated) + magnetic primary CTA + swept 21
  spaced `rgba(110, 86, 207 …)` purple leftovers the no-space passes
  missed.
- **P2 CSS** — `8b35d7a`: max-width 2400px container (centered) +
  `tabular-nums` (header counters / 6-axis scores / sidebar filter
  counts) + de-all-caps the LIBRARY label.  (Optical asymmetric padding
  + a shimmer skeleton already existed — grid is top 20 / bottom 48px;
  `.card-placeholder` uses `pcPlaceholderShimmer` — so nothing to add.)
- **design-system tokens** — `ac0a60b`: `design-system/tokens.json` (the
  multi-target source of truth) + regenerated `tokens.css` / iOS
  `BrandTokens.swift` / `tokens.python.json` rebranded to editorial-warm;
  `make tokens-check` reports all targets in sync.

**DONE — gallery (mostly):** `6ebfd94` re-seeded the 198-photo Xiapu run
(drive remounted at `/Volumes/One Touch 1/100CANON`, symlinked 198 →
`pixcull run … --scene landscape`) and regenerated **14** screenshots on
the new design (01 grid · 02 cmd-k · 03 lightbox · 05 upload · 07 history
· 08 mobile · 09 tether · 10 admin · 11 buckets · 12 light · 13 ipad-lb ·
14 marquee · 15 bias · 16 confidence), then `make modelscope-sync` (21/21
hosted, README renders, verified HTTP 200).  **Lesson:** the bash
`capture_real_screenshots.sh` server choked under rapid Playwright load
(HTTP/1.0) and wrote 19307-byte blanks — use a **per-shot harness with a
content-guard + retry + skip-on-fail against one pre-warmed server**
(see `/tmp/shot_gallery.py` pattern) instead.

**DONE — stragglers (`c87ffc4`, ModelScope-synced, verified HTTP 200):**
- **18 / 19 video-review + grade** — re-seeded `videodemo` from a REAL
  7.5-min clip (`我的城 我的家1.mp4` → `pixcull video --interval-s 4` →
  113 frames + temporal + reel + audio); 19 with the Kodak Vision3 LUT.
  Shown frames = title card + aerial scenery (no identifiable faces);
  extracted frames stay local in /tmp, only the 2 PNGs are public.
- **17 attribution-heatmap** — warm axis-tab + heatmap overlay re-injected
  on the lightbox.
- **06 share-portfolio** — re-shot BOUNDED (was a 25,760px / 20MB
  full-page) → 2560×3200 ~5MB.  The share page keeps its distinct
  (now-brass) brand gradient by design.

- **04 ab-compare** — DONE.  Solved the closure-fn problem by driving
  the real UI: hover + `force`-click two cards' `.card-cmp-btn`
  (`pinForCompare` A→B → `openCompareCustom`, which runs in page scope so
  the closure resolves).  Shows the A/B modal with two real Xiapu frames
  on the warm design.

**All 19 gallery screenshots (01–19) are now on the editorial-warm +
Geist + Double-Bezel design and synced to GitHub + ModelScope.**

Optional deeper P2 (low value, skip unless asked): per-thumbnail
skeleton; `text-wrap: balance` on headings.

**Caveats for the next session:**
- `tests/test_5k_scale.py::test_5k_scale_parse_under_2_seconds` is a pure
  CSV-parse-*speed* assertion that flakes on a loaded box (saw 4–6s vs
  the 2s threshold this session).  Unrelated to any UI change — run the
  gate with `-k "not under_2_seconds"` or on a quiet machine.  (Worth
  hardening: it's an environment-fragile timing test.)
- `serve_demo.py` is an HTTP/1.0 toy server — flaky under load; use
  `wait_until="commit"` + a `rows`/card-count `wait_for_function` in
  Playwright, and kill stray `serve_demo`/`chromium` between runs.
