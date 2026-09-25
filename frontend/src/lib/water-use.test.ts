import { describe, expect, it } from "vitest";
import { addDays } from "./comparison";
import { createDemo, demoWaterRecord } from "./demo";
import { dateForDay, localDate } from "./grow-plan";
import type { StrategyDocument } from "./operator-types";
import {
  growDayOf,
  historySamples,
  growDayTotals,
  growWeeks,
  inferStart,
  mergeDays,
  planDays,
  resolveStart,
  statisticSamples,
  sumDays,
  zoneWaterUse,
  type CounterSample,
  type GrowStart,
} from "./water-use";

const zone = "Pacific/Auckland";
const HOUR = 3_600_000;
/** NZ local wall time, written in UTC with the offset of the day: NZST (+12) until daylight saving
 * starts at 02:00 on 27 September 2026, NZDT (+13) from then. */
const nz = (date: string, time: string) => {
  const offset = date >= "2026-09-27" && !(date === "2026-09-27" && time < "02:00") ? 13 : 12;
  return Date.parse(`${date}T${time}:00Z`) - offset * HOUR;
};
const read = (date: string, time: string, value: number): CounterSample => ({
  time: nz(date, time),
  value,
});
const days = (entries: Record<string, number>) => new Map(Object.entries(entries));

describe("grow-days", () => {
  it("start at lights-on on the local wall clock, fractional hours included", () => {
    expect(growDayOf(nz("2026-09-25", "09:59"), 10, zone)).toBe("2026-09-24");
    expect(growDayOf(nz("2026-09-25", "10:00"), 10, zone)).toBe("2026-09-25");
    expect(growDayOf(nz("2026-09-25", "23:30"), 10, zone)).toBe("2026-09-25");
    // Lights on at 10:10 (10.1667 h), as the controller compares hour + minute / 60.
    expect(growDayOf(nz("2026-09-25", "10:10"), 10.1667, zone)).toBe("2026-09-24");
    expect(growDayOf(nz("2026-09-25", "10:11"), 10.1667, zone)).toBe("2026-09-25");
  });

  it("keep lights-on at 10:00 local across the start of daylight saving", () => {
    // 27 September 2026: 02:00 NZST becomes 03:00 NZDT. Lights-on 10:00 NZDT is 21:00 UTC, an
    // hour earlier in UTC than the day before, so the grow-day of 26 September lasts 23 hours.
    expect(growDayOf(Date.parse("2026-09-26T20:59:00Z"), 10, zone)).toBe("2026-09-26");
    expect(growDayOf(Date.parse("2026-09-26T21:00:00Z"), 10, zone)).toBe("2026-09-27");
    expect(growDayOf(Date.parse("2026-09-25T21:59:00Z"), 10, zone)).toBe("2026-09-25");
    expect(growDayOf(Date.parse("2026-09-25T22:00:00Z"), 10, zone)).toBe("2026-09-26");
  });
});

describe("grow-day totals from the water-today counter", () => {
  it("take each grow-day's peak after its reset at lights-on", () => {
    const totals = growDayTotals(
      [
        read("2026-09-22", "10:00", 0),
        read("2026-09-22", "13:00", 40.5),
        read("2026-09-22", "20:00", 111.49),
        read("2026-09-23", "10:02", 0),
        read("2026-09-23", "16:00", 60),
        read("2026-09-23", "20:24", 89),
      ],
      10,
      zone,
    );
    expect([...totals]).toEqual([
      ["2026-09-22", 111.49],
      ["2026-09-23", 89],
    ]);
  });

  it("add a shot delivered after lights-on but before the reset to the new grow-day", () => {
    // Recorded on the live box, zone 2, 23 September 2026: a 5.65 L shot at 10:01, the counter
    // reset at 10:02. The controller's own seven-day window counts it on the 23rd as well.
    const totals = growDayTotals(
      [
        read("2026-09-23", "09:09", 111.49),
        read("2026-09-23", "10:01", 117.14),
        read("2026-09-23", "10:02", 0),
        read("2026-09-23", "10:14", 7.05),
        read("2026-09-23", "20:24", 89),
      ],
      10,
      zone,
    );
    expect(totals.get("2026-09-22")).toBe(111.49);
    expect(totals.get("2026-09-23")).toBe(94.65);
  });

  it("count a late reset from the reset, not twice (controller down at lights-on)", () => {
    const totals = growDayTotals(
      [
        read("2026-09-22", "18:00", 50),
        read("2026-09-23", "10:30", 50),
        read("2026-09-23", "12:30", 50),
        read("2026-09-23", "13:05", 0),
        read("2026-09-23", "18:00", 30),
      ],
      10,
      zone,
    );
    expect(totals.get("2026-09-22")).toBe(50);
    expect(totals.get("2026-09-23")).toBe(30);
  });

  it("start a new count at lights-on when hourly readings hide the reset", () => {
    // The live box, zone 1, 12 September: 14.42 L the day before, and more than that by 11:00.
    const totals = growDayTotals(
      [
        read("2026-09-11", "20:00", 14.42),
        read("2026-09-12", "09:59", 14.42),
        read("2026-09-12", "10:59", 20),
        read("2026-09-12", "20:59", 86.5),
      ],
      10,
      zone,
    );
    expect(totals.get("2026-09-11")).toBe(14.42);
    expect(totals.get("2026-09-12")).toBe(86.5);
  });

  it("count a controller restart mid-day that re-publishes the same value once", () => {
    const restart = [
      read("2026-09-24", "10:00", 0),
      read("2026-09-24", "10:09", 7.05),
      read("2026-09-24", "13:00", 58.24),
      // Restart: unavailable (not a number, never a sample), then the same value again.
      read("2026-09-24", "13:02", 58.24),
      read("2026-09-24", "14:41", 83.72),
    ];
    expect(growDayTotals(restart, 10, zone).get("2026-09-24")).toBe(83.72);
    // The same restart publishing a zero first: Home Assistant's own sum counts that as a meter
    // reset and adds the day twice (seen on the live box on 7 September); only peaks count here.
    const dip = [...restart.slice(0, 3), read("2026-09-24", "13:01", 0), ...restart.slice(3)];
    expect(growDayTotals(dip, 10, zone).get("2026-09-24")).toBe(83.72);
  });

  it("report nothing for a counter frozen at the day before's value", () => {
    const totals = growDayTotals(
      [
        read("2026-09-07", "20:00", 119.07),
        read("2026-09-08", "10:59", 119.07),
        read("2026-09-08", "20:59", 119.07),
      ],
      10,
      zone,
    );
    expect(totals.get("2026-09-08")).toBe(0);
  });

  it("leave a grow-day without readings missing and carry nothing across it", () => {
    const totals = growDayTotals(
      [
        read("2026-09-14", "20:00", 60),
        // No readings on the 15th (Home Assistant down all day).
        read("2026-09-16", "10:30", 60.5),
        read("2026-09-16", "20:00", 70),
      ],
      10,
      zone,
    );
    expect([...totals.keys()]).toEqual(["2026-09-14", "2026-09-16"]);
    expect(totals.get("2026-09-16")).toBe(70);
    expect(sumDays(totals, "2026-09-14", "2026-09-16")).toEqual({
      first: "2026-09-14",
      last: "2026-09-16",
      litres: 130,
      days: 3,
      missing: 1,
    });
  });

  it("split hourly statistics correctly through a daylight-saving week", () => {
    // Hourly statistics, 21 September to 1 October: a counter that resets at 10:00 local each
    // day and reaches that grow-day's total by 22:00.
    const planned: Record<string, number> = {};
    for (let day = 21; day <= 30; day++) planned[`2026-09-${day}`] = 80 + day;
    const lightsOn = Object.keys(planned).map((date) => ({ date, at: nz(date, "10:00") }));
    const samples: CounterSample[] = [];
    for (let end = nz("2026-09-21", "11:00"); end <= nz("2026-10-01", "10:00"); end += HOUR) {
      const cycle = lightsOn.filter((day) => day.at < end).at(-1)!;
      const hours = (end - cycle.at) / HOUR;
      samples.push({
        time: end - 1,
        value: Math.round(planned[cycle.date] * Math.min(1, hours / 12) * 100) / 100,
      });
    }
    const rows = {
      "sensor.water": samples.map((s) => ({
        start: s.time + 1 - HOUR,
        end: s.time + 1,
        state: s.value,
      })),
    };
    const totals = growDayTotals(statisticSamples(rows)["sensor.water"], 10, zone);
    expect(Object.fromEntries(totals)).toEqual(planned);
    // The grow-day of 26 September has 23 hourly readings: the clocks went forward.
    expect(samples.filter((s) => growDayOf(s.time, 10, zone) === "2026-09-26")).toHaveLength(23);
    const weeks = growWeeks(totals, "2026-09-21", "2026-09-30");
    expect(
      weeks.map(({ week, first, last, litres, missing }) => ({
        week,
        first,
        last,
        litres,
        missing,
      })),
    ).toEqual([
      {
        week: 1,
        first: "2026-09-21",
        last: "2026-09-27",
        litres: 7 * 80 + 21 + 22 + 23 + 24 + 25 + 26 + 27,
        missing: 0,
      },
      {
        week: 2,
        first: "2026-09-28",
        last: "2026-09-30",
        litres: 3 * 80 + 28 + 29 + 30,
        missing: 0,
      },
    ]);
  });
});

describe("statistics rows", () => {
  it("read each hour's closing value just before the hour ends, epoch or ISO times", () => {
    const end = Date.parse("2026-09-24T22:00:00Z");
    expect(
      statisticSamples({
        a: [
          { start: end - HOUR, end, state: 59.41 },
          { start: new Date(end).toISOString(), end: new Date(end + HOUR).toISOString(), state: 0 },
          { start: end + HOUR, end: end + 2 * HOUR, state: null },
        ],
        b: "not rows",
      }),
    ).toEqual({
      a: [
        { time: end - 1, value: 59.41 },
        { time: end + HOUR - 1, value: 0 },
      ],
    });
    expect(() => statisticSamples(null)).toThrow();
  });
});

describe("merging the controller sensor with the integration's mirror", () => {
  it("prefers the first series per grow-day and fills its gaps from the second", () => {
    expect([
      ...mergeDays(
        days({ "2026-09-03": 10, "2026-09-05": 30 }),
        days({ "2026-09-04": 21, "2026-09-05": 99 }),
      ),
    ]).toEqual([
      ["2026-09-03", 10],
      ["2026-09-04", 21],
      ["2026-09-05", 30],
    ]);
  });
});

describe("grow start", () => {
  // The live box, F2 zone 1, 21 August to 25 September 2026: a commissioning run, nine dry
  // grow-days, then the grow from 1 September with one dry day on the 2nd.
  const live = days({
    "2026-08-21": 104.9,
    "2026-08-22": 113.4,
    ...Object.fromEntries(Array.from({ length: 9 }, (_, i) => [`2026-08-${23 + i}`, 0])),
    "2026-09-01": 96.4,
    "2026-09-02": 0,
    ...Object.fromEntries(
      Array.from({ length: 23 }, (_, i) => [`2026-09-${String(3 + i).padStart(2, "0")}`, 60 + i]),
    ),
  });

  it("is inferred as the first watered grow-day after the latest dry run", () => {
    expect(inferStart([live], "2026-09-25")).toEqual({ date: "2026-09-01", afterDry: 9 });
    // Four dry days are a pause inside a grow, not a gap between grows.
    expect(inferStart([days({ "2026-09-01": 5, "2026-09-06": 5 })], "2026-09-07")).toEqual({
      date: "2026-09-01",
      afterDry: null,
    });
    // Any zone watered counts: the second zone alone watered on the 3rd.
    expect(
      inferStart(
        [days({ "2026-09-01": 0, "2026-09-10": 4 }), days({ "2026-09-03": 2 })],
        "2026-09-10",
      ),
    ).toEqual({
      date: "2026-09-10",
      afterDry: 6,
    });
  });

  it("is on or before the first record when the record begins inside the grow", () => {
    expect(inferStart([days({ "2026-09-10": 4, "2026-09-11": 5 })], "2026-09-11")).toEqual({
      date: "2026-09-10",
      afterDry: null,
    });
  });

  it("is absent with no water recorded, or none for longer than the gap", () => {
    expect(inferStart([days({ "2026-09-10": 0 })], "2026-09-11")).toBeNull();
    expect(inferStart([days({ "2026-09-01": 40, "2026-09-02": 0 })], "2026-09-08")).toBeNull();
    expect(inferStart([], "2026-09-08")).toBeNull();
  });

  const document = (status: StrategyDocument["status"], revision: number, start = "2026-09-01") =>
    ({
      status,
      revision,
      plan: {
        schema_version: 1,
        profiles: [],
        zones: [
          {
            zone_id: 1,
            start_date: start,
            schedule: [
              { start_day: 1, end_day: 14, profile_id: "a", bias: 20 },
              { start_day: 15, end_day: 84, profile_id: "a", bias: 60 },
            ],
          },
        ],
      },
    }) as Pick<StrategyDocument, "status" | "revision" | "plan">;
  const inferred = { date: "2026-09-03", afterDry: 7 };

  it("comes from an armed or running plan, or a saved draft", () => {
    for (const status of ["armed", "active", "disarming", "error"] as const)
      expect(resolveStart(document(status, 3), 1, "2026-09-25", inferred)).toEqual({
        date: "2026-09-01",
        source: "plan",
        planDays: 84,
        afterDry: null,
      });
    expect(resolveStart(document("draft", 2), 1, "2026-09-25", inferred)?.source).toBe("draft");
  });

  it("is inferred for a draft nobody saved, a future plan, or a zone without one", () => {
    // Revision 0: the integration's placeholder, dated the day it was created (the live box).
    expect(resolveStart(document("draft", 0, "2026-09-24"), 1, "2026-09-25", inferred)).toEqual({
      date: "2026-09-03",
      source: "inferred",
      planDays: null,
      afterDry: 7,
    });
    expect(
      resolveStart(document("armed", 1, "2026-10-01"), 1, "2026-09-25", inferred)?.source,
    ).toBe("inferred");
    expect(resolveStart(document("armed", 1), 2, "2026-09-25", inferred)?.source).toBe("inferred");
    expect(
      resolveStart(null, 1, "2026-09-25", { date: "2026-09-10", afterDry: null })?.source,
    ).toBe("records");
    expect(resolveStart(null, 1, "2026-09-25", null)).toBeNull();
  });

  it("gives the plan length as its last scheduled day", () => {
    expect(planDays(document("armed", 1).plan.zones[0])).toBe(84);
    expect(planDays(undefined)).toBeNull();
  });
});

describe("zone water use", () => {
  // Grow started 1 September; today is the 25th (grow-day 25, week 4 = 22–28 September).
  const record = new Map(
    Array.from({ length: 25 }, (_, i) => [`2026-09-${String(i + 1).padStart(2, "0")}`, 10 + i]),
  );
  const start = (source: GrowStart["source"], plan: number | null): GrowStart => ({
    date: "2026-09-01",
    source,
    planDays: plan,
    afterDry: null,
  });

  it("sums today, the grow week, the grow so far and weekly buckets", () => {
    const use = zoneWaterUse(record, "2026-09-25", start("plan", 84));
    expect(use.today).toEqual({ day: "2026-09-25", litres: 34 });
    expect(use.growDay).toBe(25);
    expect(use.week).toMatchObject({
      first: "2026-09-22",
      last: "2026-09-25",
      litres: 31 + 32 + 33 + 34,
      growWeek: 4,
    });
    // 10 + 11 + … + 34
    expect(use.sinceStart).toMatchObject({
      first: "2026-09-01",
      litres: 550,
      missing: 0,
      recordsBegin: false,
    });
    expect(use.weeks.map((week) => [week.week, week.litres, week.days])).toEqual([
      [1, 10 + 11 + 12 + 13 + 14 + 15 + 16, 7],
      [2, 17 + 18 + 19 + 20 + 21 + 22 + 23, 7],
      [3, 24 + 25 + 26 + 27 + 28 + 29 + 30, 7],
      [4, 31 + 32 + 33 + 34, 4],
    ]);
  });

  it("estimates the grow: used so far + the last 7 grow-days' average × days left", () => {
    const use = zoneWaterUse(record, "2026-09-25", start("plan", 84));
    // Full grow-days 18–24 September: 27…33 L, 30 L a day; 84 − 25 = 59 grow-days left.
    expect(use.average).toMatchObject({
      first: "2026-09-18",
      last: "2026-09-24",
      perDay: 30,
      days: 7,
    });
    expect(use.estimate).toEqual({ total: 550 + 30 * 59, daysLeft: 59, planDays: 84 });
    expect(use.perWeek).toBeNull();
  });

  it("gives litres per week instead when the plan length is unknown", () => {
    const use = zoneWaterUse(record, "2026-09-25", start("inferred", null));
    expect(use.estimate).toBeNull();
    expect(use.perWeek).toBe(210);
  });

  it("averages only recorded grow-days and none before the grow started", () => {
    const gappy = new Map(record);
    gappy.delete("2026-09-20");
    const use = zoneWaterUse(gappy, "2026-09-25", start("plan", 84));
    expect(use.average).toMatchObject({
      days: 7,
      missing: 1,
      perDay: (27 + 28 + 30 + 31 + 32 + 33) / 6,
    });
    expect(use.sinceStart).toMatchObject({ litres: 550 - 29, missing: 1 });
    const early = zoneWaterUse(record, "2026-09-04", start("plan", 84));
    expect(early.average).toMatchObject({ first: "2026-09-01", last: "2026-09-03", perDay: 11 });
    expect(zoneWaterUse(record, "2026-09-01", start("plan", 84)).estimate).toBeNull();
  });

  it("stops the estimate at the plan's end", () => {
    expect(zoneWaterUse(record, "2026-09-25", start("plan", 20)).estimate).toEqual({
      total: 550,
      daysLeft: 0,
      planDays: 20,
    });
  });

  it("counts from the first record when the record begins after the grow start", () => {
    const late = new Map([...record].filter(([day]) => day >= "2026-09-11"));
    const use = zoneWaterUse(late, "2026-09-25", start("plan", 84));
    expect(use.sinceStart).toMatchObject({ first: "2026-09-11", recordsBegin: true, missing: 0 });
    expect(use.weeks[0]).toMatchObject({ week: 1, litres: 0, missing: 7 });
  });

  it("falls back to the last 7 grow-days without a grow start", () => {
    const use = zoneWaterUse(record, "2026-09-25", null);
    expect(use.week).toMatchObject({ first: "2026-09-19", last: "2026-09-25", growWeek: null });
    expect(use.sinceStart).toBeNull();
    expect(use.weeks).toEqual([]);
    expect(use.perWeek).toBe(210);
  });
});

describe("recorded states as readings", () => {
  it("keeps numbers only: an unavailable spell leaves no reading", () => {
    expect(
      historySamples({
        a: [
          { state: "12.5", time: 1 },
          { state: "unavailable", time: 2 },
          { state: "", time: 3 },
          { state: "12.5", time: 4 },
        ],
      }),
    ).toEqual({
      a: [
        { time: 1, value: 12.5 },
        { time: 4, value: 12.5 },
      ],
    });
  });
});

describe("demo water record", () => {
  it("gives complete grow-days from the demo plan's start, after dry ones", () => {
    const now = Date.now();
    const id = "sensor.crop_steering_zone_1_daily_water_app";
    const record = demoWaterRecord(
      createDemo(now),
      {
        entityIds: [id, "sensor.crop_steering_zone_9_daily_water_app"],
        start: now - 30 * 86_400_000,
        end: now,
      },
      now,
    );
    expect(Object.keys(record)).toEqual([id]);
    const local = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const days = growDayTotals(record[id], 10, local);
    const start = dateForDay(localDate(new Date(now)), -13);
    expect(record[id].every((sample) => sample.time <= now)).toBe(true);
    // The live counter supplies today.
    expect(days.has(growDayOf(now, 10, local))).toBe(false);
    expect(days.get(addDays(start, -1))).toBe(0);
    for (const [day, litres] of days)
      if (day >= start) (expect(litres).toBeGreaterThan(8), expect(litres).toBeLessThanOrEqual(38));
      else expect(litres).toBe(0);
  });
});
