import { describe, expect, it } from "vitest";
import { parseJevSetpoints } from "./jev";
import { jevChip, planSteering, steeringConsequence, TARGET_GROUPS } from "./targets";

const setpoints = (value: Record<string, unknown>) =>
  parseJevSetpoints({
    entity_id: "sensor.crop_steering_zone_1_jev",
    state: "watching",
    attributes: { setpoints: value },
  });

describe("the range chips beside the targets Jev manages", () => {
  const managed = setpoints({
    managed: true,
    home: { p2_shot_size: 5, p2_vwc_threshold: 30.5 },
    range: { p2_shot_size: [4, 6], p2_vwc_threshold: [28.5, 31.5] },
  });
  it("name Jev's range for the P2 shot size and re-water point", () => {
    expect(jevChip(managed, "p2_shot_size", "%")).toBe("Jev · 4–6 %");
    expect(jevChip(managed, "p2_vwc_threshold", "%")).toBe("Jev · 28.5–31.5 %");
  });
  it("say nothing for a target Jev does not move", () => {
    expect(jevChip(managed, "p1_target_vwc", "%")).toBeNull();
    expect(jevChip(managed, "ec_target_p2", "mS/cm")).toBeNull();
  });
  it("say nothing while Jev manages nothing on the zone, or where no controller says", () => {
    const off = setpoints({ managed: false, range: { p2_shot_size: [4, 6] } });
    expect(jevChip(off, "p2_shot_size", "%")).toBeNull();
    expect(jevChip(null, "p2_shot_size", "%")).toBeNull();
    expect(jevChip(setpoints({ managed: true }), "p2_shot_size", "%")).toBeNull();
  });
});

describe("the targets table", () => {
  it("files every target once, under the phase it acts in, P0 to P3", () => {
    expect(TARGET_GROUPS.map((group) => group.phase)).toEqual(["P0", "P1", "P2", "P3"]);
    const keys = TARGET_GROUPS.flatMap((group) => group.rows.map((row) => row.key));
    expect(new Set(keys).size).toBe(keys.length);
    expect(TARGET_GROUPS[2].rows.map((row) => row.key)).toEqual([
      "p2_vwc_threshold",
      "p2_shot_size",
      "ec_target_p2",
    ]);
  });
});

describe("the sentence under the steering select", () => {
  it("names the mode's own overnight dryback and what it does", () => {
    expect(steeringConsequence("Generative", 25)).toBe(
      "Generative: drier nights (25 % down from the peak) and pore EC allowed to build. It pushes flowering; watch the leaf tips for burn as pore EC climbs.",
    );
    expect(steeringConsequence("Vegetative", 12.5)).toMatch(
      /^Vegetative: wetter nights \(12\.5 % down from the peak\) and pore EC kept lower\./,
    );
  });
  it("leaves the number out when the zone reports none", () => {
    expect(steeringConsequence("Generative", undefined)).toMatch(/^Generative: drier nights and /);
  });
});

describe("the steering an armed grow plan sets", () => {
  const snapshot = (zone: Record<string, unknown>) => ({ zones: [{ zone_id: 1, ...zone }] });
  it("says the plan's week and which way it leans", () => {
    expect(planSteering(snapshot({ status: "active", day: 22, bias: 70 }), 1)).toBe(
      "week 4: Generative, 70 of 100",
    );
    expect(planSteering(snapshot({ status: "active", day: 1, bias: 20 }), 1)).toBe(
      "week 1: Vegetative, 20 of 100",
    );
    expect(planSteering(snapshot({ status: "active", day: 8, bias: 50 }), 1)).toBe(
      "week 2: Balanced, 50 of 100",
    );
  });
  it("says nothing for a zone the plan is not steering today", () => {
    expect(planSteering(snapshot({ status: "waiting", day: null, bias: null }), 1)).toBeNull();
    expect(planSteering(snapshot({ status: "active", day: 22, bias: 70 }), 2)).toBeNull();
    expect(planSteering(undefined, 1)).toBeNull();
  });
});
