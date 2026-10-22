import type { DemoHandler } from "../parity-demo";
import type { CsEvent, TimelineBlock, TimelineGetData, TimelineSummary } from "../parity-types";
import { demoId, demoJournal, demoLightsOn } from "./journal";

/** The demo's watering timeline (I1), folded from the demo Journal as the integration folds it:
 * the same rooms, zones and shot times. On top of the Journal's shots, holds, queue and alerts it
 * adds what a grow-day also has: the shot running now (Room A zone 3's timer) and each zone's next
 * two planned shots (Room A zone 3's from its timer, the first after a 12 min wait for the pump;
 * the others are the engine's expectations), all skippable until skipped. The Journal's aborted
 * shot (Room A zone 1, CS-304) is the failed block. A skip lasts the page's life; its Undo
 * (history_revert of the skip's event) puts the shot back. */

const MIN = 60_000;
const HOUR = 60 * MIN;
const ROOM_LIGHTS = 12 * HOUR;
const iso = (ms: number) => new Date(ms).toISOString();
const local = (ms: number) => new Date(ms).toLocaleDateString("sv");

/** Planned slots skipped this session ("room|zone|ms"), and the skip event that did it. */
const skipped = new Set<string>();
const skipEvents = new Map<string, string>();
const slot = (roomId: string, zone: number, at: number) => `${roomId}|${zone}|${at}`;

const blank = (id: string, at: number): TimelineBlock => ({
  id, kind: "shot", status: "done", start: iso(at), end: iso(at), litres: null, metered_l: null, reason: null,
  phase: null, vwc_before: null, vwc_expected: null, requested_at: null, pump_wait_s: null, source: "engine",
  code: null, event_id: null, skippable: false,
});

/** Every block of a room the demo knows, by zone: past ones from the Journal, then now's. */
function roomBlocks(roomId: string, now: number): Map<number, TimelineBlock[]> {
  const events = demoJournal(roomId, now);
  const rows = new Map<number, TimelineBlock[]>();
  const add = (zone: number, block: TimelineBlock) => rows.set(zone, [...(rows.get(zone) ?? []), block]);
  const closing = (e: CsEvent, kind: string) =>
    events.find((c) => c.kind === kind && c.correlation?.intent_id === e.correlation?.intent_id);
  for (const e of events) {
    if (e.zone === null) continue;
    const at = Date.parse(e.ts);
    if (e.kind === "shot.started") {
      const d = e.data;
      const done = closing(e, "shot.completed");
      const aborted = closing(e, "shot.aborted");
      const metered = done ? Number(done.data.metered_l) : null;
      add(e.zone, {
        ...blank(e.id, at),
        end: (done ?? aborted)?.ts ?? iso(at + Number(d.duration_s) * 1000),
        status: aborted ? "error" : metered !== null && metered / Number(d.commanded_l) < 0.8 ? "warning" : "done",
        code: aborted?.code ?? closing(e, "flow.reconciled")?.code ?? null,
        litres: Number(d.commanded_l), metered_l: metered, reason: String(d.reason), phase: String(d.phase),
        vwc_before: Number(d.vwc_before), vwc_expected: (d.vwc_expected as number | null) ?? null,
        requested_at: String(d.requested_at), pump_wait_s: Number(d.pump_wait_s), source: e.source.actor,
        event_id: e.id,
      });
    } else if (e.kind === "intent.held" || e.kind === "intent.queued" || e.kind === "alert.raised") {
      const kind = e.kind === "intent.held" ? "held" : e.kind === "intent.queued" ? "queued" : "alert";
      const reason = String(e.data.reason ?? e.data.title ?? e.data.guard ?? "");
      add(e.zone, { ...blank(e.id, at), kind, status: "warning", reason, code: e.code, source: e.source.actor, event_id: e.id });
    }
  }
  if (roomId === "room:") {
    // Zone 3's timer is watering now.
    const running = now - 30_000;
    add(3, {
      ...blank(demoId(running, "room::running:3"), running), end: iso(running + 60_000), litres: 1.21,
      reason: "Timer: Zone 3 day timer", phase: "P2", vwc_before: 58.1, requested_at: iso(running), pump_wait_s: 0,
      source: "timer", running: true, event_id: demoId(running, "room::running:3"),
    });
  }
  // Each zone that watered today: its next two shots on its 45 min rhythm, from 10 min ahead (the
  // same slots on every read, so a skip finds its slot again).
  const today = demoLightsOn(roomId, now);
  for (const [zone, blocks] of rows) {
    const last = blocks.filter((b) => b.kind === "shot" && !b.running && Date.parse(b.start) >= today).at(-1);
    if (!last) continue;
    const timer = last.source === "timer";
    const base = Math.floor(Date.parse(last.start) / MIN) * MIN;
    const steps = Math.max(1, Math.ceil((now + 10 * MIN - base) / (45 * MIN)));
    for (let i = 0; i < 2; i++) {
      const at = base + (steps + i) * 45 * MIN;
      const waited = roomId === "room:" && zone === 3 && i === 0 ? 720 : 0;
      const gone = skipped.has(slot(roomId, zone, at));
      blocks.push({
        ...blank(demoId(at, `planned:${roomId}:${zone}`), at), kind: "planned", status: "planned", end: iso(at + 2 * MIN),
        litres: 1.21, phase: last.phase, vwc_before: last.vwc_before, vwc_expected: last.vwc_before === null ? null : last.vwc_before + 2.2,
        reason: waited
          ? "Due 12 min earlier. Room A's pump runs one zone at a time and Zone 2's shot is on it, so this shot starts when it ends."
          : timer ? "Timer: Zone 3 day timer" : `${last.phase}: VWC will reach the re-water point`,
        requested_at: waited ? iso(at - waited * 1000) : null, pump_wait_s: waited || null,
        source: timer ? "timer" : "engine", expected: !timer, skippable: !gone, skipped: gone,
      });
    }
  }
  for (const blocks of rows.values()) blocks.sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
  return rows;
}

const roomsOf = (data: Record<string, unknown>) =>
  Array.isArray(data.rooms) && data.rooms.length ? data.rooms.map(String) : ["room:", "room:room_b_"];

function timeline(data: Record<string, unknown>, now: number): TimelineGetData {
  const start = Date.parse(String(data.start ?? "")) || now - 12 * HOUR;
  const end = Date.parse(String(data.end ?? "")) || now + 12 * HOUR;
  const zones = Array.isArray(data.zones) ? (data.zones as number[]) : null;
  const markers: Record<string, unknown>[] = [];
  const rooms = roomsOf(data).map((room_id) => {
    const on = demoLightsOn(room_id, now);
    const lights = [];
    for (let day = on - 3 * 24 * HOUR; day < end; day += 24 * HOUR)
      if (day + ROOM_LIGHTS > start) lights.push({ on: iso(day), off: iso(day + ROOM_LIGHTS) });
    const rows = [...roomBlocks(room_id, now)]
      .filter(([zone]) => !zones || zones.includes(zone))
      .sort(([a], [b]) => a - b)
      .map(([zone, blocks]) => ({
        zone,
        blocks: blocks.filter((b) => Date.parse(b.start) < end && Date.parse(b.end) >= start),
      }));
    for (const { zone, blocks } of rows)
      for (const b of blocks)
        if (b.status === "error") markers.push({ room_id, zone, t: b.start, code: b.code, block_id: b.id });
    return {
      room_id, lights, rows, pump: "switch.demo_irrigation_pump", pump_rooms: ["room:", "room:room_b_"],
      pump_load: [{ t: iso(now - HOUR), pct: 48 }, { t: iso(now), pct: 40 }], planned_source: "projection_app" as const,
    };
  });
  markers.sort((a, b) => Date.parse(String(a.t)) - Date.parse(String(b.t)));
  return { rooms, errors: { count: markers.length, markers } };
}

/** timeline_summary from the same blocks: each counted on the local day it started, planned ones
 * left out. */
function summary(data: Record<string, unknown>, now: number): TimelineSummary {
  const days = Array.isArray(data.days) ? data.days.map(String) : [local(now)];
  const rooms = roomsOf(data);
  const blocks = new Map(rooms.map((r) => [r, [...roomBlocks(r, now).values()].flat()]));
  return {
    days: days.map((date) => ({
      date,
      rooms: rooms.map((room_id) => {
        const day = (blocks.get(room_id) ?? []).filter((b) => b.kind !== "planned" && local(Date.parse(b.start)) === date);
        const count = (test: (b: TimelineBlock) => boolean) => day.filter(test).length;
        return {
          room_id,
          shots: count((b) => b.kind === "shot"),
          failed: count((b) => b.status === "error" && b.kind !== "held" && b.kind !== "queued"),
          warnings: count((b) => b.status === "warning" && b.kind !== "held" && b.kind !== "queued"),
          held: count((b) => b.kind === "held"),
          queued: count((b) => b.kind === "queued"),
        };
      }),
    })),
  };
}

export const handlers: DemoHandler[] = [
  { action: "timeline_get", answer: timeline },
  { action: "timeline_summary", answer: summary },
  {
    action: "timer_skip",
    answer: (data, now) => {
      const key = slot(String(data.room_id), Number(data.zone), Date.parse(String(data.at)));
      const eventId = demoId(now, `skip:${key}`);
      skipped.add(key);
      skipEvents.set(eventId, key);
      const at = typeof data.at === "string" ? data.at : null;
      const until = at && Number.isFinite(Date.parse(at)) ? iso(Date.parse(at) + 15 * MIN) : null;
      return {
        api: 2, ok: true, room_id: data.room_id ?? null, revision: Number(data.expected_revision ?? 1) + 1,
        readback: { status: "verified", at: iso(now) }, event_ids: [eventId],
        data: { skip: { zone: data.zone ?? null, at, until }, revision: Number(data.expected_revision ?? 1) + 1 },
      };
    },
  },
  {
    action: "history_revert",
    match: (data) => skipEvents.has(String(data.event_id)),
    answer: (data, now) => {
      skipped.delete(skipEvents.get(String(data.event_id))!);
      skipEvents.delete(String(data.event_id));
      return { reverted_event_id: data.event_id, new_event_id: demoId(now, `revert:${String(data.event_id)}`), readback: "verified" };
    },
  },
];
