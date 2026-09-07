import { chromium } from "playwright";
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto("http://127.0.0.1:5198/f2-classic.html?demo", {
  waitUntil: "networkidle",
  timeout: 60000,
});
await page.screenshot({
  path: "output/playwright/before-desktop.png",
  fullPage: false,
});
console.log(
  JSON.stringify(
    {
      title: await page.title(),
      errors,
      buttons: await page.getByRole("button").allTextContents(),
    },
    null,
    2,
  ).slice(0, 6500),
);
await page.setViewportSize({ width: 390, height: 844 });
await page.screenshot({
  path: "output/playwright/before-mobile.png",
  fullPage: false,
});
await browser.close();
