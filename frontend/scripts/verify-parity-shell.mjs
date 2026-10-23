/** Shell: the top bar and the jump-to palette (Task 30; mockups 03 at 1440 and 24 at 390), against
 * frontend/dist: run after `vite build`. Runs on the shared parity harness (parity-harness.mjs).
 *
 * The clock is pinned to today 14:10 local.
 *
 * Interactions asserted, on both backends (`?demo=1` and `?demo=1&backend=3.17`):
 * - 1440: the header reads "Updated N s ago", the AI chip, "Jump to… Ctrl K", the room's name as
 *   plain text, "Watering on" and "Stop all", in that order; no room chip buttons;
 * - 1440: with focus on a button of the room page, Ctrl K → type "changes" → Enter opens
 *   #/history/changes (heading "Changes"); that button left with its page, so focus lands on the
 *   Jump to… button;
 * - 1440: the Jump to… button opens the palette, Escape closes it and focus returns to the button;
 * - 1440: "/" opens it, "cal ph" lists "Calibrate <room> feed pH" first, ArrowDown moves the
 *   active option; a word nothing has says "Nothing matches";
 * - 1440: Ctrl K and "/" do nothing while the Stop all review is open (no stacked palette);
 * - 1440: picking another room's zone opens that room's zone page;
 * - 390: the page title over "Updated N s ago · <AI state>", no Jump to… button, both switches in
 *   words, no horizontal overflow.
 * The harness writes output/playwright/parity/shell-compare.json (screenshot sizes and every region
 * asserted). */
import assert from "node:assert/strict";
import AxeBuilder from "@axe-core/playwright";
import { runParity } from "./parity-harness.mjs";

const UPDATED = /^Updated \d+ (s|min) ago$/;
const focused = (locator) => locator.evaluate((el) => el === document.activeElement);

await runParity({
  id: "shell",
  route: "/today",
  mockup: "03-S2-Room.png",
  phoneMockup: "24-P1-AllRooms.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px backend ${backend}`;
    const base = page.url().replace(/#.*$/, "");
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    const header = page.locator("header.topbar");

    if (width <= 720) {
      // Phone: All rooms, as mockup 24.
      await page.goto(`${base}#/all-zones`);
      await page.reload();
      await header.locator(".data-age").waitFor();
      region("phone top bar");
      assert.equal((await header.locator(".topbar-title").innerText()).trim(), "All rooms");
      const facts = (await header.locator(".topbar-facts").innerText()).replace(/\s+/g, " ").trim();
      assert.match(facts, /^Updated \d+ (s|min) ago · AI \S/, `${label}: ${facts}`);
      assert.equal(await header.getByRole("button", { name: /^Jump to…/ }).isVisible(), false);
      assert.deepEqual(await header.locator(".safety-switch-text").allInnerTexts(), ["Watering on", "Stop all"]);
      await auditHeader(page, label);
      return;
    }

    // Desktop: the room page, as mockup 03.
    await page.reload();
    await header.locator(".data-age").waitFor();
    region("top bar");
    assert.match(await header.locator(".data-age").innerText(), UPDATED, `${label}: data age`);
    const roomName = (await page.getByRole("heading", { level: 1 }).first().innerText()).trim();
    assert.equal(
      (await header.locator(".header-safety-scope").innerText()).trim(),
      roomName,
      `${label}: the room's name beside its switches`,
    );
    const jump = header.getByRole("button", { name: /^Jump to…/ });
    assert.equal((await jump.innerText()).replace(/\s+/g, " ").trim(), "Jump to… Ctrl K");
    // In mockup order: age, AI, Jump to…, room, Watering, Stop all.
    const xs = await Promise.all(
      [
        header.locator(".data-age"),
        header.locator(".brain-chip"),
        jump,
        header.locator(".header-safety-scope"),
        header.getByRole("button", { name: /^Watering on/ }),
        header.getByRole("button", { name: /^Stop all/ }),
      ].map(async (l) => (await l.boundingBox()).x),
    );
    assert.deepEqual([...xs].sort((a, b) => a - b), xs, `${label}: header order ${xs}`);
    region("no room chips");
    assert.equal(await header.locator("[data-room], .room-chip, .room-chips").count(), 0);
    assert.equal(await header.getByRole("group", { name: "Rooms" }).count(), 0);

    // Focus on a room-page button, Ctrl K → "changes" → Enter.
    region("palette: Ctrl K to Changes");
    const palette = page.getByRole("dialog", { name: "Jump to" });
    const field = palette.getByRole("combobox");
    const opener = page.locator("main").getByRole("button").first();
    await opener.focus();
    assert.ok(await focused(opener), `${label}: a room-page button focused`);
    await page.keyboard.press("Control+k");
    await palette.waitFor();
    assert.ok(await focused(field), `${label}: field focused`);
    await field.fill("changes");
    assert.equal((await palette.getByRole("option").first().innerText()).split("\n")[0], "Changes");
    await page.keyboard.press("Enter");
    await palette.waitFor({ state: "hidden" });
    await page.waitForFunction(() => location.hash === "#/history/changes");
    await page.getByRole("heading", { level: 1, name: "Changes", exact: true }).waitFor();
    region("palette: focus after a jump");
    await page.waitForFunction(() => document.activeElement?.classList.contains("jump-to"));
    assert.ok(await focused(jump), `${label}: the opener left with its page; focus on Jump to…`);

    // Jump to… → Escape → focus back on the button.
    region("palette: Escape returns focus");
    await jump.click();
    await palette.waitFor();
    await page.keyboard.press("Escape");
    await palette.waitFor({ state: "hidden" });
    assert.ok(await focused(jump), `${label}: focus back on Jump to…`);

    // "/" opens it; "cal ph" leads with the calibration action.
    region("palette: search");
    await page.locator("main h1").first().click();
    await page.keyboard.press("/");
    await palette.waitFor();
    await field.fill("cal ph");
    const first = palette.getByRole("option").first();
    if (backend === "3.18")
      await page.screenshot({ path: shotPath("shell-palette-1440.png"), animations: "disabled" });
    assert.equal((await first.innerText()).split("\n")[0], `Calibrate ${roomName} feed pH`);
    assert.equal(await first.getAttribute("aria-selected"), "true");
    await page.keyboard.press("ArrowDown");
    assert.equal(await palette.getByRole("option").nth(1).getAttribute("aria-selected"), "true");
    await field.fill("qqqq");
    await palette.getByText("Nothing matches “qqqq”.").waitFor();
    await page.keyboard.press("Escape");
    await palette.waitFor({ state: "hidden" });

    // Over the Stop all review the shortcuts do nothing.
    region("palette: not over another modal");
    await header.getByRole("button", { name: /^Stop all/ }).click();
    const stop = page.getByRole("dialog", { name: /^Stop all water in / });
    await stop.waitFor();
    await page.keyboard.press("Control+k");
    await page.keyboard.press("/");
    assert.equal(await palette.isVisible(), false, `${label}: palette stacked over Stop all`);
    await page.keyboard.press("Escape");
    await stop.waitFor({ state: "hidden" });

    // Another room's zone opens in that room.
    region("palette: another room's zone");
    await jump.click();
    await field.fill("room b zone 2");
    await page.keyboard.press("Enter");
    await page.waitForFunction(() => location.hash === "#/zone/2");
    await page.waitForFunction(() => new URLSearchParams(location.search).get("room") !== null);
    assert.equal((await header.locator(".header-safety-scope").innerText()).trim(), "Room B");
    await page.goto(`${base}#/today`);
    await page.reload();
    await header.locator(".data-age").waitFor();
    await auditHeader(page, label);
  },
});
console.log("verify-parity-shell: 4 views passed.");

async function auditHeader(page, label) {
  const audit = await new AxeBuilder({ page }).include("header.topbar").analyze();
  assert.deepEqual(
    audit.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length })),
    [],
    `${label}: axe violations in the header`,
  );
}

function shotPath(file) {
  const url = new URL(`../../output/playwright/parity/${file}`, import.meta.url);
  return url.pathname.replace(/^\/([A-Za-z]:)/, "$1");
}
