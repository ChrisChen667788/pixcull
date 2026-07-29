# PixCull

**Local-first AI photo culling for working photographers.**
Six calibrated scoring axes · burst folding · style-aware personalization ·
Lightroom / Capture One round-trip. **No photo ever leaves your disk.**

本地优先的 AI 摄影分拣:6 轴评分 · 连拍折叠 · 个性化学习 · Lr/C1 双向 round-trip,
原图永远不离开你的硬盘。

![PixCull results grid](https://raw.githubusercontent.com/ChrisChen667788/pixcull/main/docs/screenshots/01-results-grid.png)

## Install

```bash
pip install pixcull
```

Python 3.11–3.12. First run downloads the optional scoring models to
`~/.pixcull/models/` (everything runs on-device; Apple-silicon accelerated).

## Quickstart

```bash
# score a folder of photos (JPG / RAW) — keep/maybe/cull + per-axis rubric
pixcull run /path/to/photos -o ./out

# write the decisions back as XMP sidecars for Lightroom / Capture One
pixcull export ./out --xmp

# score a video → temporal windows + reel candidates
pixcull video clip.mp4 -o ./out

# fold near-duplicates, build a contact sheet, learn your taste, …
pixcull --help
```

```bash
# open the review workspace in your browser (v2.31 — now packaged)
pixcull serve
```

The pip package ships the full scoring engine, the CLI **and** the
interactive review workspace: keyboard-first grid, ⌘K palette, per-axis
"why" explanations, n-way compare, maybe-resolution queue, XMP export.
`pixcull serve` stores runs under `~/.pixcull/runs` by default
(`--root` to change, `--host 0.0.0.0` to share on a trusted LAN).

![PixCull lightbox](https://raw.githubusercontent.com/ChrisChen667788/pixcull/main/docs/screenshots/03-lightbox.png)

## Highlights

- **Glass-box scoring** — every keep/cull carries a per-axis breakdown
  (technical / subject / composition / light / moment / aesthetic) and a
  plain-language "why", not just a number.
- **Learns your taste** — corrections feed a personal profile that tilts
  the axis weights toward what *you* demonstrably value.
- **Burst & near-dup folding** — stacks collapse to the peak frame with a
  one-key compare.
- **Video too** — temporal scoring, audio events (laughter / applause /
  music), reel-candidate detection with the same glass-box treatment.
- **13 UI languages**, dark/light studio-neutral themes, WCAG-conscious.
- **Local-first, always** — no uploads, no cloud, no telemetry.

## Links

- [GitHub + full README](https://github.com/ChrisChen667788/pixcull)
- [Releases](https://github.com/ChrisChen667788/pixcull/releases)
- [ModelScope mirror](https://www.modelscope.cn/models/haozi667788/pixcull)

MIT © Chris Chen
