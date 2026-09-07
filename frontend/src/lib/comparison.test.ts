import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addDays,
  ageAt,
  boundedRange,
  comparisonRange,
  downsample,
  midnight,
  summarize,
  timeAtAge,
} from "./comparison";
import { loadHistoryWindow } from "./comparison-history";
import { HaClient } from "./client";
import type { HistoryRequest, RunRecord } from "./comparison-types";
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
    expect(result.warnings.join(" ")).toMatch(/retention expired/);
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
