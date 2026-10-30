/** S1 All rooms (mockup 02) and P1 (mockup 24), against frontend/dist: run after `vite build`.
 *
 * The clock is pinned to today 14:10 local, so the demo day is the same at any real hour.
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - the room headings (Room A, Room B) and each room's grow day: the room entities on 3.18 (day 38
 *   of 63), the AI assistant's stage arc on 3.17 (day 37 of 56);
 * - each zone card links to #/zone/N with its room in the query (?room=<id>), and following one
 *   (Room B zone 1, 1440, 3.18), by click or as a fresh tab on its href, opens that zone in its room;
 * - every problem sits inside its zone card; on 3.18 Room B zone 2's open alert is on that card;
 * - the queued line ("Waiting for the pump — 2nd in line") and the short last shot ("Last shot:
 *   0.96 of 1.21 L arrived (79%)") are on Room A zone 2 only, and absent on 3.17; Room B zone 2
 *   says its back sensor's trouble once;
 * - the feed tank carries the calibration-due flag on 3.18 only, its readings are not clipped, and
 *   its button's name includes them; the stock bottles (1440) or the low stock words (390) show;
 * - on 3.17 nothing says "Needs integration".
 * Also writes full-page light and dark screenshots of each run beside the harness's own. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const out = (name) =>
  new URL(`../../output/playwright/parity/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

await runParity({
  id: "s1",
  route: "/all-zones",
  mockup: "02-S1-AllRooms.png",
  phoneMockup: "24-P1-AllRooms.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const v318 = backend === "3.18";
    const desktop = width > 720;
    // The demo follows the clock: pin it to today 14:10 local, as verify-parity-i1 does, so the
    // result does not depend on the hour the check runs.
    const pinned = new Date();
    pinned.setHours(14, 10, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    const roomA = page.locator('[data-facility-room="room:"]');
    const roomB = page.locator('[data-facility-room="room:room_b_"]');
    const zone = (room, n) => page.locator(`[data-facility-zone="${room}/${n}"]`);

    // Header: room headings, grow day, drink line.
    await page.getByRole("heading", { level: 2, name: "Room A", exact: true }).waitFor();
    await page.getByRole("heading", { level: 2, name: "Room B", exact: true }).waitFor();
    const headA = await roomA.locator(".facility-room-day").innerText();
    if (v318) {
      assert.match(headA, desktop ? /^Day 38 of 63\s*· 25 days left$/ : /^Day 38\/63$/, `${label}: Room A grow day`);
      const headB = await roomB.locator(".facility-room-day").innerText();
      assert.match(headB, desktop ? /^Day 12 of 63\s*· 51 days left$/ : /^Day 12\/63$/, `${label}: Room B grow day`);
    } else {
      assert.match(headA, desktop ? /^Day 37 of 56\s*· 19 days left$/ : /^Day 37\/56$/, `${label}: Room A stage-arc day`);
      assert.equal(await roomB.locator(".facility-room-day").count(), 0, `${label}: Room B has no grow day on 3.17`);
    }
    assert.match(await roomA.innerText(), /Drunk today\s+[\d.]+ L per plant · [\d.]+ L room/, `${label}: drink line`);
    region("header");

    // Zone cards: each links to its zone page.
    for (const [room, id] of [[roomA, "room:"], [roomB, "room:room_b_"]]) {
      const hrefs = await room.locator('a[href*="#/zone/"]').evaluateAll((links) => links.map((a) => a.getAttribute("href")));
      assert.deepEqual(
        hrefs.map((href) => {
          const url = new URL(href, "http://x/dashboard.html");
          return [url.hash, url.searchParams.get("room"), url.searchParams.has("demo")];
        }),
        [1, 2, 3].map((n) => [`#/zone/${n}`, id, true]),
        `${label}: zone links carry their room`,
      );
    }
    // Problems sit inside their zone card.
    const problems = await page.locator("[data-facility-problem]").count();
    assert.equal(await page.locator("[data-facility-zone] [data-facility-problem]").count(), problems, `${label}: problems in place`);
    const queued = page.locator("[data-facility-queued]");
    const flow = page.locator("[data-facility-flow]");
    if (v318) {
      assert.equal(
        (await zone("room:room_b_", 2).locator("[data-facility-problem]").innerText()).trim(),
        "Back sensor silent 3 h, left out of the reading",
        `${label}: open alert on its zone`,
      );
      assert.equal(await zone("room:room_b_", 2).getByText(/back sensor/i).count(), 1, `${label}: back sensor said once`);
      assert.equal(await queued.count(), 1, `${label}: one queued zone`);
      assert.equal((await zone("room:", 2).locator("[data-facility-queued]").innerText()).trim(), "Waiting for the pump — 2nd in line");
      assert.equal(await flow.count(), 1, `${label}: one short shot`);
      assert.equal((await zone("room:", 2).locator("[data-facility-flow]").innerText()).trim(), "Last shot: 0.96 of 1.21 L arrived (79%)");
      if (desktop)
        assert.equal(await zone("room:", 2).getAttribute("data-last-shot"), "hollow", `${label}: hollow last shot`);
    } else {
      assert.equal(await queued.count(), 0, `${label}: no queue on 3.17`);
      assert.equal(await flow.count(), 0, `${label}: no flow ratio on 3.17`);
      assert.equal(await page.getByText("Needs integration").count(), 0, `${label}: no Needs integration`);
    }
    region("zone cards");

    // Feed tank: pH and EC, and the calibration flag on the pH where a feed probe is due.
    const tank = roomA.locator(desktop ? ".facility-tank" : ".facility-phone-feed");
    assert.match(await tank.innerText(), /pH 5\.66[\s\S]*EC 3\.06/, `${label}: feed readings`);
    assert.equal(await roomA.locator("[data-facility-due]").count(), v318 ? 1 : 0, `${label}: calibration due`);
    assert.equal(await roomB.locator("[data-facility-due]").count(), 0, `${label}: Room B not due`);
    const clipped = await tank.evaluate((el) =>
      [el, ...el.querySelectorAll("span:not(.sr-only)")]
        .filter((node) => node.scrollWidth > node.clientWidth + 1 && getComputedStyle(node).display !== "inline")
        .map((node) => node.className || node.tagName),
    );
    assert.deepEqual(clipped, [], `${label}: feed readings not clipped`);
    const name = await tank.evaluate((el) => el.textContent);
    assert.match(name, /Open Room A tank and feed:[\s\S]*pH 5\.66[\s\S]*EC 3\.06/, `${label}: tank button name has the readings`);
    if (v318) assert.match(name, /Calibration due/, `${label}: due flag in the name`);
    if (!desktop) assert.match(name, /Part B low/, `${label}: low stock in the name`);
    assert.equal(await tank.getAttribute("aria-label"), null, `${label}: no aria-label over the text`);
    region("feed tank");

    // Stock: bottles on desktop, what is low on the phone.
    if (desktop) assert.ok((await roomA.locator(".facility-stock .stock-bottle").count()) >= 4, `${label}: stock bottles`);
    else assert.match(await roomA.locator(".facility-phone-low").innerText(), /Part B low/, `${label}: Part B low`);
    region("stock");

    if (desktop && v318) {
      // The demo's timer zone shows its T badge in the room tree.
      assert.equal(await page.locator('.room-tree [data-mode="timer"]').count(), 1, `${label}: T badge`);
      // Following a zone link opens that zone in its room.
      const other = await page.context().newPage();
      await other.goto(page.url());
      const link = other.locator('[data-facility-zone="room:room_b_/1"] a[href$="#/zone/1"]');
      const href = new URL(await link.getAttribute("href"), other.url()).href;
      await link.click();
      await other.locator("[data-zone-page]").waitFor();
      const url = new URL(other.url());
      assert.equal(url.hash, "#/zone/1", `${label}: zone link hash`);
      assert.equal(url.searchParams.get("room"), "room:room_b_", `${label}: zone link room`);
      await other.close();
      // The same href in a fresh tab (ctrl-click, a copied link) opens the same room's zone.
      const tab = await page.context().newPage();
      await tab.goto(href);
      await tab.locator("[data-zone-page]").waitFor();
      assert.equal(new URL(tab.url()).searchParams.get("room"), "room:room_b_", `${label}: new tab room`);
      assert.equal(await tab.evaluate(() => document.querySelector("header")?.textContent?.includes("Room B") ?? false), true, `${label}: new tab shows Room B`);
      await tab.close();
    }

    for (const scheme of ["light", "dark"]) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.screenshot({ path: out(`s1-full-${width}-${backend}-${scheme}.png`), fullPage: true, animations: "disabled" });
    }
    await page.emulateMedia({ colorScheme: "light" });
  },
});
console.log("PASS: S1 all rooms (headings, grow day, zone links, problems in place, queue, flow, feed due, stock)");
