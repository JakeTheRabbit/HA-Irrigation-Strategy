/** Shared browser harness for the parity page tasks. `runParity` serves frontend/dist, opens one
 * route in the demo at desktop and phone width on both backends, runs the page's own check, and
 * writes a screenshot beside its mockup under output/playwright/parity/. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";

const VIEWPORTS = [
  { width: 1440, height: 1000 },
  { width: 390, height: 844 },
];
const BACKENDS = ["3.18", "3.17"];
const outDir = new URL("../../output/playwright/parity/", import.meta.url);
const mockupDir = new URL("../../docs/superpowers/mockups/", import.meta.url);
const toPath = (url) => url.pathname.replace(/^\/([A-Za-z]:)/, "$1");

async function launch() {
  const attempts = [{}, { channel: "chrome" }, { channel: "msedge" }];
  let last;
  for (const extra of attempts) {
    try {
      return await chromium.launch({ headless: true, ...extra });
    } catch (e) {
      last = e;
    }
  }
  throw last;
}

export async function runParity({ id, route, mockup, phoneMockup, check }) {
  const html = await readFile(new URL("../dist/index.html", import.meta.url));
  await mkdir(outDir, { recursive: true });
  const server = createServer((req, res) => {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(html);
  });
  // PORT: a fixed port for a run beside other checks; an ephemeral one without.
  await new Promise((resolve) => server.listen(Number(process.env.PORT) || 0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await launch();
  const errors = [];
  const forbidden = [];
  const shots = [];
  const regions = new Set();
  try {
    for (const { width, height } of VIEWPORTS) {
      for (const backend of BACKENDS) {
        const label = `${width}px backend ${backend}`;
        const context = await browser.newContext({
          viewport: { width, height },
          deviceScaleFactor: 2,
        });
        const page = await context.newPage();
        page.on("pageerror", (e) => errors.push(`${label}: ${e.message}`));
        await page.route("**/*", (r) => {
          const url = new URL(r.request().url());
          if (url.origin !== origin || url.pathname.startsWith("/api/")) {
            forbidden.push(`${label}: ${r.request().method()} ${url.href}`);
            return r.abort();
          }
          return r.continue();
        });
        const query = backend === "3.17" ? "?demo=1&backend=3.17" : "?demo=1";
        await page.goto(`${origin}/dashboard.html${query}#${route}`);
        await check(page, { width, backend, region: (name) => regions.add(name) });
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - innerWidth,
        );
        assert.ok(overflow <= 1, `${label}: page overflows horizontally by ${overflow}px`);
        const audit = await new AxeBuilder({ page }).include("main").analyze();
        assert.deepEqual(
          audit.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })),
          [],
          `${label}: axe violations in main`,
        );
        const file = `${id}-${width}-${backend}.png`;
        await page.screenshot({ path: toPath(new URL(file, outDir)), animations: "disabled" });
        shots.push({ width, backend, file, w: width * 2, h: await shotHeight(page) });
        await context.close();
      }
    }
  } finally {
    await browser.close();
    server.close();
  }
  const phone = phoneMockup ?? mockup;
  await writeFile(
    new URL(`${id}-compare.json`, outDir),
    JSON.stringify({ id, mockup, shots, regions: [...regions] }, null, 2) + "\n",
  );
  await writeFile(new URL(`${id}-compare.html`, outDir), compareHtml(id, mockup, phone, shots));
  assert.deepEqual(errors, [], "page errors");
  assert.deepEqual(forbidden, [], "off-origin or /api/ requests");
}

const shotHeight = (page) => page.evaluate(() => innerHeight * 2);

function compareHtml(id, mockup, phoneMockup, shots) {
  const rel = "../../../docs/superpowers/mockups/";
  const rows = shots
    .map((s) => {
      const m = s.width <= 720 ? phoneMockup : mockup;
      return `<section><h2>${s.width}px, backend ${s.backend}</h2>
<div class="pair"><figure><figcaption>Built</figcaption><img src="${s.file}" alt="Built page at ${s.width}px"></figure>
<figure><figcaption>Mockup ${m}</figcaption><img src="${rel}${m}" alt="Mockup ${m}"></figure></div></section>`;
    })
    .join("\n");
  return `<!doctype html><meta charset="utf-8"><title>${id} compare</title>
<style>body{font:14px system-ui;margin:16px}.pair{display:flex;gap:16px;align-items:flex-start}
figure{margin:0;flex:1;min-width:0}img{max-width:100%;border:1px solid #888}</style>
<h1>${id}</h1>
${rows}
`;
}
