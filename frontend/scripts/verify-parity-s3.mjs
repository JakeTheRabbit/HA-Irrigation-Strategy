/** S3 Zone (mockup 04) and P3 phone zone (mockup 26), against frontend/dist: run after `vite build`.
 * Opens Room A's zone 2 (the demo's F2 zone 2, day 38 of 63) at #/zone/2.
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - the header: "Room A / Zone 2", the phase chip, the mode chip and "… plants · … sensors" (with
 *   "Day 38 of 63" on 3.18; 3.17 has the stage arc's day, where there is one);
 * - Compare with: Off removes the compared line; Yesterday adds `[data-series="yesterday"]`;
 *   "Last run, day 38" (3.18, the grow plan's day) draws `[data-series="last-run"]`; Typical draws
 *   the typical day alone;
 * - the pore EC chart draws today's line against its target;
 * - the AI suggestion sits on the page: Apply keeps the AI's change (overlay_keep) and toasts
 *   "AI change kept: … is yours now." (no value written, so no "Written and read back") with Undo;
 *   Undo writes the grower's value back and toasts "… is back to …. Written and read back HH:MM.";
 *   the suggestion is gone after Apply;
 * - Why / next action is there;
 * - the shot log has at least one row "HH:MM P2 33 mL · 61 s 58.0 → 60.8%" (3.18: the Journal,
 *   with run time; 3.17: the controller's shot table, without), and on every row VWC after the
 *   shot is at least VWC before it;
 * - on a phone, a swipe across the charts moves to the pore EC chart and its dot (24 px targets).
 * Also writes full-page light and dark screenshots of each run beside the harness's own. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const out = (name) =>
  new URL(`../../output/playwright/parity/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const HHMM = String.raw`\d{1,2}:\d{2}(?: [ap]m)?`;

await runParity({
  id: "s3",
  route: "/zone/2",
  mockup: "04-S3-Zone.png",
  phoneMockup: "26-P3-Zone.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const v318 = backend === "3.18";
    const phone = width <= 720;
    await page.getByRole("heading", { level: 1, name: "Zone 2", exact: true }).waitFor();

    // Header.
    const title = page.locator(".zone-page-title");
    assert.equal(await title.locator(".zone-room").innerText(), "Room A", `${label}: room crumb`);
    assert.equal(await title.locator(".pill[data-phase]").count(), 1, `${label}: phase chip`);
    assert.equal(await title.locator(".today-mode").count(), 1, `${label}: mode chip`);
    assert.match(
      await page.locator("[data-zone-facts]").innerText(),
      v318 ? /^Day 38 of 63 · \d+ plants · \d+ sensors?$/ : /^(Day \d+ of \d+ · )?\d+ plants · \d+ sensors?$/,
      `${label}: facts`,
    );
    region("header");

    // Full-page shots as the page opens.
    const charts = page.locator(".zone-day-charts");
    await charts.locator(".grow-svg").waitFor();
    for (const scheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.screenshot({ path: out(`s3-full-${width}-${backend}-${scheme}.png`), fullPage: true, animations: "disabled" });
    }
    await page.emulateMedia({ colorScheme: "light" });

    // Compare with.
    const compare = page.getByRole("group", { name: "Compare with" });
    const button = (name) => compare.getByRole("button", { name, exact: true });
    const series = (name) => charts.locator(`[data-series="${name}"]`);
    const layer = (name) => charts.locator(`[data-layer="${name}"]`);
    await button("Off").click();
    assert.equal(await layer("yesterday").count(), 0, `${label}: off`);
    await button("Yesterday").click();
    await series("yesterday").waitFor({ state: "attached" });
    assert.equal(await button("Yesterday").getAttribute("aria-pressed"), "true");
    const lastRun = compare.getByRole("button", { name: /^Last run, day \d+$/ });
    if (v318) {
      await lastRun.waitFor();
      assert.equal(await lastRun.innerText(), "Last run, day 38", `${label}: last run day`);
      await lastRun.click();
      await series("last-run").waitFor({ state: "attached" });
      assert.equal(await series("yesterday").count(), 0, `${label}: one compared line`);
    }
    await button("Typical").click();
    await layer("typical").waitFor({ state: "attached" });
    assert.equal(await layer("yesterday").count(), 0, `${label}: typical alone`);
    await button("Yesterday").click();
    await series("yesterday").waitFor({ state: "attached" });
    assert.equal(await layer("typical").count(), 0, `${label}: typical gone`);
    region("vwc chart compare");

    // Pore EC chart.
    const ec = page.locator("[data-zone-ec-chart]");
    await ec.locator('[data-series="pore-ec"]').waitFor({ state: "attached" });
    assert.match(await ec.locator(".panel-heading").innerText(), /Today · Pore EC\s+target [\d.]+–[\d.]+/, `${label}: ec heading`);
    region("pore ec chart");

    // On a phone, the charts swipe: VWC first, then pore EC.
    if (phone) {
      const slides = charts.locator(".zone-day-slides");
      const dots = charts.getByRole("group", { name: "Charts" }).getByRole("button");
      assert.equal(await dots.nth(0).getAttribute("aria-current"), "true", `${label}: first dot`);
      const dot = await dots.nth(1).boundingBox();
      assert.ok(dot.width >= 24 && dot.height >= 24, `${label}: dot target ${dot.width}x${dot.height}`);
      assert.match(await charts.locator(".zone-day-swipe").innerText(), /^Swipe: VWC · Pore EC$/);
      const box = await slides.boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + 80);
      await page.mouse.wheel(box.width, 0);
      await page.waitForFunction(
        () => document.querySelector(".zone-day-dots button:nth-child(2)")?.getAttribute("aria-current") === "true",
      );
      // The snap settles with the pore EC chart where the VWC chart was.
      await page.waitForFunction(() => {
        const slides = document.querySelector(".zone-day-slides").getBoundingClientRect();
        const ec = document.querySelector("[data-zone-ec-chart]").getBoundingClientRect();
        return Math.abs(ec.x - slides.x) < 2;
      });
      region("phone swipe");
    }

    // Why / next action.
    await page.locator("[data-zone-why]").getByRole("heading", { name: "Why / next action" }).waitFor();
    region("why next");

    // Shot log.
    const log = page.locator("[data-zone-shot-log]");
    await log.locator("[data-shot-row]").first().waitFor();
    const rows = await log.locator("[data-shot-row]").allInnerTexts();
    assert.ok(rows.length >= 1, `${label}: shot rows`);
    const shape = new RegExp(
      `^${HHMM}\\s+P[0-3]\\s+\\d+ mL${v318 ? " · \\d+ s" : ""}\\s+(\\d+\\.\\d) → (\\d+\\.\\d)%$`,
    );
    for (const row of rows) {
      const match = row.trim().match(shape);
      assert.ok(match, `${label}: shot row "${row}"`);
      // The water landed: VWC five minutes after the shot is at least what it was before.
      assert.ok(Number(match[2]) >= Number(match[1]), `${label}: after < before in "${row}"`);
    }
    assert.equal(await log.getByRole("button", { name: "History" }).count(), 1, `${label}: history link`);
    region("shot log");

    // The AI suggestion: Apply keeps it, toasts with Undo; Undo writes yours back.
    const suggestion = page.locator("[data-zone-suggestion]");
    assert.match(await suggestion.innerText(), /AI assistant suggests: Substrate EC target, P2 \(vegetative\) 3 mS\/cm instead of your 3\.4 mS\/cm/, `${label}: suggestion`);
    await suggestion.getByRole("button", { name: "Apply", exact: true }).click();
    const toast = page.locator("[data-sonner-toast]").filter({ hasText: "AI change kept" });
    await toast.waitFor();
    const kept = await toast.innerText();
    assert.match(kept, /AI change kept: Substrate EC target, P2 \(vegetative\) 3 mS\/cm is yours now\./, `${label}: apply toast`);
    assert.doesNotMatch(kept, /Written and read back/, `${label}: keep writes no value`);
    await suggestion.waitFor({ state: "detached" });
    await toast.getByRole("button", { name: "Undo" }).click();
    const undone = page.locator("[data-sonner-toast]").filter({ hasText: "is back to 3.4 mS/cm" });
    await undone.waitFor();
    assert.match(await undone.innerText(), new RegExp(`Written and read back ${HHMM}\\.`), `${label}: undo read back`);
    region("ai suggestion");
  },
});
console.log("PASS: S3 zone (header, compare incl. typical, pore EC chart, AI suggestion apply and undo, shot log after >= before, phone swipe)");
