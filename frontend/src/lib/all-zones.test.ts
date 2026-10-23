import { describe, expect, it } from "vitest";
import { allZones, allZonesChanges } from "./all-zones";
import { createDemo } from "./demo";
import { setDisplayUnits } from "./display-units";
import { drinkLine, facilityView, zoneHref } from "./facility-view";
import { discoverRooms } from "./model";
import { fakeController } from "./test-helpers";
import type { CsEvent } from "./parity-types";
import type { States, Zone } from "./types";

const zone = (id: number, enabled: boolean | null, entity = true) =>
  ({
    id,
    name: `Zone ${id}`,
    enabled,
    enabledEntity: entity ? `switch.crop_steering_zone_${id}_enabled` : null,
  }) as Zone;

describe("the room's switch over every zone", () => {
  it("is on while any zone is on, as the entities card's header toggle is", () => {
    expect(allZones([zone(1, true), zone(2, false)])).toEqual({ checked: true, on: 1, known: 2 });
    expect(allZones([zone(1, false), zone(2, false)])).toEqual({ checked: false, on: 0, known: 2 });
  });
  it("counts only zones whose switch reads on or off, and knows nothing without one", () => {
    expect(allZones([zone(1, true), zone(2, null), zone(3, true, false)])).toEqual({
      checked: true,
      on: 1,
      known: 1,
    });
    expect(allZones([zone(1, null)]).checked).toBeNull();
    expect(allZones([]).checked).toBeNull();
  });
  it("switched off, pauses every zone that is on", () => {
    expect(allZonesChanges([zone(1, true), zone(2, false), zone(3, true)], false)).toEqual([
      {
        change: { entityId: "switch.crop_steering_zone_1_enabled", value: false },
        label: "Zone 1 scheduling",
        before: "Enabled",
        after: "Paused",
      },
      {
        change: { entityId: "switch.crop_steering_zone_3_enabled", value: false },
        label: "Zone 3 scheduling",
        before: "Enabled",
        after: "Paused",
      },
    ]);
  });
  it("switched on, switches every zone on, one paused on purpose included", () => {
    const changes = allZonesChanges([zone(1, false), zone(2, false), zone(3, null)], true);
    expect(changes.map((item) => [item.change.entityId, item.change.value, item.before])).toEqual([
      ["switch.crop_steering_zone_1_enabled", true, "Paused"],
      ["switch.crop_steering_zone_2_enabled", true, "Paused"],
    ]); // an unreadable switch is not written blind
  });
});


const put = (id: string, state: string, attributes: Record<string, unknown> = {}): States => ({
  [id]: { entity_id: id, state, attributes },
});
const fmt = { clock: () => "", number: (v: number) => String(v), perPlant: (ml: number) => `${ml} mL` };
function facility(extra: States, recentEvents: CsEvent[] = []) {
  const states = { ...createDemo(Date.now()), ...extra };
  const controller = fakeController({ states, rooms: discoverRooms(states), roomId: "room:", lastUpdated: 1_000, recentEvents });
  const rooms = facilityView(controller, fmt);
  return { a: rooms.find((r) => r.room.id === "room:")!, b: rooms.find((r) => r.room.id === "room:room_b_")! };
}

describe("all rooms: queue, flow, grow day and problems in place", () => {
  it("grow day prefers the room entities", () => {
    const { a } = facility({
      ...put("sensor.crop_steering_grow_day", "38"),
      ...put("sensor.crop_steering_days_to_harvest", "25"),
      ...put("sensor.crop_steering_stage", "Flower bulk"),
    });
    expect(a.growDay).toEqual({ day: 38, of: 63, daysLeft: 25, stage: "Flower bulk" });
  });
  it("an open-ended plan shows its own day with no length, never the stage arc's day", () => {
    const { a } = facility({
      ...put("sensor.crop_steering_grow_day", "40"),
      ...put("sensor.crop_steering_days_to_harvest", "unknown"),
      ...put("sensor.crop_steering_stage", "Flower bulk"),
    });
    expect(a.growDay).toEqual({ day: 40, of: null, daysLeft: null, stage: "Flower bulk" });
  });
  it("zone links keep the page's query and name the zone's room", () => {
    expect(zoneHref("?demo=1&room=room_b", "room:", 2)).toBe("?demo=1&room=room%3A#/zone/2");
    expect(zoneHref("", "room:room_b_", 1)).toBe("?room=room%3Aroom_b_#/zone/1");
  });
  it("falls back to computed day when grow entities absent", () => {
    // "unknown" (no active plan) reads as absent: the AI assistant's stage arc (day 37 of 56) stands in.
    const { a, b } = facility({
      ...put("sensor.crop_steering_grow_day", "unknown"),
      ...put("sensor.crop_steering_days_to_harvest", "unknown"),
      ...put("sensor.crop_steering_stage", "unknown"),
    });
    expect(a.growDay).toEqual({ day: 37, of: 56, daysLeft: 19, stage: "flower bulk" });
    expect(b.growDay).toBeNull();
  });
  it("queued place falls back to the room queue attribute: position counts the zones ahead", () => {
    const { a, b } = facility(
      put("binary_sensor.crop_steering_shot_queued", "on", {
        queue: [{ zone: 2, position: 1, requested_at: "2026-10-22T10:00:00+13:00", priority: "steering" }],
      }),
    );
    expect(a.zones.map((z) => z.queued)).toEqual([null, { place: 2 }, null]);
    expect(b.zones.every((z) => z.queued === null)).toBe(true);
  });
  it("queued place comes from the Journal's intent.queued until that zone's shot starts", () => {
    const ev = (id: string, ts: string, zone: number, kind: string, data: Record<string, unknown> = {}, room_id = "room:"): CsEvent => ({
      v: 1, id, ts, room_id, zone, kind, outcome: kind === "intent.queued" ? "queued" : "ok", code: null,
      source: { actor: "engine" }, data,
    });
    const { a, b } = facility({}, [
      ev("1", "2026-10-22T10:00:00Z", 1, "intent.queued", { position: 1 }),
      ev("2", "2026-10-22T10:00:01Z", 1, "shot.started"),
      ev("3", "2026-10-22T10:02:00Z", 3, "intent.queued", { position: 2 }),
      ev("4", "2026-10-22T10:02:00Z", 1, "intent.queued", { position: 0 }, "room:room_b_"),
    ]);
    // zone 1 waited, then its shot started: no longer waiting. Zone 3 had two zones ahead: third.
    expect(a.zones.map((z) => z.queued)).toEqual([null, null, { place: 3 }]);
    expect(b.zones.map((z) => z.queued)).toEqual([{ place: 1 }, null, null]);
  });
  it("flow ratio 0.79 marks last shot hollow and builds the arrived sentence", () => {
    setDisplayUnits({ volume: "L" });
    const { a } = facility({
      ...put("sensor.crop_steering_zone_2_flow_ratio", "0.79", { commanded_l: 2.4, metered_l: 1.9 }),
      ...put("sensor.crop_steering_zone_3_flow_ratio", "0.98", { commanded_l: 2.4, metered_l: 2.35 }),
    });
    expect(a.zones.map((z) => [z.flowRatio, z.lastShotHollow])).toEqual([
      [null, false],
      [0.79, true],
      [0.98, false],
    ]);
    expect(a.zones[1].lastShotText).toBe("Last shot: 1.9 of 2.4 L arrived (79%)");
    expect(a.zones[2].lastShotText).toBeNull();
    // The litres keep the digits they came with.
    const { a: two } = facility(
      put("sensor.crop_steering_zone_2_flow_ratio", "0.79", { commanded_l: 1.21, metered_l: 0.96 }),
    );
    expect(two.zones[1].lastShotText).toBe("Last shot: 0.96 of 1.21 L arrived (79%)");
  });
  it("problem comes from openAlerts for that zone", () => {
    const { a, b } = facility({
      ...put("sensor.crop_steering_room_b_alerts_open", "1", {
        alerts: [
          { event_id: "e1", ts: "2026-10-22T10:00:00+13:00", code: "CS-406", title: "Back sensor silent 3 h, left out of the reading", zone: 2, acknowledged: false },
          { event_id: "e0", ts: "2026-10-22T09:00:00+13:00", code: "CS-205", title: "Older", zone: 2, acknowledged: false },
        ],
      }),
      ...put("sensor.crop_steering_alerts_open", "0", { alerts: [] }),
    });
    expect(b.zones.map((z) => z.problem)).toEqual([null, "Back sensor silent 3 h, left out of the reading", null]);
    expect(a.zones.map((z) => z.problem)).toEqual([null, null, null]);
  });
  it("problem falls back to the zone's reading issue", () => {
    // With an empty inbox (3.18); on 3.17 the room's sensor notice is the open alert.
    const { a } = facility({
      ...put("sensor.crop_steering_vwc_zone_1", "unavailable"),
      ...put("sensor.crop_steering_alerts_open", "0", { alerts: [] }),
    });
    expect(a.zones[0].problem).toBe("Moisture probe not reporting");
  });
  it("feed calibration due flag from binary_sensor calibration_due", () => {
    const { a, b } = facility({
      ...put("binary_sensor.crop_steering_calibration_due", "on", { probes: ["feed_ph"] }),
      ...put("binary_sensor.crop_steering_room_b_calibration_due", "off"),
    });
    expect([a.feedCalibrationDue, b.feedCalibrationDue]).toEqual([true, false]);
  });
  it("drink line uses formatVolume", () => {
    setDisplayUnits({ volume: "L" });
    expect(drinkLine(24.8, 0.21)).toEqual({ perPlant: "0.21 L", room: "24.8 L" });
    expect(drinkLine(24.8, null)).toEqual({ perPlant: null, room: "24.8 L" });
    expect(drinkLine(null, null)).toBeNull();
    setDisplayUnits({ volume: "gal" });
    expect(drinkLine(37.85411784, 3.785411784)).toEqual({ perPlant: "1.00 gal", room: "10.0 gal" });
    setDisplayUnits({ volume: "L" });
  });
});
