import { describe, expect, it } from "vitest";
import {
  drybackId,
  nextIrrigationId,
  publishedDryback,
  publishedNextIrrigation,
  publishedVmax,
  recordedDryback,
  vmaxId,
} from "@/lib/published";
import type { States } from "@/lib/types";

const H = 3_600_000;
const NOW = Date.parse("2026-10-22T12:00:00Z");
const state = (entity_id: string, value: string, attributes = {}, updated = NOW): States => ({
  [entity_id]: {
    entity_id,
    state: value,
    attributes,
    last_changed: new Date(updated).toISOString(),
    last_updated: new Date(updated).toISOString(),
  },
});

describe("the controller's published dryback", () => {
  it("is shown exactly as published, with the peak it was measured from", () => {
    const states = state(drybackId("f1_", 2), "12.345", {
      peak_vwc: 63.2,
      dryback_points: 7.8,
      rate_points_per_h: 0.42,
      unit_of_measurement: "%",
    });
    expect(drybackId("f1_", 2)).toBe("sensor.crop_steering_f1_zone_2_dryback_app");
    expect(publishedDryback(states, "f1_", 2)).toEqual({
      percent: 12.345,
      peak: 63.2,
      points: 7.8,
      rate: 0.42,
      reason: null,
    });
  });

  it("is never worked out from readings: no sensor, unknown or unavailable give a reason", () => {
    expect(publishedDryback({}, "", 1)).toEqual({
      percent: null,
      peak: null,
      points: null,
      rate: null,
      reason: "the controller does not publish a dryback for this zone",
    });
    expect(publishedDryback(state(drybackId("", 1), "unknown", { peak_vwc: null }), "", 1)).toEqual(
      {
        percent: null,
        peak: null,
        points: null,
        rate: null,
        reason: "no peak since lights-on yet",
      },
    );
    expect(publishedDryback(state(drybackId("", 1), "unavailable"), "", 1).reason).toBe(
      "the controller's sensor is unavailable",
    );
  });

  it("last night's is the recorded value the controller held at lights-on", () => {
    const start = NOW - 6 * H;
    const rows = [
      { time: start - 2 * H, state: "18.5", attributes: { peak_vwc: 60 } },
      { time: start, state: "21.25", attributes: { peak_vwc: 61 } },
      { time: start + 60_000, state: "0", attributes: { peak_vwc: 48 } },
    ];
    expect(recordedDryback(rows, start)).toEqual({
      percent: 21.25,
      peak: 61,
      points: null,
      rate: null,
      reason: null,
    });
    expect(recordedDryback(rows.slice(2), start).reason).toBe(
      "the controller's dryback was not recorded at lights-on",
    );
    expect(recordedDryback(undefined, start).percent).toBeNull();
  });
});

describe("the controller's next irrigation estimate", () => {
  const since = NOW - 2 * H;
  // The zone's last shot ended 40 minutes ago.
  const shotEnd = NOW - 40 * 60_000;
  const next = (value: string, published: number, lastShotEnd: number | null = shotEnd) =>
    publishedNextIrrigation(
      state(nextIrrigationId("", 1), value, {}, published),
      "",
      1,
      "P2",
      since,
      lastShotEnd,
      NOW,
    );
  it("is the published hours from when the controller published them", () => {
    expect(nextIrrigationId("", 3)).toBe(
      "sensor.crop_steering_prediction_zone_3_next_irrigation_hours",
    );
    expect(next("1.5", NOW - 10 * 60_000)).toEqual({
      at: NOW - 10 * 60_000 + 1.5 * H,
      reason: null,
    });
  });

  it("a fresh 0 h after the last shot is due now", () => {
    expect(next("0.0", NOW - 60_000)).toEqual({ at: NOW, reason: null });
  });

  it("the 0 h the controller published as it fired is not due now after that shot", () => {
    // The controller publishes 0 on the tick it fires, then nothing while the zone settles.
    expect(next("0.0", shotEnd - 3 * 60_000)).toEqual({
      at: null,
      reason: "no estimate from the controller since the last shot",
    });
  });

  it("any estimate from before the last shot ended is ignored", () => {
    expect(next("1.5", shotEnd - 60_000).reason).toBe(
      "no estimate from the controller since the last shot",
    );
  });

  it("a 0 h held long after it was published is out of date", () => {
    expect(next("0.0", NOW - 20 * 60_000, null)).toEqual({
      at: null,
      reason: "the controller's estimate is out of date",
    });
  });

  it("outside P2, from before this P2 began, or long past, it is not shown", () => {
    const states = state(nextIrrigationId("", 1), "1", {}, NOW - 30 * 60_000);
    expect(publishedNextIrrigation(states, "", 1, "P1", since, null, NOW)).toEqual({
      at: null,
      reason: "the controller estimates the next shot only in P2",
    });
    expect(publishedNextIrrigation(states, "", 1, "P2", NOW - 10 * 60_000, null, NOW).reason).toBe(
      "no estimate from the controller in this P2 yet",
    );
    expect(publishedNextIrrigation({}, "", 1, "P2", since, null, NOW).reason).toBe(
      "no estimate from the controller in this P2 yet",
    );
    expect(next("0.25", NOW - 2 * H + 60_000, null).reason).toBe(
      "the controller's estimate is out of date",
    );
  });
});

describe("the controller's detected ramp ceiling", () => {
  it("is the published Vmax and its confidence, or why there is none", () => {
    expect(vmaxId("f2_", 1)).toBe("sensor.crop_steering_f2_zone_1_vmax_detected");
    expect(publishedVmax(state(vmaxId("", 1), "66.4", { confidence: 0.8 }), "", 1)).toEqual({
      value: 66.4,
      confidence: 0.8,
      detected: NOW,
      reason: null,
    });
    expect(publishedVmax({}, "", 1)).toEqual({
      value: null,
      confidence: null,
      detected: null,
      reason: "not detected yet",
    });
  });
});
