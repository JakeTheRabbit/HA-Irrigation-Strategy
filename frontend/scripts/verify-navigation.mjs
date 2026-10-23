/** Demo-only navigation and landing regression checks. Set DASHBOARD_URL for a packaged build. */
import assert from "node:assert/strict";
import { chromium } from "playwright";
const entry = new URL(process.env.DASHBOARD_URL || "http://127.0.0.1:5270/");
entry.search = "?demo=1";
entry.hash = "";
const browser = await chromium.launch({
  headless: true,
  ...(process.platform === "win32" ? { channel: "chrome" } : {}),
});
const page = await browser.newPage({ viewport: { width: 1512, height: 1100 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.route("**/*", (route) => {
  const url = new URL(route.request().url());
  return url.origin !== entry.origin || url.pathname.startsWith("/api/")
    ? route.abort()
    : route.continue();
});
const open = async (hash = "") => {
  const url = new URL(entry);
  url.hash = hash;
  await page.goto(url.href);
};
try {
  await open();
  await page.getByRole("heading", { name: "All rooms", exact: true }).waitFor();
  assert.ok((await page.locator("[data-facility-room]").count()) >= 2);
  assert.ok((await page.locator("[data-facility-zone]").count()) >= 6);
  const room = page.locator("[data-facility-room]").nth(1);
  const id = await room.getAttribute("data-facility-room");
  await room.locator(".facility-zone").first().click();
  await page.locator("[data-zone-page]").waitFor();
  assert.equal(new URL(page.url()).searchParams.get("room"), id);
  await open("#/settings");
  await page.locator("#landing-view").selectOption("history/water");
  await open();
  await page.getByRole("heading", { name: "Water use", exact: true }).waitFor();
  await open("#/history/timeline?zone=2");
  await page.getByLabel("Timeline zone").selectOption("room");
  await page.waitForTimeout(100);
  assert.equal(await page.getByLabel("Timeline zone").inputValue(), "room");
  await open("#/zone/1");
  await page.locator("#config-manual_override input").first().click();
  await page.evaluate(() => {
    location.hash = "#/history/timeline?zone=2";
  });
  await page.getByRole("dialog").waitFor();
  await page.getByRole("dialog").getByRole("button", { name: "Discard and continue" }).click();
  await page.getByLabel("Timeline zone").waitFor();
  assert.equal(await page.getByLabel("Timeline zone").inputValue(), "2");
  await open("#/settings");
  await page.locator("#landing-view").selectOption("all-zones");
  await open();
  await page.getByRole("heading", { name: "All rooms", exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.deepEqual(errors, []);
  console.log(
    "PASS: all rooms, correct-room details, default preference, direct links, history room filter, protected zone drafts, confirmed zone navigation, mobile width, zero browser errors",
  );
} finally {
  await browser.close();
}
