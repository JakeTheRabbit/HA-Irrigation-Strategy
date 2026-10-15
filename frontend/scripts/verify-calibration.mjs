/** The feed-probe two-point calibration flow on Equipment › Probes, against the compiled demo. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
const html = await readFile(new URL("../../www/dashboard.html", import.meta.url));
const out = new URL("../../output/playwright/", import.meta.url);
const file = (name) => new URL(name, out).pathname.replace(/^\/([A-Za-z]:)/, "$1");
await mkdir(out, { recursive: true });
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
const errors = [],
  forbidden = [];
try {
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 } });
    const page = await context.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await page.route("**/*", (route) => {
      const url = route.request().url();
      if (!url.startsWith(origin) || new URL(url).pathname.startsWith("/api/")) {
        forbidden.push(url);
        return route.abort();
      }
      return route.continue();
    });
    await page.goto(`${origin}/dashboard.html?demo=1#/equipment/probes`);
    const panel = page.getByRole("region", { name: "Feed probe calibration" });
    await panel.waitFor();
    // Flower 2 maps both feed probes; its pH probe was checked before and was drifting.
    const ph = panel.locator('[data-calibration-probe="feed_ph"]');
    await ph.getByText("Drifting", { exact: false }).waitFor();
    await panel.locator('[data-calibration-probe="feed_ec"]').getByText("Never checked").waitFor();

    await ph.getByRole("button", { name: "Check pH" }).click();
    const form = panel.getByRole("form", { name: "Check the Feed-water pH probe" });
    assert.equal(await form.getByLabel("Reference (pH)").first().inputValue(), "7");
    await form.getByLabel("Probe read (pH)").first().fill("7.05");
    await form.getByLabel("Probe read (pH)").last().fill("4.1");
    const result = form.locator("[data-calibration-result]");
    assert.match(await result.innerText(), /Slope 98\.3 % · offset \+0\.05 pH/);
    assert.match(await result.innerText(), /Passes/);
    // References too close together cannot be saved.
    await form.getByLabel("Reference (pH)").last().fill("6.5");
    assert.match(await result.innerText(), /at least 1 apart/);
    assert.ok(await form.getByRole("button", { name: "Save the check" }).isDisabled());
    await form.getByLabel("Reference (pH)").last().fill("4");
    // The live reading can be taken straight from the probe.
    await form.getByRole("button", { name: "Use the reading now" }).first().click();
    assert.match(await form.getByLabel("Probe read (pH)").first().inputValue(), /^\d+(\.\d+)?$/);
    await form.getByLabel("Probe read (pH)").first().fill("7.05");
    await form.getByLabel("Note (optional)").fill("Fresh buffers");
    if (width === 1440) await page.screenshot({ path: file("probe-calibration-form.png") });
    await form.getByRole("button", { name: "Save the check" }).click();
    await form.waitFor({ state: "detached" });

    const rows = panel.locator("[data-calibration-record]");
    assert.equal(await rows.count(), 2);
    assert.equal(await rows.first().getAttribute("data-calibration-record"), "pass");
    assert.match(await rows.first().innerText(), /98\.3 %[\s\S]*\+0\.05 pH[\s\S]*Fresh buffers/);
    await ph.getByText("Passes").waitFor();
    assert.ok(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      `no horizontal overflow at ${width}`,
    );
    const audit = await new AxeBuilder({ page }).include(".probe-calibration").analyze();
    assert.deepEqual(
      audit.violations.map((v) => ({ id: v.id, impact: v.impact })),
      [],
      `calibration panel accessibility at ${width}`,
    );
    await page.screenshot({ path: file(`probe-calibration-${width}.png`), fullPage: true });
    await context.close();
  }
  // Flower 1 maps no feed-water probe: nothing to check, and it says where to map one.
  const page = await browser.newPage();
  await page.goto(`${origin}/dashboard.html?demo=1&room=room%3Af1_#/equipment/probes`);
  await page
    .getByRole("region", { name: "Feed probe calibration" })
    .getByText("No feed-water probe is mapped")
    .waitFor();
  await page.close();
  assert.deepEqual(errors, [], "no page errors");
  assert.deepEqual(forbidden, [], "no external or API requests");
  console.log("Probe calibration flow passed at 1440 and 390 px; no errors or external requests.");
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
