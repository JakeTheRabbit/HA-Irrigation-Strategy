/** T3 System status (mockup 21), against frontend/dist: run after `vite build`. Opens
 * #/settings/system in the demo, where Room B plays F1 and its zone 2 back probe is silent with
 * CS-102 open.
 *
 * The clock is pinned to today 14:02 local, so ages and "switched HH:MM" do not depend on the hour.
 *
 * Interactions asserted, at 1440 and 390 on both backends:
 * - the health line: the ring and "System health … %: N of M devices online, controller running,
 *   …" with "Checked HH:MM";
 * - Software lists the controller app, the integration, the dashboard cards, Home Assistant and the
 *   AI assistant; Heartbeat has one block per room;
 * - every mapped device is grouped (Moisture and EC probes, Valves, Pumps, Tank and feed sensors on
 *   3.18), each row with how long ago it was seen;
 * - 3.18: the CS-102 card sits under the Room B Zone 2 back VWC row (F1 Zone 2 back), the silent row
 *   leads its group; each room's heartbeat strip draws its beats, Room B's with one missed;
 *   "What to do →" opens Help at CS-102; Acknowledge removes the card and says so;
 * - 3.17: the page is built from the entities; uptime reads "—" and the heartbeat "—", each with a
 *   compact "Needs integration 3.18".
 * Also writes a full-page screenshot of each run, before Acknowledge, beside the harness's own. */
import assert from "node:assert/strict";
import { runParity } from "./parity-harness.mjs";

const out = (name) =>
  new URL(`../../output/playwright/parity/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const HHMM = String.raw`\d{1,2}:\d{2}(?: [ap]m)?`;

await runParity({
  id: "t3",
  route: "/settings/system",
  mockup: "21-T3-System.png",
  check: async (page, { width, backend, region }) => {
    const label = `${width}px ${backend}`;
    const v318 = backend === "3.18";
    const pinned = new Date();
    pinned.setHours(14, 2, 0, 0);
    await page.clock.setFixedTime(pinned);
    await page.reload();
    await page.getByRole("heading", { level: 1, name: "System status", exact: true }).waitFor();
    const health = page.getByRole("region", { name: "System health" });
    await health.locator(".system-health-line strong").waitFor();

    // Health line.
    assert.match(
      await health.locator(".system-health-line strong").innerText(),
      /^System health [\d.]+ %: \d+ of \d+ devices online, controller running, (no open alerts|1 open alert, shown below where it happens|\d+ open alerts, each shown below where it happens)\.$/,
      `${label}: sentence`,
    );
    assert.match(await health.locator(".system-checked").innerText(), new RegExp(`^Checked ${HHMM}$`), `${label}: checked`);
    assert.equal(await health.locator(".health-ring").count(), 1, `${label}: ring`);
    region("health");

    // Software and Heartbeat.
    const software = page.getByRole("region", { name: "Software" });
    for (const name of ["Controller app (f2_control)", "Integration (crop_steering)", "Dashboard cards", "Home Assistant", "AI assistant"])
      assert.equal(await software.getByText(name, { exact: true }).count(), 1, `${label}: software ${name}`);
    region("software");
    const heartbeat = page.getByRole("region", { name: "Heartbeat" });
    assert.equal(await heartbeat.locator("[data-heartbeat]").count(), 2, `${label}: a heartbeat per room`);
    region("heartbeat");

    // Every mapped device.
    const devices = page.getByRole("region", { name: "Every mapped device" });
    const groups = await devices.locator("[data-group]").evaluateAll((els) => els.map((el) => el.getAttribute("data-group")));
    assert.deepEqual(
      groups,
      v318 ? ["Moisture and EC probes", "Valves", "Pumps", "Tank and feed sensors"] : ["Moisture and EC probes", "Valves", "Pumps"],
      `${label}: groups`,
    );
    assert.ok((await devices.locator(".system-row").count()) > 10, `${label}: rows`);
    region("devices");
    // A full-page shot as the page opens, before any alert is acknowledged.
    await page.screenshot({ path: out(`t3-full-${width}-${backend}.png`), fullPage: true, animations: "disabled" });

    if (v318) {
      const back = devices.locator('[data-entity="sensor.demo_room_b_z2_back_vwc"]');
      assert.equal(await back.locator(".system-row-name").innerText().then((t) => t.split(",")[0].trim()), "Room B Zone 2 back VWC");
      assert.equal(await back.getAttribute("data-tone"), "bad", `${label}: silent row`);
      assert.match(await back.locator(".system-row-seen").innerText(), /^3 h ago$/, `${label}: silent 3 h`);
      assert.equal(await back.locator(".system-row-pct").innerText(), "91.4%", `${label}: uptime`);
      // The entity id is on the row itself, not a hover title a phone cannot reach.
      assert.equal(await back.locator(".system-row-entity").innerText(), "sensor.demo_room_b_z2_back_vwc", `${label}: entity id`);
      // Silent first in its group.
      const firstProbe = devices.locator('[data-group="Moisture and EC probes"] .system-row').first();
      assert.equal(await firstProbe.getAttribute("data-tone"), "bad", `${label}: silent first`);
      // The CS-102 card in place, under that row.
      const item = devices.locator("li").filter({ has: page.locator('[data-entity="sensor.demo_room_b_z2_back_vwc"]') });
      const card = item.locator('[data-alert="CS-102"]');
      assert.equal(await card.count(), 1, `${label}: CS-102 under F1 Zone 2 back`);
      assert.equal(await page.locator('[data-alert="CS-102"]').count(), 1, `${label}: CS-102 once`);
      region("alert-in-place");
      // Heartbeat strips: Room B's has one missed beat.
      assert.equal(await heartbeat.locator('[data-heartbeat="Room B"] .system-strip span[data-missed]').count(), 1);
      assert.match(
        await heartbeat.locator('[data-heartbeat="Room B"] .system-beat-note').innerText(),
        /^Every 60 s · 1 missed in the last hour · read-back 1\.4 s$/,
        `${label}: beat note`,
      );
      assert.equal(await page.locator("[data-needs-integration]").count(), 0, `${label}: no needs-integration`);

      // What to do → opens Help at CS-102.
      await card.getByRole("link", { name: "What to do →" }).click();
      await page.getByRole("heading", { level: 1, name: "Help", exact: true }).waitFor();
      assert.match(page.url(), /#\/help\?code=CS-102$/, `${label}: help link`);
      region("what-to-do");
      await page.goBack();
      await page.getByRole("heading", { level: 1, name: "System status", exact: true }).waitFor();
      const again = devices.locator('li:has([data-entity="sensor.demo_room_b_z2_back_vwc"]) [data-alert="CS-102"]');
      await again.waitFor();

      // Acknowledge removes it.
      await again.getByRole("button", { name: "Acknowledge" }).click();
      await page.locator('[data-alert="CS-102"]').waitFor({ state: "detached" });
      assert.match(await page.locator(".system-said").innerText(), /^CS-102 acknowledged\./, `${label}: ack said`);
      region("acknowledge");
    } else {
      assert.equal(await page.locator('[data-needs-integration="Uptime over 7 days"]').count(), 1, `${label}: uptime needs`);
      assert.equal(await page.locator('[data-needs-integration="Heartbeat history"]').count(), 1, `${label}: heartbeat needs`);
      const pcts = await devices.locator(".system-row-pct").allInnerTexts();
      assert.ok(pcts.every((t) => t === "—"), `${label}: uptime —`);
      assert.equal(await heartbeat.locator(".system-strip").count(), 0, `${label}: no strip`);
      assert.deepEqual(await heartbeat.locator(".system-beat-note").allInnerTexts(), ["—", "—"], `${label}: heartbeat —`);
      region("v317");
    }
  },
});
