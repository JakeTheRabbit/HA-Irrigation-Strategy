// Render one still per beat (70% into it) for a lesson and tile them into contact sheets.
// Usage: node scripts/stills.mjs <LessonID> [port]   → out/stills/<ID>/beat-*.png, sheet-*.png
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "..");
const [id, portArg] = process.argv.slice(2);
const port = Number(portArg || 3490);
const FPS = 30;
const data = JSON.parse(fs.readFileSync(path.join(root, "public/data", `${id}.json`), "utf8"));
const dir = path.join(root, "out/stills", id);
fs.rmSync(dir, { recursive: true, force: true });
fs.mkdirSync(dir, { recursive: true });

const frames = [];
let base = 0;
for (const slide of data.slides) {
  const total = Math.ceil(slide.duration * FPS);
  const beats = slide.beats.length ? slide.beats : [{ at: 0, type: "(none)" }];
  beats.forEach((b, i) => {
    const from = Math.round(b.at * FPS);
    const to = i + 1 < beats.length ? Math.round(beats[i + 1].at * FPS) : total;
    frames.push({ frame: base + Math.round(from + (to - from) * 0.7), label: `${slide.id}-${i + 1}-${b.type}` });
  });
  base += total;
}

const serveUrl = await bundle({ entryPoint: path.join(root, "src/index.ts") });
const composition = await selectComposition({ serveUrl, id: `lesson-${id}`, inputProps: { id }, port });
for (const [n, f] of frames.entries()) {
  await renderStill({ composition, serveUrl, frame: f.frame, inputProps: { id }, port, output: path.join(dir, `beat-${String(n).padStart(3, "0")}-${f.label}.png`), scale: 0.5 });
  process.stdout.write(`\r${n + 1}/${frames.length}`);
}
// 3 × 3 contact sheets with labels burned in by ffmpeg.
const files = fs.readdirSync(dir).filter((f) => f.startsWith("beat-")).sort();
for (let s = 0; s * 9 < files.length; s++) {
  const list = path.join(dir, `list-${s}.txt`);
  const chunk = files.slice(s * 9, s * 9 + 9);
  fs.writeFileSync(list, chunk.map((f) => `file '${path.join(dir, f).replace(/\\/g, "/")}'`).join("\n"));
  execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", list, "-vf", "tile=3x3:padding=8:color=white", "-frames:v", "1", path.join(dir, `sheet-${s + 1}.png`)]);
  fs.unlinkSync(list);
}
console.log(`\n${frames.length} beats → ${dir}`);
