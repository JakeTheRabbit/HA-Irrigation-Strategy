/** I2 Current day (mockup 06), against frontend/dist: run after `vite build`. Opens
 * #/plan/targets?zone=1 in the demo (Room A, lights 10:00–22:00).
 *
 * The clock is pinned to today 14:10 local, so the afternoon window is the same at any real hour.
 *
 * Interactions asserted, at 1440 and 390, on 3.18 and 3.17:
 * - the header says "Nothing is sent to the controller until you apply";
 * - "This afternoon, 14:10–22:00" shows Saved (estimated: the demo publishes no projection_app);
 * - ArrowDown on the re-water handle: "1 change · Review & apply" (a phone's "Review 1 change"
 *   opens the sheet), the handle reads "was …% · not applied", and With edits joins Saved;
 * - a reload keeps the unapplied edit (this tab's stored draft);
 * - Apply 1 change: "Written and read back HH:MM" under Last applied, and the draft is gone;
 * - Undo: write back the previous values: "Previous values written back HH:MM" and the re-water
 *   handle holds its old value again (3.18: history_revert of the base target.changed event;
 *   3.17: the old value re-written with read-back).
 * Also writes full-page light and dark screenshots of each run beside the harness's own. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const out = (name) =>
  new URL(`../../output/playwright/parity/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

await runParity({
  id: "i2",
  route: "/plan/targets?zone=1",
  mockup: "06-I2-CurrentDay.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const phone = width <= 720;
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    const main = page.locator("main");
    const handle = main.locator('[data-target-handle="p2_vwc_threshold"]');
    const slider = handle.getByRole("slider", { name: "Re-water point" });
    await slider.waitFor();

    assert.equal(await main.getByText("Nothing is sent to the controller until you apply", { exact: true }).isVisible(), true, `${label}: header`);
    region("header");

    const day = main.locator(".targets-afternoon");
    assert.equal(await day.locator("h3").innerText(), "This afternoon, 14:10–22:00", `${label}: afternoon window`);
    assert.match(await day.locator('[data-afternoon="saved"]').innerText(), /^Saved \(estimated\)\s+\d+ shots? · [\d.]+ (L|gal) per plant$/, `${label}: saved`);
    region("afternoon");

    for (const scheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.screenshot({ path: out(`i2-full-${width}-${backend}-${scheme}.png`), fullPage: true, animations: "disabled" });
    }
    await page.emulateMedia({ colorScheme: "light" });

    // ArrowDown on the re-water handle: one change to review.
    const was = Number(await slider.getAttribute("aria-valuenow"));
    await slider.focus();
    await page.keyboard.press("ArrowDown");
    await page.waitForFunction(() => document.querySelector('[data-target-handle="p2_vwc_threshold"]')?.hasAttribute("data-changed"));
    assert.ok(Number(await slider.getAttribute("aria-valuenow")) < was, `${label}: handle lowered`);
    assert.match(await handle.locator(".target-handle-was").innerText(), new RegExp(`^was ${was}% · not applied$`), `${label}: was line`);
    assert.match(await day.locator('[data-afternoon="edited"]').innerText(), /^With edits\s+\d+ shots? · /, `${label}: with edits`);
    region("handles");

    // The unapplied edit survives a reload (this tab's stored draft).
    await page.reload();
    await slider.waitFor();
    await page.waitForFunction(() => document.querySelector('[data-target-handle="p2_vwc_threshold"]')?.hasAttribute("data-changed"));
    assert.ok(Number(await slider.getAttribute("aria-valuenow")) < was, `${label}: draft kept over a reload`);
    region("draft kept over reload");

    const bar = page.getByRole("region", { name: "Review and apply" });
    if (phone) {
      await page.getByRole("button", { name: "Review 1 change", exact: true }).click();
      await page.locator("dialog.review-apply-sheet[open]").waitFor();
    }
    const sheet = phone ? page.locator("dialog.review-apply-sheet") : bar;
    assert.equal(await sheet.locator(".review-apply-head > b").innerText(), "1 change · Review & apply", `${label}: bar title`);
    assert.match(await sheet.locator(".review-apply-rows li").innerText(), /Re-water point[\s\S]*→[\s\S]*pts · P2 waters when VWC falls to this/, `${label}: row note`);
    if (!phone) await page.screenshot({ path: out(`i2-edit-${width}-${backend}.png`), animations: "disabled" });
    region("review bar");

    await sheet.getByRole("button", { name: "Apply 1 change", exact: true }).click();
    const receipt = bar.locator(".review-apply-receipt");
    await receipt.waitFor();
    assert.match(await receipt.innerText(), /Written and read back \d\d:\d\d/, `${label}: receipt`);
    assert.match(await bar.locator(".review-apply-kicker").innerText(), /^last applied$/i, `${label}: kicker`);
    assert.equal(await handle.locator(".target-handle-was").count(), 0, `${label}: draft applied`);
    const applied = Number(await slider.getAttribute("aria-valuenow"));
    assert.ok(applied < was, `${label}: controller holds the new value`);
    await page.screenshot({ path: out(`i2-applied-${width}-${backend}.png`), animations: "disabled" });
    region("receipt");

    await bar.getByRole("button", { name: "Undo: write back the previous values" }).click();
    await bar.getByText(/^Previous values written back \d\d:\d\d$/).waitFor();
    await page.waitForFunction((value) => Number(document.querySelector('[data-target-handle="p2_vwc_threshold"] [role="slider"]')?.getAttribute("aria-valuenow")) === value, was);
    assert.equal(await handle.locator(".target-handle-was").count(), 0, `${label}: nothing pending after undo`);
    region("undo");
  },
});
console.log("PASS: I2 current day (header, afternoon window, ArrowDown on re-water → 1 change · Review & apply, the draft kept over a reload, apply → Written and read back, undo restores; 3.18 revert and 3.17 re-write; clock pinned 14:10)");
