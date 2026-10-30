/** Every page in the route table (frontend/src/lib/routes.ts RENDERED_PAGES), against frontend/dist:
 * run after `vite build`. Each page opens in the demo at desktop 1440x900 and phone 390x844, light
 * and dark, on both demo backends (3.18 and 3.17), with the clock pinned to 18 October 2026 15:50.
 *
 * A visit fails on any console error, page error, off-origin or /api/ request, horizontal overflow,
 * or axe violation of serious or critical impact anywhere on the page. Results (one row per visit)
 * go to output/playwright/sweep/results.json. PORT pins the loopback server's port. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";

const routesSource = await readFile(new URL("../src/lib/routes.ts", import.meta.url), "utf8");
const table = routesSource.match(/RENDERED_PAGES = \[([\s\S]*?)\] as const/)[1];
const PAGES = [...table.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
assert.ok(PAGES.length >= 20, `route table parsed: ${PAGES.length} pages`);
const hashOf = (page) => (page === "zone" ? "/zone/1" : `/${page}`);

const SIZES = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "phone", width: 390, height: 844 },
];
const THEMES = ["light", "dark"];
const BACKENDS = ["3.18", "3.17"];
const PINNED = new Date(2026, 9, 18, 15, 50);
const only = process.env.ROUTES ? process.env.ROUTES.split(",") : null;

const html = await readFile(new URL("../dist/index.html", import.meta.url));
const server = createServer((_req, res) => {
  res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  res.end(html);
});
await new Promise((resolve) => server.listen(Number(process.env.PORT) || 0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;

async function launch() {
  let last;
  for (const extra of [{}, { channel: "chrome" }, { channel: "msedge" }]) {
    try {
      return await chromium.launch({ headless: true, ...extra });
    } catch (e) {
      last = e;
    }
  }
  throw last;
}
const browser = await launch();
const results = [];

async function sweep(size, theme, backend) {
  const context = await browser.newContext({
    viewport: { width: size.width, height: size.height },
    colorScheme: theme,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15_000);
  let problems = [];
  page.on("pageerror", (e) => problems.push(`page error: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(`console error: ${m.text()}`);
  });
  await page.route("**/*", (r) => {
    const url = new URL(r.request().url());
    if (url.origin !== origin || url.pathname.startsWith("/api/")) {
      problems.push(`request: ${r.request().method()} ${url.href}`);
      return r.abort();
    }
    return r.continue();
  });
  await page.clock.setFixedTime(PINNED);
  const query = backend === "3.17" ? "?demo=1&backend=3.17" : "?demo=1";
  for (const route of PAGES.filter((p) => !only || only.includes(p))) {
    problems = [];
    try {
      await page.goto(`${origin}/dashboard.html${query}#${hashOf(route)}`);
      await page.locator("main h1").first().waitFor();
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(600);
      const dark = await page.evaluate(() => document.documentElement.classList.contains("dark"));
      if (dark !== (theme === "dark")) problems.push(`theme: dark class is ${dark}`);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      if (overflow > 1) problems.push(`overflow: ${overflow}px`);
      const audit = await new AxeBuilder({ page }).analyze();
      for (const v of audit.violations)
        if (v.impact === "serious" || v.impact === "critical")
          problems.push(
            `axe ${v.impact} ${v.id}: ${v.nodes
              .slice(0, 3)
              .map((n) => n.target.join(" "))
              .join(" | ")}${v.nodes.length > 3 ? ` (+${v.nodes.length - 3})` : ""}`,
          );
    } catch (e) {
      problems.push(`visit: ${e.message.split("\n")[0]}`);
    }
    results.push({ route, size: size.name, theme, backend, pass: !problems.length, problems });
    process.stdout.write(problems.length ? "F" : ".");
  }
  await context.close();
}

try {
  const runs = [];
  for (const size of SIZES)
    for (const theme of THEMES)
      for (const backend of BACKENDS) runs.push(sweep(size, theme, backend));
  await Promise.all(runs);
} finally {
  await browser.close();
  server.close();
}
process.stdout.write("\n");
const outDir = new URL("../../output/playwright/sweep/", import.meta.url);
await mkdir(outDir, { recursive: true });
await writeFile(new URL("results.json", outDir), JSON.stringify(results, null, 2) + "\n");
const failed = results.filter((r) => !r.pass);
for (const f of failed)
  console.log(`FAIL ${f.route} ${f.size} ${f.theme} ${f.backend}\n  ${f.problems.join("\n  ")}`);
assert.equal(failed.length, 0, `${failed.length} of ${results.length} visits failed`);
console.log(
  `PASS: ${results.length} visits (${PAGES.length} pages x 2 sizes x 2 themes x 2 backends) clean`,
);
