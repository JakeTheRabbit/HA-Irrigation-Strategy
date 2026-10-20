// Gather narration audio, durations and word timings for each lesson, resolve scene
// cue phrases to times, and write public/data/<lesson>.json for the Remotion compositions.
// Usage: node scripts/prepare.mjs [--production <dir>] [A1 A2 ...]
import fs from "node:fs";
import path from "node:path";

const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const videoRoot = path.resolve(here, "..");
const repo = path.resolve(videoRoot, "..");
const args = process.argv.slice(2);
const prodAt = args.indexOf("--production");
const production = prodAt >= 0 ? args.splice(prodAt, 2)[1] : "C:/Content/Crop Steering from Zero/2026-10-20-course-r4";
const course = JSON.parse(fs.readFileSync(path.join(repo, "www/learn/course/course.json"), "utf8"));
const PILOTS = new Set(["A1", "A2", "A3", "B1", "C1"]);
const wanted = args.length ? new Set(args) : null;

const norm = (w) => w.toLowerCase().replace(/[^a-z0-9]+/g, "");

// Speech recognition writes "60%", "$15", "0.8"; the script says "sixty percent".
// Spell recognised numbers out so both sides compare as words.
const ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(" ");
const TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split(" ");
function spell(n) {
  if (n < 20) return ONES[n];
  if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? ONES[n % 10] : "");
  if (n < 1000) return ONES[Math.floor(n / 100)] + "hundred" + (n % 100 ? spell(n % 100) : "");
  return spell(Math.floor(n / 1000)) + "thousand" + (n % 1000 ? spell(n % 1000) : "");
}
function asrTokens(raw) {
  const out = [];
  const text = raw.replace(/,(?=\d{3})/g, "");
  for (const part of text.split(/(?=[%$])|(?<=[%$])|[\s/]+/)) {
    if (part === "%") out.push("percent");
    else if (part === "$") continue;
    else if (/^\d+(\.\d+)?$/.test(part.replace(/[^\d.]/g, "")) && /\d/.test(part)) {
      const [whole, frac] = part.replace(/[^\d.]/g, "").split(".");
      out.push(spell(Number(whole)));
      if (frac) out.push("point", ...frac.split("").map((d) => ONES[Number(d)]));
      if (/^\$/.test(raw)) out.push("dollars");
    } else if (norm(part)) out.push(norm(part));
  }
  return out;
}

// Longest-common-subsequence alignment of script tokens to recognised tokens, so every
// script word gets a time even where recognition misheard it (interpolated between matches).
function align(script, heard) {
  const n = script.length, m = heard.length;
  const L = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      L[i][j] = script[i].n === heard[j].n ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const times = new Array(n).fill(null);
  for (let i = 0, j = 0; i < n && j < m; ) {
    if (script[i].n === heard[j].n) { times[i] = [heard[j].s, heard[j].e]; i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) i++;
    else j++;
  }
  // Fill gaps by interpolating between the nearest matched neighbours.
  for (let i = 0; i < n; i++) {
    if (times[i]) continue;
    let a = i - 1; while (a >= 0 && !times[a]) a--;
    let b = i + 1; while (b < n && !times[b]) b++;
    const t0 = a >= 0 ? times[a][1] : (heard.length ? heard[0].s : 0), t1 = b < n ? times[b][0] : (heard.length ? heard[heard.length - 1].e : 0);
    const k = (i - a) / (b - a);
    const t = t0 + (t1 - t0) * k;
    times[i] = [t, t];
  }
  // A stray match (the same word heard elsewhere) can land out of order; keep time monotonic.
  for (let i = 1; i < n; i++) {
    if (times[i][0] < times[i - 1][0]) times[i] = [times[i - 1][1], Math.max(times[i - 1][1], times[i][1])];
  }
  return times;
}
const readJson = (p) => JSON.parse(fs.readFileSync(p, "utf8"));

function units(lesson, slide) {
  if (PILOTS.has(lesson.id))
    return slide.narration.split("\n\n").map((_, i) => {
      const id = `${slide.id}-p${String(i + 1).padStart(2, "0")}`;
      return { id, wav: path.join(production, "narration", `${id}.wav`), receipt: path.join(production, "narration", `${id}.json`), asr: path.join(production, "reports", `${id}-asr.json`) };
    });
  const id = `${lesson.id}--${slide.id}`;
  return [{ id, wav: path.join(production, "narration", lesson.id, `${slide.id}.wav`), receipt: path.join(production, "narration", lesson.id, `${slide.id}.json`), asr: path.join(production, "reports", `${id}-asr.json`) }];
}

// Find where a cue phrase starts in the slide's spoken words (searching from `from`).
function locate(words, phrase, from = 0) {
  const target = phrase.split(/\s+/).map(norm).filter(Boolean);
  for (let i = from; i <= words.length - target.length; i++)
    if (target.every((t, k) => words[i + k].n === t)) return i;
  // Speech recognition can merge or split tokens: fall back to a joined-text search.
  const joined = target.join("");
  for (let i = from; i < words.length; i++) {
    let acc = "";
    for (let k = i; k < Math.min(words.length, i + target.length + 3); k++) {
      acc += words[k].n;
      if (acc === joined) return i;
      if (!joined.startsWith(acc)) break;
    }
  }
  return -1;
}

const problems = [];
fs.mkdirSync(path.join(videoRoot, "public/data"), { recursive: true });
// Scenes load the academy's illustrations and app screenshots from public/img.
for (const sub of ["diagrams", "screens"])
  fs.cpSync(path.join(repo, "www/learn/assets", sub), path.join(videoRoot, "public/img", sub), { recursive: true });
for (const lesson of course.lessons) {
  if (wanted && !wanted.has(lesson.id)) continue;
  const sceneFile = path.join(videoRoot, "scenes", `${lesson.id}.json`);
  const scenes = fs.existsSync(sceneFile) ? readJson(sceneFile) : { slides: {} };
  const out = { id: lesson.id, title: lesson.title, summary: lesson.summary, slides: [] };
  for (const slide of lesson.slides) {
    const list = [];
    let offset = 0;
    const words = [];
    const texts = PILOTS.has(lesson.id) ? slide.narration.split("\n\n") : [slide.narration];
    for (const [ui, u] of units(lesson, slide).entries()) {
      const receipt = readJson(u.receipt);
      const rel = `audio/${lesson.id}/${path.basename(u.wav)}`;
      const dest = path.join(videoRoot, "public", rel);
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      if (!fs.existsSync(dest) || fs.statSync(dest).size !== fs.statSync(u.wav).size) fs.copyFileSync(u.wav, dest);
      const heard = readJson(u.asr).words.flatMap((w) => asrTokens(w.word.trim()).map((n) => ({ n, s: offset + w.start, e: offset + w.end })));
      const script = texts[ui].split(/\s+/).filter((w) => norm(w)).map((w) => ({ w, n: norm(w) }));
      align(script, heard).forEach(([s, e], k) => words.push({ ...script[k], s, e }));
      list.push({ src: rel, start: offset, duration: receipt.duration });
      offset += receipt.duration;
    }
    const beats = [];
    let cursor = 0;
    for (const [bi, beat] of (scenes.slides[slide.id] || []).entries()) {
      let at = 0;
      if (bi > 0 || beat.cue) {
        const i = beat.cue ? locate(words, beat.cue, cursor) : -1;
        if (i < 0) problems.push(`${lesson.id}/${slide.id} beat ${bi}: cue not spoken: "${beat.cue}"`);
        else { at = Math.max(0, words[i].s - 0.15); cursor = i; }
      }
      const steps = (beat.steps || []).map((phrase) => {
        if (!phrase) return null; // a skipped slot: the scene uses its own timing for it
        const i = locate(words, phrase, cursor);
        if (i < 0) problems.push(`${lesson.id}/${slide.id} beat ${bi}: step not spoken: "${phrase}"`);
        return i < 0 ? null : Math.max(0, words[i].s - at);
      });
      beats.push({ ...beat, at, steps });
    }
    out.slides.push({ id: slide.id, title: slide.title, duration: offset, audio: list, beats, words: words.map(({ w, s, e }) => ({ w, s, e })) });
  }
  fs.writeFileSync(path.join(videoRoot, "public/data", `${lesson.id}.json`), JSON.stringify(out));
  console.log(`${lesson.id}: ${out.slides.length} slides, ${out.slides.reduce((n, s) => n + s.beats.length, 0)} beats, ${out.slides.reduce((t, s) => t + s.duration, 0).toFixed(1)} s`);
}
if (problems.length) {
  console.error(problems.join("\n"));
  process.exitCode = 1;
}
