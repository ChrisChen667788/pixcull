# press-kit/ · Phase C deliverable destination

> **Status: empty.**  This directory is the destination for the
> deliverables of [Brief 06 · PixCull v1.0 Press Kit](../design-system/briefs/06-press-kit-brief.md).
> When you commission a marketing studio for Phase C, the files
> below get filled in.

## Expected contents after Phase C

```
press-kit/
├── README.md                       ← you are here
├── one-pager.pdf                   ← single A4 elevator pitch
├── long-form-blog-post.md          ← 1800-2400 words
├── hn-variant.md                   ← HN-friendly snappy version
├── xiaohongshu-variant.md          ← 小红书 photographer-voice
├── tech-press-variant.md           ← 36kr / Sohu / Yicai friendly
├── faq.md                          ← anticipated press Qs
├── press-contact.md                ← maintainer bio + contact
├── boilerplate-en.txt              ← 30 / 100 / 300-word EN
├── boilerplate-zh.txt              ← 30 / 100 / 300-word ZH
├── tagline-options.txt             ← 5-7 candidates · for review
├── visuals/
│   ├── brand-marks/
│   │   ├── pixcull-mark-{16,32,256,1024,4096}.png + .svg
│   │   └── (10 files)
│   ├── logomarks/
│   │   ├── horizontal-on-dark.png + .svg
│   │   ├── horizontal-on-light.png + .svg
│   │   ├── vertical-on-dark.png + .svg
│   │   ├── stacked.png + .svg
│   │   └── mono-on-dark.png + .svg
│   ├── hero-screenshots/
│   │   ├── results-grid@2x.png        (2880 × 1800)
│   │   ├── results-lightbox@2x.png
│   │   ├── share-portfolio@2x.png
│   │   ├── executive-pdf-cover@2x.png
│   │   └── ipad-lightbox-gesture@2x.png
│   ├── product-context/
│   │   ├── on-photographer-desk.jpg
│   │   ├── ipad-in-venue.jpg
│   │   └── tethered-cable-rig.jpg
│   └── brand-pattern/
│       └── repeating-spotlight-pattern@4x.png
└── videos/
    ├── trailer-30s.mp4               (1080p H.264)
    ├── trailer-30s-4k.mp4            (4K H.265)
    ├── trailer-30s.webm              (VP9)
    ├── walkthrough-90s.mp4
    ├── walkthrough-90s-4k.mp4
    ├── loop-5s.gif                   (< 500 KB)
    └── loop-5s.mp4                   (silent autoplay loop)
```

## Naming convention

All filenames are **case-sensitive lowercase with hyphens**.  Reason:
the press kit is shared via cloud-storage links + email
attachments where case-sensitivity varies; lowercase-hyphen is
maximally portable.

## Distribution after Phase C ships

```
1. Bundle the entire press-kit/ directory as press-kit.zip
2. Upload to GitHub release for v1.0
3. Add to README:
   "Press kit · https://github.com/ChrisChen667788/pixcull/releases/download/v1.0/press-kit.zip"
4. Cross-link from a /press route in serve_demo.py (optional)
```

## Where the launch happens

| Channel | Timing | Content angle |
|---------|--------|---------------|
| GitHub release | v1.0 launch day | full press-kit zip + release notes |
| ProductHunt | launch day +1h | trailer-30s + hero screenshots |
| Hacker News "Show HN" | launch day +3h | hn-variant.md as launch post |
| 小红书 | launch day | xiaohongshu-variant.md + 5 hero screenshots |
| 36kr / 极客公园 | launch day +1d (pre-pitch their reporter day -3) | tech-press-variant.md + walkthrough-90s |
| Twitter / X | rolling, owner-driven | loop-5s.gif + 1-line value props |
| 知乎 | launch day +2d | long-form-blog-post.md re-posted |
| ModelScope | launch day | release notes + hero-screenshot mirror |

## Today

Directory is empty.  The brief that fills it (Brief 06) needs
to be commissioned during Phase C of the DESIGN-SYSTEM-ROADMAP
timeline.
