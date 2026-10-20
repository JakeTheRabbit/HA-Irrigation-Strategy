#!/usr/bin/env node
/** Render native lesson diagrams, excluding the five separate paragraph videos.
 * node scripts/render_academy_video_slides.mjs --output <production-root>
 * BROWSER_CHANNEL defaults to msedge. No server, network assets or UI controls.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const help = 'Usage: node scripts/render_academy_video_slides.mjs --output <production-root> [--check-existing]';
const args = process.argv.slice(2), options = {};
for (let i = 0; i < args.length; i++) {
  if (['--help', '-h'].includes(args[i])) { console.log(help); process.exit(0); }
  if (args[i] === '--check-existing') options.check = true;
  else if (args[i] === '--output') {
    assert.ok(args[i + 1] && !args[i + 1].startsWith('--'), help);
    options.output = args[++i];
  } else throw new Error(`Unknown argument: ${args[i]}\n${help}`);
}
assert.ok(options.output, help);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.resolve(options.output), slideDir = path.join(output, 'slides');
const qaDir = path.join(output, 'visual-qa');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const write = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n');
const coursePath = path.join(root, 'www', 'learn', 'course', 'course.json');
const course = read(coursePath), renderer = fs.readFileSync(path.join(root, 'www', 'learn', 'visuals.mjs'), 'utf8');
const paragraphVideos = new Set(['A1', 'A2', 'A3', 'B1', 'C1']);
const lessons = course.lessons.filter(lesson => !paragraphVideos.has(lesson.id));
const sources = lessons.flatMap(lesson => lesson.slides.map(slide => ({ lesson, slide })));
const previousPath = path.join(qaDir, 'academy-slide-bindings.json');
const previous = fs.existsSync(previousPath) ? read(previousPath) : null;
const cached = new Map((previous?.frames || []).map(frame => [`${frame.lesson}:${frame.slide}`, frame]));
assert.equal(new Set(sources.map(({ lesson, slide }) => `${lesson.id}:${slide.id}`)).size, sources.length, 'Duplicate lesson/slide IDs');
const captureHash = hash(fs.readFileSync(fileURLToPath(import.meta.url)));
function assetFiles(visual) {
  if (!visual?.asset) return [];
  assert.match(visual.asset, /^assets\/(?:diagrams|screens)\/[a-zA-Z0-9_./-]+\.(?:png|jpe?g|webp)$/);
  assert.ok(!visual.asset.includes('..'), 'Unsafe asset path');
  const file = path.resolve(root, 'www', 'learn', visual.asset);
  assert.ok(file.startsWith(path.join(root, 'www', 'learn', 'assets') + path.sep));
  return [{ file: visual.asset, sha256: hash(fs.readFileSync(file)) }];
}
async function localAssets(page) {
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://academy.local' || !/^\/learn\/assets\/(?:diagrams|screens)\/[a-zA-Z0-9_./-]+\.(?:png|jpe?g|webp)$/.test(url.pathname)) return route.abort();
    const file = path.resolve(root, 'www', decodeURIComponent(url.pathname).slice(1));
    if (!file.startsWith(path.join(root, 'www', 'learn', 'assets') + path.sep) || !fs.existsSync(file)) return route.abort();
    const contentType = /\.png$/i.test(file) ? 'image/png' : /\.webp$/i.test(file) ? 'image/webp' : 'image/jpeg';
    await route.fulfill({ status: 200, contentType, body: fs.readFileSync(file) });
  });
}
const escape = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
const { chromium } = await import('../frontend/node_modules/playwright/index.mjs');
const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'msedge', args: ['--disable-gpu'] });
try {
  const page = await browser.newPage({ viewport: { width: 854, height: 480 }, deviceScaleFactor: 1 });
  await localAssets(page);
  await page.setContent(`<html><head><base href="http://academy.local/learn/"><style>
    html,body{margin:0;width:854px;height:480px;overflow:hidden;background:#fbfcfd}
    body{display:flex;align-items:center;justify-content:center}
    figure{margin:0;width:854px;height:auto}
    svg{width:854px!important;height:auto!important;border-radius:0!important}
    figure>img{display:block;width:854px!important;height:480px!important;max-width:none!important;object-fit:contain;border-radius:0!important}
    figcaption{display:none}
  </style></head><body></body></html>`);
  await page.evaluate(async source => {
    const url = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }));
    try { window.createVisual = (await import(url)).createVisual; }
    finally { URL.revokeObjectURL(url); }
  }, renderer);
  const bindings = [], failures = [];
  let rendered = 0, reused = 0;
  if (!options.check) { fs.mkdirSync(slideDir, { recursive: true }); fs.mkdirSync(qaDir, { recursive: true }); }
  for (const { lesson, slide } of sources) {
    const assets = assetFiles(slide.visual);
    const qa = await page.evaluate(async ({ visual, lessonId, slideId }) => {
      const figure = window.createVisual(visual, { lessonId, slideId });
      // Captions remain on the website; video frames use the complete visual only.
      figure.querySelector('figcaption')?.remove();
      document.body.replaceChildren(figure);
      await Promise.all([...figure.querySelectorAll('img')].map(img => img.decode()));
      const svg = figure.querySelector('svg'), img = figure.querySelector('img');
      const bounds = (svg || img).getBoundingClientRect();
      const texts = [...figure.querySelectorAll('svg text')].map(t => ({
        text: t.textContent, box: t.getBoundingClientRect().toJSON(),
        fontSize: parseFloat(getComputedStyle(t).fontSize) * bounds.width / 960,
      }));
      const epsilon = 0.5;
      return {
        width: innerWidth, height: innerHeight, kind: img ? 'image' : 'svg',
        svg: svg ? bounds.toJSON() : null, image: img ? bounds.toJSON() : null,
        overflow: texts.filter(({ box }) => box.left < bounds.left - epsilon || box.right > bounds.right + epsilon || box.top < bounds.top - epsilon || box.bottom > bounds.bottom + epsilon),
        minimum_text_px: texts.length ? Math.min(...texts.map(t => t.fontSize)) : null,
        labels: texts.map(t => t.text), visual_markup: (svg || img).outerHTML,
        ui_controls: figure.querySelectorAll('button,input,select,textarea,video,audio').length,
      };
    }, { visual: slide.visual, lessonId: lesson.id, slideId: slide.id });
    assert.equal(qa.width, 854); assert.equal(qa.height, 480); assert.equal(qa.ui_controls, 0);
    assert.equal(qa.kind, assets.length ? 'image' : 'svg', `${slide.id}: asset renderer did not match declared source`);
    if (qa.image) assert.ok(qa.image.x >= 0 && qa.image.y >= 0 && qa.image.right <= 854 && qa.image.bottom <= 480);
    if (qa.overflow.length) failures.push({ lesson: lesson.id, slide: slide.id, type: slide.visual.type, overflow: qa.overflow });
    const file = path.join(slideDir, lesson.id, `${slide.id}.png`);
    if (!options.check) fs.mkdirSync(path.dirname(file), {recursive:true});
    const narrationHash = hash(slide.narration), visualHash = hash(JSON.stringify(slide.visual)), svgHash = hash(qa.visual_markup);
    const old = cached.get(`${lesson.id}:${slide.id}`);
    const canReuse = previous?.capture_sha256 === captureHash && JSON.stringify(old?.asset_files) === JSON.stringify(assets) && previous?.renderer_sha256 === hash(renderer) && old?.narration_sha256 === narrationHash &&
      old?.visual_input_sha256 === visualHash && old?.visual_markup_sha256 === svgHash && fs.existsSync(file) &&
      hash(fs.readFileSync(file)) === old?.png_sha256;
    if (!options.check && !canReuse) { await page.screenshot({ path: file, timeout: 120000, animations: 'disabled' }); rendered++; }
    else reused++;
    const png = fs.readFileSync(file);
    assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    assert.equal(png.readUInt32BE(16), 854); assert.equal(png.readUInt32BE(20), 480);
    bindings.push({ lesson: lesson.id, lesson_title: lesson.title, slide: slide.id, title: slide.title,
      visual_type: slide.visual.type, file: `slides/${lesson.id}/${slide.id}.png`, width: 854, height: 480,
      narration_sha256: narrationHash, visual_input_sha256: visualHash,
      visual_markup_sha256: svgHash, svg_sha256: qa.kind === 'svg' ? svgHash : null, png_sha256: hash(png),
      rendered_kind: qa.kind, asset_files: assets,
      svg_bounds: qa.svg, image_bounds: qa.image, minimum_text_px: qa.minimum_text_px, labels: qa.labels });
  }
  const manifest = { schema: 1, course_edition: course.edition, course_sha256: hash(fs.readFileSync(coursePath)),
    renderer_sha256: hash(renderer), capture_sha256: captureHash, width: 854, height: 480, lessons: lessons.map(l => l.id),
    frame_count: bindings.length, text_bounds_failures: failures.length, frames: bindings };
  if (options.check) {
    assert.deepEqual(manifest, previous, 'Source, renderer, native SVG or PNG binding changed');
  } else {
    write(path.join(qaDir, 'academy-slide-bindings.json'), manifest);
    write(path.join(qaDir, 'academy-slide-bounds.json'), failures);
    // Twelve native frames per sheet, with ID/type labels outside each frame.
    const contact = await browser.newPage({ viewport: { width: 1344, height: 1112 }, deviceScaleFactor: 1 });
    for (let index = 0; index < bindings.length; index += 12) {
      const batch = bindings.slice(index, index + 12);
      const cards = batch.map(binding => `<article><header>${escape(binding.slide)} · ${escape(binding.visual_type)}</header><img src="data:image/png;base64,${fs.readFileSync(path.join(output, binding.file)).toString('base64')}"></article>`).join('');
      await contact.setContent(`<html><head><style>html,body{margin:0;background:#dce6eb;color:#172c3c;font:16px 'Segoe UI',sans-serif}main{padding:12px;display:grid;grid-template-columns:repeat(3,432px);gap:12px}article{margin:0;background:#fff}header{padding:7px 10px;height:22px}img{display:block;width:432px;height:auto}</style></head><body><main>${cards}</main></body></html>`);
      await contact.evaluate(async () => { await Promise.all([...document.images].map(image => image.decode())); });
      await contact.screenshot({ path: path.join(qaDir, `academy-contact-${String(index / 12 + 1).padStart(2, '0')}.png`), fullPage: true });
    }
    await contact.close();
  }
  console.log(JSON.stringify({ mode: options.check ? 'check-existing' : 'render', lessons: lessons.length,
    slides: bindings.length, rendered, reused, types: [...new Set(bindings.map(b => b.visual_type))], text_bounds_failures: failures.length,
    bounds_file: path.join(qaDir, 'academy-slide-bounds.json'), manifest: path.join(qaDir, 'academy-slide-bindings.json') }, null, 2));
  // Keep every source frame and the full issue report for review; never hide overflow.
  if (failures.length) process.exitCode = 2;
} finally { await browser.close(); }
