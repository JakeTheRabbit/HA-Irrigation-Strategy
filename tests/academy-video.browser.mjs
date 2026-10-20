// Video captions must remain readable without covering the teaching diagram.
import assert from "node:assert/strict";
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
const base = process.env.BASE_URL || "http://127.0.0.1:8794/learn/";
const browser = await chromium.launch({channel: process.env.BROWSER_CHANNEL || "msedge", headless: true});
try {
  const page = await browser.newPage();
  await page.goto(base + "#/lesson/A1");
  const video = page.locator("video");
  await video.waitFor();
  const captions = page.locator(".lp-caption");
  assert.equal(await captions.count(), 1, "A separate caption area must exist below the video");
  await page.waitForFunction(() => document.querySelector("video track")?.readyState === 2);
  await video.evaluate(v => new Promise(resolve => {
    v.addEventListener("seeked", resolve, {once:true});
    v.currentTime = 6; // after the 4 s lesson opener
  }));
  await page.waitForFunction(() => document.querySelector(".lp-caption")?.textContent.trim().length > 10);
  assert.equal(await video.evaluate(v => v.textTracks[0].mode), "hidden");
  const picture = await video.boundingBox(), text = await captions.boundingBox();
  assert.ok(text.y >= picture.y + picture.height - 1, "Captions must not cover picture labels");
  const toggle = page.getByRole("button", {name: /^CC/});
  await toggle.click();
  assert.equal(await captions.isVisible(), false);
  await toggle.click();
  assert.equal(await captions.isVisible(), true);
  console.log("PASS lesson captions follow the spoken cue below the picture and can be toggled");
} finally {
  await browser.close();
}
