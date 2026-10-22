/** S2 Room (mockup 03), against frontend/dist: run after `vite build`. Opens Room B (the demo's F1:
 * Holding, flower stretch, day 12 of 63) at #/today.
 *
 * The clock is pinned to today 14:10 local, so the demo day is the same at any real hour (Room B's
 * lights come on at 08:00: earlier, its strip has no shots yet).
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - the header: the room's stage and plants, "Day 12 of 63 · 51 days left · harvest …", the run
 *   bar's "Stretch ends day 21" marker, "Water today … room · … per watered plant" and the lights;
 * - the Today strip has 3 zone tracks (3.18), with its legend and "Open full timeline"; on 3.17 the
 *   "Needs integration" note sits inside the strip region and there are no tracks;
 * - each zone row has three gauges with their "target …" and its water against the room's median
 *   ("+N mL vs median M mL", "Not watered today" for the paused zone 3);
 * - zone 2's back sensor (3.18) says "silent 3 h", "Last heard HH:MM. Left out: the zone reads the
 *   front sensor only." and offers "Check back probe", and its open alert is not said again on the row;
 * - zone 3 is paused: "Paused by Ben at HH:MM (slab change)." on 3.18 (the Journal and the person),
 *   "Paused at HH:MM." on 3.17; "Resume zone 3" writes the switch and toasts "Zone 3 resumed.
 *   Written and read back HH:MM." with Undo; Undo writes it back: Paused and "Resume zone 3" again;
 * - the HMI zone table and the "AI assistant changes today" block are gone.
 * Also writes full-page light and dark screenshots of each run beside the harness's own. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const out = (name) =>
  new URL(`../../output/playwright/parity/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const HHMM = String.raw`\d{1,2}:\d{2}(?: [ap]m)?`;
/** A time today, or yesterday's (the demo's grow-day can start yesterday). */
const WHEN = String.raw`(?:yesterday )?${HHMM}`;
const AT = String.raw`(?:yesterday )?at ${HHMM}`;

await runParity({
  id: "s2",
  route: "/today",
  mockup: "03-S2-Room.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const v318 = backend === "3.18";
    // The demo follows the clock: pin it to today 14:10 local, as verify-parity-i1 does.
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    // The mockup's room: Room B.
    const url = new URL(page.url());
    url.searchParams.set("room", "room:room_b_");
    await page.goto(url.href);
    await page.getByRole("heading", { level: 1, name: "Room B", exact: true }).waitFor();

    // Header.
    const sub = await page.locator("[data-today-sub]").innerText();
    assert.match(sub, v318 ? /^\S.* · Flower stretch · \d+ plants in 3 zones$/ : /^\S[^·]* · \d+ plants in 3 zones$/, `${label}: stage and plants`);
    if (v318) {
      assert.match(
        await page.locator("[data-today-day]").innerText(),
        /^Day 12 of 63 · 51 days left · harvest \d{1,2} [A-Z][a-z]{2}$/,
        `${label}: grow day`,
      );
      assert.equal((await page.locator(".today-run-mark").innerText()).trim(), "Stretch ends day 21", `${label}: stage end`);
    } else assert.equal(await page.locator("[data-today-day]").count(), 0, `${label}: no grow day on 3.17`);
    const facts = await page.locator("[data-today-line]").innerText();
    assert.match(facts, /Water today\s+[\d.]+ L room · [\d.]+ L per watered plant/, `${label}: water today`);
    assert.match(facts, new RegExp(`Lights\\s+O(n|ff) ${HHMM} – ${HHMM}`), `${label}: lights`);
    region("header");

    // Today strip.
    const strip = page.locator("[data-today-strip]");
    if (v318) {
      await strip.locator(".shot-timeline").waitFor();
      assert.equal(await strip.locator('.st-row[data-kind="zone"]').count(), 3, `${label}: 3 strip rows`);
      assert.match(await strip.innerText(), /Shot done[\s\S]*Planned[\s\S]*Lights on/, `${label}: legend`);
      assert.ok((await strip.locator(".st-block").count()) > 0, `${label}: shots on the strip`);
    } else {
      await strip.locator("[data-needs-integration]").waitFor();
      assert.equal(await strip.locator('[data-needs-integration="Today\'s watering strip"]').count(), 1, `${label}: note in the strip`);
      assert.equal(await page.locator("[data-needs-integration]").count(), 1, `${label}: one note on the page`);
      assert.equal(await strip.locator(".st-row").count(), 0, `${label}: no tracks on 3.17`);
    }
    assert.equal(await strip.getByRole("button", { name: "Open full timeline" }).count(), 1, `${label}: open full timeline`);
    region("today strip");

    // Zone rows: gauges with targets, water against the median.
    const zone = (n) => page.locator(`article.today-zone[data-zone="${n}"]`);
    for (const n of [1, 2, 3]) {
      assert.equal(await zone(n).locator(".today-gauge").count(), 3, `${label}: zone ${n} gauges`);
      assert.equal(await zone(n).getByText(/^target /).count(), v318 ? 3 : 1, `${label}: zone ${n} targets`);
      const href = await zone(n).locator(`a[href$="#/zone/${n}"]`).getAttribute("href");
      assert.equal(new URL(href, "http://x/").searchParams.get("room"), "room:room_b_", `${label}: zone ${n} link room`);
    }
    for (const n of [1, 2])
      assert.match(await zone(n).locator("[data-today-delta]").innerText(), /^[+−±]\d+ mL vs median \d+ mL$/, `${label}: zone ${n} delta`);
    if (v318) assert.equal(await zone(3).locator("[data-today-delta]").innerText(), "Not watered today", `${label}: zone 3 not watered`);
    region("zone rows");

    // Sensors in place.
    if (v318) {
      const back = zone(2).locator('.today-sensors li[data-sensor="Back"]');
      assert.match(await back.locator(".today-sensor-reading").innerText(), /^silent 3 h$/, `${label}: silent since`);
      assert.match(
        await back.locator(".today-sensor-note").innerText(),
        new RegExp(`^Last heard ${WHEN}\\. Left out: the zone reads the front sensor only\\.$`),
        `${label}: silent card`,
      );
      assert.equal(await back.getByRole("button", { name: "Check back probe" }).count(), 1, `${label}: check back probe`);
      assert.equal(await zone(2).getByText(/back sensor/i).count(), 0, `${label}: alert said on the sensor, not again`);
      assert.equal(await zone(2).getAttribute("data-attention"), "warning", `${label}: zone 2 flagged`);
      assert.equal(await zone(1).locator(".today-sensors li").count(), 2, `${label}: zone 1 front and back`);
    }
    region("sensors");

    // Full-page shots as the page opens, before Resume.
    for (const scheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.screenshot({ path: out(`s2-full-${width}-${backend}-${scheme}.png`), fullPage: true, animations: "disabled" });
    }
    await page.emulateMedia({ colorScheme: "light" });

    // Paused zone 3: who and when, Resume, Undo.
    const paused = zone(3).locator("[data-today-paused] p").first();
    assert.match(
      await paused.innerText(),
      new RegExp(v318 ? `^Paused by Ben ${AT} \\(slab change\\)\\.$` : `^Paused ${AT}\\.$`),
      `${label}: paused text`,
    );
    assert.equal(await zone(3).locator(".today-mode").innerText(), "Paused", `${label}: paused chip`);
    await zone(3).getByRole("button", { name: "Resume zone 3" }).click();
    const toast = page.locator("[data-sonner-toast]").filter({ hasText: "Zone 3 resumed" });
    await toast.waitFor();
    assert.match(await toast.innerText(), new RegExp(`Zone 3 resumed\\. Written and read back ${HHMM}\\.`), `${label}: resume toast`);
    await zone(3).locator('.today-mode[data-mode="automated"]').waitFor();
    assert.equal(await zone(3).locator("[data-today-paused]").count(), 0, `${label}: resumed`);
    await toast.getByRole("button", { name: "Undo" }).click();
    await zone(3).locator('.today-mode[data-mode="paused"]').waitFor();
    assert.equal(await zone(3).getByRole("button", { name: "Resume zone 3" }).count(), 1, `${label}: paused again`);
    // Undo is a new change, not the Journal's pause: only its time is known.
    assert.match(await paused.innerText(), new RegExp(`^Paused at ${HHMM}\\.$`), `${label}: paused again text`);
    await page.locator("[data-sonner-toast]").filter({ hasText: "Zone 3 paused again" }).waitFor();
    region("paused zone");

    // Removed: the zone table and the AI assistant's changes.
    assert.equal(await page.locator("[data-today-table], [data-jev-today]").count(), 0, `${label}: duplicates removed`);
    assert.equal(await page.getByText("AI assistant changes today").count(), 0, `${label}: no AI changes block`);
    // The paused zone's pause line says why it has no water; no flag says it again.
    assert.equal(await zone(3).locator("[data-today-problem]").count(), 0, `${label}: paused zone not flagged for water`);

  },
});
console.log("PASS: S2 room (header, today strip, gauges, median, sensors in place, paused zone resume and undo)");
