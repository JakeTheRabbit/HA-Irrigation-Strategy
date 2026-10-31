/** I1 Watering timeline (mockup 05) and P2 phone timeline (mockup 25), against frontend/dist: run
 * after `vite build`. Opens #/plan/watering in the demo (Room A plays F2, Room B F1).
 *
 * The clock is pinned to today 14:10 local, so the demo day is the same at any real hour.
 *
 * Interactions asserted, at 1440 and 390:
 * - 3.18: the day strip ("Today" and the week, each day Done / N problems / Planned) on a desktop,
 *   "Today, <day>" with its failed and warning counts on a phone;
 * - 3.18: 48 h (desktop) or 24 h (phone) updates the hash (`span=48` / `span=24`) and the axis;
 * - 3.18: ←/→ on a focused block moves focus to the next block (↓/↑ on a phone, where time runs down);
 * - 3.18: the failed chip "{n} shot(s) failed" focuses a failed block; on a phone the day line's
 *   "1 failed" (the whole day) widens 12 h to 24 h and focuses the failed block;
 * - 3.18: clicking a planned block opens the popover with "Skip this shot"; skipping shows an Undo
 *   toast and the block reads skipped; Undo puts it back ("… is back on the plan.");
 * - 3.18: the room tree (desktop) picks Room B: the page stays, Room B's row is open and in view;
 * - 3.17: the body note "Needs integration 3.18" shows in place of the timeline, and the room tree
 *   still works (desktop: Room B opens, the note stays).
 * Also writes full-page light and dark screenshots of each run beside the harness's own. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const out = (name) =>
  new URL(`../../output/playwright/parity/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

await runParity({
  id: "i1",
  route: "/plan/watering",
  mockup: "05-I1-Timeline.png",
  phoneMockup: "25-P2-Timeline.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const phone = width <= 720;
    // The demo follows the clock: pin it to today 14:10 local (the mockups' "now"), so Room A's
    // grow-day has its shots, the failed one (13:48) and planned ones ahead at any real hour.
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    const main = page.locator("main");
    await main.getByRole("heading", { level: 1, name: "Timeline", exact: true }).waitFor();
    const tree = page.locator(".room-tree");
    const treeRoom = (id) => tree.locator(`[data-room="${id}"] .room-tree-row`).first();

    if (backend === "3.17") {
      const note = main.locator('[data-needs-integration="The watering timeline"]');
      await note.waitFor();
      assert.match(await note.innerText(), /Needs integration 3\.18/, `${label}: body note`);
      for (const scheme of ["light", "dark"]) {
        await page.emulateMedia({ colorScheme: scheme });
        await page.screenshot({ path: out(`i1-full-${width}-${backend}-${scheme}.png`), fullPage: true, animations: "disabled" });
      }
      await page.emulateMedia({ colorScheme: "light" });
      if (!phone) {
        await treeRoom("room:room_b_").click();
        await main.getByRole("heading", { level: 1, name: "Timeline", exact: true }).waitFor();
        await note.waitFor();
        assert.match(decodeURIComponent(page.url()), /room=(room:)?room_b/, `${label}: the tree picked Room B`);
      }
      region("needs integration note");
      return;
    }

    const timeline = main.locator(".shot-timeline");
    await timeline.locator(".st-block").first().waitFor();
    region("timeline");

    // The day.
    if (phone) {
      const day = main.locator("[data-watering-day]");
      await page.waitForFunction(() => /failed|warning|No problems/.test(document.querySelector("[data-watering-day] span")?.textContent ?? ""));
      assert.match(await day.locator("strong").innerText(), /^Today, \w{3} \d{1,2} \w{3,4}$/, `${label}: today line`);
      // At 14:10: Room A zone 1's aborted shot; Room A zone 2's short shot and Room B's sensor alert.
      assert.equal(await day.locator("span").innerText(), "1 failed · 2 warnings", `${label}: problems line`);
      assert.equal(await timeline.getAttribute("data-orientation"), "vertical", `${label}: vertical`);
      assert.match(await main.locator(".page-heading p").innerText(), /^All rooms · swipe for more$/, `${label}: subtitle`);
    } else {
      const days = main.getByRole("list", { name: "Days" }).getByRole("button");
      assert.equal(await days.count(), 7, `${label}: a week of days`);
      await page.waitForFunction(() => document.querySelector('.wt-week button[aria-pressed="true"] small')?.textContent?.trim());
      assert.match(await main.locator('.wt-week button[aria-pressed="true"] small').innerText(), /^\d+ problems?$/, `${label}: today's problems`);
      assert.equal(await main.locator('.wt-week button[data-tone="planned"]').count(), 3, `${label}: days ahead planned`);
      assert.equal(await main.getByRole("button", { name: "Today", exact: true }).isDisabled(), true, `${label}: Today chosen`);
      await timeline.locator(".st-lights-label").first().waitFor();
      assert.match(await timeline.locator(".st-lights-label").first().innerText(), /^Lights on \d{2}:\d{2}–\d{2}:\d{2}$/);
    }
    region("day strip");

    for (const scheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.screenshot({ path: out(`i1-full-${width}-${backend}-${scheme}.png`), fullPage: true, animations: "disabled" });
    }
    await page.emulateMedia({ colorScheme: "light" });

    // The span updates the address.
    const spans = main.getByRole("group", { name: "Hours shown" });
    const longer = phone ? "24 h" : "48 h";
    await spans.getByRole("button", { name: longer }).click();
    await page.waitForFunction((h) => location.hash.includes(`span=${h}`), phone ? 24 : 48);
    assert.equal(await spans.getByRole("button", { name: longer }).getAttribute("aria-pressed"), "true");
    assert.match(await timeline.locator(".st-head .st-label, .st-vaxis").first().innerText().catch(() => ""), phone ? /.*/ : /· 48 h$/);
    await spans.getByRole("button", { name: phone ? "12 h" : "24 h" }).click();
    await page.waitForFunction((h) => location.hash.includes(`span=${h}`), phone ? 12 : 24);
    region("span");

    // Arrow keys move along the blocks.
    const focused = () => page.evaluate(() => document.activeElement?.getAttribute("data-id"));
    const first = timeline.locator('.st-block[tabindex="0"]');
    await first.focus();
    const before = await focused();
    await page.keyboard.press(phone ? "ArrowUp" : "ArrowLeft");
    const moved = await focused();
    if (moved === before) await page.keyboard.press(phone ? "ArrowDown" : "ArrowRight");
    assert.notEqual(await focused(), before, `${label}: an arrow moved focus`);
    assert.ok(await focused(), `${label}: focus on a block`);
    region("keyboard");

    // The failed chip focuses a failed block.
    const failed = main.locator("[data-watering-failed]");
    assert.match(await failed.innerText(), /^1 shot failed$/, `${label}: failed chip`);
    await failed.click();
    await page.waitForFunction(() => document.activeElement?.getAttribute("data-glyph") === "failed");
    region("failed chip");

    // Phone: the day line's "1 failed" counts the whole day; from 12 h it opens 24 h and the
    // failed shot.
    if (phone) {
      assert.match(page.url(), /span=12/, `${label}: 12 h before the tap`);
      await page.evaluate(() => document.activeElement?.blur());
      await main.locator("[data-watering-day-failed]").click();
      await page.waitForFunction(() => location.hash.includes("span=24"));
      assert.equal(await spans.getByRole("button", { name: "24 h" }).getAttribute("aria-pressed"), "true");
      await page.waitForFunction(() => document.activeElement?.getAttribute("data-glyph") === "failed");
      region("phone failed count");
    }

    // A planned block: Skip this shot, Undo.
    const planned = timeline.locator('.st-block[data-glyph="planned"]:not([data-skipped]), .st-block[data-glyph="expected"]:not([data-skipped])').first();
    const id = await planned.getAttribute("data-id");
    await planned.click();
    const pop = page.locator("[data-watering-popover]");
    await pop.waitFor();
    assert.match(await pop.locator(".wt-pop-status").innerText(), /^(Planned|Expected)/, `${label}: popover status`);
    assert.match(await pop.innerText(), /Open Room [AB] Zone \d/, `${label}: open zone link`);
    await page.screenshot({ path: out(`i1-popover-${width}.png`), animations: "disabled" });
    await pop.getByRole("button", { name: "Skip this shot" }).click();
    const toast = page.locator("[data-sonner-toast]").filter({ hasText: /^Skipped Room [AB] Zone \d/ });
    await toast.waitFor();
    await page.waitForFunction((blockId) => document.querySelector(`.st-block[data-id="${blockId}"]`)?.hasAttribute("data-skipped"), id);
    await toast.getByRole("button", { name: "Undo" }).click();
    await page.locator("[data-sonner-toast]").filter({ hasText: "is back on the plan." }).waitFor();
    await page.waitForFunction((blockId) => {
      const block = document.querySelector(`.st-block[data-id="${blockId}"]`);
      return block && !block.hasAttribute("data-skipped");
    }, id);
    region("popover skip undo");

    // The room tree picks Room B: the page stays, its row is open.
    if (!phone) {
      await spans.getByRole("button", { name: "48 h" }).click();
      await treeRoom("room:room_b_").click();
      await main.getByRole("heading", { level: 1, name: "Timeline", exact: true }).waitFor();
      // The pick keeps the page's choices: the address keeps its query.
      assert.equal(await spans.getByRole("button", { name: "48 h" }).getAttribute("aria-pressed"), "true", `${label}: 48 h kept`);
      assert.match(new URL(page.url()).hash, /^#\/plan\/watering\?(.*&)?span=48(&|$)/, `${label}: the address keeps span=48`);
      const toggle = main.getByRole("button", { name: /^(Collapse|Expand) Room B$/ });
      await toggle.waitFor();
      assert.equal(await toggle.getAttribute("aria-expanded"), "true", `${label}: Room B open`);
      region("room tree");
    }
  },
});
console.log("PASS: I1 watering timeline (day strip, span hash, arrow keys, failed chip, phone failed count opens 24 h, skip + undo, room tree keeps choices and the address query, 3.17 note; clock pinned 14:10)");
