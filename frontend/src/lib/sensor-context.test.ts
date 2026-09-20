import { describe, expect, it } from "vitest";
import {
  chartScale,
  fieldCapacitySuggestion,
  fieldHint,
  formatReading,
  latestOnly,
  nearestReading,
  plotPoints,
  referenceLines,
  sensorStats,
  setpointMetric,
  setpointParam,
  spreadLabels,
  suggestedDraft,
  timeTicks,
  valueScale,
  windowLabel,
  windowPoints,
  type SensorStats,
} from "./sensor-context";
import { validateSetpoint } from "./setpoint-preview";
import type { Series, Setting } from "./types";

// 13:00 NZST on 8 September 2026 (UTC+12, before daylight saving starts).
const now = Date.parse("2026-09-08T01:00:00Z");
const timeZone = "Pacific/Auckland";
const at = (day: number, hour: number, value: number) => ({
  time: new Date(Date.UTC(2026, 8, day, hour - 12)).toISOString(),
  value,
});
const series = (points: Series["points"]): Series => ({
  entityId: "sensor.crop_steering_vwc_zone_1",
  label: "Zone 1 VWC",
  points,
});
/** Four local days: a partial first day with outliers, two full days, and a partial today. */
const fourDays = series([
  at(4, 9, 99), // before the 72 h window
  at(5, 14, 50),
  at(5, 22, 20),
  at(6, 2, 27),
  at(6, 15, 36),
  at(7, 3, 26),
  at(7, 16, 35),
  at(8, 4, 28),
  at(8, 11, 34),
  at(8, 12, 32.4),
  at(8, 18, 12), // after "now"
]);

describe("sensor window statistics", () => {
  it("keeps only finite readings inside the chosen window, in time order", () => {
    const points = windowPoints(
      series([
        at(8, 12, 32.4),
        at(8, 11, 34),
        { time: "not a time", value: 30 },
        { time: at(8, 10, 0).time, value: Number.NaN },
        at(4, 9, 99),
        at(8, 18, 12),
      ]),
      { hours: 24, now, timeZone },
    );
    expect(points.map((point) => point.value)).toEqual([34, 32.4]);
    expect(points[0].time).toBeLessThan(points[1].time);
  });
  it("reports window peak and trough with their times, and the newest reading as current", () => {
    const stats = sensorStats(fourDays, { hours: 72, now, timeZone })!;
    expect(stats.peak).toEqual({ value: 50, time: Date.parse(at(5, 14, 0).time) });
    expect(stats.trough).toEqual({ value: 20, time: Date.parse(at(5, 22, 0).time) });
    expect(stats.current).toEqual({ value: 32.4, time: Date.parse(at(8, 12, 0).time) });
    expect(stats.last).toEqual(stats.current);
  });
  it("uses the median of per-local-day extremes and ignores a partial first day once two full days exist", () => {
    const stats = sensorStats(fourDays, { hours: 72, now, timeZone })!;
    // 5 Sept is partial and dropped: peaks 36, 35, 34 and troughs 27, 26, 28 remain.
    expect(stats.days).toBe(3);
    expect(stats.typicalDailyPeak).toBe(35);
    expect(stats.typicalDailyTrough).toBe(27);
  });
  it("keeps a partial first day when fewer than two full days are available", () => {
    const stats = sensorStats(fourDays, { hours: 24, now, timeZone })!;
    // 7 Sept after 13:00 and 8 Sept until 13:00: neither is a full day.
    expect(stats.days).toBe(2);
    expect(stats.typicalDailyPeak).toBe((35 + 34) / 2);
    expect(stats.typicalDailyTrough).toBe((35 + 28) / 2);
    expect(stats.peak.value).toBe(35);
  });
  it("resolves equal extremes to the most recent reading", () => {
    const stats = sensorStats(series([at(7, 15, 36), at(8, 9, 36), at(8, 10, 30), at(8, 11, 30)]), {
      hours: 72,
      now,
      timeZone,
    })!;
    expect(stats.peak.time).toBe(Date.parse(at(8, 9, 0).time));
    expect(stats.trough.time).toBe(Date.parse(at(8, 11, 0).time));
  });
  it("never presents a stale or unavailable live reading as current", () => {
    const stats = sensorStats(fourDays, { hours: 72, now, timeZone, live: null })!;
    expect(stats.current).toBeNull();
    expect(stats.last.value).toBe(32.4);
  });
  it("uses a fresh live reading as the current value and lets it extend the range", () => {
    const stats = sensorStats(fourDays, { hours: 24, now, timeZone, live: 37.5 })!;
    expect(stats.current).toEqual({ value: 37.5, time: now });
    expect(stats.peak).toEqual({ value: 37.5, time: now });
    expect(windowPoints(fourDays, { hours: 24, now, timeZone, live: 37.5 }).at(-1)).toEqual({
      value: 37.5,
      time: now,
    });
  });
  it("returns nothing when the probe has no recorded history in the window", () => {
    expect(sensorStats(series([at(4, 9, 99)]), { hours: 24, now, timeZone })).toBeNull();
    expect(sensorStats(undefined, { hours: 24, now, timeZone })).toBeNull();
    expect(sensorStats(series([]), { hours: 24, now, timeZone, live: null })).toBeNull();
  });
  it("labels the supported windows", () => {
    expect([24, 72, 168].map(windowLabel)).toEqual(["24 h", "72 h", "7 d"]);
  });
});

describe("setpoint to metric mapping", () => {
  it("maps moisture setpoints to VWC and EC setpoints to pore EC", () => {
    for (const key of [
      "p1_target_vwc",
      "p2_vwc_threshold",
      "p3_emergency_vwc_threshold",
      "field_capacity",
      "dryback_target",
      "vegetative_dryback_target",
      "generative_dryback_target",
    ])
      expect(setpointMetric(key)).toBe("vwc");
    for (const key of [
      "ec_target_p0",
      "ec_target_p1",
      "ec_target_p2",
      "ec_target_veg_p0",
      "ec_target_gen_p2",
      "maximum_ec",
    ])
      expect(setpointMetric(key)).toBe("ec");
  });
  it("maps shot sizes, timings, counts, volumes and feed limits to nothing", () => {
    for (const key of [
      "p2_shot_size",
      "p1_initial_shot_size",
      "p1_shot_size_increment",
      "p3_emergency_shot_size",
      "p1_time_between_shots",
      "p0_maximum_wait_time",
      "p1_maximum_shots",
      "max_daily_volume",
      "substrate_volume",
      "plant_count",
      "lights_on_hour",
      "irrigation_ec_max",
      "watchdog_hours",
    ])
      expect(setpointMetric(key)).toBeNull();
  });
  it("reads the parameter from zone and room number entities of one room only", () => {
    expect(setpointParam("number.crop_steering_zone_2_p1_target_vwc", "")).toBe("p1_target_vwc");
    expect(setpointParam("number.crop_steering_f1_zone_12_ec_target_gen_p1", "f1_")).toBe(
      "ec_target_gen_p1",
    );
    expect(setpointParam("number.crop_steering_f1_maximum_ec", "f1_")).toBe("maximum_ec");
    expect(setpointParam("number.crop_steering_zone_1_field_capacity", "f1_")).toBeNull();
    expect(setpointParam("sensor.crop_steering_vwc_zone_1", "")).toBeNull();
  });
});

describe("reference lines", () => {
  const draft = {
    p1_target_vwc: 64,
    p2_vwc_threshold: 54,
    p3_emergency_vwc_threshold: 35,
    field_capacity: 70,
    dryback_target: 10,
    ec_target_p0: 3,
    ec_target_p1: 3.2,
    ec_target_p2: 3.4,
    maximum_ec: 9,
    p2_shot_size: 4,
    p1_maximum_shots: 6,
  };
  it("draws VWC and EC setpoints, never shot sizes or counts", () => {
    const lines = referenceLines({ draft, saved: draft, typicalDailyPeak: null });
    expect(lines.filter((line) => line.metric === "vwc").map((line) => line.key)).toEqual([
      "field_capacity",
      "p1_target_vwc",
      "p2_vwc_threshold",
      "p3_emergency_vwc_threshold",
    ]);
    expect(lines.filter((line) => line.metric === "ec").map((line) => line.key)).toEqual([
      "maximum_ec",
      "ec_target_p0",
      "ec_target_p1",
      "ec_target_p2",
    ]);
    expect(lines.every((line) => line.saved === null)).toBe(true);
  });
  it("adds the saved value only where the draft differs", () => {
    const lines = referenceLines({
      draft,
      saved: { ...draft, p1_target_vwc: 60 },
      typicalDailyPeak: null,
    });
    expect(lines.find((line) => line.key === "p1_target_vwc")).toMatchObject({
      value: 64,
      saved: 60,
    });
    expect(lines.find((line) => line.key === "p2_vwc_threshold")!.saved).toBeNull();
  });
  it("keeps the saved line when the draft value is invalid and therefore missing", () => {
    const { p1_target_vwc: _omitted, ...invalid } = draft;
    const line = referenceLines({ draft: invalid, saved: draft, typicalDailyPeak: null }).find(
      (item) => item.key === "p1_target_vwc",
    )!;
    expect(line.value).toBeNull();
    expect(line.saved).toBe(64);
  });
  it("derives the dryback floor from the typical daily peak", () => {
    const lines = referenceLines({
      draft: { ...draft, dryback_target: 10 },
      saved: { ...draft, dryback_target: 20 },
      typicalDailyPeak: 36,
    });
    const floor = lines.find((line) => line.key === "dryback_floor")!;
    expect(floor.metric).toBe("vwc");
    expect(floor.kind).toBe("derived");
    expect(floor.value).toBeCloseTo(32.4);
    expect(floor.saved).toBeCloseTo(28.8);
    expect(
      referenceLines({ draft, typicalDailyPeak: null }).some((l) => l.key === "dryback_floor"),
    ).toBe(false);
  });
  it("adds a learned peak as its own labelled VWC line", () => {
    const lines = referenceLines({ draft, typicalDailyPeak: null, learnedPeak: 35.9 });
    expect(lines.find((line) => line.key === "learned_peak")).toMatchObject({
      metric: "vwc",
      kind: "learned",
      value: 35.9,
      saved: null,
    });
    expect(
      referenceLines({ draft, typicalDailyPeak: null, learnedPeak: null }).some(
        (line) => line.key === "learned_peak",
      ),
    ).toBe(false);
  });
});

describe("field hints", () => {
  const vwc: SensorStats = {
    current: { value: 32.4, time: now },
    last: { value: 32.4, time: now },
    peak: { value: 36, time: now - 3_600_000 },
    trough: { value: 26.8, time: now - 40_000_000 },
    typicalDailyPeak: 35.9,
    typicalDailyTrough: 27.5,
    days: 3,
  };
  const ec: SensorStats = {
    current: { value: 3.12, time: now },
    last: { value: 3.12, time: now },
    peak: { value: 3.84, time: now - 3_600_000 },
    trough: { value: 2.61, time: now - 40_000_000 },
    typicalDailyPeak: 3.7,
    typicalDailyTrough: 2.7,
    days: 3,
  };
  it("summarises what the probe read beside a moisture target", () => {
    const hint = fieldHint("p1_target_vwc", 35, vwc, 72)!;
    expect(hint.text).toBe("Now 32.4% · 72 h range 26.8–36.0% · typical peak 35.9%");
    expect(hint.warning).toBeNull();
  });
  it("warns gently when a target or field capacity is above anything the probe read", () => {
    expect(fieldHint("p1_target_vwc", 64, vwc, 72)!.warning).toBe(
      "above anything this probe has read in 72 h (peak 36.0%)",
    );
    expect(fieldHint("field_capacity", 70, vwc, 168)!.warning).toBe(
      "above anything this probe has read in 7 d (peak 36.0%)",
    );
    expect(fieldHint("p1_target_vwc", 37.5, vwc, 72)!.warning).toBeNull();
    expect(fieldHint("p1_target_vwc", 37.6, vwc, 72)!.warning).not.toBeNull();
    // A low ramp-up target is not the direction that matters.
    expect(fieldHint("p1_target_vwc", 10, vwc, 72)!.warning).toBeNull();
  });
  it("warns in both directions for a P2 threshold", () => {
    expect(fieldHint("p2_vwc_threshold", 60, vwc, 72)!.warning).toMatch(/^above anything/);
    expect(fieldHint("p2_vwc_threshold", 20, vwc, 72)!.warning).toBe(
      "below anything this probe has read in 72 h (trough 26.8%)",
    );
    expect(fieldHint("p2_vwc_threshold", 31, vwc, 72)!.warning).toBeNull();
  });
  it("notes an emergency floor that the probe already dropped below", () => {
    expect(fieldHint("p3_emergency_vwc_threshold", 30, vwc, 72)!.warning).toBe(
      "this probe read below this floor in 72 h (trough 26.8%), so emergency shots would have fired",
    );
    expect(fieldHint("p3_emergency_vwc_threshold", 20, vwc, 72)!.warning).toBeNull();
  });
  it("explains a dryback target through its derived floor", () => {
    const hint = fieldHint("vegetative_dryback_target", 10, vwc, 72)!;
    expect(hint.text).toBe("Typical peak 35.9% → dryback floor 32.3% · 72 h trough 26.8%");
    expect(hint.warning).toBeNull();
    expect(fieldHint("generative_dryback_target", 40, vwc, 72)!.warning).toBe(
      "dryback floor 21.5% is below anything this probe has read in 72 h (trough 26.8%)",
    );
  });
  it("uses pore EC readings and units for EC setpoints", () => {
    const hint = fieldHint("ec_target_veg_p1", 3, ec, 72)!;
    expect(hint.text).toBe("Now 3.12 mS/cm · 72 h range 2.61–3.84 mS/cm · typical peak 3.70 mS/cm");
    expect(hint.warning).toBeNull();
    expect(fieldHint("ec_target_gen_p2", 6, ec, 72)!.warning).toBe(
      "above anything this probe has read in 72 h (peak 3.84 mS/cm)",
    );
    expect(fieldHint("ec_target_p0", 1.5, ec, 72)!.warning).toBe(
      "below anything this probe has read in 72 h (trough 2.61 mS/cm)",
    );
    expect(fieldHint("maximum_ec", 3.5, ec, 72)!.warning).toBe(
      "this probe read above this limit in 72 h (peak 3.84 mS/cm)",
    );
    expect(fieldHint("maximum_ec", 9, ec, 72)!.warning).toBeNull();
  });
  it("shows a stale reading as stale, never as the current value", () => {
    const hint = fieldHint("p1_target_vwc", 35, { ...vwc, current: null }, 72)!;
    expect(hint.text).toBe(
      "Now stale (last recorded 32.4%) · 72 h range 26.8–36.0% · typical peak 35.9%",
    );
  });
  it("stays silent for unmapped settings, missing history and unfinished input", () => {
    expect(fieldHint("p2_shot_size", 4, vwc, 72)).toBeNull();
    expect(fieldHint("p1_target_vwc", 64, null, 72)).toBeNull();
    expect(fieldHint("p1_target_vwc", null, vwc, 72)!.warning).toBeNull();
  });
  it("formats readings with the precision of each probe", () => {
    expect(formatReading(36, "vwc")).toBe("36.0%");
    expect(formatReading(3.842, "ec")).toBe("3.84 mS/cm");
    expect(formatReading(3.842, "ec", false)).toBe("3.84");
  });
  describe("field capacity suggestion", () => {
    it("prefers the peak the controller has learned, and says where it came from", () => {
      expect(fieldCapacitySuggestion(61.4, vwc, 72)).toEqual({
        value: 61.4,
        source: "learned",
        text: "Learned peak 61.4%, the ceiling the controller’s Auto Setpoints has learned for this zone",
      });
    });
    it("falls back to the typical daily peak from recorded history", () => {
      expect(fieldCapacitySuggestion(null, vwc, 72)).toEqual({
        value: 35.9,
        source: "history",
        text: "Typical daily peak 35.9%, the median daily high this probe recorded over 3 days (72 h window)",
      });
      expect(fieldCapacitySuggestion(undefined, { ...vwc, days: 1 }, 24)!.text).toBe(
        "Typical daily peak 35.9%, the median daily high this probe recorded over 1 day (24 h window)",
      );
      expect(fieldCapacitySuggestion(NaN, vwc, 72)!.source).toBe("history");
    });
    it("suggests nothing rather than guess when neither value exists", () => {
      expect(fieldCapacitySuggestion(null, null, 72)).toBeNull();
      expect(fieldCapacitySuggestion(null, { ...vwc, typicalDailyPeak: null }, 72)).toBeNull();
    });
    it("rides on the field-capacity hint only", () => {
      expect(fieldHint("field_capacity", 70, vwc, 72, 61.4)!.suggestion).toMatchObject({
        value: 61.4,
        source: "learned",
      });
      expect(fieldHint("field_capacity", 70, vwc, 72)!.suggestion).toMatchObject({
        value: 35.9,
        source: "history",
      });
      expect(fieldHint("p1_target_vwc", 64, vwc, 72, 61.4)!.suggestion).toBeNull();
      expect(fieldHint("maximum_ec", 9, ec, 72, 61.4)!.suggestion).toBeNull();
    });
    it("still offers a learned peak while recorded history is unavailable", () => {
      expect(fieldHint("field_capacity", 70, null, 72, 61.4)).toEqual({
        text: "",
        warning: null,
        suggestion: fieldCapacitySuggestion(61.4, null, 72),
      });
      expect(fieldHint("field_capacity", 70, null, 72, null)).toBeNull();
      expect(fieldHint("p1_target_vwc", 64, null, 72, 61.4)).toBeNull();
    });
    it("turns a suggestion into a value the field accepts", () => {
      const field = { min: 5, max: 100, step: 1 };
      expect(suggestedDraft(61.4, field)).toBe(61);
      expect(suggestedDraft(61.5, field)).toBe(62);
      expect(suggestedDraft(35.9, { min: 40, max: 90, step: 0.5 })).toBeNull();
      expect(suggestedDraft(101, field)).toBeNull();
      expect(suggestedDraft(58.34, { min: 0, max: 100, step: 0.1 })).toBe(58.3);
      expect(suggestedDraft(58.34, { min: 0, max: 100, step: 0 })).toBe(58.34);
      expect(suggestedDraft(NaN, field)).toBeNull();
    });
    it("only ever proposes a draft that passes the field's own validation", () => {
      const setting: Setting = {
        entityId: "number.crop_steering_zone_1_field_capacity",
        label: "Field capacity",
        description: "",
        value: 70,
        min: 5,
        max: 100,
        step: 0.1,
        unit: "%",
        group: "Other",
      };
      for (const value of [5, 5.04, 58.34, 61.45, 99.96, 100])
        expect(validateSetpoint(setting, String(suggestedDraft(value, setting)))).toBe("");
    });
  });
});

describe("chart geometry helpers", () => {
  it("scales the value axis over readings and setpoints so a distant target stays visible", () => {
    const scale = valueScale([26.8, 36, 64]);
    expect(scale.min).toBeLessThanOrEqual(26.8);
    expect(scale.max).toBeGreaterThanOrEqual(64);
    expect(scale.ticks.length).toBeGreaterThanOrEqual(3);
    expect(scale.ticks.length).toBeLessThanOrEqual(7);
    expect([...scale.ticks].sort((a, b) => a - b)).toEqual(scale.ticks);
    expect(scale.ticks.every((tick) => tick >= scale.min && tick <= scale.max)).toBe(true);
  });
  it("keeps every VWC setpoint and EC target on the axis, however far from the readings", () => {
    const lines = referenceLines({
      draft: { p1_target_vwc: 64, p3_emergency_vwc_threshold: 12, ec_target_p2: 7.5 },
      typicalDailyPeak: null,
    });
    const vwc = chartScale(
      [30, 36],
      lines.filter((line) => line.metric === "vwc"),
    );
    expect(vwc.scale.max).toBeGreaterThanOrEqual(64);
    expect(vwc.scale.min).toBeLessThanOrEqual(12);
    expect(vwc.offScale(64) || vwc.offScale(12)).toBe(false);
    const ec = chartScale(
      [2.6, 3.4],
      lines.filter((line) => line.metric === "ec"),
    );
    expect(ec.offScale(7.5)).toBe(false);
  });
  it("pins a distant Max EC limit to the edge instead of flattening the EC trace", () => {
    const far = referenceLines({
      draft: { maximum_ec: 9, ec_target_p1: 3 },
      typicalDailyPeak: null,
    });
    const pinned = chartScale([2.2, 3.05], far);
    expect(pinned.offScale(9)).toBe(true);
    expect(pinned.scale.max).toBeLessThan(5);
    const close = referenceLines({
      draft: { maximum_ec: 3.6, ec_target_p1: 3 },
      saved: { maximum_ec: 3.8, ec_target_p1: 3 },
      typicalDailyPeak: null,
    });
    const shown = chartScale([2.2, 3.05], close);
    expect(shown.offScale(3.6) || shown.offScale(3.8)).toBe(false);
    // A limit below the readings is exactly what the operator must see.
    const low = chartScale(
      [2.2, 3.05],
      referenceLines({ draft: { maximum_ec: 2.5 }, typicalDailyPeak: null }),
    );
    expect(low.offScale(2.5)).toBe(false);
  });
  it("gives flat or missing readings a usable range", () => {
    const flat = valueScale([5, 5]);
    expect(flat.max).toBeGreaterThan(flat.min);
    expect(flat.min).toBeLessThanOrEqual(5);
    expect(flat.max).toBeGreaterThanOrEqual(5);
    const empty = valueScale([]);
    expect(empty.max).toBeGreaterThan(empty.min);
  });
  it("never scales a percentage or EC axis below zero", () => {
    expect(valueScale([0, 5]).min).toBe(0);
    expect(valueScale([0.05, 0.4]).min).toBeGreaterThanOrEqual(0);
  });
  it("separates crowded line labels without reordering them or leaving the plot", () => {
    const spread = spreadLabels([100, 102, 104], 12, 0, 200);
    expect(spread[1] - spread[0]).toBeGreaterThanOrEqual(12);
    expect(spread[2] - spread[1]).toBeGreaterThanOrEqual(12);
    expect(spreadLabels([10, 100], 12, 0, 200)).toEqual([10, 100]);
    const low = spreadLabels([195, 198], 12, 0, 200);
    expect(low[1]).toBeLessThanOrEqual(200);
    expect(low[1] - low[0]).toBeGreaterThanOrEqual(12);
    // Input order is preserved even when values arrive unsorted.
    const mixed = spreadLabels([104, 100], 12, 0, 200);
    expect(mixed[0]).toBeGreaterThan(mixed[1]);
  });
  it("thins long histories without losing extremes and breaks the line at long silences", () => {
    const dense = Array.from({ length: 5000 }, (_, index) => ({
      time: now - (5000 - index) * 60_000,
      value: index === 1234 ? 99 : index === 4321 ? 1 : 30 + (index % 7),
    }));
    const thin = plotPoints(dense, 800);
    expect(thin.length).toBeLessThanOrEqual(1000);
    expect(Math.max(...thin.map((point) => point.value ?? 0))).toBe(99);
    expect(Math.min(...thin.map((point) => point.value ?? 50))).toBe(1);
    const gapped = plotPoints([
      { time: now - 5 * 3_600_000, value: 30 },
      { time: now - 4.5 * 3_600_000, value: 31 },
      { time: now - 3_600_000, value: 29 },
    ]);
    expect(gapped.map((point) => point.value)).toEqual([30, 31, null, 29]);
  });
  it("finds the reading nearest to the pointer", () => {
    const points = [{ time: 100 }, { time: 200 }, { time: 400 }];
    expect(nearestReading(points, 0)).toBe(0);
    expect(nearestReading(points, 149)).toBe(0);
    expect(nearestReading(points, 151)).toBe(1);
    expect(nearestReading(points, 310)).toBe(2);
    expect(nearestReading(points, 9999)).toBe(2);
    expect(nearestReading([], 5)).toBe(-1);
  });
  it("places a handful of ascending time ticks inside the window", () => {
    for (const hours of [24, 72, 168]) {
      const ticks = timeTicks(now - hours * 3_600_000, now, hours);
      expect(ticks.length).toBeGreaterThanOrEqual(2);
      expect(ticks.length).toBeLessThanOrEqual(8);
      expect(ticks.every((tick) => tick.time >= now - hours * 3_600_000 && tick.time <= now)).toBe(
        true,
      );
      expect(ticks.map((tick) => tick.time)).toEqual(
        [...ticks.map((tick) => tick.time)].sort((a, b) => a - b),
      );
      expect(ticks.every((tick) => tick.label.length > 0)).toBe(true);
    }
  });
});

describe("race-safe loading", () => {
  function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (error: unknown) => void;
    const promise = new Promise<T>((yes, no) => {
      resolve = yes;
      reject = no;
    });
    return { promise, resolve, reject };
  }
  it("delivers only the most recently started load", async () => {
    const guard = latestOnly<string>();
    const delivered: string[] = [];
    const slow = deferred<string>(),
      fast = deferred<string>();
    guard.run(
      () => slow.promise,
      (result) => delivered.push(result.ok ? result.value : "error"),
    );
    guard.run(
      () => fast.promise,
      (result) => delivered.push(result.ok ? result.value : "error"),
    );
    fast.resolve("zone 2");
    await fast.promise;
    slow.resolve("zone 1 (stale)");
    await slow.promise;
    await Promise.resolve();
    expect(delivered).toEqual(["zone 2"]);
  });
  it("reports the failure of the latest load and drops stale failures", async () => {
    const guard = latestOnly<string>();
    const delivered: string[] = [];
    const stale = deferred<string>(),
      latest = deferred<string>();
    const deliver = (result: { ok: true; value: string } | { ok: false; error: unknown }) =>
      delivered.push(result.ok ? result.value : String(result.error));
    guard.run(() => stale.promise, deliver);
    guard.run(() => latest.promise, deliver);
    stale.reject("old failure");
    latest.reject("history unavailable");
    await Promise.allSettled([stale.promise, latest.promise]);
    await Promise.resolve();
    expect(delivered).toEqual(["history unavailable"]);
  });
  it("delivers nothing after cancel", async () => {
    const guard = latestOnly<string>();
    const delivered: string[] = [];
    const pending = deferred<string>();
    guard.run(
      () => pending.promise,
      () => delivered.push("late"),
    );
    guard.cancel();
    pending.resolve("late");
    await pending.promise;
    await Promise.resolve();
    expect(delivered).toEqual([]);
  });
});
