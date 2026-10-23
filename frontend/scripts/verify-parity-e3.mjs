/** E3 Pump prime & calibrate (mockup 15), against frontend/dist: run after `vite build`. Opens
 * Room A's #/equipment/pump-calibration.
 *
 * The clock is pinned to today 14:10 local (the demo's calibration dates count back from it). The
 * demo reports a calibration run 3 s after it is asked for, on its own timer.
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - 3.18: the pump cards, Part B 69 days since its calibration and due; picking Part B gives
 *   "Next: prime Part B"; arrow keys move the pick and focus; Next moves focus to the step heading;
 * - step 2: the precheck says nothing stops a prime (its time outside the live list); a 2 s mouse hold on "Hold to prime" records
 *   pump_prime {room_id, pump: part_b, seconds: 30} then pump_stop {room_id, pump: part_b}, and
 *   "Line is full, next" goes on;
 * - step 3: "Stop the run" right after holding "Run 30 s" closes the session before the controller
 *   takes it (as dosing_api.py does): "The run was cancelled before the controller started it. Hold
 *   Run again.", Back enabled and the Run button back; holding it again records pump_calibrate {seconds: 30}, shows "Waiting for the
 *   controller to report the run…" with the drawing saying "Asked Part B to run 30 s" (1440), then step 4 when the run is reported;
 * - step 4: 150 mL → "150 mL in 30 s = 300 mL/min"; "Next: review and save";
 * - step 5: "Save 300 mL/min" commits {session_id, measured_ml: 150} and shows "Written and read
 *   back HH:MM", the rate sentence and the wear note;
 * - no pump call carries `client` or `proposal_token`;
 * - 3.17: "Needs integration 3.18" for "Pump prime and calibration", and no wizard. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const HHMM = String.raw`\d{1,2}:\d{2}(?: [ap]m)?`;
const calls = (page) => page.evaluate(() => (window.__csPumpCalls ?? []).map((c) => ({ action: c.action, data: c.data })));
/** A trusted mouse hold in the middle of a button. */
async function hold(page, locator, ms) {
  const box = await locator.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(ms);
  await page.mouse.up();
}

await runParity({
  id: "e3",
  route: "/equipment/pump-calibration",
  mockup: "15-E3-PumpWizard.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.goto(page.url());
    await page.getByRole("heading", { level: 1, name: "Prime & calibrate a pump" }).waitFor();
    region("title");

    if (backend === "3.17") {
      await page.locator('[data-needs-integration="Pump prime and calibration"]').waitFor();
      assert.equal(await page.locator("[data-needs-integration]").count(), 1, `${label}: one note`);
      assert.equal(await page.getByRole("radio").count(), 0, `${label}: no wizard on 3.17`);
      region("needs integration");
      return;
    }

    // Step 1: pick Part B.
    const partB = page.getByRole("radio", { name: /Part B/ });
    await partB.waitFor();
    assert.ok((await page.getByRole("radio").count()) >= 2, `${label}: pump cards`);
    assert.match(await partB.innerText(), /69 days ago · due, every 60 days/, `${label}: Part B due`);
    await partB.click();
    assert.equal(await partB.getAttribute("aria-checked"), "true", `${label}: Part B picked`);
    // Arrow keys move the pick (one tab stop for the group).
    await page.keyboard.press("ArrowRight");
    assert.equal(await page.getByRole("radio", { name: /Part A/ }).getAttribute("aria-checked"), "true", `${label}: arrow picks Part A`);
    await page.keyboard.press("ArrowLeft");
    assert.equal(await partB.getAttribute("aria-checked"), "true", `${label}: arrow back to Part B`);
    assert.ok(await partB.evaluate((el) => el === document.activeElement), `${label}: focus follows the pick`);
    const nextB = page.getByRole("button", { name: "Next: prime Part B" });
    await nextB.waitFor();
    region("pump cards");
    await nextB.click();
    assert.equal(await page.evaluate(() => document.activeElement?.textContent), "Prime the line", `${label}: focus on the new step`);

    // Step 2: hold to prime for 2 s.
    await page.getByText("Nothing stops a prime now", { exact: true }).waitFor();
    await page.getByText(new RegExp(`^Checked ${HHMM}$`)).waitFor();
    const before = (await calls(page)).length;
    await hold(page, page.getByRole("button", { name: /Hold to prime/ }), 2000);
    await page.getByText(/^You held it [\d.]+ s\./).waitFor();
    const primed = (await calls(page)).slice(before).filter((c) => c.action !== "pump_precheck");
    assert.deepEqual(
      primed.map((c) => c.action),
      ["pump_prime", "pump_stop"],
      `${label}: prime then stop`,
    );
    assert.deepEqual(primed[0].data, { room_id: "room:", pump: "part_b", seconds: 30, api: 2 }, `${label}: prime data`);
    assert.deepEqual(primed[1].data, { room_id: "room:", pump: "part_b", api: 2 }, `${label}: stop data`);
    region("prime");
    await page.getByRole("button", { name: "Line is full, next" }).click();

    // Step 3: a run stopped before the controller takes it is closed, not reported; Run comes back.
    await hold(page, page.getByRole("button", { name: /^Run 30 s/ }), 1900);
    await page.getByRole("button", { name: "Stop the run" }).click();
    await page.getByText("The run was cancelled before the controller started it. Hold Run again.").waitFor();
    await page.getByRole("button", { name: /^Run 30 s/ }).waitFor();
    assert.ok(await page.getByRole("button", { name: "Back" }).isEnabled(), `${label}: Back after a cancelled run`);
    region("run stopped before it started");
    // Hold Run 30 s past its 1.5 s confirm; the drawing says it was asked for, not that it runs.
    await hold(page, page.getByRole("button", { name: /^Run 30 s/ }), 1900);
    await page.getByText("Waiting for the controller to report the run…").waitFor();
    if (width > 720) assert.equal(await page.locator(".pump-cal-visual p").innerText(), "Asked Part B to run 30 s", `${label}: run asked for`);
    region("run");
    await page.getByRole("heading", { name: "How much did it pull?" }).waitFor({ timeout: 15_000 });
    const runs = (await calls(page)).filter((c) => c.action === "pump_calibrate");
    assert.equal(runs.length, 2, `${label}: run again after a cancelled run`);
    const run = runs[1];
    assert.deepEqual(run?.data, { room_id: "room:", pump: "part_b", seconds: 30, api: 2 }, `${label}: calibrate data`);

    // Step 4: 150 mL.
    await page.getByLabel("mL in the jug").fill("150");
    await page.getByText("150 mL in 30 s = 300 mL/min").waitFor();
    region("measured");
    await page.getByRole("button", { name: "Next: review and save" }).click();

    // Step 5: save and read back.
    await page.getByRole("button", { name: "Save 300 mL/min" }).click();
    const receipt = page.locator(".review-apply-receipt");
    await receipt.waitFor();
    assert.match(await receipt.innerText(), new RegExp(`Written and read back ${HHMM}`), `${label}: receipt`);
    assert.match(await page.locator(".pump-cal-rate").innerText(), /^300 mL\/min — \d+% below the catalogue figure\.$/, `${label}: rate sentence`);
    assert.match(await page.locator(".pump-cal-wear").innerText(), /^Down \d+% since [A-Z][a-z]+ — tubing may be wearing\.$/, `${label}: wear note`);
    assert.equal(await page.locator(".pump-cal-spark").count(), 1, `${label}: wear sparkline`);
    const commit = (await calls(page)).find((c) => c.action === "pump_calibration_commit");
    assert.equal(commit?.data.measured_ml, 150, `${label}: measured`);
    assert.match(String(commit?.data.session_id), /^demo-pump-cal-/, `${label}: session id`);
    for (const c of await calls(page))
      assert.ok(!("client" in c.data) && !("proposal_token" in c.data), `${label}: ${c.action} sends no client or proposal_token`);
    region("receipt");
  },
});
console.log("PASS: E3 pump prime & calibrate (pick, hold to prime, 30 s run, mL, save with read-back; 3.17 note)");
