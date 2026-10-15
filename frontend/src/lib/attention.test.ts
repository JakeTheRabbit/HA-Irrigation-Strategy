import { describe, expect, it } from "vitest";
import {
  roomReference,
  underSince,
  zoneAttention,
  type AttentionInput,
  type ZoneFacts,
} from "./attention";
import type { Notice } from "./types";

const H = 3_600_000;
const now = Date.UTC(2026, 8, 28, 4, 0);
const format: AttentionInput["format"] = {
  clock: (time) => new Date(time).toISOString().slice(11, 16),
  number: (value, digits = 1) => value.toLocaleString("en", { maximumFractionDigits: digits }),
  perPlant: (ml) => (ml < 1000 ? `${Math.round(ml)} mL` : `${(ml / 1000).toFixed(1)} L`),
};
const zone = (id: number, facts: Partial<ZoneFacts> = {}): ZoneFacts => ({
  id,
  name: `Zone ${id}`,
  phase: "P2",
  vwc: 58,
  ec: 4.2,
  vwcIssue: null,
  ecIssue: null,
  excluded: [],
  mlPerPlant: 1400,
  rewater: 55,
  readings: [],
  lastShot: now - 30 * 60_000,
  jevPausedUntil: null,
  watering: true,
  ...facts,
});
const run = (zones: ZoneFacts[], extra: Partial<AttentionInput> = {}) =>
  zoneAttention({
    now,
    zones,
    poreEc: [3.5, 6],
    notices: [],
    rescues: [],
    format,
    ...extra,
  });
/** Readings every ten minutes from `hours` ago to now, at `value`. */
const flat = (hours: number, value: number) =>
  Array.from({ length: hours * 6 + 1 }, (_, index) => ({
    time: now - hours * H + index * 10 * 60_000,
    value,
  }));

describe("a quiet room", () => {
  it("flags no zone that is in its band, watered like the others and fully probed", () => {
    expect(run([zone(1), zone(2), zone(3)]).size).toBe(0);
  });
});

describe("pore EC outside the stage's range", () => {
  it("says which way, against the stage's band", () => {
    const flags = run([zone(1, { ec: 3.07 }), zone(2, { ec: 6.4 }), zone(3)]);
    expect(flags.get(1)).toEqual([
      { rule: "pore-ec", level: "warning", text: "Pore EC 3.1, under the stage’s 3.5–6" },
    ]);
    expect(flags.get(2)?.[0].text).toBe("Pore EC 6.4, over the stage’s 3.5–6");
    expect(flags.has(3)).toBe(false);
  });
  it("needs a stage to compare with", () => {
    expect(run([zone(1, { ec: 1 })], { poreEc: null }).size).toBe(0);
  });
});

describe("water per plant against the room", () => {
  it("flags more than 140% and less than 70% of the room's median zone, its own water included", () => {
    const flags = run([
      zone(1, { mlPerPlant: 2800 }),
      zone(2, { mlPerPlant: 1400 }),
      zone(3, { mlPerPlant: 1300 }),
      zone(4, { mlPerPlant: 800 }),
    ]);
    // The median of 800, 1300, 1400 and 2800 is 1350.
    expect(flags.get(1)?.[0].text).toBe("2.8 L/plant today, 2.1× the room");
    expect(flags.get(4)?.[0].text).toBe("800 mL/plant today, 0.6× the room");
    expect(flags.has(2) || flags.has(3)).toBe(false);
  });
  it("compares two zones with each other, by name", () => {
    const flags = run([zone(1, { mlPerPlant: 2800 }), zone(2, { mlPerPlant: 1400 })]);
    expect(flags.get(1)?.[0].text).toBe("2.8 L/plant today, 2× Zone 2");
    expect(flags.get(2)?.[0].text).toBe("1.4 L/plant today, 0.5× Zone 1");
  });
  it("says nothing for a room of one, a zone without a plant count, or too early in the day", () => {
    expect(run([zone(1, { mlPerPlant: 2800 })]).size).toBe(0);
    expect(run([zone(1, { mlPerPlant: null }), zone(2), zone(3)]).size).toBe(0);
    expect(
      run([zone(1, { mlPerPlant: 150 }), zone(2, { mlPerPlant: 40 }), zone(3, { mlPerPlant: 60 })])
        .size,
    ).toBe(0);
  });
  it("finds the reference the rules name", () => {
    const zones = [1, 2, 3].map((id) => zone(id, { mlPerPlant: id * 100 }));
    expect(roomReference(zones, 1)).toEqual({ ml: 200, name: null });
    expect(roomReference(zones.slice(0, 2), 1)).toEqual({ ml: 200, name: "Zone 2" });
    expect(roomReference(zones.slice(0, 1), 1)).toBeNull();
  });
});

describe("under the re-water point in P2 with no shot", () => {
  it("flags a zone that has sat under it for over an hour, critical", () => {
    const flags = run([zone(1, { vwc: 52, readings: flat(2, 52), lastShot: now - 3 * H })]);
    expect(flags.get(1)?.[0]).toEqual({
      rule: "not-watered",
      level: "critical",
      text: "Under its re-water point (55%) for 120 min, no shot",
    });
  });
  it("is quiet for the first hour, after a shot, outside P2, or while the zone is not watered", () => {
    const readings = [...flat(2, 57).slice(0, 8), ...flat(2, 52).slice(8)];
    // Under since 40 minutes ago.
    expect(run([zone(1, { vwc: 52, readings, lastShot: now - 3 * H })]).size).toBe(0);
    const long = flat(2, 52);
    expect(run([zone(1, { vwc: 52, readings: long, lastShot: now - 20 * 60_000 })]).size).toBe(0);
    expect(run([zone(1, { vwc: 52, readings: long, phase: "P3", lastShot: null })]).size).toBe(0);
    expect(run([zone(1, { vwc: 52, readings: long, watering: false, lastShot: null })]).size).toBe(
      0,
    );
  });
  it("counts from the first reading of the latest run under the level", () => {
    const readings = [
      { time: now - 3 * H, value: 50 },
      { time: now - 2 * H, value: 58 },
      { time: now - 90 * 60_000, value: 54 },
      { time: now, value: 53 },
    ];
    expect(underSince(readings, 55)).toBe(now - 90 * 60_000);
    expect(underSince([...readings, { time: now, value: 60 }], 55)).toBeNull();
    expect(underSince([], 55)).toBeNull();
  });
});

describe("probes", () => {
  it("flags an unusable moisture probe as critical, a pore EC probe and a probe left out as warnings", () => {
    const flags = run([
      zone(1, { vwc: null, vwcIssue: "not reporting" }),
      zone(2, { ec: null, ecIssue: "stale (older than 20 minutes)" }),
      zone(3, {
        excluded: [
          { probe: "sensor.b", reason: "out of range", kind: "vwc" },
          { probe: "sensor.c", reason: "not reporting", kind: "vwc" },
        ],
      }),
    ]);
    expect(flags.get(1)?.[0]).toEqual({
      rule: "probe",
      level: "critical",
      text: "Moisture probe not reporting",
    });
    expect(flags.get(2)?.[0].text).toBe("Pore EC probe stale (older than 20 minutes)");
    expect(flags.get(3)?.[0].text).toBe("2 moisture probes left out: out of range, not reporting");
  });
});

describe("the zone's own notices", () => {
  const notice = (id: string, severity: Notice["severity"], zoneId?: number): Notice => ({
    id,
    title: `${id} title`,
    detail: "",
    severity,
    ...(zoneId === undefined ? {} : { zoneId }),
  });
  it("flag its card; the room's and information notices do not", () => {
    const flags = run([zone(1), zone(2)], {
      notices: [
        notice("zone-1-status", "critical", 1),
        notice("room-hardware-fault", "critical"),
        notice("zone-2-info", "info", 2),
      ],
    });
    expect(flags.get(1)).toEqual([
      { rule: "alert", level: "critical", text: "zone-1-status title" },
    ]);
    expect(flags.has(2)).toBe(false);
  });
  it("leave a sensor notice to the probe rule that says the same", () => {
    const flags = run([zone(1, { vwc: null, vwcIssue: "not reporting" })], {
      notices: [notice("zone-1-sensors", "warning", 1)],
    });
    expect(flags.get(1)?.map((reason) => reason.rule)).toEqual(["probe"]);
  });
});

describe("rescue shots and Jev", () => {
  it("flags a rescue shot in the last 12 hours", () => {
    const flags = run([zone(1), zone(2)], {
      rescues: [
        { zoneId: 1, time: now - 5 * H },
        { zoneId: 2, time: now - 13 * H },
      ],
    });
    expect(flags.get(1)?.[0].text).toBe("Rescue shot at 23:00");
    expect(flags.has(2)).toBe(false);
  });
  it("flags Jev's setpoints paused after a revert, until the pause ends", () => {
    expect(run([zone(1, { jevPausedUntil: now + 2 * H })]).get(1)?.[0].text).toBe(
      "Jev’s setpoint changes paused until 06:00 after a revert",
    );
    expect(run([zone(1, { jevPausedUntil: now - 1 })]).size).toBe(0);
  });
});

describe("order", () => {
  it("puts critical reasons first, then the rules in their order, so the card leads with the worst", () => {
    const flags = run(
      [
        zone(1, {
          ec: 7,
          mlPerPlant: 3000,
          vwc: 52,
          readings: flat(2, 52),
          lastShot: now - 3 * H,
          jevPausedUntil: now + H,
        }),
        zone(2),
        zone(3),
      ],
      { rescues: [{ zoneId: 1, time: now - H }] },
    );
    expect(flags.get(1)?.map((reason) => reason.rule)).toEqual([
      "not-watered",
      "rescue",
      "pore-ec",
      "water",
      "jev-paused",
    ]);
  });
});
