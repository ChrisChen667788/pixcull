# Minimax image-01 prompts — patterns

The 3 prompts in `scripts/gen_mascot.mjs` work for any mascot. Below are
**style modifiers** to swap into the `mascot` field of brand.json depending
on the project's vibe.

## Style families that ship reliably on image-01

### Mihoyo / Honkai Star Rail (default, "OFFICE ZOO")
```
stylized cyberpunk anime [subject] mascot wearing [outfit], bright [accent
color] eyes, friendly mischievous expression
```
- Best for: tech, gaming, edgy productivity tools
- Result: 5-star gacha character vibe, premium feel

### Kawaii chibi
```
super-deformed chibi [subject] mascot with oversized head and tiny body,
sparkly innocent eyes, soft pastel anime style, pixar-meets-sanrio
```
- Best for: education, kid products, friendly utilities
- Result: instantly approachable, low-stakes

### Pixel art
```
16-bit pixel-art [subject] mascot, 64×64 sprite aesthetic scaled up, clean
2-pixel outline, retro Game Boy Color palette but with [accent color] glow
```
- Best for: dev tools, retro / indie game projects
- Result: nostalgic, hacker-aesthetic

### Corporate-friendly
```
flat-shaded vector [subject] mascot, soft gradients, geometric simplification,
notion / linear / vercel illustration style, friendly approachable expression
```
- Best for: SaaS, B2B, anything with serious audience
- Result: safe, looks like it came out of a brand book

### Y2K cyber-punk
```
[subject] mascot rendered in Y2K aesthetic, chunky black borders, hot pink
+ acid yellow + cyan, sticker-shadow drop, sparkle decoration
```
- Best for: Gen-Z products, social, meme-y projects
- Result: playful retro-future vibe

## Color palette guidance

The `palette.wordmarkStart` / `Mid` / `End` colors drive both the AI prompt's
"rim lighting" hint AND the gradient wordmark in overlay. Match them:

- **Warm / energy**: gold `#FFD700` → orange `#FFA947` → red `#FF4757`
- **Cosmic / mystic**: gold `#FFD700` → pink `#FF4FA3` → violet `#B086FF`
- **Tech / clean**: cyan `#4ECDC4` → blue `#4A90E2` → indigo `#7C3AED`
- **Bio / fresh**: yellow-green `#A3E635` → green `#22C55E` → teal `#0EA5E9`
- **Mono / luxe**: pure white `#FFFFFF` → silver `#E5E7EB` (2-stop only)

Background trio (`bgDeep` → `bgMid` → `bgCosmic`) should always go DARK so
the wordmark gradient pops. The OFFICE ZOO default works for 90% of cases:
```
"bgDeep":   "#0a0a1e"  // panel back
"bgMid":    "#1a0d35"  // hero background fallback
"bgCosmic": "#2D1B69"  // radial center
```

## Things to put in the prompt vs leave to the script

**Put in the `mascot` field** (one-off per project):
- Subject (rat / cat / robot / bean / human child / etc)
- Outfit specifics
- Eye color or distinguishing feature
- Expression (mischievous / serious / sleepy / etc)

**Leave to the script** (always the same):
- Aspect ratio (handled per-variant)
- Negative space requirements (per-variant)
- "no text" / "no wordmark" / "no watermark" (in every prompt)
- 8k / sharp / high detail flags

## Why "no text" still doesn't fully work

Minimax image-01 (and most current image models) treats "no text" as a soft
constraint. The model still occasionally bakes garbled "WORDMARK"-attempt
characters into the negative space. This is WHY the overlay pass uses
backdrop fades — to cover whatever residue slips through. Don't waste
re-rolls trying to get a pristine no-text image; let the overlay handle it.

## Re-roll triggers

Re-run a variant (`--only vertical`) when:
- Mascot anatomy is broken (wrong number of limbs, deformed face)
- Color palette drifted hard from the requested rim lighting
- Pose is unusable (e.g., vertical poster's mascot is lying down)

Don't re-roll for:
- Garbled text in negative space (overlay covers it)
- Slight composition asymmetry (overlay's wordmark dominates the eye)
- Background bokeh density variation (acceptable polish drift)
