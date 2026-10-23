/** E2 Feed & dosing (mockup 14), against frontend/dist: run after `vite build`. Opens
 * #/equipment/feed in the demo (Room A: a batch tank, four dosing pumps, its last batch's mix check
 * failed on EC).
 *
 * The clock is pinned to today 16:00 local, so the demo's tank story (filled 14:00, drawn down since)
 * reads the same at any real hour.
 *
 * Interactions asserted, at 1440 and 390, on 3.18 and 3.17:
 * - #/equipment/feed lands on #/equipment/dosing, titled "Feed & dosing · Room A" with
 *   "protections armed 5 of 5";
 * - the plumbing holds the pumps with their stock, the batch card, the tank card with its guards,
 *   and the failed mix check in place, beside the tank;
 * - feed recipes mark this week, and the next batch warns that Part B falls below its low line;
 * - Calibrate a pump and Calibrate feed pH/EC open the wizard routes; the mix check's calibrate link
 *   points at the feed calibration;
 * - a short press of Top up and re-check sends nothing; holding it 1.5 s records a dosing_request
 *   to make a batch (the request line names it), and the failed check gives way to the batch. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const out = (name) =>
  new URL(`../../output/playwright/parity/${name}`, import.meta.url).pathname.replace(
    /^\/([A-Za-z]:)/,
    "$1",
  );

await runParity({
  id: "e2",
  route: "/equipment/feed",
  mockup: "14-E2-Dosing.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const pinned = new Date();
    pinned.setHours(16, 0, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    const main = page.locator("main");
    await main
      .getByRole("heading", { name: "Feed & dosing · Room A", exact: true, level: 1 })
      .waitFor();
    assert.equal(
      new URL(page.url()).hash,
      "#/equipment/dosing",
      `${label}: #/equipment/feed lands on dosing`,
    );
    assert.match(
      await main.locator(".page-heading p").innerText(),
      /^Batch tank, 4 dosing pumps, 3 zones · protections armed 5 of 5$/,
      `${label}: subtitle`,
    );
    region("title");

    // The plumbing: pumps and stock, the batch, the tank with its guards, the mix check in place.
    const plumbing = main.locator("[data-plumbing]");
    assert.equal(
      await plumbing.locator("[data-dosing-pump]").count(),
      4,
      `${label}: a node per pump`,
    );
    assert.match(
      await plumbing.locator('[data-dosing-pump="part_b"] [data-pump-stock]').innerText(),
      /5\.4 \/ 20\.0 (L|gal)[\s\S]*low/,
      `${label}: Part B stock`,
    );
    region("pumps and stock");
    const batch = plumbing.locator("[data-batch-card]");
    assert.match(
      await batch.locator("h2").innerText(),
      /^Batch\s+Bloom · week 3$/,
      `${label}: batch title`,
    );
    assert.match(await batch.innerText(), /Part B\s+1,?800 mL/, `${label}: batch doses`);
    assert.match(await batch.innerText(), /Target EC 2\.40 mS\/cm/, `${label}: target`);
    assert.match(
      await batch.locator("[data-batch-line]").innerText(),
      /^No batch running · last batch finished \d/,
      `${label}: batch line`,
    );
    region("batch card");
    for (const text of [
      "Read-back on every dose",
      "Overfill cut 102%",
      "Minimum 8%",
      "Mix pump off",
      "Timeout 20 min",
    ])
      assert.equal(
        await plumbing.locator('[data-protection="armed"]', { hasText: text }).count(),
        1,
        `${label}: ${text} armed`,
      );
    await plumbing.locator("[data-tank-status]").waitFor();
    assert.equal(
      await plumbing.locator("[data-reservoir-guard]").getAttribute("data-reservoir-guard"),
      "ok",
      `${label}: guard`,
    );
    region("tank and guards");
    const mix = plumbing.locator('[data-mix-check="off target"]');
    await mix.waitFor();
    assert.match(
      await mix.locator("h3").innerText(),
      /^Mix check failed \d\d:\d\d$/,
      `${label}: mix title`,
    );
    assert.match(
      await mix.innerText(),
      /Want EC 2\.30–3\.50 mS\/cm; it read 3\.71 mS\/cm\./,
      `${label}: mix why`,
    );
    assert.match(
      await mix.innerText(),
      /Feed EC probe calibrated 9 days ago · calibrate/,
      `${label}: calibration age`,
    );
    assert.equal(
      await mix.getByRole("link", { name: "calibrate" }).getAttribute("href"),
      "#/equipment/feed-calibration",
    );
    assert.equal(
      await main.getByText("Use once anyway").count(),
      0,
      `${label}: no release of a held feed`,
    );
    if (width > 720) {
      // Beside the tank, on the same row.
      const [tank, card] = await Promise.all([
        plumbing.locator(".plumb-tank").boundingBox(),
        mix.boundingBox(),
      ]);
      assert.ok(
        card.x >= tank.x + tank.width - 1 && card.y < tank.y + tank.height,
        `${label}: mix check beside the tank`,
      );
    }
    region("mix check in place");

    const recipes = main.locator("[data-feed-recipes]");
    assert.equal(
      await recipes.locator('[aria-current="step"]').innerText(),
      "Wk 3",
      `${label}: this week`,
    );
    assert.match(
      await recipes.locator("[data-now]").innerText(),
      /Bloom[\s\S]*Wk 3–8[\s\S]*This week/,
      `${label}: Bloom this week`,
    );
    region("feed recipes");
    const next = main.locator("[data-next-batch]");
    assert.match(
      await next.locator("[data-stock-warning]").innerText(),
      /^Part B after this batch: 3\.6 (L|gal), 2 batches left\sStock tanks$/,
      `${label}: stock warning`,
    );
    assert.equal(
      await next.locator("[data-stock-warning] a").getAttribute("href"),
      "#/equipment/stock",
      `${label}: stock warning links to the stock tanks`,
    );
    assert.match(await next.innerText(), /when the tank reaches 8%/, `${label}: next batch level`);
    // Filled to 100 % at 14:00 and at 87 % now: 6.5 % an hour, so 8 % about 12 h from now.
    await next.locator('[data-next-batch-at]:not([data-next-batch-at=""])').waitFor();
    assert.match(
      await next.locator("[data-next-batch-at]").innerText(),
      /^[A-Z][a-z]{2} \d{1,2} [A-Z][a-z]{2}, about \d\d:\d\d$/,
      `${label}: next batch time`,
    );
    region("next batch");

    for (const scheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.screenshot({
        path: out(`e2-full-${width}-${backend}-${scheme}.png`),
        fullPage: true,
        animations: "disabled",
      });
    }
    await page.emulateMedia({ colorScheme: "light" });

    // The calibrate buttons open the wizard routes.
    for (const [name, hash] of [
      ["Calibrate a pump", "#/equipment/pump-calibration"],
      ["Calibrate feed pH/EC", "#/equipment/feed-calibration"],
    ]) {
      await next.getByRole("button", { name, exact: true }).click();
      await page.waitForFunction((want) => location.hash === want, hash);
      await page.goBack();
      await mix.waitFor();
    }
    region("calibrate links");

    // Top up and re-check: a short press sends nothing; a 1.5 s hold asks for a batch.
    const hold = mix.getByRole("button", { name: /^Top up and re-check/ });
    await hold.scrollIntoViewIfNeeded();
    const box = await hold.boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.waitForTimeout(400);
    await page.mouse.up();
    await page.waitForTimeout(300);
    assert.equal(
      await main.locator("[data-request-stage]").count(),
      0,
      `${label}: a short press sends nothing`,
    );
    await page.mouse.down();
    await page.waitForTimeout(1700);
    await page.mouse.up();
    await main.locator("[data-request-stage]", { hasText: "make a batch" }).waitFor();
    region("hold to top up and re-check");
    // The controller takes it: the batch runs, and the failed check gives way to it.
    await main
      .locator("[data-batch-line]", { hasText: /^Making a batch/ })
      .waitFor({ timeout: 10_000 });
    assert.equal(
      await main.locator("[data-mix-check]").count(),
      0,
      `${label}: the batch replaces the check`,
    );
    await page.screenshot({
      path: out(`e2-topup-${width}-${backend}.png`),
      animations: "disabled",
    });
    // Stop the batch so the run ends with nothing moving.
    await main.getByRole("button", { name: "Stop the batch", exact: true }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Send stop", exact: true }).click();
    await main
      .locator("[data-batch-line]", { hasText: /^No batch running · last batch stopped/ })
      .waitFor({ timeout: 10_000 });
    // The harness screenshot is the page as first seen.
    await page.reload();
    await main.locator('[data-mix-check="off target"]').waitFor();
    await page.evaluate(() => scrollTo(0, 0));
  },
});
console.log(
  "PASS: E2 feed & dosing (feed lands on dosing, protections armed 5 of 5, plumbing with pumps, batch card, tank guards and the failed mix check in place, recipes this week, next batch stock warning, calibrate routes, short press sends nothing, 1.5 s hold records a batch request; clock pinned 16:00)",
);
