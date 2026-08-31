# Competitive refresh — the recurring protocol

Runs at most every **two weeks**. Produces a *diff*, not a re-listing.

The 2026-08-31 edition established the reason this protocol has to be strict:
**ten headline claims were fact-checked and ten failed.** Sources cited a theme
change for a flagship feature, a paid advertorial for a product's architecture,
and a 2025 paper dated as 2026. A single-pass scan reports vendor marketing back
with a citation stapled on. Treat first-pass output as unverified by default.

## The run, in order

**1. Poll the primary sources.** Vendor changelogs and release notes before any
aggregator or "best culling software 2026" listicle. The machine-readable list is
`docs/competitive/sources.json`.

**2. Diff against the last snapshot.** `docs/competitive/snapshot-<date>.json`
holds every product with its flagship capability, model, source URL and source
date. A run reports:
  - **new** — a product or model not in the last snapshot
  - **changed** — a flagship capability whose description or source date moved
  - **stale** — a claim carried forward whose source is now over 90 days old and
    must be re-verified before it may be repeated
  - **gone** — a product that no longer appears

**3. Fact-check everything that moved.** Every capability claim carrying a
processing-mode assertion (on-device / cloud / hybrid), an accuracy figure, or a
pricing structure gets opened at its primary source by a second pass whose job is
to *refute* it. Nothing enters the document on the strength of a single pass.

**4. Write only the delta.** If nothing meaningful changed, the run says so and
stops. Two weeks is short; most runs should be short. A run that produces a full
report every fortnight is manufacturing news, and the first thing a reader stops
trusting is a document that is always exciting.

**5. Wake a human only for these.** Otherwise log quietly:
  - a platform vendor (Adobe, Apple, Capture One, a camera maker) ships something
    that was a PixCull differentiator — the free-inside-a-tool-they-already-have
    case, which is structurally the hardest to answer
  - a rival ships a capability listed under "deliberately declined" in the current
    charter, with evidence it is working — the decline may need revisiting
  - an open-weight model lands that changes what is possible locally
  - a claim in the current published analysis is found to be **wrong** — correcting
    our own document outranks reporting someone else's news

## Standing rules

- **No currency amounts.** Pricing structure in words only. Enforced by
  `test_no_money_amounts`; a run that violates it fails the build.
- **Every claim carries a source URL and the source's own date**, not the date it
  was read.
- **Confidence is explicit**: `verified` (primary vendor source or independent
  hands-on), `partial` (one secondary source, or a primary source over six months
  old), `unverified` (competitor-authored, aggregator, or no confirmable URL).
  Unverified claims are published *as unverified*, never dropped and never rounded up.
- **A competitor-authored source is never authoritative about a competitor.** The
  2026-08-31 run found a rival's architecture described by another rival; it was
  discarded.
- **"Could not confirm" is a result.** So is "nothing changed".

## Method, and why not just a feature matrix

A feature-parity checklist is the failure mode this protocol is shaped against: it
counts capabilities and misses the one that matters. The 2026-08-31 edition's most
consequential finding was not a feature at all — it was that a platform vendor put
a narrow culling pass inside the application photographers already open every day.
No matrix row captures "distribution".

So each edition must answer, in prose:
- **What is the photographer hiring this tool to do**, and who else is now hired
  for that job? (jobs-to-be-done, not feature counts)
- **Which capabilities are must-have, which are delighters, and which have decayed
  from delighter to expected?** (Kano, applied to the same list over time — this is
  what the snapshot diff is for)
- **What is each rival's shipping velocity?** A changelog that ships theme changes
  for two quarters says more than its feature list does.
- **Where is our own claimed advantage weaker than it looks?** The published
  analysis carries a mandatory section for this and it may not be empty.

## Scope of what the automation may change on its own

It may write `docs/competitive/snapshot-<date>.json`, append to
`docs/COMPETITIVE-<edition>.md`, and open a summary. It may **not** rewrite the
roadmap charter, change defaults, or push. Turning a competitive finding into a
version is a decision with a human in it.
