/** User-authored library workflow against the compiled, isolated demo. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
const out = fileURLToPath(new URL("../../output/playwright/", import.meta.url));
await mkdir(out, { recursive: true });
const html = await readFile(new URL("../../www/dashboard.html", import.meta.url));
const server = createServer((req, res) => {
  res.writeHead(200, { "Content-Type": "text/html" });
  res.end(html);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({
  headless: true,
  ...(process.platform === "win32" ? { channel: "chrome" } : {}),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  acceptDownloads: true,
  colorScheme: "dark",
});
// HTTP LAN installations lack randomUUID; keep getRandomValues available.
await context.addInitScript(() =>
  Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true }),
);
const forbidden = [],
  errors = [],
  checks = [];
await context.route("**/*", (route) => {
  const u = new URL(route.request().url());
  if (u.origin !== origin || u.pathname.startsWith("/api/")) {
    forbidden.push(u.href);
    return route.abort();
  }
  return route.continue();
});
const page = await context.newPage();
page.setDefaultTimeout(10000);
page.on("pageerror", (error) => errors.push(error.message));
const library = () => page.locator("[data-recipe-library]");
async function openLibrary() {
  if ((await library().getAttribute("open")) === null)
    await library().locator("summary").first().click();
}
async function downloadPlan(button) {
  const pending = page.waitForEvent("download");
  await button.click();
  return JSON.parse(await readFile(await (await pending).path(), "utf8"));
}
async function check(name, fn) {
  try {
    await fn();
    checks.push({ name, status: "pass" });
    console.log("PASS " + name);
  } catch (error) {
    checks.push({ name, status: "fail", error: error.stack });
    console.error("FAIL " + name + ": " + error.message);
    await page.screenshot({
      path: out + "recipe-failure-" + checks.length + ".png",
      fullPage: true,
    });
  }
}
async function axe(name) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  assert.deepEqual(
    r.violations.map((v) => v.id),
    [],
    name,
  );
}
try {
  await page.goto(origin + "/dashboard.html?demo=1#/grow-plan", { waitUntil: "networkidle" });
  await library().waitFor();
  await check(
    "Named recipes persist without randomUUID; draft replacement retains current dates",
    async () => {
      const initial = await downloadPlan(page.getByRole("button", { name: "Export", exact: true }));
      await openLibrary();
      await page.getByRole("button", { name: "Save current as recipe", exact: true }).click();
      await page.getByLabel("Recipe name", { exact: true }).fill("My saved plan");
      await page
        .getByLabel("Notes (optional)", { exact: true })
        .fill("User-authored example for the browser demo.");
      await page.getByRole("button", { name: "Save to library", exact: true }).click();
      await page.getByRole("dialog").waitFor({ state: "hidden" });
      assert.equal(await library().locator(".recipe-list li").count(), 1);
      const saved = await downloadPlan(
        page.getByRole("button", { name: "Export recipe My saved plan", exact: true }),
      );
      assert.deepEqual(saved.plan, initial.plan);
      await page.locator("#zone-start-date").fill("2026-08-01");
      await page.getByRole("button", { name: "Preview recipe My saved plan", exact: true }).click();
      const load = page.getByRole("button", { name: "Load into local draft", exact: true });
      assert.equal(await load.isDisabled(), true);
      await page
        .getByLabel("Replace the current unsaved planner draft with this recipe.", { exact: true })
        .check();
      await load.click();
      await page.getByRole("dialog").waitFor({ state: "hidden" });
      assert.equal(await page.locator("#zone-start-date").inputValue(), "2026-08-01");
      const loaded = await downloadPlan(page.getByRole("button", { name: "Export", exact: true }));
      assert.deepEqual(loaded.plan.profiles, initial.plan.profiles);
      assert.deepEqual(
        loaded.plan.zones.map((z) => z.schedule),
        initial.plan.zones.map((z) => z.schedule),
      );
      assert.ok((await page.locator('[data-planning-line="vwc"]').count()) > 0);
      await page.getByRole("button", { name: "Discard draft", exact: true }).click();
      await page.reload({ waitUntil: "networkidle" });
      await openLibrary();
      assert.equal(await library().locator(".recipe-list li").count(), 1);
      await axe("recipe library desktop");
      await page.evaluate(() => {
        document.activeElement?.blur();
        window.scrollTo(0, 0);
      });
      await library().screenshot({
        path: fileURLToPath(new URL("../../img/recipe-library.png", import.meta.url)),
      });
    },
  );
  await check("Library isolates rooms and confirms removal; imports remain local", async () => {
    const exported = await downloadPlan(
      page.getByRole("button", { name: "Export recipe My saved plan", exact: true }),
    );
    await page.locator("#desktop-room").selectOption("room:f1_");
    await library().waitFor();
    await openLibrary();
    assert.equal(await library().locator(".recipe-list li").count(), 0);
    await page.locator("#desktop-room").selectOption("room:");
    await library().waitFor();
    await openLibrary();
    await page.getByRole("button", { name: "Remove recipe My saved plan", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Cancel", exact: true }).click();
    assert.equal(await library().locator(".recipe-list li").count(), 1);
    await page.getByRole("button", { name: "Remove recipe My saved plan", exact: true }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Remove recipe", exact: true })
      .click();
    await library().getByText("No saved recipes yet.", { exact: false }).waitFor();
    await page
      .locator('input[type="file"][aria-label="Import recipe file"]')
      .setInputFiles({
        name: "own-plan.json",
        mimeType: "application/json",
        buffer: Buffer.from(JSON.stringify(exported)),
      });
    await page.getByLabel("Recipe name", { exact: true }).fill("Imported copy");
    await page.getByRole("button", { name: "Save to library", exact: true }).click();
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await axe("recipe library mobile");
    await page.getByRole("button", { name: "Preview recipe Imported copy", exact: true }).click();
    await axe("recipe preview mobile");
    await page.getByRole("button", { name: "Keep current draft", exact: true }).click();
    await page.setViewportSize({ width: 1440, height: 1000 });
  });
  await check("Corrupt browser storage is retained and blocks replacement", async () => {
    const key = "crop-steering.recipe-library.v1:demo:room%3A";
    await page.evaluate((key) => localStorage.setItem(key, "{broken"), key);
    await page.getByRole("button", { name: "Reload library", exact: true }).click();
    await library().getByRole("alert").waitFor();
    assert.equal(
      await page.getByRole("button", { name: "Save current as recipe", exact: true }).isDisabled(),
      true,
    );
    assert.equal(await page.evaluate((key) => localStorage.getItem(key), key), "{broken");
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download stored data", exact: true }).click();
    assert.equal(await readFile(await (await pending).path(), "utf8"), "{broken");
    assert.deepEqual(forbidden, []);
    assert.deepEqual(errors, []);
  });
} finally {
  await writeFile(
    out + "recipe-library-checks.json",
    JSON.stringify({ checks, forbidden, errors }, null, 2),
  );
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
if (checks.some((c) => c.status !== "pass") || errors.length || forbidden.length)
  process.exitCode = 1;
