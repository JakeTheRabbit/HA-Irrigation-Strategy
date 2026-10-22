import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, test } from "vitest";
import { ShotTimeline } from "@/components/shot-timeline";
import { setDisplayUnits } from "./display-units";
import type { TimelineBlock as ApiBlock, TimelineGetData } from "./parity-types";
import {
  blockSentence,
  nextFocus,
  place,
  toTimelineRows,
  type TimelineBlock,
  type TimelineRow,
} from "./shot-timeline";

const TZ = "Pacific/Auckland";
const T0 = Date.parse("2026-10-22T06:00:00+13:00");
const iso = (ms: number) => new Date(ms).toISOString();
const min = 60_000;

function api(extra: Partial<ApiBlock>): ApiBlock {
  return {
    id: "b",
    kind: "shot",
    status: "done",
    start: iso(T0),
    end: iso(T0 + 2 * min),
    litres: 2.4,
    metered_l: null,
    reason: null,
    phase: "P2",
    vwc_before: null,
    vwc_expected: null,
    requested_at: null,
    pump_wait_s: null,
    source: "engine",
    code: null,
    event_id: null,
    skippable: false,
    expected: false,
    running: false,
    skipped: false,
    ...extra,
  };
}
function data(
  blocks: ApiBlock[],
  extra: Partial<TimelineGetData["rooms"][number]> = {},
): TimelineGetData {
  return {
    rooms: [
      {
        room_id: "room:f2_",
        lights: [{ on: iso(T0), off: iso(T0 + 12 * 60 * min) }],
        rows: [{ zone: 3, blocks }],
        pump: null,
        pump_rooms: [],
        pump_load: [],
        planned_source: "projection_app",
        ...extra,
      },
    ],
    errors: { count: 0, markers: [] },
  };
}
const ROOMS = [{ id: "room:f2_", name: "F2", stage: "Flower", day: 38 }];
const rowsOf = (blocks: ApiBlock[], extra?: Partial<TimelineGetData["rooms"][number]>) =>
  toTimelineRows(data(blocks, extra), { "room:f2_:3": 40 }, ROOMS);
const glyphs = (blocks: ApiBlock[]) => rowsOf(blocks)[1].blocks.map((b) => b.glyph);

function block(extra: Partial<TimelineBlock>): TimelineBlock {
  return {
    id: "x",
    glyph: "done",
    start: T0,
    end: T0 + 2 * min,
    requestedAt: null,
    pumpWaitS: null,
    litres: 2.4,
    meteredL: null,
    litresPerPlant: 0.06,
    reason: null,
    phase: null,
    vwcBefore: null,
    vwcExpected: null,
    source: "engine",
    code: null,
    eventId: null,
    skippable: false,
    zone: 3,
    roomId: "room:f2_",
    running: false,
    skipped: false,
    ...extra,
  };
}

afterEach(() => setDisplayUnits({ clock: "24", volume: "L" }));

describe("toTimelineRows glyphs", () => {
  test("maps expected:true to expected regardless of source", () => {
    expect(
      glyphs([
        api({ id: "a", kind: "planned", status: "planned", expected: true, source: "engine" }),
        api({ id: "b", kind: "planned", status: "planned", expected: true, source: "timer" }),
        api({ id: "c", kind: "planned", status: "planned", source: "timer" }),
        api({ id: "d", kind: "shot", status: "done" }),
      ]),
    ).toEqual(["expected", "expected", "planned", "done"]);
  });

  test("maps held and error to failed, alert to warning", () => {
    expect(
      glyphs([
        api({ id: "a", kind: "held", status: "warning" }),
        api({ id: "b", kind: "shot", status: "error" }),
        api({ id: "c", kind: "alert", status: "warning" }),
        api({ id: "d", kind: "shot", status: "warning" }),
        api({ id: "e", kind: "queued", status: "warning" }),
      ]),
    ).toEqual(["failed", "failed", "warning", "warning", "queued"]);
  });

  test("running is done and flagged; skipped is planned and flagged", () => {
    const [running, skipped] = rowsOf([
      api({ id: "a", running: true }),
      api({ id: "b", kind: "planned", status: "planned", expected: true, skipped: true }),
    ])[1].blocks;
    expect([running.glyph, running.running]).toEqual(["done", true]);
    expect([skipped.glyph, skipped.skipped]).toEqual(["planned", true]);
  });

  test("a room row leads its zone rows, with lights, litres per plant and tone", () => {
    const rows = rowsOf([
      api({ id: "a", litres: 2, metered_l: 2.4 }),
      api({ id: "b", kind: "shot", status: "error" }),
    ]);
    expect(rows.map((r) => [r.key, r.zone, r.label, r.sublabel, r.tone])).toEqual([
      ["room:f2_", null, "F2", "Flower · day 38", "bad"],
      ["room:f2_:3", 3, "Zone 3", "P2", "bad"],
    ]);
    expect(rows[0].lights).toEqual([{ on: T0, off: T0 + 12 * 60 * min }]);
    expect(rows[1].blocks[0].litresPerPlant).toBeCloseTo(0.06);
    expect(rows[0].plannedUnavailable).toBeFalsy();
  });

  test("planned_source unavailable marks the room row", () => {
    expect(rowsOf([api({})], { planned_source: "unavailable" })[0].plannedUnavailable).toBe(true);
  });
});

describe("placement and keys", () => {
  const span = { start: T0, end: T0 + 100 * min };
  test("place clamps blocks crossing the span edge", () => {
    expect(place(block({ start: T0 - 10 * min, end: T0 + 10 * min }), span)).toEqual({
      offsetPct: 0,
      sizePct: 10,
    });
    expect(place(block({ start: T0 + 95 * min, end: T0 + 110 * min }), span)).toEqual({
      offsetPct: 95,
      sizePct: 5,
    });
    expect(place(block({ start: T0 + 20 * min, end: T0 + 30 * min }), span)).toEqual({
      offsetPct: 20,
      sizePct: 10,
    });
  });

  test("place answers 0/0 for an empty span", () => {
    expect(place(block({}), { start: T0, end: T0 })).toEqual({ offsetPct: 0, sizePct: 0 });
    expect(place(block({}), { start: T0, end: T0 - min })).toEqual({ offsetPct: 0, sizePct: 0 });
  });

  test("queued block keeps requestedAt and pumpWaitS", () => {
    const requested = T0 - 5 * min;
    const [queued] = rowsOf([
      api({ kind: "queued", status: "warning", requested_at: iso(requested), pump_wait_s: 300 }),
    ])[1].blocks;
    expect(queued.glyph).toBe("queued");
    expect(queued.requestedAt).toBe(requested);
    expect(queued.pumpWaitS).toBe(300);
  });

  test("nextFocus moves right within a row, down across rows, Home to nearest now", () => {
    const row = (key: string, starts: number[]): TimelineRow => ({
      key,
      roomId: "room:f2_",
      zone: 1,
      label: key,
      sublabel: "",
      lights: [],
      blocks: starts.map((s, i) =>
        block({ id: `${key}${i}`, start: T0 + s * min, end: T0 + s * min + min }),
      ),
    });
    const rows = [row("a", [0, 10, 20]), { ...row("room", []), zone: null }, row("b", [2, 19, 40])];
    expect(nextFocus(rows, { row: 0, block: 0 }, "ArrowRight", T0)).toEqual({ row: 0, block: 1 });
    expect(nextFocus(rows, { row: 0, block: 2 }, "ArrowRight", T0)).toEqual({ row: 0, block: 2 });
    expect(nextFocus(rows, { row: 0, block: 0 }, "ArrowLeft", T0)).toEqual({ row: 0, block: 0 });
    // Down skips the empty room row and lands on the block nearest in time.
    expect(nextFocus(rows, { row: 0, block: 2 }, "ArrowDown", T0)).toEqual({ row: 2, block: 1 });
    expect(nextFocus(rows, { row: 2, block: 0 }, "ArrowUp", T0)).toEqual({ row: 0, block: 0 });
    expect(nextFocus(rows, { row: 2, block: 0 }, "ArrowDown", T0)).toEqual({ row: 2, block: 0 });
    expect(nextFocus(rows, { row: 2, block: 0 }, "Home", T0 + 37 * min)).toEqual({
      row: 2,
      block: 2,
    });
  });
});

describe("ShotTimeline", () => {
  const span = { start: T0, end: T0 + 12 * 60 * min };
  const now = T0 + 6 * 60 * min;
  const rows = (): TimelineRow[] => [
    {
      key: "room:f2_",
      roomId: "room:f2_",
      zone: null,
      label: "F2",
      sublabel: "Flower · day 38",
      blocks: [],
      lights: [],
    },
    {
      key: "room:f2_:3",
      roomId: "room:f2_",
      zone: 3,
      label: "Zone 3",
      sublabel: "P2",
      lights: [{ on: T0, off: T0 + 12 * 60 * min }],
      blocks: [
        block({ id: "past", start: T0 + 280 * min, end: T0 + 282 * min }),
        block({ id: "future", glyph: "planned", start: T0 + 420 * min, end: T0 + 422 * min }),
      ],
    },
  ];
  const render = (extra: Record<string, unknown> = {}) =>
    renderToStaticMarkup(
      createElement(ShotTimeline, {
        rows: rows(),
        span,
        now,
        mode: "full",
        timeZone: TZ,
        ...extra,
      }),
    );

  test("block buttons carry the spoken sentence", () => {
    setDisplayUnits({ clock: "24", volume: "L" });
    const out = render();
    expect(out).toContain('aria-label="F2 zone 3, 10:40, 2.4 litres, done."');
    expect(out).toMatch(/<button[^>]*aria-label="F2 zone 3, 13:00, 2.4 litres, planned\."/);
    expect(blockSentence(block({ running: true }), "F2", TZ)).toBe(
      "F2 zone 3, 06:00, 2.4 litres, watering now.",
    );
    expect(blockSentence(block({ glyph: "planned", skipped: true }), "F2", TZ)).toBe(
      "F2 zone 3, 06:00, 2.4 litres, skipped.",
    );
    expect(blockSentence(block({ glyph: "queued", litres: null }), "F2", TZ)).toBe(
      "F2 zone 3, 06:00, waiting for pump.",
    );
    // One block is in the tab order (roving tabindex).
    expect(out.match(/tabindex="0"/g)).toHaveLength(1);
    expect(out).toContain("Now </span>12:00");
  });

  test("stale hatches only future blocks", () => {
    const out = render({ stale: true });
    expect(out).toMatch(
      /data-id="future"[^>]*data-stale="true"|data-stale="true"[^>]*data-id="future"/,
    );
    expect(out).not.toMatch(/data-id="past"[^>]*data-stale|data-stale="true"[^>]*data-id="past"/);
    expect(render()).not.toContain("data-stale");
  });

  test("vertical orientation labels width as water", () => {
    const out = render({ orientation: "vertical" });
    expect(out).toContain("Width = water");
    expect(out).toContain('data-orientation="vertical"');
    expect(render()).toContain("Bar height = water per plant");
  });

  test("planned shots unavailable shows one muted line", () => {
    const list = rows();
    list[0].plannedUnavailable = true;
    const out = renderToStaticMarkup(
      createElement(ShotTimeline, { rows: list, span, now, mode: "full", timeZone: TZ }),
    );
    expect(out.match(/Planned shots not available from the controller/g)).toHaveLength(1);
  });

  test("blocks entirely outside the span are not drawn", () => {
    const list = rows();
    list[1].blocks.push(
      block({ id: "before", start: T0 - 60 * min, end: T0 - 50 * min }),
      block({ id: "after", start: T0 + 13 * 60 * min, end: T0 + 13 * 60 * min + min }),
      block({ id: "edge", start: T0 - 5 * min, end: T0 + 5 * min }),
    );
    const out = renderToStaticMarkup(
      createElement(ShotTimeline, { rows: list, span, now, mode: "full", timeZone: TZ }),
    );
    expect(out).not.toContain('data-id="before"');
    expect(out).not.toContain('data-id="after"');
    expect(out).toContain('data-id="edge"');
  });

  test("a collapsed room shows its zones' blocks on the room row", () => {
    const out = render({ collapsedRooms: new Set(["room:f2_"]), onToggleRoom: () => {} });
    expect(out).toContain('aria-expanded="false"');
    expect(out).not.toContain(">Zone 3<");
    expect(out).toContain('data-id="past"');
  });
});
