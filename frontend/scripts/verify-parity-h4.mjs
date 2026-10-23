/** H4 History › Changes (mockup 12), against frontend/dist: run after `vite build`. Opens
 * #/history/changes in the demo (every room on 3.18; the selected Room A's setting log on 3.17).
 *
 * The clock is pinned to today 15:00 local. Room A's seeded changes end at the values the room holds
 * now: Zone 2 maintenance (P2) shot size 3.5% → 4% by You an hour ago, an AI judge change, a Learner change
 * yesterday, MCP, AiGrow and a plan step, and one 9 days back (outside the first week).
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - the heading "Changes", the scope line ("Showing all rooms. …" on 3.18, Room A's log on 3.17),
 *   "k of n changes · last 7 days", day groups as lists of entries with a <time>;
 * - Made by chips with counts; the Learner chip filters the feed (every entry Learner) and sets
 *   `actor=learner` in the address; pressing it again clears it;
 * - Kind chips: on 3.17 every kind but Setpoint is disabled beside a compact "Needs integration 3.18";
 * - choosing an entry fills the SELECTED CHANGE panel (its label, Why, What happened next);
 * - "Revert to 3.5%" puts it back: the receipt reads "Written and read back HH:MM" and a toast
 *   with Undo appears; Undo writes the value back ("Previous value written back");
 * - on a phone the selected row shows the panel's Revert button only, not its own;
 * - "Show the 7 days before" appends the older week (the change 9 days back appears);
 * - #/history/changes?actor=ai opens with AI judge pressed and only AI judge entries;
 * - on #/plan/targets the clock button of a [data-setting-row] opens its popover (only the clock
 *   button is asserted).
 * The harness port is ephemeral (listen 0), so parallel runs do not collide. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const HHMM = String.raw`\d{1,2}:\d{2}(?: [ap]m)?`;

await runParity({
  id: "h4",
  route: "/history/changes",
  mockup: "12-H4-Changes.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const v318 = backend === "3.18";
    const pinned = new Date();
    pinned.setHours(15, 0, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    await page.getByRole("heading", { level: 1, name: "Changes", exact: true }).waitFor();
    const count = page.locator("[data-count]");
    await page.waitForFunction(() => document.querySelector(".changes-feed")?.getAttribute("aria-busy") === "false" && document.querySelectorAll("[data-change]").length > 0, null, { timeout: 20_000 });

    // Scope and count.
    const scope = (await page.locator("[data-changes-scope]").innerText()).replace(/\s+/g, " ").trim();
    if (v318) assert.equal(scope, "Showing all rooms. Pick a room or zone in the room list to narrow it.", `${label}: scope`);
    else assert.match(scope, /^Showing Room A: /, `${label}: scope`);
    assert.equal(await page.locator("[data-changes-backend]").getAttribute("data-changes-backend"), backend, `${label}: backend`);
    const total = Number((await count.innerText()).match(/of (\d+) changes/)[1]);
    assert.match(await count.innerText(), new RegExp(`^${total} of ${total} changes · last 7 days$`), `${label}: count`);
    region("header");
    // 3.17: entries are shown, from the room's setting log.
    assert.ok((await page.locator("[data-change]").count()) >= (v318 ? 6 : 4), `${label}: entries`);
    assert.ok((await page.locator(".changes-day ol.changes-list time").count()) > 0, `${label}: day lists with times`);
    assert.match(await page.locator(".changes-day-title").first().innerText(), /^today · /i, `${label}: today first`);
    region("day groups");

    // Made by chips: Learner filters.
    const madeBy = page.getByRole("group", { name: "Made by" });
    const chips = await madeBy.getByRole("button").allInnerTexts();
    for (const name of ["You", "Learner", "AI judge", ...(v318 ? ["MCP", "AiGrow", "Plan"] : [])])
      assert.ok(chips.some((text) => new RegExp(String.raw`^${name}\s+\d+$`).test(text)), `${label}: chip ${name} in ${chips}`);
    const learner = madeBy.locator('[data-actor="learner"]');
    await learner.click();
    assert.equal(await learner.getAttribute("aria-pressed"), "true");
    assert.match(new URL(page.url()).hash, /[?&]actor=learner\b/, `${label}: actor in address`);
    const learnerChips = await page.locator("[data-change] .changes-chip.is-static").allInnerTexts();
    assert.ok(learnerChips.length > 0 && learnerChips.every((text) => text.trim() === "Learner"), `${label}: only Learner (${learnerChips})`);
    assert.match(await count.innerText(), new RegExp(`^${learnerChips.length} of ${total} changes`), `${label}: filtered count`);
    await learner.click();
    assert.doesNotMatch(new URL(page.url()).hash, /actor=/, `${label}: actor cleared`);
    region("made by chips");

    // Kind chips.
    const kinds = page.getByRole("group", { name: "Kind" });
    if (v318) {
      assert.ok(/^Setpoint\s+\d+$/.test(await kinds.locator('[data-kind="setpoint"]').innerText()), `${label}: setpoint kind`);
      assert.equal(await kinds.locator('[data-kind="plan"]').isDisabled(), false);
    } else {
      assert.equal(await kinds.locator('[data-kind="setpoint"]').isDisabled(), false, `${label}: setpoint enabled`);
      for (const kind of ["plan", "recipe", "setup", "calibration", "alerts"])
        assert.equal(await kinds.locator(`[data-kind="${kind}"]`).isDisabled(), true, `${label}: ${kind} disabled`);
      await kinds.locator(".needs-integration.is-compact").waitFor();
    }
    region("kind chips");

    // Choosing an entry fills the panel.
    const row = page.locator("[data-change]").filter({ has: page.getByRole("button", { name: "Revert to 3.5%" }) }).first();
    await row.locator(".changes-pick").click();
    const id = await row.getAttribute("data-change");
    const panel = page.locator(`[data-selected-change="${id}"]`);
    await panel.waitFor();
    assert.match(new URL(page.url()).hash, new RegExp(`[?&]id=${encodeURIComponent(id).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`), `${label}: id in address`);
    assert.match(await panel.locator(".changes-panel-title").innerText(), /^Maintenance shot size$/, `${label}: panel title`);
    assert.match(await panel.locator("[data-why]").innerText(), /^Pore EC is over its band/, `${label}: why`);
    assert.ok((await panel.locator("[data-next]").innerText()).length > 0, `${label}: what happened next`);
    // Each fact once: a phone's selected row drops its own Revert button for the panel's.
    assert.equal(
      await page.locator(`[data-change="${id}"] > [data-revert]`).count(),
      width > 720 ? 1 : 0,
      `${label}: one Revert button for the selected row`,
    );
    region("selected change");

    // Revert to 3.5%: receipt, then a toast with Undo.
    // The panel carries the put-back (on a phone it opens under the row, which drops its own button).
    const revert = panel.getByRole("button", { name: "Revert to 3.5%" });
    await revert.click();
    const receipt = panel.locator("[data-receipt]");
    await receipt.waitFor();
    assert.match(await receipt.innerText(), new RegExp(`Written and read back ${HHMM}`), `${label}: receipt`);
    const toast = page.locator("[data-sonner-toast]").filter({ hasText: /Written and read back/ });
    await toast.waitFor();
    region("revert receipt");
    await toast.getByRole("button", { name: "Undo" }).click();
    await panel.getByText(new RegExp(`Previous value written back ${HHMM}`)).waitFor();
    region("undo");

    // The 7 days before: only that week is read, and its rows are appended to those shown.
    const shownBefore = await page.locator("[data-change]").count();
    await page.locator("[data-load-older]").click();
    await page.waitForFunction((n) => document.querySelectorAll("[data-change]").length > n, shownBefore);
    region("older week appended");

    // The address opens filtered.
    const url = new URL(page.url());
    url.hash = "#/history/changes?actor=ai";
    await page.goto(url.href);
    await page.reload();
    await page.getByRole("heading", { level: 1, name: "Changes", exact: true }).waitFor();
    await page.locator("[data-change]").first().waitFor({ timeout: 20_000 });
    assert.equal(await page.getByRole("group", { name: "Made by" }).locator('[data-actor="ai"]').getAttribute("aria-pressed"), "true");
    const aiChips = await page.locator("[data-change] .changes-chip.is-static").allInnerTexts();
    assert.ok(aiChips.length > 0 && aiChips.every((text) => text.trim() === "AI judge"), `${label}: only AI judge (${aiChips})`);
    region("address filter");

    // A setting's clock opens its popover.
    url.hash = "#/plan/targets";
    await page.goto(url.href);
    const clockButton = page.locator("[data-setting-row] [data-setting-history]").first();
    await clockButton.waitFor({ timeout: 20_000 });
    await clockButton.click();
    await page.locator(".setting-history").waitFor();
    await page.keyboard.press("Escape");
    region("setting clock popover");

    // Back to the page, one change picked, for the screenshot.
    url.hash = `#/history/changes?id=${encodeURIComponent(id)}`;
    await page.goto(url.href);
    await page.locator(`[data-selected-change="${id}"]`).waitFor({ timeout: 20_000 });
  },
});
console.log("PASS: H4 changes (scope, counts, Learner chip + actor=, kind chips, selected change, Revert to 3.5% receipt + toast + Undo, one Revert per selected row, older week appended, ?actor=ai, setting clock popover; 3.17 from the setting log)");
