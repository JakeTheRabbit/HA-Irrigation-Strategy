/** E6 Setup: pumps & valves (mockup 18), against frontend/dist: run after `vite build`.
 * Opens Setup at #/equipment/setup in the demo (Room A: three zones of 36 plants × 1 dripper at
 * 4.0 L/h, pump switch.demo_pump at 1200 L/h, one zone at a time; Room A is watering, so the
 * integration refuses a setup change and a dripper flow edit is not written).
 *
 * The clock is pinned to today 14:10 local, so the demo is the same at any real hour.
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - 3.18: the pump card, the zone table and "What can run together" are there;
 * - Max flow 1200 → 900: one change, "Pump max flow 1200 L/h → 900 L/h", and the checks from the
 *   integration's capacity check ("Pump max flow 900 L/h is in range", "Every zone fits the pump on
 *   its own");
 * - Zone 3 dripper flow 4.0 → 3.0: two changes, "was 4.0" under the field;
 * - Apply 2 changes: supply_save takes, setup_save is refused while Room A waters: "Pump settings
 *   were saved. Zone 3 dripper flow was not: controller still holds 4.0 L/h." with Try again, and the
 *   dripper row stays (1 change); the refusal's reason is on Zone 3's row (aria-describedby), not
 *   on Zone 2's when that is edited, and editing Zone 3 clears it;
 * - Max flow retyped as the shown value (900.0): no change;
 * - Discard changes, Max flow 800, Apply 1 change: "Written and read back HH:MM"; Undo writes the
 *   previous values back;
 * - Max flow 250 with 2 zones at once: a red check blocks Apply, the pump card says "The pump can't
 *   feed 2 zones at once. Set Zones at once to 1 or less." and Use 1 sets it;
 * - 3.17: the "Needs integration 3.18" note for pump capacity, and the Setup page's room-name field
 *   still there. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const HHMM = String.raw`\d{1,2}:\d{2}(?: [ap]m)?`;

await runParity({
  id: "e6",
  route: "/equipment/setup",
  mockup: "18-E6-Setup.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByRole("heading", { level: 1, name: "Rooms and setup", exact: true }).waitFor();

    if (backend === "3.17") {
      const note = page.locator('[data-needs-integration="Pump capacity and exclusive groups"]');
      await note.waitFor();
      assert.match(await note.innerText(), /Needs integration 3\.18/, `${label}: note`);
      await page.getByLabel("Room name", { exact: true }).waitFor();
      region("needs integration note");
      region("room name field");
      return;
    }

    const editor = page.locator("[data-supply-editor]");
    await editor.waitFor();
    assert.match(await editor.locator("h2").first().innerText(), /^Setup: pumps & valves · Room A$/, `${label}: heading`);
    const panel = editor.getByRole("region", { name: "Review and apply" });
    const sub = panel.locator(".review-apply-sub");
    const maxFlow = editor.getByLabel("Max flow", { exact: true });
    const dripper = editor.getByLabel("Zone 3 dripper flow", { exact: true });
    await dripper.waitFor();
    assert.equal(await maxFlow.inputValue(), "1200", `${label}: saved max flow`);
    assert.equal(await dripper.inputValue(), "4.0", `${label}: saved dripper flow`);
    await editor.getByRole("heading", { name: "What can run together" }).waitFor();
    assert.equal(await editor.locator(".supply-together li").count(), 4, `${label}: 3 pairs and all three`);
    region("pump card");
    // A room with many zones: every "Max zones at once" count stays reachable (the counts wrap).
    // The demo rooms have three zones, so a copy of the real group holding twelve counts is
    // measured under the page's own stylesheet, then removed.
    const counts = await editor.getByRole("group", { name: "Max zones at once" }).evaluate((group) => {
      const copy = group.cloneNode(true);
      copy.removeAttribute("aria-labelledby");
      copy.setAttribute("aria-hidden", "true");
      const proto = copy.querySelector("button");
      copy.replaceChildren(
        ...Array.from({ length: 12 }, (_, i) => {
          const b = proto.cloneNode(true);
          b.textContent = String(i + 1);
          return b;
        }),
      );
      group.after(copy);
      const card = group.closest(".supply-card").getBoundingClientRect();
      const right = Math.min(card.right, document.documentElement.clientWidth);
      const rects = [...copy.children].map((b) => b.getBoundingClientRect());
      copy.remove();
      return { lines: new Set(rects.map((r) => Math.round(r.top))).size, out: rects.filter((r) => r.right > right + 0.5).length };
    });
    assert.equal(counts.out, 0, `${label}: 12 zone counts all inside the pump card`);
    if (width <= 720) assert.ok(counts.lines > 1, `${label}: 12 zone counts wrap at phone width`);
    region("max zones at once, 12 zones");
    region("zone valves and drippers");
    region("what can run together");

    // Max flow 900: one change, and the checks of the preview.
    await maxFlow.fill("900");
    assert.equal(await sub.innerText(), "1 unsaved change, not active until applied", `${label}: one change`);
    assert.match(await panel.locator(".review-apply-rows").innerText(), /Pump max flow\s+1200 L\/h → 900 L\/h/);
    const checks = panel.getByRole("list", { name: "Checks" });
    await checks.getByText("Pump max flow 900 L/h is in range", { exact: true }).waitFor();
    await checks.getByText("Every zone fits the pump on its own", { exact: true }).waitFor();
    region("review and apply");

    // Zone 3 dripper flow: two changes.
    await dripper.fill("3.0");
    assert.equal(await sub.innerText(), "2 unsaved changes, not active until applied", `${label}: two changes`);
    assert.match(await editor.locator('tr[data-zone="3"]').innerText(), /was 4\.0/, `${label}: was`);

    // Apply: the pump takes, the dripper flow is refused while Room A waters.
    await panel.getByRole("button", { name: "Apply 2 changes" }).click();
    const failure = panel.getByRole("alert");
    await failure.waitFor();
    assert.equal(
      (await failure.locator("span").first().innerText()).trim(),
      "Pump settings were saved. Zone 3 dripper flow was not: controller still holds 4.0 L/h.",
      `${label}: partial failure`,
    );
    await failure.getByRole("button", { name: "Try again" }).waitFor();
    assert.equal(await sub.innerText(), "1 unsaved change, not active until applied", `${label}: dripper row stays`);
    assert.equal(await maxFlow.inputValue(), "900", `${label}: saved 900`);
    region("partial failure");
    // The refusal's reason sits on Zone 3's row, tied to its field; another row never shows it, and
    // editing Zone 3 clears it.
    const row3 = editor.locator('tr[data-zone="3"]');
    const reason = row3.locator(".supply-error");
    await reason.waitFor();
    assert.equal(await dripper.getAttribute("aria-describedby"), await reason.getAttribute("id"), `${label}: reason tied to field`);
    await editor.getByLabel("Zone 2 dripper flow", { exact: true }).fill("3.5");
    assert.equal(await editor.locator('tr[data-zone="2"] .supply-error').count(), 0, `${label}: reason not on zone 2`);
    await dripper.fill("3.1");
    assert.equal(await reason.count(), 0, `${label}: reason cleared on edit`);

    // A pump change alone: written and read back, then undone.
    await panel.getByRole("button", { name: "Discard changes" }).click();
    assert.equal(await sub.innerText(), "No unsaved changes.", `${label}: discarded`);
    // Retyping the shown value is no change.
    await maxFlow.fill("900.0");
    assert.equal(await sub.innerText(), "No unsaved changes.", `${label}: same value, no change`);
    await maxFlow.fill("800");
    await panel.getByRole("button", { name: "Apply 1 change" }).click();
    const receipt = panel.locator(".review-apply-receipt");
    await receipt.waitFor();
    assert.match(await receipt.innerText(), new RegExp(`Written and read back ${HHMM}`), `${label}: receipt`);
    assert.match(await receipt.innerText(), /Pump max flow 900 L\/h → 800 L\/h/, `${label}: receipt rows`);
    await receipt.getByRole("button", { name: "Undo: write back the previous values" }).click();
    await panel.getByText(new RegExp(`^Previous values written back ${HHMM}$`)).waitFor();
    assert.equal(await maxFlow.inputValue(), "900", `${label}: undone`);
    region("receipt and undo");

    // Over capacity: a red check, the sentence in place and Use 1.
    await maxFlow.fill("250");
    await editor.getByRole("group", { name: "Max zones at once" }).getByRole("button", { name: "2", exact: true }).click();
    const refusal = editor.locator(".supply-refusal");
    await refusal.waitFor();
    assert.match(
      await refusal.innerText(),
      /The pump can't feed 2 zones at once\. Set Zones at once to 1 or less\./,
      `${label}: refusal`,
    );
    await panel.getByText("Fix the red check to apply").waitFor();
    await refusal.getByRole("button", { name: "Use 1" }).click();
    assert.equal(
      await editor.getByRole("group", { name: "Max zones at once" }).getByRole("button", { name: "1", exact: true }).getAttribute("aria-pressed"),
      "true",
      `${label}: use 1`,
    );
    await refusal.waitFor({ state: "detached" });
    await panel.getByRole("button", { name: "Discard changes" }).click();
    region("over capacity");
  },
});
console.log("PASS: E6 Setup pumps & valves (2 viewports x 2 backends)");
