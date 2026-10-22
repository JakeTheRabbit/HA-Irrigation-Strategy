import { useMemo } from "react";
import { whileVisible, type LiveConnection } from "./live";
import type { CsEvent } from "./parity-types";
import type { Controller } from "./types";

/** How many live events `Controller.recentEvents` keeps. */
export const RECENT_EVENTS = 300;
const POLL_MS = 30_000;

/** Thrown by a feed's `poll` when the integration has no `journal_query` (before 3.18): the feed
 * stops quietly. */
export class JournalMissing extends Error {}

/** The ring with `events` added: deduped on id, oldest first, the newest `limit` kept. The same
 * ring when nothing is new. */
export function mergeEvents(ring: readonly CsEvent[], events: readonly CsEvent[], limit = RECENT_EVENTS): readonly CsEvent[] {
  const byId = new Map(ring.map((event) => [event.id, event]));
  for (const event of events) if (!byId.has(event.id)) byId.set(event.id, event);
  if (byId.size === ring.length) return ring;
  return [...byId.values()]
    .sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
    .slice(-limit);
}

/** Every room's new Journal events as they happen: `crop_steering/subscribe` over Home Assistant's
 * websocket, resubscribed once on each reconnect. Without a connection, or on an integration that
 * lacks the command (`unknown_command`, 3.17), each room's `journal_query` from its own last event
 * every 30 s while the page is visible; while the journal is `unavailable` the same, retrying the
 * subscription each time. `unauthorized`, or no `journal_query` either, stops it. Returns stop. */
export function startEventFeed(opts: {
  connection: LiveConnection | null;
  rooms: string[];
  poll: (roomId: string, since: string) => Promise<CsEvent[]>;
  onEvents: (e: CsEvent[]) => void;
  visible: () => boolean;
}): () => void {
  const { connection, rooms, poll, onEvents, visible } = opts;
  const now = new Date().toISOString();
  const since = new Map(rooms.map((room) => [room, now]));
  let stopped = false;
  let token = 0;
  let cancel: (() => unknown) | undefined;
  let stopPoll: (() => void) | undefined;
  let retry = false;
  let busy = false;
  const end = (unsubscribe: (() => unknown) | undefined) =>
    void Promise.resolve()
      .then(unsubscribe)
      .catch(() => {});
  const deliver = (events: CsEvent[]) => {
    for (const event of events) {
      const last = since.get(event.room_id);
      if (last && Date.parse(event.ts) > Date.parse(last)) since.set(event.room_id, event.ts);
    }
    if (events.length) onEvents(events);
  };
  const pollRooms = async () => {
    if (busy || stopped || !visible()) return;
    busy = true;
    try {
      for (const room of rooms) {
        let events: CsEvent[];
        try {
          events = await poll(room, since.get(room)!);
        } catch (error) {
          if (error instanceof JournalMissing) return stop();
          continue;
        }
        if (stopped) return;
        deliver(events);
      }
    } finally {
      busy = false;
    }
  };
  const startPolling = () => {
    stopPoll ??= whileVisible(() => {
      void pollRooms();
      if (retry) subscribe();
    }, POLL_MS);
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
      )
      .then(
        (unsubscribe) => {
          if (!current()) return end(unsubscribe);
          cancel = unsubscribe;
          retry = false;
          stopPoll?.();
          stopPoll = undefined;
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
