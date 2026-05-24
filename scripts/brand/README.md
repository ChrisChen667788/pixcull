# PixCull brand kit

Generates the brand visuals embedded in `README.md`, the ModelScope studio
page, and any external marketing surface.  Two paths — pick based on
whether you have a Minimax image API key.

```
scripts/brand/
├── pixcull-brand.json          ← single source of truth for project name,
│                                 mascot prompt, palette, tagline, …
├── gen_brand_svg.py            ← path A: no AI, pure SVG (today's default)
├── gen_animated_demo.py        ← animated SVG hero-reveal demo for README
├── gen_mascot.mjs              ← path B step 1: Minimax-AI mascot art
├── overlay_wordmark.mjs        ← path B step 2: Playwright wordmark overlay
├── PROMPTS-REFERENCE.md        ← prompt-engineering cheatsheet (path B)
└── OVERLAY-REFERENCE.md        ← HTML overlay knobs (path B)
```

Output lands in `docs/brand/`:

| File | Aspect | Use case |
|---|---|---|
| `pixcull-horizontal-lockup.svg` | 16:9 (1280×720) | **GitHub README hero** / Notion / Slack header |
| `pixcull-vertical-poster.svg`   | 9:16 (720×1280) | 小红书 / 抖音 / iPhone wallpaper |
| `pixcull-mark-only.svg`         | 1:1  (1024×1024) | Sticker die-cut / monogram / favicon |
| `pixcull-hero-reveal-demo.svg`  | 16:9 animated   | Inline animated demo in README |

---

## Path A — pure-SVG (no AI, no Playwright, no API keys)

Default since v0.9-MARKETING.  Produces 4 polished SVG variants in ~50ms.
Uses the v0.9-P0-3 brand identity:

- Logo: "spotlight on one in a crowd" (4 muted circles + 1 large gradient circle)
- Wordmark: serif (Charter / Iowan Old Style / PT Serif fallback stack),
  with `Cull` half in the signature `#6E56CF → #EC4899` gradient
- Background: radial cosmic (`bgCosmic → bgMid → bgDeep`)
- Animated demo: SMIL keyframes replaying the v0.9-P0-2 hero-reveal sequence

```sh
# Regenerate all 4 brand SVGs from pixcull-brand.json
python scripts/brand/gen_brand_svg.py
python scripts/brand/gen_animated_demo.py
```

Output is deterministic — git diffs are stable, palette tweaks reflect in
seconds.  This is the "ship today" path and what `README.md` references.

---

## Path B — AI mascot + real-font overlay (premium banners)

Once you have a Minimax image API key and Playwright, you can produce
raster banners with an AI-generated mascot character (Mihoyo / Honkai
Star Rail style by default).  See the upstream brand-banner-kit skill at
<https://github.com/anthropics/skills> for the full recipe.

```sh
# One-time setup
cp .env.example .env
# Fill MINIMAX_API_KEY in .env, then:
npx playwright install chromium       # ~200 MB download

# Each release that wants fresh banners:
set -a && source .env && set +a
node scripts/brand/gen_mascot.mjs       scripts/brand/pixcull-brand.json
node scripts/brand/overlay_wordmark.mjs scripts/brand/pixcull-brand.json
```

The mascot prompt + palette in `pixcull-brand.json` is tuned for PixCull
(culling-themed photo aesthetic, cosmic dark background, signature
purple→pink wordmark).  Edit prompts in `pixcull-brand.json.mascot` —
`PROMPTS-REFERENCE.md` documents the style-family options.

---

## Customising the brand

Single source of truth: **`pixcull-brand.json`**.

```json
{
  "projectName": "PixCull",
  "slug": "pixcull",
  "tagline": "本地 AI 帮你 6 秒挑出一晚要拍的全部精选。",
  "subtitle": "LOCAL-FIRST AI PHOTO CULLING",
  "palette": {
    "wordmarkStart": "#6E56CF",
    "wordmarkMid":   "#A855F7",
    "wordmarkEnd":   "#EC4899",
    "bgDeep":        "#0b0d10",
    "bgMid":         "#1a1230",
    "bgCosmic":      "#3d1b69"
  }
}
```

Any change → re-run `gen_brand_svg.py` → all 4 variants update in lock-step.

---

## Embedding in the README

```markdown
<p align="center">
  <img src="docs/brand/pixcull-horizontal-lockup.svg"
       alt="PixCull · Local-first AI photo culling" width="100%">
</p>

<p align="center">
  <img src="docs/brand/pixcull-hero-reveal-demo.svg"
       alt="PixCull hero reveal — workspace bar slide-in, sidebar slide-in,
            24 photo cards stagger fade-up, stats count from zero"
       width="100%">
</p>
```

GitHub renders both inline (SVG animations included — no autoplay
restriction like with `<video>`).  Both ship at sub-30KB so README load
stays snappy.

---

## Brand asset checklist (when you cut a release)

- [ ] Edit `pixcull-brand.json` if anything changed (tagline / palette)
- [ ] Run `python scripts/brand/gen_brand_svg.py`
- [ ] Run `python scripts/brand/gen_animated_demo.py`
- [ ] Diff `docs/brand/*.svg` in git → spot-check
- [ ] Update `README.md` if the hero copy needs a refresh
- [ ] Update `modelscope/README.md` to mirror
- [ ] Capture fresh real-UI screenshots if any major surface changed:
       `bash scripts/brand/capture_screenshots.sh` (when this lands)
- [ ] (Optional path B) Re-roll AI mascot if you have MINIMAX_API_KEY
