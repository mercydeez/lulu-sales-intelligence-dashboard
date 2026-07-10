#!/usr/bin/env node
/**
 * Generate the raster brand assets (PNG + ICO) from the vector source of truth,
 * public/branding/favicon.svg. Run when the mark changes.
 *
 *   cd frontend
 *   npm i -D sharp png-to-ico
 *   node scripts/branding/generate-rasters.mjs
 *
 * Outputs into public/branding/:
 *   favicon-16.png, favicon-32.png, apple-touch-icon.png (180), favicon.ico (16+32+48)
 *
 * Kept as a script (not a build step) so the deploy pipeline needs no native deps.
 */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const brandingDir = join(here, '..', '..', 'public', 'branding');

// Apple touch icons must be opaque (no transparency) — flatten onto white.
const APPLE_BG = { r: 255, g: 255, b: 255, alpha: 1 };

async function main() {
  const sharp = (await import('sharp')).default;
  const pngToIco = (await import('png-to-ico')).default;

  await mkdir(brandingDir, { recursive: true });
  const svg = await readFile(join(brandingDir, 'favicon.svg'));

  const png = (size, opts = {}) =>
    sharp(svg, { density: 384 })
      .resize(size, size, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 }, ...opts })
      .png()
      .toBuffer();

  const f16 = await png(16);
  const f32 = await png(32);
  const f48 = await png(48);
  await writeFile(join(brandingDir, 'favicon-16.png'), f16);
  await writeFile(join(brandingDir, 'favicon-32.png'), f32);

  // Apple touch icon: 180×180 on an opaque white field with a little padding.
  const apple = await sharp(svg, { density: 512 })
    .resize(150, 150, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .extend({ top: 15, bottom: 15, left: 15, right: 15, background: APPLE_BG })
    .flatten({ background: APPLE_BG })
    .png()
    .toBuffer();
  await writeFile(join(brandingDir, 'apple-touch-icon.png'), apple);

  await writeFile(join(brandingDir, 'favicon.ico'), await pngToIco([f16, f32, f48]));

  console.log('✓ Wrote favicon-16.png, favicon-32.png, apple-touch-icon.png, favicon.ico to public/branding/');
}

main().catch((err) => {
  console.error('Raster generation failed:', err);
  process.exit(1);
});
