import { describe, expect, it } from "vitest";
import { parseJevSetpoints } from "./jev";
import { jevChip, TARGET_GROUPS } from "./targets";

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
