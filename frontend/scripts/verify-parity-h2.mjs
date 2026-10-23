/** H2 History › Water & flow (mockup 10), against frontend/dist: run after `vite build`. Opens Room A
 * (the demo's F2) at #/history/water. `PORT` (optional) fixes the harness's port.
 *
 * The clock is pinned to today 16:00 local. Room A's main-line meter counts all three zones; zone 2's
 * line blocks from its 14:14 shot (0.53 of 1.21 L, twice), so its last three shots average 62%;
 * zones 1 and 3 run at 98%. Yesterday at 02:14 the meter counted 0.6 L with every valve shut (CS-319,
 * over the controller's 0.5 L bound). The demo's main-line meter is Room A's only: no other room reads it.
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - 3.18: the header "Water & flow" and the meter line; "Did the water reach the plants?";
 *   one card per zone, zone 2 "Blocked line?" and the others "On target";
 * - zone 2's gauge aria-label says 62%; the blocked card sits inside zone 2, and only there,
 *   naming the 14:14 shot;
 * - a short tap on the test-shot button sends nothing; a 1.6 s hold sends test_shot, the demo
 *   records the press (the zone's test-shot button state: `data-recorded` on the receipt) and the
 *   receipt says when it was asked for;
 * - the intro says shots run one zone at a time (the demo pump's max_concurrent_zones is 1);
 * - Leak check: "Clear today", "0.00 L in … watched", the lanes' screen-reader labels count their
 *   spans, one day of the last 7 marked (yesterday, 02:14), the other six "no alert", not clear;
 * - Water per plant: a row per zone, zone 2 under the median, said once;
 * - 3.17: "Needs integration 3.18" for the metered flow check, and the estimate chart
 *   (Litres by zone, by grow week) still there.
 * Also writes full-page light and dark screenshots of each run beside the harness's own. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const out = (name) =>
  new URL(`../../output/playwright/parity/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const HHMM = String.raw`\d{1,2}:\d{2}(?: [ap]m)?`;

await runParity({
  id: "h2",
  route: "/history/water",
  mockup: "10-H2-WaterFlow.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const v318 = backend === "3.18";
    const pinned = new Date();
    pinned.setHours(16, 0, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    await page.getByRole("heading", { level: 1, name: "Water & flow", exact: true }).waitFor();

    if (!v318) {
      await page.locator('[data-needs-integration="Metered flow check"]').waitFor();
      assert.equal(await page.getByRole("heading", { name: "Needs integration 3.18" }).count(), 1, `${label}: one note`);
      assert.equal(await page.locator("[data-flow-zone]").count(), 0, `${label}: no flow cards on 3.17`);
      const panel = page.locator(".wu-panel");
      await panel.getByRole("heading", { name: "Litres by zone", exact: true }).waitFor();
      await panel.getByRole("img", { name: /^Litres per grow week for Zone 1, Zone 2, Zone 3/ }).waitFor();
      region("needs integration note");
      region("estimate chart");
      for (const scheme of ["light", "dark"]) {
        await page.emulateMedia({ colorScheme: scheme });
        await page.screenshot({ path: out(`h2-full-${width}-${backend}-${scheme}.png`), fullPage: true, animations: "disabled" });
      }
      await page.emulateMedia({ colorScheme: "light" });
      return;
    }

    // Header.
    assert.match(await page.locator("[data-meter-line]").innerText(), new RegExp(`^Room A main-line meter · last changed ${HHMM}$`), `${label}: meter line`);
    await page.getByRole("heading", { name: "Did the water reach the plants?", exact: true }).waitFor();
    assert.match(await page.locator(".wf-intro p").innerText(), /Shots run one zone at a time, so every litre is counted against its own zone\.$/, `${label}: one zone at a time`);
    region("header");

    // Zone cards.
    const zone = (n) => page.locator(`[data-flow-zone="${n}"]`);
    await zone(2).locator("[data-flow-chip]").waitFor();
    assert.equal(await page.locator("[data-flow-zone]").count(), 3, `${label}: one card per zone`);
    for (const [n, chip] of [[1, "On target"], [2, "Blocked line?"], [3, "On target"]])
      assert.equal((await zone(n).locator("[data-flow-chip]").innerText()).trim(), chip, `${label}: zone ${n} chip`);
    const gauge = zone(2).locator("svg.arc-gauge");
    assert.match(await gauge.getAttribute("aria-label"), /62%/, `${label}: zone 2 gauge`);
    assert.match(await zone(1).locator("svg.arc-gauge").getAttribute("aria-label"), /98%/, `${label}: zone 1 gauge`);
    assert.match(await zone(2).innerText(), /Today \d+% · [\d.]+ of [\d.]+ L/, `${label}: zone 2 today`);
    assert.ok((await zone(2).locator(".wf-bar-metered[data-short]").count()) >= 2, `${label}: zone 2 short bars`);
    region("zone cards");

    // The blocked card: in zone 2, only there.
    assert.equal(await page.locator("[data-blocked-card]").count(), 1, `${label}: one blocked card`);
    const blocked = zone(2).locator("[data-blocked-card]");
    assert.match(await blocked.innerText(), new RegExp(`Metered water dropped from the ${HHMM} shot on\\. Check the Zone 2 drippers and line filter\\.`), `${label}: blocked words`);
    assert.match(await blocked.innerText(), /14:14|2:14 pm/, `${label}: from the 14:14 shot`);
    assert.equal(await blocked.getByRole("link", { name: "Open catch test" }).getAttribute("href"), "#/equipment/setup");
    region("blocked card");

    // Test shot: a short tap does nothing, a 1.6 s hold asks for it.
    const hold = blocked.locator(".hold-button");
    // The button's first line; its screen-reader words follow.
    assert.match((await hold.innerText()).split("\n")[0], /^Run \d+ s test shot on Zone 2$/, `${label}: test shot label`);
    await hold.scrollIntoViewIfNeeded();
    const box = await hold.boundingBox();
    const press = async (ms) => {
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.waitForTimeout(ms);
      await page.mouse.up();
    };
    await press(300);
    await page.waitForTimeout(2000);
    assert.equal(await page.locator("[data-test-shot-receipt]").count(), 0, `${label}: a tap sends nothing`);
    await press(1600);
    const receipt = page.locator("[data-test-shot-receipt]");
    await receipt.waitFor();
    assert.match(await receipt.innerText(), new RegExp(`^Test shot asked for at ${HHMM}\\.`), `${label}: receipt`);
    assert.equal(await receipt.getAttribute("data-recorded"), "", `${label}: the demo recorded the test_shot press`);
    region("test shot");

    // Leak check.
    const leak = page.locator("[data-leak-check]");
    await leak.locator("[data-leak-chip]").waitFor();
    assert.equal((await leak.locator("[data-leak-chip]").innerText()).trim(), "Clear today", `${label}: leak chip`);
    assert.match(await leak.locator("[data-shut-flow]").innerText(), /^0\.00 L in \d+ h \d{2} min watched$/, `${label}: shut flow`);
    assert.equal(await leak.locator("[data-shut-flow]").getAttribute("data-tone"), "ok", `${label}: shut flow in the clear tone only when clear`);
    assert.ok((await leak.locator('[data-lane="valve"] span').count()) > 5, `${label}: valve lane`);
    assert.ok((await leak.locator('[data-lane="meter"] span').count()) > 5, `${label}: meter lane`);
    const span = new RegExp(`^\\d+ times, ${HHMM} to ${HHMM}$`);
    assert.match((await leak.getByRole("img", { name: /^Valve open: / }).getAttribute("aria-label")).replace(/^Valve open: /, ""), span, `${label}: valve lane label`);
    assert.match((await leak.getByRole("img", { name: /^Meter flow: / }).getAttribute("aria-label")).replace(/^Meter flow: /, ""), span, `${label}: meter lane label`);
    assert.equal(await leak.locator("li[data-hit]").count(), 1, `${label}: one day with water through shut valves`);
    assert.equal(await leak.locator("li:not([data-hit]) .sr-only", { hasText: /: no alert$/ }).count(), 6, `${label}: other days "no alert"`);
    assert.match(await leak.locator("[data-leak-last]").innerText(), new RegExp(`^\\w{3} \\d{1,2}, ${HHMM} Room A: water flows with no zone on \\(CS-319\\)$`), `${label}: last incident`);
    region("leak check");

    // Water per plant.
    const plant = page.locator("[data-water-per-plant]");
    assert.equal(await plant.locator("[data-plant-zone]").count(), 3, `${label}: a row per zone`);
    assert.match(await plant.locator(".wf-plant-note").innerText(), /^Zone 2 is [\d.]+ L a plant under the median\. It asked for [\d.]+ L, so the gap is most likely the blocked line, not the plan\.$/, `${label}: plant note`);
    assert.equal(await page.getByText(/a plant under the median/).count(), 1, `${label}: said once`);
    region("water per plant");

    // The controller's own counters stay below.
    await page.locator(".wu-panel").getByRole("heading", { name: "Litres by zone", exact: true }).waitFor();

    for (const scheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.screenshot({ path: out(`h2-full-${width}-${backend}-${scheme}.png`), fullPage: true, animations: "disabled" });
    }
    await page.emulateMedia({ colorScheme: "light" });
    await page.evaluate(() => window.scrollTo(0, 0));
  },
});
console.log("PASS: H2 water & flow (meter line, zone cards + 62% gauge, blocked card in zone 2, tap vs 1.6 s hold → test_shot, leak check + 7 days, water per plant, 3.17 note + estimate chart; clock pinned 16:00)");
