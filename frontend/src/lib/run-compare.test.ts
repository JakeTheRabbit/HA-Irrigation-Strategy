import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunChart, RunCompare, RUN_METRICS } from "@/pages/run-compare";
import type { ComparedRun, RunRecord, RunsDocument } from "./comparison-types";
import { stageArc } from "./stage-arc";
import { fakeController } from "./test-helpers";

const stages = stageArc(56);
const vwc = RUN_METRICS.find((m) => m.metric === "vwc")!;
const run = (id: string, current: boolean, values: number[]): ComparedRun => ({
  id,
  name: id,
  current,
  days: { vwc: values.map((value, i) => ({ day: i + 1, value })) },
  digits: { vwc: 1 },
});
const chart = (runs: ComparedRun[], today: number | null = null) =>
  renderToStaticMarkup(
    createElement(RunChart, {
      spec: vwc,
      runs,
      colours: new Map(runs.map((r) => [r.id, "red"])),
      stages,
      maxDay: 56,
      today,
    }),
  );

describe("compare runs charts", () => {
  it("asks for a run to be ticked when none is, instead of saying the ticked runs lack data", () => {
    const html = chart([]);
    expect(html).toContain("Tick a run to compare.");
    expect(html).not.toContain("No grow-day summary");
  });

  it("says each run's mean in the chart's text alternative, not by line colour alone", () => {
    const html = chart([run("Run 15", true, [60, 61, 62]), run("Run 14", false, [58.5, 58.5])]);
    expect(html).toContain("Run 15 averages 61.0%");
    expect(html).toContain("Run 14 averages 58.5%");
  });
});

describe("compare runs legend", () => {
  afterEach(() => vi.useRealTimers());
  const record = (start: string): RunRecord => ({
    id: "r15",
    room_id: "room:",
    name: "Run 15",
    start_date: start,
    end_date: null,
    time_zone: "Pacific/Auckland",
    archived: false,
    captured_at: "",
    reference_source: "",
    lights: { on: null, off: null },
    zones: [],
  });
  const page = (start: string) => {
    vi.useFakeTimers();
    vi.setSystemTime(Date.parse("2026-10-23T12:00:00+13:00"));
    const runs: RunsDocument = {
      schema_version: 1,
      room_id: "room:",
      revision: 1,
      time_zone: "Pacific/Auckland",
      runs: [record(start)],
      error: null,
      max_runs: 20,
    };
    return renderToStaticMarkup(createElement(RunCompare, { controller: fakeController({}), runs, refresh: 0 }));
  };

  it("names today only while today's line is drawn", () => {
    const within = page("2026-10-14");
    expect(within).toContain("Today, day 10 of this run");
    expect(within).toContain("rc-today");
    // Day 300 is past the 56-day chart: no line, so no legend entry for it.
    const past = page("2025-12-28");
    expect(past).not.toContain("Today, day");
    expect(past).not.toContain("rc-today");
  });
});
