import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PlanningCurve } from "../components/planning-curve";
import { describe, expect, it } from "vitest";
import {
  buildPlanningCurve,
  dryRates,
  foldRecorded,
  planningAxis,
  planningClock,
  projectDay,
  smoothRecorded,
} from "./planning-curve";
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
      56, 56,
    ]);
    expect(plan.vwc.filter((point) => point.phase === "P3").map((point) => point.value)).toEqual([
      58, 56,
    ]);
    expect(plan.notes.join(" ")).toMatch(/Neither timing nor measured moisture is forecast/);
    expect(plan.notes.join(" ")).toMatch(/retention/i);
  });
  it("changes supplied VWC, EC and shot targets reactively", () => {
    const plan = buildPlanningCurve(
      { ...parameters, p1_target_vwc: 72, ec_target_p2: 4, p2_shot_size: 7 },
      6,
      18,
    );
    expect(plan.vwc.some((point) => point.value === 72)).toBe(true);
    expect(plan.ec.some((point) => point.phase === "P2" && point.value === 4)).toBe(true);
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
  it("joins both references at phase boundaries and across the complete day/night cycle", () => {
    const plan = buildPlanningCurve(parameters, 6, 18);
    for (const points of [plan.vwc, plan.ec]) {
      expect(points[0].hour).toBe(0);
      expect(points.at(-1)!.hour).toBe(24);
      expect(points.at(-1)!.value).toBe(points[0].value);
      for (let index = 1; index < points.length; index++) {
        expect(points[index].hour).toBeGreaterThanOrEqual(points[index - 1].hour);
        if (points[index].hour === points[index - 1].hour)
          expect(points[index].value).toBeCloseTo(points[index - 1].value);
      }
      expect(
        points
          .filter((point) => point.hour === 12)
          .every((point) => point.value === (points === plan.vwc ? 58 : 3.5)),
      ).toBe(true);
    }
    expect(plan.ec.at(-1)!.value).toBe(parameters.ec_target_p0);
    expect(plan.notes.join(" ")).toMatch(/no P3 EC setpoint/);
  });
  it("keeps the P3 floor independent and marks a crossed emergency reference", () => {
    const baseline = buildPlanningCurve(parameters, 6, 18);
    const draft = buildPlanningCurve({ ...parameters, p3_emergency_vwc_threshold: 57 }, 6, 18);
    expect(draft.vwc).toEqual(baseline.vwc);
    expect(draft.ec).toEqual(baseline.ec);
    expect(draft.emergencyReferenceActive).toBe(true);
    expect(baseline.emergencyReferenceActive).toBe(false);
    expect(draft.warnings.join(" ")).toMatch(/does not predict or schedule an emergency shot/);
  });
  it("does not invent a night rise when the relative endpoint exceeds the daytime reference", () => {
    const plan = buildPlanningCurve({ ...parameters, dryback_target: 5 }, 6, 18);
    expect(plan.morningDrybackVwc).toBe(66.5);
    expect(plan.overnightEndVwc).toBe(58);
    expect(
      plan.vwc.filter((point) => point.phase === "P3").every((point) => point.value === 58),
    ).toBe(true);
    expect(plan.warnings.join(" ")).toMatch(/no rehydration is invented/);
  });
  it("keeps lights-off inside an earlier P3 window continuous and handles collapsed phases", () => {
    for (const extra of [
      { p3_last_irrigation: 120 },
      { p0_maximum_wait_time: 720 },
      { p0_maximum_wait_time: 600, p1_maximum_shots: 20 },
    ] as Record<string, number>[]) {
      const plan = buildPlanningCurve({ ...parameters, ...extra }, 20, 8);
      for (const points of [plan.vwc, plan.ec]) {
        expect(points.at(-1)!.hour).toBe(24);
        expect(points.at(-1)!.value).toBe(points[0].value);
        expect(
          points.every(
            (point) => Number.isFinite(point.value) && point.hour >= 0 && point.hour <= 24,
          ),
        ).toBe(true);
        for (let index = 1; index < points.length; index++) {
          expect(points[index].hour).toBeGreaterThanOrEqual(points[index - 1].hour);
          if (points[index].hour === points[index - 1].hour)
            expect(points[index].value).toBeCloseTo(points[index - 1].value);
        }
      }
    }
  });
  it("preserves missing EC gaps instead of connecting across an absent phase target", () => {
    const { ec_target_p1, ...partial } = parameters;
    const plan = buildPlanningCurve(partial, 6, 18);
    expect(plan.ec.some((point) => point.phase === "P1")).toBe(false);
    expect(plan.ec.find((point) => point.phase === "P2")?.breakBefore).toBe(true);
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
  it("renders one connected VWC and dashed EC path through the night, with explicit schematic labels", () => {
    const html = renderToStaticMarkup(
      createElement(PlanningCurve, { parameters, lightsOn: 6, lightsOff: 18 }),
    );
    for (const key of ["vwc", "ec"]) {
      const path = html.match(new RegExp(`<path data-planning-line="${key}"[^>]*d="([^"]+)"`))?.[1];
      expect(path).toBeTruthy();
      expect(path!.match(/M/g)).toHaveLength(1);
      const points = [...path!.matchAll(/[ML]([\d.]+),([\d.]+)/g)];
      expect(points.at(-1)![2]).toBe(points[0][2]);
      expect(Number(points.at(-1)![1])).toBeGreaterThan(Number(points[0][1]));
    }
    expect(html).toContain("relative drop from the reference peak");
    expect(html).toContain("Dashed EC connects configured phase anchors");
  });
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
    // The VWC axis scales to what is plotted, so pixel positions may shift with the draft; what
    // each line stands for must not.
    expect(before).toContain("P3 emergency floor: 38% VWC");
    expect(after).toContain("P3 emergency floor: 42.5% VWC");
    for (const html of [before, after]) {
      expect(line(html, "baseline-p3-floor")).toBeDefined();
      expect(html).toContain("Saved P3 floor: 38% VWC");
    }
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

describe("P1 ramp drawn shot by shot", () => {
  it("gives every eligible shot its own step, from the morning endpoint to the P1 target", () => {
    const plan = buildPlanningCurve({ ...parameters, p1_shot_size_increment: 1 }, 6, 18);
    expect(plan.p1Steps.map((step) => step.hour)).toEqual(plan.p1Windows);
    expect(plan.p1Steps.map((step) => step.size)).toEqual([6, 7, 8, 9]);
    expect(plan.p1Steps[0].from).toBe(56);
    expect(plan.p1Steps.at(-1)!.to).toBeCloseTo(68);
    // each step's share of the 12-point climb follows its share of the water
    expect(plan.p1Steps.map((step) => +(step.to - step.from).toFixed(2))).toEqual([
      2.4, 2.8, 3.2, 3.6,
    ]);
    plan.p1Steps.slice(1).forEach((step, index) => expect(step.from).toBe(plan.p1Steps[index].to));
  });
  it("splits the climb evenly when shot sizes are not supplied", () => {
    const { p1_initial_shot_size, ...rest } = parameters;
    const plan = buildPlanningCurve(rest, 6, 18);
    expect(plan.p1Steps.map((step) => [step.size, step.to - step.from])).toEqual([
      [null, 3],
      [null, 3],
      [null, 3],
      [null, 3],
    ]);
  });
  it("draws no steps without a climb or without shot windows", () => {
    expect(buildPlanningCurve({ ...parameters, p1_target_vwc: 50 }, 6, 18).p1Steps).toEqual([]);
    expect(buildPlanningCurve({ ...parameters, p1_time_between_shots: 0 }, 6, 18).p1Steps).toEqual(
      [],
    );
    expect(buildPlanningCurve({}, 6, 18).p1Steps).toEqual([]);
  });
  it("renders one riser per shot in the graph", () => {
    const html = renderToStaticMarkup(
      createElement(PlanningCurve, { parameters, lightsOn: 6, lightsOff: 18 }),
    );
    expect(html.match(/data-planning-shot="P1"/g)).toHaveLength(4);
  });
});

describe("recorded readings on the plan graph", () => {
  const at = (day: number, hour: number, minute = 0) =>
    new Date(2026, 8, day, hour, minute).getTime();
  it("folds readings onto the lights-on axis and separates today from earlier days", () => {
    const readings = [
      { time: at(19, 9, 30), value: 30 }, // before lights-on on the 19th: the grow-day of the 18th
      { time: at(19, 10, 0), value: 31 },
      { time: at(19, 16, 0), value: 38 },
      { time: at(20, 4, 0), value: 33 }, // still the grow-day that began on the 19th
      { time: at(20, 10, 30), value: 32 },
      { time: at(20, 12, 0), value: 36 },
    ];
    const folded = foldRecorded(readings, 10, at(20, 12, 5));
    expect(folded.today).toEqual([
      { hour: 0.5, value: 32, time: at(20, 10, 30) },
      { hour: 2, value: 36, time: at(20, 12, 0) },
    ]);
    expect(folded.previous.map((day) => day.map((point) => point.hour))).toEqual([[0, 6, 18]]);
    expect(folded.earlier).toBe(1); // the 18th's single reading is counted, not drawn as a line
  });
  it("returns nothing for bad input and never draws the future", () => {
    expect(foldRecorded([], 10, at(20, 12))).toEqual({ today: [], previous: [], earlier: 0 });
    expect(foldRecorded([{ time: at(20, 13), value: 40 }], 10, at(20, 12)).today).toEqual([]);
    expect(foldRecorded([{ time: at(20, 11), value: 40 }], Number.NaN, at(20, 12)).today).toEqual(
      [],
    );
  });
  it("scales the VWC axis to what is plotted instead of a fixed 0-100", () => {
    // the span is always 20/40/60/80/100, so the four grid intervals are whole multiples of 5
    expect(planningAxis([34, 40, 22, 31.2, 23.4])).toEqual({ min: 10, max: 50 });
    expect(planningAxis([56, 58])).toEqual({ min: 45, max: 65 });
    expect(planningAxis([2, 99])).toEqual({ min: 0, max: 100 });
    expect(planningAxis([])).toEqual({ min: 0, max: 100 });
  });
  it("plots recorded VWC on the same graph as the draggable targets", () => {
    const now = at(20, 12, 5);
    const html = renderToStaticMarkup(
      createElement(PlanningCurve, {
        parameters,
        lightsOn: 10,
        lightsOff: 22,
        recorded: {
          now,
          vwc: [
            { time: at(19, 11), value: 57 },
            { time: at(19, 15), value: 66 },
            { time: at(20, 11), value: 58 },
            { time: at(20, 12), value: 61 },
          ],
          ec: [{ time: at(20, 12), value: 3.1 }],
        },
      }),
    );
    expect(html).toContain('data-planning-line="recorded-vwc"');
    expect(html).toContain('data-planning-line="recorded-vwc-previous"');
    expect(html).toContain("Now 61");
    expect(html).not.toContain("not recorded or forecast sensor data");
  });
});

describe("the projected day: every phase drawn the way the engine runs it", () => {
  // live F2 zone 1, 2026-09-20
  const live = {
    field_capacity: 55,
    dryback_target: 10,
    p1_target_vwc: 40,
    p2_vwc_threshold: 34,
    p2_shot_size: 3,
    p1_initial_shot_size: 2,
    p1_shot_size_increment: 0.5,
    p1_maximum_shots: 10,
    p1_time_between_shots: 20,
    p0_maximum_wait_time: 60,
    p3_emergency_vwc_threshold: 22,
    p3_emergency_shot_size: 2,
  };
  const project = (parameters: Record<string, number>, options = {}) =>
    projectDay(buildPlanningCurve(parameters, 10, 22), parameters, {
      rates: { day: 0.72, night: 0.37 },
      ...options,
    })!;
  const valueAt = (day: ReturnType<typeof project>, hour: number) =>
    day.points.filter((point) => point.hour <= hour).at(-1)!.value;
  it("P0 keeps drying after lights-on until the first shot", () => {
    const day = project(live);
    const wait = day.points.filter((point) => point.phase === "P0");
    expect(wait[0]).toMatchObject({ hour: 0, value: day.lightsOnVwc });
    expect(wait.at(-1)!.hour).toBe(1);
    expect(wait.at(-1)!.value - day.lightsOnVwc).toBeCloseTo(-0.72, 2);
  });
  it("P1 shows all ten shots, drying between them, and lands on the target", () => {
    const day = project(live);
    const ramp = day.shots.filter((shot) => shot.phase === "P1");
    expect(ramp).toHaveLength(10);
    expect(ramp.map((shot) => shot.size)).toEqual([2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5]);
    expect(ramp.at(-1)!.to).toBe(40);
    expect(ramp[1].from).toBeCloseTo(ramp[0].to - 0.72 / 3, 2); // 20 minutes of dry-down
    ramp.forEach((shot) => expect(shot.to).toBeGreaterThan(shot.from));
  });
  it("P2 fires a shot every time VWC falls to the threshold and none after the last-irrigation cutoff", () => {
    const tight = { ...live, p2_vwc_threshold: 39, p2_shot_size: 1, p3_last_irrigation: 120 };
    const maintenance = project(tight).shots.filter((shot) => shot.phase === "P2");
    expect(maintenance).toHaveLength(4); // 1 point at 0.72 points/h: one shot every ~83 minutes
    for (const shot of maintenance) {
      expect(shot.from).toBeLessThanOrEqual(39);
      expect(shot.from).toBeGreaterThan(38.9);
      expect(shot.to - shot.from).toBeCloseTo(1); // full retention unless a gain is known
      expect(shot.hour).toBeLessThan(10); // P3 starts two hours before lights-off
    }
    const halved = project(tight, { retention: 0.5 }).shots.filter((shot) => shot.phase === "P2");
    expect(halved[0].to - halved[0].from).toBeCloseTo(0.5);
    expect(halved.length).toBeGreaterThan(maintenance.length);
    // the live setpoints: 40 down to 34 at 0.72 points/h takes over eight hours, so P2 barely fires
    expect(project(live).shots.filter((shot) => shot.phase === "P2")).toHaveLength(0);
  });
  it("P3 dries down through the night at the slower rate and the next day starts where it ends", () => {
    const day = project(live);
    expect(valueAt(day, 24)).toBe(day.lightsOnVwc);
    expect(day.points.at(-1)!.hour).toBe(24);
    expect(valueAt(day, 12) - valueAt(day, 24)).toBeCloseTo(0.37 * 12, 1);
    expect(day.lightsOnVwc).toBeLessThan(34);
    for (let index = 1; index < day.points.length; index++)
      expect(day.points[index].hour).toBeGreaterThanOrEqual(day.points[index - 1].hour);
  });
  it("measures the dryback target from the projected peak, as the engine does from the measured one", () => {
    const day = project(live);
    expect(day.peak).toBe(40);
    expect(day.drybackVwc).toBeCloseTo(36);
  });
  it("fires the emergency shot if the night would cross the P3 floor", () => {
    const day = project({ ...live, p3_emergency_vwc_threshold: 31 });
    const emergency = day.shots.filter((shot) => shot.emergency);
    expect(emergency.length).toBeGreaterThan(0);
    expect(emergency[0].phase).toBe("P3");
    expect(emergency[0].to - emergency[0].from).toBeCloseTo(2);
  });
  it("stays sane when shot count, spacing or sizes are not supplied", () => {
    const sparse = { p1_target_vwc: 65, p2_vwc_threshold: 55, dryback_target: 20 };
    const day = projectDay(buildPlanningCurve(sparse, 10, 22), sparse)!;
    expect(day.peak).toBe(65);
    expect(day.shots).toEqual([]); // nothing to draw a riser from
    expect(Math.min(...day.points.map((point) => point.value))).toBeGreaterThan(45); // held at the threshold, then one night's dry-down
  });
  it("falls back to nominal rates without history and draws nothing without targets", () => {
    const plan = buildPlanningCurve(live, 10, 22);
    const day = projectDay(plan, live)!;
    expect(day.measured).toEqual({ day: false, night: false });
    expect(day.rates).toEqual({ day: 0.7, night: 0.35 });
    expect(projectDay(buildPlanningCurve({}, 10, 22), {})).toBeNull();
  });
  it("measures a zone's own dry-down from its recorded hours, ignoring the hours a shot landed", () => {
    const day = Array.from({ length: 24 * 6 }, (_, index) => {
      const hour = index / 6;
      const shot = hour >= 4 && hour < 5 ? 4 : 0; // one wet hour mid-photoperiod
      const value = hour < 12 ? 40 - 0.6 * hour + shot : 32.8 - 0.3 * (hour - 12);
      return { hour, value, time: index };
    });
    expect(dryRates([day, day], 12)).toEqual({ day: 0.6, night: 0.3 });
    expect(dryRates([day.slice(0, 8)], 12)).toEqual({ day: null, night: null });
  });
  it("is not flattened by frequent P2 top-ups", () => {
    // teeth every 75 minutes losing 2.7 points each: 2.16 points/h. Hour-to-hour averages read 0.18.
    const sawtooth = Array.from({ length: 24 * 6 }, (_, index) => {
      const hour = index / 6;
      const value =
        hour < 10 ? 64 - 2.7 * ((hour / 1.25) % 1) : 64 - 8.5 * ((hour - 10) / 14) ** 0.75;
      return { hour, value, time: index };
    });
    expect(dryRates([sawtooth, sawtooth], 12).day).toBeCloseTo(2.16, 2);
  });
});

describe("recorded lines are drawn smooth", () => {
  it("drops probe jitter, keeps a shot, and ends on the live reading", () => {
    const minute = 60_000;
    const readings = Array.from({ length: 180 }, (_, index) => ({
      time: index * minute,
      // flickers +/-0.4 every reading; a shot lifts it 5 points at the 90th minute
      value: (index < 90 ? 30 : 35) + (index % 2 ? 0.4 : -0.4),
    }));
    readings.push({ time: 180 * minute, value: 34.2 });
    const smooth = smoothRecorded(readings, 10);
    expect(smooth.length).toBeLessThanOrEqual(19);
    const steps = smooth
      .slice(1, -1)
      .map((point, index) => Math.abs(point.value - smooth[index].value));
    expect(steps.filter((step) => step > 1)).toHaveLength(1); // only the shot is a real move
    expect(smooth.at(-1)).toEqual({ time: 180 * minute, value: 34.2 });
    expect(smoothRecorded([])).toEqual([]);
  });
});
