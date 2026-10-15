import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Timeline } from "@/pages/timeline";
import { createDemo } from "./demo";
import { parseJevEntry, type JevEntry } from "./jev";
import { buildRoom, discoverRooms } from "./model";
import {
  byHand,
  eventKind,
  eventTime,
  eventTimes,
  filterTimeline,
  jevActed,
  jevKind,
  mergeTimeline,
  NO_FILTER,
  timelineCsv,
  timelineResult,
  timelineText,
} from "./timeline";
import type { Controller, LogEvent, States } from "./types";

const at = (day: number, hour: number, minute = 0) =>
  new Date(2026, 8, day, hour, minute).getTime();
const now = at(28, 1, 30);
const event = (
  id: string,
  timestamp: string,
  message: string,
  type: LogEvent["type"],
  zoneId?: number,
) => ({ id, timestamp, message, type, ...(zoneId === undefined ? {} : { zoneId }) }) as LogEvent;
const jev = (raw: Record<string, unknown>, index = 0) => parseJevEntry(raw, index) as JevEntry;
const stamp = (day: number, hour: number, minute = 0) =>
  `2026-09-${day}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00`;

describe("a record's time", () => {
  it("reads an ISO stamp as it is, and a feed clock on the reference's day", () => {
    expect(eventTime("2026-09-27T21:40:00", now)).toBe(at(27, 21, 40));
    expect(eventTime("01:10", now)).toBe(at(28, 1, 10));
    // Still to come today: yesterday's.
    expect(eventTime("23:50", now)).toBe(at(27, 23, 50));
    expect(eventTime("not a time", now)).toBeNull();
  });
  it("steps the feed back a day each time its clock goes forward down the list", () => {
    const feed = [
      event("a", "01:10", "Z1 P3 rescue shot", "water", 1),
      event("b", "22:05", "Z1 P2 shot", "water", 1),
      event("c", "10:30", "Z1 P1 shot", "water", 1),
      event("d", "23:00", "Z2 P2 shot", "water", 2),
    ];
    expect(eventTimes(feed, now)).toEqual([
      at(28, 1, 10),
      at(27, 22, 5),
      at(27, 10, 30),
      at(26, 23, 0),
    ]);
  });
});

describe("the merged timeline", () => {
  const decision = jev(
    {
      t: stamp(27, 22, 48),
      zone: 3,
      judge: "setpoints",
      verdict: "smaller shots",
      p: 0.7,
      action: "P2 shot 4.5% -> 4%",
      result: "acted",
    },
    0,
  );
  const outcome = jev(
    {
      t: stamp(28, 0, 48),
      zone: 3,
      judge: "setpoints",
      kind: "outcome",
      of: "2026-09-27T22:48",
      verdict: "P2 shot 4.5% -> 4%",
      result: "worked",
      reason: "the zone held its re-water point",
    },
    1,
  );
  const stray = jev(
    {
      t: stamp(28, 1, 0),
      zone: 2,
      judge: "salt",
      kind: "outcome",
      of: stamp(20, 12, 0),
      verdict: "hold the EC steer",
      result: "did not work",
    },
    2,
  );
  const quiet = jev(
    { t: stamp(27, 23, 30), zone: 1, judge: "night", verdict: "real drying", result: "no action" },
    3,
  );
  const alert = jev(
    {
      t: stamp(27, 15, 1),
      zone: 2,
      judge: "alerts",
      verdict: "first of its kind today",
      action: "CS-705: card only",
      result: "acted",
      reason: "this zone is off the stage's arc",
    },
    4,
  );
  const feed = [
    event("w", "2026-09-28T01:20:00", "Rescue shot: 0.4 L (P3)", "water", 1),
    event("p", "2026-09-27T22:00:00", "P2 → P3: lights off", "phase", 1),
    event("h", "2026-09-27T12:00:00", "Pump fault: holding", "warning"),
    event("s", "2026-09-27T11:00:00", "Z1 P2 threshold 62 → 61 by hand", "info", 1),
    event("i", "2026-09-27T10:00:00", "Controller started", "info"),
  ];
  const merged = mergeTimeline(feed, [stray, outcome, quiet, decision, alert], now);

  it("is one list, newest first, the controller's records and Jev's side by side", () => {
    expect(merged.map((item) => item.time)).toEqual(
      [...merged.map((item) => item.time)].sort((a, b) => b! - a!),
    );
    expect(merged.map((item) => item.key)).toEqual([
      "event:w",
      "jev:2:2026-09-28T01:00:00:salt",
      "jev:3:2026-09-27T23:30:00:night",
      "jev:0:2026-09-27T22:48:00:setpoints",
      "event:p",
      "jev:4:2026-09-27T15:01:00:alerts",
      "event:h",
      "event:s",
      "event:i",
    ]);
  });
  it("puts an outcome on the decision it checks, not on a row of its own", () => {
    const row = merged.find((item) => item.jev === decision)!;
    expect(row.outcomes).toEqual([outcome]);
    expect(merged.some((item) => item.jev === outcome)).toBe(false);
    expect(timelineResult(row)).toBe("Acted; worked");
  });
  it("keeps an outcome whose decision is not on the list as a row", () => {
    const row = merged.find((item) => item.jev === stray)!;
    expect(row.outcomes).toEqual([]);
    expect(timelineText(row)).toBe("Jev · Pore EC: after “hold the EC steer”");
    expect(timelineResult(row)).toBe("Didn’t work");
  });
  it("sorts each row into water, phase, setpoints, alerts, Jev or a note", () => {
    expect(merged.map((item) => item.kind)).toEqual([
      "water",
      "jev",
      "jev",
      "setpoint",
      "phase",
      "alert",
      "alert",
      "setpoint",
      "note",
    ]);
    expect(eventKind(event("x", "10:00", "Z2 waiting: under the P2 threshold", "info"))).toBe(
      "note",
    );
    expect(eventKind(event("x", "10:00", "Shot size 4 to 5 %", "info"))).toBe("setpoint");
    expect(eventKind(event("x", "10:00", "P2 shot size 4 -> 5 %", "info"))).toBe("setpoint");
    expect(jevKind(jev({ judge: "dawn", action: "CS-701: push", result: "acted" }))).toBe("alert");
  });
  it("shows Jev's actions by default and every decision on request", () => {
    expect(filterTimeline(merged, NO_FILTER).some((item) => item.jev === quiet)).toBe(false);
    expect(
      filterTimeline(merged, { ...NO_FILTER, allJev: true }).some((item) => item.jev === quiet),
    ).toBe(true);
    // A refusal is Jev asking; it shows with the actions.
    const refused = mergeTimeline(
      [],
      [
        jev({
          t: stamp(27, 10, 54),
          zone: 3,
          judge: "dawn",
          action: "start the ramp now",
          result: "refused",
        }),
      ],
      now,
    );
    expect(filterTimeline(refused, NO_FILTER)).toHaveLength(1);
  });
  it("filters by zone, the room alone, type and words", () => {
    const zones = (filter: Partial<typeof NO_FILTER>) =>
      filterTimeline(merged, { ...NO_FILTER, allJev: true, ...filter }).map((item) => item.key);
    expect(zones({ zone: 3 })).toEqual(["jev:0:2026-09-27T22:48:00:setpoints"]);
    expect(zones({ zone: "room" })).toEqual(["event:h", "event:i"]);
    expect(zones({ type: "setpoint" })).toEqual(["jev:0:2026-09-27T22:48:00:setpoints", "event:s"]);
    expect(zones({ type: "alert", zone: 2 })).toEqual(["jev:4:2026-09-27T15:01:00:alerts"]);
    expect(zones({ query: "LIGHTS OFF" })).toEqual(["event:p"]);
    // Code's why is searched too.
    expect(zones({ query: "stage's arc" })).toEqual(["jev:4:2026-09-27T15:01:00:alerts"]);
  });
  it("exports as CSV with the local time, the row in words and Jev's result", () => {
    const csv = timelineCsv(merged, "Flower 2").split("\r\n");
    expect(csv[0]).toBe('"Timestamp","Room","Zone","Type","Message","Result"');
    expect(csv).toContain(
      '"2026-09-27 22:48:00","Flower 2","3","setpoint","Jev · Setpoints: smaller shots, 70% → P2 shot 4.5% → 4%","Acted; worked"',
    );
    expect(csv).toContain(
      '"2026-09-27 12:00:00","Flower 2","Room","alert","Pump fault: holding",""',
    );
    expect(
      timelineCsv(
        mergeTimeline([event("f", "2026-09-27T10:00:00", "=HYPERLINK()", "info")], [], now),
        "R",
      ),
    ).toContain(`"'=HYPERLINK()"`);
  });
});

describe("a setpoint the grower changed", () => {
  it("is the grower's, noted by Jev, not Jev acting", () => {
    const entry = jev({
      t: stamp(28, 15, 13),
      zone: 2,
      judge: "setpoints",
      verdict: "set by hand",
      action: "p2 vwc threshold 62 -> 61",
      result: "acted",
    });
    const [row] = mergeTimeline([], [entry], now);
    expect(byHand(entry)).toBe(true);
    expect(row.kind).toBe("setpoint");
    expect(timelineText(row)).toBe("By hand · Setpoints: p2 vwc threshold 62 → 61");
    expect(timelineResult(row)).toBe("Noted by Jev");
    expect(byHand(jev({ judge: "setpoints", verdict: "smaller shots", result: "acted" }))).toBe(
      false,
    );
  });
});

describe("Jev's actions", () => {
  it("are what did something or tried to, and how it turned out", () => {
    const entries = ["acted", "no action", "advice", "refused", "worked", "waiting", "?"].map(
      (result, index) => jev({ t: stamp(27, 10 + index), zone: 1, judge: "salt", result }, index),
    );
    expect(entries.filter(jevActed).map((entry) => entry.result)).toEqual([
      "acted",
      "refused",
      "worked",
    ]);
  });
});

describe("the Timeline page", () => {
  const controller = (states: States, prefix: string) =>
    ({
      states,
      room: buildRoom(
        states,
        discoverRooms(states).find((room) => room.prefix === prefix)!,
      ),
    }) as Controller;
  const noon = new Date(2026, 8, 28, 16, 0).getTime();
  // The page reads the clock: pinned to the demo's day, so "Today" and "Yesterday" are the demo's.
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(noon);
  });
  afterEach(() => vi.useRealTimers());
  it("lists the demo room's records and Jev's actions, a tick or cross on a checked decision", () => {
    const states = createDemo(noon);
    const html = renderToStaticMarkup(
      createElement(Timeline, { controller: controller(states, "") }),
    );
    const rows = html.match(/class="timeline-row"/g)?.length ?? 0;
    const merged = mergeTimeline(
      buildRoom(states, discoverRooms(states)[0]).events,
      [],
      noon,
    ).length;
    expect(rows).toBeGreaterThan(merged);
    for (const text of ["All Jev decisions", "Refused", "Advice", "calls today", "input tokens"])
      expect(html).toContain(text);
    expect(html).toMatch(/class="timeline-outcome" data-worked="(true|false)"/);
    // Days are headed: the demo's journal reaches back to yesterday.
    expect(html).toContain("<h2>Today</h2>");
    expect(html).toContain("<h2>Yesterday</h2>");
  });
  it("shows a room without Jev its controller records, without Jev's controls", () => {
    const states = createDemo(noon);
    const html = renderToStaticMarkup(
      createElement(Timeline, { controller: controller(states, "f1_") }),
    );
    expect(html).toContain('class="timeline-row"');
    expect(html).not.toContain("All Jev decisions");
    expect(html).not.toContain('data-source="jev"');
  });
  it("opens on one zone when asked", () => {
    const states = createDemo(noon);
    const html = renderToStaticMarkup(
      createElement(Timeline, { controller: controller(states, ""), zone: 3 }),
    );
    expect(
      html.match(/class="timeline-zone">([^<]+)</g)?.every((cell) => cell.includes("Zone 3")),
    ).toBe(true);
  });
});
