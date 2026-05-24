#!/usr/bin/env node
/**
 * overlay_wordmark.mjs — Pass 2 of brand-banner-kit.
 *
 * Reads the raw mascot PNGs produced by gen_mascot.mjs, layers HTML over
 * each (backdrop fade + real-font wordmark + tagline), screenshots at 2× DPR,
 * writes the final ship-ready PNGs:
 *
 *   <slug>-vertical-poster.png      (9:16, with wordmark + tagline)
 *   <slug>-horizontal-lockup.png    (16:9, with wordmark + subtitle + tagline)
 *   <slug>-mark-only.png            (1:1, NO overlay — passthrough copy)
 *
 * Usage:
 *   node overlay_wordmark.mjs <path-to-brand.json>
 *
 * Why Playwright instead of canvas / sharp: HTML + CSS gives the best
 * control over real system fonts, gradient text (background-clip: text),
 * and layered backdrops that fade-cover AI watermarks. Sharp/Jimp would
 * need manual font metrics work and lose the gradient text trick.
 */
import { chromium } from 'playwright';
import { promises as fs } from 'node:fs';
import path from 'node:path';

if (process.argv.length < 3) {
  console.error('Usage: node overlay_wordmark.mjs <brand.json>');
  process.exit(2);
}

const brandPath = process.argv[2];
const brand = JSON.parse(await fs.readFile(brandPath, 'utf8'));
const OUT = brand.outputDir;
const SLUG = brand.slug;

/* The three jobs. Mark-only is intentionally passthrough — no text. */
const JOBS = [
  {
    variant: 'vertical',
    src: path.join(OUT, `${SLUG}-mascot-vertical.png`),
    out: path.join(OUT, `${SLUG}-vertical-poster.png`),
    width: 720, height: 1280,
    html: verticalHTML(brand),
  },
  {
    variant: 'horizontal',
    src: path.join(OUT, `${SLUG}-mascot-horizontal.png`),
    out: path.join(OUT, `${SLUG}-horizontal-lockup.png`),
    width: 1280, height: 720,
    html: horizontalHTML(brand),
  },
  {
    variant: 'mark',
    src: path.join(OUT, `${SLUG}-mascot-mark.png`),
    out: path.join(OUT, `${SLUG}-mark-only.png`),
    width: 1024, height: 1024,
    html: null,  // passthrough — copy raw bytes
  },
];

const browser = await chromium.launch();

for (const job of JOBS) {
  if (!await pathExists(job.src)) {
    console.error(`✗ missing source ${job.src} — run gen_mascot.mjs first`);
    continue;
  }
  if (job.html == null) {
    // Passthrough copy for mark-only.
    await fs.copyFile(job.src, job.out);
    const sz = (await fs.stat(job.out)).size;
    console.log(`✓ ${job.variant} (passthrough) → ${job.out} (${(sz / 1024).toFixed(1)} KB)`);
    continue;
  }
  console.log(`▶ ${job.variant} → ${job.out}`);
  const raw = await fs.readFile(job.src);
  const dataUrl = `data:image/png;base64,${raw.toString('base64')}`;
  const ctx = await browser.newContext({
    viewport: { width: job.width, height: job.height },
    deviceScaleFactor: 2,
  });
  const page = await ctx.newPage();
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8">
    <style>
      html, body { margin:0; padding:0; width:${job.width}px; height:${job.height}px; overflow:hidden; }
      .stage { position:relative; width:100%; height:100%;
        background: url('${dataUrl}') center/cover no-repeat; }
    </style></head><body>
    <div class="stage">${job.html}</div>
    </body></html>`);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(150);  // font + gradient settle
  const buf = await page.screenshot({
    type: 'png',
    clip: { x: 0, y: 0, width: job.width, height: job.height },
    omitBackground: false,
  });
  await fs.writeFile(job.out, buf);
  console.log(`  ✓ ${(buf.length / 1024).toFixed(1)} KB`);
  await ctx.close();
}

await browser.close();
console.log('\n✓ overlay_wordmark done.');

/* ─── helpers ──────────────────────────────────────────────────────── */
async function pathExists(p) {
  try { await fs.access(p); return true; } catch { return false; }
}

function gradient(brand) {
  const c1 = brand.palette.wordmarkStart;
  const c2 = brand.palette.wordmarkMid;
  const c3 = brand.palette.wordmarkEnd;
  return c2
    ? `linear-gradient(135deg, ${c1} 0%, ${c2} 50%, ${c3} 100%)`
    : `linear-gradient(135deg, ${c1} 0%, ${c3} 100%)`;
}

function verticalHTML(brand) {
  // Backdrop layers: opaque navy → transparent fade fully covers AI
  // garbled watermark in top + bottom strips. Real font sits on top.
  return `
    <div style="position:absolute; top:0; left:0; right:0; height:210px;
      background: linear-gradient(180deg,
        ${brand.palette.bgDeep}ff 0%,
        ${brand.palette.bgMid}f7 55%,
        ${brand.palette.bgMid}8c 85%,
        ${brand.palette.bgMid}00 100%);
      pointer-events: none;"></div>
    <div style="position:absolute; top:48px; left:0; right:0;
      display:flex; flex-direction:column; align-items:center;
      gap:14px; padding:0 28px;">
      <div style="
        font: 900 60px/1 -apple-system, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans CJK SC', system-ui, sans-serif;
        letter-spacing: -0.03em;
        background: ${gradient(brand)};
        -webkit-background-clip: text; background-clip: text;
        color: transparent;
        text-shadow: 0 0 28px ${brand.palette.wordmarkMid ?? brand.palette.wordmarkEnd}8c;
      ">${brand.projectName}</div>
      ${brand.subtitle ? `<div style="
        font: 800 17px/1.2 -apple-system, 'PingFang SC', system-ui, sans-serif;
        letter-spacing: 0.20em; text-transform: uppercase;
        color: ${brand.palette.wordmarkStart}; opacity: 0.92;
        text-shadow: 0 0 8px ${brand.palette.wordmarkStart}73;
      ">${spaceCJK(brand.subtitle)}</div>` : ''}
    </div>
    <div style="position:absolute; bottom:0; left:0; right:0; height:140px;
      background: linear-gradient(0deg,
        ${brand.palette.bgDeep}ff 0%,
        ${brand.palette.bgMid}f5 55%,
        ${brand.palette.bgMid}00 100%);
      pointer-events: none;"></div>
    <div style="position:absolute; bottom:34px; left:0; right:0;
      display:flex; flex-direction:column; align-items:center; gap:6px;">
      ${brand.tagline ? `<div style="
        font: 700 16px/1.3 -apple-system, 'PingFang SC', system-ui, sans-serif;
        color: rgba(248, 244, 227, 0.92);
        text-align: center; padding: 0 24px;
      ">${brand.tagline}</div>` : ''}
      ${brand.footerLine ? `<div style="
        font: 700 11px/1 -apple-system, system-ui, sans-serif;
        letter-spacing: 0.15em; color: ${brand.palette.wordmarkStart}; opacity: 0.85;
      ">${brand.footerLine.toUpperCase()}</div>` : ''}
    </div>
  `;
}

function horizontalHTML(brand) {
  // Wordmark sits in the right 70% negative space. No backdrop needed —
  // the AI prompt told it to leave that area clean (and it usually does).
  return `
    <div style="position:absolute; top:50%; left:42%; right:48px;
      transform: translateY(-50%);
      display:flex; flex-direction:column; align-items:flex-start; gap:14px;">
      <div style="
        font: 900 96px/1 -apple-system, 'PingFang SC', 'Hiragino Sans GB', system-ui, sans-serif;
        letter-spacing: -0.035em;
        background: ${gradient(brand)};
        -webkit-background-clip: text; background-clip: text;
        color: transparent;
        text-shadow: 0 0 32px ${brand.palette.wordmarkMid ?? brand.palette.wordmarkEnd}73;
      ">${brand.projectName}</div>
      ${brand.subtitle ? `<div style="
        font: 800 18px/1 -apple-system, 'PingFang SC', system-ui, sans-serif;
        letter-spacing: 0.22em; text-transform: uppercase;
        color: ${brand.palette.wordmarkStart}; opacity: 0.85;
      ">${spaceCJK(brand.subtitle)}</div>` : ''}
      ${brand.tagline ? `<div style="
        font: 700 19px/1.4 -apple-system, 'PingFang SC', system-ui, sans-serif;
        color: rgba(248, 244, 227, 0.82); margin-top: 6px;
      ">${brand.tagline}</div>` : ''}
    </div>
  `;
}

/** Insert a thin space between CJK chars so subtitle reads as
 *  letter-spaced even when no CSS letter-spacing applies to CJK. */
function spaceCJK(s) {
  return [...s].map((c, i, arr) => {
    const next = arr[i + 1];
    const isCJK = /[一-鿿]/.test(c);
    const nextIsCJK = next && /[一-鿿]/.test(next);
    return isCJK && nextIsCJK ? `${c} ` : c;
  }).join('');
}
