# Design audit · 2026 Q4 — v0.10 self-check + v0.11 scoping

**v0.10-P2-4** — half a year after the 2026 Q3 audit that
launched the v0.9 charter (brand + signature moments + Cmd+K).
Same methodology: hold PixCull's current state side-by-side
with seven reference products + identify the next round of
gaps.

## Method

For each reference product, score PixCull on a 1–5 scale for
the relevant dimension and write a short verdict.  Aggregate
the gaps into the v0.11 charter draft (`docs/ROADMAP-v0.11-
charter.md`, also shipped this slice).

References used (same set as Q3, for trend tracking):

1. **Linear** — Cmd+K, motion identity, brand gradient
2. **Stripe** — dashboard data density, gradient identity
3. **Notion** — slash menu, color-coded properties, AI-as-text
4. **Apple Photos** — Memories animation, swipe gestures
5. **Raycast** — keyboard-only design ceiling
6. **CapCut Pro** — Z-gen motion + signature gradient
7. **Pixelmator / Affinity** — chrome-less canvas-first
8. **Figma** (NEW this audit) — multiplayer presence + cursor
9. **DaVinci Resolve** (NEW this audit) — pro-tool restraint

## Scorecard — where v0.10 lands

| Dimension                     | Q3 (v0.8) | Q3 target (v0.9) | Q4 (v0.10) | Comment |
|-------------------------------|-----------|-------------------|-----------|---------|
| Motion identity               | 2 | 4 | **4** | Soft-bounce + hero reveal landed v0.9 ✓ |
| Brand gradient consistency    | 1 | 5 | **5** | indigo→violet→pink across logo / CTA / `.ai-num` / radial ✓ |
| Cmd+K command palette         | 0 | 5 | **5** | 27 actions + fuzzy match ✓ |
| Client deliverable polish     | 2 | 5 | **5** | /share portfolio + exec PDF ✓ |
| Card hover affordances        | 2 | 4 | **4** | floating actions + lightbox swipe ✓ |
| Modal visual differentiation  | 2 | 4 | **4** | info/action/destructive/detail ✓ |
| **Multiplayer presence**      | 0 | 4 | **5** | v0.9-P1-2 + v0.10-P0-1 two-way + conflict UI |
| **mDNS auto-discovery**       | 0 | 0 | **4** | v0.10-P0-2 — Tailscale-lite for LAN |
| **ML rigor (eval harness)**   | 1 | 1 | **4** | v0.10-P0-3 — recall@5 CI gate, λ benchmark |
| **iOS Companion parity**      | 1 | 1 | **4** | v0.10-P0-4 — SwiftUI brand + gestures + portfolio |
| **Studio multi-user**         | 1 | 1 | **3** | v0.10-P1-1 — team taste + head-shooter override |
| **Tether peak streaming**     | 0 | 0 | **4** | v0.10-P1-2 — sub-second peak transfer |
| **Slash menu (Notion-like)**  | 0 | 0 | **4** | v0.10-P1-3 in rubric textareas |
| **Audio-photo sync**          | 0 | 0 | **3** | v0.10-P1-4 — opt-in, vocab v1 (37 phrases) |
| **i18n coverage**             | 2 | 4 | **5** | zh + en + ja + ko + es (5 locales) |
| **PWA install path**          | 0 | 0 | **4** | v0.10-P2-1 — manifest + SW + apple-mobile-web-app |
| **Canon library depth**       | 3 | 3 | **5** | v0.10-P2-2 — 27 → 57 entries (+ contemporary) |
| **Crash reporting (opt-in)**  | 0 | 0 | **4** | v0.10-P2-3 — Sentry with hard-scrubbed event hook |
| Real distribution (brew/MSI)  | 1 | 1 | **2** | v0.8-P0-3 + v0.8-P1-2 scaffolding only; cred-blocked |

**Trend** — Q3 → Q4 average score: 1.4 → 4.0 across the dimensions
tracked.  PixCull is no longer "competent" — every reference now
maps cleanly to a PixCull surface that holds its own.

## Where the audit still finds gaps

Three honest weak spots after v0.10:

### Gap 1 — Real distribution is still credential-blocked

Even though `release_macos.sh` / `release_windows.sh` / 
`release_linux_appimage.sh` are all production-ready, no user
has actually `brew install --cask pixcull`'d the app yet because
the Apple Developer enrolment + SignPath OSS approval + GPG key
generation haven't happened. **The fix isn't more code; it's
calendar time.**  Charter v0.11 will hold this slice as a
non-engineering item with a deadline.

### Gap 2 — ML eval harness exists but hasn't run on real data

The `eval_rescorer.py` + `eval_style_v2.py` harness shipped in
v0.10-P0-3 has only run on synthetic test data (the unit tests).
The real 22k+ annotation pool the user has accumulated under
`out_wedding_eval/` + per-user `runs/` hasn't been gathered
into a goldenset yet.  **v0.11 needs a `build_goldenset.py` to
do that pooling + the actual V3 retrain.**

### Gap 3 — Multiplayer is great in the same LAN; we don't have remote

v0.10 LAN sync + mDNS solves the same-room case beautifully.
The remote-collab case (host in studio + editor at home) still
relies on URL pasting through iMessage and a flaky port-forward
on the host's router.  **Tailscale-style WAN reachability would
close this** but adds an external dep on Tailscale's auth fabric,
which our local-first promise has been allergic to.  Defer
unless there's user demand.

## What v0.10 explicitly punted

Restating from the v0.10 charter so the v0.11 scoping knows
what's still open:

- **Cloud accounts** — local-first stays untouched.
- **Realtime via WebRTC / WebSocket** — LAN polling stays.
- **Electron / Tauri** — packaging stable; no rewrite.
- **Cloud LLM hard dep** — DeepSeek + WhisperKit stay optional.
- **Per-vertical λ default** — style V2 benchmark gives the
  data; consuming it is v0.11-or-later.

## v0.11 scoping — three theses

The next charter should pick from three thematic theses; one is
the body of the v0.11 charter, the others land in v0.12 / v0.13.

### Thesis A — "Studio-grade infrastructure"

Theme: PixCull becomes the canonical *team* tool, not just the
canonical solo tool.  Slices:

- Goldenset builder + V3 rescorer retrain (finish the v0.10
  homework)
- Per-vertical style λ runtime override (consume the benchmark)
- Real-time LAN sync via mDNS-discovered WebRTC datachannel
  (drop the 5s polling for true presence + low-latency
  conflict resolution)
- Studio billing CLI (multi-user license-key delivery —
  needed when we monetise)

### Thesis B — "Pro motion + interaction depth"

Theme: keep the v0.9 signature moments but push interaction
density to the Pixelmator / Affinity / DaVinci ceiling.  Slices:

- Drag-to-scrub photo timeline in the lightbox (DaVinci-style)
- Marquee select + bulk operations across the grid
- Modular keyboard shortcut customisation (Raycast level)
- Onboarding redo with 3D motion (the v0.9-P0-2 hero reveal
  generalises to *every* major surface)

### Thesis C — "AI judgement transparency"

Theme: every AI score on a card explains itself in one tap,
no more "trust the model".  Slices:

- Per-axis attribution heatmap (which pixels drove score_final?)
- Counterfactual chip ("would this be 0.10 lower if the
  composition were rule-of-thirds instead of centered?")
- Confidence-weighted decision modal (the model is 60% sure
  this is a maybe; here's why)
- Bias audit dashboard (cull rate per scene / face cluster /
  time-of-day — surface where the rescorer is over/under-firing)

**Charter pick:** Thesis A.  Closes v0.10's biggest unfinished
homework + naturally extends the LAN-collab work that landed in
this release.  Theses B + C are queued for v0.12 / v0.13.

## Timestamp + provenance

- Audit timestamp: 2026 (notional Q4)
- Predecessor: docs/DESIGN-AUDIT-2026Q3.md (charter for v0.9)
- v0.11 charter draft: docs/ROADMAP-v0.11-charter.md
- Reference product set: see *Method* above
- Pixel-level evidence: not collected this round
  (every gap above was felt during v0.10 dogfooding on the
  1147-row 川西行 wedding run)
