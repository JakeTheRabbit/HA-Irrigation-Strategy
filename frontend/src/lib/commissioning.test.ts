import { describe, expect, it } from "vitest";
import {
  MARK_SYMBOL,
  WIZARD_STEPS,
  needsWizard,
  stepMark,
  switchOn,
  warnings,
} from "./commissioning";
import type { Commissioning, CommissioningCheck, SetupRoom } from "./operator-types";

const check = (
  id: CommissioningCheck["id"],
  blocking: boolean,
  problems: string[] = [],
): CommissioningCheck => ({
  id,
  step: WIZARD_STEPS.find((s) => s.check === id)!.step,
  ok: !problems.length,
  blocking,
  problems,
});

function status(problems: Partial<Record<CommissioningCheck["id"], string[]>> = {}): Commissioning {
  const checks = [
    check("controller", false, problems.controller),
    check("room", false, problems.room),
    check("valves", true, problems.valves),
    check("probes", true, problems.probes),
    check("sizing", false, problems.sizing),
    check("test_shot", true, problems.test_shot),
  ];
  return {
    commissioned: false,
    ready: checks.every((c) => !c.blocking || c.ok),
    waiting_for: null,
    checks,
    draft: { water_seen: {}, sizing_confirmed: false },
  };
}

describe("the setup wizard's Switch on", () => {
  it("is enabled once every safety check passes", () => {
    expect(switchOn(status())).toEqual({ enabled: true, reason: null });
  });

  it.each([
    ["valves", "Zone 2: select a valve", "Valves & pump: Zone 2: select a valve"],
    [
      "valves",
      "switch.zone_1_valve must read OFF before changing setup (it is ON: turn it off, then submit again)",
      "Valves & pump: switch.zone_1_valve must read OFF before changing setup (it is ON: turn it off, then submit again)",
    ],
    [
      "probes",
      "Zone 1: sensor.zone_1_ec reports in 'ppm', which can't be read as EC",
      "Probes: Zone 1: sensor.zone_1_ec reports in 'ppm', which can't be read as EC",
    ],
    ["test_shot", "Zone 1: run a test shot", "Test shot: Zone 1: run a test shot"],
    [
      "test_shot",
      "Zone 1: confirm water reached the drippers",
      "Test shot: Zone 1: confirm water reached the drippers",
    ],
  ] as const)("stays disabled while %s fails, and names it", (id, problem, reason) => {
    expect(switchOn(status({ [id]: [problem] }))).toEqual({ enabled: false, reason });
  });

  it("names the earliest failing safety step", () => {
    const result = switchOn(
      status({ test_shot: ["Zone 1: run a test shot"], probes: ["Zone 1: map a moisture probe"] }),
    );
    expect(result.reason).toBe("Probes: Zone 1: map a moisture probe");
  });

  it("is never held by sizing on the generic defaults, the controller or the lights (D18)", () => {
    const only = status({
      sizing: ["Sizing still on the generic defaults (substrate_volume): check and confirm it"],
      controller: ["The controller app has not reported for this room yet"],
      room: ["Lights-on and lights-off are the same hour"],
    });
    expect(switchOn(only).enabled).toBe(true);
    expect(warnings(only)).toHaveLength(3);
    expect(stepMark(only.checks.find((c) => c.id === "sizing"))).toBe("attention");
  });

  it("marks each step ✓ / ! / ○", () => {
    const s = status({ test_shot: ["Zone 1: run a test shot"], sizing: ["generic"] });
    expect(s.checks.map((c) => MARK_SYMBOL[stepMark(c)])).toEqual(["✓", "✓", "✓", "✓", "!", "○"]);
    expect(stepMark(undefined)).toBe("todo");
  });
});

describe("who sees the wizard", () => {
  const room = (commissioning?: Commissioning, active = true) =>
    ({ active, commissioning }) as SetupRoom;

  it("is a room still being set up", () => {
    expect(needsWizard(room(status()))).toBe(true);
  });

  it("is never a commissioned room, an archived one, or one on an older integration", () => {
    expect(needsWizard(room({ ...status(), commissioned: true }))).toBe(false);
    expect(needsWizard(room(status(), false))).toBe(false);
    expect(needsWizard(room(undefined))).toBe(false);
    expect(needsWizard(null)).toBe(false);
  });
});
