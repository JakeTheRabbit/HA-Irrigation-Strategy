import { describe, expect, it } from "vitest";
import type { CsEvent } from "./parity-types";
import { demoJournal, demoJournalVwc } from "./parity-demo/journal";
import { shotLog, tableShotLog, vwcAfter, vwcBefore } from "./zone-shot-log";

const ON = Date.UTC(2026, 9, 22, 6, 0);
const MIN = 60_000;
const at = (minutes: number) => new Date(ON + minutes * MIN).toISOString();

let seq = 0;
function event(kind: string, minutes: number, zone: number, intent: string, data: Record<string, unknown>): CsEvent {
  return {
    v: 1,
    id: `e${++seq}`,
    ts: at(minutes),
    room_id: "room:",
    zone,
    kind,
    outcome: "ok",
    code: null,
    source: { actor: "engine" },
    correlation: { intent_id: intent },
    data,
  };
}
/** A started/completed pair as the controller journals it: the phase on the start only. */
function shot(minutes: number, zone: number, phase: string, metered: number | null = 1.32, elapsed = 52) {
  const intent = `i-${zone}-${minutes}`;
  return [
    event("shot.started", minutes, zone, intent, { phase, kind: "p2_topup", commanded_l: 1.21, vwc_before: 58 }),
    event("shot.completed", minutes + elapsed / 60, zone, intent, {
      elapsed_s: elapsed,
      commanded_l: 1.21,
      metered_l: metered,
      vwc_before: 58,
      ec_before: 4.8,
    }),
  ];
}

describe("zone shot log", () => {
  it("shot log keeps only this zone's completed shots since lights-on, newest first", () => {
    const events = [
      ...shot(-30, 2, "P3"), // before lights-on
      ...shot(70, 2, "P1"),
      ...shot(75, 1, "P1"), // another zone
      ...shot(190, 2, "P2"),
      event("shot.started", 300, 2, "running", { phase: "P2", commanded_l: 1.21 }), // not finished
      event("shot.aborted", 320, 2, "aborted", { elapsed_s: 10, commanded_l: 0.2, metered_l: null }),
    ];
    const rows = shotLog(events, 2, ON, 40);
    expect(rows.map((row) => row.at)).toEqual([ON + 190 * MIN, ON + 70 * MIN]);
    expect(rows.map((row) => row.phase)).toEqual(["P2", "P1"]);
    expect(rows[0]).toMatchObject({ seconds: 52, vwcBefore: 58, end: ON + 190 * MIN + 52_000 });
  });

  it("shot log converts litres to mL per plant", () => {
    const [metered] = shotLog(shot(70, 2, "P1", 1.32), 2, ON, 40);
    expect(metered).toMatchObject({ mlPerPlant: 33, metered: true });
    // No meter: the litres the controller commanded, said as such.
    const [commanded] = shotLog(shot(70, 2, "P1", null), 2, ON, 40);
    expect(commanded).toMatchObject({ mlPerPlant: 30.25, metered: false });
    expect(shotLog(shot(70, 2, "P1"), 2, ON, 0)[0].mlPerPlant).toBeNull();
  });

  it("shot log finds the start of a completed shot without its started event", () => {
    const [, completed] = shot(70, 2, "P1");
    const [row] = shotLog([completed], 2, ON, 40);
    expect(row).toMatchObject({ at: ON + 70 * MIN, phase: "", seconds: 52 });
  });

  it("the 3.17 shot table gives the same rows, phase from the shot kind", () => {
    const rows = tableShotLog(
      [
        { start: at(-20), kind: "p3_emergency", litres: 1 },
        { start: at(70), kind: "p1_ramp", litres: 1.2 },
        { start: at(190), kind: "p2_topup", litres: null },
        "junk",
      ],
      ON,
      40,
    );
    expect(rows).toEqual([
      { at: ON + 190 * MIN, end: ON + 190 * MIN, phase: "P2", mlPerPlant: null, metered: true, seconds: null, vwcBefore: null },
      { at: ON + 70 * MIN, end: ON + 70 * MIN, phase: "P1", mlPerPlant: 30, metered: true, seconds: null, vwcBefore: null },
    ]);
    expect(tableShotLog(undefined, ON, 40)).toBeNull();
  });

  const series = [0, 5, 10, 15, 20, 25, 30].map((m) => ({ t: ON + m * MIN, v: 58 + m / 10 }));

  it("vwcAfter picks the reading nearest five minutes after the shot", () => {
    expect(vwcAfter(series, ON + MIN)).toBe(58.5); // settled at +6 min: the +5 reading
    expect(vwcAfter(series, ON + 8 * MIN)).toBe(59.5); // settled at +13 min: +15 over +10
    expect(vwcAfter(series, ON, 20 * MIN)).toBe(60);
  });

  it("vwcAfter never takes a reading from before the shot ended", () => {
    // Settled at +9 min: +10 is nearest, but only readings at or after the end (+4) count.
    expect(vwcAfter(series, ON + 4 * MIN)).toBe(59);
    // The shot ended at +12: the +10 reading is before it, so the +15 one stands.
    expect(vwcAfter(series, ON + 12 * MIN)).toBe(59.5);
    expect(vwcAfter([{ t: ON, v: 70 }], ON + MIN)).toBeNull();
  });

  it("vwcAfter takes what there is for a shot that ended under five minutes ago", () => {
    const recent = [{ t: ON - 5 * MIN, v: 57 }, { t: ON + MIN, v: 58.6 }];
    expect(vwcAfter(recent, ON)).toBe(58.6);
    expect(vwcAfter([{ t: ON - 5 * MIN, v: 57 }], ON)).toBeNull();
  });

  it("vwcAfter returns null without a reading inside 15 min", () => {
    expect(vwcAfter(series, ON + 60 * MIN)).toBeNull();
    expect(vwcAfter([], ON)).toBeNull();
  });

  it("vwcBefore is the last reading at or before the shot, within 15 min", () => {
    expect(vwcBefore(series, ON + 12 * MIN)).toBe(59);
    expect(vwcBefore(series, ON - MIN)).toBeNull();
    expect(vwcBefore(series, ON + 50 * MIN)).toBeNull();
  });

  it("the demo's probe rises after every Journal shot, from the shot's own VWC before", () => {
    const now = Date.UTC(2026, 9, 23, 3, 0);
    for (const [room, prefix] of [["room:", ""], ["room:room_b_", "room_b_"]])
      for (const zone of [1, 2, 3]) {
        const id = `sensor.crop_steering_${prefix}vwc_zone_${zone}`;
        // The probe's own day, every 5 min for 50 h: drying all the way, as if never watered.
        const own = Array.from({ length: 601 }, (_, i) => ({
          time: new Date(now - (600 - i) * 5 * 60_000).toISOString(),
          value: 70 - i * 0.03,
        }));
        const flat = [{ entityId: id, label: id, points: own }];
        const [series] = demoJournalVwc(flat, now);
        const points = series.points.map((p) => ({ t: Date.parse(p.time), v: p.value }));
        const rows = shotLog(demoJournal(room, now), zone, 0, 40);
        for (const row of rows) {
          expect(vwcBefore(points, row.at)).toBeCloseTo(row.vwcBefore!, 1);
          expect(vwcAfter(points, row.end)!).toBeGreaterThanOrEqual(row.vwcBefore!);
        }
      }
  });
});
