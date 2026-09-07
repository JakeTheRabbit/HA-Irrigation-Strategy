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
