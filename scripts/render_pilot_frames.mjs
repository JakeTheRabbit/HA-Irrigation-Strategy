#!/usr/bin/env node
/**
 * Render paragraph cards without an application server or external network assets.
 *
 * node scripts/render_pilot_frames.mjs --output <production-root>
 * node scripts/render_pilot_frames.mjs --output <production-root> \
 *   --motion-alignment <word-anchors.json>
 * node scripts/render_pilot_frames.mjs --output <production-root> --check-existing
 *
 * --motion-alignment accepts {words:[{word,start,end}]} from the actual
 * B1-05-p03 voice take, or a ready.json referring to that word_anchors file.
 * Its narration/B1-05-p03.json receipt must already exist under --output.
 * Timing comes from those words and that receipt; no audio timing is assumed.
 * BROWSER_CHANNEL selects Playwright's browser (default: msedge).
 * --check-existing performs read-only source, layout, PNG and manifest checks.
 * Install the existing frontend dependencies before running this script.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const help = `Usage: node scripts/render_pilot_frames.mjs --output <production-root>
  [--motion-alignment <word-anchors.json-or-ready.json>] [--check-existing]

Renders frames/<paragraph-id>.png and checks native 854x480 text bounds.
Optional motion uses the actual B1-05-p03 narration receipt and word timestamps.
--check-existing reads and verifies existing files without writing anything.
BROWSER_CHANNEL defaults to msedge. --help shows this message.`;
const args = process.argv.slice(2), options = {};
for (let i = 0; i < args.length; i++) {
  const arg = args[i];
  if (arg === '--help' || arg === '-h') { console.log(help); process.exit(0); }
  if (arg === '--check-existing') options.check = true;
  else if (['--output', '--motion-alignment'].includes(arg)) {
    assert.ok(args[i + 1] && !args[i + 1].startsWith('--'), `Missing value for ${arg}`);
    options[arg.slice(2)] = args[++i];
  } else throw new Error(`Unknown argument: ${arg}\n${help}`);
}
assert.ok(options.output, help);
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const learn = path.join(root, 'www', 'learn'), output = path.resolve(options.output);
const read = file => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
const write = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2));
const cards = ['a1', 'other'].flatMap(name => read(path.join(learn, 'course', `pilot-cues-${name}.json`)));
const sources = read(path.join(learn, 'course', 'modules', 'pilots.json'));
const expected = sources.flatMap(lesson => lesson.slides.flatMap(slide =>
  slide.narration.split(/\r?\n\s*\r?\n/).map((text, paragraph) => ({
    id: `${slide.id}-p${String(paragraph + 1).padStart(2, '0')}`,
    lesson: lesson.id, scene: slide.id, paragraph, text,
  }))));
assert.equal(new Set(cards.map(c => c.id)).size, cards.length, 'Duplicate cue IDs');
assert.equal(cards.length, expected.length, 'Source/cue paragraph count differs');
for (const source of expected) {
  const card = cards.find(c => c.id === source.id);
  assert.ok(card, `Missing cue ${source.id}`);
  for (const [key, value] of Object.entries(source)) assert.equal(card[key], value, `Source mismatch: ${source.id}.${key}`);
}
const renderer = fs.readFileSync(path.join(learn, 'pilot-frames.mjs'), 'utf8');
const captureHash = hash(fs.readFileSync(fileURLToPath(import.meta.url)));
function assetFiles(card) {
  const asset = card.visual?.asset;
  if (!asset) return [];
  assert.match(asset, /^assets\/(?:diagrams|screens)\/[a-zA-Z0-9_./-]+\.(?:png|jpe?g|webp)$/);
  assert.ok(!asset.includes('..'), 'Unsafe asset path');
  const file = path.resolve(learn, asset);
  assert.ok(file.startsWith(path.join(learn, 'assets') + path.sep));
  return [{ file: asset, sha256: hash(fs.readFileSync(file)) }];
}
const { chromium } = await import('../frontend/node_modules/playwright/index.mjs');
const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'msedge', args: ['--disable-gpu'] });
try {
  const page = await browser.newPage({ viewport: { width: 854, height: 480 }, deviceScaleFactor: 1 });
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://academy.local' || !/^\/learn\/assets\/(?:diagrams|screens)\/[a-zA-Z0-9_./-]+\.(?:png|jpe?g|webp)$/.test(url.pathname)) return route.abort();
    const file = path.resolve(root, 'www', decodeURIComponent(url.pathname).slice(1));
    if (!file.startsWith(path.join(learn, 'assets') + path.sep) || !fs.existsSync(file)) return route.abort();
    await route.fulfill({status:200, contentType:/\.png$/i.test(file)?'image/png':/\.webp$/i.test(file)?'image/webp':'image/jpeg',body:fs.readFileSync(file)});
  });
  await page.setContent('<html><head><base href="http://academy.local/learn/"></head><body style="margin:0"></body></html>');
  await page.evaluate(async source => {
    const url = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }));
    try { window.renderPilotCard = (await import(url)).renderPilotCard; }
    finally { URL.revokeObjectURL(url); }
  }, renderer);
  async function render(card) {
    await page.evaluate(async c => { document.body.replaceChildren(window.renderPilotCard(c)); await Promise.all([...document.images].map(img => img.decode())); }, card);
    const qa = await page.evaluate(() => {
      const article = document.querySelector('article'), bounds = article.getBoundingClientRect();
      const overflow = [...article.querySelectorAll('svg text')].map(t => ({ text: t.textContent, r: t.getBoundingClientRect().toJSON() }))
        .filter(({ r }) => r.x < 27 || r.right > 827 || r.top < 93 || r.bottom > 405);
      const heading = article.querySelector('h1');
      if (heading && heading.getBoundingClientRect().bottom > 94) overflow.push({ heading: 'wrap' });
      const images = [...article.querySelectorAll('img')].map(img => ({src: img.getAttribute('src'), width: img.naturalWidth, height: img.naturalHeight, bounds: img.getBoundingClientRect().toJSON()}));
      for (const img of images) if (!img.width || !img.height || img.bounds.left < 0 || img.bounds.top < 0 || img.bounds.right > 854 || img.bounds.bottom > 480) overflow.push({image:img});
      const traces = [...article.querySelectorAll('svg path')].filter(p => ['#1878b9', '#b76628'].includes(p.getAttribute('stroke')))
        .map(p => ({ stroke: p.getAttribute('stroke'), d: p.getAttribute('d') }));
      return { width: bounds.width, height: bounds.height, overflow, traces, images,
        labels: [...article.querySelectorAll('svg text')].map(t => t.textContent) };
    });
    assert.equal(qa.width, 854); assert.equal(qa.height, 480);
    assert.equal(qa.overflow.length, 0, `${card.id} text outside teaching area: ${JSON.stringify(qa.overflow)}`);
    assert.equal(qa.images.length, assetFiles(card).length, `${card.id}: declared asset did not render`);
    return qa;
  }
  function png(file) {
    const data = fs.readFileSync(file);
    assert.equal(data.subarray(0, 8).toString('hex'), '89504e470d0a1a0a', `Invalid PNG: ${file}`);
    assert.equal(data.readUInt32BE(16), 854); assert.equal(data.readUInt32BE(20), 480);
    return hash(data);
  }
  const frameDir = path.join(output, 'frames'), frameHashes = [];
  const previousFile = path.join(output, 'visual-qa', 'frame-hashes.json');
  if (options.check) assert.ok(fs.existsSync(previousFile), 'Cannot verify existing frames without their source/hash manifest');
  const previous = new Map((fs.existsSync(previousFile) ? read(previousFile) : []).map(frame => [frame.file, frame]));
  if (!options.check) fs.mkdirSync(frameDir, { recursive: true });
  for (const card of cards) {
    await render(card);
    const file = path.join(frameDir, `${card.id}.png`);
    const binding = {file:path.basename(file), source_sha256:hash(JSON.stringify(card)), renderer_sha256:hash(renderer), capture_sha256:captureHash, asset_files:assetFiles(card)};
    const old = previous.get(binding.file), reusable = old && fs.existsSync(file) && old.sha256 === png(file) &&
      Object.entries(binding).every(([key,value]) => JSON.stringify(old[key]) === JSON.stringify(value));
    if (!options.check && !reusable) await page.screenshot({ path: file, timeout: 120000, animations: 'disabled' });
    frameHashes.push({ ...binding, sha256: png(file) });
    if (!options.check) {
      fs.mkdirSync(path.join(output, 'visual-qa'), {recursive:true});
      write(previousFile, frameHashes); // Source-bound checkpoint: a retry can reuse completed frames.
      if (frameHashes.length % 12 === 0) console.log(`Captured/verified ${frameHashes.length}/${cards.length} pilot frames`);
    }
  }
  const summary = { mode: options.check ? 'check-existing' : 'render', cards: cards.length,
    source_coverage: 'exact', text_bounds_failures: 0, renderer_sha256: hash(renderer), capture_sha256: captureHash,
    frames_manifest_sha256: hash(JSON.stringify(frameHashes)) };
  if (!options.check) {
    fs.mkdirSync(path.join(output, 'visual-qa'), { recursive: true });
    write(path.join(output, 'visual-qa', 'frame-hashes.json'), frameHashes);
    write(path.join(output, 'visual-qa', 'bounds.json'), []);
  } else if (fs.existsSync(path.join(output, 'visual-qa', 'frame-hashes.json'))) {
    assert.deepEqual(frameHashes, read(path.join(output, 'visual-qa', 'frame-hashes.json')), 'Base PNG hashes differ');
  }
  const motionDir = path.join(output, 'motion', 'B1-05-p03');
  if (options['motion-alignment'] && !options.check) {
    const alignmentPath = path.resolve(options['motion-alignment']);
    let alignment = read(alignmentPath);
    if (alignment.word_anchors) {
      const referenced = path.resolve(path.dirname(alignmentPath), alignment.word_anchors);
      alignment = read(referenced);
    }
    const words = alignment.words || alignment.actual_voice_anchors;
    assert.ok(Array.isArray(words), 'Alignment requires actual word timestamps');
    const normalized = w => w.word.toLowerCase().replace(/[^a-z-]/g, '');
    const changeIndex = words.findIndex(w => normalized(w) === 'changes');
    const toIndex = words.findIndex((w, i) => i > changeIndex && normalized(w) === 'to');
    const percentIndex = words.findIndex((w, i) => i > toIndex && normalized(w) === 'percent');
    assert.ok(changeIndex >= 0 && toIndex > changeIndex && percentIndex > toIndex, 'Cannot locate the spoken changes ... to ... percent clause');
    const receipt = read(path.join(output, 'narration', 'B1-05-p03.json'));
    const original = cards.find(c => c.id === 'B1-05-p03');
    assert.equal(receipt.text, original.text, 'Motion audio receipt is stale');
    const fps = 24, frames = receipt.frames;
    assert.ok(Number.isInteger(frames) && frames > 0);
    assert.ok(Math.abs(receipt.duration - frames / fps) < 0.001, 'Motion duration differs from receipt');
    const start = Math.round(words[changeIndex].start * fps), end = Math.round(words[percentIndex].end * fps);
    assert.ok(start >= 0 && end > start && end < frames, 'Spoken motion clause is outside the narration');
    const [before, after] = original.visual.values;
    assert.ok(Number.isFinite(before) && Number.isFinite(after) && before !== after);
    const uniqueDir = path.join(motionDir, 'unique'), sequenceDir = path.join(motionDir, 'frames');
    fs.mkdirSync(uniqueDir, { recursive: true }); fs.mkdirSync(sequenceDir, { recursive: true });
    // Invalidate readiness before changing a sequence; publish it only after all checks pass.
    if (fs.existsSync(path.join(motionDir, 'ready.json'))) fs.unlinkSync(path.join(motionDir, 'ready.json'));
    const unique = []; let traces;
    for (let step = 0; step <= 48; step++) {
      const value = Number((before + (after - before) * step / 48).toFixed(2));
      const card = structuredClone(original);
      card.visual.values = [before, value];
      card.visual.labels = [`Saved ${before}% → local draft ${value}%`, 'Synthetic readings stay unchanged'];
      const qa = await render(card), signature = hash(JSON.stringify(qa.traces));
      if (traces) assert.equal(signature, traces, 'Observed traces changed during the edit'); else traces = signature;
      if (step === 0) assert.ok(!qa.labels.some(l => l.includes(`${after}%`)), 'Final draft leaked into initial picture');
      const file = path.join(uniqueDir, `value_${String(step).padStart(2, '0')}.png`);
      await page.screenshot({ path: file, timeout: 120000, animations: 'disabled' }); unique.push({ file, value });
    }
    const hashes = [], timeline = [];
    for (let frame = 0; frame < frames; frame++) {
      const step = frame <= start ? 0 : frame >= end ? 48 : Math.round((frame - start) / (end - start) * 48);
      const file = `frame_${String(frame).padStart(4, '0')}.png`, destination = path.join(sequenceDir, file);
      fs.copyFileSync(unique[step].file, destination); hashes.push({ file, sha256: png(destination) });
      timeline.push({ frame, time: frame / fps, step, value: unique[step].value });
    }
    // Reject stale trailing frames from a previous, longer audio take.
    assert.equal(fs.readdirSync(sequenceDir).filter(f => /^frame_\d{4}\.png$/.test(f)).length, frames,
      'Stale motion frames exist; use a fresh output directory');
    write(path.join(motionDir, 'word-anchors.json'), alignment);
    write(path.join(motionDir, 'frame-hashes.json'), hashes);
    write(path.join(motionDir, 'frame-timeline.json'), timeline);
    const ready = { id: original.id, status: 'ready',
      audio_sha256: hash(fs.readFileSync(path.join(output, 'narration', `${original.id}.wav`))),
      audio_receipt_sha256: hash(fs.readFileSync(path.join(output, 'narration', `${original.id}.json`))),
      source_sha256: hash(original.text), frozen: true, fps, frames, frame_count: frames,
      duration: frames / fps, width: 854, height: 480, first_frame: 0, last_frame: frames - 1,
      frame_pattern: path.join(sequenceDir, 'frame_%04d.png'), saved_value: before, initial_value: before, final_value: after,
      movement_start_frame: start, movement_end_frame: end, movement_start_seconds: start / fps, movement_end_seconds: end / fps,
      word_clause_start: words[changeIndex].start, word_clause_end: words[percentIndex].end,
      word_anchors: path.join(motionDir, 'word-anchors.json'), actual_voice_anchors: words.slice(changeIndex, percentIndex + 1),
      frame_hashes: path.join(motionDir, 'frame-hashes.json'), frames_manifest_sha256: hash(JSON.stringify(hashes)),
      observed_trace_sha256: traces, renderer_sha256: hash(renderer), unique_screenshots: unique.length };
    write(path.join(motionDir, 'motion-receipt.json'), ready);
    write(path.join(motionDir, 'ready.tmp.json'), ready);
    fs.renameSync(path.join(motionDir, 'ready.tmp.json'), path.join(motionDir, 'ready.json'));
    summary.motion_frames = frames;
  } else if (options.check && fs.existsSync(path.join(motionDir, 'ready.json'))) {
    const ready = read(path.join(motionDir, 'ready.json')), hashes = read(path.join(motionDir, 'frame-hashes.json'));
    const files = fs.readdirSync(path.join(motionDir, 'frames')).filter(f => /^frame_\d{4}\.png$/.test(f)).sort();
    assert.equal(files.length, ready.frames); assert.equal(hashes.length, ready.frames);
    for (let i = 0; i < files.length; i++) {
      assert.equal(files[i], `frame_${String(i).padStart(4, '0')}.png`);
      assert.equal(hashes[i].file, files[i]); assert.equal(png(path.join(motionDir, 'frames', files[i])), hashes[i].sha256);
    }
    assert.equal(hash(JSON.stringify(hashes)), ready.frames_manifest_sha256);
    summary.motion_frames = files.length; summary.motion_hashes = 'verified';
  }
  console.log(JSON.stringify(summary, null, 2));
} finally { await browser.close(); }
