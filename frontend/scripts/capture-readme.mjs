/** The README's tour screenshots (img/jev-*.png), captured from the compiled dashboard's isolated
 * demo at a fixed clock, so a change to the demo or its words can be recaptured with one command:
 * build the frontend, then run `node frontend/scripts/capture-readme.mjs`. Nothing leaves the page. */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";

const html = await readFile(new URL("../../www/dashboard.html", import.meta.url));
const img = (name) =>
  new URL(`../../img/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const server = createServer((req, res) => {
  res.writeHead(200, { "Content-Type": "text/html" });
  res.end(html);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({
  headless: true,
  ...(process.platform === "win32" ? { channel: "chrome" } : {}),
});

/** A page on the demo at 3:50 PM, mid-day in Room A, in the light theme. */
async function open(viewport, deviceScaleFactor) {
  const page = await browser.newPage({ viewport, deviceScaleFactor, colorScheme: "light" });
  await page.clock.setFixedTime(new Date(2026, 8, 28, 15, 50, 0));
  await page.route("**/*", (route) =>
    route.request().url().startsWith(origin) ? route.continue() : route.abort(),
  );
  return page;
}
const go = async (page, route) => {
  await page.goto(`${origin}/dashboard.html?demo=1#/${route}`, { waitUntil: "networkidle" });
  await page.locator("main").waitFor();
};

try {
  const page = await open({ width: 1440, height: 680 }, 1.5);
  await go(page, "today");
  await page.locator("[data-jev-today]").waitFor();
  await page.screenshot({ path: img("jev-today.png") });

  await go(page, "zone/1");
  const day = page.locator("[data-day-timeline]");
  await day.locator('[data-layer="yesterday"]').waitFor();
  await day.screenshot({ path: img("jev-zone-day.png") });
  await page.locator("[data-zone-jev]").screenshot({ path: img("jev-zone-panel.png") });

  await go(page, "plan/targets");
  await page.locator(".targets-panel").screenshot({ path: img("jev-plan-targets.png") });
  await go(page, "plan/schedule");
  await page.locator(".grow-stages").screenshot({ path: img("jev-stages.png") });

  await go(page, "history/timeline");
  const types = page.getByRole("group", { name: "Record type" });
  await types.getByRole("button", { name: "AI assistant", exact: true }).click();
  await page.locator(".timeline-panel").screenshot({ path: img("jev-history.png") });
  await types.getByRole("button", { name: "Setpoints", exact: true }).click();
  await page.locator(".timeline-panel").screenshot({ path: img("jev-history-setpoints.png") });

  await go(page, "equipment/probes");
  await page.locator(".probes-status").screenshot({ path: img("jev-equipment.png") });

  const phone = await open({ width: 390, height: 844 }, 2);
  await go(phone, "today");
  await phone.screenshot({ path: img("jev-today-phone.png") });
  console.log("Captured the README's 9 demo screenshots into img/.");
} finally {
  await browser.close();
  server.close();
}
