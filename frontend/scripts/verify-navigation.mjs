/** Demo-only navigation and landing regression checks against the compiled demo (frontend/dist,
 * built by `vite build`), served on an ephemeral 127.0.0.1 port. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile } from "node:fs/promises";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
const html = await readFile(new URL("../dist/index.html", import.meta.url));
const out = new URL("../../output/playwright/", import.meta.url);
const file = (name) => new URL(name, out).pathname.replace(/^\/([A-Za-z]:)/, "$1");
await mkdir(out, { recursive: true });
const server = createServer((req, res) => {
  res.writeHead(200, { "Content-Type": "text/html" });
  res.end(html);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const entry = new URL(`http://127.0.0.1:${server.address().port}/dashboard.html?demo=1`);
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
  assert.equal(pages.length, 20);
  assert.equal(new Set(pages).size, 20);
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
  await page.screenshot({ path: file("nav-tree-1440.png") });

  // The old checks: all rooms, room address, landing preference, direct links, zone drafts.
  await open("#/all-zones");
  assert.ok((await page.locator("[data-facility-room]").count()) >= 2);
  assert.ok((await page.locator("[data-facility-zone]").count()) >= 6);
  const room = page.locator("[data-facility-room]").nth(1);
  const id = await room.getAttribute("data-facility-room");
  await room.locator(".facility-zone-head button").first().click();
  await page.locator("[data-zone-page]").waitFor();
  assert.equal(new URL(page.url()).searchParams.get("room"), id);
  await open("#/settings");
  await page.locator("#landing-view").selectOption("history/water");
  await open();
  await page.getByRole("heading", { name: "Water use", exact: true }).waitFor();
  await open("#/history/timeline?zone=2");
  await page.waitForURL((url) => url.hash === "#/history/explorer?zone=2");
  await page.getByLabel("Timeline zone").selectOption("room");
  await page.waitForTimeout(100);
  assert.equal(await page.getByLabel("Timeline zone").inputValue(), "room");
  await open("#/zone/1");
  await page.locator("#config-manual_override input").first().click();
  await page.evaluate(() => {
    location.hash = "#/history/explorer?zone=2";
  });
  await page.getByRole("dialog").waitFor();
  await page.getByRole("dialog").getByRole("button", { name: "Discard and continue" }).click();
  await page.getByLabel("Timeline zone").waitFor();
  assert.equal(await page.getByLabel("Timeline zone").inputValue(), "2");
  await open("#/settings");
  await page.locator("#landing-view").selectOption("all-zones");
  await open();
  await page.getByRole("heading", { name: "All rooms", exact: true }).waitFor();

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
  await page.screenshot({ path: file("nav-tree-390.png") });
  assert.deepEqual(errors, []);
  console.log(
    "PASS: tree menu (5 sections, 20 pages), Changes aria-current + address, open state survives reload, keyboard, tabs hidden at 1440 and shown at 390, 5-button bottom bar, axe clean, all rooms, correct-room details, default preference, direct and old links, history room filter, protected zone drafts, mobile width, zero browser errors",
  );
} finally {
  await browser.close();
  server.close();
}
