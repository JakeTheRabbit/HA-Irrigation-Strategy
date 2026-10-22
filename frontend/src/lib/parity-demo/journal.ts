import type { DemoHandler } from "../parity-demo";
import type { CsEvent, JournalActor, JournalOutcome, JournalPage } from "../parity-types";

/** The demo's Journal: a deterministic grow-day per demo room, yesterday's and today's, from its
 * lights-on. Room A plays F2 ("Flower · bulk", P2, 7/6/7 shots a day), Room B plays F1 ("Flower ·
 * stretch", P1, 4/4/0 shots, zone 3 paused). Only events at or before `now` are answered. */
const ROOMS: Record<string, { lightsOn: number; phase: "P1" | "P2"; shots: number[]; low?: number }> = {
  "room:": { lightsOn: 10, phase: "P2", shots: [7, 6, 7], low: 2 },
  "room:room_b_": { lightsOn: 8, phase: "P1", shots: [4, 4, 0] },
};
const MIN = 60_000;
const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/** A ULID-shaped id: the 48-bit time, then 80 bits from the key (stable for the same row). */
export function demoId(ms: number, key: string): string {
  let time = "";
  for (let t = ms, i = 0; i < 10; i++, t = Math.floor(t / 32)) time = CROCKFORD[t % 32] + time;
  let hash = 2166136261;
  let tail = "";
  for (let i = 0; i < 16; i++) {
    for (const ch of key + i) hash = Math.imul(hash ^ ch.charCodeAt(0), 16777619) >>> 0;
    tail += CROCKFORD[hash % 32];
  }
  return time + tail;
}

/** Local wall time with the viewer's offset, as the integration writes it. */
function iso(ms: number): string {
  const d = new Date(ms);
  const offset = -d.getTimezoneOffset();
  const pad = (n: number, w = 2) => String(Math.abs(n)).padStart(w, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:` +
    `${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}${offset < 0 ? "-" : "+"}${pad(Math.trunc(offset / 60))}:${pad(offset % 60)}`
  );
}

function lightsOnBefore(now: number, hour: number): number {
  const d = new Date(now);
  d.setHours(hour, 0, 0, 0);
  if (d.getTime() > now) d.setDate(d.getDate() - 1);
  return d.getTime();
}

function roomDay(roomId: string, on: number): CsEvent[] {
  const room = ROOMS[roomId];
  const out: CsEvent[] = [];
  const add = (
    at: number,
    kind: string,
    data: Record<string, unknown>,
    opts: { zone?: number | null; actor?: JournalActor; outcome?: JournalOutcome; code?: string | null; detail?: string; intent?: string } = {},
  ) => {
    const id = demoId(at, `${roomId}:${kind}:${opts.zone ?? ""}:${at}`);
    out.push({
      v: 1,
      id,
      ts: iso(at),
      room_id: roomId,
      zone: opts.zone ?? null,
      kind,
      outcome: opts.outcome ?? "ok",
      code: opts.code ?? null,
      source: { actor: opts.actor ?? "engine", detail: opts.detail ?? null, user_id: opts.actor === "manual" ? "demo-user" : null },
      correlation: opts.intent ? { intent_id: opts.intent } : {},
      data,
    });
    return id;
  };
  const p2At = on + 180 * MIN;
  add(on - 230 * MIN, "stock.refilled", { tank: "part_a", litres: 20, level_l: 20 }, { actor: "manual" });
  add(on - 120 * MIN, "config.changed", { store: "setup", section: "zones", old: { plant_count: 39 }, new: { plant_count: 40 }, diff: [{ path: "zones.1.plant_count", old: 39, new: 40 }] }, { actor: "manual" });
  add(on - 60 * MIN, "calibration.committed", { probe: "feed_ph", slope_pct: 98.4, offset: 0.06, verdict: "pass", applied: true }, { actor: "manual" });
  add(on, "phase.changed", { from: "P3", to: "P0", how: "lights on" });
  add(on + 60 * MIN, "phase.changed", { from: "P0", to: "P1", how: "dryback reached" });
  if (room.phase === "P2") add(p2At, "phase.changed", { from: "P1", to: "P2", how: "field capacity reached" });
  add(on + 90 * MIN, "ai.judgement", { judge: "dryback", label: "Dryback on target", action: "advice", power: "advise", evidence: "Overnight dryback 18.2 % against a 15–20 % band." }, { actor: "ai", zone: 1 });
  add(on + 240 * MIN, "ai.outcome", { what: "Dryback came back to target.", good: true }, { actor: "ai", zone: 1 });
  add(on + 120 * MIN, "target.changed", { key: "p2_vwc_threshold", scope: "zone:1", layer: "base", old: 58, new: 57.5, expires: null, reason: "Auto setpoints: dryback ran short", expected: "Longer dryback by tomorrow", entity_id: "number.crop_steering_zone_1_p2_vwc_threshold" }, { actor: "learner", zone: 1 });
  add(on + 200 * MIN, "target.changed", { key: "p1_target_vwc", scope: "room", layer: "base", old: 65, new: 66, expires: null, reason: null, expected: null, entity_id: "number.crop_steering_p1_target_vwc" }, { actor: "manual" });
  add(on + 105 * MIN, "intent.held", { reason: "making a batch", guard: "dosing_hold", would: "P1 ramp shot" }, { zone: 3, outcome: "held" });
  add(on + 150 * MIN, "alert.raised", { key: "tank_low", title: "Feed tank below 30 %" }, { code: "CS-901", outcome: "held" });
  add(on + 180 * MIN, "alert.cleared", { key: "tank_low" });
  if (roomId === "room:")
    add(on + 270 * MIN, "alert.raised", { key: "pore_ec_high", title: "Pore EC 6.6 is over the 4.5–6.0 band", entity_id: "sensor.crop_steering_ec_zone_2" }, { zone: 2, code: "CS-205", outcome: "partial" });
  else
    add(on + 270 * MIN, "alert.raised", { key: "probe_silent", title: "Back sensor silent 3 h, left out of the reading" }, { zone: 2, code: "CS-406", outcome: "partial" });
  room.shots.forEach((count, index) => {
    const zone = index + 1;
    if (!count) add(on + 70 * MIN, "intent.held", { reason: "zone disabled", guard: "zone_paused", would: "P1 ramp shot" }, { zone, outcome: "held" });
    for (let shot = 0; shot < count; shot++) {
      const requested = on + 70 * MIN + shot * 45 * MIN + index * 4 * MIN;
      const queued = zone === 2 && shot === 1;
      const wait = queued ? 64 : 0;
      const start = requested + wait * 1000;
      const phase = start >= p2At && room.phase === "P2" ? "P2" : "P1";
      const commanded = 1.21;
      const metered = zone === room.low && shot === 2 ? 0.85 : 1.18;
      const vwc = 56.4 + shot * 0.6 + index * 0.3;
      const intent = demoId(requested, `${roomId}:intent:${zone}:${shot}`);
      if (queued) add(requested, "intent.queued", { position: 1, priority: "steering", requested_at: iso(requested), guard: "pump_capacity" }, { zone, outcome: "queued", intent });
      const reason = phase === "P1" ? `P1 ramp shot ${shot + 1}` : "P2 top-up: VWC under threshold";
      add(start, "shot.started", { phase, kind: phase === "P1" ? "p1_ramp" : "p2_topup", reason, size_pct: 3, duration_s: 60, commanded_l: commanded, vwc_before: vwc, vwc_expected: phase === "P1" ? vwc + 1.8 : null, requested_at: iso(requested), pump_wait_s: wait }, { zone, intent, detail: reason });
      add(start + 61_000, "shot.completed", { elapsed_s: 61, commanded_l: commanded, metered_l: metered, vwc_before: vwc, ec_before: 4.8 + index * 0.4 }, { zone, intent, detail: reason });
      const ratio = metered / commanded;
      add(start + 62_000, "flow.reconciled", { ratio, commanded_l: commanded, metered_l: metered }, { zone, intent, outcome: ratio < 0.8 ? "partial" : "ok", code: ratio < 0.8 ? "CS-318" : null });
    }
  });
  return out;
}

const tsMs = (e: CsEvent) => Date.parse(e.ts);

/** Yesterday's and today's demo events for one room, ordered and numbered. */
export function demoJournal(roomId: string, now: number): CsEvent[] {
  const room = ROOMS[roomId];
  if (!room) return [];
  const today = lightsOnBefore(now, room.lightsOn);
  const events = [...roomDay(roomId, today - 86_400_000), ...roomDay(roomId, today)].sort(
    (a, b) => tsMs(a) - tsMs(b) || a.id.localeCompare(b.id),
  );
  events.forEach((e, i) => (e.seq = i + 1));
  return events.filter((e) => tsMs(e) <= now);
}

/** `journal_query`, by room, `since`/`until` instants, kinds, zones, actor and cursor. */
export function journalQuery(data: Record<string, unknown>, now: number): JournalPage {
  const since = Date.parse(String(data.since ?? ""));
  const until = data.until == null ? Infinity : Date.parse(String(data.until));
  const kinds = Array.isArray(data.kinds) ? (data.kinds as string[]) : null;
  const zones = Array.isArray(data.zones) ? (data.zones as number[]) : null;
  const limit = Math.min(500, Math.max(1, Number(data.limit) || 500));
  const [cursorMs, cursorSeq] = typeof data.cursor === "string" ? data.cursor.split(":").map(Number) : [-Infinity, 0];
  const match = demoJournal(String(data.room_id ?? ""), now).filter((e) => {
    const t = tsMs(e);
    return (
      (!Number.isFinite(since) || t >= since) &&
      t < until &&
      (!kinds || kinds.includes(e.kind)) &&
      (!zones || (e.zone !== null && zones.includes(e.zone))) &&
      (!data.actor || e.source.actor === data.actor) &&
      (t > cursorMs || (t === cursorMs && (e.seq ?? 0) > cursorSeq))
    );
  });
  const events = match.slice(0, limit);
  const last = events[events.length - 1];
  return { events, cursor: match.length > limit && last ? `${tsMs(last)}:${last.seq}` : null };
}

export const handlers: DemoHandler[] = [{ action: "journal_query", answer: journalQuery }];
