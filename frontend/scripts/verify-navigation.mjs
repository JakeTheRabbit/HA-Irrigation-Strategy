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
  await room.locator(".facility-zone h3 button").first().click();
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
  // A zone the room does not have says so; it never shows the room's first zone under that address.
  await open("#/zone/99");
  await page.getByText("Zone 99 is not in", { exact: false }).waitFor();
  assert.equal(await page.locator("[data-zone-page]").count(), 0);
  assert.match(await page.title(), /^Zone 99 not in this room/);
  // Every Capabilities link opens its page at the control it names, highlighted and in view.
  await open("#/settings/features");
  await page.locator("a.features-also").first().waitFor();
  const featureLinks = [
    ...new Set(await page.$$eval("a.features-also", (as) => as.map((a) => a.getAttribute("href")))),
  ].filter((href) => href.includes("?feature="));
  assert.ok(featureLinks.length >= 20);
  const missed = [];
  for (const href of featureLinks) {
    await page.goto("about:blank");
    await open(href);
    const id = new URLSearchParams(href.split("?")[1]).get("feature");
    const landed = await page
      .waitForFunction(
        (id) => {
          const el = document.querySelector(`[data-feature-focus="${id}"]`);
          const box = el?.getBoundingClientRect();
          return !!box && box.height > 0 && box.top < innerHeight && box.bottom > 0;
        },
        id,
        { timeout: 3000 },
      )
      .then(() => true)
      .catch(() => false);
    if (!landed) missed.push(href);
  }
  assert.deepEqual(missed, []);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.deepEqual(errors, []);
  console.log(
    "PASS: all rooms, correct-room details, default preference, direct links, missing zone notice, capability links land on their control, history room filter, protected zone drafts, confirmed zone navigation, mobile width, zero browser errors",
  );
} finally {
  await browser.close();
}
