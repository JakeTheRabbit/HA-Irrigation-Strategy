import { useMemo } from "react";
import { whileVisible, type LiveConnection } from "./live";
import type { CsEvent } from "./parity-types";
import type { Controller } from "./types";

/** How many live events `Controller.recentEvents` keeps. */
export const RECENT_EVENTS = 300;
const POLL_MS = 30_000;
/** A poll request that has not settled by then is given up, so the next tick can run. */
const POLL_TIMEOUT_MS = 20_000;

/** Thrown by a feed's `poll` when the integration has no `journal_query` (before 3.18). */
export class JournalMissing extends Error {}

/** The ring with `events` added: deduped on id, oldest first, the newest `limit` kept. The same
 * ring when that holds the same events. */
export function mergeEvents(ring: readonly CsEvent[], events: readonly CsEvent[], limit = RECENT_EVENTS): readonly CsEvent[] {
  const byId = new Map(ring.map((event) => [event.id, event]));
  for (const event of events) if (!byId.has(event.id)) byId.set(event.id, event);
  if (byId.size === ring.length) return ring;
  const next = [...byId.values()]
    .sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
    .slice(-limit);
  return next.length === ring.length && next.every((event, i) => event.id === ring[i].id) ? ring : next;
}

function withTimeout<T>(request: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return Promise.race([
    request,
    new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error("The Journal read timed out.")), ms);
    }),
  ]).finally(() => clearTimeout(timer));
}

/** Every room's new Journal events as they happen: `crop_steering/subscribe` over Home Assistant's
 * websocket (`resubscribe: false`: the feed resubscribes itself on each `ready`, so it sees the
 * answer), then one catch-up `journal_query` per room for what the socket missed. Without a
 * connection, or on an integration that lacks the command (`unknown_command`, 3.17), each room's
 * `journal_query` from its own last event every 30 s while the page is visible (and at once when a
 * room's last event is older than the feed); while
 * the journal is `unavailable` the same, retrying the subscription each time. `unauthorized`, or no
 * `journal_query` while polling, stops it; a subscribed feed just skips its catch-ups.
 * `since` holds each room's last event time across feeds; a room without one starts at `start`
 * (default now). Returns stop. */
export function startEventFeed(opts: {
  connection: LiveConnection | null;
  rooms: string[];
  poll: (roomId: string, since: string) => Promise<CsEvent[]>;
  onEvents: (e: CsEvent[]) => void;
  visible: () => boolean;
  since?: Map<string, string>;
  start?: string;
}): () => void {
  const { connection, rooms, poll, onEvents, visible } = opts;
  const since = opts.since ?? new Map<string, string>();
  const now = new Date().toISOString();
  const start = opts.start ?? now;
  for (const room of rooms) if (!since.has(room)) since.set(room, start);
  let stopped = false;
  let token = 0;
  let cancel: (() => unknown) | undefined;
  let stopPoll: (() => void) | undefined;
  let retry = false;
  let busy = false;
  /** A read asked for while one ran: null, or whether it was a catch-up. */
  let again: boolean | null = null;
  let noJournal = false;
  const end = (unsubscribe: (() => unknown) | undefined) =>
    void Promise.resolve()
      .then(unsubscribe)
      .catch(() => {});
  const deliver = (events: CsEvent[]) => {
    for (const event of events) {
      const last = since.get(event.room_id);
      if (last && rooms.includes(event.room_id) && Date.parse(event.ts) > Date.parse(last))
        since.set(event.room_id, event.ts);
    }
    if (events.length) onEvents(events);
  };
  /** `catchUp`: the one read after a subscribe, which runs hidden or not (a timer read waits). */
  const pollRooms = async (catchUp = false): Promise<void> => {
    if (stopped || noJournal || (!catchUp && !visible())) return;
    if (busy) return void (again = !!again || catchUp);
    busy = true;
    try {
      for (const room of rooms) {
        let events: CsEvent[];
        try {
          events = await withTimeout(poll(room, since.get(room)!), POLL_TIMEOUT_MS);
        } catch (error) {
          if (!(error instanceof JournalMissing)) continue;
          if (cancel) return void (noJournal = true);
          return stop();
        }
        if (stopped) return;
        deliver(events);
      }
    } finally {
      busy = false;
      if (again !== null) {
        const next = again;
        again = null;
        void pollRooms(next);
      }
    }
  };
  const startPolling = () => {
    if (stopPoll) return;
    stopPoll = whileVisible(() => {
      void pollRooms();
      if (retry) subscribe();
    }, POLL_MS);
    // A room whose last event is older than this feed (carried over, or the demo's epoch) is read
    // at once; a fresh one has nothing to read yet.
    if (rooms.some((room) => Date.parse(since.get(room)!) < Date.parse(now))) void pollRooms();
  };
  const subscribe = () => {
    if (!connection) return startPolling();
    const mine = ++token;
    const current = () => mine === token && !stopped;
    connection
      .subscribeMessage<CsEvent>(
        (event) => {
          if (current()) deliver([event]);
        },
        { type: "crop_steering/subscribe", rooms },
        { resubscribe: false },
      )
      .then(
        (unsubscribe) => {
          if (!current()) return end(unsubscribe);
          cancel = unsubscribe;
          retry = false;
          stopPoll?.();
          stopPoll = undefined;
          void pollRooms(true);
        },
        (error: unknown) => {
          if (!current()) return;
          const code = (error as { code?: unknown } | null)?.code;
          if (code === "unauthorized") return stop();
          retry = code !== "unknown_command";
          startPolling();
        },
      );
  };
  const resubscribe = () => {
    if (stopped) return;
    end(cancel);
    cancel = undefined;
    subscribe();
  };
  const stop = () => {
    stopped = true;
    token++;
    stopPoll?.();
    stopPoll = undefined;
    connection?.removeEventListener?.("ready", resubscribe);
    end(cancel);
    cancel = undefined;
  };
  connection?.addEventListener?.("ready", resubscribe);
  subscribe();
  return stop;
}

/** The ring's events that `filter` keeps. */
export const selectEvents = (ring: readonly CsEvent[], filter: (e: CsEvent) => boolean): CsEvent[] => ring.filter(filter);

/** The controller's recent live events that `filter` keeps (memoise `filter`). History views call
 * `pagedQuery` themselves. */
export function useCsEvents(controller: Controller, filter: (e: CsEvent) => boolean): CsEvent[] {
  return useMemo(() => selectEvents(controller.recentEvents, filter), [controller.recentEvents, filter]);
}
