/** E4 Feed pH/EC calibration (mockups 16 desktop, 28 phone), against frontend/dist: run after
 * `vite build`. Opens #/equipment/feed-calibration in the demo (Room A maps its tank pH and EC probes as
 * the feed probes; Room B maps none). PORT: serve on that port (default: an ephemeral one).
 *
 * The clock is installed at today 14:10 local and then driven with `runFor`, so the demo probe settles
 * in a minute of page time and every time read back is 14:1x at any real hour.
 *
 * Interactions asserted, at 1440 and 390:
 * - 3.18: Choose probe lists Room A feed pH and EC; Start calibration opens buffer 1 with the prepare
 *   copy, "Step 2 of 5 · dosing for Room A paused" (phone: "Equipment · step 2 of 5 · dosing paused");
 *   the demo reading settles: Capture is disabled ("Capture 7.00 point · waiting for stable", phone
 *   "Waiting for a steady reading") while it moves, enabled once it held 30 s ("Steady"); Capture
 *   gives "Captured 7.04"; desktop, leaving through the menu keeps the session and step 1 offers "Resume calibration"
 *   with "Dosing for Room A stays paused until HH:MM" and the footer "Step 1 of 5 · dosing for Room A
 *   paused" (no "compensated" claim anywhere);
 *   buffer 2 the same ("Captured 4.09"); the result reads "Probe reads 0.04 pH high. Response 98.3% —
 *   healthy." with Pass marked; Apply calibration gives "Written and read back 14:1x" and the proof
 *   "Now reads 4.00 in pH 4.00 buffer ✓"; Undo writes the previous calibration back.
 * - The Room A pH card reads "last calibrated <date>" and "Overdue since <date>", as the demo's
 *   calibration_due sensor says (calibration.py due(): the newest record that did not fail).
 * - Desktop, after Undo: "Calibrate the other probe", Start, then Back abandons the session (no Resume
 *   card, footer "Step 1 of 5" with no pause); Start again, 31 min later the status poll finds it
 *   expired: "Your last calibration session expired" and the footer no longer says dosing is paused.
 * - Phone: ✕ goes back to Feed & dosing; ✕ mid-session abandons it (back on the page: step 1, no
 *   Resume card, no "dosing paused").
 * - 3.17: the v1 two-point check form ("Feed probe calibration") under one Needs integration note.
 * - Both: Equipment › Probes & offsets shows the link "Feed pH and EC probes: Calibrate →".
 * Only requests to the page's own origin are made (the harness fails any other). */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

await runParity({
  id: "e4",
  route: "/equipment/feed-calibration",
  mockup: "16-E4-FeedCal.png",
  phoneMockup: "28-P5-Calibrate.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const phone = width <= 720;
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.install({ time: pinned });

    // The Probes page links here.
    await page.goto(page.url().replace(/#.*$/, "#/equipment/probes"));
    // A hash change keeps the document: reload it so the installed clock drives the page.
    await page.reload();
    const link = page.getByRole("link", { name: "Feed pH and EC probes: Calibrate →", exact: true });
    await link.waitFor();
    assert.equal(await link.getAttribute("href"), "#/equipment/feed-calibration", `${label}: probes link`);
    assert.equal(await page.locator("section.probe-calibration").count(), 0, `${label}: no form on Probes`);
    region("probes link");
    await link.click();
    const main = page.locator("main");

    if (backend === "3.17") {
      await main.getByRole("heading", { level: 1, name: "Feed pH/EC calibration" }).waitFor();
      const form = main.getByRole("region", { name: "Feed probe calibration" });
      await form.locator('[data-calibration-probe="feed_ph"]').waitFor();
      assert.equal(await main.locator("[data-needs-integration]").count(), 1, `${label}: one needs-integration note`);
      region("v1 check form");
      return;
    }

    const title = phone ? "Calibrate Room A feed pH" : "Calibrate feed pH probe";
    await main.getByRole("heading", { level: 1, name: title }).waitFor();
    const cards = main.locator("[data-feed-probe]");
    await cards.first().waitFor();
    assert.deepEqual(
      (await cards.allInnerTexts()).map((t) => t.split("\n")[0]),
      ["Room A feed pH", "Room A feed EC"],
      `${label}: probes`,
    );
    assert.equal(await cards.first().getAttribute("aria-checked"), "true");
    const phCard = await cards.first().innerText();
    assert.match(phCard, /last calibrated \d{1,2} \w{3}/, `${label}: pH card last calibrated`);
    assert.match(phCard, /Overdue since \d{1,2} \w{3}/, `${label}: pH card overdue as calibration_due`);
    region("choose probe");
    region("probe due as calibration_due");

    const foot = page.locator(".feed-cal-foot");
    await foot.getByRole("button", { name: "Start calibration" }).click();
    await main
      .getByText("Rinse the probe, dab it dry and stand it in the 7.00 buffer. Leave it still; the reading settles by itself.", { exact: true })
      .waitFor();
    if (phone) assert.equal(await page.locator(".feed-cal-phonebar p").innerText(), "Equipment · step 2 of 5 · dosing paused");
    else assert.equal(await foot.locator(".feed-cal-count").innerText(), "Step 2 of 5 · dosing for Room A paused");

    const capture = (buffer) =>
      phone ? foot.locator(".feed-cal-next") : main.getByRole("button", { name: new RegExp(`^Capture ${buffer} point`) });
    const settle = async (buffer, read) => {
      await page.clock.runFor(5_000);
      const button = capture(buffer);
      assert.ok(await button.isDisabled(), `${label}: capture locked while settling`);
      assert.equal(
        await button.innerText(),
        phone ? "Waiting for a steady reading" : `Capture ${buffer} point · waiting for stable`,
        `${label}: waiting label`,
      );
      if (!phone) assert.match(await main.locator("[data-stability]").innerText(), /^(Settling…|Stable \d+ s of 30 s)/);
      await page.clock.runFor(75_000);
      if (!phone) await main.locator("[data-stability]").getByText("Steady", { exact: true }).waitFor();
      else await main.locator('.stability-ring[data-state="steady"]').waitFor();
      assert.equal(await button.innerText(), `Capture ${buffer} point`, `${label}: capture label`);
      assert.ok(await button.isEnabled(), `${label}: capture unlocked`);
      await button.click();
      await main.getByText(`Captured ${read}`, { exact: true }).waitFor();
    };
    await page.screenshot({ path: `../output/playwright/parity/e4-settling-${width}.png`, animations: "disabled" });
    await settle("7.00", "7.04");
    region("buffer 1 settles then captures");

    if (!phone) {
      // Leaving through the menu keeps the session: step 1 offers to resume it.
      await page.evaluate(() => (location.hash = "#/equipment/dosing"));
      await page.waitForFunction(() => location.hash === "#/equipment/dosing");
      await page.evaluate(() => (location.hash = "#/equipment/feed-calibration"));
      await main.locator(".feed-cal-resume").waitFor();
      // The open session still pauses dosing: the Resume card and the footer say so.
      assert.match(
        await main.locator(".feed-cal-resume span").innerText(),
        /^A calibration of the Room A feed pH probe is still open\. Dosing for Room A stays paused until \d\d:\d\d\.$/,
        `${label}: resume card pause`,
      );
      assert.equal(await foot.locator(".feed-cal-count").innerText(), "Step 1 of 5 · dosing for Room A paused");
      assert.doesNotMatch(await page.locator(".feed-cal").innerText(), /compensated/, `${label}: no compensation claim`);
      await main.getByRole("button", { name: "Resume calibration" }).click();
      await page.locator(".feed-cal-rail").getByText("read 7.04", { exact: true }).waitFor();
      region("resume");
    }
    await foot.getByRole("button", { name: "Next: rinse, into 4.00" }).click();
    await settle("4.00", "4.09");
    region("buffer 2");

    await foot.getByRole("button", { name: "Next: see the result" }).click();
    assert.equal(
      await main.locator("[data-verdict-headline]").innerText(),
      "Probe reads 0.04 pH high. Response 98.3% — healthy.",
      `${label}: headline`,
    );
    assert.equal(await main.locator('.feed-cal-grades li[aria-current="true"]').innerText(), "Pass");
    region("result headline");

    await foot.getByRole("button", { name: "Next: apply" }).click();
    await main.getByRole("button", { name: "Apply calibration" }).click();
    const receipt = main.locator(".review-apply-receipt");
    await receipt.getByText(/^Written and read back 14:1\d$/).waitFor();
    await main.locator("[data-proof]").getByText("Now reads 4.00 in pH 4.00 buffer", { exact: true }).waitFor();
    assert.equal((await main.locator("[data-proof]").innerText()).trim(), "Now reads 4.00 in pH 4.00 buffer ✓");
    region("apply receipt and proof");
    await page.screenshot({ path: `../output/playwright/parity/e4-applied-${width}.png`, animations: "disabled" });

    await receipt.getByRole("button", { name: "Undo: write back the previous values" }).click();
    await main.getByText(/^Previous values written back 14:1\d$/).waitFor();
    assert.equal(await main.locator("[data-proof]").count(), 0, `${label}: no proof after undo`);
    region("undo");

    if (phone) {
      const close = page.getByRole("button", { name: "Close calibration, back to Feed & dosing" });
      await close.click();
      await page.waitForFunction(() => location.hash === "#/equipment/dosing");
      region("phone close");
      await page.goBack();
      await main.getByRole("heading", { level: 1, name: title }).waitFor();
      // ✕ mid-session abandons it: nothing left holding dosing.
      await foot.getByRole("button", { name: "Start calibration" }).click();
      await page.locator(".feed-cal-phonebar p").getByText("Equipment · step 2 of 5 · dosing paused", { exact: true }).waitFor();
      await close.click();
      await page.waitForFunction(() => location.hash === "#/equipment/dosing");
      await page.goBack();
      await main.getByRole("heading", { level: 1, name: title }).waitFor();
      await main.locator("[data-feed-probe]").first().waitFor();
      assert.equal(await page.locator(".feed-cal-phonebar p").innerText(), "Equipment · step 1 of 5", `${label}: no pause after close`);
      assert.equal(await main.locator(".feed-cal-resume").count(), 0, `${label}: no resume after close`);
      region("phone close abandons");
    } else {
      // Back from buffer 1 abandons the session.
      await main.getByRole("button", { name: "Calibrate the other probe" }).click();
      await foot.getByRole("button", { name: "Start calibration" }).click();
      await foot.locator(".feed-cal-count").getByText("Step 2 of 5 · dosing for Room A paused", { exact: true }).waitFor();
      await foot.getByRole("button", { name: "Back", exact: true }).click();
      await foot.locator(".feed-cal-count").getByText("Step 1 of 5", { exact: true }).waitFor();
      assert.equal(await main.locator(".feed-cal-resume").count(), 0, `${label}: no resume after Back`);
      region("back abandons");
      // A session that expires releases the hold: the page stops saying dosing is paused.
      await foot.getByRole("button", { name: "Start calibration" }).click();
      await foot.locator(".feed-cal-count").getByText("Step 2 of 5 · dosing for Room A paused", { exact: true }).waitFor();
      await page.clock.fastForward(31 * 60_000);
      await page.clock.runFor(6_000);
      await main.getByText("Your last calibration session expired. Start again from buffer 1.", { exact: true }).waitFor();
      assert.equal(await foot.locator(".feed-cal-count").innerText(), "Step 2 of 5", `${label}: no pause after expiry`);
      region("expiry releases the pause");
    }
  },
});
console.log("PASS: E4 feed pH/EC calibration (2 viewports x 2 backends)");
