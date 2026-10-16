import { describe, expect, it } from "vitest";
import { readRunoff, runoffMode } from "./runoff";
import type { States } from "./types";

const states = (items: [string, string, Record<string, unknown>?][]): States =>
  Object.fromEntries(items.map(([id, state, attributes]) => [id, { entity_id: id, state, attributes: attributes ?? {} }]));

describe("the runoff estimate", () => {
  it("has no mode on an integration without the estimator, and off until chosen", () => {
    expect(runoffMode(states([]), "")).toBeNull();
    expect(runoffMode(states([["select.crop_steering_runoff_estimator", "off"]]), "")).toBe("off");
    expect(runoffMode(states([["select.crop_steering_runoff_estimator", "ai"]]), "")).toBe("ai");
  });
  it("reads the room-wide percentage with its band, or why there is none", () => {
    const s = states([
      [
        "sensor.crop_steering_runoff_estimate_app",
        "14.2",
        {
          band_pct: 3.1,
          r2: 0.82,
          litres_per_run: 18,
          litres_per_run_source: "sealed-room closure",
          litres_per_hour: { "switch.ac": 5.5 },
          days: [{ date: "2026-10-15", runs: 11, fed_l: 210, closure_error_pct: -4 }],
          scope: "room-wide estimate, per grow-day",
        },
      ],
    ]);
    const r = readRunoff(s, "")!;
    expect([r.pct, r.band, r.r2, r.litresPerRun]).toEqual([14.2, 3.1, 0.82, 18]);
    expect(r.perUnit).toEqual([["switch.ac", 5.5]]);
    expect(r.days[0]).toMatchObject({ date: "2026-10-15", runs: 11, closureErrorPct: -4 });
    const waiting = readRunoff(
      states([["sensor.crop_steering_runoff_estimate_app", "unresolvable", { why: "CS-311" }]]),
      "",
    )!;
    expect([waiting.pct, waiting.status, waiting.why]).toEqual([null, "unresolvable", "CS-311"]);
  });
});
