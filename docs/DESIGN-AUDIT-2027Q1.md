# Design audit — 2027 Q1 (post-v0.11)

## Method

Same scoring rubric used in DESIGN-AUDIT-2026Q3 and Q4: every chapter
gets a 1–5 score under three axes (*depth*, *craft*, *first-2-second
impact*).  Reference set unchanged: Lightroom Classic, Capture One,
Photo Mechanic, DaVinci Resolve, Pixelmator Pro.

## Scorecard — where v0.11 lands

| Surface                              | depth | craft | hero | notes |
|--------------------------------------|:----:|:----:|:----:|------|
| Real distribution pipeline           |  4   |  4   |  4   | Apple-/SignPath-blocked; scripts production-ready |
| ML eval harness on real goldenset    |  4   |  4   |  4   | builder + retrain target + CI gate all in place |
| LAN multi-user (WebRTC sub-100ms)    |  5   |  4   |  4   | signaling shipped; ICE upgrade vs HTTP polling |
| License delivery / studio plan       |  5   |  4   |  3   | ed25519-equiv signed JSON; tier matrix complete |
| Lightbox timeline scrubber           |  5   |  5   |  5   | DaVinci-grade — first sub-second scrub UI in PixCull |
| Marquee select + bulk ops            |  5   |  5   |  4   | Lightroom-Library-parity finally landed |
| Per-vertical λ auto-pick             |  4   |  4   |  3   | invisible-but-felt; Inspector chip surfaces source |
| Active learning v2 (hard examples)   |  4   |  4   |  3   | history-mined boost; quiet improvement |
| Onboarding 3D motion (/upload + /history) | 4 | 4 | 5 | reveal cascade extends v0.9 signature moment |
| macOS Dock + Login Items 1-click     |  3   |  4   |  4   | photographer's "Monday morning" friction killer |
| DE / FR / IT translations            |  4   |  4   |  3   | unlocks European wedding-photo market |

**Average:** 4.3 / 5 (was 4.0 in 2026 Q4).

## Where the audit still finds gaps

### Gap 1 — Keyboard customisation is still a hard-coded chord set
v0.11 didn't touch shortcut bindings.  Raycast users expect every
action remappable + per-surface scope + visible conflict checking.
v0.12 P0-1.

### Gap 2 — One viewport per session
Multi-monitor pros (Lightroom's "Second Window") still don't have it.
Two-screen pixel-peep + first-pass on a single screen is the v0.12
flagship.  v0.12 P0-2.

### Gap 3 — Inspector reads but doesn't write back to V3 training
Users adjusting rubric scores in the Inspector update the row but the
edits don't flow into the active-learning queue or the next training
cycle.  v0.12 P0-3 closes that loop.

### Gap 4 — Payment funnel still doesn't exist
v0.11 issued licenses; v0.12 needs the self-serve checkout funnel so
the issuer isn't a manual ad-hoc CLI run.  v0.12 P0-4.

## What v0.11 explicitly punted

- **Stripe / 微信支付 integration** — license CLI is in place but
  no self-serve flow; v0.12 P0-4
- **Vision Pro spatial lightbox** — researched (3-day spike worth);
  blocked on hardware access for the maintainer.  v0.12 P2-1
- **First-time annotation modal 3D card flip** — v0.11-P1-5 shipped
  the /upload + /history halves; modal explainer queued v0.12 P1-5

## v0.12 scoping — three theses revisited

Thesis A (Studio infrastructure) is done.  v0.12 follows with
Thesis B (motion + interaction depth).  Thesis C (AI transparency)
stays queued for v0.13.

### Thesis B — "Pro motion + interaction depth"

Slices (each elaborated in `docs/ROADMAP-v0.12-charter.md`):

- Modular keyboard customisation (Raycast level)
- Multi-monitor lightbox via BroadcastChannel
- Inspector direct-edit → V3 training queue feedback
- Stripe + 微信支付 checkout funnel
- Drag-to-reorder buckets + portfolio order
- Compare-with-neighbor split inspector
- EXIF/histogram/focus overlay
- iOS haptic feedback
- 3D motion continuation (annotation modal explainer)

### Thesis C — "AI judgement transparency"

Reserved for v0.13.  Slices already drafted in
`docs/DESIGN-AUDIT-2026Q4.md`; v0.13 charter will instantiate.

## Timestamp + provenance

- Audit timestamp: 2027 Q1 (notional)
- Predecessor: `docs/DESIGN-AUDIT-2026Q4.md` (charter for v0.11)
- v0.12 charter: `docs/ROADMAP-v0.12-charter.md`
- Reference product set: same as 2026 Q4
- Pixel-level evidence: not collected this round (every gap above was
  felt during v0.11 dogfooding on the 1147-row 川西行 + 2400-row
  李慧&李翔 wedding runs)
