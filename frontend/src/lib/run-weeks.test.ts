import { describe, expect, it } from "vitest";
import { addDays } from "./comparison";
import type { DailyReading } from "./comparison-types";
import { biggestDifferences, chartRows, chartSummary, runWeeks, type RunWeek } from "./run-weeks";

const day = (date: string, min: number, max: number): DailyReading => ({
  date,
  records: 96,
  min,
  max,
});
const days = (start: string, count: number, min: number, max: number) =>
  Array.from({ length: count }, (_, index) => day(addDays(start, index), min + index * 0.1, max));

describe("a run by grow week", () => {
  const start = "2026-08-24";
  const weeks = runWeeks({
    start,
    last: "2026-09-28",
    today: "2026-09-28",
    vwc: [...days(start, 14, 55, 66), day("2026-09-28", 50, 60)],
    ec: days(start, 7, 3.9, 4.6),
    water: new Map([
      ["2026-08-24", 72],
      ["2026-08-25", 90],
      ["2026-09-28", 20],
    ]),
    plants: 36,
  });
  it("counts weeks of seven days from the start, the last one still running", () => {
    expect(weeks.map((week) => [week.week, week.first, week.last, week.current])).toEqual([
      [1, "2026-08-24", "2026-08-30", false],
      [2, "2026-08-31", "2026-09-06", false],
      [3, "2026-09-07", "2026-09-13", false],
      [4, "2026-09-14", "2026-09-20", false],
      [5, "2026-09-21", "2026-09-27", false],
      [6, "2026-09-28", "2026-09-28", true],
    ]);
    expect(weeks[5].days).toBe(1);
  });
  it("takes a week's typical day: the median daily low and the median daily high", () => {
    expect(weeks[0].moisture![0]).toBeCloseTo(55.3);
    expect(weeks[0].moisture![1]).toBe(66);
    expect(weeks[0].poreEc![0]).toBeCloseTo(4.2);
    expect(weeks[1].moisture![0]).toBeCloseTo(56);
    expect(weeks[1].poreEc).toBeNull();
    expect(weeks[2].moisture).toBeNull();
    expect([weeks[0].recorded, weeks[2].recorded]).toEqual([7, 0]);
  });
  it("averages water per plant over recorded grow-days, today's unfinished one left out", () => {
    expect(weeks[0].water).toBeCloseTo((72 + 90) / 2 / 36);
    expect(weeks[1].water).toBeNull();
    expect(weeks[5].water).toBeNull();
    expect(
      runWeeks({
        start,
        last: "2026-08-30",
        today: "2026-09-28",
        vwc: [],
        ec: [],
        water: new Map([["2026-08-24", 72]]),
        plants: null,
      })[0].water,
    ).toBeNull();
  });
  it("stops at an ended run's last day, and has none before its start", () => {
    const ended = runWeeks({
      start,
      last: "2026-09-08",
      today: "2026-09-28",
      vwc: [],
      ec: [],
      water: new Map(),
      plants: 36,
    });
    expect(ended.map((week) => week.last)).toEqual(["2026-08-30", "2026-09-06", "2026-09-08"]);
    expect(ended.some((week) => week.current)).toBe(false);
    expect(
      runWeeks({
        start,
        last: "2026-08-20",
        today: "2026-08-20",
        vwc: [],
        ec: [],
        water: new Map(),
        plants: 36,
      }),
    ).toEqual([]);
  });
});

describe("where two runs differ most", () => {
  const week = (number: number, figures: Partial<RunWeek>): RunWeek => ({
    week: number,
    first: "",
    last: "",
    current: false,
    moisture: null,
    poreEc: null,
    water: null,
    shots: null,
    dryback: null,
    recorded: 7,
    days: 7,
    ...figures,
  });
  const now = [
    week(1, { moisture: [55, 65], poreEc: [4, 4.6], water: 2 }),
    week(2, { moisture: [52, 60], poreEc: [4.8, 5.6], water: 2.6 }),
    week(3, { moisture: [54, 64] }),
  ];
  const then = [
    week(1, { moisture: [56, 66], poreEc: [4.1, 4.5], water: 1.9 }),
    week(2, { moisture: [55, 65], poreEc: [3.9, 4.5], water: 2 }),
  ];
  it("lists the biggest first, and nothing a grower would not notice", () => {
    const found = biggestDifferences(now, then);
    expect(found.map((item) => [item.week, item.metric])).toEqual([
      [2, "poreEc"],
      [2, "water"],
      [2, "moisture"],
    ]);
    expect(found[0].text).toBe("Week 2: pore EC 4.8–5.6 against 3.9–4.5, 1 higher");
    expect(found[1].text).toBe("Week 2: 2.6 L per plant a day against 2, 30 % more");
    expect(found[2].text).toBe("Week 2: moisture 52–60 % against 55–65 %, 4 points drier");
    // Week 1 differs by a point of moisture and 5 % of water: not worth saying.
    expect(found.some((item) => item.week === 1)).toBe(false);
  });
  it("compares only weeks both runs reached, and keeps to the limit", () => {
    expect(biggestDifferences(now, then, 1)).toHaveLength(1);
    expect(biggestDifferences(now, [])).toEqual([]);
    expect(biggestDifferences(now.slice(2), then)).toEqual([]);
  });
});

describe("shots and dryback by grow week", () => {
  const start = "2026-08-24";
  const weeks = runWeeks({
    start,
    last: "2026-09-08",
    today: "2026-09-08",
    vwc: days(start, 7, 50, 62.5),
    ec: [],
    water: new Map(),
    shots: new Map([
      ["2026-08-24", 8],
      ["2026-08-25", 11],
      ["2026-09-08", 3],
    ]),
    plants: 36,
  });
  it("averages shots over recorded grow-days, today's unfinished one left out", () => {
    expect(weeks[0].shots).toBeCloseTo(9.5);
    expect(weeks[1].shots).toBeNull();
    expect(weeks[2].shots).toBeNull();
  });
  it("takes dryback as the typical day's drop from peak to trough, a share of the peak", () => {
    // Median low 50.3, median high 62.5: (62.5 - 50.3) / 62.5.
    expect(weeks[0].dryback).toBeCloseTo(((62.5 - 50.3) / 62.5) * 100);
    expect(weeks[1].dryback).toBeNull();
  });
  it("has no shots without a shot counter, never zero", () => {
    expect(
      runWeeks({
        start,
        last: start,
        today: "2026-09-08",
        vwc: [],
        ec: [],
        water: new Map(),
        plants: 1,
      })[0].shots,
    ).toBeNull();
  });
});

describe("the Compare runs charts", () => {
  const week = (number: number, figures: Partial<RunWeek>): RunWeek => ({
    week: number,
    first: "",
    last: "",
    current: false,
    moisture: null,
    poreEc: null,
    water: null,
    shots: null,
    dryback: null,
    recorded: 7,
    days: 7,
    ...figures,
  });
  const mine = [
    week(1, { moisture: [50, 62], poreEc: [3.9, 4.6], water: 0.5, shots: 9, dryback: 19.4 }),
    week(2, { moisture: [48, 63], dryback: 23.8 }),
  ];
  const theirs = [
    week(1, { moisture: [52, 61], water: 0.45, shots: 8, dryback: 14.8 }),
    week(2, {}),
    week(3, { moisture: [47, 60], dryback: 21.7 }),
  ];
  it("lines up each run's weeks, every week either run reached, gaps as null", () => {
    const rows = chartRows([mine, theirs]);
    expect(rows.map((row) => row.label)).toEqual(["W1", "W2", "W3"]);
    expect(rows[0]).toMatchObject({
      r0_peak: 62,
      r0_trough: 50,
      r0_ecHigh: 4.6,
      r0_ecLow: 3.9,
      r0_water: 0.5,
      r0_shots: 9,
      r0_dryback: 19.4,
      r1_peak: 61,
      r1_ecHigh: null,
      r1_shots: 8,
    });
    expect(rows[1].r1_peak).toBeNull();
    expect(rows[2]).toMatchObject({ r0_peak: null, r0_dryback: null, r1_dryback: 21.7 });
    expect(chartRows([])).toEqual([]);
  });
  it("says in words what each chart shows, and when a run has no record", () => {
    const runs = [
      { name: "This run", weeks: mine },
      { name: "Last run", weeks: theirs },
    ];
    expect(chartSummary("Dryback", runs, "dryback", " %", 0)).toBe(
      "Dryback by grow week. This run: 2 weeks recorded, 19 to 24 %, 24 % in week 2. Last run: 2 weeks recorded, 15 to 22 %, 22 % in week 3.",
    );
    expect(chartSummary("Pore EC", runs, "ecHigh", "", 1)).toBe(
      "Pore EC by grow week. This run: 1 week recorded, 4.6 to 4.6, 4.6 in week 1. Last run: no record.",
    );
  });
});
