# The mark, and why it changed

## What was there

A radial "cosmic" gradient in brown-black, a beige-to-mud-brown ramp, four
small white circles and one large glowing one. The circles were captioned in
the source as "the crowd" and "the picked one".

Three problems, in order of how much they cost:

1. **It was not about photographs.** A glowing orb on a dark radial ground is
   the house style of every generated logo of the last two years. Nothing in it
   said photo, frame, take, or choice — the circles could have been any product
   that picks one thing out of several.
2. **The palette ended in mud.** The ramp ran to `#6a6052`, and the ground to
   `#110e0b`. Every asset it touched looked dim.
3. **The brand did not agree with itself.** The README banner used brown and
   tan; the hero image four hundred lines below it used blue-grey `#a8b2c1`.
   Two assets, one file, and they did not look like one project.

## What it is now

**The frame you marked.**

A photo editor culling a take marks the frames they want on a contact sheet,
and the mark is a corner bracket — the same shape as a viewfinder, the same
shape as a crop mark. Behind the marked frame sit the rest of the take, dimmed,
because culling is choosing one out of several that look alike.

That is the job the software does, drawn as the thing photographers already do
by hand.

### The constraint that shaped it

Sixteen pixels. A contact-sheet grid is mush at favicon size, so the stack is
suggested by two offset edges rather than drawn as frames, and the brackets
carry the silhouette. The bracket box is centred on the canvas so the mark sits
level in a round avatar as well as a square tile, and the stack is kept inside
that box — a stack poking out past the crop marks reads as untidy, not as depth.

### Palette

| token | value | used for |
|---|---|---|
| `bgDeep` / `bgMid` / `bgCosmic` | `#101113` `#17181a` `#1e2024` | ground, matching the product's own base rather than a second dark of its own |
| `frameStart` → `frameEnd` | `#efe6d6` → `#cbb894` | the chosen frame: warm paper under a lamp, kept in the light half so it reads as lit |
| `accent` | `#e8a33c` | crop brackets, the film-edge rule, and the eyebrow line — **and nothing else**, so the colour keeps meaning "this is the chosen one" |
| `stackNear` / `stackFar` | `#5b5f68` `#43464d` | the rest of the take |
| `textBody` / `textMuted` | `#d6d3cd` `#8b8f97` | copy |

One accent, used for one meaning. That is the whole colour system and it is
deliberately small: a second accent would have to earn a second meaning.

## The assets

| file | size | where |
|---|---|---|
| `brand/pixcull-mark-only.svg` | 1024² | app icon, favicon, avatar |
| `brand/pixcull-horizontal-lockup.svg` | 1280×420 | README banner |
| `brand/pixcull-vertical-poster.svg` | 720×1280 | phone / social vertical |
| `assets/github-hero.svg` | 1280×400 | README closing image |
| `assets/github-social-preview.svg` / `.png` | 1280×640 | GitHub social card |

The lockup was 1280×720 — a 16:9 slide with two hundred pixels of nothing
between the tagline and the footer, rendered at `width="100%"` before a reader
had seen a sentence. It is a banner now.

The hero's right half is **not a mock of the interface**: three frames from one
take, each with its verdict and a reason in the product's own words, one of them
marked. A fake screenshot in a hero image is a promise the software has to keep
on the reader's first run.

## Regenerating

```
python scripts/brand/gen_brand_svg.py
```

reads `scripts/brand/pixcull-brand.json` and writes the mark, the lockup and the
poster. The hero and the social card are hand-authored SVGs; the social PNG is
rasterised from its SVG at 2× with Playwright.

Edit the generator, not the output. The mark exists in one place —
`_logo_group()` — and every asset draws it from there, because a logo defined
twice is a logo that will differ in two places.
