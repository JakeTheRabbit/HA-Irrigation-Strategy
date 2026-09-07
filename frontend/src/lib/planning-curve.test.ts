import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PlanningCurve } from "../components/planning-curve";
import { describe, expect, it } from "vitest";
import { buildPlanningCurve, planningClock } from "./planning-curve";
const parameters = {
  field_capacity: 70,
  dryback_target: 20,
  p1_target_vwc: 68,
  p2_vwc_threshold: 58,
  p2_shot_size: 4,
  p1_initial_shot_size: 6,
  p3_emergency_vwc_threshold: 40,
  ec_target_p0: 3,
  ec_target_p1: 2.8,
  ec_target_p2: 3.5,
  p0_maximum_wait_time: 60,
  p1_time_between_shots: 15,
  p1_maximum_shots: 4,
};
describe("setpoint planning curve", () => {
  it("derives relative dryback target and phase windows from supplied settings", () => {
    const plan = buildPlanningCurve(parameters, 6, 18);
    expect(plan.morningDrybackVwc).toBe(56);
    expect(plan.phases.map((p) => [p.id, p.start, p.end])).toEqual([
      ["P0", 0, 1],
      ["P1", 1, 2],
      ["P2", 2, 12],
      ["P3", 12, 24],
    ]);
    expect(plan.p2Envelope).toEqual([58, 62]);
    expect(plan.vwc.filter((point) => point.phase === "P0").map((point) => point.value)).toEqual([
      70, 56,
    ]);
    expect(plan.vwc.some((point) => point.phase === "P3")).toBe(false);
    expect(plan.notes.join(" ")).toMatch(/P3.*not.*forecast/i);
    expect(plan.notes.join(" ")).toMatch(/retention/i);
  });
  it("changes supplied VWC, EC and shot targets reactively", () => {
    const plan = buildPlanningCurve(
      { ...parameters, p1_target_vwc: 72, ec_target_p2: 4, p2_shot_size: 7 },
      6,
      18,
    );
    expect(plan.vwc.some((point) => point.value === 72)).toBe(true);
    expect(
      plan.ec.filter((point) => point.phase === "P2").every((point) => point.value === 4),
    ).toBe(true);
    expect(plan.p2Envelope).toEqual([58, 65]);
  });
  it("does not invent absent EC targets or water-content measurements", () => {
    const plan = buildPlanningCurve({}, 6, 18);
    expect(plan.vwc).toEqual([]);
    expect(plan.ec).toEqual([]);
    expect(plan.missing).toContain("P1 VWC target");
  });
  it("handles a lights-on window crossing midnight", () => {
    const plan = buildPlanningCurve(parameters, 20, 8);
    expect(plan.photoperiod).toBe(12);
    expect(planningClock(20, 4)).toBe("00:00");
    expect(planningClock(20, 24)).toBe("20:00");
  });
  it("exposes reference assumptions and incompatible daytime targets", () => {
    const { field_capacity, ...rest } = parameters;
    const plan = buildPlanningCurve({ ...rest, p2_vwc_threshold: 75 }, 6, 18);
    expect(plan.morningDrybackVwc).toBeCloseTo(54.4);
    expect(plan.notes.join(" ")).toMatch(/P1 target.*reference/);
    expect(plan.warnings.join(" ")).toMatch(/threshold.*above.*target/i);
  });
  it("draws only supplied eligible ramp-up windows before the P3 cutoff", () => {
    const plan = buildPlanningCurve(parameters, 6, 18);
    expect(plan.p1Windows).toEqual([1, 1.25, 1.5, 1.75]);
    expect(
      buildPlanningCurve({ ...parameters, p1_time_between_shots: 30 }, 6, 18).p1Windows,
    ).toEqual([1, 1.5, 2, 2.5]);
    expect(
      buildPlanningCurve({ ...parameters, p0_maximum_wait_time: 660, p1_maximum_shots: 8 }, 6, 18)
        .p1Windows,
    ).toEqual([11, 11.25, 11.5, 11.75]);
    expect(
      buildPlanningCurve({ ...parameters, p1_time_between_shots: 0 }, 6, 18).p1Windows,
    ).toEqual([]);
    expect(buildPlanningCurve({}, 6, 18).p1Windows).toEqual([]);
  });
  it("rejects ambiguous equal lights-on and lights-off times", () => {
    expect(buildPlanningCurve(parameters, 6, 6).warnings.join(" ")).toMatch(/must differ/);
  });
});

describe("HA-bounded curve editing", () => {
  it("quantizes against the actual minimum and step and never exceeds max", async () => {
    const { changePlanningValue } = await import("./planning-curve");
    const calls: [string, number][] = [];
    const onChange = (key: string, value: number) => calls.push([key, value]);
    const bounds = { floor: { min: 10.25, max: 60.4, step: 0.5 } };
    changePlanningValue("floor", 38.4, bounds, onChange);
    changePlanningValue("floor", -100, bounds, onChange);
    changePlanningValue("floor", 100, bounds, onChange);
    expect(calls).toEqual([
      ["floor", 38.25],
      ["floor", 10.25],
      ["floor", 60.25],
    ]);
  });
  it("does not emit changes for unmapped fields, invalid bounds or non-finite input", async () => {
    const { changePlanningValue } = await import("./planning-curve");
    let calls = 0;
    const cb = () => {
      calls++;
    };
    changePlanningValue("missing", 40, {}, cb);
    changePlanningValue("floor", NaN, { floor: { min: 10, max: 60, step: 0.5 } }, cb);
    changePlanningValue("floor", 40, { floor: { min: 10, max: 60, step: 0 } }, cb);
    expect(calls).toBe(0);
  });
});

describe("rendered planning curve", () => {
  const saved = {
    parameters: {
      p1_target_vwc: 65,
      p2_vwc_threshold: 55,
      field_capacity: 70,
      dryback_target: 20,
      ec_target_p2: 4,
      p3_emergency_vwc_threshold: 38,
    },
    lightsOn: 10,
    lightsOff: 22,
  };
  const line = (html: string, key: string) =>
    html.match(new RegExp(`<line data-planning-line="${key}"[^>]*`))?.[0];
  it("moves the rendered P3 draft floor immediately and retains the saved ghost line", () => {
    const render = (floor: number) =>
      renderToStaticMarkup(
        createElement(PlanningCurve, {
          ...saved,
          parameters: { ...saved.parameters, p3_emergency_vwc_threshold: floor },
          baseline: saved,
        }),
      );
    const before = render(38),
      after = render(42.5);
    expect(line(before, "p3-floor")).not.toEqual(line(after, "p3-floor"));
    expect(line(before, "baseline-p3-floor")).toEqual(line(after, "baseline-p3-floor"));
    expect(after).toContain('data-planning-line="baseline-vwc"');
    expect(after).toContain('data-planning-line="ec"');
  });
  it("exposes actual slider bounds and keeps unmapped handles read-only", () => {
    const html = renderToStaticMarkup(
      createElement(PlanningCurve, {
        ...saved,
        bounds: { p3_emergency_vwc_threshold: { min: 10, max: 60, step: 0.5 } },
        onChange: () => {},
        showEditors: false,
      }),
    );
    expect(html).toContain('aria-label="P3 emergency floor" aria-valuemin="10" aria-valuemax="60"');
    expect(html.match(/role="slider"/g)).toHaveLength(1);
    expect(html).not.toContain("Precise target controls");
  });
  it("omits invalid draft geometry and all draft phase targets if light timing is unavailable", () => {
    const html = renderToStaticMarkup(
      createElement(PlanningCurve, { ...saved, parameters: {}, lightsOn: NaN, baseline: saved }),
    );
    expect(line(html, "p3-floor")).toBeUndefined();
    expect(line(html, "baseline-p3-floor")).toBeDefined();
    expect(html).not.toContain('data-planning-line="vwc"');
    expect(html).not.toContain("NaN:NaN");
  });
});
