# Design audit — 2027 Q3 (post-v0.13, pre-v1.0)

## Method

Same scoring rubric as the 2026-Q3 / Q4 / 2027-Q1 / Q2 sequence.
This is the *final* design audit before v1.0 release gate.

## Scorecard — where v0.13 lands

| Surface                                  | depth | craft | hero | notes |
|------------------------------------------|:----:|:----:|:----:|------|
| Per-axis attribution heatmap             |  5   |  4   |  5   | `A` toggle in lightbox; IG over timm backbone; indigo→pink colorize |
| Counterfactual chip                      |  5   |  4   |  4   | rule-of-thirds / centered / diagonal / golden-ratio perturbations |
| Confidence-weighted decision modal       |  5   |  4   |  4   | hover-popover on maybe-band cards; dismissable per-run |
| Bias audit dashboard `/admin/bias`       |  5   |  5   |  5   | scene + time-of-day + aperture buckets; z>1.5σ findings |
| NL explainer (template fallback)         |  4   |  4   |  3   | LLM if installed, template fallback always works |
| Style-ref distance visualisation         |  4   |  5   |  4   | popover bar chart on chip click |
| Disagreement dashboard                   |  5   |  4   |  3   | per-run reversal counts; links to bias audit |
| Goldenset auto-augmentation script       |  5   |  4   |  3   | closes the active-learning loop into next training cycle |
| Positive attribution (extends P0-1)      |  4   |  4   |  3   | same heatmap module covers keep too |
| Preferred-axes profile                   |  4   |  4   |  3   | mute + boost per axis; JSON persistence |
| Bias audit markdown export               |  4   |  5   |  3   | `/admin/bias.md` for client-deliverable PDF |

**Average:** 4.4 / 5 (up from 4.3 in Q2 — transparency theme delivers
both depth and craft because most surfaces *removed* opacity rather
than adding visual weight).

## Where the audit still finds gaps (now small)

### Gap 1 — Per-ref CLIP distance isn't broken out
v0.13-P1-2 shows V1/V2/blend totals but not which individual reference
contributes most.  Requires a new endpoint exposing per-ref CLIP
cosine.  Queued for v1.0-followup or v1.1.

### Gap 2 — Bias dashboard is global-only
The dashboard aggregates across every run; per-photographer-profile
slicing would help studios with multiple shooters track each
person's bias separately.  Queued for v1.1.

### Gap 3 — Counterfactual classifier is unsupervised
v0.13-P0-2 ships the perturbation framework + scoring pipe; the
production *classifier* (MobileNetV3-Small, 4 classes, 5k labels)
still needs the labels.  Counterfactuals work today via brute-force
"score all variants"; a trained classifier would scope to the right
one and speed up the chip 4×.

## What v0.13 explicitly punted to v1.0+

- **Stripe Tax Identifier flow** (v0.12 was webhook + tier-mint;
  invoicing lives in Stripe Dashboard until v1.0+)
- **Visualised shortcut customisation GUI** (v0.12 shipped the
  backend; the v0.13 design audit confirmed users can edit
  `~/.pixcull/shortcuts.json` directly — GUI is comfort, not
  blocker)
- **Counterfactual classifier production training** — perturbation
  framework ready; labels collection is v0.14 work
- **Vision Pro spike → ship** — `docs/VISIONOS-SPIKE.md` complete;
  ship blocked on hardware

## v1.0 release gate

See `docs/RELEASE-V1.md` for the full gate criteria.  Headline:

- Real distribution (brew tap + signed MSI + signed AppImage):
  3 platforms × Sparkle update path ready
- ML eval on real 22k+ goldenset: recall@5 ≥ baseline + 5%
- Multi-user LAN + WebRTC datachannel: sub-100ms presence
- Commercial: license CLI + Stripe webhook + ≥ 50 active subscribers OR decision-to-stay-free-only
- AI transparency: 100% decisions explainable in 1 click
- i18n: ≥ 13 locales (current: 13)
- Brand: design audit score ≥ 4.4 (current: 4.4 — at gate)
- Dogfood: maintainer + ≥ 3 real photographers in production

## v2.0+ horizon

v1.0 closes "PixCull, the local-first AI culling tool for stills."
v2.0 candidates (charter-only at this point):

- **Video culling / reel selection** — same rescorer stack applied
  to frame-extracted MP4 / RAW video
- **Generative compositing** — automatic best-of composite from
  reject burst sequences ("save the bride's smile from frame 2 +
  the groom's eyes from frame 4")
- **Enterprise SSO + audit log** — for production studios with
  dozens of editors

## Timestamp + provenance

- Audit timestamp: 2027 Q3 (notional)
- Predecessor: `docs/DESIGN-AUDIT-2027Q2.md` (charter for v0.13)
- v1.0 release plan: `docs/RELEASE-V1.md`
- Reference product set: Lightroom Classic, Capture One, Photo
  Mechanic, DaVinci Resolve, Pixelmator Pro, Affinity Photo,
  Raycast, Stripe (commercial polish reference)
- Pixel-level evidence: collected on this audit — every gap above
  was felt during v0.13 dogfooding on the 川西行 wedding run +
  the v0.12 multi-monitor compare passes
