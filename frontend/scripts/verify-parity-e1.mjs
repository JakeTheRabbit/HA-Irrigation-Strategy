/** E1 Equipment › Probes & offsets (mockup 13), against frontend/dist: run after `vite build`. Opens
 * #/equipment/probes in the demo on Room A (it plays F2): the room the tree picks.
 *
 * The clock is pinned to today 15:00 local, so the probes' last 24 h and their health read the same
 * every run.
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - the header "Probes & offsets" and its counts "N probes · K in zone values · raw readings always
 *   kept"; the table under the room's name ("k of n probes healthy"), one row per moisture probe, front
 *   and back of each zone;
 * - 3.18: every Offset reads "0.0"; Match handheld on Room A Zone 1 Back → type the probe's
 *   reading + 3 → "+3.0" → "Apply +3.0 offset to Zone 1 Back" (through the phone's review sheet) → a
 *   receipt "Written and read back HH:MM" with "Zone 1 Back offset 0.0 → +3.0 · Room A Zone 1 value a% → b% (integration's figure)" → its Offset reads "+3.0"
 *   → Undo → "Previous values written back HH:MM" and "0.0" again;
 * - "Check placement" in the editor focuses the "Where to put a probe" card;
 * - the substrate curve card says why no curve applies (3.18) or "Needs integration 3.18" (3.17);
 * - 3.17: "Match handheld" says "Needs integration 3.18" once, every Offset reads "—", no Match
 *   handheld button;
 * - the feed calibration region is still on the page (Task 24 moves it). */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const HHMM = String.raw`\d{1,2}:\d{2}(?: [ap]m)?`;
const PROBE = "sensor.demo_z1_back_vwc";

await runParity({
  id: "e1",
  route: "/equipment/probes",
  mockup: "13-E1-Probes.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const v318 = backend === "3.18";
    const phone = width <= 720;
    const pinned = new Date();
    pinned.setHours(15, 0, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    await page.getByRole("heading", { level: 1, name: "Probes & offsets", exact: true }).waitFor();
    const counts = (await page.locator(".page-heading p").innerText()).trim();
    assert.match(counts, /^\d+ probes · \d+ in zone values · raw readings always kept$/, `${label}: counts ${counts}`);
    region("header");

    // Under the room's name, one row per moisture probe.
    assert.equal(await page.locator('tbody[data-probes-room="room:"]').count(), 1, `${label}: Room A`);
    const rows = page.locator(".probes-table tr[data-probe]");
    assert.equal(await rows.count(), 6, `${label}: moisture probe rows`);
    const health = await page.locator(".probes-room-health").allInnerTexts();
    assert.ok(health.every((t) => /^\d+ of \d+ probes? healthy$/.test(t.trim())), `${label}: room health ${health}`);
    await page.locator(".probes-table [data-sensor-trend] .sparkline").first().waitFor({ timeout: 15_000 });
    region("rooms");

    // The feed probes are calibrated on their own page (Task 24): a link to it.
    assert.equal(
      await page.getByRole("link", { name: "Feed pH and EC probes: Calibrate →", exact: true }).getAttribute("href"),
      "#/equipment/feed-calibration",
      `${label}: feed calibration link`,
    );
    region("feed calibration");

    const curve = page.locator("[data-substrate-curve]");
    if (v318)
      assert.match(
        await curve.locator("[data-curve-reason]").first().innerText(),
        /^This probe already converts to moisture\. A curve only applies to raw readings\.$/,
        `${label}: curve reason`,
      );
    else assert.equal(await curve.locator('[data-needs-integration="Probe curves"]').count(), 1, `${label}: curve needs integration`);
    region("substrate curve");

    const offsets = await page.locator("[data-offset]").allInnerTexts();
    if (!v318) {
      assert.ok(offsets.every((t) => t.trim() === "—"), `${label}: offsets ${offsets}`);
      assert.equal(await page.locator("[data-match-handheld]").count(), 0, `${label}: no Match handheld`);
      const missing = page.locator("[data-match-handheld-missing]");
      assert.equal(await missing.count(), 1, `${label}: one note`);
      assert.match(await missing.innerText(), /Match handheld\s*Needs integration 3\.18/, `${label}: note`);
      region("needs integration");
      return;
    }
    assert.ok(offsets.every((t) => t.trim() === "0.0"), `${label}: offsets ${offsets}`);

    // Match handheld on Room A Zone 1 Back.
    const row = page.locator(`tr[data-probe="${PROBE}"]`);
    const raw = Number.parseFloat(await row.locator(".probes-vwc").innerText());
    // Its accessible name holds the visible words (WCAG 2.5.3).
    const match = row.getByRole("button", { name: "Match handheld: Zone 1 Back", exact: true });
    await match.click();
    const editor = page.locator(`[data-offset-editor="${PROBE}"]`);
    // The toggle names the row it opens.
    const controls = await match.getAttribute("aria-controls");
    assert.equal(await page.locator(`[id="${controls}"] [data-offset-editor="${PROBE}"]`).count(), 1, `${label}: aria-controls ${controls}`);
    await editor.getByRole("textbox", { name: "Handheld reading, same spot, %" }).fill((raw + 3).toFixed(1));
    assert.equal((await editor.locator("[data-offset-preview]").innerText()).trim(), "+3.0", `${label}: offset preview`);
    assert.match(await editor.innerText(), /Raw value kept · logged in History › Changes/, `${label}: raw kept`);
    region("match handheld");

    // Check placement focuses the card.
    await editor.locator("[data-check-placement-editor]").click();
    assert.equal(await page.evaluate(() => document.activeElement?.hasAttribute("data-placement-card")), true, `${label}: placement focused`);
    region("placement");

    // Review & apply: inline on desktop, the bottom sheet on a phone.
    if (phone) await editor.getByRole("button", { name: "Review 1 change" }).click();
    const apply = page.getByRole("button", { name: "Apply +3.0 offset to Zone 1 Back", exact: true });
    await apply.click();
    const receipt = editor.locator(".review-apply-receipt");
    await receipt.waitFor();
    const text = await receipt.innerText();
    assert.match(text, new RegExp(`Written and read back ${HHMM}`), `${label}: receipt ${text}`);
    // The offset is what was read back; the zone value is the integration's own figure.
    assert.match(text, /Zone 1 Back offset 0\.0 → \+3\.0 · Room A Zone 1 value \d+\.\d% → \d+\.\d% \(integration's figure\)/, `${label}: receipt line ${text}`);
    await page.waitForFunction((id) => document.querySelector(`[data-offset="${id}"]`)?.textContent?.trim() === "+3.0", PROBE);
    region("receipt");

    await receipt.getByRole("button", { name: "Undo: write back the previous values" }).click();
    await editor.getByText(new RegExp(`^Previous values written back ${HHMM}$`)).waitFor();
    await page.waitForFunction((id) => document.querySelector(`[data-offset="${id}"]`)?.textContent?.trim() === "0.0", PROBE);
    region("undo");
  },
});
console.log("PASS: E1 probes & offsets (room, match handheld, receipt, undo, placement, curve, feed calibration, 3.17)");
