import { describe, expect, it } from "vitest";
import {
  DISPLAY_DEFAULTS,
  DISPLAY_ROWS,
  demoDisplay,
  displayEntityId,
  readDisplay,
} from "./display";
import type { EntityState } from "./types";

const entity = (state: string, attributes: Record<string, unknown> = {}): EntityState => ({
  entity_id: displayEntityId("f2_"),
  state,
  attributes,
});

describe("room display options", () => {
  it("reads every option off without a store, as the dashboard always was", () => {
    expect(readDisplay(undefined)).toEqual({
      available: false,
      revision: 0,
      options: DISPLAY_DEFAULTS,
    });
    expect(Object.values(DISPLAY_DEFAULTS).every((v) => v === false || v === "cards")).toBe(true);
  });
  it("reads an option the sensor carries, and the default for a missing or bad one", () => {
    const read = readDisplay(
      entity("3", { today_tank_readout: true, today_zone_layout: "grid", show_camera: "yes" }),
    );
    expect(read.available).toBe(true);
    expect(read.revision).toBe(3);
    expect(read.options).toEqual({ ...DISPLAY_DEFAULTS, today_tank_readout: true });
  });
  it("is unavailable while the sensor is unavailable", () => {
    expect(readDisplay(entity("unavailable")).available).toBe(false);
  });
  it("lists each row once, with STE help", () => {
    const keys = DISPLAY_ROWS.map((row) => row.key);
    expect(new Set(keys).size).toBe(keys.length);
    for (const row of DISPLAY_ROWS) {
      expect(!!row.entity || row.key in DISPLAY_DEFAULTS).toBe(true);
      expect(row.copy.tooltip.length).toBeGreaterThan(0);
    }
  });
  it("turns on the demo's options from ?display=", () => {
    const states = { [displayEntityId("f2_")]: entity("0", { ...DISPLAY_DEFAULTS }) };
    const on = demoDisplay(states, "today_tank_readout,nonsense");
    expect(on[displayEntityId("f2_")].attributes.today_tank_readout).toBe(true);
    expect(demoDisplay(states, null)).toBe(states);
    const all = readDisplay(demoDisplay(states, "all")[displayEntityId("f2_")]).options;
    expect(all.today_zone_layout).toBe("table");
  });
});
