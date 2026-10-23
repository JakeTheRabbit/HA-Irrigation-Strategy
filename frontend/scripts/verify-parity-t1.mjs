/** T1 Alert rules (mockups 19 and 27), against frontend/dist: run after `vite build`. Opens
 * #/settings/alerts in the demo: five rules over Room A and Room B (zone 3's back EC probe silent and
 * firing, zone 2 EC fired today, Room B's heartbeat last fired three days ago, Room B zone 1 flow with
 * no meter, Part B stock off and under its 6 L). Rule pushes reach Phone 1, the one phone ticked for
 * Sensors.
 *
 * The clock is pinned to today 14:10 local, so the demo day is the same at any real hour.
 *
 * Interactions asserted, at 1440 and 390:
 * - 3.18: Your rules: "5 rules · 4 on", each row's server sentence and status (firing, fired today,
 *   last fired, never, off and would fire now), and Room B's flow "isn't reporting" in place;
 * - 3.18: the builder (phone: New rule opens it, its choices are native selects; desktop: listboxes);
 * - 3.18: Threshold 40 → the replay's sentence changes within 1 s; ArrowUp on the threshold line
 *   moves it by 0.1 and the sentence's number follows;
 * - 3.18: Send a test push → "Delivered to Phone 1 ✓.";
 * - 3.18: Save → "Written and read back HH:MM" and a sixth row;
 * - 3.18: Edit the Off Part B rule, save → "Saved (off). Written and read back HH:MM."; editing
 *   again hides that receipt, putting the written value back shows it;
 * - 3.18: the On switch applies at once with Undo; Undo puts it back, read back;
 * - 3.18 phone: the On switch and the threshold line are 44 px touch targets; the line is a vertical
 *   slider;
 * - 3.17: "Needs integration 3.18" (Your own alert rules) in the builder on desktop and under Your
 *   rules on phone, and the list says Home Assistant has no rule sensors yet.
 * Also writes full-page light and dark screenshots of each run beside the harness's own. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const out = (name) =>
  new URL(`../../output/playwright/parity/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

await runParity({
  id: "t1",
  route: "/settings/alerts",
  mockup: "19-T1-AlertRules.png",
  phoneMockup: "27-P4-Rule.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const phone = width <= 720;
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    const main = page.locator("main");
    await main.getByRole("heading", { level: 1, name: "Alert rules", exact: true }).waitFor();
    const shoot = async (name) => {
      for (const scheme of ["light", "dark"]) {
        await page.emulateMedia({ colorScheme: scheme });
        await page.screenshot({ path: out(`t1-${name}-${width}-${backend}-${scheme}.png`), fullPage: true, animations: "disabled" });
      }
      await page.emulateMedia({ colorScheme: "light" });
      await page.waitForTimeout(500);
    };

    if (backend === "3.17") {
      // On phone the builder is not reachable, so the note sits under Your rules.
      const note = main.locator('[data-needs-integration="Your own alert rules"]');
      await note.waitFor();
      assert.equal(await note.count(), 1, `${label}: one note`);
      assert.match(await note.innerText(), /Needs integration 3\.18/, `${label}: note`);
      if (phone) assert.equal(await main.locator('.ar-list [data-needs-integration="Your own alert rules"]').count(), 1, `${label}: note under Your rules`);
      region("needs integration note");
      await main.getByText("No alert rules in Home Assistant yet.").waitFor();
      region("legacy rule sensors");
      await shoot("full");
      return;
    }

    // Your rules.
    const rows = main.locator(".ar-row");
    await rows.first().waitFor();
    assert.equal(await rows.count(), 5, `${label}: five rules`);
    assert.equal(await main.locator(".ar-list-head small").innerText(), "5 rules · 4 on");
    const status = async (i) => rows.nth(i).locator("[data-status]").innerText();
    assert.match(await rows.nth(0).locator(".ar-sentence").innerText(), /^Tell when Room A Zone 3 back EC silence stays above 30 min for 5 min\.$/);
    assert.match(await status(0), /^Firing now · since \d{2}:\d{2}$/, `${label}: firing`);
    assert.match(await status(1), /^Fired \d{2}:\d{2} today$/, `${label}: fired today`);
    assert.match(await status(2), /^Last fired [A-Z][a-z]{2} \d{2}:\d{2}$/, `${label}: last fired`);
    assert.equal(await status(3), "Never fired", `${label}: never`);
    assert.equal(
      await rows.nth(3).locator(".ar-silent").innerText(),
      "Room B Zone 1 flow isn't reporting. This rule can't fire until it does.",
      `${label}: not reporting`,
    );
    assert.equal(await status(4), "Off · would fire now (5.4 L)", `${label}: off would fire`);
    if (phone) {
      const box = await rows.first().getByRole("switch").boundingBox();
      assert.ok(box && box.height >= 44 && box.width >= 44, `${label}: switch 44 px (${box?.width}x${box?.height})`);
    }
    region("your rules");
    if (!phone) await shoot("full");

    // The builder.
    if (phone) {
      await main.getByRole("button", { name: "New rule", exact: true }).click();
      await main.getByRole("heading", { level: 1, name: "New alert rule" }).waitFor();
    }
    const rule = main.getByRole("group", { name: "Rule" });
    if (phone) {
      for (const name of ["When", "Is", "When it counts"])
        assert.equal(await rule.locator(`select[aria-label="${name}"]`).count(), 1, `${label}: native ${name}`);
    } else assert.equal(await rule.locator("select").count(), 0, `${label}: listbox tokens on desktop`);
    assert.equal(await rule.getByRole("link", { name: "Phone 1" }).getAttribute("href"), "#/settings/notifications");
    region("sentence builder");

    const sentence = main.locator("[data-replay-sentence]");
    await page.waitForFunction(() => (document.querySelector("[data-replay-sentence]")?.textContent ?? "").length > 0);
    const before = await sentence.innerText();
    await rule.locator('input[aria-label="Threshold"]').fill("40");
    const t0 = Date.now();
    await page.waitForFunction((b) => {
      const text = document.querySelector("[data-replay-sentence]")?.textContent ?? "";
      return text && text !== b;
    }, before, { timeout: 1000 });
    assert.ok(Date.now() - t0 < 1000, `${label}: replay within 1 s`);
    region("replay threshold 40");

    const line = main.getByRole("slider", { name: "Threshold" });
    assert.equal(await line.getAttribute("aria-valuenow"), "40");
    await line.focus();
    await page.keyboard.press("ArrowUp");
    // One step: never 40.2.
    assert.notEqual(await line.getAttribute("aria-valuenow"), "40.2", `${label}: ArrowUp 0.1`);
    await page.waitForFunction(() => document.querySelector('[role="slider"][aria-label="Threshold"]')?.getAttribute("aria-valuenow") === "40.1");
    // The sentence's number follows the line.
    await page.waitForFunction(() => document.querySelector('input[aria-label="Threshold"]')?.value === "40.1");
    assert.equal(await line.getAttribute("aria-orientation"), "vertical");
    if (phone) {
      const box = await line.boundingBox();
      assert.ok(box && box.height >= 44, `${label}: threshold line 44 px (${box?.height})`);
    }
    region("threshold line");
    if (phone) await shoot("builder");

    // A test push.
    await main.getByRole("button", { name: phone ? "Send test" : "Send a test push to Phone 1" }).click();
    await main.locator("[data-delivery]").waitFor();
    assert.equal(await main.locator("[data-delivery]").innerText(), "Delivered to Phone 1 ✓.", `${label}: delivery`);
    region("test push");

    // Save.
    await main.getByRole("button", { name: phone ? "Save rule" : "Save rule and start watching" }).click();
    const saved = main.locator("[data-save-note]");
    await saved.waitFor();
    assert.match(await saved.innerText(), /Written and read back \d{2}:\d{2}/, `${label}: read back`);
    await main.getByRole("button", { name: "Saved", exact: true }).waitFor();
    if (phone) await main.getByRole("button", { name: "All rules" }).click();
    await page.waitForFunction(() => document.querySelectorAll(".ar-row").length === 6);
    assert.match(await rows.nth(5).locator(".ar-sentence").innerText(), /^Tell when Room A zone 1 VWC stays below 40\.1% for 10 min\.$/);
    region("save new row");

    // Edit the Off rule (Part B stock): its receipt says it is off, not watching; a further edit
    // hides the receipt until the draft holds the written values again.
    await rows.nth(4).getByRole("button", { name: /^Edit: / }).click();
    if (phone) await main.getByRole("heading", { level: 1, name: "Edit alert rule" }).waitFor();
    const threshold = rule.locator('input[aria-label="Threshold"]');
    // The builder holds Part B (6 L) before it is edited.
    await page.waitForFunction(() => document.querySelector('input[aria-label="Threshold"]')?.value === "6");
    await threshold.fill("7");
    await main.getByRole("button", { name: phone ? "Save rule" : "Save changes" }).click();
    await saved.waitFor();
    assert.match(await saved.innerText(), /^Saved \(off\)\. Written and read back \d{2}:\d{2}\.$/, `${label}: off receipt`);
    await threshold.fill("8");
    await saved.waitFor({ state: "detached" });
    await threshold.fill("7");
    await saved.waitFor();
    if (phone) await main.getByRole("button", { name: "All rules" }).click();
    region("off rule receipt");

    // The On switch, then Undo.
    const toggle = rows.nth(1).getByRole("switch");
    assert.equal(await toggle.getAttribute("aria-checked"), "true");
    await toggle.click();
    const off = page.locator("[data-sonner-toast]").filter({ hasText: /^Rule off: Tell when Room A zone 2 EC/ });
    await off.waitFor();
    assert.equal(await toggle.getAttribute("aria-checked"), "false", `${label}: switched off`);
    await off.getByRole("button", { name: "Undo" }).click();
    await page.locator("[data-sonner-toast]").filter({ hasText: /^Switch put back\. Written and read back/ }).waitFor();
    await page.waitForFunction(() => document.querySelectorAll(".ar-row")[1]?.querySelector('[role="switch"]')?.getAttribute("aria-checked") === "true");
    region("toggle undo");
    await shoot("after");
  },
});
