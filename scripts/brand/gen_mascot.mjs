#!/usr/bin/env node
/**
 * gen_mascot.mjs — Pass 1 of brand-banner-kit.
 *
 * Reads a brand JSON, calls Minimax image-01 three times (9:16, 16:9, 1:1)
 * with prompts tailored per variant, writes raw mascot PNGs to the brand's
 * outputDir as <slug>-mascot-{vertical,horizontal,mark}.png. These files
 * are then consumed by overlay_wordmark.mjs (Pass 2).
 *
 * Usage:
 *   set -a && source .env && set +a
 *   node gen_mascot.mjs <path-to-brand.json>
 *   node gen_mascot.mjs <path-to-brand.json> --only vertical
 *
 * Env: MINIMAX_API_KEY required.
 *
 * Why separate from overlay_wordmark.mjs: the AI call is expensive
 * (~$0.03/image, ~10s/call) and non-deterministic. Splitting lets the
 * caller re-run just the text overlay (cheap, fast) when tweaking
 * wordmark layout without burning more API calls.
 */
import { promises as fs } from 'node:fs';
import path from 'node:path';

const API = 'https://api.minimaxi.com/v1/image_generation';

function parseArgs(argv) {
  const args = argv.slice(2);
  const out = { brandPath: null, only: null };
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--only') out.only = args[++i];
    else if (!out.brandPath) out.brandPath = args[i];
  }
  if (!out.brandPath) {
    console.error('Usage: node gen_mascot.mjs <brand.json> [--only vertical|horizontal|mark]');
    process.exit(2);
  }
  return out;
}

const KEY = process.env.MINIMAX_API_KEY;
if (!KEY) {
  console.error('✗ MINIMAX_API_KEY not in env. Source .env (set -a && source .env && set +a) and retry.');
  process.exit(1);
}

const { brandPath, only } = parseArgs(process.argv);
const brand = JSON.parse(await fs.readFile(brandPath, 'utf8'));
const OUT = brand.outputDir;
await fs.mkdir(OUT, { recursive: true });

/* ─── prompt builder ────────────────────────────────────────────────── */
function basePrompt(brand) {
  return (
    `Subject: a ${brand.mascot}. Mihoyo Honkai Star Rail character art ` +
    `style, premium 5-star gacha character illustration aesthetic, sharp ` +
    `clean lines, high detail. Color palette: ${brand.palette.wordmarkStart} ` +
    `gold + ${brand.palette.wordmarkMid ?? brand.palette.wordmarkEnd} pink/violet ` +
    `rim lighting + deep cosmic background. 8k sharp render.`
  );
}

const PROMPTS = {
  vertical: (brand) =>
    `A vertical full-body character poster of the ${brand.projectName} mascot. ` +
    basePrompt(brand) +
    ` Full-body standing pose (head to feet visible), centered in the lower 60% ` +
    `of the frame. Top 25% is empty negative space (will be overlaid with text ` +
    `later). Bottom 15% is also empty negative space. The mascot holds a small ` +
    `prop tied to the brand subject. Background: deep cosmic gradient ` +
    `(${brand.palette.bgMid} → ${brand.palette.bgCosmic}) with subtle pink/violet ` +
    `aurora glow, soft bokeh particles, starfield specks. Composition: 9:16 ` +
    `portrait. No text overlay, no wordmark, no watermark, no logo.`,

  horizontal: (brand) =>
    `A clean horizontal brand lockup background. ` + basePrompt(brand) +
    ` The chibi mascot sits in the LEFT 30% of the frame, head and shoulders only, ` +
    `cleanly framed and crisp. The RIGHT 70% of the frame is intentionally empty ` +
    `negative space, a smooth cosmic gradient (${brand.palette.bgMid} → ${brand.palette.bgDeep}), ` +
    `reserved for wordmark overlay. No cinematic effects, no bokeh, no starfield, ` +
    `no particles, no spotlight, no banner ribbons — this is a CLEAN lockup, not a ` +
    `hero cover. Subtle pink/violet rim light behind the character only. ` +
    `Composition: 16:9. No text, no wordmark, no watermark.`,

  mark: (brand) =>
    `A minimal icon-only mark of the ${brand.projectName} mascot. JUST the ` +
    `subject's head silhouette, front-facing, simplified to bold clean shapes for ` +
    `use at small sizes and single-color printing. Bright yellow accent eyes are ` +
    `the only color point. Pure flat background (solid dark navy ${brand.palette.bgDeep}), ` +
    `NO decorative frame, NO badge border, NO 5-star card chrome, NO text, NO ` +
    `wordmark, NO background scenery, NO glow effects, NO bokeh, NO particles. ` +
    `Just the simplified silhouette, centered, like a brand monogram. ` +
    `Bauhaus icon clarity meets mihoyo character cuteness. ` +
    `Composition: 1:1 square. No text, no watermark.`,
};

const TASKS = [
  { variant: 'vertical',   aspect_ratio: '9:16', file: `${brand.slug}-mascot-vertical.png` },
  { variant: 'horizontal', aspect_ratio: '16:9', file: `${brand.slug}-mascot-horizontal.png` },
  { variant: 'mark',       aspect_ratio: '1:1',  file: `${brand.slug}-mascot-mark.png` },
];

/* ─── main loop ─────────────────────────────────────────────────────── */
for (const t of TASKS) {
  if (only && t.variant !== only) continue;
  const prompt = PROMPTS[t.variant](brand);
  const outPath = path.join(OUT, t.file);
  console.log(`▶ ${t.variant} (${t.aspect_ratio}) → ${t.file}`);
  try {
    const r = await fetch(API, {
      method: 'POST',
      headers: { Authorization: `Bearer ${KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: 'image-01',
        prompt,
        aspect_ratio: t.aspect_ratio,
        response_format: 'base64',
        n: 1,
      }),
    });
    if (!r.ok) {
      console.error(`  ✗ ${r.status}: ${(await r.text()).slice(0, 200)}`);
      continue;
    }
    const data = await r.json();
    const md = data.data;
    // Minimax has shipped multiple response shapes over time; handle both.
    const b64 = md?.image_base64?.[0] ?? md?.[0]?.image_base64 ?? md?.[0]?.b64_json;
    const url = md?.image_urls?.[0] ?? md?.[0]?.url;
    let buf = null;
    if (b64) buf = Buffer.from(b64, 'base64');
    else if (url) {
      const rr = await fetch(url);
      if (rr.ok) buf = Buffer.from(await rr.arrayBuffer());
    }
    if (!buf) {
      console.error('  ✗ no image data; response head:', JSON.stringify(data).slice(0, 200));
      continue;
    }
    await fs.writeFile(outPath, buf);
    console.log(`  ✓ ${(buf.length / 1024).toFixed(1)} KB`);
  } catch (err) {
    console.error('  ✗', err.message);
  }
}

console.log('\n✓ gen_mascot done. Run overlay_wordmark.mjs next.');
