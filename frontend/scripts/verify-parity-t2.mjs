/** T2 Notifications (mockup 20), against frontend/dist: run after `vite build`. PORT sets the
 * harness's port (0, any free one, without it).
 *
 * The clock is pinned to today 14:10 local, so the demo's Room B mute (until 20:00) and every
 * "HH:MM" read the same at any real hour.
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - the matrix: a column per kind in the catalogue's order, then Rooms and Emergencies loud, each
 *   phone with Send test and "Never tested"; on a phone, a card per phone;
 * - Tick Manager's Dosing: the bar says "1 change not applied yet: Manager gets Dosing"; Apply
 *   1 change; the receipt says "Written and read back 14:10" and the box stays ticked;
 * - Test all: every phone says "Accepted 14:10" (3.17 is asked phone by phone);
 * - 3.18: Mute Room A for 2 h: the toast says "Room A muted until 16:10. Written and read back
 *   14:10." and the row says so; Undo: "Room A sends every alert again", and the row is back;
 *   Room B reads "muted until 20:00";
 * - 3.18: each phone's chip shows its own window (Owner 23:00–05:00, Grower none); pick Grower, turn
 *   them on and set 22:00–06:00: the strip goes from 6 h to 8 h, spans 00:00–06:00 and 22:00–24:00, Owner keeps
 *   23:00–05:00, and the bar says exactly "1 change not applied yet: Grower: quiet 22:00–06:00";
 *   Discard leaves no draft;
 * - 3.17: quiet hours and room mutes are "Needs integration 3.18" in place; the rest works. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const out = (name) =>
  new URL(`../../output/playwright/parity/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const KINDS = [
  "Emergencies",
  "Hardware lockouts",
  "Sensors and drift",
  "Shots stopped",
  "Phase changes",
  "Vitals",
  "Stock tanks",
  "Dosing",
  "AI assistant",
  "Setup and settings",
];

await runParity({
  id: "t2",
  route: "/settings/notifications",
  mockup: "20-T2-Notifications.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const v318 = backend === "3.18";
    const phone = width <= 720;
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    const main = page.locator("main");
    await main.getByRole("heading", { name: "Who gets which alerts" }).waitFor();
    for (const scheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.screenshot({ path: out(`t2-full-${width}-${backend}-${scheme}.png`), fullPage: true, animations: "disabled" });
    }
    await page.emulateMedia({ colorScheme: "light" });

    // The matrix.
    if (phone) {
      assert.equal(await page.locator("[data-notify-card]").count(), 3, `${label}: a card per phone`);
      assert.equal(await page.locator("table.notify-table").isVisible(), false, `${label}: no table on a phone`);
    } else {
      const head = page.locator("table.notify-table thead th");
      const names = (await head.allInnerTexts()).map((text) => text.trim());
      assert.deepEqual(names, ["Phone", ...KINDS, "Rooms", "Emergencies loud"], `${label}: columns`);
      assert.equal(await page.locator("table.notify-table tbody tr").count(), 3, `${label}: rows`);
    }
    const scope = phone ? page.locator(".notify-cards") : page.locator("table.notify-table");
    assert.equal(await scope.getByText("Never tested").count(), 3, `${label}: never tested`);
    assert.equal(
      await scope.getByRole("switch", { name: "Owner (Phone 1): Emergencies loud" }).isChecked(),
      true,
      `${label}: Emergencies loud`,
    );
    region("matrix");

    // Tick Manager's Dosing: the bar's sentence, Apply, the receipt.
    const dosing = scope.getByRole("checkbox", { name: "Manager (Phone 3): Dosing", exact: true });
    await dosing.check();
    let bar = page.locator(".notify-bar");
    if (phone) {
      await bar.getByRole("button", { name: "Review 1 change" }).click();
      bar = page.getByRole("dialog", { name: "Review and apply" });
    }
    assert.equal(
      (await bar.locator("[data-draft-summary]").innerText()).trim(),
      "1 change not applied yet: Manager gets Dosing",
      `${label}: bar sentence`,
    );
    await bar.getByRole("button", { name: "Discard", exact: true }).waitFor();
    await bar.getByRole("button", { name: "Apply 1 change", exact: true }).click();
    const receipt = page.locator(".notify-bar .review-apply-receipt");
    await receipt.waitFor();
    assert.match(await receipt.innerText(), /Written and read back 14:10/, `${label}: receipt`);
    assert.equal(await dosing.isChecked(), true, `${label}: Dosing kept`);
    region("bar");

    // Test all.
    await main.getByRole("button", { name: "Test all", exact: true }).click();
    await page.waitForFunction(
      (sel) => [...document.querySelectorAll(sel)].filter((el) => el.offsetParent && el.textContent === "Accepted 14:10").length === 3,
      phone ? ".notify-cards .notify-test-result" : "table.notify-table .notify-test-result",
    );
    region("test");

    const quiet = main.locator(".notify-quiet");
    const mutes = main.locator(".notify-idle");
    if (!v318) {
      await quiet.getByRole("heading", { name: "Needs integration 3.18" }).waitFor();
      await mutes.getByText("Needs integration 3.18").waitFor();
      assert.equal(await mutes.getByRole("button", { name: /^Mute / }).count(), 0, `${label}: no mutes on 3.17`);
      region("needs-integration");
      return;
    }

    // Mute Room A for 2 h, then Undo.
    const roomA = mutes.locator('[data-mute-room=""]');
    assert.equal((await roomA.innerText()).split("\n")[0], "Room A sends every alert.", `${label}: Room A not muted`);
    assert.match(
      await mutes.locator('[data-mute-room="room_b_"]').innerText(),
      /^Room B muted until 20:00\. Only emergencies get through\./,
      `${label}: Room B muted`,
    );
    await roomA.getByRole("button", { name: "Mute Room A for 2 h" }).click();
    const toast = page.locator("[data-sonner-toast]", { hasText: "Room A muted until 16:10. Written and read back 14:10." });
    await toast.waitFor();
    await roomA.getByRole("button", { name: "Unmute Room A" }).waitFor();
    assert.match(await roomA.innerText(), /Room A muted until 16:10\. Only emergencies get through\./, `${label}: muted row`);
    await toast.getByRole("button", { name: "Undo" }).click();
    await page.locator("[data-sonner-toast]", { hasText: "Room A sends every alert again. Written and read back 14:10." }).waitFor();
    await roomA.getByRole("button", { name: "Mute Room A for 2 h" }).waitFor();
    region("mutes");

    // Quiet hours 22:00–06:00 on Grower, and on Grower only: the strip goes from 6 h to 8 h.
    const legend = quiet.locator("[data-quiet-legend]");
    assert.match(await legend.innerText(), /quiet 6 h/, `${label}: owner's quiet hours`);
    assert.match(await legend.innerText(), /lights on: Room A 10:00–22:00, Room B 08:00–20:00/, `${label}: lights`);
    const chips = quiet.getByRole("radiogroup", { name: "Quiet hours for" });
    const chip = (name) => chips.getByRole("radio", { name: new RegExp(`^${name} `) });
    assert.equal((await chip("Owner").innerText()).replace(/\s+/g, " ").trim(), "Owner 23:00–05:00", `${label}: Owner's window`);
    assert.equal((await chip("Grower").innerText()).replace(/\s+/g, " ").trim(), "Grower no quiet hours", `${label}: Grower has none`);
    await chip("Grower").click();
    assert.equal(await chip("Grower").getAttribute("aria-checked"), "true", `${label}: Grower shown`);
    assert.equal(await chip("Owner").getAttribute("aria-checked"), "false", `${label}: Owner not shown`);
    assert.match(await quiet.innerText(), /emergencies still come through, and so do the AI's setpoint changes with Keep and Undo/, `${label}: quiet note`);
    assert.match(await quiet.innerText(), /A Home Assistant restart drops what is waiting\./, `${label}: restart note`);
    assert.equal((await quiet.locator(".notify-strip-ticks span").last().innerText()).trim(), "24:00", `${label}: day end tick`);
    assert.equal(await quiet.getByRole("switch", { name: /^Quiet hours on Grower/ }).isChecked(), false, `${label}: Grower off`);
    await quiet.getByRole("switch", { name: /^Quiet hours on Grower/ }).check();
    await quiet.getByLabel("From").fill("22:00");
    await quiet.getByLabel("to", { exact: true }).fill("06:00");
    assert.equal(await quiet.getByRole("switch", { name: /^Quiet hours on Grower/ }).isChecked(), true, `${label}: Grower on`);
    assert.match(await legend.innerText(), /quiet 8 h/, `${label}: strip 8 h`);
    assert.deepEqual(
      await quiet.locator("[data-quiet-span]").evaluateAll((spans) => spans.map((span) => span.dataset.quietSpan)),
      ["0-360", "1320-1440"],
      `${label}: strip spans`,
    );
    assert.equal((await chip("Owner").innerText()).replace(/\s+/g, " ").trim(), "Owner 23:00–05:00", `${label}: Owner unchanged`);
    assert.equal((await chip("Grower").innerText()).replace(/\s+/g, " ").trim(), "Grower 22:00–06:00", `${label}: Grower's window`);
    // A problem sits on its field: the same start and end shows under the quiet-hours editor.
    await quiet.getByLabel("to", { exact: true }).fill("22:00");
    await quiet.locator(".field-error", { hasText: "Quiet hours need a start and an end that differ." }).waitFor();
    await quiet.getByLabel("to", { exact: true }).fill("06:00");
    await quiet.locator(".field-error").waitFor({ state: "detached" });
    let quietBar = page.locator(".notify-bar");
    if (phone) {
      await quietBar.getByRole("button", { name: "Review 1 change", exact: true }).click();
      quietBar = page.getByRole("dialog", { name: "Review and apply" });
    }
    assert.equal(
      (await quietBar.locator("[data-draft-summary]").innerText()).trim(),
      "1 change not applied yet: Grower: quiet 22:00–06:00",
      `${label}: bar names Grower's quiet hours only`,
    );
    await quietBar.getByRole("button", { name: "Discard", exact: true }).click();
    if (phone && (await quietBar.isVisible())) await quietBar.getByRole("button", { name: "Close" }).click();
    assert.match(await legend.innerText(), /quiet 6 h/, `${label}: discarded`);
    region("quiet");
  },
});
