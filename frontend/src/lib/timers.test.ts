import { describe, expect, test, vi } from "vitest";
import type { SentenceToken } from "@/components/primitives/sentence";
import type { TimerProgram, TimerProgramListItem } from "./parity-types";
import { parityDemo } from "./parity-demo";
import { DEMO_TIMER_PROGRAM_ID } from "./parity-demo/journal";
import { resetDemoTimers } from "./parity-demo/timers";
import { fakeController } from "./test-helpers";
import {
  TIMER_TYPE_LABEL,
  consequence,
  fieldErrors,
  modeNote,
  nextShotWords,
  programRows,
  readBackReceipt,
  restoreDeleted,
  sharedZoneError,
  timerTitle,
  timerTokens,
} from "./timers";

const TZ = "Pacific/Auckland";
const base = (over: Partial<TimerProgram>): TimerProgram => ({
  id: "p1",
  room_id: "room:veg_",
  name: "Timer",
  zones: [1],
  type: "recycle",
  duration_s: 120,
  interval_min: 30,
  frequency_per_day: null,
  start_at: null,
  window: { kind: "all" },
  active: true,
  ...over,
});

describe("timerTitle", () => {
  test("timerTitle matches the three mockup strings", () => {
    expect(
      timerTitle(
        base({ zones: [1, 2], window: { kind: "custom", from: "08:00", to: "12:00" } }),
        { room: "Veg", 1: "mothers", 2: "clones" },
        TZ,
      ),
    ).toBe("Every 30 min for 2 min, 08:00–12:00, Veg zones 1–2");
    expect(
      timerTitle(
        base({ type: "simple", zones: [2], duration_s: 90, interval_min: null, frequency_per_day: 6, window: { kind: "lights_on" } }),
        { room: "Veg", 2: "clones" },
        TZ,
      ),
    ).toBe("6 times a day for 90 s, while lights are on, Veg zone 2 (clones)");
    expect(
      timerTitle(
        base({ type: "one_off", duration_s: 180, interval_min: null, start_at: "2026-10-23T20:00:00+13:00" }),
        { room: "Veg", 1: "mothers" },
        TZ,
      ),
    ).toBe("Once at 20:00 for 3 min, Fri 23 Oct, Veg zone 1 (mothers)");
  });
  test("zones that do not run on are listed", () => {
    expect(timerTitle(base({ zones: [3, 1] }), { room: "Room A" }, TZ)).toBe("Every 30 min for 2 min, all day, Room A zones 1, 3");
    expect(timerTitle(base({ zones: [] }), { room: "Room A" }, TZ)).toBe("Every 30 min for 2 min, all day, no zones yet");
  });
});

test("type labels map one_off/recycle/simple", () => {
  expect(TIMER_TYPE_LABEL).toEqual({ one_off: "One-off", recycle: "Recycle", simple: "Simple" });
});

describe("consequence", () => {
  const shots = (n: number, zone = 1) =>
    Array.from({ length: n }, (_, i) => ({ zone, at: new Date(Date.UTC(2026, 9, 23, 8, i * 30)).toISOString(), duration_s: 120 }));
  const preview = (list: ReturnType<typeof shots>) => ({ preview: list, shots: list.length, total_s: list.reduce((s, p) => s + p.duration_s, 0) });
  test("consequence names the daily-limit stop with consistent numbers", () => {
    // 0.00125 L a plant a second: 0.15 L a 2 min shot; 1.5 L allows 10 of the 12.
    expect(consequence(preview(shots(8)), { 1: 0.00125 }, 1.5)).toBe("8 shots · 16 min · about 1.2 L per plant.");
    expect(consequence(preview(shots(12)), { 1: 0.00125 }, 1.5)).toBe(
      "12 shots · 24 min · about 1.8 L per plant. Stops after shot 10: daily limit 1.5 L per plant.",
    );
  });
  test("without the zone's rate it gives shots and minutes only", () => {
    expect(consequence(preview(shots(12)), {}, 1.5)).toBe("12 shots · 24 min.");
    expect(consequence(preview(shots(3)), { 1: Number.NaN }, null)).toBe("3 shots · 6 min.");
  });
  test("with two zones the one that stops is named, each zone's shots counted on their own", () => {
    const both = preview([...shots(12, 1), ...shots(12, 2)]);
    expect(consequence(both, { 1: 0.00125, 2: 0.00125 }, { 1: 1.5, 2: 3 })).toBe(
      "24 shots · 48 min · about 1.8 L per plant. Zone 1 stops after shot 10: daily limit 1.5 L per plant.",
    );
  });
  test("no shots at all", () => {
    expect(consequence(preview([]), { 1: 0.00125 }, 1.5)).toBe("No shots in the next 24 hours.");
  });
});

describe("fieldErrors", () => {
  test("fieldErrors maps End must be after start to end", () => {
    expect(fieldErrors("End must be after start")).toEqual([{ field: "end", message: "End must be after start" }]);
  });
  test("other server words go to their fields, capitalised", () => {
    expect(fieldErrors("pick at least one zone")).toEqual([{ field: "zones", message: "Pick at least one zone" }]);
    expect(fieldErrors("Zone 3 is already in timer 'Day'")).toEqual([{ field: "zones", message: "Zone 3 is already in timer 'Day'" }]);
    expect(fieldErrors("interval must be at least 1 minute")[0].field).toBe("interval_min");
    expect(fieldErrors("start_at must be an ISO datetime")[0].field).toBe("start_at");
    expect(fieldErrors("Something else")).toEqual([{ field: "program", message: "Something else" }]);
    expect(fieldErrors(null)).toEqual([]);
  });
});

describe("timerTokens", () => {
  const ctx = { now: Date.parse("2026-10-23T14:10:00+13:00"), timeZone: TZ };
  const find = (parts: (string | SentenceToken)[], label: string) =>
    parts.find((p): p is SentenceToken => typeof p !== "string" && p.label === label)!;
  test("timerTokens editing interval_min updates the draft", () => {
    const set = vi.fn();
    const draft = base({ interval_min: 30 });
    const every = find(timerTokens(draft, set, ctx), "Every");
    expect(every.kind).toBe("select");
    if (every.kind === "select") {
      expect(every.value).toBe("30");
      every.onChange("45");
    }
    expect(set).toHaveBeenCalledWith({ ...draft, interval_min: 45 });
  });
  test("each text part names the controls after it (phone rows)", () => {
    const words = (p: TimerProgram) => timerTokens(p, () => {}, ctx).filter((x) => typeof x === "string");
    expect(words(base({ window: { kind: "custom", from: "08:00", to: "12:00" } }))).toEqual(["Run for", "every", "from", "to"]);
    expect(words(base({ type: "simple", frequency_per_day: 6 }))).toEqual(["Run for", ","]);
    expect(words(base({ type: "one_off", start_at: "2026-10-23T20:00:00+13:00" }))).toEqual(["Run for", "at", "on"]);
  });
  test("a one-off's day and time write start_at on the room's clock", () => {
    const set = vi.fn();
    const draft = base({ type: "one_off", start_at: "2026-10-23T20:00:00+13:00" });
    const parts = timerTokens(draft, set, ctx);
    const day = find(parts, "Day");
    if (day.kind !== "select") throw new Error("day is a select");
    expect(day.options[0]).toEqual({ value: "2026-10-23", label: "Today" });
    expect(day.options[1].label).toBe("Tomorrow");
    day.onChange("2026-10-24");
    expect(Date.parse(set.mock.calls[0][0].start_at)).toBe(Date.parse("2026-10-24T20:00:00+13:00"));
    const at = find(parts, "At");
    if (at.kind !== "time") throw new Error("at is a time");
    expect(at.value).toBe("20:00");
  });
  test("a value off the list stays choosable", () => {
    const every = find(timerTokens(base({ interval_min: 37 }), () => {}, ctx), "Every");
    expect(every.kind === "select" && every.options.some((o) => o.value === "37")).toBe(true);
  });
});

test("nextShotWords says today, tomorrow or the weekday", () => {
  const now = Date.parse("2026-10-23T14:10:00+13:00");
  expect(nextShotWords("2026-10-23T14:30:00+13:00", now, TZ)).toBe("today 14:30");
  expect(nextShotWords("2026-10-24T08:00:00+13:00", now, TZ)).toBe("tomorrow 08:00");
  expect(nextShotWords("2026-10-27T20:00:00+13:00", now, TZ)).toBe("Tue 20:00");
});

test("sharedZoneError names the active program that has the zone, as the integration does", () => {
  const others = [base({ id: "a", name: "Day", zones: [3] }), base({ id: "b", name: "Off", zones: [2], active: false })];
  expect(sharedZoneError(base({ id: "new", zones: [2, 3] }), others)).toBe("Zone 3 is already in timer 'Day'");
  expect(sharedZoneError(base({ id: "a", zones: [3] }), others)).toBeNull();
  expect(sharedZoneError(base({ id: "new", zones: [3], active: false }), others)).toBeNull();
});

describe("save receipt from the read-back", () => {
  const saved = base({ interval_min: 30 });
  const draft = base({ interval_min: 45 });
  const rows = programRows(saved, draft, { room: "Room A" }, TZ, () => {});
  const ctx = { names: { room: "Room A" }, tz: TZ };
  test("rows are the changed fields, before and after", () => {
    expect(rows.map((r) => [r.id, r.label, r.before, r.after])).toEqual([["interval_min", "Every", "30 min", "45 min"]]);
    expect(programRows(null, draft, { room: "Room A" }, TZ, () => {}).map((r) => [r.id, r.before])).toEqual([["program", "None"]]);
  });
  const listed = (p: TimerProgram): TimerProgramListItem => ({ ...p, next_at: null, zones_in_timer_mode: p.zones });
  test("Written and read back only when the listed program holds every field", () => {
    const ok = readBackReceipt(rows, draft, { kind: "ok", programs: [listed(draft)] }, ctx, 1000, ["e1"]);
    expect(ok).toMatchObject({ ok: true, failed: [], eventIds: ["e1"], summary: "Every 30 min → 45 min" });
  });
  test("a field the controller does not hold fails its row only", () => {
    const two = programRows(saved, { ...draft, duration_s: 60 }, { room: "Room A" }, TZ, () => {});
    const out = readBackReceipt(two, { ...draft, duration_s: 60 }, { kind: "ok", programs: [listed({ ...draft, duration_s: 120 })] }, ctx, 1000, []);
    expect(out.ok).toBe(false);
    expect(out.failed).toEqual([{ id: "duration_s", holds: "2 min" }]);
    expect(out.summary).toBe("Every 30 min → 45 min");
  });
  test("a list that cannot be read claims nothing", () => {
    expect(readBackReceipt(rows, draft, { kind: "error" }, ctx, 1000, ["e1"])).toMatchObject({ ok: false, unconfirmed: true });
  });
});

describe("irrigation mode", () => {
  test("a switch says what it does before it is applied", () => {
    expect(modeNote({ zone: 3, mode: "timer", hasProbe: true, covered: true, pending: true })).toBe(
      "Zone 3 stops steering and waters only by its timers.",
    );
    expect(modeNote({ zone: 3, mode: "timer", hasProbe: true, covered: false, pending: true })).toBe(
      "Zone 3 stops steering and waters only by its timers. No running program covers it, so it will not be watered.",
    );
    expect(modeNote({ zone: 2, mode: "off", hasProbe: true, covered: false, pending: true })).toBe(
      "Zone 2 gets no shots at all, rescue shots included.",
    );
  });
  test("standing notes", () => {
    expect(modeNote({ zone: 1, mode: "timer", hasProbe: false, covered: true, pending: false })).toBe("No probe, so steering is not offered.");
    expect(modeNote({ zone: 1, mode: "timer", hasProbe: true, covered: false, pending: false })).toBe(
      "No running program covers this zone: it will not be watered.",
    );
    expect(modeNote({ zone: 1, mode: "steering", hasProbe: true, covered: false, pending: false })).toBeNull();
  });
});

describe("restoreDeleted", () => {
  test("undo shows the program the integration renewed", async () => {
    const operator = vi.fn(async (action: string) =>
      action === "history_revert"
        ? { api: 2, ok: true, readback: { status: "verified", at: "x" }, event_ids: ["n"], data: { reverted_event_id: "e1", new_event_id: "n", readback: "verified", renewed: [{ name: "Day", old_id: "a", id: "b" }] } }
        : { api: 2, ok: true, readback: { status: "verified", at: "x" }, event_ids: [], data: { programs: [], revision: 3 } },
    );
    expect(await restoreDeleted(fakeController({ operator }), ["e1"], "a")).toBe("b");
  });
  test("an old program that came back under its own id keeps it", async () => {
    const operator = vi.fn(async () => ({ api: 2, ok: true, readback: { status: "verified", at: "x" }, event_ids: [], data: { reverted_event_id: "e1", new_event_id: "n", readback: "verified" } }));
    expect(await restoreDeleted(fakeController({ operator }), ["e1"], "a")).toBe("a");
  });
  test("a refusal throws its words", async () => {
    const operator = vi.fn(async () => ({ api: 2, ok: false, error: { code: "stale_revision", message: "The timer programs has changed since this change; reload the history" } }));
    await expect(restoreDeleted(fakeController({ operator }), ["e1"], "a")).rejects.toThrow(/has changed since/);
  });
});

describe("demo timers, as the integration keeps them", () => {
  const ask = (action: Parameters<typeof parityDemo>[0], data: Record<string, unknown>) =>
    parityDemo(action, data, Date.parse("2026-10-23T14:10:00+13:00"), "3.18") as Promise<Record<string, any>>;
  test("a delete is journalled; its revert brings the program back under a new id", async () => {
    resetDemoTimers();
    const gone = await ask("timer_program_delete", { room_id: "room:", expected_revision: 1, id: DEMO_TIMER_PROGRAM_ID });
    expect(gone.readback.status).toBe("none");
    expect(gone.event_ids).toHaveLength(1);
    expect((await ask("timer_program_list", { room_id: "room:" })).data.programs).toHaveLength(1);
    const back = await ask("history_revert", { event_id: gone.event_ids[0] });
    expect(back.readback.status).toBe("verified");
    const renewed = back.data.renewed[0];
    expect(renewed).toMatchObject({ old_id: DEMO_TIMER_PROGRAM_ID, name: "Zone 3 day timer" });
    const list = (await ask("timer_program_list", { room_id: "room:" })).data;
    expect(list.programs.map((p: TimerProgram) => p.id)).toContain(renewed.id);
    expect(list.revision).toBe(3);
  });
  test("a stale revision and a zone in two running programs are refused in the integration's words", async () => {
    resetDemoTimers();
    expect((await ask("timer_program_set", { room_id: "room:", expected_revision: 0, program: {} })).error).toMatchObject({ code: "stale_revision", current_revision: 1 });
    const twice = await ask("timer_program_set", {
      room_id: "room:", expected_revision: 1,
      program: { name: "Second", type: "recycle", zones: [3], duration_s: 60, interval_min: 30, window: { kind: "all" } },
    });
    expect(twice.error).toEqual({ code: "invalid", message: "Zone 3 is already in timer 'Zone 3 day timer'" });
    const end = await ask("timer_program_preview", {
      room_id: "room:", program: { type: "recycle", zones: [3], duration_s: 60, interval_min: 30, window: { kind: "custom", from: "08:00", to: "08:00" } },
    });
    expect(end.error.message).toBe("End must be after start");
  });
});
