import { describe, expect, test } from "vitest";
import { createDemo } from "./demo";
import { discoverRooms } from "./model";
import { openAlerts } from "./open-alerts";
import { fakeController } from "./test-helpers";
import type { States } from "./types";

function controller(extra: States) {
  const states = { ...createDemo(Date.now()), ...extra };
  return fakeController({
    states,
    rooms: discoverRooms(states),
    roomId: "room:",
    lastUpdated: 1_000,
  });
}
const lowStock = (prefix: string): States => ({
  [`sensor.crop_steering_${prefix}stock_low`]: {
    entity_id: `sensor.crop_steering_${prefix}stock_low`,
    state: "1",
    attributes: { tanks: [{ name: "Part A", level_l: 2, batches_left: 1, low: true }] },
  },
});

describe("openAlerts", () => {
  test("openAlerts reads alerts_open and falls back to CS attention on 3.17", () => {
    // 3.18: room "room:" publishes its inbox; the stock notice is not read twice.
    const v318 = controller({
      ...lowStock(""),
      "sensor.crop_steering_alerts_open": {
        entity_id: "sensor.crop_steering_alerts_open",
        state: "2",
        attributes: {
          room_id: "room:",
          alerts: [
            {
              event_id: "e2",
              ts: "2026-10-22T11:00:00+13:00",
              code: "CS-301",
              title: "Zone 3 valve didn't open",
              zone: 3,
              entity_id: null,
              acknowledged: false,
            },
            {
              event_id: "e1",
              ts: "2026-10-22T10:00:00+13:00",
              code: null,
              title: "Feed pH above 6.2",
              zone: null,
              entity_id: "sensor.feed_ph",
              rule_id: "r1",
              acknowledged: false,
            },
            {
              event_id: "e0",
              ts: "2026-10-22T09:00:00+13:00",
              code: null,
              title: "Old",
              zone: 1,
              entity_id: null,
              acknowledged: true,
            },
          ],
        },
      },
    });
    const mine = openAlerts(v318).filter((a) => a.roomId === "room:");
    expect(mine).toEqual([
      {
        eventId: "e2",
        roomId: "room:",
        zone: 3,
        code: "CS-301",
        title: "Zone 3 valve didn't open",
        ruleId: null,
        at: Date.parse("2026-10-22T11:00:00+13:00"),
      },
      {
        eventId: "e1",
        roomId: "room:",
        zone: null,
        code: null,
        title: "Feed pH above 6.2",
        ruleId: "r1",
        at: Date.parse("2026-10-22T10:00:00+13:00"),
      },
    ]);

    // 3.17: no inbox sensor, so the room's own notices (the Today attention rule's input) stand in.
    const v317 = openAlerts(controller(lowStock("room_b_")));
    expect(v317).toEqual([
      {
        eventId: null,
        roomId: "room:room_b_",
        zone: null,
        code: null,
        title: "Stock tank running low",
        ruleId: null,
        at: 1_000,
      },
    ]);
  });

  test("an unavailable inbox falls back to the room's notices", () => {
    const c = controller({
      ...lowStock(""),
      "sensor.crop_steering_alerts_open": {
        entity_id: "sensor.crop_steering_alerts_open",
        state: "unavailable",
        attributes: { room_id: "room:" },
      },
    });
    expect(openAlerts(c).map((a) => [a.roomId, a.title])).toEqual([
      ["room:", "Stock tank running low"],
    ]);
  });
});
