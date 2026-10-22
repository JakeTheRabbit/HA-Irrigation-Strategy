/** I4 Grow plan & presets (mockup 08), against frontend/dist: run after `vite build`. Opens
 * #/plan/schedule in the demo (Room A plays F2, lights 10:00–22:00; Room B plays F1).
 *
 * The clock is pinned to today 14:10 local, so the next lights-on is tomorrow 10:00 at any real hour.
 *
 * Interactions asserted, at 1440 and 390:
 * - 3.18: the plan's head names the room, its state chip and "Arm at lights-on, <Day> 10:00";
 * - 3.18: one typed balance makes "Draft · 1 edit, not live yet" with Discard draft and Review & save;
 *   Discard draft puts the saved plan back;
 * - 3.18: "Add exception on day N" moves the grid to days on that day; a typed balance shows the
 *   "Exception · in draft" card;
 * - 3.18: the presets panel: "Stored on the controller…", the room's live card and the two seeded
 *   presets; Save Room A plan as a new preset adds a card;
 * - 3.18: Copy to room: the room tree picks (the sidebar on desktop, a bottom sheet on a phone),
 *   Room A is not offered; the preview lists 3 changes, old struck, and "Not copied: P2 dilute ratio
 *   (Room B has no such setting)"; "Copy 3 changes to Room B" writes, "Written and read back HH:MM"
 *   names the setting not copied and claims only the values written; Undo puts every value back;
 * - 3.18 desktop: from Room B to Room A, Room B has no timer programs: the receipt names the rows
 *   written and the timers not copied, and says Undo is not available here (History › Changes);
 * - 3.18: the browser recipe library sits under "On this browser";
 * - 3.17: the presets panel shows "Needs integration 3.18"; the grow plan and the browser recipes work.
 * Also writes full-page light and dark screenshots of each run beside the harness's own. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const out = (name) =>
  new URL(`../../output/playwright/parity/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

await runParity({
  id: "i4",
  route: "/plan/schedule",
  mockup: "08-I4-GrowPlan.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const phone = width <= 720;
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    const main = page.locator("main");
    const shoot = async (name) => {
      for (const scheme of ["light", "dark"]) {
        await page.emulateMedia({ colorScheme: scheme });
        await page.screenshot({ path: out(`i4-${name}-${width}-${backend}-${scheme}.png`), fullPage: true, animations: "disabled" });
      }
      await page.emulateMedia({ colorScheme: "light" });
      // Colours ease back after a scheme change: let them settle before the harness's contrast audit.
      await page.waitForTimeout(500);
    };
    await main.getByRole("heading", { level: 2, name: "Room A grow plan", exact: true }).waitFor();
    const presets = main.locator(".presets-panel");
    await presets.waitFor();

    // The browser recipe library, on both backends.
    const openTab = async (name) => {
      const advanced = main.locator("details.plan-advanced");
      if ((await advanced.getAttribute("open")) === null) await advanced.locator("> summary").click();
      await main.getByRole("tablist", { name: "Grow planner view" }).getByRole("tab", { name, exact: true }).click();
    };
    await openTab("Recipes");
    await main.getByRole("heading", { level: 2, name: "On this browser", exact: true }).waitFor();
    await main.locator("[data-recipe-library]").waitFor();
    region("on this browser");

    if (backend === "3.17") {
      const note = presets.locator('[data-needs-integration="Presets"]');
      await note.waitFor();
      assert.match(await note.innerText(), /Needs integration 3\.18/, `${label}: note`);
      assert.match(await main.locator(".plan-draft-bar").innerText(), /Arm at lights-on/, `${label}: plan still works`);
      await shoot("full");
      region("needs integration note");
      return;
    }

    // The head: state chip and the existing arm flow, named by the next lights-on.
    const tomorrow = new Date(pinned.getTime() + 86_400_000).toLocaleDateString("en-GB", { weekday: "short" });
    assert.equal(await main.locator(".plan-head .plan-state").innerText(), "Draft", `${label}: chip`);
    const bar = main.locator(".plan-draft-bar");
    assert.equal(await bar.innerText(), `Saved · not live yet\nArm at lights-on, ${tomorrow} 10:00`, `${label}: bar`);
    region("plan head");

    // One typed balance: a one-edit draft, then discarded.
    await openTab("Steering balance");
    const cell = main.getByRole("textbox", { name: "Zone 1, week 2, steering balance percent generative" });
    await cell.fill("81");
    await cell.press("Enter");
    await bar.getByText("Draft · 1 edit, not live yet", { exact: true }).waitFor();
    await bar.getByRole("button", { name: "Review & save", exact: true }).waitFor();
    region("draft bar");
    await bar.getByRole("button", { name: "Discard draft", exact: true }).click();
    await bar.getByText("Saved · not live yet", { exact: true }).waitFor();

    // An exception on one day.
    const add = main.getByRole("button", { name: /^Add exception on day \d+$/ });
    const day = Number((await add.innerText()).match(/\d+$/)[0]);
    await add.click();
    const dayCell = main.getByRole("textbox", { name: `Zone 1, day ${day}, steering balance percent generative` });
    await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label")?.includes(", day "));
    await dayCell.fill("90");
    await dayCell.press("Enter");
    const exception = main.locator(".plan-exception");
    await exception.waitFor();
    assert.match(await exception.innerText(), new RegExp(`^EXCEPTION · IN DRAFT\\s+Day ${day}: 90% generative`, "i"), `${label}: exception`);
    await shoot("draft");
    region("exception in draft");
    await bar.getByRole("button", { name: "Discard draft", exact: true }).click();
    await bar.getByText("Saved · not live yet", { exact: true }).waitFor();

    // Presets: the controller's list.
    assert.match(await presets.innerText(), /Stored on the controller: the same list on every phone and PC/);
    const cards = presets.locator(".preset-card");
    await page.waitForFunction(() => document.querySelectorAll(".preset-card").length === 3);
    assert.deepEqual(await cards.locator("b").allInnerTexts(), ["Room A plan", "Room B generative push", "Zone 3 day timer"]);
    assert.equal(await cards.first().getAttribute("aria-pressed"), "true");
    assert.match(await cards.first().innerText(), /Running in Room A · its live settings/);
    region("preset cards");
    await presets.getByRole("button", { name: "Save Room A plan as a new preset" }).click();
    await presets.getByLabel("Preset name").fill("Room A week 6");
    await presets.getByRole("button", { name: "Save preset", exact: true }).click();
    await presets.getByText("Saved “Room A week 6” on the controller.").waitFor();
    await page.waitForFunction(() => document.querySelectorAll(".preset-card").length === 4);
    region("save preset");

    // Copy to Room B: pick, preview, copy, receipt, Undo.
    const pick = async (room, source) => {
      await presets.getByRole("button", { name: /^Pick (a|another) room$/ }).click();
      const tree = page.locator(phone ? "dialog.room-tree-sheet .room-tree[data-picking]" : "aside.desktop-sidebar .room-tree[data-picking]");
      await tree.waitFor();
      assert.equal(await tree.locator(`[data-room="${source}"]`).count(), 0, `${label}: the source room is not offered`);
      // The page owns the pick: the box shows ticked once the page has it (not within the click).
      const box = tree.locator(`label.room-tree-row[data-room="${room}"] input`);
      await box.click();
      await page.waitForFunction((el) => el.checked, await box.elementHandle());
      await tree.getByRole("button", { name: "Done" }).click();
    };
    await pick("room:room_b_", "room:");
    const review = presets.getByRole("region", { name: "Review and apply" });
    await review.waitFor();
    assert.match(await review.innerText(), /Peak VWC target\s+66%\s+→\s+70%/, `${label}: diff row`);
    assert.equal(await review.locator(".review-apply-rows s").count(), 3, `${label}: old values struck`);
    assert.equal(
      await presets.locator(".preset-not-copied").innerText(),
      "Not copied: P2 dilute ratio (Room B has no such setting)",
      `${label}: not copied`,
    );
    region("copy preview");
    await shoot("preview");
    await review.getByRole("button", { name: "Copy 3 changes to Room B", exact: true }).click();
    const receipt = review.locator(".review-apply-receipt");
    await receipt.waitFor();
    assert.match(await receipt.innerText(), /Written and read back 14:10/, `${label}: read back`);
    assert.match(await receipt.innerText(), /Not copied: P2 dilute ratio \(Room B has no such setting\)\./, `${label}: receipt names it`);
    assert.match(await receipt.innerText(), /Controller confirmed every value written/, `${label}: no full-copy claim`);
    assert.doesNotMatch(await receipt.innerText(), /Undo not available/, `${label}: Undo by event ids`);
    await shoot("copied");
    region("copy receipt");
    await receipt.getByRole("button", { name: "Undo: write back the previous values" }).click();
    await review.getByText(/^Previous values written back 14:10$/).waitFor();
    region("undo");

    // From Room B to Room A: Room B has no timer programs.
    if (!phone) {
      await page.locator('aside.desktop-sidebar .room-tree [data-room="room:room_b_"] .room-tree-row').first().click();
      await main.getByRole("heading", { level: 2, name: "Room B grow plan", exact: true }).waitFor();
      await pick("room:", "room:room_b_");
      const fromB = main.locator(".presets-panel").getByRole("region", { name: "Review and apply" });
      await fromB.waitFor();
      assert.equal(
        await main.locator(".preset-not-copied").innerText(),
        "Not copied: Timer programs (source room has no timer programs)",
      );
      await fromB.getByRole("button", { name: /^Copy \d+ changes? to Room A$/ }).click();
      const done = fromB.locator(".review-apply-receipt");
      await done.waitFor();
      assert.match(await done.innerText(), /Not copied: Timer programs \(source room has no timer programs\)\./);
      assert.equal(await done.getByRole("button", { name: /^Undo/ }).count(), 0, `${label}: nothing to undo by id`);
      assert.match(await done.innerText(), /Undo not available here: put the written values back from History\./);
      assert.equal(await done.getByRole("link", { name: "Open History › Changes" }).getAttribute("href"), "#/history/changes");
      await shoot("from-room-b");
      region("not copied receipt");
    }
  },
});
console.log(
  "PASS: I4 grow plan & presets (head + Arm at lights-on, one-edit draft bar + discard, exception in draft, controller presets + save, tree pick without the source room, preview with struck values + not copied, copy read back + not copied named + undo, Room B timers not copied without undo, On this browser recipes, 3.17 note; clock pinned 14:10)",
);
