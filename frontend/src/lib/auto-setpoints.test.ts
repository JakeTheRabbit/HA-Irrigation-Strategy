import { describe, expect, it } from "vitest";
import { autoStatusText, managedBy, parseAutoSetpoints } from "./auto-setpoints";
import type { EntityState } from "./types";

const entity = (state: string, attributes: Record<string, unknown> = {}): EntityState => ({
  entity_id: "sensor.crop_steering_zone_1_auto_setpoints",
  state,
  attributes,
});

describe("auto setpoint status", () => {
  it("hides the surface when the supervisor sensor does not exist", () => {
    expect(parseAutoSetpoints(undefined)).toBeNull();
  });
  it("reads the documented state and attributes", () => {
    const status = parseAutoSetpoints(
      entity("tracking", {
        learned_peak: 35.9,
        gain: 0.62,
        day_rate: 0.7,
        night_rate: 0.37,
        p1_outcome: "plateau",
        last_change: "P1 target 38.0 → 36.5 %",
        jev: "ok",
        managed: [
          "number.crop_steering_zone_1_p1_target_vwc",
          "number.crop_steering_zone_1_p2_vwc_threshold",
        ],
        updated: "2026-09-08T00:58:00+00:00",
        hold_days: 3,
        frozen_reason: null,
      }),
    )!;
    expect(status).toEqual({
      entityId: "sensor.crop_steering_zone_1_auto_setpoints",
      state: "tracking",
      learnedPeak: 35.9,
      gain: 0.62,
      dayRate: 0.7,
      nightRate: 0.37,
      p1Outcome: "plateau",
      lastChange: "P1 target 38.0 → 36.5 %",
      jev: "ok",
      managed: [
        "number.crop_steering_zone_1_p1_target_vwc",
        "number.crop_steering_zone_1_p2_vwc_threshold",
      ],
      updated: "2026-09-08T00:58:00+00:00",
      holdDays: 3,
      frozenReason: null,
    });
  });
  it.each(["pending", "reached", "plateau", "suspect", "short"])(
    "accepts the %s P1 outcome",
    (outcome) => {
      expect(parseAutoSetpoints(entity("tracking", { p1_outcome: outcome }))!.p1Outcome).toBe(
        outcome,
      );
    },
  );
  it("reads hold days and the frozen reason as optional, untrusted attributes", () => {
    const frozen = parseAutoSetpoints(
      entity("frozen", {
        hold_days: "2",
        frozen_reason: "an armed grow plan owns this room's targets",
      }),
    )!;
    expect(frozen.holdDays).toBe(2);
    expect(frozen.frozenReason).toBe("an armed grow plan owns this room's targets");
    const missing = parseAutoSetpoints(entity("tracking"))!;
    expect(missing.holdDays).toBeNull();
    expect(missing.frozenReason).toBeNull();
    const malformed = parseAutoSetpoints(
      entity("tracking", { hold_days: -1, frozen_reason: { nested: true } }),
    )!;
    expect(malformed.holdDays).toBeNull();
    expect(malformed.frozenReason).toBeNull();
    expect(parseAutoSetpoints(entity("tracking", { hold_days: 1.5 }))!.holdDays).toBeNull();
    expect(parseAutoSetpoints(entity("tracking", { hold_days: 0 }))!.holdDays).toBe(0);
  });
  it("treats unknown states and malformed attributes defensively", () => {
    const status = parseAutoSetpoints(
      entity("unavailable", {
        learned_peak: "n/a",
        gain: Number.NaN,
        p1_outcome: "exploded",
        last_change: "",
        jev: 7,
        managed: ["number.crop_steering_zone_1_p1_target_vwc", 5, "switch.pump", null],
        updated: 12,
      }),
    )!;
    expect(status.state).toBe("unavailable");
    expect(status.learnedPeak).toBeNull();
    expect(status.gain).toBeNull();
    expect(status.p1Outcome).toBeNull();
    expect(status.lastChange).toBeNull();
    expect(status.jev).toBeNull();
    expect(status.managed).toEqual(["number.crop_steering_zone_1_p1_target_vwc"]);
    expect(status.updated).toBeNull();
    expect(parseAutoSetpoints(entity("something-new"))!.state).toBe("unavailable");
    expect(parseAutoSetpoints(entity("off", { managed: "not-a-list" }))!.managed).toEqual([]);
  });
  it("accepts numeric strings for learned values", () => {
    expect(parseAutoSetpoints(entity("learning", { learned_peak: "36.25" }))!.learnedPeak).toBe(
      36.25,
    );
  });
  it("describes state, learned peak, last change and Jev in one line", () => {
    const status = parseAutoSetpoints(
      entity("tracking", { learned_peak: 35.9, last_change: "P1 target → 36.5 %", jev: "ok" }),
    )!;
    expect(autoStatusText(status)).toBe(
      "Tracking · learned peak 35.9% · last change: P1 target → 36.5 % · Jev: ok",
    );
    expect(autoStatusText(parseAutoSetpoints(entity("learning", { jev: "unavailable" }))!)).toBe(
      "Learning · learned peak not yet known · no changes yet · Jev: unavailable",
    );
    expect(autoStatusText(parseAutoSetpoints(entity("off"))!)).toBe(
      "Off · learned peak not yet known · no changes yet · Jev: not reported",
    );
  });
  it("adds hold days while a learned peak is held, and why a supervisor is frozen", () => {
    const held = parseAutoSetpoints(entity("tracking", { learned_peak: 35.9, hold_days: 3 }))!;
    expect(autoStatusText(held)).toBe(
      "Tracking · learned peak 35.9%, held 3 days · no changes yet · Jev: not reported",
    );
    const oneDay = parseAutoSetpoints(entity("tracking", { learned_peak: 35.9, hold_days: 1 }))!;
    expect(autoStatusText(oneDay)).toMatch(/held 1 day ·/);
    // 0 means the supervisor is probing one point higher, not holding.
    const probing = parseAutoSetpoints(entity("tracking", { learned_peak: 35.9, hold_days: 0 }))!;
    expect(autoStatusText(probing)).toMatch(/learned peak 35.9%, probing higher ·/);
    const idle = parseAutoSetpoints(entity("frozen", { learned_peak: 35.9, hold_days: 0 }))!;
    expect(autoStatusText(idle)).toMatch(/learned peak 35.9% ·/);
    const frozen = parseAutoSetpoints(
      entity("frozen", { frozen_reason: "probe response looks suspect", jev: "unavailable" }),
    )!;
    expect(autoStatusText(frozen)).toBe(
      "Frozen: probe response looks suspect · learned peak not yet known · no changes yet · Jev: unavailable",
    );
    // A reason left over from an earlier freeze is not shown once the supervisor runs again.
    const recovered = parseAutoSetpoints(entity("tracking", { frozen_reason: "old reason" }))!;
    expect(autoStatusText(recovered)).not.toMatch(/old reason/);
  });
  it("only marks fields as managed while the supervisor is active", () => {
    const managed = ["number.crop_steering_zone_1_p1_target_vwc"];
    const tracking = parseAutoSetpoints(entity("tracking", { managed }))!;
    const frozen = parseAutoSetpoints(entity("frozen", { managed }))!;
    const off = parseAutoSetpoints(entity("off", { managed }))!;
    expect(managedBy([tracking], "number.crop_steering_zone_1_p1_target_vwc")).toBe(true);
    expect(managedBy([frozen], "number.crop_steering_zone_1_p1_target_vwc")).toBe(true);
    expect(managedBy([off], "number.crop_steering_zone_1_p1_target_vwc")).toBe(false);
    expect(managedBy([tracking], "number.crop_steering_zone_1_p2_vwc_threshold")).toBe(false);
    expect(managedBy([null, tracking], "number.crop_steering_zone_1_p1_target_vwc")).toBe(true);
  });
});
