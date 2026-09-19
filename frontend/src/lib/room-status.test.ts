import { afterEach, describe, expect, it, vi } from "vitest";
import { buildRoom, discoverRooms, roomIsActive, validateChange } from "./model";
import { applyChanges } from "./client";
import { createDemo, demoHistory } from "./demo";
import { ControllerStore } from "./use-controller";
import { sensorStats } from "./sensor-context";
import type { EntityState, States } from "./types";

const entity = (
  entity_id: string,
  state: string,
  attributes: Record<string, unknown> = {},
): EntityState => ({ entity_id, state, attributes });
function fixture(extra: EntityState[] = []): States {
  const entries = [
    entity("sensor.crop_steering_engine_config", "ready", {
      prefix: "",
      slug: "",
      num_zones: 1,
      enable_flag: "input_boolean.f2_control_enabled",
    }),
    entity("sensor.crop_steering_f1_engine_config", "ready", {
      prefix: "f1_",
      slug: "f1",
      num_zones: 1,
      enable_flag: "switch.crop_steering_f1_engine_enabled",
    }),
    entity("input_boolean.f2_control_enabled", "on"),
    entity("switch.crop_steering_f1_engine_enabled", "on"),
    // No probe readings: an active room raises a "sensor data unavailable" warning.
    entity("sensor.crop_steering_zone_1_status", "Holding"),
    entity("sensor.crop_steering_f1_zone_1_status", "Fault: valve blocked"),
    ...extra,
  ];
  return Object.fromEntries(entries.map((item) => [item.entity_id, item]));
}
const room = (states: States, id = "room:") =>
  buildRoom(
    states,
    discoverRooms(states).find((item) => item.id === id)!,
  );

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("room on/off status", () => {
  it("treats a room without the switch as on and exposes no control", () => {
    const view = room(fixture());
    expect(view.roomActive).toBe(true);
    expect(view.roomActiveEntity).toBeNull();
    expect(view.zones[0].status).toBe("Holding");
    expect(view.alerts.some((alert) => /sensor data unavailable/.test(alert.title))).toBe(true);
  });
  it("reads the room switch for the default and named rooms independently", () => {
    const states = fixture([
      entity("switch.crop_steering_room_active", "on"),
      entity("switch.crop_steering_f1_room_active", "off"),
    ]);
    expect(room(states).roomActive).toBe(true);
    expect(room(states).roomActiveEntity).toBe("switch.crop_steering_room_active");
    expect(room(states, "room:f1_").roomActive).toBe(false);
    expect(room(states, "room:f1_").roomActiveEntity).toBe("switch.crop_steering_f1_room_active");
    const [first, second] = discoverRooms(states);
    expect(roomIsActive(states, first)).toBe(true);
    expect(roomIsActive(states, second)).toBe(false);
  });
  it("keeps an off room in the room picker, unlike an archived room", () => {
    const states = fixture([entity("switch.crop_steering_f1_room_active", "off")]);
    expect(discoverRooms(states).map((item) => item.id)).toEqual(["room:", "room:f1_"]);
    states["sensor.crop_steering_f1_engine_config"].attributes.active = false;
    expect(discoverRooms(states).map((item) => item.id)).toEqual(["room:"]);
  });
  it("shows zones as Room off and suppresses derived alerts for an off room", () => {
    const states = fixture([
      entity("switch.crop_steering_f1_room_active", "off"),
      entity("sensor.crop_steering_f1_ai_heartbeat", "online", {
        last_beat: "2020-01-01T00:00:00Z",
      }),
    ]);
    const view = room(states, "room:f1_");
    expect(view.zones.map((zone) => zone.status)).toEqual(["Room off"]);
    expect(view.alerts).toEqual([]);
    // The same room raises its warnings again as soon as it is switched on.
    states["switch.crop_steering_f1_room_active"].state = "on";
    const active = room(states, "room:f1_");
    expect(active.zones[0].status).toBe("Fault: valve blocked");
    expect(active.alerts.length).toBeGreaterThan(0);
  });
  it("still reports stuck hardware in an off room", () => {
    const states = fixture([
      entity("switch.crop_steering_room_active", "off"),
      entity("sensor.crop_steering_ai_heartbeat", "online", {
        hardware_fault: "Valve 2 did not close",
      }),
    ]);
    expect(room(states).alerts.map((alert) => alert.id)).toEqual(["room:-hardware-fault"]);
  });
  it("never hides alerts when the switch state is unknown", () => {
    const states = fixture([entity("switch.crop_steering_room_active", "unavailable")]);
    const view = room(states);
    expect(view.roomActive).toBe(true);
    expect(view.roomActiveEntity).toBe("switch.crop_steering_room_active");
    expect(view.alerts.length).toBeGreaterThan(0);
  });
  it("allows only this room's on/off and auto-setpoint switches to be written", () => {
    const states = fixture([
      entity("switch.crop_steering_room_active", "on"),
      entity("switch.crop_steering_auto_setpoints", "off"),
      entity("switch.crop_steering_f1_room_active", "on"),
      entity("switch.crop_steering_f1_auto_setpoints", "off"),
    ]);
    const view = room(states);
    expect(
      validateChange(view, states, { entityId: "switch.crop_steering_room_active", value: false }),
    ).toBeNull();
    expect(
      validateChange(view, states, {
        entityId: "switch.crop_steering_auto_setpoints",
        value: true,
      }),
    ).toBeNull();
    for (const entityId of [
      "switch.crop_steering_f1_room_active",
      "switch.crop_steering_f1_auto_setpoints",
    ])
      expect(validateChange(view, states, { entityId, value: false })).toMatch(/not an editable/);
    expect(
      validateChange(view, states, { entityId: "switch.crop_steering_room_active", value: 0 }),
    ).toMatch(/not an editable/);
  });
  it("switches the room off through turn_off and confirms it by readback", async () => {
    const states = fixture([entity("switch.crop_steering_room_active", "on")]);
    const service = vi.fn().mockResolvedValue(undefined);
    const state = vi.fn().mockResolvedValue(entity("switch.crop_steering_room_active", "off"));
    const result = await applyChanges({ service, state }, room(states), states, [
      { entityId: "switch.crop_steering_room_active", value: false },
    ]);
    expect(service).toHaveBeenCalledWith("switch", "turn_off", {
      entity_id: "switch.crop_steering_room_active",
    });
    expect(result).toEqual({ applied: ["switch.crop_steering_room_active"], failed: [] });
    state.mockResolvedValue(entity("switch.crop_steering_room_active", "on"));
    const unconfirmed = await applyChanges({ service, state }, room(states), states, [
      { entityId: "switch.crop_steering_room_active", value: false },
    ]);
    expect(unconfirmed.applied).toEqual([]);
    expect(unconfirmed.failed[0].reason).toMatch(/readback/i);
  });
});

describe("auto setpoints in the room model", () => {
  it("hides the control when the switch is missing", () => {
    const view = room(fixture());
    expect(view.autoSetpoints).toEqual({ entityId: null, enabled: null });
    expect(view.zones[0].auto).toBeNull();
  });
  it("reads the room switch and each zone's supervisor sensor", () => {
    const states = fixture([
      entity("switch.crop_steering_auto_setpoints", "on"),
      entity("sensor.crop_steering_zone_1_auto_setpoints", "tracking", {
        learned_peak: 35.9,
        managed: ["number.crop_steering_zone_1_p1_target_vwc"],
      }),
    ]);
    const view = room(states);
    expect(view.autoSetpoints).toEqual({
      entityId: "switch.crop_steering_auto_setpoints",
      enabled: true,
    });
    expect(view.zones[0].auto).toMatchObject({
      state: "tracking",
      learnedPeak: 35.9,
      managed: ["number.crop_steering_zone_1_p1_target_vwc"],
    });
    expect(room(states, "room:f1_").autoSetpoints.entityId).toBeNull();
  });
});

describe("demo fixtures for room status, auto setpoints and sensor history", () => {
  it("ships both demo rooms switched on with the new controls present", () => {
    const states = createDemo();
    for (const item of discoverRooms(states)) {
      const view = buildRoom(states, item);
      expect(view.roomActive).toBe(true);
      expect(view.roomActiveEntity).toBe(`switch.crop_steering_${item.prefix}room_active`);
      expect(view.autoSetpoints.entityId).toBe(`switch.crop_steering_${item.prefix}auto_setpoints`);
      expect(view.zones.every((zone) => zone.auto !== null)).toBe(true);
      expect(view.settings.some((field) => field.entityId.endsWith("_field_capacity"))).toBe(true);
      expect(view.settings.some((field) => field.entityId.endsWith("_maximum_ec"))).toBe(true);
    }
    const managed = buildRoom(states, discoverRooms(states)[0]).zones[0].auto!.managed;
    expect(managed.length).toBeGreaterThan(0);
    expect(managed.every((id) => !!states[id])).toBe(true);
  });
  it("switching a demo room off calms it and switching it on restores it", async () => {
    vi.stubGlobal("window", {
      location: { origin: "http://example.test", hostname: "example.test", href: "", search: "" },
      history: { replaceState: vi.fn() },
    });
    const store = new ControllerStore(true);
    const id = store.getSnapshot().room.roomActiveEntity!;
    const off = await store.getSnapshot().write([{ entityId: id, value: false }]);
    expect(off).toEqual({ applied: [id], failed: [] });
    expect(store.getSnapshot().room.roomActive).toBe(false);
    expect(store.getSnapshot().room.alerts).toEqual([]);
    expect(store.getSnapshot().room.zones.every((zone) => zone.status === "Room off")).toBe(true);
    expect(store.getSnapshot().rooms).toHaveLength(2);
    await store.getSnapshot().write([{ entityId: id, value: true }]);
    expect(store.getSnapshot().room.roomActive).toBe(true);
  });
  it("turning demo auto setpoints off stops every zone supervisor", async () => {
    vi.stubGlobal("window", {
      location: { origin: "http://example.test", hostname: "example.test", href: "", search: "" },
      history: { replaceState: vi.fn() },
    });
    const store = new ControllerStore(true);
    const id = store.getSnapshot().room.autoSetpoints.entityId!;
    expect(store.getSnapshot().room.autoSetpoints.enabled).toBe(true);
    await store.getSnapshot().write([{ entityId: id, value: false }]);
    expect(store.getSnapshot().room.zones.map((zone) => zone.auto!.state)).toEqual([
      "off",
      "off",
      "off",
    ]);
    await store.getSnapshot().write([{ entityId: id, value: true }]);
    expect(store.getSnapshot().room.zones.every((zone) => zone.auto!.state === "learning")).toBe(
      true,
    );
  });
  it("generates plausible day-cycle history that ends at the live reading", () => {
    const now = Date.parse("2026-09-08T01:00:00Z");
    const states = createDemo(now);
    const vwcId = "sensor.crop_steering_vwc_zone_1",
      ecId = "sensor.crop_steering_ec_zone_1";
    const [vwc, ec] = demoHistory(states, [vwcId, ecId], 72, now);
    expect(vwc.points.length).toBeGreaterThan(200);
    expect(vwc.points.length).toBeLessThanOrEqual(1200);
    expect(vwc.points.at(-1)!.value).toBeCloseTo(Number(states[vwcId].state), 1);
    expect(ec.points.at(-1)!.value).toBeCloseTo(Number(states[ecId].state), 1);
    const timeZone = "Pacific/Auckland";
    const vwcStats = sensorStats(vwc, { hours: 72, now, timeZone })!;
    const ecStats = sensorStats(ec, { hours: 72, now, timeZone })!;
    // A daily irrigation and dryback swing, not a flat line or noise.
    expect(vwcStats.peak.value - vwcStats.trough.value).toBeGreaterThan(5);
    expect(vwcStats.peak.value - vwcStats.trough.value).toBeLessThan(25);
    expect(vwcStats.trough.value).toBeGreaterThan(20);
    expect(vwcStats.peak.value).toBeLessThan(90);
    expect(ecStats.peak.value - ecStats.trough.value).toBeGreaterThan(0.2);
    expect(ecStats.trough.value).toBeGreaterThan(0.5);
    expect(vwcStats.days).toBeGreaterThanOrEqual(3);
    // Deterministic for a fixed clock, and distinct between zones.
    expect(demoHistory(states, [vwcId], 72, now)[0].points).toEqual(vwc.points);
    const other = demoHistory(states, ["sensor.crop_steering_vwc_zone_2"], 72, now)[0];
    expect(other.points[10].value).not.toBe(vwc.points[10].value);
    // Seven days stay small enough to chart without client-side thinning.
    expect(demoHistory(states, [vwcId], 168, now)[0].points.length).toBeLessThanOrEqual(1200);
  });
});
