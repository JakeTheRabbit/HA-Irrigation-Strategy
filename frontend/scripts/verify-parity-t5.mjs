/** T5 Dashboards & display (mockup 23), against frontend/dist: run after `vite build`. Opens
 * #/settings in the demo.
 *
 * The clock is pinned to today 14:10 local, so every receipt reads "… 14:10" at any real hour.
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - the Units panel has EC, Temperature, Volume and Clock rows, each with its live example, and the
 *   footnote; 3.18 says "Shown on every page and phone for this room", 3.17 "Saved on this browser
 *   only until integration 3.18";
 * - PPM 500 → "Saved and read back 14:10", the EC example turns to ppm; Undo puts mS/cm back ("Put
 *   back and read back 14:10"); PPM 500 again, and #/all-zones then shows ppm and no mS/cm (the
 *   Task 5 store, from the room's display store on 3.18, from this browser on 3.17);
 * - Where the app opens: choosing a view says "Saved and read back 14:10";
 * - Wall and tablet dashboards (3.18): three template cards; Room tablet's "Create in Home
 *   Assistant" → "Created … 14:10 as /crop-steering-room_tablet-1", "Open in Home Assistant" and
 *   "Create again"; on 3.17 the "Needs integration 3.18" note sits in the dashboards region;
 * - "Keep this screen on while open" shows only where the browser has Wake Lock;
 * - "More display options" starts closed and opens to the connection, appearance and display
 *   options. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

await runParity({
  id: "t5",
  route: "/settings",
  mockup: "23-T5-Dashboards.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const v318 = backend === "3.18";
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    await page.getByRole("heading", { level: 1, name: "Dashboards & display", exact: true }).waitFor();

    // Units.
    const units = page.locator("[data-unit-settings]");
    await units.waitFor();
    region("units");
    assert.equal(
      (await units.locator(".unit-head p").innerText()).trim(),
      v318 ? "Shown on every page and phone for this room" : "Saved on this browser only until integration 3.18",
      `${label}: units scope`,
    );
    assert.deepEqual(await units.locator(".unit-label").allInnerTexts(), ["EC", "Temperature", "Volume", "Clock"]);
    for (const example of ["ec", "temp", "volume", "clock"])
      assert.ok((await units.locator(`[data-unit-example="${example}"]`).innerText()).trim(), `${label}: ${example} example`);
    assert.match(await units.locator(".unit-foot").innerText(), /^Display only\. Readings stay stored in mS\/cm, °C and litres/);
    const ec = units.locator('[data-unit="ec_unit"]');
    const ecExample = ec.locator("[data-unit-example]");
    assert.match(await ecExample.innerText(), /mS\/cm/, `${label}: EC in mS/cm first`);
    await ec.getByRole("button", { name: "PPM 500", exact: true }).click();
    await ec.getByText("Saved and read back 14:10").waitFor();
    assert.match(await ecExample.innerText(), /\d ppm/, `${label}: EC example in ppm`);
    assert.equal(await ec.getByRole("button", { name: "PPM 500", exact: true }).getAttribute("aria-pressed"), "true");
    await ec.getByRole("button", { name: "Undo", exact: true }).click();
    await ec.getByText("Put back and read back 14:10").waitFor();
    assert.match(await ecExample.innerText(), /mS\/cm/, `${label}: undo puts mS/cm back`);
    await ec.getByRole("button", { name: "PPM 500", exact: true }).click();
    await ec.getByText("Saved and read back 14:10").waitFor();

    // Where the app opens.
    const opens = page.locator(".where-opens");
    region("where the app opens");
    await page.locator("#landing-view").selectOption("history/water");
    await opens.getByText("Saved and read back 14:10").waitFor();
    await page.locator("#landing-view").selectOption("all-zones");

    // Wall and tablet dashboards.
    const walls = page.locator("[data-wall-dashboards]");
    region("wall and tablet dashboards");
    if (v318) {
      await walls.locator(".wall-card").first().waitFor();
      assert.deepEqual(await walls.locator(".wall-card h3").allInnerTexts(), ["Facility wall", "Room tablet", "Dosing station"]);
      const tablet = walls.locator('[data-template="room_tablet"]');
      await tablet.getByRole("button", { name: "Create in Home Assistant", exact: true }).click();
      const created = tablet.locator(".wall-created");
      await created.waitFor();
      assert.match(await created.innerText(), /^Created .*14:10 as \/crop-steering-room_tablet-1\s*Open in Home Assistant$/, `${label}: created line`);
      assert.equal(await created.getByRole("link", { name: "Open in Home Assistant" }).getAttribute("href"), "/crop-steering-room_tablet-1");
      await tablet.getByRole("button", { name: "Create again", exact: true }).waitFor();
    } else {
      await walls.locator('[data-needs-integration="Wall and tablet dashboards"]').waitFor();
      assert.equal(await walls.locator(".wall-card").count(), 0, `${label}: no templates on 3.17`);
    }

    // Keep the screen on: only where Wake Lock exists.
    const wakeLock = await page.evaluate(() => "wakeLock" in navigator && !!navigator.wakeLock);
    assert.equal(await page.getByText("Keep this screen on while open", { exact: true }).count(), wakeLock ? 1 : 0);

    // More display options.
    const more = page.locator("details.more-display");
    region("more display options");
    assert.equal(await more.evaluate((d) => d.open), false, `${label}: more options closed`);
    await more.locator("summary").click();
    await more.getByRole("heading", { name: "Home Assistant connection" }).waitFor();
    await more.getByRole("heading", { name: "Appearance" }).waitFor();
    await more.locator("[data-display-settings]").waitFor();

    // The rest of the app follows the units.
    await page.evaluate(() => (location.hash = "#/all-zones"));
    await page.waitForFunction(() => /\d ppm/.test(document.querySelector("main")?.innerText ?? ""));
    assert.doesNotMatch(await page.locator("main").innerText(), /mS\/cm/, `${label}: all rooms in ppm only`);
    region("all rooms in ppm");

    await page.evaluate(() => (location.hash = "#/settings"));
    await page.getByRole("heading", { level: 1, name: "Dashboards & display", exact: true }).waitFor();
    await page.evaluate(() => scrollTo(0, 0));
  },
});
console.log("PASS: T5 dashboards & display (units + undo + all rooms in ppm, where the app opens, wall dashboards, more options)");
