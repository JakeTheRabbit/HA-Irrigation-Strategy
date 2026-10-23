import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addDays,
  ageAt,
  boundedRange,
  CALLOUT_FLOOR,
  comparedRun,
  comparisonRange,
  dailyStatistics,
  downsample,
  midnight,
  runCallout,
  runResult,
  summarize,
  timeAtAge,
  wallTime,
} from "./comparison";
import { loadHistoryWindow } from "./comparison-history";
import { HaClient } from "./client";
import type { ComparedRun, HistoryRequest, RunRecord } from "./comparison-types";
import type { GrowDay, Harvest } from "./grows";
import { stageArc } from "./stage-arc";
const id = "sensor.crop_steering_vwc_zone_1";
const zone = "Pacific/Auckland";
const request = (start = "2026-08-01T00:00:00Z", end = "2026-08-15T00:00:00Z"): HistoryRequest => ({
  entityIds: [id],
  start,
  end,
  timeZone: "UTC",
});
const record = (start_date: string, time_zone = zone, end_date: string | null = null) =>
  ({ start_date, time_zone, end_date }) as RunRecord;
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});
describe("run comparison calendar and aggregation", () => {
  it("uses 23/25-hour Auckland dates and round trips grow age", () => {
    expect(midnight("2026-09-28", zone) - midnight("2026-09-27", zone)).toBe(23 * 3600000);
    expect(midnight("2026-04-06", zone) - midnight("2026-04-05", zone)).toBe(25 * 3600000);
    for (const start of ["2026-09-27", "2026-04-05"])
      expect(ageAt(timeAtAge(0.5, start, zone), start, zone)).toBeCloseTo(0.5);
  });
  it("uses 23/25-hour New York dates, the northern hemisphere's clock changes", () => {
    const ny = "America/New_York";
    expect(midnight("2026-03-09", ny) - midnight("2026-03-08", ny)).toBe(23 * 3600000);
    expect(midnight("2026-11-02", ny) - midnight("2026-11-01", ny)).toBe(25 * 3600000);
    for (const start of ["2026-03-08", "2026-11-01"])
      expect(ageAt(timeAtAge(0.5, start, ny), start, ny)).toBeCloseTo(0.5);
  });
  it("aligns previous progress by local grow age and truncates closed runs", () => {
    const current = record("2026-09-27"),
      previous = record("2026-04-05");
    const range = comparisonRange(
      current,
      previous,
      midnight(current.start_date, zone),
      timeAtAge(0.5, current.start_date, zone),
      Date.parse("2026-10-01"),
    )!;
    expect(range.end - range.start).toBe(12.5 * 3600000);
    const closed = comparisonRange(
      record("2026-09-01"),
      record("2026-04-01", zone, "2026-04-02"),
      midnight("2026-09-01", zone),
      midnight("2026-09-10", zone),
      Date.parse("2026-10-01"),
    )!;
    expect(closed.end).toBe(midnight("2026-04-03", zone));
  });
  it("caps now, rejects future and excessive calendar ranges", () => {
    const now = midnight("2026-08-10", zone) + 3600000;
    expect(boundedRange("2026-08-09", "2026-08-20", zone, now).end).toBe(now);
    expect(() => boundedRange("2026-09-01", "2026-09-02", zone, now)).toThrow(/elapsed/);
    expect(() => boundedRange("2025-01-01", "2026-01-02", zone, now)).toThrow(/366/);
    expect(addDays("2024-02-28", 1)).toBe("2024-02-29");
  });
  it("bounds chart data, preserves extrema in continuous spans and explicit gap breaks", () => {
    const points = Array.from({ length: 10000 }, (_, index) => ({
      time: index * 1000,
      value: index === 5555 ? 999 : 50,
    }));
    const reduced = downsample(points, 800);
    expect(reduced.length).toBeLessThanOrEqual(800);
    expect(reduced.some((p) => p.value === 999)).toBe(true);
    expect(
      downsample([
        { time: 0, value: 3 },
        { time: 3600000, value: 4 },
      ]).map((p) => p.value),
    ).toEqual([3, null, 4]);
    expect(
      downsample([
        { time: 0, value: NaN },
        { time: 1, value: 3 },
      ])[0].value,
    ).toBeNull();
  });
  it("summarizes actual state changes by local date without inventing means", () => {
    const time = midnight("2026-04-05", zone);
    expect(
      summarize(
        [
          { time, value: 50 },
          { time: time + 1000, value: null },
          { time: time + 2000, value: 70 },
        ],
        zone,
      ),
    ).toEqual([{ date: "2026-04-05", records: 2, min: 50, max: 70 }]);
  });
});
describe("bounded Recorder windows", () => {
  it("sends exact entity/end filters with at most two requests in flight", async () => {
    let inFlight = 0,
      max = 0;
    const paths: string[] = [];
    const result = await loadHistoryWindow(
      async (path) => {
        paths.push(path);
        inFlight++;
        max = Math.max(max, inFlight);
        await new Promise((resolve) => setTimeout(resolve, 1));
        inFlight--;
        const start = path.split("?")[0].split("period/")[1];
        return [[{ entity_id: id, last_changed: start, state: "50" }]];
      },
      request("2026-08-01T00:00:00Z", "2026-08-24T12:34:00Z"),
    );
    expect(max).toBe(2);
    expect(paths).toHaveLength(4);
    const end = new URLSearchParams(paths.at(-1)!.split("?")[1]);
    expect(end.get("end_time")).toBe("2026-08-24T12:34:00.000Z");
    expect(end.get("filter_entity_id")).toBe(id);
    expect(result.series[0].daily.reduce((sum, row) => sum + row.records, 0)).toBe(4);
  });
  it("never turns Recorder carry-in into new observations or hides expired retention", async () => {
    const result = await loadHistoryWindow(
      async () => [[{ entity_id: id, last_changed: "2026-01-01T00:00:00Z", state: "50" }]],
      request(),
    );
    expect(result.series[0].daily).toEqual([]);
    expect(result.series[0].points.every((p) => p.value === null)).toBe(true);
    expect(result.warnings.join(" ")).toMatch(/retention time is over/);
  });
  it("drops end boundary, NaN and unavailable states from numeric summaries", async () => {
    const result = await loadHistoryWindow(
      async () => [
        [
          { entity_id: id, last_changed: "2026-08-01T00:00:00Z", state: "50" },
          { last_changed: "2026-08-01T00:01:00Z", state: "NaN" },
          { last_changed: "2026-08-01T00:02:00Z", state: "unavailable" },
          { last_changed: "2026-08-02T00:00:00Z", state: "99" },
        ],
      ],
      request("2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"),
    );
    expect(result.series[0].daily[0]).toMatchObject({ records: 1, min: 50, max: 50 });
    expect(result.series[0].points.map((p) => p.value)).toEqual([50, null, null]);
  });
  it("does not fabricate gaps from downsampled spacing in dense multimonth history", async () => {
    const result = await loadHistoryWindow(
      async (path) => {
        const start = Date.parse(path.split("?")[0].split("period/")[1]);
        const end = Date.parse(new URLSearchParams(path.split("?")[1]).get("end_time")!);
        return [
          Array.from({ length: Math.ceil((end - start) / 60000) }, (_, index) => ({
            entity_id: id,
            last_changed: new Date(start + index * 60000).toISOString(),
            state: String(50 + Math.sin(index)),
          })),
        ];
      },
      request("2026-06-01T00:00:00Z", "2026-08-01T00:00:00Z"),
    );
    expect(result.series[0].points.length).toBeLessThanOrEqual(1600);
    expect(result.series[0].points.every((p) => p.value !== null)).toBe(true);
    expect(result.series[0].daily.reduce((sum, row) => sum + row.records, 0)).toBe(61 * 1440);
  });
  it("stops chunk dispatch on native transport timeouts with at most two pending callApi requests", async () => {
    vi.useFakeTimers();
    const callApi = vi.fn(() => new Promise<never>(() => {}));
    const client = new HaClient("http://example.test", "", { callApi, callService: vi.fn() }, 10);
    const pending = client.historyWindow(request("2026-07-01T00:00:00Z", "2026-08-10T00:00:00Z"));
    await vi.advanceTimersByTimeAsync(100);
    const result = await pending;
    expect(callApi).toHaveBeenCalledTimes(2);
    expect(result.warnings.join(" ")).toMatch(/timed out/);
    expect(result.warnings.join(" ")).toMatch(/not requested/);
    client.dispose();
  });
  it("rejects aborted requests and invalid ranges before reading", async () => {
    const abort = new AbortController();
    abort.abort();
    const read = vi.fn();
    await expect(loadHistoryWindow(read, { ...request(), signal: abort.signal })).rejects.toThrow(
      /cancelled/,
    );
    expect(read).not.toHaveBeenCalled();
    await expect(
      loadHistoryWindow(read, request("2025-01-01T00:00:00Z", "2026-01-03T00:00:00Z")),
    ).rejects.toThrow(/366/);
    await expect(loadHistoryWindow(read, { ...request(), entityIds: [] })).rejects.toThrow(
      /explicitly/,
    );
  });
});
describe("daily long-term statistics", () => {
  it("names each day by its middle, so a server a few hours off names the same day", () => {
    // Auckland's midnight on 24 August is noon UTC the day before.
    const rows = {
      [id]: [
        { start: Date.UTC(2026, 7, 23, 12), end: Date.UTC(2026, 7, 24, 12), min: 55, max: 66 },
        { start: "2026-08-24T12:00:00Z", min: 54, max: 65 },
        { start: Date.UTC(2026, 7, 25, 12), min: "56", max: 64 },
      ],
      "sensor.none": null,
    };
    expect(dailyStatistics(rows, zone)[id]).toEqual([
      { date: "2026-08-24", records: 1, min: 55, max: 66 },
      { date: "2026-08-25", records: 1, min: 54, max: 65 },
    ]);
    expect(dailyStatistics(rows, "UTC")[id].map((row) => row.date)).toEqual([
      "2026-08-24",
      "2026-08-25",
    ]);
    expect(dailyStatistics(rows, zone)["sensor.none"]).toEqual([]);
    expect(() => dailyStatistics(null, zone)).toThrow("invalid statistics");
  });
});

describe("a wall-clock time in a named time zone", () => {
  it("is the same instant whatever the browser's own zone", () => {
    expect(wallTime("2026-09-23", 600, "Pacific/Auckland")).toBe(
      Date.parse("2026-09-22T22:00:00Z"),
    );
    expect(wallTime("2026-09-23", 600, "America/New_York")).toBe(
      Date.parse("2026-09-23T14:00:00Z"),
    );
    expect(wallTime("2026-09-23", 630, "UTC")).toBe(Date.parse("2026-09-23T10:30:00Z"));
  });
  it("reads a time a clock change skips or repeats as the browser's Date does", () => {
    // 02:30 on 27 September 2026 does not exist in Auckland: it reads as 03:30 NZDT.
    expect(wallTime("2026-09-27", 150, "Pacific/Auckland")).toBe(
      Date.parse("2026-09-26T14:30:00Z"),
    );
    // 02:30 on 5 April 2026 happens twice: the first, NZDT, is taken.
    expect(wallTime("2026-04-05", 150, "Pacific/Auckland")).toBe(
      Date.parse("2026-04-04T13:30:00Z"),
    );
  });
});

describe("compare runs callouts", () => {
  const stages = stageArc(63); // stretch 1-21, bulk 22-49, finish 50-63
  const series = (from: number, to: number, value: number) =>
    Array.from({ length: to - from + 1 }, (_, i) => ({ day: from + i, value }));
  const run = (
    name: string,
    current: boolean,
    days: Partial<Record<keyof typeof CALLOUT_FLOOR, { day: number; value: number }[]>>,
  ): ComparedRun => ({ id: name, name, current, days });

  it("runCallout names run, delta at source precision and stage for each metric", () => {
    const vwc = runCallout(
      "vwc",
      [run("Run 15", true, { vwc: series(1, 38, 60.2) }), run("Run 13", false, { vwc: series(1, 63, 61.9) })],
      stages,
    );
    expect(vwc).toEqual({
      text: "Run 13 sat 1.7 pts wetter than this run all through stretch.",
      box: { fromDay: 1, toDay: 21 },
    });
    const dryback = runCallout(
      "dryback",
      [
        run("Run 15", true, { dryback: [...series(1, 21, 18), ...series(22, 38, 12.4)] }),
        run("Run 14", false, { dryback: [...series(1, 21, 18), ...series(22, 63, 13.6)] }),
      ],
      stages,
    );
    expect(dryback).toEqual({
      text: "This run dries back 1.2 pts less than Run 14 in bulk, days 22–38.",
      box: { fromDay: 22, toDay: 38 },
    });
    const ec = runCallout(
      "pore_ec",
      [run("Run 15", true, { pore_ec: series(22, 38, 5.6) }), run("Run 14", false, { pore_ec: series(1, 63, 5.2) })],
      stages,
    );
    expect(ec?.text).toBe("This run is 0.4 mS/cm higher than Run 14 in bulk, days 22–38.");
    const water = runCallout(
      "water",
      [run("Run 15", true, { water: series(1, 21, 0.22) }), run("Run 13", false, { water: series(1, 63, 0.18) })],
      stages,
    );
    expect(water?.text).toBe(
      "Run 13 gave 0.04 L (18%) less water a plant a day than this run all through stretch.",
    );
    // Three runs: the biggest gap is the one named.
    const three = runCallout(
      "vwc",
      [
        run("Run 15", true, { vwc: series(1, 21, 60) }),
        run("Run 14", false, { vwc: series(1, 21, 60.8) }),
        run("Run 13", false, { vwc: series(1, 21, 58.5) }),
      ],
      stages,
    );
    expect(three?.text).toBe("Run 13 sat 1.5 pts drier than this run all through stretch.");
  });

  it("runCallout returns null under each metric's floor", () => {
    const pair = (metric: keyof typeof CALLOUT_FLOOR, a: number, b: number) =>
      runCallout(
        metric,
        [run("Run 15", true, { [metric]: series(1, 21, a) }), run("Run 14", false, { [metric]: series(1, 21, b) })],
        stages,
      );
    expect(pair("vwc", 60, 60.4)).toBeNull();
    expect(pair("dryback", 12, 12.4)).toBeNull();
    expect(pair("pore_ec", 5, 5.1)).toBeNull();
    expect(pair("water", 0.2, 0.21)).toBeNull();
    // At the floor it speaks.
    expect(pair("vwc", 60, 60.5)?.text).toBe("Run 14 sat 0.5 pts wetter than this run all through stretch.");
    // One run, or fewer than three days in common, is not a comparison.
    expect(runCallout("vwc", [run("Run 15", true, { vwc: series(1, 21, 60) })], stages)).toBeNull();
    expect(
      runCallout(
        "vwc",
        [run("Run 15", true, { vwc: series(1, 2, 60) }), run("Run 14", false, { vwc: series(1, 63, 65) })],
        stages,
      ),
    ).toBeNull();
  });

  it("builds whole-room daily values from grow-day summaries, zones averaged", () => {
    const record = {
      id: "r",
      name: "Run 14",
      start_date: "2026-06-09",
      end_date: "2026-08-10",
    } as RunRecord;
    const day = (date: string, zone: number, mean: number, drop: number, ec: number, lpp: number) =>
      ({
        date,
        zone,
        partial: false,
        backfilled: null,
        vwc: { peak: null, trough: null, mean },
        ec: { min: null, max: null, mean: ec },
        p0: { dryback_pct: null, drop_pts: drop, landing: null },
        litres: null,
        litres_per_plant: lpp,
      }) as GrowDay;
    const compared = comparedRun(
      record,
      [day("2026-06-09", 1, 60, 10, 3, 0.1), day("2026-06-09", 2, 62, 12, 4, 0.2), day("2026-06-08", 1, 1, 1, 1, 1)],
      false,
    );
    expect(compared.days).toEqual({
      vwc: [{ day: 1, value: 61 }],
      dryback: [{ day: 1, value: 11 }],
      pore_ec: [{ day: 1, value: 3.5 }],
      water: [{ day: 1, value: 0.15000000000000002 }],
    });
  });

  it("says what a run ended with, never more than was recorded", () => {
    const record = { id: "r", name: "Run 14", start_date: "2026-06-09", end_date: "2026-08-10", zones: [] } as unknown as RunRecord;
    const harvest = {
      harvest_date: "2026-08-10",
      room: { dry_weight_g: 41_200, wet_weight_g: null, plants_harvested: null, canopy_m2: 80 },
      zones: {},
      plants: [],
      quality: null,
      notes: null,
      lab: { thc_pct: null, terpenes: {} },
    } as Harvest;
    expect(runResult(record, harvest, null)).toEqual({ text: "Harvested Mon 10 Aug · 41.2 kg dry · 515 g/m²", missing: false });
    expect(runResult(record, { ...harvest, room: { ...harvest.room!, canopy_m2: null } }, null).text).toBe(
      "Harvested Mon 10 Aug · 41.2 kg dry",
    );
    expect(runResult(record, undefined, null)).toEqual({ text: "No harvest result recorded", missing: true });
    const open = { ...record, end_date: null };
    expect(runResult(open, undefined, "2026-11-16").text).toBe("Growing · harvest due Mon 16 Nov");
    expect(runResult(open, undefined, null).text).toBe("Growing · no harvest date planned");
  });
});
