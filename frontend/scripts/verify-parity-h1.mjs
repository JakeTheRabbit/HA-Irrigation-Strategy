/** H1 History › Explorer (mockup 09), against frontend/dist: run after `vite build`. Opens Room A (the
 * demo's F2) at #/history/explorer.
 *
 * The clock is pinned to today 15:00 local: Room A's lights came on at 10:00, so today has its
 * phase changes, its shots, the 06:10 tank refill and zone 2's pore EC over the band since 14:20.
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - the header "Explorer", the ranges Today · 7 d · This run · Custom (Today pressed, "…, 00:00 to
 *   now"), "Export CSV · 8 series";
 * - the PHASE lane has its segments and the SHOTS lane its shots: from the Journal on 3.18, from the
 *   phase sensor's history and the shot table on 3.17;
 * - notes in place on 3.18 ("Refilled 06:10 · …% to 74%", "Zone 2 over the band since …", once,
 *   on the pore EC chart, its 14:30 alert not said again); none on
 *   3.17, where "Needs integration 3.18" says so;
 * - the Zone 3 VWC chip removes its line and the export counts 7 series; ticking it puts both back;
 * - moving the mouse over a chart shows the time pill "HH:MM · P2" and the legend reads that time;
 * - Compare with last run draws the last run's lines (dashed) beside today's;
 * - 7 d reads a week; back to Today;
 * - #/history/timeline redirects here.
 * Also writes full-page light and dark screenshots of each run beside the harness's own. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const out = (name) =>
  new URL(`../../output/playwright/parity/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const HHMM = String.raw`\d{1,2}:\d{2}(?: [ap]m)?`;

await runParity({
  id: "h1",
  route: "/history/explorer",
  mockup: "09-H1-Explorer.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const v318 = backend === "3.18";
    const pinned = new Date();
    pinned.setHours(15, 0, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    await page.getByRole("heading", { level: 1, name: "Explorer", exact: true }).waitFor();
    const explorer = page.locator("[data-room-explorer]");

    // Header and ranges.
    const ranges = page.getByRole("group", { name: "Range" });
    assert.deepEqual(await ranges.getByRole("button").allInnerTexts(), ["Today", "7 d", "This run", "Custom"], `${label}: ranges`);
    assert.equal(await ranges.getByRole("button", { name: "Today" }).getAttribute("aria-pressed"), "true");
    assert.match(await page.locator("[data-range-text]").innerText(), /^\w{3} \d{1,2} \w{3,4}, 00:00 to now$/, `${label}: range text`);
    const exportButton = page.locator("[data-export-csv]");
    assert.equal((await exportButton.innerText()).trim(), "Export CSV · 8 series", `${label}: export`);
    region("header");

    // Lanes.
    await page.waitForFunction(() => Number(document.querySelector("[data-room-explorer]")?.dataset.explorerLoads) > 0, null, { timeout: 20_000 });
    const board = page.locator(".explorer-board");
    assert.equal(await board.getAttribute("data-lanes-source"), v318 ? "journal" : "entities", `${label}: lane source`);
    await page.locator("[data-phase-lane] [data-phase]").nth(2).waitFor();
    const phases = await page.locator("[data-phase-lane] [data-phase]").evaluateAll((all) => all.map((el) => el.dataset.phase));
    assert.ok(phases.includes("P2") && phases.includes("P1"), `${label}: phases ${phases}`);
    await page.locator("[data-shot-lane] .st-block").first().waitFor({ state: "attached" });
    assert.ok((await page.locator("[data-shot-lane] .st-block").count()) >= 5, `${label}: shots`);
    region("phase lane");
    region("shot lane");

    // Notes in place.
    const notes = page.locator("[data-chart-note]");
    if (v318) {
      await notes.first().waitFor({ state: "attached" });
      const texts = await notes.allInnerTexts();
      assert.ok(texts.some((t) => /^Refilled 06:10 · \d+% to 74%$/.test(t.trim())), `${label}: refill note ${texts}`);
      assert.ok(texts.some((t) => new RegExp(`^Zone 2 over the band since ${HHMM}$`).test(t.trim())), `${label}: band note ${texts}`);
      // Said once, on the pore EC chart (its alert at 14:30 is not said again).
      assert.equal(await page.locator('[data-chart="Pore EC"] [data-chart-note]').filter({ hasText: "Zone 2" }).count(), 1, `${label}: band note on pore EC`);
    } else {
      assert.equal(await notes.count(), 0, `${label}: no notes on 3.17`);
      assert.equal(await page.locator('[data-needs-integration="Notes on the charts"]').count(), 1, `${label}: needs integration`);
    }
    region("notes");

    // Full-page shots as the page opens.
    for (const scheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.screenshot({ path: out(`h1-full-${width}-${backend}-${scheme}.png`), fullPage: true, animations: "disabled" });
    }
    await page.emulateMedia({ colorScheme: "light" });

    // The Zone 3 VWC chip removes its line.
    const zone3 = page.getByRole("button", { name: "Zone 3 VWC", exact: true });
    const line = explorer.locator('[data-series="sensor.crop_steering_vwc_zone_3"]');
    await line.waitFor({ state: "attached" });
    await zone3.click();
    assert.equal(await zone3.getAttribute("aria-pressed"), "false");
    assert.equal(await line.count(), 0, `${label}: zone 3 line removed`);
    assert.match(await exportButton.innerText(), /Export CSV · 7 series/);
    await zone3.click();
    await line.waitFor({ state: "attached" });
    assert.match(await exportButton.innerText(), /Export CSV · \d+ series/);
    region("series chips");

    // The shared crosshair: a time pill under the charts, the legends read that time.
    const plot = page.locator('[data-chart="VWC"] .explorer-plot');
    await plot.scrollIntoViewIfNeeded();
    const box = await plot.boundingBox();
    const before = await page.locator('[data-chart="VWC"] [data-legend] b').first().innerText();
    await page.mouse.move(box.x + box.width * 0.45, box.y + box.height / 2);
    const pill = page.locator("[data-time-pill]");
    await pill.waitFor();
    assert.match((await pill.innerText()).trim(), new RegExp(`^${HHMM}( · P[0-3])?$`), `${label}: pill`);
    assert.equal(await page.locator(".explorer-cross").count(), await page.locator(".explorer-plot > svg").count(), `${label}: one line in every chart`);
    assert.match(await page.locator('[data-chart="VWC"] [data-legend] b').first().innerText(), /^\d+\.\d%$/, `${label}: legend at the crosshair (was ${before})`);
    await page.mouse.move(box.x + box.width / 2, box.y - 400);
    region("crosshair");

    // Compare with the last run.
    const compare = page.locator("[data-compare-last]");
    assert.match(await compare.innerText(), /^Compare with last run\s*\(.+, same day \d+\)$/, `${label}: compare label`);
    await compare.click();
    assert.equal(await compare.getAttribute("aria-checked"), "true");
    await explorer.locator("[data-before]").first().waitFor({ state: "attached", timeout: 20_000 });
    await compare.click();
    region("compare");

    // 7 d, then back to Today.
    await ranges.getByRole("button", { name: "7 d" }).click();
    assert.equal(await ranges.getByRole("button", { name: "7 d" }).getAttribute("aria-pressed"), "true");
    assert.match(new URL(page.url()).hash, /range=7d/);
    await ranges.getByRole("button", { name: "Today" }).click();
    region("ranges");

    // The old Timeline address lands here.
    const url = new URL(page.url());
    url.hash = "#/history/timeline";
    await page.goto(url.href);
    await page.waitForFunction(() => location.hash.startsWith("#/history/explorer"));
    await page.getByRole("heading", { level: 1, name: "Explorer", exact: true }).waitFor();
    await page.waitForFunction(() => Number(document.querySelector("[data-room-explorer]")?.dataset.explorerLoads) > 0, null, { timeout: 20_000 });
    region("timeline redirect");
  },
});
console.log("PASS: H1 explorer (ranges, lanes, notes on 3.18 only, Zone 3 VWC chip, time pill, compare with last run, 7 d, #/history/timeline redirect)");
