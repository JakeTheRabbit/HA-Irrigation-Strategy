/** H3 History › Compare runs (mockup 11), against frontend/dist: run after `vite build`. Opens Room A
 * (the demo's F2) at #/history/compare.
 *
 * The clock is pinned to today 12:00 local, so the demo's runs and grow-day summaries (dated from
 * today) are the same on every run.
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - "<room> · whole-room daily values" and "Line runs up by" (Day of flower; Day of run disabled:
 *   run records carry no clone date);
 * - a card per run: this run first, ticked and locked, "Growing · …"; the ended run "Harvested …";
 * - four small multiples (VWC, overnight dryback, pore EC, water per plant), each with every ticked
 *   run's line; the callouts name the other run and each has its box;
 * - unticking that run removes its lines and its callouts;
 * - a run registered in History › Grows without a harvest shows "No harvest result recorded";
 *   Add harvest result opens the form (Dry kg); saving reads it back ("Written and read back HH:MM")
 *   and the card says the dry weight; Undo takes it back out. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const HHMM = String.raw`\d{1,2}:\d{2}(?: [ap]m)?`;

await runParity({
  id: "h3",
  route: "/history/compare",
  mockup: "11-H3-Compare.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const pinned = new Date();
    pinned.setHours(12, 0, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    await page.getByRole("heading", { level: 1, name: "Compare runs", exact: true }).waitFor();
    const compare = page.locator("[data-run-compare]");
    await compare.waitFor();

    // Header.
    assert.match(await compare.locator(".rc-scope").innerText(), / · whole-room daily values$/, `${label}: scope`);
    const align = compare.getByLabel("Line runs up by");
    assert.equal(await align.inputValue(), "flower", `${label}: line up`);
    assert.equal(await align.locator('option[value="run"]').isDisabled(), true, `${label}: day of run disabled`);
    region("header");

    // Run cards.
    const cards = compare.locator("[data-run-card]");
    await compare.locator(".rc-result", { hasText: "Harvested" }).first().waitFor();
    assert.ok((await cards.count()) >= 2, `${label}: cards`);
    const first = cards.first();
    assert.match(await first.innerText(), / · this run/, `${label}: this run first`);
    assert.equal(await first.getByRole("checkbox").isDisabled(), true, `${label}: this run locked`);
    assert.equal(await first.getByRole("checkbox").isChecked(), true);
    assert.match(await first.locator(".rc-result").innerText(), /^Growing · /, `${label}: growing`);
    const other = cards.nth(1);
    const otherId = await other.getAttribute("data-run-card");
    const otherName = (await other.locator(".rc-tick-run").innerText()).trim();
    assert.match(await other.locator(".rc-result").innerText(), /^Harvested \w{3} \d{1,2} \w{3} · [\d.]+ kg dry/, `${label}: harvested`);
    region("run cards");

    // Four small multiples, each with both runs' lines.
    const charts = compare.locator("[data-compare-chart]");
    assert.deepEqual(
      await charts.evaluateAll((all) => all.map((el) => el.getAttribute("data-compare-chart"))),
      ["vwc", "dryback", "pore_ec", "water"],
      `${label}: charts`,
    );
    assert.equal(await compare.locator(`[data-run-line="${otherId}"]`).count(), 4, `${label}: ${otherName} lines`);
    const callouts = compare.locator("[data-callout]:not([hidden])");
    const texts = await callouts.allInnerTexts();
    assert.ok(texts.length >= 1, `${label}: callouts`);
    for (const text of texts) assert.ok(text.includes(otherName), `${label}: callout names ${otherName}: ${text}`);
    assert.equal(await compare.locator("[data-callout-box]").count(), texts.length, `${label}: a box per callout`);
    region("small multiples");
    region("callouts");

    // Unticking the other run removes its lines and its callouts.
    await other.getByRole("checkbox").uncheck();
    assert.equal(await compare.locator(`[data-run-line="${otherId}"]`).count(), 0, `${label}: lines gone`);
    assert.equal(await compare.locator("[data-callout]:not([hidden])", { hasText: otherName }).count(), 0, `${label}: callouts gone`);
    assert.equal(await compare.locator("[data-callout-box]").count(), 0, `${label}: boxes gone`);
    await other.getByRole("checkbox").check();
    assert.equal(await compare.locator(`[data-run-line="${otherId}"]`).count(), 4, `${label}: lines back`);
    region("untick");

    // A run with no harvest result: registered in History › Grows, in the same visit.
    await page.evaluate(() => (location.hash = "#/history/grows"));
    const records = page.locator("#run-records");
    await records.waitFor();
    const dateAgo = (days) => {
      const d = new Date(pinned.getTime() - days * 86_400_000);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    };
    await records.getByRole("button", { name: "Add run", exact: true }).click();
    await page.getByLabel("Run name", { exact: true }).fill("Run 12");
    await page.getByLabel("Run start date", { exact: true }).fill(dateAgo(170));
    await page.getByLabel("Run end date", { exact: true }).fill(dateAgo(120));
    await page.getByRole("button", { name: "Save run record", exact: true }).click();
    await page.locator(".comparison-run-list article").filter({ hasText: "Run 12" }).waitFor();
    await page.evaluate(() => (location.hash = "#/history/compare"));
    const card = page.locator("[data-run-card]").filter({ hasText: "Run 12" });
    await card.locator(".rc-result", { hasText: "No harvest result recorded" }).waitFor();
    await card.getByRole("button", { name: "Add harvest result", exact: true }).click();
    const kg = card.getByLabel("Dry kg", { exact: true });
    await kg.waitFor();
    region("add harvest form");
    await kg.fill("38.4");
    const review = page.getByRole("region", { name: "Review and apply" });
    assert.match(await review.innerText(), /Run 12 dry weight\s*none\s*→\s*38\.4 kg/, `${label}: review row`);
    await review.getByRole("button", { name: "Save to Run 12", exact: true }).click();
    const receipt = review.getByRole("status");
    await receipt.waitFor();
    assert.match(await receipt.innerText(), new RegExp(`Written and read back ${HHMM}`), `${label}: receipt`);
    assert.match(await card.locator(".rc-result").innerText(), /^Harvested \w{3} \d{1,2} \w{3} · 38\.4 kg dry$/, `${label}: card result`);
    await review.getByRole("button", { name: "Undo: write back the previous values", exact: true }).click();
    await review.getByText(/^Previous values written back/).waitFor();
    assert.equal((await card.locator(".rc-result").innerText()).trim(), "No harvest result recorded", `${label}: undone`);
    region("harvest receipt");
    await page.evaluate(() => scrollTo(0, 0));
  },
});
