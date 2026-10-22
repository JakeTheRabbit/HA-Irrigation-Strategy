import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Explorer } from "@/pages/explorer";
import { ZonePage } from "@/pages/zone";
import { createDemo } from "./demo";
import { buildRoom, discoverRooms } from "./model";
import { eventTime, eventTimes } from "./timeline";
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

describe("History › Explorer", () => {
  const noon = new Date(2026, 8, 28, 16, 0).getTime();
  // The page reads the clock: pinned to the demo's day.
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(noon);
  });
  afterEach(() => vi.useRealTimers());
  const controller = (states: States, prefix: string) => {
    const rooms = discoverRooms(states);
    const room = rooms.find((item) => item.prefix === prefix)!;
    return {
      states,
      rooms,
      room: buildRoom(states, room),
      roomId: room.id,
      timeZone: "Pacific/Auckland",
      connection: "demo",
      demo: true,
      recentEvents: [],
    } as unknown as Controller;
  };
  it("charts the room under its lanes, with the series chips, ranges and CSV export", () => {
    const html = renderToStaticMarkup(createElement(Explorer, { controller: controller(createDemo(noon), "") }));
    expect(html).toContain("<h1");
    expect(html).toContain(">Explorer</h1>");
    for (const range of ["Today", "7 d", "This run", "Custom"]) expect(html).toContain(`>${range}</button>`);
    expect(html).toContain("Export CSV · 8 series");
    expect(html).toContain('aria-label="Zone 3 VWC"');
    expect(html).toContain("Compare with last run");
    // The old list and its setpoint log are gone: who changed what lives on History › Changes.
    expect(html).not.toContain("timeline-row");
    expect(html).not.toContain("Search the timeline");
    // Without a zone picked, the zone's probe detail waits for one.
    expect(html).not.toContain("data-history-explorer");
    expect(html).toContain("Pick a zone in the room list");
    // Until History › Changes is built, the page says where setting changes will be.
    expect(html).toContain("Setting changes will show on History › Changes.");
    // The AI assistant's decisions that acted, with how each turned out.
    expect(html).toContain("AI assistant decisions");
    expect(html).toMatch(/data-ai-decision=/);
    expect(html).toMatch(/class="explorer-outcome" data-worked="(true|false)"/);
  });
  it("keeps one operational chart on Zone and moves long-term evidence into History for that zone", () => {
    const states = createDemo(noon);
    const control = controller(states, "");
    const zone = control.room.zones[2];
    const detail = renderToStaticMarkup(
      createElement(ZonePage, { controller: control, zoneId: zone.id, navigate: () => undefined }),
    );
    expect(detail.match(/data-day-timeline=/g)).toHaveLength(1);
    expect(detail.match(/data-zone-why=/g)).toHaveLength(1);
    expect(detail).not.toContain("data-history-explorer");
    expect(detail).not.toContain("Recorded behaviour against targets");
    expect(detail).not.toContain("data-brain-zone");
    const history = renderToStaticMarkup(createElement(Explorer, { controller: control, zone: zone.id }));
    expect(history.match(/data-history-explorer=/g)).toHaveLength(1);
    expect(history).toContain(`${zone.name}: each probe, its targets and other grows`);
    expect(history).toContain("Recorded behaviour against targets");
    // The phase lane follows the zone picked.
    expect(history).toContain(`Phase · ${zone.name}`);
  });
});
