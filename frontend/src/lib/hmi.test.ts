import { describe, expect, it } from "vitest";
import { gauge, gaugeSpeech, probeGaps, valueAt, vwcGauge } from "./hmi";

describe("probe gaps", () => {
  it("takes a dropout out of the readings and keeps when it was", () => {
    const readings = [55, 54.5, 0, 0, 0.4, 53.8, 53.5].map((value, index) => ({
      time: index * 300_000,
      value,
    }));
    const { clean, gaps } = probeGaps(readings);
    expect(clean.map((reading) => reading.value)).toEqual([55, 54.5, 53.8, 53.5]);
    expect(gaps).toEqual([{ start: 600_000, end: 1_200_000 }]);
  });
  it("finds nothing in a good probe, and each separate dropout once", () => {
    expect(probeGaps([{ time: 0, value: 30 }]).gaps).toEqual([]);
    const two = [40, 0, 40, 0].map((value, index) => ({ time: index, value }));
    expect(probeGaps(two).gaps).toEqual([
      { start: 1, end: 1 },
      { start: 3, end: 3 },
    ]);
  });
});

describe("gauges", () => {
  it("says how far a value is from its target, for a screen reader too", () => {
    const now = gauge({ label: "VWC now", value: 25.4, target: 50, unit: "%", tolerance: 5 });
    expect(now).toMatchObject({ state: "abnormal", words: "24.6 points under" });
    expect(now.deviation).toBeCloseTo(-24.6);
    expect(gaugeSpeech(now)).toBe("VWC now 25.4%, target 50%, 24.6 points under");
  });
  it("is normal inside its tolerance or its band, and abnormal outside the band", () => {
    expect(gauge({ label: "x", value: 51, target: 50, unit: "%", tolerance: 2 }).state).toBe(
      "normal",
    );
    expect(gauge({ label: "x", value: 50, target: 50, unit: "%" }).words).toBe("on target");
    const ec = gauge({ label: "Pore EC", value: 2.8, band: [3.5, 6], unit: "", digits: 2, points: "mS/cm" });
    expect(ec).toMatchObject({ state: "abnormal", words: "0.7 mS/cm under" });
    expect(gauge({ label: "Pore EC", value: 4, band: [3.5, 6], unit: "" }).words).toBe("in band");
  });
  it("a peak not reached yet is not abnormal when under is allowed", () => {
    expect(
      gauge({ label: "Peak", value: 58, target: 64, unit: "%", tolerance: 2, underIsNormal: true })
        .state,
    ).toBe("normal");
  });
  it("shows the data quality and no number when there is no value", () => {
    const gap = gauge({ label: "VWC now", value: null, target: 50, unit: "%", quality: "probe gap" });
    expect(gap).toMatchObject({ state: "no-data", words: "probe gap", deviation: null });
    expect(gaugeSpeech(gap)).toBe("VWC now probe gap, target 50%");
  });
});

describe("value of a line at an hour", () => {
  it("interpolates between points and is null outside the line", () => {
    const line = [
      { hour: 0, value: 50 },
      { hour: 2, value: 60 },
    ];
    expect(valueAt(line, 1)).toBe(55);
    expect(valueAt(line, 3)).toBeNull();
  });
});

describe("VWC against its phase", () => {
  const limits = { rewater: 61, peak: 64, rescue: 35 };
  it("in P2 sits between the re-water point and the peak target", () => {
    const model = vwcGauge({ ...limits, value: 62, phase: "P2" });
    expect(model).toMatchObject({ band: [61, 64], state: "normal", words: "in band" });
    expect(vwcGauge({ ...limits, value: 55, phase: "P2" }).state).toBe("abnormal");
  });
  it("overnight only the rescue floor counts", () => {
    expect(vwcGauge({ ...limits, value: 50, phase: "P3" })).toMatchObject({
      band: [35, 64],
      state: "normal",
    });
  });
  it("in P1 is under its peak target without alarm", () => {
    expect(vwcGauge({ ...limits, value: 50, phase: "P1" })).toMatchObject({
      target: 64,
      state: "normal",
      words: "14 points under",
    });
  });
});
