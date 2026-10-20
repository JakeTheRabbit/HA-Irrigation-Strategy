// Render lesson videos with Remotion. Usage:
//   node scripts/render.mjs [A1 A2 ...] [--out <dir>] [--concurrency N] [--no-intro]
// Writes <out>/<ID>.mp4 plus <ID>.vtt captions and <ID>.chapters.json (slide starts).
import fs from "node:fs";
import path from "node:path";
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "..");
const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(name);
  return i >= 0 ? args.splice(i, 2)[1] : fallback;
};
const flag = (name) => {
  const i = args.indexOf(name);
  return i >= 0 ? (args.splice(i, 1), true) : false;
};
const out = path.resolve(opt("--out", path.join(root, "out/lessons")));
const concurrency = Number(opt("--concurrency", 8));
const noIntro = flag("--no-intro");
const captionsOnly = flag("--captions-only"); // rewrite .vtt/.chapters.json from data without rendering
const ids = args.length ? args : fs.readdirSync(path.join(root, "public/data")).map((f) => f.replace(/\.json$/, ""));
const FPS = 30;
const INTRO = noIntro ? 0 : 4;
fs.mkdirSync(out, { recursive: true });

const stamp = (t) => {
  const ms = Math.round(t * 1000);
  return `${String(Math.floor(ms / 3600000)).padStart(2, "0")}:${String(Math.floor(ms / 60000) % 60).padStart(2, "0")}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;
};

// Caption cues: group spoken words into lines of up to ~42 characters, breaking at pauses.
function captions(data) {
  const cues = [];
  let offset = INTRO;
  for (const slide of data.slides) {
    let line = [];
    const flush = () => {
      if (!line.length) return;
      cues.push([offset + line[0].s, offset + line[line.length - 1].e, line.map((w) => w.w).join(" ")]);
      line = [];
    };
    for (const [i, w] of slide.words.entries()) {
      const text = line.map((x) => x.w).join(" ");
      if (line.length && (text.length + w.w.length > 42 || w.s - line[line.length - 1].e > 0.6)) flush();
      line.push(w);
      if (/[.?!]$/.test(w.w) && i + 1 < slide.words.length) flush();
    }
    flush();
    offset += Math.ceil(slide.duration * FPS) / FPS;
  }
  return "WEBVTT\n\n" + cues.map(([a, b, t]) => `${stamp(a)} --> ${stamp(Math.max(b, a + 0.4))}\n${t}`).join("\n\n") + "\n";
}

const serveUrl = captionsOnly ? null : (console.log("Bundling…"), await bundle({ entryPoint: path.join(root, "src/index.ts") }));
for (const id of ids) {
  const data = JSON.parse(fs.readFileSync(path.join(root, "public/data", `${id}.json`), "utf8"));
  const intro = !noIntro && fs.existsSync(path.join(root, "public/clips/openers", `${id}.mp4`)) ? `clips/openers/${id}.mp4` : undefined;
  const inputProps = { id, intro };
  const started = Date.now();
  if (!captionsOnly) {
    const composition = await selectComposition({ serveUrl, id: `lesson-${id}`, inputProps, port: 3471 });
    await renderMedia({
      composition,
      serveUrl,
      codec: "h264",
      outputLocation: path.join(out, `${id}.mp4`),
      inputProps,
      concurrency,
      port: 3471,
      // Flat graphics compress very well at constant quality; GPU encoding needs a fixed bitrate.
      crf: 22,
      x264Preset: "medium",
      audioBitrate: "192k",
      onProgress: ({ progress }) => process.stdout.write(`\r${id} ${(progress * 100).toFixed(0)}%   `),
    });
  }
  fs.writeFileSync(path.join(out, `${id}.vtt`), captions(data));
  let t = intro ? INTRO : 0;
  const chapters = data.slides.map((s) => {
    const c = { id: s.id, title: s.title, start: Math.round(t * 1000) / 1000 };
    t += Math.ceil(s.duration * FPS) / FPS;
    return c;
  });
  fs.writeFileSync(path.join(out, `${id}.chapters.json`), JSON.stringify({ duration: Math.round(t * 1000) / 1000, chapters }, null, 2));
  console.log(`\r${id}: ${t.toFixed(1)} s rendered in ${((Date.now() - started) / 1000).toFixed(0)} s`);
}
