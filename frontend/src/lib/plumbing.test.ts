import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  PLUMBING_HINTS,
  PLUMBING_LABELS,
  PLUMBING_LAYOUTS,
  hardwareForLayout,
  inferPlumbing,
  plumbingErrors,
  plumbingUses,
} from "./plumbing";

describe("declared plumbing", () => {
  it("offers exactly the layouts the integration accepts, in the same order", () => {
    const source = readFileSync(
      new URL("../../../custom_components/crop_steering/plumbing.py", import.meta.url),
      "utf8",
    );
    const block = /^PLUMBING_LAYOUTS = \{([\s\S]*?)^\}/m.exec(source)![1];
    const theirs = [...block.matchAll(/"(\w+)":\s*\((True|False),\s*(True|False)\)/g)].map((m) => [
      m[1],
      { pump: m[2] === "True", mainline: m[3] === "True" },
    ]);
    expect(theirs).toEqual(Object.entries(PLUMBING_LAYOUTS));
    expect(Object.keys(PLUMBING_LABELS)).toEqual(Object.keys(PLUMBING_LAYOUTS));
    expect(Object.keys(PLUMBING_HINTS)).toEqual(Object.keys(PLUMBING_LAYOUTS));
  });

  it("infers a prefill from the mapped switches", () => {
    expect(inferPlumbing({})).toBe("valves_only");
    expect(inferPlumbing({ pump_switch: "switch.p", main_line_switch: "" })).toBe("pump_valves");
    expect(inferPlumbing({ main_line_switch: "switch.m" })).toBe("mainline_valves");
    expect(inferPlumbing({ pump_switch: "switch.p", main_line_switch: "switch.m" })).toBe(
      "pump_mainline_valves",
    );
  });

  it("refuses a pumped room with no pump, which 2.18.0 saved and then ran dry", () => {
    expect(plumbingErrors("pump_valves", { pump_switch: "" })).toEqual([
      "This room is plumbed with a pump: choose the pump switch, or change the plumbing.",
    ]);
    expect(plumbingErrors("pump_valves", { pump_switch: "switch.p" })).toEqual([]);
  });

  it("refuses a switch the layout says the room does not have", () => {
    expect(
      plumbingErrors("valves_only", { pump_switch: "switch.p", main_line_switch: "switch.m" }),
    ).toHaveLength(2);
  });

  it("has nothing to say about a room that never declared, and asks when the answer is junk", () => {
    expect(plumbingErrors("", { pump_switch: "switch.p" })).toEqual([]);
    expect(plumbingErrors(undefined, {})).toEqual([]);
    expect(plumbingErrors("siphon", {})).toEqual(["Choose how this room is plumbed."]);
  });

  it("shows only the switches the layout has, and keeps every other mapping", () => {
    expect(plumbingUses("valves_only", "pump_switch")).toBe(false);
    expect(plumbingUses("mainline_valves", "main_line_switch")).toBe(true);
    expect(plumbingUses("valves_only", "feed_ec_sensor")).toBe(true);
    expect(plumbingUses("", "pump_switch")).toBe(true); // undeclared: both still offered
    expect(
      hardwareForLayout("mainline_valves", {
        pump_switch: "switch.p",
        main_line_switch: "switch.m",
        feed_ec_sensor: "sensor.ec",
      }),
    ).toEqual({ pump_switch: "", main_line_switch: "switch.m", feed_ec_sensor: "sensor.ec" });
  });
});
