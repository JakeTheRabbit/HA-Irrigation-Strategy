import { describe, expect, it } from "vitest";
import {
  APP_OPTIONS,
  PLACEMENTS,
  RESTORED_MANIFEST,
  placementsFor,
  FEATURES,
  GROUPS,
  controlsOf,
  featureRows,
  matches,
  registeredControl,
  resetChanges,
} from "./features";
import { buildRoom, discoverRooms, validateChange } from "./model";
import type { EntityState, States } from "./types";

const entity = (
  entity_id: string,
  state: string,
  attributes: Record<string, unknown> = {},
): EntityState => ({ entity_id, state, attributes });

function fixture(): States {
  const entries = [
    entity("sensor.crop_steering_tent_engine_config", "ready", {
      prefix: "tent_",
      slug: "tent",
      num_zones: 2,
      room_name: "Tent",
      pump: "switch.pump",
      valves: { "1": "switch.valve_1" },
    }),
    entity("switch.crop_steering_tent_engine_enabled", "on"),
    entity("switch.crop_steering_tent_zone_1_enabled", "on"),
    entity("switch.crop_steering_tent_zone_2_enabled", "on"),
    entity("switch.crop_steering_tent_ec_stacking_enabled", "off"),
    entity("switch.crop_steering_tent_zone_1_p3_dryback_hold", "off"),
    entity("switch.crop_steering_tent_zone_2_p3_dryback_hold", "on"),
    entity("switch.pump", "off"),
    entity("select.crop_steering_tent_ai_no_touch", "Off", {
      options: ["Off", "1 h", "Until lights-on", "24 h"],
    }),
    entity("number.crop_steering_tent_p3_time_between_shots", "10", {
      min: 0,
      max: 120,
      step: 1,
    }),
    entity("number.crop_steering_tent_zone_1_p3_time_between_shots", "25", {
      min: 0,
      max: 120,
      step: 1,
    }),
  ];
  return Object.fromEntries(entries.map((e) => [e.entity_id, e]));
}
const roomOf = (states: States) => buildRoom(states, discoverRooms(states)[0]);

describe("the feature registry", () => {
  it("has unique ids, known groups and one entry per control", () => {
    const ids = FEATURES.map((f) => f.id);
    expect(new Set(ids).size).toBe(ids.length);
    const groups = new Set(GROUPS.map((g) => g.id));
    for (const f of FEATURES) {
      expect(groups.has(f.group), f.id).toBe(true);
      expect(f.help.length, f.id).toBeGreaterThan(0);
    }
    const keys = FEATURES.flatMap(controlsOf).map((c) => `${c.domain}.${c.key}`);
    expect(new Set(keys).size).toBe(keys.length);
    expect(new Set(APP_OPTIONS.map((o) => o.key)).size).toBe(APP_OPTIONS.length);
  });
  it("finds room and zone controls by entity id, never another room's or hardware", () => {
    expect(registeredControl("tent_", "switch.crop_steering_tent_ec_stacking_enabled")?.zone).toBe(
      null,
    );
    expect(
      registeredControl("tent_", "number.crop_steering_tent_zone_2_p3_time_between_shots")?.zone,
    ).toBe(2);
    expect(registeredControl("tent_", "switch.crop_steering_veg_ec_stacking_enabled")).toBeNull();
    expect(registeredControl("tent_", "switch.pump")).toBeNull();
    // A zone-only switch has no room entity, and a room-only number no zone entity.
    expect(registeredControl("tent_", "switch.crop_steering_tent_p3_dryback_hold")).toBeNull();
    expect(registeredControl("tent_", "number.crop_steering_tent_zone_1_pump_prime_time")).toBeNull();
  });
});

describe("the Features page rows", () => {
  it("marks what differs from its default and resets only that", () => {
    const rows = featureRows(fixture(), "tent_", [1, 2], "switch.crop_steering_tent_engine_enabled");
    const p3 = rows.find((r) => r.feature.id === "p3")!;
    expect(p3.changed).toBe(true);
    expect(resetChanges(p3)).toEqual([
      { entityId: "number.crop_steering_tent_zone_1_p3_time_between_shots", value: 10 },
    ]);
    const hold = rows.find((r) => r.feature.id === "p3_dryback_hold")!;
    expect(hold.master?.room).toBeNull();
    expect(hold.master?.zones.map((c) => c.value)).toEqual([false, true]);
    expect(rows.find((r) => r.feature.id === "ec_stacking")!.changed).toBe(false);
    // A feature with no entity in this room is left out.
    expect(rows.some((r) => r.feature.id === "auto_setpoints")).toBe(false);
    expect(matches(p3, "rescue")).toBe(true);
    expect(matches(p3, "camera")).toBe(false);
  });
});

describe("writes allowed from the Features page", () => {
  it("accept registered switches, selects and numbers inside their limits", () => {
    const states = fixture();
    const room = roomOf(states);
    expect(
      validateChange(room, states, {
        entityId: "switch.crop_steering_tent_ec_stacking_enabled",
        value: true,
      }),
    ).toBeNull();
    expect(
      validateChange(room, states, {
        entityId: "switch.crop_steering_tent_zone_2_p3_dryback_hold",
        value: false,
      }),
    ).toBeNull();
    expect(
      validateChange(room, states, { entityId: "select.crop_steering_tent_ai_no_touch", value: "1 h" }),
    ).toBeNull();
    expect(
      validateChange(room, states, { entityId: "select.crop_steering_tent_ai_no_touch", value: "2 h" }),
    ).not.toBeNull();
    expect(
      validateChange(room, states, {
        entityId: "number.crop_steering_tent_p3_time_between_shots",
        value: 30,
      }),
    ).toBeNull();
    expect(
      validateChange(room, states, {
        entityId: "number.crop_steering_tent_p3_time_between_shots",
        value: 500,
      }),
    ).toMatch(/between/);
  });
  it("still refuse hardware", () => {
    const states = fixture();
    expect(
      validateChange(roomOf(states), states, { entityId: "switch.pump", value: true }),
    ).toMatch(/hardware/);
  });
});


describe("restored settings outside entity controls", () => {
  it("finds each room display preference through the Display settings link", () => {
    const options = RESTORED_MANIFEST.filter((row) => row.entity.includes("display (attribute "));
    expect(options).toHaveLength(11);
    for (const option of options)
      expect(PLACEMENTS.find((row) => row.entity === option.entity)?.page).toBe("settings");
  });
  it("keeps setup and overlays discoverable without making them entity writes", () => {
    expect(placementsFor("all", "camera").map((row) => row.location)).toContain("Settings > Display");
    expect(placementsFor("history", "dryback markers")[0]?.page).toBe("history/timeline");
    expect(placementsFor("history", "Per-probe grow comparison")[0]?.page).toBe("zone");
    expect(placementsFor("equipment", "ACs")[0]?.page).toBe("equipment/setup");
    expect(PLACEMENTS.some((row) => /^(switch|number|select)\.crop_steering_/.test(row.entity))).toBe(false);
    expect(placementsFor("feed", "pH role")[0]?.page).toBe("equipment/dosing");
  });
});
