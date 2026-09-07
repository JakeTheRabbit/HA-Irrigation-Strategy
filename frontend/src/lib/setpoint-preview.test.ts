import { waterParameters } from "./water-delivery";
import type { Controller } from "./types";
import { describe, expect, it } from "vitest";
import { buildRoom, discoverRooms } from "./model";
import { buildSetpointPreview, validateSetpoint } from "./setpoint-preview";
import { buildPlanningCurve } from "./planning-curve";
import type { EntityState, States } from "./types";

function fixture(prefix = "f1_") {
  const states: States = {};
  const put = (id: string, state: string, attributes: Record<string, unknown> = {}) => {
    states[id] = { entity_id: id, state, attributes } as EntityState;
  };
  put(`sensor.crop_steering_${prefix}engine_config`, "ready", { prefix, num_zones: 2 });
  const numeric = (suffix: string, value: number, min = 0, max = 100, step = 0.5) =>
    put(`number.crop_steering_${prefix}${suffix}`, String(value), { min, max, step });
  numeric("lights_on_hour", 10, 0, 23, 1);
  numeric("lights_off_hour", 22, 0, 23, 1);
  numeric("dripper_flow_rate", 4, 0.1, 20, 0.1);
  numeric("field_capacity", 70);
  for (const [key, value] of Object.entries({
    p1_target_vwc: 65,
    p2_vwc_threshold: 55,
    p1_initial_shot_size: 2,
    p2_shot_size: 3,
    p3_emergency_vwc_threshold: 38,
    p3_emergency_shot_size: 2,
    vegetative_dryback_target: 15,
    generative_dryback_target: 30,
    substrate_volume: 6.5,
    plant_count: 42,
    drippers_per_plant: 1,
  }))
    numeric(`zone_1_${key}`, value);
  numeric("zone_1_p0_maximum_wait_time", 30, 5, 300, 5);
  numeric("zone_1_p1_time_between_shots", 15, 5, 60, 5);
  numeric("zone_1_p1_maximum_shots", 8, 1, 20, 1);
  for (const mode of ["veg", "gen"])
    for (const phase of [0, 1, 2])
      numeric(`zone_1_ec_target_${mode}_p${phase}`, mode === "veg" ? 3 : 6, 0.5, 15, 0.1);
  put(`select.crop_steering_${prefix}zone_1_steering_mode`, "Generative", {
    options: ["Vegetative", "Generative"],
  });
  // Exposed legacy entities that the current controller does not consume.
  numeric("zone_1_p3_gen_last_irrigation", 180, 30, 600, 15);
  numeric("zone_1_ec_target_gen_p3", 9, 0.5, 15, 0.1);
  numeric("zone_2_p3_emergency_vwc_threshold", 25);
  const room = () => buildRoom(states, discoverRooms(states)[0]);
  return {
    states,
    room,
    put,
    numeric,
    id: (key: string) => `number.crop_steering_${prefix}${key}`,
  };
}

describe("manual setpoint preview", () => {
  it("maps actual per-zone legacy names, room sizing and light hours without unused controller fields", () => {
    const f = fixture();
    const p = buildSetpointPreview(f.room(), f.states, 1, {});
    expect(p.draft.mode).toBe("Generative");
    expect(p.draft.parameters).toMatchObject({
      dryback_target: 30,
      ec_target_p0: 6,
      ec_target_p1: 6,
      ec_target_p2: 6,
      p3_emergency_vwc_threshold: 38,
      field_capacity: 70,
      substrate_volume: 6.5,
      dripper_flow_rate: 4,
      plant_count: 42,
      p0_maximum_wait_time: 30,
    });
    expect(p.draft.parameters.p3_last_irrigation).toBeUndefined();
    expect(p.draft.parameters.ec_target_p3).toBeUndefined();
    expect([p.draft.lightsOn, p.draft.lightsOff]).toEqual([10, 22]);
    expect(p.fields.ec_target_p2.entityId).toBe(f.id("zone_1_ec_target_gen_p2"));
    expect(p.bounds.ec_target_p2).toEqual({ min: 0.5, max: 15, step: 0.1 });
  });
  it("switches the selected legacy mode locally, keeping saved mode and EC references", () => {
    const f = fixture();
    const p = buildSetpointPreview(f.room(), f.states, 1, {
      "select.crop_steering_f1_zone_1_steering_mode": { value: "Vegetative" },
      [f.id("zone_1_ec_target_veg_p2")]: { value: "3.7" },
    });
    expect(p.saved.parameters.ec_target_p2).toBe(6);
    expect(p.draft.parameters.ec_target_p2).toBe(3.7);
    expect(p.draft.parameters.dryback_target).toBe(15);
    expect(p.fields.ec_target_p2.entityId).toBe(f.id("zone_1_ec_target_veg_p2"));
    expect(f.states[f.id("zone_1_ec_target_veg_p2")].state).toBe("3");
  });
  it("isolates named rooms, zones and draft sizing overrides", () => {
    const f = fixture();
    f.put("number.crop_steering_zone_1_p1_target_vwc", "99", { min: 0, max: 100, step: 1 });
    const p = buildSetpointPreview(f.room(), f.states, 1, {
      "number.crop_steering_zone_1_p1_target_vwc": { value: "98" },
      [f.id("zone_2_p3_emergency_vwc_threshold")]: { value: "20" },
      [f.id("zone_1_substrate_volume")]: { value: "8" },
    });
    expect(p.draft.parameters.p1_target_vwc).toBe(65);
    expect(p.draft.parameters.p3_emergency_vwc_threshold).toBe(38);
    expect(p.fieldOverrides[f.id("zone_1_substrate_volume")]).toBe(8);
    expect(p.fieldOverrides[f.id("zone_1_p3_emergency_vwc_threshold")]).toBeUndefined();
  });
  it.each(["", "nonsense", "101", "38.2"])(
    "omits invalid draft %s without reverting to live value",
    (value) => {
      const f = fixture();
      const p = buildSetpointPreview(f.room(), f.states, 1, {
        [f.id("zone_1_p3_emergency_vwc_threshold")]: { value },
      });
      expect(p.saved.parameters.p3_emergency_vwc_threshold).toBe(38);
      expect(p.draft.parameters.p3_emergency_vwc_threshold).toBeUndefined();
      expect(p.fieldOverrides[f.id("zone_1_p3_emergency_vwc_threshold")]).toBeNaN();
      expect(p.issues.length).toBeGreaterThan(0);
    },
  );
  it("reacts to P3 floor edits while keeping the saved floor and shot cadence unchanged", () => {
    const f = fixture();
    const p = buildSetpointPreview(f.room(), f.states, 1, {
      [f.id("zone_1_p3_emergency_vwc_threshold")]: { value: "42.5" },
    });
    const saved = buildPlanningCurve(p.saved.parameters, p.saved.lightsOn, p.saved.lightsOff);
    const draft = buildPlanningCurve(p.draft.parameters, p.draft.lightsOn, p.draft.lightsOff);
    expect(saved.emergencyFloor).toBe(38);
    expect(draft.emergencyFloor).toBe(42.5);
    expect(draft.p1Windows).toEqual(saved.p1Windows);
  });
  it("does not invent a missing schedule, mode or missing zone target", () => {
    const f = fixture();
    delete f.states["select.crop_steering_f1_zone_1_steering_mode"];
    delete f.states[f.id("lights_on_hour")];
    delete f.states[f.id("zone_1_p1_target_vwc")];
    const p = buildSetpointPreview(f.room(), f.states, 1, {});
    expect(p.draft.mode).toBeNull();
    expect(p.draft.parameters.ec_target_p0).toBeUndefined();
    expect(p.draft.parameters.p1_target_vwc).toBeUndefined();
    expect(p.draft.lightsOn).toBeNaN();
  });
  it("uses the controller's legacy growth_stage fallback, never room steering_mode", () => {
    const f = fixture();
    delete f.states["select.crop_steering_f1_zone_1_steering_mode"];
    f.put("select.crop_steering_f1_growth_stage", "Vegetative");
    f.put("select.crop_steering_f1_steering_mode", "Generative");
    expect(buildSetpointPreview(f.room(), f.states, 1, {}).draft.parameters.ec_target_p0).toBe(3);
  });
  it("does not mask an invalid local steering-mode choice with saved mode", () => {
    const f = fixture();
    const p = buildSetpointPreview(f.room(), f.states, 1, {
      "select.crop_steering_f1_zone_1_steering_mode": { value: "" },
    });
    expect(p.draft.mode).toBeNull();
    expect(p.draft.parameters.dryback_target).toBeUndefined();
    expect(p.issues.length).toBeGreaterThan(0);
  });
  it("shows valid active-plan targets read-only, ignoring all manual drafts", () => {
    const f = fixture();
    f.put("sensor.crop_steering_f1_strategy_plan", "active", {
      enabled: true,
      snapshot_version: 1,
      room_id: "room:f1_",
      updated_at: new Date().toISOString(),
      valid_until: new Date(Date.now() + 60000).toISOString(),
      zones: [
        {
          zone_id: 1,
          status: "active",
          parameters: {
            p1_target_vwc: 62,
            p2_vwc_threshold: 55,
            p3_emergency_vwc_threshold: 38,
            dryback_target: 20,
            ec_target_p0: 3,
            ec_target_p1: 3.5,
            ec_target_p2: 4.2,
            p2_shot_size: 3,
            p1_initial_shot_size: 2,
            p3_emergency_shot_size: 2,
          },
        },
      ],
    });
    const p = buildSetpointPreview(f.room(), f.states, 1, {
      [f.id("zone_1_p1_target_vwc")]: { value: "80" },
    });
    expect(p.readOnly).toBe(true);
    expect(p.source).toBe("active-plan");
    expect(p.draft.parameters.p1_target_vwc).toBe(62);
    expect(p.draft.parameters.ec_target_p0).toBe(3);
    expect(p.draft.parameters.p1_time_between_shots).toBe(15);
    expect(p.draft.parameters.field_capacity).toBe(70);
    expect(p.draft.parameters.substrate_volume).toBe(6.5);
    expect(p.fieldOverrides).toEqual({});
    expect(p.bounds).toEqual({});
  });
  it("never displays manual fallback targets as active when the plan snapshot is invalid", () => {
    const f = fixture();
    f.put("sensor.crop_steering_f1_strategy_plan", "active", {
      enabled: true,
      room_id: "room:f1_",
    });
    const p = buildSetpointPreview(f.room(), f.states, 1, {});
    expect(p.readOnly).toBe(true);
    expect(p.source).toBe("unavailable-plan");
    expect(p.draft.parameters.p1_target_vwc).toBeUndefined();
  });
  it("validates actual HA bounds and min-anchored steps", () => {
    const f = fixture();
    const field = f.room().settings.find((s) => s.entityId === f.id("zone_1_ec_target_gen_p2"))!;
    expect(validateSetpoint(field, "0.6")).toBe("");
    expect(validateSetpoint(field, "0.55")).toContain("increments");
    expect(validateSetpoint(field, "0")).toContain("between");
  });
});

it("keeps room flow drafts below existing zone flow, using entity-specific overrides", () => {
  const f = fixture();
  f.numeric("zone_1_dripper_flow_rate", 2, 0.1, 20, 0.1);
  const p = buildSetpointPreview(f.room(), f.states, 1, {
    [f.id("dripper_flow_rate")]: { value: "8" },
  });
  expect(p.draft.parameters.dripper_flow_rate).toBe(2);
  expect(p.fieldOverrides[f.id("dripper_flow_rate")]).toBeUndefined();
  expect(p.fields.dripper_flow_rate.entityId).toBe(f.id("zone_1_dripper_flow_rate"));
});
it("uses a legacy Transition growth stage as generative, matching the controller", () => {
  const f = fixture();
  delete f.states["select.crop_steering_f1_zone_1_steering_mode"];
  f.put("select.crop_steering_f1_growth_stage", "Transition");
  expect(buildSetpointPreview(f.room(), f.states, 1, {}).draft.parameters.ec_target_p2).toBe(6);
});
it("overlays room light-hour drafts independently from the saved whole-day schedule", () => {
  const f = fixture();
  const p = buildSetpointPreview(f.room(), f.states, 1, {
    [f.id("lights_off_hour")]: { value: "20" },
  });
  expect(p.saved.lightsOff).toBe(22);
  expect(p.draft.lightsOff).toBe(20);
  expect(
    buildPlanningCurve(p.draft.parameters, p.draft.lightsOn, p.draft.lightsOff).photoperiod,
  ).toBe(10);
});

it("rejects incomplete active targets despite a fresh snapshot timestamp", () => {
  const f = fixture();
  f.put("sensor.crop_steering_f1_strategy_plan", "active", {
    enabled: true,
    snapshot_version: 1,
    room_id: "room:f1_",
    updated_at: new Date().toISOString(),
    valid_until: new Date(Date.now() + 60000).toISOString(),
    zones: [{ zone_id: 1, status: "active", parameters: { p1_target_vwc: 62 } }],
  });
  const p = buildSetpointPreview(f.room(), f.states, 1, {});
  expect(p.source).toBe("unavailable-plan");
  expect(p.draft.parameters.p1_target_vwc).toBeUndefined();
});

it("maps a legacy room duration cap and its exact-ID draft into the water preview", () => {
  const f = fixture();
  f.numeric("maximum_shot_duration", 900, 5, 3600, 1);
  const legacy = f.id("maximum_shot_duration");
  const p = buildSetpointPreview(f.room(), f.states, 1, { [legacy]: { value: "60" } });
  expect(p.saved.parameters.max_shot_duration).toBe(900);
  expect(p.draft.parameters.max_shot_duration).toBe(60);
  expect(p.fields.max_shot_duration.entityId).toBe(legacy);
  expect(p.fieldOverrides[legacy]).toBe(60);
  const c = { states: f.states, room: f.room() } as Controller;
  expect(waterParameters(c, 1, p.draft.parameters, p.fieldOverrides).max_shot_duration).toBe(60);
  const invalid = buildSetpointPreview(f.room(), f.states, 1, { [legacy]: { value: "" } });
  expect(invalid.draft.parameters.max_shot_duration).toBeUndefined();
  expect(invalid.fieldOverrides[legacy]).toBeNaN();
  expect(
    waterParameters(c, 1, invalid.draft.parameters, invalid.fieldOverrides).max_shot_duration,
  ).toBeNull();
});
it("keeps existing invalid canonical cap above legacy and ignores invented zone caps", () => {
  const f = fixture();
  f.numeric("maximum_shot_duration", 900, 5, 3600, 1);
  f.numeric("max_shot_duration", 70, 5, 3600, 1);
  f.numeric("zone_1_max_shot_duration", 5, 5, 3600, 1);
  const legacy = f.id("maximum_shot_duration");
  let p = buildSetpointPreview(f.room(), f.states, 1, { [legacy]: { value: "60" } });
  expect(p.draft.parameters.max_shot_duration).toBe(70);
  expect(p.fieldOverrides[legacy]).toBeUndefined();
  f.states[f.id("max_shot_duration")].state = "unavailable";
  p = buildSetpointPreview(f.room(), f.states, 1, { [legacy]: { value: "60" } });
  expect(p.draft.parameters.max_shot_duration).toBeUndefined();
});
