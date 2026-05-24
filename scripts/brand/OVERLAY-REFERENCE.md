# Overlay layout — knobs to turn

The HTML templates in `scripts/overlay_wordmark.mjs` are tuned for the
default OFFICE ZOO case (Chinese tagline, 5-char wordmark, English
subtitle). Real-world projects vary. Here's what to adjust when.

## Vertical poster (9:16, 720×1280)

### Backdrop bands
```js
top:    210px tall  // covers ~16% of frame height
bottom: 140px tall  // covers ~11%
```

Increase when:
- AI's garbled text extends further into the frame (rare but happens
  with longer project names that AI tries harder to render)
- Tagline is long (2 lines) — bump bottom to 180-200px so backdrop
  fully wraps it

Decrease when:
- Project name is 1-2 short words — top can drop to 160px to give the
  mascot more breathing room

### Wordmark font size
Default `font: 900 60px`. Scales OK for 5-12 char Latin names. For:
- 1-4 chars: bump to 80-100px
- 13-20 chars: drop to 44-48px and consider 2-line layout
- CJK-only (e.g., `班味剧场`): drop to 50px (CJK glyphs are visually denser)

### Negative space rule
Mascot AI prompt asks for top 25% + bottom 15% negative space. The script
overlays in top 210/1280 ≈ 16% and bottom 140/1280 ≈ 11%. There's ~10%
slack — useful when mascot's pose pokes into the safe area.

## Horizontal lockup (16:9, 1280×720)

### Wordmark position
```js
top: 50%
left: 42%   // 30% mascot + ~12% padding
right: 48px
```

If mascot's silhouette extends past 40% width (long tail / props), bump
`left` to 48%. If mascot is unusually narrow, drop to 36% so the wordmark
sits closer to center for better balance.

### No backdrop?
Horizontal lockup intentionally has NO backdrop layer. The AI prompt
explicitly asks for "smooth uninterrupted gradient" in the right 70%, and
image-01 honors that ~95% of the time. The 5% where it doesn't, manually
re-roll the variant rather than adding backdrop (which would look mismatched
against the clean character side).

### Three-line stack height
```
wordmark:   96px tall × 1 line
subtitle:   18px tall × 1 line + 14px gap
tagline:    19px tall × ~2 lines + 6px gap
```
Total stack ~180-200px. Fits 720px height with room to breathe. If you
add a 4th line (e.g., a CTA button), bump `top` to 45% so the stack stays
vertically centered.

## Mark-only (1:1, 1024×1024) — no overlay

Passed through unchanged from gen_mascot.mjs. If you want to add a
subtle wordmark to the mark-only file (e.g., a 1-line "PROJECT" footer),
swap the `html: null` branch in `JOBS` to an HTML string. But this
defeats the purpose of mark-only (which is the file you slap on stickers
and don't want any text).

## Font fallbacks

```css
font-family: -apple-system, "PingFang SC", "Hiragino Sans GB",
             "Microsoft YaHei", "Noto Sans CJK SC", system-ui, sans-serif;
```

- **macOS / iOS**: PingFang SC wins. Crisp.
- **Linux (CI / Docker)**: Likely needs `apt install fonts-noto-cjk` for
  Noto Sans CJK SC to render Chinese. Without it, you get tofu (□).
- **Windows**: Microsoft YaHei or PingFang SC if installed.

If you're running this skill in a CI environment with no display, see
Playwright's headless mode docs — the script already works headless, but
font availability is the user's responsibility.

## Adding a 4th variant

If a project needs a 5:4 square crop for Instagram or a 4:3 for slide
decks, add a new entry to `JOBS` in `overlay_wordmark.mjs` AND a new task
to `TASKS` in `gen_mascot.mjs` with matching `aspect_ratio` + variant name.
Then write a `<variant>HTML(brand)` function patterned after `verticalHTML`
or `horizontalHTML` depending on the orientation.

Minimax image-01 supports: 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3. Stick to
those; arbitrary ratios get cropped server-side.
