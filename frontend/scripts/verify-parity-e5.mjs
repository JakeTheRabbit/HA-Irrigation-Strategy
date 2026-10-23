/** E5 Stock tanks (mockup 17), against frontend/dist: run after `vite build`. Opens
 * #/equipment/stock in the demo (Room A: Silica 10 L, Part B 20 L at 5.4 L, Part A 20 L, Line
 * cleaner 5 L).
 *
 * The clock is pinned to today 14:10 local, so the demo's refill this morning is in the past and
 * "Written and read back" reads 14:10 at any real hour.
 *
 * Interactions asserted, at 1440 and 390, on both backends:
 * - the heading "Stock tanks · Room A"; four tank cards, each bottle drawn by volume (the cube root
 *   of its capacity over the largest): Part B full size, Line cleaner at ∛(5/20);
 * - Part B reads "5.4 L of 20 L" and its batches left; Part B runs out first (highlighted);
 * - "Log refill to 20 L" on Part B applies at once: "20 L of 20 L" and the toast "Part B refilled to
 *   20 L. Written and read back 14:10."; its Undo puts 5.4 L back ("Part B put back to 5.4 L.");
 * - Set level on Line cleaner to 0.8 L: its card says "Below the low line. Order now.";
 * - Used per week draws a bar chart with a legend of the four tanks;
 * - Refills: 3.18 lists the Journal's refill "Part A … +16.6 L, to 20 L"; 3.17 lists each tank's
 *   last refill to full and says that is all the integration keeps.
 * Only requests to the page's own origin are made (the harness fails any other). */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

await runParity({
  id: "e5",
  route: "/equipment/stock",
  mockup: "17-E5-Stock.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    const main = page.locator("main");
    await main.getByRole("heading", { level: 1, name: "Stock tanks · Room A" }).waitFor();
    const card = (id) => main.locator(`[data-stock-tank="${id}"]`);
    await card("part_b").waitFor();
    assert.equal(await main.locator("[data-stock-tank]").count(), 4, `${label}: four tanks`);

    // Drawn to scale: by volume, the cube root of capacity over the largest.
    const scaleOf = async (id) => {
      const t = await card(id).locator("svg.stock-bottle g").first().getAttribute("transform");
      return Number(/scale\(([\d.]+)\)/.exec(t)[1]);
    };
    assert.equal(await scaleOf("part_b"), 1, `${label}: Part B full size`);
    assert.ok(Math.abs((await scaleOf("cleaner")) - Math.cbrt(5 / 20)) < 1e-9, `${label}: cleaner by volume`);
    assert.ok(Math.abs((await scaleOf("silica")) - Math.cbrt(10 / 20)) < 1e-9, `${label}: silica by volume`);
    region("bottles to scale");

    const level = (id) => card(id).locator("[data-stock-level]").innerText();
    assert.equal(await level("part_b"), "5.4 L of 20 L", `${label}: Part B level`);
    assert.match(await card("part_b").locator("[data-stock-outlook]").innerText(), /^\d+ batch(es)? (· \d+ days? )?left$/);
    assert.equal(await card("part_b").getAttribute("data-stock-next"), "", `${label}: Part B runs out first`);
    region("tank outlook");

    // Log refill: applied at once with Undo back to 5.4 L.
    await card("part_b").getByRole("button", { name: "Log refill to 20 L" }).click();
    const done = page.locator("[data-sonner-toast]").filter({ hasText: "Part B refilled to 20 L. Written and read back 14:10." });
    await done.waitFor();
    assert.equal(await level("part_b"), "20 L of 20 L", `${label}: refilled`);
    await done.getByRole("button", { name: "Undo" }).click();
    await page.locator("[data-sonner-toast]").filter({ hasText: "Part B put back to 5.4 L." }).waitFor();
    assert.equal(await level("part_b"), "5.4 L of 20 L", `${label}: undone`);
    region("refill undo");

    // Below the low line, in place on the tank.
    assert.equal(await card("cleaner").locator("[data-stock-low]").count(), 0);
    await card("cleaner").getByRole("button", { name: "Set level" }).click();
    await card("cleaner").getByLabel("Tank level (L)", { exact: true }).fill("0.8");
    await card("cleaner").getByRole("button", { name: "Save level", exact: true }).click();
    await card("cleaner").locator("[data-stock-low]").waitFor();
    assert.equal(await card("cleaner").locator("[data-stock-low]").innerText(), "Below the low line. Order now.");
    region("below low");

    const weekly = main.locator("[data-stock-weekly]");
    await weekly.getByRole("heading", { name: "Used per week" }).waitFor();
    assert.deepEqual(await weekly.locator(".stock-legend li").allInnerTexts(), ["Silica", "Part B", "Part A", "Line cleaner"]);
    await weekly.locator(".recharts-bar-rectangle").first().waitFor();
    region("used per week");

    const refills = main.locator("[data-stock-refills]");
    await refills.getByRole("heading", { name: "Refills" }).waitFor();
    if (backend === "3.18") {
      const row = refills.locator("[data-stock-refill]").first();
      await row.waitFor();
      assert.match(await row.innerText(), /^Part A\s+\d{1,2} \w{3}\s+\+16\.6 L, to 20 L$/, `${label}: journal refill`);
      assert.equal(await refills.locator("[data-stock-refills-older]").count(), 0);
    } else {
      await refills.locator("[data-stock-refills-older]").waitFor();
      assert.equal(await refills.locator("[data-stock-refill]").count(), 4, `${label}: each tank's last refill`);
    }
    region("refills");
  },
});
console.log("PASS: E5 stock tanks (2 viewports x 2 backends)");
