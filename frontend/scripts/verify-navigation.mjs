/** Demo-only navigation and landing regression checks. Serves the compiled www/dashboard.html itself
 * (dashboard-server.mjs); set DASHBOARD_URL to test another server. */
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { serveDashboard } from "./dashboard-server.mjs";
const out = new URL("../../output/playwright/", import.meta.url);
const file = (name) => new URL(name, out).pathname.replace(/^\/([A-Za-z]:)/, "$1");
await mkdir(out, { recursive: true });
const served = process.env.DASHBOARD_URL ? null : await serveDashboard();
const entry = new URL(process.env.DASHBOARD_URL || `${served.origin}/dashboard.html`);
entry.search = "?demo=1";
entry.hash = "";
const browser = await chromium.launch({
  headless: true,
  ...(process.platform === "win32" ? { channel: "chrome" } : {}),
});
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
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
const tree = page.locator('.desktop-sidebar nav[aria-label="Main navigation"]');
try {
  await open();
  await page.getByRole("heading", { name: "All rooms", exact: true }).waitFor();

  // The tree: five sections in order, every sub-page once.
  assert.deepEqual(
    await tree.locator("[data-nav-section]").evaluateAll((els) => els.map((e) => e.textContent.trim())),
    ["Status", "Irrigation", "History", "Equipment", "Settings"],
  );
  for (const section of ["plan", "history", "equipment", "settings"])
    await tree.locator(`button[data-nav-section="${section}"]`).click();
  const pages = await tree
    .locator("[data-nav-page]")
    .evaluateAll((els) => els.map((e) => e.getAttribute("data-nav-page")));
  assert.equal(pages.length, 21);
  assert.equal(new Set(pages).size, 21);
  for (const section of ["plan", "equipment", "settings"])
    await tree.locator(`button[data-nav-section="${section}"]`).click();
  await page.evaluate(() => localStorage.removeItem("crop-steering.nav-open"));
  await page.reload();
  assert.equal(
    await tree.locator('button[data-nav-section="history"]').getAttribute("aria-expanded"),
    "false",
  );

  // Clicking Changes marks it current and addresses it.
  await tree.locator('button[data-nav-section="history"]').click();
  await tree.getByRole("link", { name: "Changes", exact: true }).click();
  await page.getByRole("heading", { name: "Changes", exact: true }).waitFor();
  assert.equal(new URL(page.url()).hash, "#/history/changes");
  assert.equal(
    await tree.locator('[data-nav-page="history/changes"]').getAttribute("aria-current"),
    "page",
  );
  assert.equal(await tree.locator('[aria-current="page"]').count(), 1);

  // History stays open after a reload; the other sections stay as they were.
  await page.reload();
  await page.getByRole("heading", { name: "Changes", exact: true }).waitFor();
  assert.equal(
    await tree.locator('button[data-nav-section="history"]').getAttribute("aria-expanded"),
    "true",
  );
  assert.equal(
    await tree.locator('button[data-nav-section="equipment"]').getAttribute("aria-expanded"),
    "false",
  );

  // Keyboard: ↓ from History reaches its first page, ← returns to History, ← again closes it,
  // → opens it, End reaches Settings.
  await tree.locator('button[data-nav-section="history"]').focus();
  await page.keyboard.press("ArrowDown");
  assert.equal(await page.evaluate(() => document.activeElement?.dataset.navPage), "history/explorer");
  await page.keyboard.press("ArrowLeft");
  assert.equal(await page.evaluate(() => document.activeElement?.dataset.navSection), "history");
  await page.keyboard.press("ArrowLeft");
  assert.equal(
    await tree.locator('button[data-nav-section="history"]').getAttribute("aria-expanded"),
    "false",
  );
  await page.keyboard.press("ArrowRight");
  assert.equal(
    await tree.locator('button[data-nav-section="history"]').getAttribute("aria-expanded"),
    "true",
  );
  await page.keyboard.press("End");
  assert.equal(await page.evaluate(() => document.activeElement?.dataset.navSection), "settings");
  await page.keyboard.press("Home");
  assert.equal(await page.evaluate(() => document.activeElement?.dataset.navSection), "today");

  // Only the current section opens by itself, and it closes again when the grower moves on;
  // a section the grower opened stays open, across pages and reloads.
  const expanded = async (section) =>
    tree.locator(`button[data-nav-section="${section}"]`).getAttribute("aria-expanded");
  await page.evaluate(() => localStorage.removeItem("crop-steering.nav-open"));
  await page.reload();
  await page.getByRole("heading", { name: "Changes", exact: true }).waitFor();
  assert.equal(await expanded("history"), "true", "the current section opens by itself");
  await tree.locator('button[data-nav-section="settings"]').click();
  await tree.locator('button[data-nav-section="equipment"]').click();
  await tree.getByRole("link", { name: "Stock", exact: true }).click();
  await page.waitForURL((url) => url.hash === "#/equipment/stock");
  assert.equal(await expanded("history"), "false", "History closes when the grower leaves it");
  assert.equal(await expanded("settings"), "true", "an opened section stays open");
  await tree.getByRole("link", { name: "Probes & offsets", exact: true }).click();
  await page.waitForURL((url) => url.hash === "#/equipment/probes");
  assert.equal(await expanded("settings"), "true");
  await page.reload();
  await page.locator('[data-nav-page="equipment/probes"][aria-current="page"]').waitFor();
  assert.deepEqual(
    await Promise.all(["plan", "history", "equipment", "settings"].map(expanded)),
    ["false", "false", "true", "true"],
    "a reload keeps only the sections the grower opened",
  );
  // The current section can still be collapsed.
  await tree.locator('button[data-nav-section="equipment"]').click();
  assert.equal(await expanded("equipment"), "false");
  await tree.locator('button[data-nav-section="history"]').click();

  // Desktop hides the in-page tabs; axe passes on the tree.
  assert.equal(await page.locator(".page-tabs").isVisible(), false);
  const audit = await new AxeBuilder({ page })
    .include('.desktop-sidebar nav[aria-label="Main navigation"]')
    .analyze();
  assert.deepEqual(
    audit.violations.map((v) => ({ id: v.id, impact: v.impact })),
    [],
    "tree menu accessibility",
  );
  await tree.locator('button[data-nav-section="equipment"]').click();
  await page.screenshot({ path: file("nav-tree-1440.png"), animations: "disabled" });

  // The old checks: all rooms, room address, landing preference, direct links, zone drafts.
  await open("#/all-zones");
  assert.ok((await page.locator("[data-facility-room]").count()) >= 2);
  assert.ok((await page.locator("[data-facility-zone]").count()) >= 6);
  const room = page.locator("[data-facility-room]").nth(1);
  const id = await room.getAttribute("data-facility-room");
  await room.locator(".facility-zone-head a").first().click();
  await page.locator("[data-zone-page]").waitFor();
  assert.equal(new URL(page.url()).searchParams.get("room"), id);
  await open("#/settings");
  await page.locator("#landing-view").selectOption("history/water");
  await open();
  await page.getByRole("heading", { level: 1, name: "Water & flow", exact: true }).waitFor();
  await open("#/history/timeline?zone=2");
  await page.waitForURL((url) => url.hash === "#/history/explorer?zone=2");
  // The old timeline link opens the Explorer on zone 2's detail; the room list is the zone picker.
  await page.locator('[data-zone-detail="2"]').waitFor();
  await open("#/history/explorer");
  await page.locator(".explorer-zone-hint").waitFor();
  assert.equal(await page.locator("[data-zone-detail]").count(), 0);
  await open("#/zone/1");
  await page.locator("#config-manual_override input").first().click();
  await page.evaluate(() => {
    location.hash = "#/history/explorer?zone=2";
  });
  await page.getByRole("dialog").waitFor();
  await page.getByRole("dialog").getByRole("button", { name: "Discard and continue" }).click();
  await page.locator('[data-zone-detail="2"]').waitFor();
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
    // Keyboard focus moves to it, and a screen reader hears where the page opened.
    else if (
      !(await page.evaluate((id) => {
        const el = document.querySelector(`[data-feature-focus="${id}"]`);
        return !!el && (el === document.activeElement || el.contains(document.activeElement));
      }, id))
    )
      missed.push(`${href} (focus)`);
  }
  assert.deepEqual(missed, []);
  assert.match(await page.locator("#feature-announce").innerText(), /^Opened at /);
  // Only the ?feature= part changing, on the same page, lands again: room scope included.
  for (const [from, to] of [
    ["#/settings?feature=water_today_view", "manual_hardware_enabled"],
    ["#/plan/targets?feature=p0", "photoperiod"],
    ["#/equipment/setup?feature=daily_limits", "source_gate"],
  ]) {
    await page.goto("about:blank");
    await open(from);
    await page.locator("[data-feature-focus]").waitFor();
    await page.evaluate((hash) => (location.hash = hash), `${from.split("?")[0]}?feature=${to}`);
    await page.locator(`[data-feature-focus="${to}"]`).waitFor({ timeout: 3000 });
  }

  // Phone: the in-page tabs show, the bottom bar keeps five sections, nothing overflows.

  await page.setViewportSize({ width: 390, height: 844 });
  await open("#/history/changes");
  await page.getByRole("heading", { name: "Changes", exact: true }).waitFor();
  assert.equal(await page.locator(".page-tabs").isVisible(), true);
  assert.equal(await page.locator(".bottom-nav button").count(), 5);
  await page.locator(".bottom-nav button").nth(1).click();
  assert.equal(new URL(page.url()).hash, "#/plan/watering");
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.locator('.mobile-sidebar nav[aria-label="Main navigation"]').waitFor();
  await page.waitForTimeout(300);
  await page.screenshot({ path: file("nav-tree-390.png"), animations: "disabled" });
  assert.deepEqual(errors, []);
  console.log(
    "PASS: tree menu (5 sections, 21 pages), Changes aria-current + address, only the current and grower-opened sections expand (left sections close; opened ones survive navigation and reload), keyboard, tabs hidden at 1440 and shown at 390, 5-button bottom bar, axe clean, all rooms, correct-room details, default preference, direct and old links, missing zone notice, capability links land on their control, explorer zone pick, protected zone drafts, mobile width, zero browser errors",
  );
} finally {
  await browser.close();
  await served?.close();
}
