import { describe, expect, it, vi } from "vitest";
import { discoverRooms, buildRoom, numeric, validateChange } from "./model";
import { applyChanges, HaClient } from "./client";
import { createDemo, demoHistory } from "./demo";
import type { States, EntityState } from "./types";

const entity = (
  entity_id: string,
  state: string,
  attributes: Record<string, unknown> = {},
): EntityState => ({ entity_id, state, attributes });
function fixture(): States {
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
    }),
    entity("sensor.crop_steering_vwc_zone_1", "60"),
    entity("sensor.crop_steering_f1_vwc_zone_1", "unavailable"),
    entity("sensor.crop_steering_f1_zone_1_phase", "P1"),
    entity("sensor.crop_steering_system_zone_1_status", "F1 status"),
    entity("number.crop_steering_p1_target_vwc", "65", {
      min: 0,
      max: 100,
      step: 0.5,
    }),
    entity("number.crop_steering_f1_p1_target_vwc", "72", {
      min: 0,
      max: 100,
      step: 0.5,
    }),
    entity("input_boolean.f2_control_enabled", "on"),
    entity("switch.crop_steering_zone_1_enabled", "on"),
    entity("switch.crop_steering_zone_1_pump", "off"),
  ];
  return Object.fromEntries(entries.map((e) => [e.entity_id, e]));
}

describe("room model", () => {
  it("uses configured room names when HA gives both descriptor sensors the same generic name", () => {
    const states = fixture();
    Object.assign(states["sensor.crop_steering_engine_config"].attributes, {
      room_name: "Crop Steering",
      friendly_name: "Crop Steering Engine Configuration",
    });
    Object.assign(states["sensor.crop_steering_f1_engine_config"].attributes, {
      room_name: "  F1  ",
      friendly_name: "Crop Steering Engine Configuration",
    });
    expect(discoverRooms(states)).toEqual([
      { id: "room:", prefix: "", name: "Crop Steering" },
      { id: "room:f1_", prefix: "f1_", name: "F1" },
    ]);
    states["sensor.crop_steering_f1_engine_config"].attributes.room_name = "Flower One";
    expect(discoverRooms(states).find((room) => room.id === "room:f1_")).toEqual({
      id: "room:f1_",
      prefix: "f1_",
      name: "Flower One",
    });
  });
  it.each([undefined, null, "", "   ", 42])(
    "keeps legacy friendly-name and slug fallbacks for an invalid configured name (%s)",
    (roomName) => {
      const states = fixture();
      const attributes = states["sensor.crop_steering_f1_engine_config"].attributes;
      Object.assign(attributes, { room_name: roomName, friendly_name: "Flower 1 Engine Config" });
      expect(discoverRooms(states).find((room) => room.id === "room:f1_")?.name).toBe("Flower 1");
      delete attributes.friendly_name;
      expect(discoverRooms(states).find((room) => room.id === "room:f1_")?.name).toBe("F1");
      expect(discoverRooms(states)[0].name).toBe("Default room");
    },
  );
  it("never replaces missing F1 data with default room data", () => {
    const states = fixture();
    const rooms = discoverRooms(states);
    const f1 = buildRoom(
      states,
      rooms.find((r) => r.prefix === "f1_")!,
    );
    expect(f1.zones[0].vwc.value).toBeNull();
    expect(f1.zones[0].target.value).toBe(72);
    expect(f1.zones[0].status).toBe("F1 status");
    expect(f1.settings.map((s) => s.entityId)).not.toContain("number.crop_steering_p1_target_vwc");
    expect(
      buildRoom(
        states,
        rooms.find((r) => r.prefix === "")!,
      ).entities.map((e) => e.entity_id),
    ).not.toContain("sensor.crop_steering_system_zone_1_status");
  });
  it("requires an actual room descriptor", () => expect(discoverRooms({})).toEqual([]));
  it("selects phase-specific thresholds and leaves unresolved EC mode unknown", () => {
    const states = fixture();
    const room = discoverRooms(states)[0];
    states["sensor.crop_steering_zone_1_phase"] = entity("sensor.crop_steering_zone_1_phase", "P2");
    states["number.crop_steering_p2_vwc_threshold"] = entity(
      "number.crop_steering_p2_vwc_threshold",
      "51",
      { min: 0, max: 100, step: 0.5 },
    );
    expect(buildRoom(states, room).zones[0].target.value).toBe(51);
    expect(buildRoom(states, room).zones[0].ecTarget.value).toBeNull();
    states["sensor.crop_steering_zone_1_phase"].state = "P0";
    expect(buildRoom(states, room).zones[0].target.value).toBeNull();
  });
  it("excludes unsupported parameters and only validates discovered steering modes", () => {
    const states = fixture();
    const room = discoverRooms(states)[0];
    states["number.crop_steering_intelligence_magic"] = entity(
      "number.crop_steering_intelligence_magic",
      "5",
      { min: 0, max: 100, step: 1 },
    );
    states["select.crop_steering_steering_mode"] = entity(
      "select.crop_steering_steering_mode",
      "Vegetative",
      { options: ["Vegetative", "Generative"] },
    );
    states["select.crop_steering_recipe_stage"] = entity(
      "select.crop_steering_recipe_stage",
      "Veg",
      { options: ["Veg", "Ripen"] },
    );
    const view = buildRoom(states, room);
    expect(view.settings.some((s) => s.entityId.includes("intelligence"))).toBe(false);
    expect(view.choices).toHaveLength(1);
    expect(
      validateChange(view, states, {
        entityId: "select.crop_steering_steering_mode",
        value: "Generative",
      }),
    ).toBeNull();
    expect(
      validateChange(view, states, {
        entityId: "select.crop_steering_steering_mode",
        value: "other",
      }),
    ).toBeTruthy();
    expect(
      validateChange(view, states, {
        entityId: "select.crop_steering_recipe_stage",
        value: "Ripen",
      }),
    ).toBeTruthy();
  });
  it("surfaces the engine hardware latch and room-filters the shared activity feed", () => {
    const states = fixture();
    states["sensor.crop_steering_ai_heartbeat"] = entity(
      "sensor.crop_steering_ai_heartbeat",
      "online",
      { hardware_fault: "Valve remained on" },
    );
    states["sensor.crop_steering_activity_log"] = entity(
      "sensor.crop_steering_activity_log",
      "active",
      {
        feed: "10:30 Z1 P2 shot\n10:29 f1 Z1 P2 shot\n10:28 absent_room Z1 P2 shot",
      },
    );
    states["sensor.crop_steering_f1_activity_log"] = entity(
      "sensor.crop_steering_f1_activity_log",
      "active",
      { feed: "10:30 Z1 P2 shot\n10:29 f1 Z1 P2 shot" },
    );
    const rooms = discoverRooms(states);
    const first = buildRoom(states, rooms[0]);
    expect(first.alerts[0].severity).toBe("critical");
    expect(first.events).toHaveLength(1);
    expect(first.events[0].timestamp).toBe("10:30");
    expect(buildRoom(states, rooms[1]).events[0].timestamp).toBe("10:29");
  });
  it("handles unavailable and blank numbers without fabricating zero", () => {
    for (const state of ["", "unavailable", "unknown", "NaN", "Infinity"])
      expect(numeric(entity("sensor.x", state))).toBeNull();
    expect(numeric(entity("sensor.x", "0"))).toBe(0);
  });
  it("rejects out of bounds, off-step, foreign room and hardware writes", () => {
    const states = fixture();
    const room = buildRoom(states, discoverRooms(states)[0]);
    for (const value of [101, 64.1, "", "65", NaN])
      expect(
        validateChange(room, states, {
          entityId: "number.crop_steering_p1_target_vwc",
          value,
        }),
      ).toBeTruthy();
    expect(
      validateChange(room, states, {
        entityId: "number.crop_steering_p1_target_vwc",
        value: 64.5,
      }),
    ).toBeNull();
    expect(
      validateChange(room, states, {
        entityId: "number.crop_steering_f1_p1_target_vwc",
        value: 64.5,
      }),
    ).toBeTruthy();
    expect(
      validateChange(room, states, {
        entityId: "switch.crop_steering_zone_1_pump",
        value: true,
      }),
    ).toBeTruthy();
  });
  it("rejects a misconfigured engine flag that points directly at mapped hardware", () => {
    const states = fixture();
    states["sensor.crop_steering_engine_config"].attributes.pump =
      "input_boolean.f2_control_enabled";
    const room = buildRoom(states, discoverRooms(states)[0]);
    expect(
      validateChange(room, states, {
        entityId: "input_boolean.f2_control_enabled",
        value: true,
      }),
    ).toMatch(/hardware/);
  });
});

describe("zone valve and irrigation event telemetry", () => {
  const lastShot = "2020-07-01T12:34:56.123456+12:00";
  const producer = "sensor.crop_steering_zone_1_last_irrigation_app";
  const wrapper = "sensor.crop_steering_zone_1_last_irrigation";
  const zone = (states: States, prefix = "") =>
    buildRoom(
      states,
      discoverRooms(states).find((room) => room.prefix === prefix)!,
    ).zones[0];

  it("uses only the selected room's exact valve mapping, including external entity namespaces", () => {
    const states = fixture();
    states["sensor.crop_steering_engine_config"].attributes.valves = { "1": "switch.rack_a" };
    states["sensor.crop_steering_f1_engine_config"].attributes.valves = { "1": "switch.rack_b" };
    states["switch.rack_a"] = entity("switch.rack_a", "on");
    states["switch.rack_b"] = entity("switch.rack_b", "off");
    expect(zone(states)).toMatchObject({ valveEntity: "switch.rack_a", valveOn: true });
    expect(zone(states, "f1_")).toMatchObject({ valveEntity: "switch.rack_b", valveOn: false });
    delete states["sensor.crop_steering_f1_engine_config"].attributes.valves;
    expect(zone(states, "f1_")).toMatchObject({ valveEntity: null, valveOn: null });
    expect(zone(states).enabled).toBe(true);
  });
  it("finds a legacy engine descriptor by its declared room prefix, not its entity name", () => {
    const states = fixture();
    const config = states["sensor.crop_steering_engine_config"];
    delete states[config.entity_id];
    config.entity_id = "sensor.crop_steering_system_engine_config";
    config.attributes.valves = { "1": "switch.rack_a" };
    states[config.entity_id] = config;
    states["switch.rack_a"] = entity("switch.rack_a", "on");
    expect(zone(states)).toMatchObject({ valveEntity: "switch.rack_a", valveOn: true });
    expect(zone(states, "f1_").valveOn).toBeNull();
  });
  it.each([undefined, null, [], "switch.rack_a", {}, { "1": 12 }, { "1": "sensor.rack_a" }])(
    "does not guess a valve when its mapping is missing or malformed (%j)",
    (valves) => {
      const states = fixture();
      states["sensor.crop_steering_engine_config"].attributes.valves = valves;
      // A similarly named pump and an enabled scheduling switch prove no valve state.
      expect(zone(states)).toMatchObject({ valveEntity: null, valveOn: null });
    },
  );
  it.each([undefined, "unknown", "unavailable", "open", "", "ON"])(
    "keeps a mapped valve's unresolved state unknown (%s)",
    (value) => {
      const states = fixture();
      states["sensor.crop_steering_engine_config"].attributes.valves = { "1": "switch.rack_a" };
      if (value !== undefined) states["switch.rack_a"] = entity("switch.rack_a", value);
      expect(zone(states)).toMatchObject({ valveEntity: "switch.rack_a", valveOn: null });
    },
  );
  it("reads the retained producer event state without treating publication time as irrigation", () => {
    const states = fixture();
    states[producer] = { ...entity(producer, lastShot), last_updated: "2026-01-01T00:00:00Z" };
    states[wrapper] = entity(wrapper, "2021-01-01T00:00:00Z");
    expect(zone(states).lastIrrigation).toEqual({
      entityId: producer,
      timestamp: "2020-07-01T00:34:56.123Z",
      issue: null,
    });
    expect(zone(states, "f1_").lastIrrigation.timestamp).toBeNull();
    const f1Producer = "sensor.crop_steering_f1_zone_1_last_irrigation_app";
    states[f1Producer] = entity(f1Producer, "2021-02-03T04:05:06Z");
    expect(zone(states, "f1_").lastIrrigation.timestamp).toBe("2021-02-03T04:05:06.000Z");
  });
  it("uses the integration timestamp only when the producer entity is absent", () => {
    const states = fixture();
    states[wrapper] = entity(wrapper, lastShot);
    expect(zone(states).lastIrrigation).toMatchObject({ entityId: wrapper, issue: null });
    states[producer] = { ...entity(producer, "unavailable"), last_updated: lastShot };
    expect(zone(states).lastIrrigation).toEqual({
      entityId: producer,
      timestamp: null,
      issue: "Irrigation timestamp unavailable",
    });
  });
  it.each([
    "10:30",
    "2020-07-01",
    "2020-07-01T12:34:56",
    "2020-02-30T00:00:00Z",
    "2020-07-01T24:00:00Z",
    "not a date",
    "0",
  ])(
    "rejects invalid or ambiguous event timestamps (%s), including with valid update metadata",
    (value) => {
      const states = fixture();
      states[producer] = {
        ...entity(producer, value),
        last_updated: lastShot,
        last_changed: lastShot,
      };
      expect(zone(states).lastIrrigation).toMatchObject({
        timestamp: null,
        issue: "Invalid irrigation timestamp",
      });
    },
  );
  it("rejects future events, accepts an event at now, and keeps absent events explicit", () => {
    const now = Date.parse("2026-09-08T00:00:00Z");
    const clock = vi.spyOn(Date, "now").mockReturnValue(now);
    try {
      const states = fixture();
      expect(zone(states).lastIrrigation).toEqual({
        entityId: null,
        timestamp: null,
        issue: "No irrigation timestamp reported",
      });
      states[producer] = entity(producer, "2026-09-08T00:00:00.001Z");
      expect(zone(states).lastIrrigation).toMatchObject({
        timestamp: null,
        issue: "Irrigation timestamp is in the future",
      });
      states[producer].state = "2026-09-08T00:00:00Z";
      expect(zone(states).lastIrrigation).toMatchObject({
        timestamp: "2026-09-08T00:00:00.000Z",
        issue: null,
      });
    } finally {
      clock.mockRestore();
    }
  });
});

describe("verified transport and demo isolation", () => {
  it("reports a service success with unchanged readback as failed", async () => {
    const states = fixture();
    const room = buildRoom(states, discoverRooms(states)[0]);
    const client = {
      service: vi.fn().mockResolvedValue(undefined),
      state: vi.fn().mockResolvedValue(states["number.crop_steering_p1_target_vwc"]),
    };
    const result = await applyChanges(client, room, states, [
      { entityId: "number.crop_steering_p1_target_vwc", value: 70 },
    ]);
    expect(result.applied).toEqual([]);
    expect(result.failed[0].reason).toMatch(/readback/i);
  });
  it("does not send invalid changes", async () => {
    const states = fixture();
    const room = buildRoom(states, discoverRooms(states)[0]);
    const client = { service: vi.fn(), state: vi.fn() };
    await applyChanges(client, room, states, [
      { entityId: "switch.crop_steering_zone_1_pump", value: true },
    ]);
    expect(client.service).not.toHaveBeenCalled();
  });
  it("demo creates two isolated rooms, meaningful history and makes no requests", () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const states = createDemo();
    const rooms = discoverRooms(states);
    expect(rooms).toHaveLength(2);
    for (const room of rooms) expect(buildRoom(states, room).zones).toHaveLength(3);
    expect(
      demoHistory(states, ["sensor.crop_steering_f1_vwc_zone_1"], 24)[0].points.length,
    ).toBeGreaterThan(10);
    expect(fetch).not.toHaveBeenCalled();
    fetch.mockRestore();
  });
  it("uses a bounded fetch signal", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("[]", { status: 200 }));
    await new HaClient("http://example.test", "test").states();
    expect(fetch.mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal);
    fetch.mockRestore();
  });
});

it("exposes zone-specific dripper flow with the actual HA bounds", () => {
  const states = fixture();
  const id = "number.crop_steering_f1_zone_1_dripper_flow_rate";
  states[id] = entity(id, "4", { min: 0.1, max: 20, step: 0.1 });
  const room = buildRoom(
    states,
    discoverRooms(states).find((r) => r.prefix === "f1_")!,
  );
  expect(room.zones[0].fields.find((field) => field.entityId === id)).toMatchObject({
    value: 4,
    min: 0.1,
    max: 20,
    step: 0.1,
  });
});

it("exposes the real same-room legacy duration entity as an editable room safety field", () => {
  const states = fixture();
  const legacy = "number.crop_steering_f1_maximum_shot_duration";
  states[legacy] = entity(legacy, "900", { min: 5, max: 3600, step: 1, unit_of_measurement: "s" });
  states["number.crop_steering_maximum_shot_duration"] = entity(
    "number.crop_steering_maximum_shot_duration",
    "600",
    { min: 5, max: 3600, step: 1 },
  );
  const room = buildRoom(
    states,
    discoverRooms(states).find((r) => r.prefix === "f1_")!,
  );
  const field = room.settings.find((s) => s.entityId === legacy);
  expect(field).toMatchObject({
    entityId: legacy,
    value: 900,
    min: 5,
    max: 3600,
    step: 1,
    unit: "s",
    group: "Safety",
  });
  expect(field?.zoneId).toBeUndefined();
  expect(
    room.settings.some((s) => s.entityId === "number.crop_steering_maximum_shot_duration"),
  ).toBe(false);
});

it("does not offer a shadowed legacy cap as an effective room setting", () => {
  const states = fixture();
  const legacy = "number.crop_steering_f1_maximum_shot_duration";
  const canonical = "number.crop_steering_f1_max_shot_duration";
  states[legacy] = entity(legacy, "900", { min: 5, max: 3600, step: 1 });
  states[canonical] = entity(canonical, "unavailable", { min: 5, max: 3600, step: 1 });
  const room = buildRoom(
    states,
    discoverRooms(states).find((r) => r.prefix === "f1_")!,
  );
  expect(room.settings.find((s) => s.entityId === canonical)?.value).toBeNull();
  expect(room.settings.some((s) => s.entityId === legacy)).toBe(false);
});
