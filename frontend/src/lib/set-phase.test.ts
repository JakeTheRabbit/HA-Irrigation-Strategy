import { describe, expect, it } from "vitest";
import { buildRoom, discoverRooms, validateChange } from "./model";
import { demoReact } from "./demo";
import type { EntityState, States } from "./types";

const SET = "select.crop_steering_zone_1_set_phase";
const PHASE = "sensor.crop_steering_zone_1_phase";
const entity = (
  entity_id: string,
  state: string,
  attributes: Record<string, unknown> = {},
): EntityState => ({ entity_id, state, attributes });
const picker = entity(SET, "Keep", { options: ["Keep", "P0", "P1", "P2", "P3"] });
function fixture(extra: EntityState[] = []): States {
  const entries = [
    entity("sensor.crop_steering_engine_config", "ready", {
      prefix: "",
      slug: "",
      num_zones: 1,
      enable_flag: "input_boolean.f2_control_enabled",
    }),
    entity("input_boolean.f2_control_enabled", "on"),
    entity(PHASE, "P1"),
    ...extra,
  ];
  return Object.fromEntries(entries.map((item) => [item.entity_id, item]));
}
const view = (states: States) => buildRoom(states, discoverRooms(states)[0]);

describe("moving a zone to a phase by hand", () => {
  it("finds the zone's Set Phase select when the integration has one", () => {
    expect(view(fixture([picker])).zones[0].setPhaseEntity).toBe(SET);
    expect(view(fixture()).zones[0].setPhaseEntity).toBeNull();
  });

  it("writes a phase from P0 to P3 to it, and nothing else", () => {
    const states = fixture([picker]);
    const room = view(states);
    for (const value of ["P0", "P1", "P2", "P3"])
      expect(validateChange(room, states, { entityId: SET, value })).toBeNull();
    for (const value of ["Keep", "P4", "", true, 2])
      expect(validateChange(room, states, { entityId: SET, value })).toMatch(/phase/);
  });

  it("in the demo, moves the zone and sets the select back to Keep, as the controller does", () => {
    const states = fixture([picker]);
    const next = demoReact({ ...states, [SET]: { ...states[SET], state: "P2" } }, SET, "P2");
    expect(next[PHASE].state).toBe("P2");
    expect(next[SET].state).toBe("Keep");
    expect(demoReact(states, SET, "Keep")).toBe(states); // no request: nothing happens
  });
});
