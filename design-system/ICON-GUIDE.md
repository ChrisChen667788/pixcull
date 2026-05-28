# Icon system (v0.13.16)

PixCull uses a single SVG sprite for all UI icons, embedded once in
`pixcull/report/templates/results.html` and referenced via:

```html
<svg class="icon"><use href="#icon-NAME"/></svg>
```

The sprite supersedes the v0.4-v0.12 pattern of emoji + Unicode +
ad-hoc inline SVG.  This file documents the canonical inventory + the
emoji-to-icon mapping for migration.

## Canonical inventory (24×24, stroke-based, `currentColor` tinted)

| Icon ID | Visual | Surface usage | Replaces (legacy) |
|---|---|---|---|
| `icon-archive` | 📦 file box | History card · run archive | 🗃 |
| `icon-trophy` | 🏆 cup | Burst peak badge | 🏆 |
| `icon-heart` | ♥ heart | Favourites · liked photos | ❤ |
| `icon-contrast` | ◐ half-circle | Theme toggle (light/dark) | — |
| `icon-sparkles` | ✦ stars | AI / Cmd+K palette | ✨ |
| `icon-swap` | ⇆ two arrows | A/B compare | ⇆ |
| `icon-chart` | 📊 bar chart | Admin perf · histogram | 📊 |
| `icon-alert` | ⚠ triangle | Bias finding · warning | ⚠ |
| `icon-pin` | 📍 pin | Bookmark · pin photo | — |
| `icon-grip` | ⋮⋮ six dots | Drag handle (bucket, portfolio) | — |
| `icon-sun` / `icon-moon` | ☀ / ☾ | Theme switcher | ☀ / ☾ |
| **`icon-bookmark`** | bookmark ribbon (outline) | Toggle bookmark — empty state | — |
| **`icon-bookmark-filled`** | bookmark ribbon (filled) | Toggle bookmark — active state | — |
| **`icon-camera`** | classic camera silhouette | Run header · upload page | 📷 |
| **`icon-image`** | photo frame with mountain | Thumb placeholder · gallery | 🖼 |
| **`icon-search`** | magnifying glass | Search box · semantic search | 🔎 |
| **`icon-settings`** | gear | /settings · shortcuts panel | ⚙ |
| **`icon-history`** | clock with arrow | /history nav | 🕒 |
| **`icon-tether`** | wifi arc | Tether mode / LAN sync | 📡 |
| **`icon-bucket`** | delivery bucket | Bucket panel | 🪣 |
| **`icon-share`** | three-node network | Share portfolio link | 🔗 |
| **`icon-undo`** | curved arrow | Cmd+Z affordance | ↶ |

(**Bold** = added in v0.13.16.)

## Sizing

Three sizes mapped to existing CSS classes:

```css
.icon          { width: 16px; height: 16px; }   /* default — inline w/ text */
.icon.icon--sm { width: 12px; height: 12px; }   /* chip / badge */
.icon.icon--lg { width: 22px; height: 22px; }   /* button / toolbar */
```

## Migration policy

Old code with emoji works fine; v0.13.16 doesn't force a sweep.  When
**any** surface gets a substantial rework, replace its inline emoji
with the SVG sprite reference.  Forbid new emoji as load-bearing
chrome from v0.13.16 onward — they're reserved for decorative use only
(toast `🎉`, share preview `📷`).

## Adding a new icon

1. Pick a noun-form name: `icon-NOUN` (no verbs; `icon-trash` not
   `icon-delete`).
2. Author at 24×24 with `viewBox="0 0 24 24"`, stroke-based,
   `currentColor`.  Match Heroicons / Lucide visual weight (2px
   stroke, rounded line-cap).
3. Add to the sprite block in `pixcull/report/templates/results.html`
   (line ~5283).
4. Append a row to this file's inventory table.

## Why not Lucide / Heroicons?

We considered both.  Trade-off:

- **Lucide** (free, 1k+ icons):  ~250 KB if bundled fully.  Tree-shaking
  requires a JS framework PixCull doesn't have.  Manual extraction
  works but creates a sync burden.
- **Heroicons** (Tailwind):  similar size + visual style.
- **Our own sprite**:  ~22 icons × ~0.4 KB = ~9 KB.  Authoring 1 icon
  per quarter is sustainable; consistency is enforced by being
  hand-curated.

Verdict:  our sprite stays.  When the inventory exceeds ~50 icons,
revisit Lucide subset import.

---

doc timestamp: 2027 Q3 (v0.13.16)
predecessor: `pixcull/report/templates/results.html` (sprite source of truth)
sister docs: `design-system/BRAND-GUIDE.md` · `design-system/tokens.json`
