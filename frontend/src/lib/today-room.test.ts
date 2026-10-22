import { describe, expect, it } from "vitest";
import { createDemo } from "./demo";
import { setDisplayUnits } from "./display-units";
import { discoverRooms } from "./model";
import { demoParityStatus } from "./parity-demo/status";
import type { CsEvent } from "./parity-types";
import { fakeController } from "./test-helpers";
import { clock } from "./time";
import { drinkDelta, pausedText, personName, roomZoneRows } from "./today-room";
import type { States } from "./types";

const TZ = "UTC";
const PAUSED = Date.UTC(2026, 9, 22, 9, 52);
const NOW = Date.UTC(2026, 9, 22, 14, 10);
const SWITCH = "switch.crop_steering_room_b_zone_3_enabled";

/** The demo with Room B selected, its zone 3 switched off at 09:52, and these extras. */
function roomB(extra: States = {}, recentEvents: CsEvent[] = [], base = createDemo(NOW)) {
  const states: States = { ...base, ...extra };
  states[SWITCH] = { ...states[SWITCH], state: "off", last_changed: new Date(PAUSED).toISOString() };
  return fakeController({
    states,
    rooms: discoverRooms(states),
    roomId: "room:room_b_",
    timeZone: TZ,
    recentEvents,
  });
}
const pauseEvent = (user: string | null, reason?: string): CsEvent => ({
  v: 1,
  id: "01JDEMOPAUSE",
  ts: new Date(PAUSED).toISOString(),
  room_id: "room:room_b_",
  zone: 3,
  kind: "config.changed",
  outcome: "ok",
  code: null,
  source: { actor: "manual", user_id: user },
  data: {
    store: "setup",
    section: "zones",
    diff: [{ path: "zones.3.enabled", old: true, new: false }],
    ...(reason ? { reason } : {}),
  },
});
const person = (userId: string): States => ({
  "person.ben": {
    entity_id: "person.ben",
    state: "home",
    attributes: { friendly_name: "Ben", user_id: userId },
  },
});

describe("the room page's zone rows", () => {
  it("paused zone row names who and when", () => {
    const controller = roomB(person("u-ben"), [pauseEvent("u-ben", "slab change")]);
    const row = roomZoneRows(controller, NOW).find((item) => item.zone === 3)!;
    expect(row.paused).toEqual({ by: "Ben", at: PAUSED, why: "slab change" });
    expect(pausedText(row.paused!, TZ, NOW)).toBe("Paused by Ben at 09:52 (slab change).");
    expect(roomZoneRows(controller, NOW).filter((item) => item.paused)).toHaveLength(1);
  });

  it("paused zone without a person shows time only", () => {
    // No Journal (3.17): the switch's own last change.
    const bare = roomZoneRows(roomB(), NOW).find((item) => item.zone === 3)!;
    expect(bare.paused).toEqual({ by: null, at: PAUSED, why: null });
    expect(pausedText(bare.paused!, TZ, NOW)).toBe("Paused at 09:52.");
    // A Journal user with no Home Assistant person, and no reason given: never invented.
    const unknown = roomZoneRows(roomB({}, [pauseEvent("u-gone")]), NOW).find((item) => item.zone === 3)!;
    expect(pausedText(unknown.paused!, TZ, NOW)).toBe("Paused at 09:52.");
    expect(personName(person("u-ben"), null)).toBeNull();
    expect(personName(person("u-ben"), "u-gone")).toBeNull();
    // An event older than the switch's own change is not this pause.
    const old = { ...pauseEvent("u-ben", "slab change"), ts: new Date(PAUSED - 3_600_000).toISOString() };
    expect(roomZoneRows(roomB(person("u-ben"), [old]), NOW)[2].paused).toEqual({ by: null, at: PAUSED, why: null });
  });

  it("drink delta against median is signed", () => {
    setDisplayUnits({ volume: "L" });
    expect(drinkDelta({ ml: 161, median: 160 })).toBe("+1 mL vs median 160 mL");
    expect(drinkDelta({ ml: 158, median: 160 })).toBe("−2 mL vs median 160 mL");
    expect(drinkDelta({ ml: 160.2, median: 160 })).toBe("±0 mL vs median 160 mL");
    expect(drinkDelta({ ml: 0, median: 160 })).toBe("Not watered today");
    // The median is over the zones watered today: the paused zone's nothing does not pull it down.
    const states = demoParityStatus(createDemo(NOW), NOW);
    const rows = roomZoneRows(roomB({}, [], states), NOW);
    const watered = rows.filter((row) => row.drink && row.drink.ml > 0).map((row) => row.drink!.ml);
    expect(rows[2].drink?.ml).toBe(0);
    expect(rows[0].drink?.median).toBeCloseTo((watered[0] + watered[1]) / 2);
  });

  it("sensor row carries silent-since text", () => {
    const states = demoParityStatus(createDemo(NOW), NOW);
    const rows = roomZoneRows(roomB({}, [], states), NOW);
    const back = rows[1].sensors.find((sensor) => sensor.short === "Back")!;
    expect(back.silent).toEqual({
      since: "silent 3 h",
      text: `Last heard ${clock(NOW - 3 * 3_600_000, TZ)}. Left out: the zone reads the front sensor only.`,
    });
    expect(rows[1].sensors.find((sensor) => sensor.short === "Front")!.silent).toBeNull();
    // The open alert about that sensor is said on it, not again on the row.
    expect(rows[1].view.problem).toBe("Back sensor silent 3 h, left out of the reading");
    expect(rows[1].problem).toBeNull();
    expect(rows[0].sensors.every((sensor) => sensor.silent === null)).toBe(true);
  });
});
