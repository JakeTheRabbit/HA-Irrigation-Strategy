import { describe, expect, it } from "vitest";
import {
  deltaSeries,
  doubleCheck,
  liveValues,
  RULES,
  ruleRows,
  shotLog,
  stress,
  stressSources,
  svp,
  waterResponse,
  zoneGates,
} from "./sensing";
import type { EntityState, States } from "./types";

const state = (entity_id: string, value: string, attributes: Record<string, unknown> = {}): EntityState => ({
  entity_id,
  state: value,
  attributes,
});
const states = (...items: EntityState[]): States => Object.fromEntries(items.map((s) => [s.entity_id, s]));

describe("the gate list", () => {
  it("reads the controller's gates in order, and nothing from a controller without them", () => {
    const s = states(
      state("sensor.crop_steering_zone_1_waiting_for_app", "P2", {
        gates: [
          { key: "kill_switch", label: "Kill switch on", state: "hold", detail: "disabled" },
          { key: "zone_on", label: "Zone switch on", state: "pass", detail: "" },
          { nonsense: true },
        ],
      }),
      state("sensor.crop_steering_zone_2_waiting_for_app", "P2", {}),
    );
    expect(zoneGates(s, "", 1)?.map((g) => [g.key, g.state])).toEqual([
      ["kill_switch", "hold"],
      ["zone_on", "pass"],
    ]);
    expect(zoneGates(s, "", 2)).toBeNull();
  });
});

describe("the shot table", () => {
  const log = state("sensor.crop_steering_zone_1_shot_log_app", "landed", {
    shots: [{ start: "2026-10-10T12:00:00+13:00", kind: "p2_topup", litres: 1.2, verdict: "landed", ai_verdict: null }],
  });
  it("is hidden while the room's shot check is off", () => {
    expect(shotLog(states(log), "", 1)).toBeNull();
    expect(shotLog(states(log, state("select.crop_steering_shot_check", "off")), "", 1)).toBeNull();
  });
  it("reads the rows once the room asks for the table", () => {
    const rows = shotLog(states(log, state("select.crop_steering_shot_check", "table")), "", 1);
    expect(rows?.[0]).toMatchObject({ kind: "p2_topup", litres: 1.2, verdict: "landed", aiVerdict: null });
  });
});

describe("water vs VPD", () => {
  it("shows only with the room's switch on", () => {
    const sensor = state("sensor.crop_steering_zone_1_water_response_app", "0.42", { r: 0.8, n_days: 9, words: "x" });
    expect(waterResponse(states(sensor), "", 1)).toBeNull();
    const on = states(sensor, state("switch.crop_steering_water_vpd_insight", "on"));
    expect(waterResponse(on, "", 1)).toEqual({ slope: 0.42, r: 0.8, days: 9, words: "x" });
  });
});

describe("plant stress", () => {
  it("works out leaf minus air, leaf VPD and, only with the grower's baselines, CWSI", () => {
    const s = stress(24, 26, 60, -2, 4);
    expect(s.delta).toBe(-2);
    expect(s.leafVpd).toBeCloseTo(svp(24) - 0.6 * svp(26), 6);
    expect(s.cwsi).toBeCloseTo(0, 6);
    expect(stress(24, 26, null, null, null)).toMatchObject({ leafVpd: null, cwsi: null });
    expect(stress(24, 26, 60, 3, 1).cwsi).toBeNull(); // upper not above lower
  });
  it("needs the switch on and a leaf sensor, the zone's own first", () => {
    const off = states();
    const desc = { leaf_temperature_sensor: "sensor.leaf", zone_leaf_sensors: { "2": "sensor.leaf_2" } };
    expect(stressSources(off, desc, "", 1)).toBeNull();
    const on = states(state("switch.crop_steering_plant_stress_card", "on"));
    expect(stressSources(on, desc, "", 1)?.leaf).toBe("sensor.leaf");
    expect(stressSources(on, desc, "", 2)?.leaf).toBe("sensor.leaf_2");
    expect(stressSources(on, {}, "", 1)).toBeNull();
  });
  it("pairs each leaf reading with the air reading in force", () => {
    const leaf = [
      { time: 10, value: 24 },
      { time: 20, value: 25 },
    ];
    const air = [
      { time: 5, value: 26 },
      { time: 15, value: 27 },
    ];
    expect(deltaSeries(leaf, air)).toEqual([
      { time: 10, value: -2 },
      { time: 20, value: -2 },
    ]);
  });
});

describe("the rules", () => {
  it("are the generated doctrine rules, each param naming its settings", () => {
    expect(RULES.rules.length).toBeGreaterThan(100);
    expect(RULES.params.p2_shot_size.settings).toEqual(["p2_shot_size"]);
    expect(RULES.params.dryback_target.settings).toEqual([
      "vegetative_dryback_target",
      "generative_dryback_target",
    ]);
  });
  it("show each zone's live value, else the room's, and flag only what is outside the engine's bounds", () => {
    const s = states(
      state("number.crop_steering_zone_1_p2_shot_size", "5"),
      state("number.crop_steering_zone_2_p2_shot_size", "25"),
      state("number.crop_steering_maximum_ec", "9"),
    );
    expect(liveValues(s, "", [1, 2], "p2_shot_size", [0.5, 20]).map((v) => [v.zone, v.outside])).toEqual([
      [1, false],
      [2, true],
    ]);
    expect(doubleCheck(s, "", [1, 2]).map((v) => [v.setting, v.zone])).toEqual([["p2_shot_size", 2]]);
    const found = ruleRows(s, "", [1, 2], "ACT-07").filter((r) => r.rule.id === "ACT-07");
    expect(found).toHaveLength(1);
    expect(found[0].values.some((v) => v.setting === "p2_shot_size")).toBe(true);
  });
});
