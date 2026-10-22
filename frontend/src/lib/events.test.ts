import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { JournalMissing, mergeEvents, RECENT_EVENTS, selectEvents, startEventFeed } from "./events";
import type { LiveConnection } from "./live";
import type { CsEvent } from "./parity-types";
import { ControllerStore } from "./use-controller";

const START = "2026-10-22T00:00:00.000Z";
const ev = (n: number, room = "room:f2_", ts = new Date(Date.parse(START) + n * 1000).toISOString()): CsEvent => ({
  v: 1, id: String(n).padStart(26, "0"), ts, room_id: room, zone: 1, kind: "shot.completed",
  outcome: "ok", code: null, source: { actor: "engine" }, data: {},
});

/** A Home Assistant websocket whose `crop_steering/subscribe` answers with `answer()`. */
function fakeConnection(answer: () => Promise<() => unknown>) {
  const ready = new Set<() => void>();
  const sent: { callback: (event: CsEvent) => void; message: Record<string, unknown> }[] = [];
  const connection: LiveConnection = {
    subscribeMessage: vi.fn((callback, message) => {
      sent.push({ callback: callback as (event: CsEvent) => void, message });
      return answer();
    }) as LiveConnection["subscribeMessage"],
    addEventListener: (_event, callback) => ready.add(callback),
    removeEventListener: (_event, callback) => ready.delete(callback),
  };
  return { connection, sent, reconnect: () => ready.forEach((callback) => callback()), ready };
}
const refuse = (code: string) => () => Promise.reject({ code, message: code });

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(Date.parse(START));
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("startEventFeed", () => {
  test("uses crop_steering/subscribe and polls only on unknown_command", async () => {
    const unsubscribe = vi.fn();
    const live = fakeConnection(() => Promise.resolve(unsubscribe));
    const poll = vi.fn().mockResolvedValue([]);
    const onEvents = vi.fn();
    const stop = startEventFeed({ connection: live.connection, rooms: ["room:f2_", "room:f1_"], poll, onEvents, visible: () => true });
    await vi.advanceTimersByTimeAsync(0);
    expect(live.sent.map((s) => s.message)).toEqual([{ type: "crop_steering/subscribe", rooms: ["room:f2_", "room:f1_"] }]);
    live.sent[0].callback(ev(1));
    expect(onEvents).toHaveBeenCalledWith([ev(1)]);
    await vi.advanceTimersByTimeAsync(90_000);
    expect(poll).not.toHaveBeenCalled();
    stop();
    await vi.advanceTimersByTimeAsync(0);
    expect(unsubscribe).toHaveBeenCalledTimes(1);
    live.sent[0].callback(ev(2));
    expect(onEvents).toHaveBeenCalledTimes(1);

    // An older integration (3.17) has no subscribe command: poll every 30 s, never resubscribe.
    const old = fakeConnection(refuse("unknown_command"));
    const stopOld = startEventFeed({ connection: old.connection, rooms: ["room:f2_"], poll, onEvents, visible: () => true });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(poll).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(poll).toHaveBeenCalledTimes(2);
    expect(old.sent).toHaveLength(1);
    stopOld();
  });

  test("polls and retries the subscription while the journal is unavailable", async () => {
    let answer: () => Promise<() => unknown> = refuse("unavailable");
    const live = fakeConnection(() => answer());
    const poll = vi.fn().mockResolvedValue([]);
    const stop = startEventFeed({ connection: live.connection, rooms: ["room:f2_"], poll, onEvents: vi.fn(), visible: () => true });
    await vi.advanceTimersByTimeAsync(0);
    answer = () => Promise.resolve(vi.fn());
    await vi.advanceTimersByTimeAsync(30_000);
    expect(poll).toHaveBeenCalledTimes(1);
    expect(live.sent).toHaveLength(2);
    // Subscribed: the poll stops.
    await vi.advanceTimersByTimeAsync(90_000);
    expect(poll).toHaveBeenCalledTimes(1);
    expect(live.sent).toHaveLength(2);
    stop();
  });

  test("stops on unauthorized", async () => {
    const live = fakeConnection(refuse("unauthorized"));
    const poll = vi.fn().mockResolvedValue([]);
    startEventFeed({ connection: live.connection, rooms: ["room:f2_"], poll, onEvents: vi.fn(), visible: () => true });
    await vi.advanceTimersByTimeAsync(0);
    expect(live.ready.size).toBe(0);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(poll).not.toHaveBeenCalled();
    expect(live.sent).toHaveLength(1);
  });

  test("resubscribes once on reconnect and ends the old subscription", async () => {
    const unsubscribes = [vi.fn(), vi.fn()];
    let n = 0;
    const live = fakeConnection(() => Promise.resolve(unsubscribes[n++]));
    const onEvents = vi.fn();
    const stop = startEventFeed({ connection: live.connection, rooms: ["room:f2_"], poll: vi.fn(), onEvents, visible: () => true });
    await vi.advanceTimersByTimeAsync(0);
    live.reconnect();
    await vi.advanceTimersByTimeAsync(0);
    expect(live.sent).toHaveLength(2);
    expect(unsubscribes[0]).toHaveBeenCalledTimes(1);
    expect(unsubscribes[1]).not.toHaveBeenCalled();
    live.sent[0].callback(ev(1));
    live.sent[1].callback(ev(2));
    expect(onEvents.mock.calls).toEqual([[[ev(2)]]]);
    stop();
    await vi.advanceTimersByTimeAsync(0);
    expect(unsubscribes[1]).toHaveBeenCalledTimes(1);
    expect(live.ready.size).toBe(0);
  });

  test("polls each room with room_id and its own last ts", async () => {
    const poll = vi.fn(async (room: string, _since: string) => (room === "room:f2_" && poll.mock.calls.length === 1 ? [ev(5)] : []));
    const onEvents = vi.fn();
    const stop = startEventFeed({ connection: null, rooms: ["room:f2_", "room:f1_"], poll, onEvents, visible: () => true });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(poll.mock.calls).toEqual([["room:f2_", START], ["room:f1_", START]]);
    expect(onEvents).toHaveBeenCalledWith([ev(5)]);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(poll.mock.calls.slice(2)).toEqual([["room:f2_", ev(5).ts], ["room:f1_", START]]);
    stop();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(poll).toHaveBeenCalledTimes(4);
  });

  test("does not poll while hidden and resumes when visible", async () => {
    let shown = false;
    const poll = vi.fn().mockResolvedValue([]);
    const stop = startEventFeed({ connection: null, rooms: ["room:f2_"], poll, onEvents: vi.fn(), visible: () => shown });
    await vi.advanceTimersByTimeAsync(90_000);
    expect(poll).not.toHaveBeenCalled();
    shown = true;
    await vi.advanceTimersByTimeAsync(30_000);
    expect(poll).toHaveBeenCalledTimes(1);
    stop();
  });

  test("stops when journal_query is missing", async () => {
    const poll = vi.fn().mockRejectedValue(new JournalMissing());
    const onEvents = vi.fn();
    startEventFeed({ connection: null, rooms: ["room:f2_", "room:f1_"], poll, onEvents, visible: () => true });
    await vi.advanceTimersByTimeAsync(150_000);
    expect(poll).toHaveBeenCalledTimes(1);
    expect(onEvents).not.toHaveBeenCalled();
  });

  test("keeps polling after another error", async () => {
    const poll = vi.fn().mockRejectedValueOnce(new Error("timed out")).mockResolvedValue([]);
    const stop = startEventFeed({ connection: null, rooms: ["room:f2_"], poll, onEvents: vi.fn(), visible: () => true });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(poll).toHaveBeenCalledTimes(2);
    stop();
  });
});

describe("the ring", () => {
  test("dedupes on id", () => {
    const ring = mergeEvents([ev(1), ev(2)], [ev(2), ev(3), ev(3)]);
    expect(ring.map((e) => e.id)).toEqual([ev(1).id, ev(2).id, ev(3).id]);
    expect(mergeEvents(ring, [ev(1)])).toBe(ring);
  });
  test("keeps the newest 300, newest last", () => {
    const many = Array.from({ length: 320 }, (_, i) => ev(320 - i));
    const ring = mergeEvents([], many);
    expect(ring).toHaveLength(RECENT_EVENTS);
    expect(ring[0].id).toBe(ev(21).id);
    expect(ring.at(-1)!.id).toBe(ev(320).id);
  });
  test("useCsEvents applies its filter", () => {
    const ring = [ev(1, "room:f2_"), ev(2, "room:f1_"), ev(3, "room:f2_")];
    expect(selectEvents(ring, (e) => e.room_id === "room:f2_").map((e) => e.id)).toEqual([ev(1).id, ev(3).id]);
  });
});

describe("controller feed", () => {
  test("polls every room's journal and fills recentEvents until stopped", async () => {
    const store = new ControllerStore(true, "?demo=1");
    const rooms = store.getSnapshot().rooms.map((room) => room.id);
    const operator = vi.spyOn(store, "operator").mockImplementation(async (_action, data) =>
      ({ api: 2, ok: true, data: { events: data?.room_id === rooms[0] ? [ev(1, rooms[0])] : [], cursor: null } }) as never);
    const stop = store.start();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(operator.mock.calls.filter(([action]) => action === "journal_query").map(([, data]) => data)).toEqual(
      rooms.map((room_id) => ({ room_id, since: START, limit: 500, api: 2 })),
    );
    expect(store.getSnapshot().recentEvents).toEqual([ev(1, rooms[0])]);
    stop();
    operator.mockClear();
    await vi.advanceTimersByTimeAsync(90_000);
    expect(operator.mock.calls.filter(([action]) => action === "journal_query")).toEqual([]);
  });
  test("an older integration stops the poll quietly", async () => {
    const store = new ControllerStore(true, "?demo=1&backend=3.17");
    const operator = vi.spyOn(store, "operator");
    const stop = store.start();
    await vi.advanceTimersByTimeAsync(150_000);
    expect(operator.mock.calls.filter(([action]) => action === "journal_query")).toHaveLength(1);
    expect(store.getSnapshot().recentEvents).toEqual([]);
    stop();
  });
});
