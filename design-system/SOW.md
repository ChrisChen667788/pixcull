# Statement of Work · Hiring designers for PixCull Phase B + C

> This document tells **you, the project owner** how to actually
> hire the people the briefs describe.  Phase A shipped already
> (`tokens.json` + build script + CI lint + tests).  Phase B
> needs ~RMB 23k-43k + 2 months; Phase C needs ~RMB 50k-100k +
> 3-6 months.

## 1. What's already shipped

Phase A (engineering infrastructure):

- `design-system/tokens.json` — 79 tokens; designer can edit via
  Tokens Studio Figma plugin
- `scripts/build_design_tokens.py` — JSON → CSS + Swift + Python
- `scripts/lint_design_tokens.py` — CI baseline gate (current 128
  inline hex; goal v1.0 is 0)
- `tests/test_design_tokens.py` — 17 tests covering both scripts
- `Makefile` with `make tokens`, `make tokens-check`,
  `make lint-design`
- `design-system/README.md` — workflow docs for designers +
  engineers

Phase A is **DONE + production-quality**.  Phase B + C are
hiring tasks the briefs in `design-system/briefs/` are ready
for.

## 2. The 6 briefs at a glance

| Brief | Phase | Hire | Duration | Cost (RMB) | Output |
|-------|-------|------|----------|------------|--------|
| 01 · Brand guide | B | Mid-level brand designer | 1 mo | 15k-25k | `BRAND-GUIDE.pdf` + refined `tokens.json` |
| 02 · 10 illustrations | B | Editorial illustrator | 1 mo | 5k-10k | 10 × SVG + PNG, replaces placeholders |
| 03 · Figma library | B | Brief 01's designer OR systems specialist | 2 wk | 10k-18k (bundle: +5k-10k on top of 01) | `.fig` file + Tokens Studio wiring |
| 04 · Custom typeface | C | Type designer (CJK + Latin) | 2-3 mo | 30k-60k | `PixCull Sans` variable font + license |
| 05 · Rive motion | C | Motion designer (Rive specialist) | 4-6 wk | 8k-15k | 4 × `.riv` files + JS integration |
| 06 · Press kit | C | Marketing studio (small) | 4-6 wk | 10k-20k | Visuals + 3 videos + 5 copy docs |

### Phase B total

**1 month** if Brief 01's designer also takes Brief 03 (bundle
pricing).  Otherwise 2 months parallel.  
**Cost**: RMB 30k–53k (bundled).

### Phase C total

**3-6 months** depending on overlap; can run Briefs 04 / 05 / 06
in parallel.  
**Cost**: RMB 48k–95k.

## 3. Where to find these people

### For brand designers (Brief 01 / 03)

**China-based**:
- 站酷 (zcool.com.cn) — direct freelance market
- 设计师社区 (shejishequ) — has B2B-style brand designers
- 优设网 (uisdc.com) recommended-designer board
- 小红书 #品牌设计 hashtag — newer talent, often photographer-friendly

**Anywhere**:
- Working Not Working
- The Dots
- Behance — but vet for "tech product brand systems" not "logo
  one-off" portfolios
- LinkedIn — direct outreach to designers who previously worked
  for Stripe / Linear / Vercel adjacent shops

### For illustrators (Brief 02)

**China-based**:
- Procreate / Apple Pencil community on 小红书
- 插画师 portfolios on 站酷
- Editorial-line-drawing search on 视觉中国

**Anywhere**:
- Dribbble — filter by "editorial illustration" + "line art"
- Reshot has community contributors who freelance
- Direct from artists whose work appears in Dropbox / Notion /
  Linear empty-state pages

### For type designers (Brief 04)

This is the hardest hire — very few people do CJK + Latin
typefaces well.

- **Type@Cooper alumni** — graduates of the NYC type design
  program; LinkedIn search
- **方正字库** (Founder Type) — China's largest commercial CJK
  foundry; sometimes their designers freelance
- **小林章 (Akira Kobayashi)** workshops — Japanese type circle,
  occasional pairings with CJK type designers
- **Klim Type Foundry** — NZ, sometimes does commissions
- **Fontwerk** — Berlin, contemporary work, has done CJK pairings
- **Dalton Maag** — London, large studio with commercial CJK capacity

Realistically: **expect to hire one designer for Latin and a
second for CJK**, both supervised by you for consistency.

### For Rive motion (Brief 05)

- Rive's official **community showcase** (rive.app/community)
  has freelance designers credited
- Twitter / X — Rive specialists are vocal there
- Dribbble — filter "Rive" or "motion design"

### For marketing / press kit (Brief 06)

**China-based** (recommended for Chinese-market launch):
- 极客公园 — has done launches for tech products
- 知群 / 36 氪 freelance writer pools
- 小红书 launch-strategy creator collabs

**Anywhere**:
- ImpactInk for English-side launches
- Smaller agencies who've done Linear / Notion press are usually
  too expensive (~$10k-20k USD); look one tier down.

## 4. Procurement steps — what to do, in order

1. **Now**: Decide Phase B priority order.  Brief 01 → Brief 02
   → Brief 03 sequenced is safest.  Brief 01's brand guide
   informs both 02 + 03.
2. **Week 0**: Post Brief 01 to 3-5 designer channels.  Reply
   to first 3 inquiries; ask for portfolio.  Pick 1.
3. **Week 1-4**: Engage Brief 01 designer.  Daily Slack /
   WeChat sync; weekly review meeting.  At week 4, the brand
   guide PDF should be in your hands.
4. **Week 5-8 (parallel)**:
   - Brief 02 illustrator engaged (3-week sprint)
   - Brief 03 Figma library (2 weeks, may be same designer)
5. **Week 8**: Engineer integrates Phase B outputs into
   `results.html`.  v0.12 release.
6. **Phase C trigger**: 1-2 months after Phase B settles + you
   see the visual improvement landing with users.  Brief 04 +
   05 + 06 can run in parallel; Brief 06 is the only one with a
   release-date dependency (it lands at v1.0).

## 5. Things to watch for during the engagement

### Red flags from designers

- Portfolio is all logos + posters, no tech-product systems work
- Insists on Sketch over Figma (Sketch hasn't been "default" in
  systems work since 2020)
- Asks for "design first, develop later" without consideration
  of `tokens.json` round-trip
- No experience with Tokens Studio plugin (for Brief 01 / 03)

### Green flags

- Asks "where does this color get used in code?" early
- Has shipped a system that survived ≥ 1 year of product
  evolution
- Comfortable with `var(--color-*)` semantics
- Has opinions about typography sizing more refined than
  "small / medium / large"

### Negotiation tips

- Designers under-price the first quote; ask "what's the right
  range for this scope?" before sharing your budget
- Get fixed-project pricing over day-rates for Brief 01 / 02 / 06;
  hourly is OK for Brief 03 / 05
- Always negotiate a **2-revision-round** allowance up front;
  scope creep happens
- Type design (Brief 04) is the only one where day-rate makes
  sense — typefaces are open-ended scope

### Payment + IP

- **50% / 50% split** is standard for short engagements
- **30% / 30% / 40% three-payment** for engagements > 6 weeks
- **All assets revert to PixCull** on payment completion (work-
  for-hire clause).  Exception: Brief 04 typeface, where the
  designer may want retained royalty rights if not SIL-OFL.
- Get a written contract.  Three free templates in
  [Spectrum's contract library](https://contractlibrary.com/) or
  HelloSign templates work.

## 6. After Phase B + C

After all six briefs ship, the visual surface of PixCull should
score ≥ 4.0/5 on the blind-designer-panel metric defined in
[docs/DESIGN-SYSTEM-ROADMAP.md §6](../docs/DESIGN-SYSTEM-ROADMAP.md#6--衡量是否变好了3-个客观指标).
If it doesn't, do another round.

The Phase A token infrastructure means **Phase B + C work
extends Phase A; doesn't replace it**.  Edits to tokens.json by
the new designers automatically flow to all platforms.  No
discontinuity.

---

*SOW version 1.0 · drafted alongside the 6 briefs · revision
expected after first Phase B engagement starts.*
