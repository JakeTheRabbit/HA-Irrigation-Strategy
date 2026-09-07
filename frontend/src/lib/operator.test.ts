import { afterEach, describe, expect, it, vi } from "vitest";
import { HaClient, type HassSession } from "./client";
import { buildRoom, discoverRooms, validateChange } from "./model";
import { createDemo } from "./demo";
import type { States } from "./types";
import type { OperatorAction } from "./operator-types";

afterEach(() => vi.restoreAllMocks());
describe("workspace response transport", () => {
  it("uses response-bearing REST even inside an inherited HA session", async () => {
    const callApi = vi
      .fn()
      .mockResolvedValue({ changed_states: [], service_response: { revision: 3 } });
    const callService = vi.fn();
    const client = new HaClient("http://ha.test", "", { callApi, callService } as HassSession);
    expect(await client.operator("strategy_get", { room_id: "room:f1_" })).toEqual({ revision: 3 });
    expect(callApi).toHaveBeenCalledWith(
      "POST",
      "services/crop_steering/strategy_get?return_response",
      { room_id: "room:f1_" },
    );
    expect(callService).not.toHaveBeenCalled();
  });
  it("rejects ordinary acknowledgements and unrecognized operations", async () => {
    const callApi = vi.fn().mockResolvedValue([]),
      callService = vi.fn();
    const client = new HaClient("http://ha.test", "", { callApi, callService } as HassSession);
    await expect(client.operator("strategy_save", {})).rejects.toThrow(/updated Crop Steering/);
    await expect(client.operator("execute_irrigation_shot" as OperatorAction, {})).rejects.toThrow(
      /Unsupported/,
    );
    expect(callApi).toHaveBeenCalledTimes(1);
  });
});
function activePlan(states: States) {
  const id = "sensor.crop_steering_strategy_plan";
  states[id] = {
    entity_id: id,
    state: "active",
    attributes: {
      snapshot_version: 1,
      room_id: "room:",
      enabled: true,
      updated_at: new Date().toISOString(),
      valid_until: new Date(Date.now() + 180000).toISOString(),
      zones: [
        {
          zone_id: 1,
          status: "active",
          parameters: {
            p1_target_vwc: 71,
            p2_vwc_threshold: 49,
            ec_target_p1: 4.2,
            ec_target_p2: 5.2,
          },
        },
      ],
    },
  };
  states["sensor.crop_steering_zone_1_phase"] = {
    entity_id: "sensor.crop_steering_zone_1_phase",
    state: "P2",
    attributes: {},
  };
  return states[id];
}
describe("active plan presentation and lifecycle", () => {
  it("shows atomic plan targets and refuses conflicting manual writes", () => {
    const states = createDemo();
    activePlan(states);
    const room = buildRoom(
      states,
      discoverRooms(states).find((r) => r.id === "room:")!,
    );
    expect(room.strategy.valid).toBe(true);
    expect(room.zones[0].target.value).toBe(49);
    expect(room.zones[0].ecTarget.value).toBe(5.2);
    expect(
      validateChange(room, states, {
        entityId: "number.crop_steering_zone_1_p1_target_vwc",
        value: 60,
      }),
    ).toMatch(/active grow plan/);
  });
  it("never presents old manual targets as active after expiry or wrong room identity", () => {
    for (const bad of ["expired", "wrong-room"]) {
      const states = createDemo(),
        snapshot = activePlan(states);
      if (bad === "expired")
        snapshot.attributes.valid_until = new Date(Date.now() - 1).toISOString();
      else snapshot.attributes.room_id = "room:f1_";
      const room = buildRoom(
        states,
        discoverRooms(states).find((r) => r.id === "room:")!,
      );
      expect(room.strategy.valid).toBe(false);
      expect(room.zones[0].target.value).toBeNull();
      expect(room.zones[0].ecTarget.value).toBeNull();
      expect(
        room.alerts.some((a) => a.severity === "critical" && a.title.includes("snapshot")),
      ).toBe(true);
    }
  });
  it("preserves zone identities after archival and hides archived rooms", () => {
    const states = createDemo(),
      descriptor = states["sensor.crop_steering_engine_config"];
    descriptor.attributes.active_zone_ids = [1, 3];
    descriptor.attributes.zone_names = { "3": "East bench" };
    const room = buildRoom(
      states,
      discoverRooms(states).find((r) => r.id === "room:")!,
    );
    expect(room.zones.map((z) => z.id)).toEqual([1, 3]);
    expect(room.zones[1].name).toBe("East bench");
    descriptor.attributes.active = false;
    expect(discoverRooms(states).some((r) => r.id === "room:")).toBe(false);
  });
});
