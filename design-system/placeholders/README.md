# Placeholder assets · awaiting Phase B

This directory **intentionally contains nothing real**.

It's the destination directory for assets that Phase B briefs
will produce.  When you hire an illustrator (Brief 02) or brand
designer (Brief 01) and they hand back final files, they go here,
then the engineer wires them into the real product paths
(`docs/brand/`, `pixcull/report/templates/results.html` `<symbol>`
blocks, etc.).

## Expected contents after Phase B

```
placeholders/
├── illustrations/
│   ├── art-empty-inbox.svg          (Brief 02 #01)
│   ├── art-empty-inbox@2x.png
│   ├── art-empty-inbox@4x.png
│   ├── art-no-match.svg              (Brief 02 #02)
│   ├── ...                            (8 more)
│   ├── art-style-train-empty.svg     (Brief 02 #09 · NEW)
│   └── art-tether-waiting.svg        (Brief 02 #10 · NEW)
├── brand/
│   ├── pixcull-mark-dark.svg         (Brief 01 — replaces current placeholder)
│   ├── pixcull-mark-light.svg
│   ├── pixcull-mark-mono.svg
│   ├── pixcull-icon-16.png
│   ├── pixcull-icon-32.png
│   ├── pixcull-icon-256.png
│   ├── pixcull-icon-512.png
│   ├── pixcull-icon-1024.png
│   ├── wordmark-horizontal.svg
│   └── wordmark-stacked.svg
└── component-renders/
    ├── results-grid-hero.png         (Brief 03 page layout export)
    ├── lightbox-inspector.png
    └── share-portfolio-cover.png
```

## What an engineer does after Phase B delivers

```bash
# 1. Verify the files are clean (run through SVGO / OptiPNG if not)
cd design-system/placeholders/illustrations/
ls -lh

# 2. Move brand marks to canonical location
mv ../brand/*.svg ../../docs/brand/
mv ../brand/*.png ../../docs/brand/

# 3. For each illustration, paste the SVG content into the
#    matching <symbol id="art-*"> block in
#    pixcull/report/templates/results.html
#    (the existing block; we replace not add)

# 4. Run the lint to confirm no new violations
make lint-design

# 5. Rebuild design tokens (in case the brand designer's brand-
#    guide bump altered colors)
make tokens
git diff design-system/   # confirm expected changes
```

This directory currently is empty — that is correct.
