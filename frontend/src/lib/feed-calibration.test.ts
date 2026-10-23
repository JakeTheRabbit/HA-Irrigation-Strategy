import { afterEach, describe, expect, it, vi } from "vitest";
import { createDemo } from "./demo";
import { OperatorDemo } from "./operator-demo";
import { callV2 } from "./parity-api";
import type { States } from "./types";
import { revertEvents } from "./undo";
import {
  OFFLINE_AFTER_MS,
  captureState,
  isApplied,
  looksSteady,
  proofLine,
  refusalView,
  sessionStore,
  spanOver,
  steadyFor,
  verdictWords,
  type StoredSession,
} from "./feed-calibration";

const at = (s: number) => s * 1000;

describe("spanOver", () => {
  it("spanOver last 30 s", () => {
    // The 7.50 before the window counts from the window's start (a probe reports changes only);
    // the 6.00 earlier than that does not.
    const readings = [
      { at: at(0), value: 6.0 },
      { at: at(10), value: 7.5 },
      { at: at(25), value: 7.52 },
      { at: at(40), value: 7.49 },
      { at: at(55), value: 7.51 },
    ];
    const r = spanOver(readings);
    expect(r.span).toBeCloseTo(0.03, 10);
    expect(r.mean).toBeCloseTo((7.52 + 7.49 + 7.51) / 3, 10);
  });
  it("is not a whole window until the readings reach back 30 s", () => {
    const r = spanOver([
      { at: at(0), value: 7 },
      { at: at(20), value: 7 },
    ]);
    expect(Number.isNaN(r.span)).toBe(true);
    expect(looksSteady(r, "ph")).toBe(false);
  });
  it("takes a shorter window", () => {
    expect(spanOver([{ at: at(0), value: 1 }, { at: at(5), value: 2 }, { at: at(20), value: 2.5 }], 10_000).span).toBeCloseTo(0.5, 10);
  });
});

describe("looksSteady", () => {
  it("looksSteady pH 0.02 and EC 1% of mean", () => {
    expect(looksSteady({ span: 0.019, mean: 7 }, "ph")).toBe(true);
    expect(looksSteady({ span: 0.02, mean: 7 }, "ph")).toBe(false);
    expect(looksSteady({ span: 0.0139, mean: 1.4 }, "ec")).toBe(true);
    expect(looksSteady({ span: 0.014, mean: 1.4 }, "ec")).toBe(false);
    // A reading that did not move at all is steady, even at 0.
    expect(looksSteady({ span: 0, mean: 0 }, "ec")).toBe(true);
  });
  it("counts how long the reading has held still, as the backend does", () => {
    const readings = [
      { at: at(0), value: 5.9 },
      { at: at(10), value: 7.0 },
      { at: at(20), value: 7.01 },
      { at: at(35), value: 7.0 },
    ];
    expect(steadyFor(readings, "ph")).toBe(25_000);
  });
});

describe("verdictWords", () => {
  it("verdictWords 97% healthy, 86% clean soon", () => {
    expect(verdictWords(97, -0.12, "ph")).toEqual({
      headline: "Probe reads 0.12 pH low. Response 97% — healthy.",
      health: "healthy",
    });
    expect(verdictWords(86, 0, "ph")).toEqual({
      headline: "Response 86% — clean or replace the probe soon.",
      health: "clean_soon",
    });
  });
  it("reads high, replace, and EC in the display unit", () => {
    expect(verdictWords(98.3, 0.04, "ph").headline).toBe("Probe reads 0.04 pH high. Response 98.3% — healthy.");
    expect(verdictWords(78, 0, "ph")).toEqual({ headline: "Response 78% — replace the probe.", health: "replace" });
    expect(verdictWords(112, 0, "ph").health).toBe("clean_soon");
    expect(verdictWords(99, -0.05, "ec").headline).toBe("Probe reads 0.05 mS/cm low. Response 99% — healthy.");
  });
});

describe("captureState", () => {
  const now = at(1000);
  it("stale reading disables Capture", () => {
    const s = captureState(now - 125_000, now, true, { buffer: "7.00", kind: "ph" });
    expect(s.enabled).toBe(false);
    expect(s.reason).toBe("No reading from the feed pH probe for 2 min. Check it's plugged in.");
    expect(OFFLINE_AFTER_MS).toBe(120_000);
  });
  it("waits for stable, then names the point", () => {
    expect(captureState(now - 2_000, now, false, { buffer: "7.00", kind: "ph" })).toEqual({
      enabled: false,
      label: "Capture 7.00 point · waiting for stable",
      reason: null,
    });
    expect(captureState(now - 2_000, now, true, { buffer: "7.00", kind: "ph" })).toEqual({
      enabled: true,
      label: "Capture 7.00 point",
      reason: null,
    });
    expect(captureState(null, now, true, { buffer: "1.413 mS/cm", kind: "ec" }).reason).toBe(
      "No reading from the feed EC probe yet.",
    );
  });
});

describe("refusalView", () => {
  it("expired session restarts from buffer 1", () => {
    const v = refusalView({ kind: "error", code: "invalid", message: "Calibration session expired. Start again." });
    expect(v).toEqual({
      kind: "expired",
      text: "Your last calibration session expired. Start again from buffer 1.",
      restartStep: 2,
    });
  });
  it("a moving reading offers Capture anyway; anything else shows the server's words", () => {
    expect(
      refusalView({
        kind: "error",
        code: "guard_refused",
        message: "The reading is not steady yet: nothing was captured. Wait, or capture it anyway.",
        data: { stable: false, raw: 7.1 },
      }),
    ).toEqual({ kind: "moving", text: "Reading still moving — calibration may be off.", restartStep: null });
    expect(
      refusalView({ kind: "error", code: "invalid", message: "No reading from the feed pH probe for 2 min. Check it's plugged in." }),
    ).toEqual({ kind: "other", text: "No reading from the feed pH probe for 2 min. Check it's plugged in.", restartStep: null });
  });
});

describe("sessionStore", () => {
  const memory = new Map<string, string>();
  const storage = {
    getItem: (k: string) => memory.get(k) ?? null,
    setItem: (k: string, v: string) => void memory.set(k, v),
    removeItem: (k: string) => void memory.delete(k),
  };
  afterEach(() => memory.clear());
  const entry: StoredSession = {
    session_id: "s1",
    expires_at: "2026-10-23T02:30:00Z",
    step: 3,
    room_id: "room:",
    probe: "feed_ph",
    kind: "ph",
    solutions: [7, 4],
    raw_entity_id: "sensor.demo_tank_ph",
    temperature_entity_id: null,
    dosing_paused: true,
    points: [7.04, null],
  };
  it("keeps the session under crop-steering.cal-session and resumes it only before it expires", () => {
    const store = sessionStore(storage);
    store.set(entry);
    expect(JSON.parse(memory.get("crop-steering.cal-session")!)).toMatchObject({ session_id: "s1", expires_at: entry.expires_at, step: 3 });
    expect(store.resumable("room:", Date.parse("2026-10-23T02:29:00Z"))?.session_id).toBe("s1");
    expect(store.resumable("room:", Date.parse("2026-10-23T02:30:00Z"))).toBeNull();
    expect(store.resumable("room:room_b_", Date.parse("2026-10-23T02:00:00Z"))).toBeNull();
    store.clear();
    expect(store.get()).toBeNull();
  });
  it("reads a damaged or missing store as none", () => {
    memory.set("crop-steering.cal-session", "{nope");
    expect(sessionStore(storage).get()).toBeNull();
    expect(sessionStore(null).get()).toBeNull();
  });
});

describe("proofLine and isApplied", () => {
  it("ticks a corrected reading within 0.1 of the buffer, from the corrected sensor only when it uses this calibration", () => {
    const states = {
      "sensor.crop_steering_feed_ph_corrected": {
        entity_id: "sensor.crop_steering_feed_ph_corrected",
        state: "4.01",
        attributes: { applied: true, slope_pct: 98.3, offset: 0.04 },
      },
    } as States;
    const result = { slope_pct: 98.3, offset: 0.04 };
    expect(proofLine(states, "", "feed_ph", 4, result, 2)).toEqual({ text: "Now reads 4.01 in pH 4.00 buffer", ok: true });
    expect(proofLine(states, "", "feed_ph", 4, { slope_pct: 97, offset: 0.04 }, 2)).toBeNull();
    // Never more digits than the raw probe reads.
    states["sensor.crop_steering_feed_ph_corrected"].state = "3.999";
    expect(proofLine(states, "", "feed_ph", 4, result, 2)?.text).toBe("Now reads 4.00 in pH 4.00 buffer");
    states["sensor.crop_steering_feed_ph_corrected"].state = "4.2";
    expect(proofLine(states, "", "feed_ph", 4, result, 2)).toEqual({ text: "Now reads 4.20 in pH 4.00 buffer", ok: false });
    expect(isApplied({ records: [{ id: "r1", probe: "feed_ph", applied: true }] }, "r1")).toBe(true);
    expect(isApplied({ records: [{ id: "r1", probe: "feed_ph", applied: false }] }, "r1")).toBe(false);
  });
});

describe("the demo integration", () => {
  afterEach(() => vi.useRealTimers());
  it("settles the reading, captures both points, applies, reads back and undoes", async () => {
    vi.useFakeTimers({ now: Date.parse("2026-10-23T01:00:00Z") });
    let states = createDemo(Date.now());
    const demo = new OperatorDemo(
      () => states,
      (next) => (states = next),
    );
    const controller = { operator: <T,>(action: string, data: Record<string, unknown> = {}) => demo.call<T>(action as never, data) };
    const start = await callV2<{ session_id: string; raw_entity_id: string; solutions: number[] }>(controller, "calibration_start", {
      room_id: "room:",
      probe: "feed_ph",
    });
    expect(start.kind).toBe("ok");
    if (start.kind !== "ok") return;
    expect(start.data.solutions).toEqual([7, 4]);
    const raw = () => Number(states[start.data.raw_entity_id].state);
    const first = raw();
    // Still moving: the integration refuses and stores nothing.
    const early = await callV2(controller, "calibration_capture", { session_id: start.data.session_id, point: 0 });
    expect(early).toMatchObject({ kind: "error", code: "guard_refused", data: { stable: false } });
    vi.advanceTimersByTime(90_000);
    expect(raw()).not.toBe(first);
    const p0 = await callV2<{ stable: boolean; raw: number }>(controller, "calibration_capture", { session_id: start.data.session_id, point: 0 });
    expect(p0).toMatchObject({ kind: "ok", data: { stable: true, raw: 7.04 } });
    vi.advanceTimersByTime(90_000);
    await callV2(controller, "calibration_capture", { session_id: start.data.session_id, point: 1 });
    const commit = await callV2<{ record_id: string; slope_pct: number; offset: number; verdict: string }>(controller, "calibration_commit", {
      session_id: start.data.session_id,
    });
    expect(commit).toMatchObject({ kind: "ok", data: { slope_pct: 98.3, offset: 0.04, verdict: "pass" } });
    if (commit.kind !== "ok") return;
    expect(commit.eventIds).toHaveLength(1);
    const read = async () =>
      (await callV2<{ records: { id: string; probe: string; applied?: boolean }[] }>(controller, "calibration_get", { room_id: "room:" })) as {
        kind: "ok";
        data: { records: { id: string; probe: string; applied?: boolean }[] };
      };
    expect(isApplied((await read()).data, commit.data.record_id)).toBe(true);
    expect(states["sensor.crop_steering_feed_ph_corrected"].state).toBe("3.999");
    // The session is over: a second commit finds it expired.
    const again = await callV2(controller, "calibration_commit", { session_id: start.data.session_id });
    expect(refusalView(again as never).kind).toBe("expired");
    await revertEvents(controller, commit.eventIds);
    expect(isApplied((await read()).data, commit.data.record_id)).toBe(false);
    // Undoing twice is refused: the calibration in force is no longer this one.
    await expect(revertEvents(controller, commit.eventIds)).rejects.toThrow(/changed/);
  });
  it("refuses a room with no feed probe and an older integration has none of it", async () => {
    let states = createDemo(Date.now());
    const demo = new OperatorDemo(
      () => states,
      (next) => (states = next),
    );
    const controller = { operator: <T,>(action: string, data: Record<string, unknown> = {}) => demo.call<T>(action as never, data) };
    expect(await callV2(controller, "calibration_start", { room_id: "room:room_b_", probe: "feed_ph" })).toMatchObject({
      kind: "error",
      code: "invalid",
      message: "The room has no feed pH probe set up",
    });
    const old = new OperatorDemo(
      () => states,
      (next) => (states = next),
      null,
      null,
      "3.17",
    );
    expect(
      await callV2({ operator: <T,>(a: string, d: Record<string, unknown> = {}) => old.call<T>(a as never, d) }, "calibration_start", {
        room_id: "room:",
        probe: "feed_ph",
      }),
    ).toEqual({ kind: "missing" });
  });
});
