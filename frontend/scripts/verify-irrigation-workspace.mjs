/** Isolated demo proof for the consolidated Irrigation editor. No HA requests allowed. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";
import { serveDashboard } from "./dashboard-server.mjs";
const served = process.env.IRRIGATION_URL ? null : await serveDashboard();
const origin = process.env.IRRIGATION_URL || served.origin;
const out = new URL("../../output/ui-implementation-2026-10-18/", import.meta.url);
await mkdir(out, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  ...(process.platform === "win32" ? { channel: "chrome" } : {}),
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
page.setDefaultTimeout(10000);
const errors = [],
  requests = [],
  checks = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.route("**/*", (route) => {
  const u = new URL(route.request().url());
  if (u.origin !== origin || u.pathname.startsWith("/api/")) {
    requests.push(u.origin + u.pathname);
    return route.abort();
  }
  return route.continue();
});
async function fresh(view = "targets") {
  await page.goto("about:blank");
  await page.goto(`${origin}/?demo=1#/plan/${view}`);

  await page.locator('.irrigation-canvas [data-planning-line="vwc"]').waitFor();
}
const curve = () => page.locator('.irrigation-canvas [data-planning-line="vwc"]');
const value = () => curve().getAttribute("data-planning-values");
async function oneCanvas() {
  assert.equal(await page.locator("h1:visible").count(), 1);
  assert.equal(
    await page.locator('[aria-label="24-hour phase and setpoint chart"]:visible').count(),
    1,
  );
  assert.equal(
    await page.locator(".irrigation-canvas [data-planning-ec]").getAttribute("display"),
    null,
  );
}
try {
  await fresh();
  await oneCanvas();
  checks.push("One page heading and one visible continuous VWC/EC canvas");
  const input = page.locator('input[id$="zone_1_p1_target_vwc"]');
  const before = await value();
  await input.fill("69");
  await input.blur();
  assert.notEqual(await value(), before);
  await page.getByRole("button", { name: "Calendar", exact: true }).click();
  await page.locator("#steering-balance").waitFor({ state: "visible" });
  await oneCanvas();
  assert.equal(
    await page.getByRole("region", { name: "Grow schedule", exact: true }).isVisible(),
    true,
  );
  const calBefore = await value();
  await page.locator("#steering-balance").fill("33");
  await page.locator("#steering-balance").dispatchEvent("input");
  assert.notEqual(await value(), calBefore);
  checks.push("Calendar balance redraws interpolated schedule reference");
  await page.screenshot({
    path: new URL("irrigation-calendar.png", out).pathname.replace(/^\/([A-Z]:)/, "$1"),
    fullPage: false,
  });
  await page.getByRole("button", { name: /^Current day/ }).click();
  assert.equal(await input.inputValue(), "69");
  await oneCanvas();
  await page.getByRole("button", { name: /^Calendar/ }).click();
  assert.equal(await page.locator("#steering-balance").inputValue(), "33");
  checks.push("Current and schedule drafts survive repeated view switches");
  await page.locator("#irrigation-zone").selectOption("2");
  await page.getByRole("button", { name: /^Current day/ }).click();
  await page.locator('input[id$="zone_2_p1_target_vwc"]').waitFor();
  assert.equal(await page.locator("#irrigation-zone").inputValue(), "2");
  await page.getByRole("button", { name: /^Calendar/ }).click();
  assert.equal(await page.locator("#irrigation-zone").inputValue(), "2");
  checks.push("Shared zone survives switches and follows both editors");
  await fresh("schedule");
  await page.getByRole("button", { name: "Arm plan", exact: true }).click();
  await page.getByRole("button", { name: "Arm for next lights-on", exact: true }).click();
  await page.getByRole("button", { name: "Disarm plan", exact: true }).waitFor();
  assert.equal(await page.locator("#steering-balance").isDisabled(), true);
  checks.push("Arming preserves separate lifecycle and locks schedule editing until disarmed");
  await page.getByRole("button", { name: /^Current day/ }).click();
  await oneCanvas();
  await page.screenshot({
    path: new URL("irrigation-current.png", out).pathname.replace(/^\/([A-Z]:)/, "$1"),
    fullPage: false,
  });
  assert.deepEqual(errors, []);
  assert.deepEqual(requests, []);
  checks.push("No browser errors or external/HA requests");
  await writeFile(
    new URL("irrigation-report.json", out),
    JSON.stringify({ checks, errors, requests }, null, 2),
  );
  console.log(JSON.stringify({ checks, errors, requests }, null, 2));
} finally {
  await browser.close();
  await served?.close();
}
