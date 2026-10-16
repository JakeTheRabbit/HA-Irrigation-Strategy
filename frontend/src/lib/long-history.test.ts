import { afterEach, describe, expect, it, vi } from "vitest";
import { HaClient } from "./client";

const request = { entityIds: ["sensor.probe"], start: "2026-01-01T00:00:00Z", end: "2026-01-02T00:00:00Z", timeZone: "UTC" };
afterEach(() => vi.unstubAllGlobals());

describe("optional InfluxDB history", () => {
  it("uses bounded server history and labels its source", async () => {
    const fetcher = vi.fn(async (url: string) => new Response(JSON.stringify({ service_response:
      url.includes("history_connection_get") ? { connection: { source: "influxdb" } } : {
        start: request.start, end: request.end, warnings: ["InfluxDB downsampled"],
        series: [{ entityId: "sensor.probe", points: [{ time: Date.parse(request.start), value: 40, min: 38, max: 42 }] }],
      } }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const result = await new HaClient("https://ha.example", "ha-token").historyWindow(request, "room:test_");
    expect(result.series[0].points[0].value).toBe(40);
    expect(result.series[0].daily[0].records).toBe(1);
    expect(result.warnings[0]).toContain("InfluxDB");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("falls back to Recorder visibly when the opted-in server query fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("history_connection_get")) return new Response(JSON.stringify({ service_response: { connection: { source: "influxdb" } } }));
      if (url.includes("history_long")) return new Response("failed", { status: 500 });
      return new Response(JSON.stringify([[{ entity_id: "sensor.probe", state: "40", last_changed: request.start }]]));
    }));
    const result = await new HaClient("https://ha.example", "ha-token").historyWindow(request, "room:test_");
    expect(result.warnings[0]).toContain("showing Home Assistant Recorder");
    expect(result.series[0].points.length).toBeGreaterThan(0);
  });
});
