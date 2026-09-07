/** HA shell contract fixture: temporary kiosk state, recovery, no preference writes. */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright";
const html = await readFile(new URL("../../www/dashboard.html", import.meta.url));
const shell = `<!doctype html><html><body><home-assistant></home-assistant><script>
window.events=[];const host=document.querySelector('home-assistant');
host.hass={kioskMode:new URLSearchParams(location.search).has('existing')};
const shadow=host.attachShadow({mode:'open'});shadow.innerHTML='<home-assistant-main></home-assistant-main><slot></slot>';
const main=shadow.querySelector('home-assistant-main');
window.addEventListener('hass-kiosk-mode',e=>{host.hass.kioskMode=e.detail.enable;events.push(['kiosk',e.detail.enable]);});
main.addEventListener('hass-toggle-menu',()=>events.push(['menu']));
host.insertAdjacentHTML('beforeend','<iframe title="Crop Steering" style="width:100%;height:100vh;border:0" src="/dashboard.html?demo=1"></iframe>');
</script></body></html>`;
const server = createServer((req, res) => {
  res.writeHead(200, { "Content-Type": "text/html" });
  res.end(req.url.startsWith("/crop-steering") ? shell : html);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({
  headless: true,
  ...(process.platform === "win32" ? { channel: "chrome" } : {}),
});
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await context.route("**/*", (route) =>
  new URL(route.request().url()).origin === origin ? route.continue() : route.abort(),
);
try {
  await page.goto(origin + "/crop-steering");
  const frame = page.frameLocator("iframe");
  await frame.getByRole("button", { name: "Open Home Assistant menu", exact: true }).click();
  assert.equal(
    await page.evaluate(() => document.querySelector("home-assistant").hass.kioskMode),
    true,
  );
  assert.ok(await page.evaluate(() => events.some((e) => e[0] === "menu")));
  await page.setViewportSize({ width: 390, height: 844 });
  await frame.getByRole("button", { name: "Open Home Assistant menu", exact: true }).click();
  assert.ok(await frame.locator("html").evaluate((el) => el.scrollWidth <= innerWidth + 1));
  await page.evaluate(() => {
    history.pushState({}, "", "/lovelace");
    dispatchEvent(new Event("location-changed"));
  });
  assert.equal(
    await page.evaluate(() => document.querySelector("home-assistant").hass.kioskMode),
    false,
  );
  await page.goto(origin + "/crop-steering?existing=1");
  await frame.getByRole("button", { name: "Open Home Assistant menu", exact: true }).waitFor();
  await page.evaluate(() => {
    history.pushState({}, "", "/lovelace");
    dispatchEvent(new Event("location-changed"));
  });
  assert.equal(
    await page.evaluate(() => document.querySelector("home-assistant").hass.kioskMode),
    true,
  );
  await page.goto(origin + "/dashboard.html?demo=1");
  await page.getByRole("heading", { name: "Room overview" }).waitFor();
  assert.equal(
    await page.getByRole("button", { name: "Open Home Assistant menu", exact: true }).count(),
    0,
  );
  assert.deepEqual(errors, []);
  const out = new URL("../../output/playwright/", import.meta.url);
  await mkdir(out, { recursive: true });
  await writeFile(
    new URL("ha-shell-verification.json", out),
    JSON.stringify(
      {
        checks: [
          "temporary kiosk enabled",
          "desktop/mobile recovery button",
          "leaving restores previous state",
          "preexisting kiosk preserved",
          "standalone unchanged",
        ],
        errors,
      },
      null,
      2,
    ),
  );
  console.log("5 HA shell browser checks passed.");
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
