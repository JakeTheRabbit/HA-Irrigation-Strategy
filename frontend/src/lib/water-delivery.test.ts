import { describe, expect, it } from "vitest";
import {
  coreWaterValue,
  dailyWater,
  estimatePhaseShot,
  estimatePercent,
  estimateRuntime,
  flowInputs,
  p1WaterBudget,
  totalSubstrateL,
  waterParameters,
  type WaterParameters,
} from "./water-delivery";
import type { Controller, Zone } from "./types";
import { createDemo } from "./demo";
import { buildRoom, discoverRooms } from "./model";

const config: WaterParameters = {
  substrate_volume: 6.75,
  plant_count: 42,
  drippers_per_plant: 1,
  dripper_flow_rate: 4,
  max_shot_duration: 900,
  p1_initial_shot_size: 2,
  p1_shot_size_increment: 0.5,
  p1_maximum_shots: 6,
  p1_time_between_shots: 15,
  p2_shot_size: 5,
  p3_emergency_shot_size: 2,
  max_daily_volume: 150,
};
const flow = flowInputs(config);
const zone = (value: number | null, unit = "L") => ({ water: { value, unit } }) as Zone;

describe("runtime water estimates", () => {
  it("separates 42 pots of 6.75 L from water delivered at 4 L/h for 120 s", () => {
    expect(totalSubstrateL(6.75, 42)).toBe(283.5);
    const result = estimateRuntime(flow, 120);
    expect(result.requested!.mlPerPlant).toBeCloseTo(133.333333333, 8);
    expect(result.requested!.zoneL).toBeCloseTo(5.6, 8);
    expect(result.effective).toEqual(result.requested);
    expect(result.capped).toBe(false);
  });
  it("a 60 s cap yields 66.667 mL per plant and 2.8 L per zone", () => {
    const result = estimateRuntime({ ...flow, maxDurationS: 60 }, 120);
    expect(result.requested!.zoneL).toBeCloseTo(5.6);
    expect(result.effective!.mlPerPlant).toBeCloseTo(66.666666667, 8);
    expect(result.effective!.zoneL).toBeCloseTo(2.8);
    expect(result.effective!.seconds).toBe(60);
    expect(result.capped).toBe(true);
  });
  it("matches whole-second runtime and the engine minimum without inventing more requested water", () => {
    const fractional = estimateRuntime(flow, 120.9);
    expect(fractional.effective!.seconds).toBe(120);
    expect(fractional.rounded).toBe(true);
    const minimum = estimateRuntime(flow, 2);
    expect(minimum.effective!.seconds).toBe(5);
    expect(minimum.effective!.zoneL).toBeCloseTo((42 * 4 * 5) / 3600);
    expect(minimum.minimumApplied).toBe(true);
  });
  it("requires an explicit valid duration cap for an effective estimate", () => {
    for (const maxDurationS of [null, NaN, Infinity, 0, -1, 4]) {
      const result = estimateRuntime({ ...flow, maxDurationS }, 120);
      expect(result.requested!.zoneL).toBeCloseTo(5.6);
      expect(result.effective).toBeNull();
    }
  });
  it("rejects empty, zero, nonfinite or negative runtime and invalid dripper counts/flow", () => {
    for (const seconds of [null, NaN, Infinity, 0, -1])
      expect(estimateRuntime(flow, seconds).requested).toBeNull();
    for (const drippersPerPlant of [null, 0, -1, 1.5, Infinity]) {
      expect(estimateRuntime({ ...flow, drippersPerPlant }, 120).requested).toBeNull();
    }
    for (const flowLph of [null, 0, NaN, -1, Infinity]) {
      expect(estimateRuntime({ ...flow, flowLph }, 120).requested).toBeNull();
    }
  });
  it("a missing or invalid count hides zone litres but preserves independently calculable per-plant flow", () => {
    for (const plants of [null, 0, 1.5, Infinity]) {
      const result = estimateRuntime({ ...flow, plants }, 120);
      expect(result.effective!.zoneL).toBeNull();
      expect(result.effective!.mlPerPlant).toBeCloseTo(133.3333333);
      expect(totalSubstrateL(6.75, plants)).toBeNull();
    }
  });
  it("plant count scales zone volume, never time or per-plant delivery", () => {
    const a = estimatePercent({ ...config, plant_count: 1 }, 5);
    const b = estimatePercent({ ...config, plant_count: 42 }, 5);
    expect(a.requested!.seconds).toBeCloseTo(303.75);
    expect(a.requested!.mlPerPlant).toBeCloseTo(337.5);
    expect(b.effective!.zoneL).toBeCloseTo(a.effective!.zoneL! * 42);
    expect(b.effective!.mlPerPlant).toBe(a.effective!.mlPerPlant);
  });
  it("counts every increment and per-shot cap in the conditional P1 series", () => {
    const result = p1WaterBudget({
      ...config,
      substrate_volume: 10,
      plant_count: 2,
      dripper_flow_rate: 10,
      max_shot_duration: 60,
      p1_initial_shot_size: 1,
      p1_shot_size_increment: 1,
      p1_maximum_shots: 3,
      p1_time_between_shots: 10,
    })!;
    expect(result.requestedZoneL).toBeCloseTo(1.2);
    expect(result.effectiveMlPerPlant).toBeCloseTo(433.33333333);
    expect(result.effectiveZoneL).toBeCloseTo(0.8666666667);
    expect(result.minimumSpacingMinutes).toBe(20);
    expect(result.lastPercent).toBe(3);
    for (const p1_maximum_shots of [0, 1.5, Infinity]) {
      expect(p1WaterBudget({ ...config, p1_maximum_shots })).toBeNull();
    }
  });
});

describe("daily controller estimates", () => {
  it("divides the all-plant zone total and preserves a known zero", () => {
    expect(dailyWater(zone(5.6), 42).mlPerPlant).toBeCloseTo(133.3333333);
    expect(dailyWater(zone(5600, "mL"), 42).mlPerPlant).toBeCloseTo(133.3333333);
    expect(dailyWater(zone(0), 42)).toEqual({ zoneL: 0, plants: 42, mlPerPlant: 0 });
  });
  it("never turns unknown delivery/count or unsupported units into zero", () => {
    for (const value of [null, NaN, -1, Infinity])
      expect(dailyWater(zone(value), 42).mlPerPlant).toBeNull();
    for (const plants of [null, 0, -1, 1.5, Infinity])
      expect(dailyWater(zone(5.6), plants).mlPerPlant).toBeNull();
    expect(dailyWater(zone(5.6, "gal"), 42).zoneL).toBeNull();
  });
});

function controller() {
  return {
    room: { room: { prefix: "veg_" }, zones: [{ id: 1, fields: [] }], settings: [] },
    states: {
      "number.crop_steering_veg_zone_1_plant_count": { state: "42" },
      "number.crop_steering_veg_dripper_flow_rate": { state: "4" },
      "number.crop_steering_veg_zone_2_dripper_flow_rate": { state: "99" },
      "number.crop_steering_dripper_flow_rate": { state: "999" },
    },
  } as unknown as Controller;
}
it("uses selected room/zone, respects all draft overrides, and suppresses invalid drafts", () => {
  const c = controller();
  expect(waterParameters(c, 1).dripper_flow_rate).toBe(4);
  expect(waterParameters(c, 1).plant_count).toBe(42);
  const fields = {
    dripper_flow_rate: 8,
    plant_count: 12,
    max_shot_duration: 60,
    p1_shot_size_increment: 2,
    p1_maximum_shots: 3,
    p1_time_between_shots: 10,
    max_daily_volume: 75,
    p2_shot_size: NaN,
  };
  const result = waterParameters(c, 1, { p2_shot_size: 5, p1_initial_shot_size: 3 }, fields);
  expect(result).toMatchObject({ ...fields, p2_shot_size: null, p1_initial_shot_size: 3 });
  expect(
    waterParameters(c, 1, {}, { "number.crop_steering_veg_zone_1_plant_count": 20 }).plant_count,
  ).toBe(20);
});
it("never masks an unavailable zone value with a valid room fallback", () => {
  const c = controller();
  c.states["number.crop_steering_veg_zone_1_dripper_flow_rate"] = { state: "unavailable" } as never;
  expect(waterParameters(c, 1).dripper_flow_rate).toBeNull();
});

it("room drafts cannot override an existing zone flow, including unavailable zone readings", () => {
  const c = controller();
  const roomDraft = { "number.crop_steering_veg_dripper_flow_rate": 8 };
  expect(waterParameters(c, 1, undefined, roomDraft).dripper_flow_rate).toBe(8);
  c.states["number.crop_steering_veg_zone_1_dripper_flow_rate"] = { state: "2" } as never;
  expect(waterParameters(c, 1, undefined, roomDraft).dripper_flow_rate).toBe(2);
  c.states["number.crop_steering_veg_zone_1_dripper_flow_rate"].state = "unavailable";
  expect(waterParameters(c, 1, undefined, roomDraft).dripper_flow_rate).toBeNull();
});
it("an explicitly supplied partial plan never fills missing targets from manual settings", () => {
  const c = controller();
  c.states["number.crop_steering_veg_zone_1_p2_shot_size"] = { state: "5" } as never;
  expect(waterParameters(c, 1).p2_shot_size).toBe(5);
  expect(waterParameters(c, 1, {}).p2_shot_size).toBeNull();
  expect(waterParameters(c, 1, { p2_shot_size: 3 }).p2_shot_size).toBe(3);
  expect(waterParameters(c, 1, {}).plant_count).toBe(42);
});

it("every demo zone has explicit usable runtime and P1 budget inputs", () => {
  const states = createDemo();
  for (const room of discoverRooms(states)) {
    const c = { states, room: buildRoom(states, room) } as Controller;
    for (const zone of c.room.zones) {
      const parameters = waterParameters(c, zone.id);
      expect(estimatePercent(parameters, parameters.p1_initial_shot_size).effective).not.toBeNull();
      expect(p1WaterBudget(parameters)).not.toBeNull();
      expect(dailyWater(zone, parameters.plant_count).mlPerPlant).toBeGreaterThan(0);
    }
  }
});

it("shows configured phase sizes separately from the engine's narrower percentage limits", () => {
  const inputs = {
    ...config,
    substrate_volume: 10,
    plant_count: 2,
    dripper_flow_rate: 10,
    max_shot_duration: 3600,
  };
  const p1 = estimatePhaseShot({ ...inputs, p1_initial_shot_size: 20 }, "p1_initial_shot_size");
  expect(p1.configured.requested!.seconds).toBeCloseTo(720);
  expect(p1.configured.requested!.zoneL).toBeCloseTo(4);
  expect(p1.limit).toMatchObject({ configured: 20, value: 15, min: 0.5, max: 15, changed: true });
  expect(p1.controlled.effective!.seconds).toBe(540);
  expect(p1.controlled.effective!.zoneL).toBeCloseTo(3);
  const p2 = estimatePhaseShot({ ...inputs, p2_shot_size: 25 }, "p2_shot_size");
  expect(p2.limit.value).toBe(20);
  expect(p2.controlled.effective!.zoneL).toBeCloseTo(4);
  const p3 = estimatePhaseShot(
    { ...inputs, p3_emergency_shot_size: 0.1 },
    "p3_emergency_shot_size",
  );
  expect(p3.limit.value).toBe(0.5);
  expect(p3.controlled.effective!.mlPerPlant).toBeCloseTo(50);
  expect(
    estimatePhaseShot({ ...inputs, p2_shot_size: NaN }, "p2_shot_size").controlled.effective,
  ).toBeNull();
});
it("applies initial/increment core limits before summing a P1 ramp, not to each later shot", () => {
  const result = p1WaterBudget({
    ...config,
    substrate_volume: 10,
    plant_count: 2,
    dripper_flow_rate: 10,
    max_shot_duration: 3600,
    p1_initial_shot_size: 20,
    p1_shot_size_increment: 10,
    p1_maximum_shots: 3,
  })!;
  expect(result.requestedZoneL).toBeCloseTo(18);
  expect(result.effectiveZoneL).toBeCloseTo(12);
  expect(result.initial.value).toBe(15);
  expect(result.increment.value).toBe(5);
  expect(result.coreLastPercent).toBe(25);
  expect(result.lastPercent).toBe(40);
  const count = p1WaterBudget({ ...config, p1_maximum_shots: 41 })!;
  expect(count.count).toBe(40);
  expect(count.shotsLimit).toMatchObject({ configured: 41, value: 40, changed: true });
});
it("surfaces a configured daily budget outside the core's 10–2000 litre limits", () => {
  expect(coreWaterValue("max_daily_volume", 1)).toMatchObject({
    configured: 1,
    value: 10,
    changed: true,
  });
  expect(coreWaterValue("max_daily_volume", 2500)).toMatchObject({
    configured: 2500,
    value: 2000,
    changed: true,
  });
  expect(coreWaterValue("max_daily_volume", null).value).toBeNull();
});
