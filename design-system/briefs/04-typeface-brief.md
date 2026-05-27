# Brief 04 · PixCull Sans — Custom Typeface

> **Hand to a type designer.**
> 2-3 month engagement, RMB 30,000–60,000.  Phase C.  Trigger:
> v0.13 timeline, after Phase B brand work has settled +
> establishes the visual frame.

## Why we'd commission a custom typeface

After Phase B (brand guide + component library + custom
illustrations), PixCull has its own visual voice except for **one
slot**: the typeface.  Currently we use Inter (variable, OSS,
excellent — but on every other tech product in the world).

A custom typeface gives:

1. **Identity** — Affinity Sans, Stripe Beirut, Linear Inter
   Tight, GitHub Mona Sans — every iconic product has its own
   typeface
2. **Optical-size adaptation** for the very large numerals on
   `/share` portfolio + executive PDF cover (where 48-56pt serif
   numerals are the signature element of v0.9-P0-3)
3. **Native-feel** for non-Latin scripts — Inter's CJK coverage is
   uneven; a custom typeface designed alongside its Chinese
   companion reads better in PixCull's Chinese user base
4. **Display-grade detail** in the v0.9 hero-reveal moment, where
   a stock Charter / Inter pairing falls short

## Scope: what "PixCull Sans" should be

### Family structure

- **PixCull Sans** — sans-serif workhorse, replaces Inter
  - Weights: 200 / 300 / 400 / 500 / 600 / 700 / 800 / 900
    (8 weights — same as Inter ramp for drop-in replacement)
  - Variable axis: `wght` 200-900, `opsz` 12-48
  - Three numeral sets:
    - **tabular lining** (default for AI scoring numbers — must
      align in columns)
    - **proportional lining** (for inline body text)
    - **oldstyle proportional** (for editorial flair on
      executive PDF + brand wordmark)
- **PixCull Serif** (companion) — for the v0.9-P0-3 hero
  numerals + executive PDF cover + brand wordmark
  - 3 weights: regular / semi-bold / bold
  - Display-optimised (heavy contrast, larger optical-size 36-72)
  - **Optional**: out-of-scope if budget tight; Phase B's
    Editorial New / system Charter stays for serif slot

### Required script coverage

1. **Latin Extended-A** (covers ES, FR, DE, IT, PT — all v0.10 +
   v0.11 i18n targets)
2. **Simplified Chinese** (~3500 glyphs covering all UI strings +
   common photo metadata)
3. **Japanese** (Kanji subset matching v0.8 ja_JP locale + Hiragana
   + Katakana)
4. **Korean** (Hangul syllables, ~2500 most-common)
5. **Spanish** ⊆ Latin Extended-A

**Out of scope for v1.0**: Arabic, Hebrew (no RTL support in
PixCull yet), Devanagari, Thai.

### Optical-size axis details

PixCull renders text at three distinct sizes that need different
optical treatment:

- **Body 13px** — Inter at 13px is the current high bar
- **Numerals 28-36px** — the score_final + keynum hero numbers
- **Display 56-72pt** — executive PDF cover title + `/share` hero

The variable `opsz` axis interpolates these so the same family
covers all three without three separate files.

### Numeral styling — special focus

PixCull is a **numbers-heavy product**.  Every photo has a score
(0.0-1.0), 6 axis stars, recall@k metrics, file counts.
**The numerals carry the brand voice.**

Spec for PixCull Sans numerals:

- **Tabular lining** — every digit identical width.  Used in
  the `score_final` column, recall@k tables, the executive PDF
  dashboard.  Mandatory.
- **Proportional lining** — used in inline body text.  Mandatory.
- **Oldstyle proportional** — display-mode editorial.  Used in
  the `/share` portfolio hero numerals (where the v0.9-P0-3 serif
  currently sits).  **Optional but high-impact.**
- **Lining slashed-zero** option — distinguishes 0 from O at
  small sizes
- **Lining numerals at 28pt** should pair with the brand-gradient
  text-fill perfectly — confirm the stroke width supports the
  gradient mask without breaking

## Reference + inspiration

Existing typefaces we'd happily be "next to" on a moodboard:

- **Inter** — current baseline; PixCull Sans should feel like its
  spiritual successor, not a departure
- **Söhne** — Klim's editorial workhorse, great numerals
- **GT America** — Grilli Type, friendly + neutral
- **Untitled Sans** — Klim, narrower + more editorial
- **Söhne Mono** — for the inspiration of the mono companion (if
  scope extends)
- **DIN 2014** — for the engineered + dense character of
  tabular numerals
- **Charter** (Matthew Carter) — what we currently use for serif

## Deliverables

1. **PixCull Sans variable font** — `.ttf` + `.woff2` for web,
   `.otf` + `.ttc` for macOS / iOS bundling
2. **Glyphs source file** (`.glyphs` or `.glyphspackage`) for
   future iteration
3. **Specimen book PDF** (12-20 pages)
4. **Test page HTML** rendering every weight + optical size +
   numeral set against real PixCull copy ("comprehensive 6 维评分")
5. **Licensing** — choose ONE:
   - **Option A**: SIL Open Font License (OFL) — fully OSS,
     PixCull bundles freely + redistributes.  Aligns with
     project ethos.  Lower designer-side ongoing revenue.
   - **Option B**: Commercial license + retained royalty — designer
     keeps revenue from third-party use; PixCull pays a buyout +
     gets perpetual license for self.
   - **Recommendation**: Option A.  Aligns with MIT project
     ethos.  Pricing premium reflects the no-royalty trade-off.

## Timeline + payment

- Month 1 — Latin sketches + weight axis + numeral system
- Month 2 — CJK expansion + Korean + variable-axis tuning
- Month 3 — hinting + specimen + testing on PixCull's actual UI
  + license + delivery

Payment: 25% kickoff, 25% at end of month 1 (Latin draft
acceptance), 25% at end of month 2 (CJK draft acceptance),
25% on final delivery + license.

## Acceptance criteria

- All 8 weights × all 5 scripts pass shaping correctness via
  HarfBuzz test suite
- `opsz` axis tested at 12, 18, 28, 48, 72pt on PixCull's actual
  surfaces (results.html / share-page / executive PDF)
- Tabular numerals at 28pt mask cleanly with the brand gradient
  (test rendering provided)
- Specimen PDF + Glyphs source + variable woff2 all delivered
- License documented in `LICENSE-FONTS.md`

## Out of scope for v1.0 — but spec for future

- **PixCull Mono** companion (for the file paths shown in
  Inspector + console logs) — Phase D, v0.14+
- **PixCull Display Italic** — Phase D
- **Variable italic axis** — Phase D

## How to bid

Reply to chenhaorui667788@gmail.com with:

1. Portfolio: 2-3 prior typefaces shipped (links to specimens)
2. Experience with CJK + Latin in the same family (mandatory)
3. Rate (typically expressed as buyout + per-weight unit)
4. Timeline given your queue
5. Tool preference (Glyphs / FontLab / RoboFont)
6. Any change you'd push back on in this spec

Contact: chenhaorui667788@gmail.com
