import { describe, expect, test } from "vitest";
import type { TimelineSummary } from "./parity-types";
import type { TimelineBlock, TimelineRow } from "./shot-timeline";
import { fakeController } from "./test-helpers";
import {
  dayChip,
  dayStart,
  defaultSpan,
  keepProblems,
  liveMatch,
  loadRevisions,
  shiftDate,
  skipShot,
  spanOf,
  statusLine,
  stripDates,
  wateringHash,
  wateringQuery,
  type WateringQuery,
} from "./watering";

const TZ = "Pacific/Auckland";

describe("wateringQuery", () => {
  test("wateringQuery round-trips including rooms", () => {
    const q: WateringQuery = {
      date: "2026-10-22",
      span: 48,
      rooms: ["F1", "F2"],
      stages: ["flower"],
      problemsOnly: true,
      q: "z3",
    };
    const hash = wateringHash(q);
    expect(hash).toBe("#/plan/watering?date=2026-10-22&span=48&rooms=F1,F2&stages=flower&problems=1&q=z3");
    expect(wateringQuery(hash)).toEqual(q);
  });

  test("an address without a query reads the defaults", () => {
    expect(wateringQuery("#/plan/watering")).toEqual({
      date: "",
      span: 24,
      rooms: [],
      stages: [],
      problemsOnly: false,
      q: "",
    });
    expect(wateringQuery("#/plan/watering?span=7&date=22-10-2026").span).toBe(24);
    expect(wateringQuery("#/plan/watering?span=7&date=22-10-2026").date).toBe("");
  });
});

test("default span is 24 on desktop and 12 on phone", () => {
  expect(defaultSpan(1440)).toBe(24);
  expect(defaultSpan(721)).toBe(24);
  expect(defaultSpan(720)).toBe(12);
  expect(defaultSpan(390)).toBe(12);
});

describe("dates", () => {
  test("a week strip centred on the date, across a month end", () => {
    expect(stripDates("2026-10-30")).toEqual([
      "2026-10-27",
      "2026-10-28",
      "2026-10-29",
      "2026-10-30",
      "2026-10-31",
      "2026-11-01",
      "2026-11-02",
    ]);
    expect(shiftDate("2026-01-01", -1)).toBe("2025-12-31");
  });

  test("a date starts at the zone's midnight, and a span starts there", () => {
    const start = dayStart("2026-10-22", TZ);
    expect(new Date(start).toISOString()).toBe("2026-10-21T11:00:00.000Z");
    const q = wateringQuery("#/plan/watering?date=2026-10-22&span=48");
    expect(spanOf(q, start + 14 * 3_600_000, TZ)).toEqual({ start, end: start + 48 * 3_600_000 });
  });

  test("12 h today sits around now; another day shows its daytime", () => {
    const start = dayStart("2026-10-22", TZ);
    const now = start + 14 * 3_600_000 + 10 * 60_000; // 14:10
    const today = spanOf({ ...wateringQuery(""), date: "2026-10-22", span: 12 }, now, TZ, "2026-10-22");
    expect(today).toEqual({ start: start + 7 * 3_600_000, end: start + 19 * 3_600_000 });
    const other = spanOf({ ...wateringQuery(""), date: "2026-10-23", span: 12 }, now, TZ, "2026-10-22");
    expect(other.start).toBe(dayStart("2026-10-23", TZ) + 6 * 3_600_000);
  });
});

describe("dayChip", () => {
  const summary: TimelineSummary = {
    days: [
      {
        date: "2026-10-21",
        rooms: [
          { room_id: "room:", shots: 20, failed: 0, warnings: 1, held: 2, queued: 1 },
          { room_id: "room:b_", shots: 12, failed: 0, warnings: 0, held: 0, queued: 0 },
        ],
      },
      {
        date: "2026-10-22",
        rooms: [
          { room_id: "room:", shots: 20, failed: 1, warnings: 1, held: 0, queued: 0 },
          { room_id: "room:b_", shots: 12, failed: 0, warnings: 1, held: 0, queued: 0 },
        ],
      },
      { date: "2026-10-20", rooms: [{ room_id: "room:", shots: 20, failed: 0, warnings: 0, held: 3, queued: 0 }] },
    ],
  };
  const rooms = ["room:", "room:b_"];

  test("dayChip counts failed plus warnings from timeline_summary", () => {
    expect(dayChip(summary, "2026-10-22", rooms, "2026-10-22")).toEqual({ label: "3 problems", tone: "problem" });
    expect(dayChip(summary, "2026-10-21", rooms, "2026-10-22")).toEqual({ label: "1 problem", tone: "problem" });
    expect(dayChip(summary, "2026-10-22", ["room:b_"], "2026-10-22")).toEqual({ label: "1 problem", tone: "problem" });
  });

  test("held and queued are not problems; a day ahead is planned", () => {
    expect(dayChip(summary, "2026-10-20", rooms, "2026-10-22")).toEqual({ label: "Done", tone: "done" });
    expect(dayChip(summary, "2026-10-23", rooms, "2026-10-22")).toEqual({ label: "Planned", tone: "planned" });
    expect(dayChip({ days: [] }, "2026-10-19", rooms, "2026-10-22")).toEqual({ label: "Done", tone: "done" });
  });
});

const T0 = Date.parse("2026-10-22T10:00:00+13:00");
function block(extra: Partial<TimelineBlock>): TimelineBlock {
  return {
    id: "x",
    glyph: "done",
    start: T0,
    end: T0 + 60_000,
    requestedAt: null,
    pumpWaitS: null,
    litres: 1.21,
    meteredL: null,
    litresPerPlant: null,
    reason: null,
    phase: null,
    vwcBefore: null,
    vwcExpected: null,
    source: "engine",
    code: null,
    eventId: null,
    skippable: false,
    zone: 1,
    roomId: "room:",
    running: false,
    skipped: false,
    ...extra,
  };
}
const row = (roomId: string, zone: number | null, blocks: TimelineBlock[]): TimelineRow => ({
  key: zone === null ? roomId : `${roomId}:${zone}`,
  roomId,
  zone,
  label: zone === null ? roomId : `Zone ${zone}`,
  sublabel: "",
  blocks,
  lights: [],
});

test("problemsOnly keeps rooms with a failed or warning block", () => {
  const rows = [
    row("room:", null, []),
    row("room:", 1, [block({ glyph: "done" })]),
    row("room:", 2, [block({ glyph: "warning", zone: 2 })]),
    row("room:b_", null, []),
    row("room:b_", 1, [block({ glyph: "done", roomId: "room:b_" }), block({ glyph: "planned", roomId: "room:b_" })]),
    row("room:c_", null, []),
    row("room:c_", 3, [block({ glyph: "failed", roomId: "room:c_", zone: 3 })]),
  ];
  expect(keepProblems(rows).map((r) => r.key)).toEqual(["room:", "room::1", "room::2", "room:c_", "room:c_:3"]);
});

describe("skip", () => {
  test("skip uses the revision from timer_program_list", async () => {
    const calls: [string, Record<string, unknown> | undefined][] = [];
    const controller = fakeController({
      operator: async (action, data) => {
        calls.push([action, data]);
        if (action === "timer_program_list")
          return { api: 2, ok: true, revision: null, data: { programs: [], revision: null, revisions: { "room:": 7, "room:b_": 3 } } };
        return { api: 2, ok: true, revision: 8, readback: { status: "verified", at: null }, event_ids: ["01EVT"], data: { skip: {}, revision: 8 } };
      },
    });
    const revisions = await loadRevisions(controller);
    expect(revisions).toEqual({ "room:": 7, "room:b_": 3 });
    const result = await skipShot(controller, block({ glyph: "planned", zone: 3, skippable: true }), revisions!);
    expect(result).toEqual({ kind: "ok", eventIds: ["01EVT"] });
    expect(calls[1]).toEqual([
      "timer_skip",
      { room_id: "room:", zone: 3, at: new Date(T0).toISOString(), expected_revision: 7, api: 2 },
    ]);
  });

  test("a stale revision comes back as stale, never retried", async () => {
    let skips = 0;
    const controller = fakeController({
      operator: async (action) => {
        if (action === "timer_skip") skips++;
        return { api: 2, ok: false, error: { code: "stale_revision", message: "Timer programs changed elsewhere.", current_revision: 9 } };
      },
    });
    expect(await skipShot(controller, block({ skippable: true }), { "room:": 7 })).toEqual({ kind: "stale" });
    expect(skips).toBe(1);
  });

  test("without a revision for the room nothing is sent", async () => {
    const controller = fakeController({ operator: () => Promise.reject(new Error("sent")) });
    expect((await skipShot(controller, block({ skippable: true }), {})).kind).toBe("error");
  });
});

describe("popover words", () => {
  test("a planned shot that waited for the pump says so", () => {
    expect(statusLine(block({ glyph: "planned", pumpWaitS: 720 }))).toBe("Planned · waited 12 min for pump");
    expect(statusLine(block({ glyph: "done", pumpWaitS: 64 }))).toBe("Done · waited 1 min for pump");
    expect(statusLine(block({ glyph: "done", running: true }))).toBe("Watering now");
    expect(statusLine(block({ glyph: "planned", skipped: true }))).toBe("Skipped");
    expect(statusLine(block({ glyph: "failed", pumpWaitS: 0 }))).toBe("Failed");
  });
});

test("a live event reloads only for a visible room inside the span", () => {
  const span = { start: T0, end: T0 + 3_600_000 };
  const event = (kind: string, room_id: string, at: number) =>
    ({ v: 1, id: "e", ts: new Date(at).toISOString(), room_id, zone: 1, kind, outcome: "ok", code: null, source: { actor: "engine" }, data: {} }) as const;
  expect(liveMatch(event("shot.started", "room:", T0 + 60_000), ["room:"], span)).toBe(true);
  expect(liveMatch(event("intent.queued", "room:", T0 + 60_000), ["room:"], span)).toBe(true);
  expect(liveMatch(event("shot.started", "room:b_", T0 + 60_000), ["room:"], span)).toBe(false);
  expect(liveMatch(event("shot.started", "room:", T0 + 2 * 3_600_000), ["room:"], span)).toBe(false);
  expect(liveMatch(event("target.changed", "room:", T0 + 60_000), ["room:"], span)).toBe(false);
});
