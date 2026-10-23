/** T4 AI assistant (mockup 22) at #/settings/ai, against frontend/dist: run after `vite build`.
 *
 * The clock is pinned to today 14:10 local, so the demo's AI ledger (Room A's judgement at 11:30, its
 * outcome at 14:00) is the same at any real hour.
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - Judges: 15 judges, "k of n on · Room A and Room B"; Room A's "Shot sizes" is a switch, Room B (an
 *   integration from before the power switches) says "No switch"; alert judges are read only;
 * - toggling "Shot sizes in Room A" writes at once and toasts "Shot sizes on in Room A. Written and
 *   read back HH:MM." with Undo; Undo puts it back off and toasts "… off again in Room A. Written and
 *   read back HH:MM.";
 * - Budget today: "$0.13 of $1.00", the calls line (3.18: system_status_get.ai "42 of 200 calls
 *   (21.0 %)" with its bar; 3.17: the brain sensor's calls), and the daily budget shown read only
 *   with where to change it: the controller app's options (no write service exists, so no receipt);
 * - Dry run and the model as the controller reports them (Haiku 5.5 current); calls and spend are said
 *   once, in Budget today, not again beside the model;
 * - What it did, and what happened: at least one row (3.18 Journal "Worked"; 3.17 decision log);
 *   "Full ledger in History →" opens #/history/changes?actor=ai;
 * - the prompt editor sits under "Instructions and permissions", and the power switches are not
 *   repeated there. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const HHMM = String.raw`\d{1,2}:\d{2}(?: [ap]m)?`;

await runParity({
  id: "t4",
  route: "/settings/ai",
  mockup: "22-T4-AI.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const v318 = backend === "3.18";
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    await page.getByRole("heading", { level: 1, name: "AI assistant", exact: true }).waitFor();

    // Judges.
    const judges = page.locator("[data-ai-judges]");
    assert.equal(await judges.locator("tbody tr").count(), 15, `${label}: judges`);
    assert.match(
      await judges.locator(".ai-card-head > span").innerText(),
      /^\d+ of \d+ on · Room A and Room B$/,
      `${label}: count`,
    );
    const shots = judges.getByRole("switch", { name: "Shot sizes in Room A", exact: true });
    assert.equal(await shots.getAttribute("aria-checked"), "false", `${label}: shot sizes off by default`);
    assert.equal(
      await judges.locator('tr[data-judge="shotsize"] td').last().innerText(),
      "No switch",
      `${label}: Room B has no switch`,
    );
    assert.equal(
      await judges.getByRole("img", { name: /^Water path in Room A: not asked\. Set in the controller app\.$/ }).count(),
      1,
      `${label}: alert judge read only`,
    );
    region("judges");

    // Immediate write, then Undo.
    await shots.click();
    const toast = page.locator("[data-sonner-toast]");
    await toast
      .filter({ hasText: new RegExp(`^Shot sizes on in Room A\\. Written and read back ${HHMM}\\.`) })
      .waitFor();
    assert.equal(await shots.getAttribute("aria-checked"), "true", `${label}: switch on`);
    await toast.getByRole("button", { name: "Undo" }).click();
    await toast
      .filter({ hasText: new RegExp(`^Shot sizes off again in Room A\\. Written and read back ${HHMM}\\.`) })
      .waitFor();
    assert.equal(await shots.getAttribute("aria-checked"), "false", `${label}: undone`);
    region("judge switch undo");

    // Budget.
    const budget = page.locator("[data-ai-budget]");
    assert.equal(await budget.locator(".ai-spent").innerText(), "$0.13", `${label}: spent`);
    await budget.getByText("of $1.00", { exact: true }).waitFor();
    if (v318) {
      await budget.getByText(/^42 of 200 calls \(21\.0 %\)/).waitFor();
      assert.equal(await budget.getByRole("meter", { name: "AI calls used today" }).count(), 1);
    } else await budget.getByText(/^\d+ calls/).waitFor();
    await budget.getByText("This page cannot change it.", { exact: false }).waitFor();
    assert.equal(await budget.locator("input").count(), 0, `${label}: no pretend budget editor`);
    region("budget");

    // Dry run and model.
    const model = page.locator("[data-ai-model]");
    await model.getByText("Dry run off", { exact: true }).waitFor();
    assert.equal(
      await model.locator('[aria-current="true"]').innerText(),
      "Haiku 5.5",
      `${label}: current model`,
    );
    assert.equal(await model.getByText(/calls|\$\d/).count(), 0, `${label}: calls and spend said once`);
    region("dry run and model");

    // Ledger.
    const ledger = page.locator("[data-ai-ledger]");
    await ledger.locator("ol.ai-outcomes > li").first().waitFor();
    if (v318) await ledger.locator(".ai-pill", { hasText: "Worked" }).first().waitFor();
    region("ledger");

    // Instructions and permissions.
    const instructions = page.locator(".ai-instructions");
    await instructions.getByRole("heading", { name: "Instructions and permissions" }).waitFor();
    assert.equal(await instructions.locator("[data-brain-instructions]").count(), 1);
    assert.equal(await instructions.locator('[id^="config-ai_power_"]').count(), 0, `${label}: powers once`);
    region("instructions");

    // The ledger link opens Changes filtered to the AI (last: it leaves the page).
    await ledger.getByRole("link", { name: "Full ledger in History →" }).click();
    await page.waitForFunction(() => location.hash === "#/history/changes?actor=ai");
    await page.goBack();
    await page.getByRole("heading", { level: 1, name: "AI assistant", exact: true }).waitFor();
    region("ledger link");
  },
});
console.log("verify-parity-t4: passed at 1440 and 390 on 3.18 and 3.17.");
