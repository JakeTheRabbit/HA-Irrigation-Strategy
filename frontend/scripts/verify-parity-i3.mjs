/** I3 Timer programs (mockup 07), against frontend/dist: run after `vite build`. Opens
 * #/plan/timers in the demo (Room A plays F2: zone 3 waters by "Zone 3 day timer", 1 min every 45 min
 * while its lights are on, 10:00–22:00; a night top-up draft; Room B has no timer).
 *
 * The clock is pinned to today 14:10 local, so the demo day is the same at any real hour.
 *
 * Interactions asserted, at 1440 and 390:
 * - 3.18: the program cards ("On · next shot today 14:30", "Draft · not running");
 * - 3.18: the Amount sentence: on a phone its choices are native selects;
 * - 3.18: Every 45 → 30 min changes the Next 24 hours count, and the daily limit names its stop;
 * - 3.18: the edit goes through Review & apply: "Written and read back HH:MM", the card reads the new
 *   interval and the button "Saved"; its Undo writes the previous program back;
 * - 3.18: a custom window ending at its start shows "End must be after start" beside it and the
 *   preview goes blank;
 * - 3.18: Delete program acts at once with an Undo toast; Undo restores it (under its new id) and
 *   opens it;
 * - 3.18: irrigation mode: Timer on a steering zone says what it does first; Keep leaves it; Off on
 *   zone 2 is written and read back, its Undo puts Steering back;
 * - 3.18 desktop: the room tree picks Room B: "No timer yet…", Use that opens a draft and "Pick at
 *   least one zone" shows beside Zones;
 * - 3.17: the page shows "Needs integration 3.18" (Timer programs).
 * Also writes full-page light and dark screenshots of each run beside the harness's own. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const out = (name) =>
  new URL(`../../output/playwright/parity/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

await runParity({
  id: "i3",
  route: "/plan/timers",
  mockup: "07-I3-Timers.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const phone = width <= 720;
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    const main = page.locator("main");
    await main.getByRole("heading", { level: 1, name: "Timer programs", exact: true }).waitFor();
    const shoot = async (name) => {
      for (const scheme of ["light", "dark"]) {
        await page.emulateMedia({ colorScheme: scheme });
        await page.screenshot({ path: out(`i3-${name}-${width}-${backend}-${scheme}.png`), fullPage: true, animations: "disabled" });
      }
      await page.emulateMedia({ colorScheme: "light" });
      // Colours ease back after a scheme change: let them settle before the harness's contrast audit.
      await page.waitForTimeout(500);
    };

    if (backend === "3.17") {
      const note = main.locator('[data-needs-integration="Timer programs"]');
      await note.waitFor();
      assert.match(await note.innerText(), /Needs integration 3\.18/, `${label}: note`);
      await shoot("full");
      region("needs integration note");
      return;
    }

    // The cards.
    const cards = main.locator(".tm-card");
    await cards.first().waitFor();
    assert.equal(await cards.count(), 2, `${label}: two programs`);
    assert.match(await cards.nth(0).innerText(), /Every 45 min for 1 min, while lights are on, Room A zone 3\s+On · next shot today 14:30/);
    assert.match(await cards.nth(1).innerText(), /2 times a day for 90 s, while lights are off, Room A zone 3\s+Draft · not running/);
    region("program cards");

    // The preview of the saved program.
    const summary = main.locator("[data-timer-summary]");
    await page.waitForFunction(() => /^16 shots/.test(document.querySelector("[data-timer-summary]")?.textContent ?? ""));
    assert.equal(await summary.innerText(), "16 shots · 16 min · about 1.1 L per plant. First today 14:30.", `${label}: summary`);
    assert.ok(await main.locator(".tm-preview .st-block").count() >= 16, `${label}: shots drawn`);
    await shoot("full");
    region("next 24 hours");

    // The Amount sentence: native selects on a phone.
    const amount = main.getByRole("group", { name: "Amount" });
    if (phone) {
      assert.equal(await amount.locator('select[aria-label="Run for"]').count(), 1, `${label}: native Run for`);
      await amount.locator('select[aria-label="Every"]').selectOption("30");
    } else {
      assert.equal(await amount.locator("select").count(), 0, `${label}: listbox tokens on desktop`);
      await amount.getByRole("button", { name: "Every: 45 min" }).click();
      await page.getByRole("option", { name: "30 min" }).click();
    }
    region("amount sentence");
    await page.waitForFunction(() => /^24 shots/.test(document.querySelector("[data-timer-summary]")?.textContent ?? ""));
    assert.match(await summary.innerText(), /^24 shots · 24 min · about 1\.6 L per plant\. Stops after shot 16: daily limit 1\.11 L per plant\./, `${label}: count changed, daily limit`);
    assert.ok(await main.locator('.tm-preview .st-block[data-glyph="failed"]').count() >= 1, `${label}: blocked shots drawn`);
    assert.match(await main.locator(".tm-kicker").innerText(), /Unsaved edits/i);
    region("preview count");

    // Save through Review & apply.
    if (phone) {
      await main.getByRole("button", { name: "Review 1 change" }).click();
      await page.getByRole("dialog", { name: "Review and apply" }).getByRole("button", { name: "Apply 1 change" }).click();
    } else await main.getByRole("button", { name: "Apply 1 change" }).click();
    const receipt = main.locator(".review-apply-receipt");
    await receipt.waitFor();
    assert.match(await receipt.innerText(), /Written and read back \d{2}:\d{2}/, `${label}: read back`);
    assert.match(await receipt.innerText(), /Every 45 min → 30 min/, `${label}: receipt row`);
    await main.getByRole("button", { name: "Saved", exact: true }).waitFor();
    assert.match(await cards.nth(0).innerText(), /^Every 30 min for 1 min/, `${label}: card reads the save`);
    await shoot("saved");
    await receipt.getByRole("button", { name: "Undo: write back the previous values" }).click();
    await main.getByText(/Previous values written back/).waitFor();
    await page.waitForFunction(() => /^Every 45 min/.test(document.querySelector(".tm-card")?.textContent ?? ""));
    region("review apply saved undo");

    // A custom window that ends where it starts.
    await main.getByRole("group", { name: "When" }).getByRole("button", { name: "Custom" }).click();
    await amount.locator('input[aria-label="To"]').fill("08:00");
    const end = main.locator('[data-field-error="end"]');
    await end.waitFor();
    assert.equal(await end.innerText(), "End must be after start", `${label}: end error`);
    assert.equal(await main.locator(".tm-preview .shot-timeline").count(), 0, `${label}: preview blank`);
    region("field error");
    if (phone) {
      // Discard sits in the review sheet.
      await main.getByRole("button", { name: /^Review \d+ changes?$/ }).click();
      await page.getByRole("dialog", { name: "Review and apply" }).getByRole("button", { name: "Discard edits" }).click();
    } else await main.getByRole("button", { name: "Discard edits" }).click();
    await page.waitForFunction(() => !document.querySelector('[data-field-error="end"]'));

    // Delete at once, Undo restores.
    await main.getByRole("button", { name: "Delete program" }).click();
    const deleted = page.locator("[data-sonner-toast]").filter({ hasText: /^Deleted: Every 45 min/ });
    await deleted.waitFor();
    await page.waitForFunction(() => document.querySelectorAll(".tm-card").length === 1);
    await deleted.getByRole("button", { name: "Undo" }).click();
    await page.locator("[data-sonner-toast]").filter({ hasText: /^Restored: Every 45 min/ }).waitFor();
    await page.waitForFunction(() => document.querySelectorAll(".tm-card").length === 2);
    assert.equal(await main.locator('.tm-card[aria-pressed="true"] b').innerText(), "Every 45 min for 1 min, while lights are on, Room A zone 3", `${label}: restored and open`);
    assert.match(await main.locator("#tm-editor-title").innerText(), /^Every 45 min/);
    region("delete undo");

    // Irrigation mode.
    const modes = main.locator(".tm-modes");
    const zone = (n) => modes.locator(`li[data-zone="${n}"]`);
    await zone(1).getByRole("button", { name: "Timer" }).click();
    assert.equal(
      await zone(1).locator(".tm-mode-note").innerText(),
      "Zone 1 stops steering and waters only by its timers. No running program covers it, so it will not be watered.",
      `${label}: consequence first`,
    );
    await zone(1).getByRole("button", { name: "Keep Steering" }).click();
    assert.equal(await zone(1).getByRole("button", { name: "Steering" }).getAttribute("aria-pressed"), "true");
    await zone(2).getByRole("button", { name: "Off" }).click();
    await zone(2).getByRole("button", { name: "Switch Zone 2 to Off" }).click();
    const switched = page.locator("[data-sonner-toast]").filter({ hasText: /^Zone 2 set to Off\. Written and read back \d{2}:\d{2}\./ });
    await switched.waitFor();
    assert.equal(await zone(2).getByRole("button", { name: "Off" }).getAttribute("aria-pressed"), "true");
    await switched.getByRole("button", { name: "Undo" }).click();
    await page.locator("[data-sonner-toast]").filter({ hasText: "Zone 2 is back on Steering." }).waitFor();
    assert.equal(await zone(2).getByRole("button", { name: "Steering" }).getAttribute("aria-pressed"), "true");
    region("irrigation mode");

    // Room B from the room tree: no timer yet.
    if (!phone) {
      await page.locator('.room-tree [data-room="room:room_b_"] .room-tree-row').first().click();
      await main.getByRole("heading", { level: 1, name: "Timer programs", exact: true }).waitFor();
      const empty = main.locator("[data-timers-empty]");
      await empty.waitFor();
      assert.match(await empty.innerText(), /No timer yet\. Most mother rooms use 2 min every 2 h during lights-on\./);
      await empty.getByRole("button", { name: "Use that" }).click();
      const zones = main.locator('[data-field-error="zones"]');
      await zones.waitFor();
      assert.equal(await zones.innerText(), "Pick at least one zone", `${label}: zones error`);
      assert.match(await main.locator("#tm-editor-title").innerText(), /^Every 120 min for 2 min, while lights are on, no zones yet$/);
      await shoot("room-b");
      region("empty state use that");
    }
  },
});
console.log(
  "PASS: I3 timer programs (cards, native selects on phone, Every 45→30 changes the preview and names the daily-limit stop, save read back + Saved + undo, End must be after start beside its field, delete + undo restores, mode consequence + read-back + undo, Room B empty state + Use that, 3.17 note; clock pinned 14:10)",
);
