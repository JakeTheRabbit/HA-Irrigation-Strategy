import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  alignBands,
  appendLive,
  atHour,
  compareDays,
  dayTrace,
  dryDown,
  duration,
  earlierDays,
  earlierEntities,
  earlierTraces,
  growDay,
  joinRows,
  levels,
  morningDryback,
  nextShot,
  NOT_REPORTING,
  openSeconds,
  phaseAt,
  phaseBands,
  phaseTargets,
  reachedHour,
  readings,
  revisionAt,
  setpointChanges,
  setpointSteps,
  timelineEntities,
  typicalDay,
  unprojected,
  valueAt,
  valveShots,
  zoneBlocks,
  type Block,
  type DayTrace,
  type GrowDay,
  type PhaseBand,
  type Reading,
  type Shot,
  type TimelineRow,
} from "./day-timeline";
import { createDemo, demoDay } from "./demo";
import { buildRoom, discoverRooms } from "./model";
import type { EntityState } from "./types";

const at = (time: string, date = "2026-09-22") => Date.parse(`${date}T${time}Z`);
const row = (state: string, time: number, attributes?: Record<string, unknown>): TimelineRow => ({
  state,
  time,
  ...(attributes ? { attributes } : {}),
});
const decision = (time: number, fired: string[] = [], blocked: string[] = []) =>
  row(fired[0] ?? blocked[0] ?? "Holding — all zones in band", time, { fired, blocked });

describe("grow day", () => {
  const local = (day: number, hour: number, minute = 0) =>
    new Date(2026, 8, day, hour, minute).getTime();
  it("runs from the last lights-on to the next, lights-off inside it", () => {
    expect(growDay(10, 22, local(23, 14))).toEqual({
      start: local(23, 10),
      lightsOff: local(23, 22),
      end: local(24, 10),
    });
    // Before lights-on it is still yesterday's grow-day; at lights-on today's begins.
    expect(growDay(10, 22, local(23, 9, 59))!.start).toBe(local(22, 10));
    expect(growDay(10, 22, local(23, 10))!.start).toBe(local(23, 10));
  });
  it("crosses midnight with the lights and takes fractional hours", () => {
    const night = { start: local(23, 20), lightsOff: local(24, 8), end: local(24, 20) };
    expect(growDay(20, 8, local(23, 23))).toEqual(night);
    expect(growDay(20, 8, local(24, 7))).toEqual(night);
    expect(growDay(10.5, 22.25, local(23, 12))).toEqual({
      start: local(23, 10, 30),
      lightsOff: local(23, 22, 15),
      end: local(24, 10, 30),
    });
  });
  it("needs a real photoperiod", () => {
    for (const [on, off] of [
      [null, 22],
      [10, null],
      [10, 10],
      [24, 10],
      [-1, 10],
    ])
      expect(growDay(on, off, local(23, 12))).toBeNull();
  });
});

// Flower 2 on 23 September 2026 (UTC; lights-on 10:00 NZST is 22:00Z), as the recorder returned it.
const START = at("22:00:00");
const decisions = [
  decision(START),
  decision(at("22:01:18.029"), ["Z2 P3 P3 emergency VWC 20<20"]),
  decision(at("22:02:18.786")),
  decision(at("22:07:56.822"), [
    "Z1 P1 P0 bypass VWC 25<=rewater 30 | P1 ramp VWC 25<36",
    "Z3 P1 P0 bypass VWC 32<=rewater 40 | P1 ramp VWC 32<49",
  ]),
  decision(at("22:08:57.611")),
  decision(at("22:14:36.300"), ["Z2 P1 MIN-DAILY floor 0.0<8.4L (guaranteed)"]),
  decision(at("22:18:13.309"), ["Z1 P1 MIN-DAILY floor 4.0<8.4L (guaranteed)"]),
  decision(at("22:19:13.984")),
];

describe("phase bands", () => {
  it("draws each phase as recorded", () => {
    const zone1 = [row("P3", START), row("P0", at("22:02:18.694")), row("P1", at("22:07:56.719"))];
    const bands = phaseBands(zone1, START, at("22:30:00"));
    expect(bands).toEqual([
      { phase: "P3", start: START, end: at("22:02:18.694") },
      { phase: "P0", start: at("22:02:18.694"), end: at("22:07:56.719") },
      { phase: "P1", start: at("22:07:56.719"), end: at("22:30:00") },
    ]);
    expect(phaseAt(bands, at("22:05:00"))).toBe("P0");
    expect(phaseAt(bands, at("22:31:00"))).toBeNull();
  });
  it("leaves a restart as a gap, joins repeats and clips to the day", () => {
    const restart = [
      row("P3", at("21:00:00")),
      row("unavailable", at("21:09:00")),
      row("P3", at("21:10:00")),
      row("P3", at("21:30:00")),
    ];
    expect(phaseBands(restart, at("21:05:00"), START)).toEqual([
      { phase: "P3", start: at("21:05:00"), end: at("21:09:00") },
      { phase: "P3", start: at("21:10:00"), end: START },
    ]);
    expect(phaseBands(undefined, START, at("23:00:00"))).toEqual([]);
  });
});

describe("shots", () => {
  it("names each shot by what the controller posted after the valve closed", () => {
    const row1 = [
      row("off", START),
      row("on", at("22:03:22.638")),
      row("off", at("22:04:47.630")),
      row("on", at("22:15:40.100")),
      row("off", at("22:18:11.000")),
    ];
    const shots = valveShots(row1, decisions, 1, START, at("22:30:00"));
    expect(shots).toEqual([
      {
        start: at("22:03:22.638"),
        end: at("22:04:47.630"),
        open: false,
        phase: "P1",
        reason: "P0 bypass VWC 25<=rewater 30 | P1 ramp VWC 25<36",
      },
      {
        start: at("22:15:40.100"),
        end: at("22:18:11.000"),
        open: false,
        phase: "P1",
        reason: "MIN-DAILY floor 4.0<8.4L (guaranteed)",
      },
    ]);
    // The phase changed in the same post, so the first P1 shot sits in the recorded P0 band.
    const bands = phaseBands(
      [row("P3", START), row("P0", at("22:02:18.694")), row("P1", at("22:07:56.719"))],
      START,
      at("22:30:00"),
    );
    expect(phaseAt(bands, shots[0].start)).toBe("P0");
  });
  it("starts a shot open at lights-on at the window, and keeps one still running open", () => {
    const row2 = [
      row("on", START),
      row("off", at("22:01:16.000")),
      row("on", at("22:12:03.000")),
      row("off", at("22:14:34.000")),
      row("on", at("22:29:00.000")),
    ];
    const shots = valveShots(row2, decisions, 2, START, at("22:30:00"));
    expect(shots.map(({ phase, reason, open }) => ({ phase, reason, open }))).toEqual([
      { phase: "P3", reason: "P3 emergency VWC 20<20", open: false },
      { phase: "P1", reason: "MIN-DAILY floor 0.0<8.4L (guaranteed)", open: false },
      { phase: null, reason: null, open: true },
    ]);
    expect(shots[0].start).toBe(START);
    expect(shots[2].end).toBe(at("22:30:00"));
  });
  it("starts a phase at the first shot the controller fired in it, not at its later post", () => {
    const zone1 = [row("P3", START), row("P0", at("22:02:18.694")), row("P1", at("22:07:56.719"))];
    const bands = phaseBands(zone1, START, at("22:30:00"));
    const valve = [
      row("off", START),
      row("on", at("22:03:22.638")),
      row("off", at("22:04:47.630")),
    ];
    const shots = valveShots(valve, decisions, 1, START, at("22:30:00"));
    expect(alignBands(bands, shots)).toEqual([
      { phase: "P3", start: START, end: at("22:02:18.694") },
      { phase: "P0", start: at("22:02:18.694"), end: at("22:03:22.638") },
      { phase: "P1", start: at("22:03:22.638"), end: at("22:30:00") },
    ]);
    expect(bands[1].end).toBe(at("22:07:56.719"));
    // A shot fired in the phase it sits in (zone 2's P3 emergency) or never named moves nothing.
    const emergency = valveShots(
      [row("on", START), row("off", at("22:01:16.000"))],
      decisions,
      2,
      START,
      at("22:30:00"),
    );
    expect(alignBands(bands, emergency)).toEqual(bands);
    const unnamed = { ...shots[0], phase: null, reason: null };
    expect(alignBands(bands, [unnamed])).toEqual(bands);
  });
  it("never lends a hand-opened valve another zone's or a later decision", () => {
    // Zone 3 opened by hand: the next post fired only zone 2.
    const row3 = [row("off", START), row("on", at("22:10:00")), row("off", at("22:11:00"))];
    expect(valveShots(row3, decisions, 3, START, at("22:30:00"))).toEqual([
      { start: at("22:10:00"), end: at("22:11:00"), open: false, phase: null, reason: null },
    ]);
  });
});

describe("blocks and holds", () => {
  // Flower 2 on 22 September 2026: a dosing hold during the ramp, then two zones blocked at their
  // daily budget until lights-off, and the kill switch off across a restart.
  const day = [
    decision(at("22:00:00", "2026-09-21")),
    decision(at("00:06:00.712"), [], ["Z2 P1 external hold (nutrient_dosing_active)"]),
    decision(
      at("00:25:18.897"),
      [],
      [
        "Z1 P1 external hold (nutrient_dosing_active)",
        "Z2 P1 external hold (nutrient_dosing_active)",
        "Z3 P1 external hold (nutrient_dosing_active)",
      ],
    ),
    decision(
      at("00:28:23.030"),
      [],
      [
        "Z2 P1 external hold (nutrient_dosing_active)",
        "Z3 P1 external hold (nutrient_dosing_active)",
      ],
    ),
    decision(at("00:45:03.238"), ["Z2 P1 P1 flush/runoff EC 4.9 (at ceiling 27)"]),
    decision(
      at("01:31:47.000"),
      [],
      ["Z2 P1 BLOCK daily-cap 106/80L (budget; emergencies exempt)"],
    ),
    decision(
      at("02:06:57.000"),
      ["Z1 P2 P2 top-up VWC 33<33"],
      ["Z2 P1 BLOCK daily-cap 106/80L (budget; emergencies exempt)"],
    ),
    decision(
      at("03:02:40.000"),
      [],
      [
        "Z1 P2 BLOCK daily-cap 84/80L (budget; emergencies exempt)",
        "Z2 P1 BLOCK daily-cap 106/80L (budget; emergencies exempt)",
      ],
    ),
    decision(at("10:00:14.000")),
    decision(
      at("21:09:37.000"),
      [],
      [
        "Z1 P3 f2-control disabled (kill switch off)",
        "Z2 P3 f2-control disabled (kill switch off)",
      ],
    ),
    decision(at("21:10:37.000")),
  ];
  const from = at("22:00:00", "2026-09-21");
  it("collapses repeats into one interval per unbroken hold", () => {
    expect(zoneBlocks(day, 2, from, START)).toEqual([
      {
        kind: "hold",
        text: "external hold (nutrient_dosing_active)",
        start: at("00:06:00.712"),
        end: at("00:45:03.238"),
        open: false,
      },
      {
        kind: "cap",
        text: "BLOCK daily-cap 106/80L (budget; emergencies exempt)",
        start: at("01:31:47.000"),
        end: at("10:00:14.000"),
        open: false,
      },
      {
        kind: "hold",
        text: "f2-control disabled (kill switch off)",
        start: at("21:09:37.000"),
        end: at("21:10:37.000"),
        open: false,
      },
    ]);
    expect(
      zoneBlocks(day, 1, from, START).map(({ kind, start, end }) => [kind, start, end]),
    ).toEqual([
      ["hold", at("00:25:18.897"), at("00:28:23.030")],
      ["cap", at("03:02:40.000"), at("10:00:14.000")],
      ["hold", at("21:09:37.000"), at("21:10:37.000")],
    ]);
    expect(zoneBlocks(day, 4, from, START)).toEqual([]);
  });
  it("keeps one interval while only the numbers move, and one still held open at the end", () => {
    const rows = [
      decision(at("12:00:00"), [], ["Z1 P2 BLOCK daily-cap 80/80L (budget; emergencies exempt)"]),
      decision(at("12:30:00"), [], ["Z1 P2 BLOCK daily-cap 81.5/80L (budget; emergencies exempt)"]),
      decision(
        at("13:00:00"),
        [],
        [
          "Z1 P2 BLOCK high EC 9.1 — feed not dilutive (self-clears)",
          "Z2 P2 source-water EC 3.6 out of [1,3.5]",
        ],
      ),
    ];
    expect(zoneBlocks(rows, 1, at("11:00:00"), at("14:00:00"))).toEqual([
      {
        kind: "cap",
        text: "BLOCK daily-cap 80/80L (budget; emergencies exempt)",
        start: at("12:00:00"),
        end: at("13:00:00"),
        open: false,
      },
      {
        kind: "block",
        text: "BLOCK high EC 9.1 — feed not dilutive (self-clears)",
        start: at("13:00:00"),
        end: at("14:00:00"),
        open: true,
      },
    ]);
    expect(zoneBlocks(rows, 2, at("11:00:00"), at("14:00:00"))[0]).toMatchObject({
      kind: "hold",
      open: true,
    });
    // Without the attribute lists nothing is guessed from the state text.
    expect(
      zoneBlocks([row("Z1 P2 BLOCK daily-cap 80/80L", at("12:00:00"))], 1, 0, at("14:00:00")),
    ).toEqual([]);
  });
});

describe("setpoint changes", () => {
  it("lists each change inside the day, not a restart's unavailable reading", () => {
    const rows = {
      "number.a": [
        row("33.7", START),
        row("unavailable", at("23:09:00")),
        row("33.7", at("23:10:00")),
        row("30.2", at("23:30:00")),
      ],
      "number.b": [row("3", START), row("2.5", at("23:00:00"))],
      // The value carried in at lights-on is where the day starts, not a change today.
      "number.c": [row("6", START)],
    };
    expect(
      setpointChanges(rows, ["number.a", "number.b", "number.c"], START, at("23:59:00")),
    ).toEqual([
      { entityId: "number.b", time: at("23:00:00"), from: 3, to: 2.5 },
      { entityId: "number.a", time: at("23:30:00"), from: 33.7, to: 30.2 },
    ]);
  });
  it("reads numbers as steps and readings, skipping what is not a number", () => {
    const rows = [row("30.2", START), row("", at("22:10:00")), row("31", at("22:20:00"))];
    expect(readings(rows, START, at("23:00:00"))).toEqual([
      { time: START, value: 30.2 },
      { time: at("22:20:00"), value: 31 },
    ]);
    expect(levels(rows, START, at("23:00:00"))).toEqual([
      { value: 30.2, start: START, end: at("22:10:00") },
      { value: 31, start: at("22:20:00"), end: at("23:00:00") },
    ]);
  });
});

const drying = (from: number, minutes: number, start: number, rate: number): Reading[] =>
  Array.from({ length: minutes + 1 }, (_, minute) => ({
    time: from + minute * 60_000,
    // A probe's noise, alternating around the trend.
    value: start - (rate * minute) / 60 + (minute % 2 ? 0.04 : -0.04),
  }));

describe("dry-down", () => {
  const T = at("02:00:00");
  it("fits the recent fall and says when it reaches the threshold", () => {
    const points = drying(T, 40, 32, 0.8);
    const fit = dryDown(points, 30, T, T + 40 * 60_000)!;
    expect(fit.rate).toBeCloseTo(0.8, 1);
    // 32 - 0.8 * 40/60 = 31.47 now; 1.47 points at 0.8 per hour is about 110 minutes more.
    expect(fit.from.value).toBeCloseTo(31.47, 1);
    expect(Math.abs(fit.at - (T + 150 * 60_000))).toBeLessThan(4 * 60_000);
  });
  it("says nothing without enough recent data or a real fall", () => {
    const now = T + 40 * 60_000;
    expect(dryDown(drying(T, 40, 32, -0.5), 30, T, now)).toBeNull();
    expect(dryDown(drying(T, 40, 32, 0), 30, T, now)).toBeNull();
    expect(dryDown(drying(T, 10, 32, 0.8), 30, T, now)).toBeNull();
    expect(
      dryDown(
        drying(T, 40, 32, 0.8).filter((_, i) => i % 12 === 0),
        30,
        T,
        now,
      ),
    ).toBeNull();
    // Readings before `since` (the shot still wetting up) are not used.
    expect(dryDown(drying(T, 40, 32, 0.8), 30, T + 30 * 60_000, now)).toBeNull();
  });
});

describe("next shot", () => {
  const day: GrowDay = {
    start: START,
    lightsOff: at("10:00:00", "2026-09-23"),
    end: at("22:00:00", "2026-09-23"),
  };
  const now = at("03:00:00", "2026-09-23");
  const shot = (end: number, open = false): Shot => ({
    start: end - 120_000,
    end,
    open,
    phase: "P2",
    reason: null,
  });
  const zone = {
    phase: "P2" as string | null,
    since: at("01:00:00", "2026-09-23"),
    held: null as Block | null,
    lastShot: shot(at("01:50:00", "2026-09-23")) as Shot | null,
    points: drying(at("02:00:00", "2026-09-23"), 60, 32, 0.8),
    vwc: 31.2 as number | null,
    threshold: 30 as number | null,
    ceiling: null as number | null,
    interval: 20 as number | null,
    maxWait: 60 as number | null,
  };
  it("estimates P2 from the dry-down since the last shot settled", () => {
    const next = nextShot(zone, day, now);
    expect(next.basis).toBe("dry-down");
    expect(next.fit!.rate).toBeCloseTo(0.8, 1);
    expect(Math.abs(next.at! - at("04:30:00", "2026-09-23"))).toBeLessThan(5 * 60_000);
    // Past lights-off it is no estimate, though the line is still drawn.
    const early = { ...day, lightsOff: at("04:00:00", "2026-09-23") };
    expect(nextShot(zone, early, now)).toMatchObject({ at: null, basis: "late" });
    expect(nextShot(zone, early, now).fit).toBeDefined();
  });
  it("is due at or under the threshold, settling right after a shot, and silent when flat", () => {
    expect(nextShot({ ...zone, vwc: 29.9 }, day, now)).toEqual({ at: now, basis: "due" });
    expect(nextShot({ ...zone, lastShot: shot(now - 20 * 60_000) }, day, now).basis).toBe(
      "settling",
    );
    const flat = drying(at("02:00:00", "2026-09-23"), 60, 32, 0);
    expect(nextShot({ ...zone, points: flat }, day, now).basis).toBe("no-dry-down");
    expect(nextShot({ ...zone, vwc: null }, day, now).basis).toBe("no-reading");
  });
  it("follows the engine's own timing in P0 and P1", () => {
    const p0 = { ...zone, phase: "P0", since: at("02:30:00", "2026-09-23") };
    expect(nextShot(p0, day, now)).toEqual({ at: at("03:30:00", "2026-09-23"), basis: "p0-wait" });
    expect(nextShot({ ...p0, since: at("01:00:00", "2026-09-23") }, day, now).at).toBe(now);
    const p1 = { ...zone, phase: "P1", ceiling: 36, lastShot: shot(at("02:50:00", "2026-09-23")) };
    expect(nextShot(p1, day, now)).toEqual({
      at: at("03:10:00", "2026-09-23"),
      basis: "p1-interval",
    });
    expect(nextShot({ ...p1, vwc: 36.5 }, day, now).basis).toBe("ramp-done");
  });
  it("estimates nothing while a shot runs, a hold is open, or after lights-off", () => {
    expect(nextShot({ ...zone, lastShot: shot(now, true) }, day, now).basis).toBe("firing");
    const held: Block = { kind: "cap", text: "BLOCK daily-cap", start: 0, end: now, open: true };
    expect(nextShot({ ...zone, held }, day, now).basis).toBe("held");
    expect(nextShot({ ...zone, phase: "P3" }, day, now).basis).toBe("night");
    expect(nextShot(zone, day, at("10:30:00", "2026-09-23")).basis).toBe("night");
  });
});

describe("live updates extend a loaded day", () => {
  const state = (
    entity_id: string,
    value: string,
    changed: number,
    updated = changed,
    attributes: Record<string, unknown> = {},
  ): EntityState => ({
    entity_id,
    state: value,
    attributes,
    last_changed: new Date(changed).toISOString(),
    last_updated: new Date(updated).toISOString(),
  });
  const request = {
    entityIds: ["switch.valve", "sensor.vwc", "sensor.new"],
    attributeIds: ["sensor.decision"],
  };
  const loaded = {
    "switch.valve": [row("off", START)],
    "sensor.vwc": [row("30.1", START)],
    "sensor.decision": [decision(START)],
  };
  it("appends what changed, when it changed", () => {
    const states = {
      "switch.valve": state("switch.valve", "on", at("22:05:00"), at("22:05:30")),
      "sensor.vwc": state("sensor.vwc", "30.1", at("22:06:00")),
      "sensor.decision": state(
        "sensor.decision",
        "Holding — all zones in band",
        START,
        at("22:07:00"),
        { fired: [], blocked: ["Z1 P2 zone disabled"] },
      ),
      "sensor.new": state("sensor.new", "P0", at("22:08:00")),
      "sensor.unrelated": state("sensor.unrelated", "1", at("22:08:00")),
    };
    const rows = appendLive(loaded, states, request);
    expect(rows["switch.valve"]).toEqual([row("off", START), row("on", at("22:05:00"))]);
    // The same reading again is not a new row.
    expect(rows["sensor.vwc"]).toBe(loaded["sensor.vwc"]);
    // The decision's blocked list changed without its state: that is a row, at last_updated.
    expect(rows["sensor.decision"].at(-1)).toEqual(
      row("Holding — all zones in band", at("22:07:00"), {
        fired: [],
        blocked: ["Z1 P2 zone disabled"],
      }),
    );
    expect(rows["sensor.new"]).toEqual([row("P0", at("22:08:00"))]);
    expect(rows["sensor.unrelated"]).toBeUndefined();
    // Pure, and the same object when there is nothing new.
    expect(loaded["switch.valve"]).toEqual([row("off", START)]);
    expect(appendLive(rows, states, request)).toBe(rows);
  });
  it("never rewrites the past with an older state", () => {
    const rows = { "switch.valve": [row("off", START), row("on", at("22:05:00"))] };
    const stale = { "switch.valve": state("switch.valve", "off", at("21:00:00")) };
    expect(appendLive(rows, stale, request)).toBe(rows);
  });
});

describe("what a room's timeline reads", () => {
  it("each zone's phase, valve and probe, the setpoints, and the decision with attributes", () => {
    const states = createDemo(Date.UTC(2026, 8, 23, 3));
    const room = buildRoom(
      states,
      discoverRooms(states).find((item) => item.prefix === "")!,
    );
    const read = timelineEntities(room, states);
    expect(read.zones[0]).toEqual({
      id: 1,
      phase: "sensor.crop_steering_zone_1_phase",
      valve: "switch.demo_valve_1",
      vwc: "sensor.crop_steering_vwc_zone_1",
    });
    for (const id of [
      "sensor.crop_steering_zone_3_phase",
      "switch.demo_valve_2",
      "number.crop_steering_zone_1_p2_vwc_threshold",
      "number.crop_steering_lights_on_hour",
    ])
      expect(read.entityIds).toContain(id);
    expect(read.entityIds.some((id) => id.startsWith("number.crop_steering_f1_"))).toBe(false);
    expect(read.attributeIds).toEqual(["sensor.crop_steering_current_decision"]);
  });
});

describe("the demo's day", () => {
  // Seven hours after Flower 2's demo lights-on, in whatever time zone the test runs.
  const now = new Date(2026, 8, 23, 17, 0).getTime();
  const states = createDemo(now);
  const load = (prefix: string) => {
    const room = buildRoom(
      states,
      discoverRooms(states).find((item) => item.prefix === prefix)!,
    );
    const read = timelineEntities(room, states);
    const hour = (key: string) =>
      Number(states[`number.crop_steering_${prefix}lights_${key}_hour`].state);
    const day = growDay(hour("on"), hour("off"), now)!;
    const rows = demoDay(states, { ...read, start: day.start, end: now }, now);
    const decisions = rows[read.attributeIds[0]];
    return { read, day, rows, decisions };
  };
  it("is a whole plausible day that ends now, recorded only for what was asked", () => {
    const { read, day, rows, decisions } = load("");
    expect(Object.keys(rows).sort()).toEqual([...read.entityIds, ...read.attributeIds].sort());
    expect(
      Object.values(rows)
        .flat()
        .every((item) => item.time >= day.start && item.time <= now),
    ).toBe(true);
    for (const zone of read.zones) {
      const phases = phaseBands(rows[zone.phase], day.start, now).map((band) => band.phase);
      expect(phases).toEqual(["P3", "P0", "P1", "P2"]);
      const shots = valveShots(rows[zone.valve!], decisions, zone.id, day.start, now);
      // The controller named every shot it fired: six ramp shots, then top-ups.
      expect(shots.every((shot) => shot.phase !== null)).toBe(true);
      expect(shots.filter((shot) => shot.phase === "P1")).toHaveLength(6);
      expect(shots.some((shot) => shot.phase === "P2")).toBe(true);
      // The probe's history ends at its live reading.
      expect(rows[zone.vwc!].at(-1)!.state).toBe(states[zone.vwc!].state);
    }
  });
  it("shows a hold, the change that ended it, and a supervisor's setpoint move", () => {
    const { day, rows, decisions } = load("");
    const [hold] = zoneBlocks(decisions, 2, day.start, now);
    expect(hold).toMatchObject({ kind: "hold", open: false });
    expect(hold.text).toMatch(/^source-water EC/);
    const changes = setpointChanges(
      rows,
      ["number.crop_steering_irrigation_ec_max", "number.crop_steering_zone_1_p1_target_vwc"],
      day.start,
      now,
    );
    expect(changes.map(({ entityId, from, to }) => [entityId, from, to])).toEqual([
      ["number.crop_steering_zone_1_p1_target_vwc", 66, 64],
      ["number.crop_steering_irrigation_ec_max", 3.4, 3.5],
    ]);
    expect(Math.abs(changes[1].time - hold.end)).toBeLessThan(60_000);
    // Flower 1's zone 3, disabled for inspection, is held from then on.
    const f1 = load("f1_");
    expect(zoneBlocks(f1.decisions, 3, f1.day.start, now)).toEqual([
      expect.objectContaining({ kind: "hold", text: "zone disabled", open: true }),
    ]);
  });
});

describe("earlier grow-days on today's axis", () => {
  // NZ daylight saving starts 02:00 on 27 September 2026: the grow-day from 10:00 NZST on the 26th
  // to 10:00 NZDT on the 27th is 23 hours long.
  let zone: string | undefined;
  beforeAll(() => {
    zone = process.env.TZ;
    process.env.TZ = "Pacific/Auckland";
  });
  afterAll(() => {
    if (zone === undefined) delete process.env.TZ;
    else process.env.TZ = zone;
  });
  const z = (iso: string) => Date.parse(iso);
  const tenToTen = () => ({ on: 10, off: 22 });
  it("a clock change makes a 23-hour grow-day, placed by hours since its own lights-on", () => {
    const day = growDay(10, 22, z("2026-09-27T01:00:00Z"))!; // 14:00 NZDT on the 27th
    const [yesterday, before] = earlierDays(day, 2, tenToTen);
    expect(yesterday).toEqual({
      start: z("2026-09-25T22:00:00Z"), // 10:00 NZST
      lightsOff: z("2026-09-26T10:00:00Z"), // 22:00 NZST
      end: z("2026-09-26T21:00:00Z"), // 10:00 NZDT
    });
    expect((yesterday.end - yesterday.start) / 3_600_000).toBe(23);
    expect(before.end - before.start).toBe(24 * 3_600_000);
    // A reading at 09:50 NZDT is 22 h 50 min after that day's lights-on, not 23 h 50 min.
    const rows = {
      vwc: [0, 5, 10, 22.8333].map((hour, index) =>
        row(String(30 - index), yesterday.start + hour * 3_600_000),
      ),
    };
    const trace = dayTrace(rows, { vwc: "vwc", valve: null, active: null }, 1, yesterday)!;
    expect(trace.points.at(-1)!.hour).toBeCloseTo(22.8333, 3);
    expect(atHour(trace.points, 22.8333)).toBe(27);
  });
  it("a changed schedule moves the day's lights-on, and its lights-off with it", () => {
    const day = growDay(10, 22, z("2026-09-23T03:00:00Z"))!; // 15:00 NZST on the 23rd
    const change = (at: string) => (time: number) =>
      time < z(at) ? { on: 8, off: 20 } : { on: 10, off: 22 };
    // Changed in the evening: the 22nd came on at 08:00 and ran 26 hours to today's 10:00.
    const [evening] = earlierDays(day, 1, change("2026-09-22T09:00:00Z"));
    expect(evening).toEqual({
      start: z("2026-09-21T20:00:00Z"), // 08:00 on the 22nd
      lightsOff: z("2026-09-22T08:00:00Z"), // 20:00
      end: day.start,
    });
    // Changed before 08:00 on the 22nd: that day came on at 10:00, the one before ran 26 hours.
    const [early, earlier] = earlierDays(day, 2, change("2026-09-21T19:00:00Z"));
    expect(early.start).toBe(z("2026-09-21T22:00:00Z"));
    expect(earlier.start).toBe(z("2026-09-20T20:00:00Z"));
    expect((earlier.end - earlier.start) / 3_600_000).toBe(26);
  });
  it("reads the lights hours, the room switch and the setup revision from the recorded week", () => {
    const states = createDemo(z("2026-09-23T03:00:00Z"));
    const room = buildRoom(
      states,
      discoverRooms(states).find((item) => item.prefix === "")!,
    );
    const read = earlierEntities(room, states);
    for (const id of [
      "sensor.crop_steering_vwc_zone_1",
      "switch.demo_valve_3",
      "number.crop_steering_lights_on_hour",
      "switch.crop_steering_room_active",
    ])
      expect(read.entityIds).toContain(id);
    expect(read.entityIds.some((id) => /phase|threshold|decision/.test(id))).toBe(false);
    expect(read.attributeIds).toEqual(["sensor.crop_steering_engine_config"]);
    const day = growDay(10, 22, z("2026-09-23T03:00:00Z"))!;
    const days = earlierDays(day, 7, tenToTen);
    const config = read.attributeIds[0];
    const vwc = days.flatMap((past) =>
      [0, 6, 12].map((hour) => row("30", past.start + hour * 3_600_000)),
    );
    const week = {
      "sensor.crop_steering_vwc_zone_1": vwc,
      // Moved to 08:00 on the 20th: its grow-day came on then.
      "number.crop_steering_lights_on_hour": [
        row("10", days[6].start),
        row("8", z("2026-09-19T21:00:00Z")),
      ],
      "switch.crop_steering_room_active": [
        row("on", days[6].start),
        row("off", days[1].start + 3_600_000),
        row("on", days[1].start + 7_200_000),
      ],
      [config]: [
        row("ready", days[6].start, { setup_revision: 4 }),
        row("ready", days[3].start + 3_600_000),
        row("ready", days[2].start + 3_600_000, { setup_revision: 5 }),
      ],
    };
    const cut = earlierTraces(week, room, day, { on: 10, off: 22 }, config);
    const zone1 = cut.traces.get(1)!;
    // The day before yesterday the room was switched off for an hour: nothing to compare.
    expect(zone1.map((trace) => trace !== null)).toEqual([
      true,
      false,
      true,
      true,
      true,
      true,
      true,
    ]);
    expect(cut.setup).toEqual([5, 5, 4, 4, 4, 4, 4]);
    expect(revisionAt(week[config], days[3].start + 3_600_000 + 1)).toBe(4);
    expect(revisionAt(week[config], days[6].start - 1)).toBeNull();
    expect(cut.traces.get(2)!.every((trace) => trace === null)).toBe(true); // nothing recorded
  });
});

describe("how today is tracking", () => {
  const START = at("22:00:00");
  const hours = (list: [number, number][]) =>
    list.map(([hour, value]) => ({ hour, value, time: START + hour * 3_600_000 }));
  const day: GrowDay = {
    start: START,
    lightsOff: START + 12 * 3_600_000,
    end: START + 24 * 3_600_000,
  };
  const shot = (from: number, seconds: number): Shot => ({
    start: START + from * 3_600_000,
    end: START + from * 3_600_000 + seconds * 1000,
    open: false,
    phase: null,
    reason: null,
  });
  // Yesterday: a P1 ramp from 25 % that reached the 28.4 % target at 1.5 h, then P2.
  const yesterday: DayTrace = {
    day,
    points: hours([
      [0, 26],
      [0.5, 25],
      [1, 27],
      [1.5, 28.6],
      [3, 27.6],
      [3.3, 27],
      [3.5, 26.6],
    ]),
    shots: [shot(0.6, 120), shot(1, 150), shot(3.4, 90)],
  };
  it("VWC now, the P1 target and water so far against yesterday at the same hour", () => {
    const now = compareDays([yesterday], 3.25, 28.1, 28.4)!;
    expect(now.vwc).toBeCloseTo(28.1 - 27.1, 6); // yesterday read 27.1 % a quarter past three hours in
    expect(now.reached).toBe(1.5);
    expect(now.reachedBy).toBe(1);
    expect(now.seconds).toBe(270); // the two shots before 3.25 h, not the one at 3.4 h
    expect(openSeconds(yesterday.shots, START, 3.41)).toBeCloseTo(270 + 36, 6); // 36 s of the third
    // Readings too far apart to read between, and none near: nothing.
    expect(atHour(yesterday.points, 2.25)).toBeNull();
    // Today reached 28.4 % ten minutes later than yesterday.
    expect(
      reachedHour(
        hours([
          [0, 25],
          [1.5, 28],
          [1.6667, 28.5],
        ]),
        28.4,
      ),
    ).toBeCloseTo(1.6667, 4);
  });
  it("a P1 target yesterday never reached, and a day that started above it", () => {
    const short = {
      ...yesterday,
      points: hours([
        [0, 26],
        [2, 28],
        [4, 27],
      ]),
    };
    expect(compareDays([short], 3, 28, 28.4)).toMatchObject({ reached: null, reachedBy: 0 });
    expect(
      reachedHour(
        hours([
          [0, 29],
          [1, 30],
        ]),
        28.4,
      ),
    ).toBe(0);
    expect(reachedHour([], 28.4)).toBeNull();
  });
  it("a typical day reaches the P1 target only when its median day did", () => {
    const at = (hour: number | null): DayTrace => ({
      ...yesterday,
      points: hours(
        hour === null
          ? [
              [0, 26],
              [3, 27],
            ]
          : [
              [0, 26],
              [hour, 29],
              [3, 27],
            ],
      ),
    });
    // One of three days reached 28.4 %: the typical day did not.
    expect(compareDays([at(1), at(null), at(null)], 3, 28, 28.4)).toMatchObject({
      reached: null,
      reachedBy: 1,
    });
    // Two of three did: the median day's time, the later of the two.
    expect(compareDays([at(1), at(2), at(null)], 3, 28, 28.4)).toMatchObject({
      reached: 2,
      reachedBy: 2,
    });
    expect(compareDays([at(1), at(2), at(1.5)], 3, 28, 28.4)!.reached).toBe(1.5);
  });
  it("no recorded day: nothing to compare, and no line", () => {
    expect(compareDays([], 3, 28, 28.4)).toBeNull();
    const empty = dayTrace(
      { vwc: [row("27", START)] },
      { vwc: "vwc", valve: null, active: null },
      1,
      day,
    );
    expect(empty).toBeNull();
    const off = dayTrace(
      { vwc: [row("27", START), row("26", START + 3_600_000)], active: [row("off", START - 1)] },
      { vwc: "vwc", valve: null, active: "active" },
      1,
      day,
    );
    expect(off).toBeNull();
  });
  it("the typical day: the median and middle half of the days recorded, where three or more were", () => {
    const days = [0, 1, 2, 3, 4].map((offset) =>
      hours(Array.from({ length: 13 }, (_, index) => [index / 2, 25 + offset] as [number, number])),
    );
    days[3] = days[3].filter((point) => point.hour <= 3); // one day stopped recording at 3 h
    const typical = typicalDay(days);
    expect(typical[0]).toEqual({ hour: 0, low: 26, median: 27, high: 28 });
    expect(typical.find((point) => point.hour > 4)).toMatchObject({
      low: 25.75,
      median: 26.5,
      high: 27.5,
    });
    expect(typical.at(-1)!.hour).toBeCloseTo(6, 9);
    expect(typicalDay(days.slice(0, 2))).toEqual([]); // two days are not a typical one
  });
  it("targets: the P0 dryback level under the peak, a setpoint changed mid-day, a plan's snapshot", () => {
    const threshold = "number.crop_steering_zone_2_p2_vwc_threshold";
    const rows = {
      [threshold]: [row("26.6", START - 3_600_000), row("27.2", START + 4 * 3_600_000)],
    };
    const parameters = {
      dryback_target: 10,
      p1_target_vwc: 28.4,
      p2_vwc_threshold: 27.2,
      p3_emergency_vwc_threshold: 20,
    };
    const bands: PhaseBand[] = [
      { phase: "P0", start: START, end: START + 3_600_000 },
      { phase: "P1", start: START + 3_600_000, end: START + 2 * 3_600_000 },
      { phase: "P2", start: START + 2 * 3_600_000, end: START + 12 * 3_600_000 },
      { phase: "P3", start: START + 12 * 3_600_000, end: day.end },
    ];
    const points = [
      row("25", START),
      row("26", START + 600_000),
      row("25.2", START + 1_800_000),
    ].map((item) => ({ time: item.time, value: Number(item.state) }));
    const manual = setpointSteps(
      rows,
      parameters,
      (key) => (key === "p2_vwc_threshold" ? threshold : null),
      false,
    );
    expect(
      phaseTargets(bands, manual, points).map(({ phase, value, start }) => [
        phase,
        value,
        (start - START) / 3_600_000,
      ]),
    ).toEqual([
      ["P0", 26 * 0.9, 0], // 10 % below the highest reading since P0 began
      ["P1", 28.4, 1],
      ["P2", 26.6, 2],
      ["P2", 27.2, 4], // changed at 4 h
      ["P3", 20, 12],
    ]);
    // A plan armed: its snapshot's values, whatever the numbers recorded.
    const planned = setpointSteps(
      rows,
      { ...parameters, p2_vwc_threshold: 25 },
      () => threshold,
      true,
    );
    expect(phaseTargets(bands, planned, points).filter((step) => step.phase === "P2")).toEqual([
      { phase: "P2", value: 25, start: bands[2].start, end: bands[2].end },
    ]);
    // In P0 now: the projected rest of P0 keeps the level from the peak since P0 began.
    const now = START + 1_800_000;
    const ongoing: PhaseBand[] = [
      { phase: "P0", start: START, end: now },
      { phase: "P0", start: now, end: START + 3_600_000 },
    ];
    expect(phaseTargets(ongoing, manual, points).map((step) => step.value)).toEqual([
      26 * 0.9,
      26 * 0.9,
    ]);
    // Without a dryback target (no steering mode) P0 has no target.
    expect(
      phaseTargets(
        bands.slice(0, 1),
        setpointSteps({}, {}, () => null, false),
        points,
      ),
    ).toEqual([]);
  });
  it("how far P0 dried, as the engine measures it", () => {
    const points = [
      { time: START, value: 30 },
      { time: START + 600_000, value: 30.5 },
      { time: START + 1_800_000, value: 28.1 },
      { time: START + 5_000_000, value: 20 },
    ];
    expect(morningDryback(points, { start: START, end: START + 3_600_000 })).toBeCloseTo(
      ((30.5 - 28.1) / 30.5) * 100,
      6,
    );
    expect(morningDryback(points, { start: 0, end: 1 })).toBeNull();
  });
  it("a controller not reporting gets no projection, only when it last reported", () => {
    const now = at("03:00:00");
    expect(unprojected(NOT_REPORTING, now - 12 * 60_000, now)).toBe(
      "no projection: last report 12 min ago",
    );
    expect(unprojected(NOT_REPORTING, null, now)).toBe(
      "no projection: no report from the controller",
    );
    expect(unprojected("the room is off", null, now)).toBe("not watering: the room is off");
    expect(unprojected(null, now, now)).toBeNull();
  });
  it("joins a week of day-sized requests into one history per entity", () => {
    const joined = joinRows([{ a: [row("2", 20)], b: [row("x", 5)] }, { a: [row("1", 10)] }]);
    expect(joined).toEqual({ a: [row("1", 10), row("2", 20)], b: [row("x", 5)] });
    expect(valueAt([row("8", 10), row("unavailable", 20), row("10", 30)], 25)).toBe(8);
    expect(valueAt([row("8", 10)], 5)).toBeNull();
  });
});

describe("the demo's earlier days", () => {
  it("run on from today's curve, with shots of their own", () => {
    const now = new Date(2026, 8, 23, 17, 0).getTime();
    const states = createDemo(now);
    const room = buildRoom(
      states,
      discoverRooms(states).find((item) => item.prefix === "")!,
    );
    const day = growDay(10, 22, now)!;
    const [yesterday] = earlierDays(day, 1, () => ({ on: 10, off: 22 }));
    const ids = earlierEntities(room, states);
    const before = demoDay(states, { ...ids, start: yesterday.start, end: yesterday.end }, now);
    const today = demoDay(states, { ...ids, start: day.start, end: now }, now);
    const vwc = "sensor.crop_steering_vwc_zone_1";
    // Yesterday ends where today begins, on the same curve.
    const last = before[vwc].at(-1)!,
      first = today[vwc][0];
    expect(Math.abs(Number(last.state) - Number(first.state))).toBeLessThan(0.5);
    // A room switched off now was on yesterday: that day still compares.
    const active = "switch.crop_steering_room_active";
    const off = demoDay(
      { ...states, [active]: { ...states[active], state: "off" } },
      { ...ids, start: yesterday.start, end: yesterday.end },
      now,
    );
    expect(off[active]).toEqual([row("on", yesterday.start)]);
    expect(dayTrace(off, { vwc, valve: null, active }, 1, yesterday)).not.toBeNull();
    const trace = dayTrace(
      before,
      { vwc, valve: "switch.demo_valve_1", active: null },
      1,
      yesterday,
    )!;
    expect(trace.shots.length).toBeGreaterThan(6);
    const seconds = (shots: Shot[]) => shots.map((item) => (item.end - item.start) / 1000);
    expect(seconds(trace.shots)).not.toEqual(
      seconds(valveShots(today["switch.demo_valve_1"], [], 1, day.start, now)).slice(
        0,
        trace.shots.length,
      ),
    );
  });
});

describe("durations", () => {
  it("reads like a person would say it", () => {
    expect(duration(40_000)).toBe("40 s");
    expect(duration(145_000)).toBe("2 min 25 s");
    expect(duration(120_000)).toBe("2 min");
    expect(duration(600_000)).toBe("10 min");
    expect(duration(72 * 60_000)).toBe("1 h 12 min");
    expect(duration(3_600_000)).toBe("1 h");
  });
});
