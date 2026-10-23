/** History › Water & flow: did the water each shot asked for reach the plants? Read from the
 * controller's `flow.reconciled {ratio, commanded_l, metered_l}` events (backend Task 26), its CS-319
 * alerts (water through a meter with no shot in flight) and the meter's recorded readings. */
import type { Span, TimelineRow } from "./day-timeline";
import type { CsEvent } from "./parity-types";
import { clock, dayKey, startOfDay } from "./time";

/** The controller's own bounds (crop_steering_engine/flow.py LOW, HIGH). */
export const FLOW_LOW = 0.8;
export const FLOW_HIGH = 1.2;
const EPS = 1e-9;

export type FlowVerdict = "on_target" | "low" | "high" | "no_meter";
export interface FlowShot {
  at: number;
  askedL: number;
  meteredL: number;
}
export interface ZoneFlow {
  last3Pct: number | null;
  todayPct: number | null;
  shots: FlowShot[];
  verdict: FlowVerdict;
}

const finite = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;
const mean = (values: number[]) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : null);

/** The zone's reconciled shots, oldest first: each with a finite ratio and both litres, at its
 * shot's start where the events hold its `shot.started` (same intent id), else as reconciled. */
function reconciled(events: CsEvent[], zone: number) {
  const starts = new Map(
    events
      .filter((e) => e.kind === "shot.started" && e.zone === zone && e.correlation?.intent_id)
      .map((e) => [e.correlation!.intent_id, Date.parse(e.ts)]),
  );
  return events
    .filter((e) => e.kind === "flow.reconciled" && e.zone === zone)
    .map((e) => ({
      at: starts.get(e.correlation?.intent_id) ?? Date.parse(e.ts),
      ratio: finite(e.data.ratio),
      askedL: finite(e.data.commanded_l),
      meteredL: finite(e.data.metered_l),
    }))
    .filter((r): r is { at: number; ratio: number; askedL: number; meteredL: number } =>
      r.ratio !== null && r.askedL !== null && r.meteredL !== null && Number.isFinite(r.at),
    )
    .sort((a, b) => a.at - b.at);
}

/** A zone's metered against asked: the mean of `ratio × 100` over its last three reconciled shots
 * (any day) and over those from `dayStart` on, and those shots. The verdict reads the last three
 * against the controller's 0.8 and 1.2; `no_meter` when nothing was reconciled. */
export function zoneFlow(events: CsEvent[], zone: number, dayStart = -Infinity): ZoneFlow {
  const all = reconciled(events, zone);
  if (!all.length) return { last3Pct: null, todayPct: null, shots: [], verdict: "no_meter" };
  const today = all.filter((r) => r.at >= dayStart);
  const last3 = mean(all.slice(-3).map((r) => r.ratio))!;
  const todayMean = mean(today.map((r) => r.ratio));
  return {
    last3Pct: last3 * 100,
    todayPct: todayMean === null ? null : todayMean * 100,
    shots: today.map(({ at, askedL, meteredL }) => ({ at, askedL, meteredL })),
    verdict: last3 < FLOW_LOW - EPS ? "low" : last3 > FLOW_HIGH + EPS ? "high" : "on_target",
  };
}

/** When the zone's water dropped: the first of its last unbroken run of shots under 0.8; null when
 * its last shot was not short. */
export function blockedSince(shots: FlowShot[]): number | null {
  let since: number | null = null;
  for (const shot of shots) since = shot.askedL > 0 && shot.meteredL / shot.askedL < FLOW_LOW - EPS ? (since ?? shot.at) : null;
  return since;
}

/** The zone's mean ratio for each of the `days` calendar days up to `now`'s, oldest first; null for
 * a day with no reconciled shot. */
export function dailyRatios(events: CsEvent[], zone: number, now: number, tz: string, days = 7): (number | null)[] {
  const keys: string[] = [];
  let day = startOfDay(now, tz);
  for (let i = 0; i < days; i++) {
    keys.unshift(dayKey(day, tz));
    day = startOfDay(day - 12 * 3_600_000, tz);
  }
  const byDay = new Map<string, number[]>();
  for (const r of reconciled(events, zone)) {
    const key = dayKey(r.at, tz);
    byDay.set(key, [...(byDay.get(key) ?? []), r.ratio]);
  }
  return keys.map((key) => mean(byDay.get(key) ?? []));
}

/** Today's mean against the days before it: more than 10 points down or up, else steady. */
export function trendWord(days: (number | null)[]): "steady" | "fell today" | "rose today" | "today only" | null {
  const today = days.at(-1);
  if (today === null || today === undefined) return null;
  const before = mean(days.slice(0, -1).filter((d): d is number => d !== null));
  if (before === null) return "today only";
  return today < before - 0.1 ? "fell today" : today > before + 0.1 ? "rose today" : "steady";
}

/** A CS-319 the controller raised about `meter` (controller.py _watch_meters: key `flow_idle_<meter>`,
 * `entity_id` the meter). */
function meterAlert(e: CsEvent, meter: string): boolean {
  return e.kind === "alert.raised" && e.code === "CS-319" && (e.data.entity_id === meter || e.data.key === `flow_idle_${meter}`);
}

/** Each CS-319 the controller raised about `meter` (water through it with every valve shut). `litres`
 * only when the alert carries it: the controller's alert says it in words, not as a number. */
export function leakIncidents(alerts: CsEvent[], meter: string): { at: number; title: string; litres: number | null }[] {
  return alerts
    .filter((e) => meterAlert(e, meter))
    .map((e) => ({ at: Date.parse(e.ts), title: String(e.data.title ?? "Water through the meter with no zone on"), litres: finite(e.data.litres) }))
    .sort((a, b) => a.at - b.at);
}

const LITRES: Record<string, number> = { L: 1, l: 1, "m³": 1000, gal: 3.785411784 };
/** A meter's reading in litres, as the controller converts it (flow.to_litres); null for an unknown
 * unit or a reading that is not a number. */
export function meterLitres(state: string, unit: unknown): number | null {
  const factor = typeof unit === "string" ? LITRES[unit] : undefined;
  const value = state.trim() === "" ? NaN : Number(state);
  return factor === undefined || !Number.isFinite(value) ? null : value * factor;
}

/** The spans each valve was on, from its recorded states. */
function onSpans(rows: TimelineRow[], end: number): Span[] {
  const spans: Span[] = [];
  let since: number | null = null;
  for (const row of [...rows].sort((a, b) => a.time - b.time)) {
    if (row.state === "on" && since === null) since = row.time;
    else if (row.state !== "on" && since !== null) spans.push({ start: since, end: row.time }), (since = null);
  }
  if (since !== null) spans.push({ start: since, end });
  return spans;
}

/** Leak check over [start, end): when any valve was open, when the meter counted water, and the
 * litres it counted with every valve shut over the time they were shut. A rise is a shot's water
 * when its valve was open at any time between the reading before and that reading: so a shot's
 * water runs up to the meter's first reading after the valve shut, however late the meter reports.
 * `litres` is null when the meter's unit is not one the controller reads. */
export function leakWatch(valves: TimelineRow[][], meter: TimelineRow[], unit: unknown, start: number, end: number) {
  const valveOpen = valves
    .flatMap((rows) => onSpans(rows, end))
    .filter((s) => s.end > start && s.start < end)
    .sort((a, b) => a.start - b.start);
  const busy = (from: number, to: number) => valveOpen.some((s) => s.start <= to && s.end > from);
  const readings = [...meter]
    .sort((a, b) => a.time - b.time)
    .map((row) => ({ time: row.time, litres: meterLitres(row.state, unit) }))
    .filter((r): r is { time: number; litres: number } => r.litres !== null && r.time < end);
  const meterFlow: Span[] = [];
  let litres = 0;
  for (let i = 1; i < readings.length; i++) {
    const rise = readings[i].litres - readings[i - 1].litres;
    if (rise <= 0) continue; // still, or the meter reset
    if (readings[i].time >= start) meterFlow.push({ start: Math.max(start, readings[i - 1].time), end: readings[i].time });
    if (readings[i].time >= start && !busy(readings[i - 1].time, readings[i].time)) litres += rise;
  }
  const from = Math.max(start, readings[0]?.time ?? end);
  let watchedMs = Math.max(0, end - from);
  let covered = from;
  for (const s of valveOpen) {
    const a = Math.max(covered, s.start),
      b = Math.min(end, s.end);
    if (b > a) watchedMs -= b - a;
    covered = Math.max(covered, b);
  }
  return { valveOpen, meterFlow, litres: meterLitres("0", unit) === null ? null : litres, watchedMs };
}

/** The flow meter that counts a zone's water, as the controller looks it up (controller.py
 * _flow_meter, _pump_meter): the zone's own in the supply's `zone_meters`, else the `flow_meter` of
 * the pump the room names. A room that names no pump reads no pump's meter. */
export function zoneMeter(
  supply: { zone_meters?: unknown; irrigation_pumps?: unknown } | null | undefined,
  roomId: string,
  zone: number,
  pump: unknown,
): string | null {
  const meters = (supply?.zone_meters as Record<string, Record<string, unknown>> | undefined)?.[roomId];
  const own = meters?.[String(zone)];
  if (typeof own === "string" && own) return own;
  const pumps = Array.isArray(supply?.irrigation_pumps) ? (supply.irrigation_pumps as { entity_id?: unknown; flow_meter?: unknown }[]) : [];
  const served = pump ? pumps.find((p) => p?.entity_id === pump) : undefined;
  return typeof served?.flow_meter === "string" && served.flow_meter ? served.flow_meter : null;
}

/** The room's pump in the supply's `irrigation_pumps`: the one the room names, else the only one. */
export function roomPump<P extends object>(pumps: unknown, pump: unknown): (P & { entity_id?: unknown }) | undefined {
  const list = Array.isArray(pumps) ? (pumps as (P & { entity_id?: unknown })[]) : [];
  return list.find((p) => p.entity_id === pump) ?? (list.length === 1 ? list[0] : undefined);
}

/** Whether another room's zone reads `meter` (its own in `zone_meters`, or its pump's): the
 * controller then holds CS-319 while any of those rooms has a shot in flight (_watch_meters), and
 * this room's valves alone cannot tell its shots from a leak. */
export function meterShared(
  supply: { zone_meters?: unknown; irrigation_pumps?: unknown } | null | undefined,
  rooms: { id: string; zones: number[]; pump: unknown }[],
  roomId: string,
  meter: string,
): boolean {
  return meterRooms(supply, rooms, meter).some((id) => id !== roomId);
}

/** Every room whose zones read `meter`. The controller journals the meter's CS-319 under the first
 * of them (_watch_meters `readers[0]`), which may be another room than the one on screen. */
export function meterRooms(
  supply: { zone_meters?: unknown; irrigation_pumps?: unknown } | null | undefined,
  rooms: { id: string; zones: number[]; pump: unknown }[],
  meter: string,
): string[] {
  return rooms.filter((room) => room.zones.some((zone) => zoneMeter(supply, room.id, zone, room.pump) === meter)).map((room) => room.id);
}

/** The controller's CS-319 bound (controller.py METER_IDLE_L): a rise above it, with no shot in flight. */
export const METER_IDLE_L = 0.5;
/** Watched less than this today, a quiet meter is not yet a clear day. */
export const MIN_WATCH_MS = 3_600_000;

export type LeakVerdict = "flowing" | "clear" | "no_alert" | "unwatched";
/** The leak check's word for today. Only the controller's CS-319 says `flowing`: the page's own
 * count is shown as litres, never as the verdict. On a meter another room reads too (`shared`),
 * only the alert tells: `no_alert`. `unwatched` when a zone on the meter has no recorded valve
 * (`blind`: its shots cannot be told from a leak) or nothing was read in litres. `clear` when the
 * page counted no more than METER_IDLE_L with every valve shut over at least MIN_WATCH_MS, else
 * `no_alert`. */
export function leakVerdict(
  watch: { litres: number | null; watchedMs: number },
  alertsToday: number,
  shared: boolean,
  blind = false,
): LeakVerdict {
  if (alertsToday > 0) return "flowing";
  if (shared) return "no_alert";
  if (blind || watch.litres === null || watch.watchedMs <= 0) return "unwatched";
  return watch.litres > METER_IDLE_L || watch.watchedMs < MIN_WATCH_MS ? "no_alert" : "clear";
}

/** The id of the newest of the room's `flow.reconciled`, or of `meter`'s CS-319 from any room, in the
 * live feed, or null: a new one re-reads the page's Journal, so a shot's bar shows once the meter has
 * counted it, and a leak alert shows as it is raised. */
export function latestFlowEvent(events: readonly CsEvent[], roomId: string, meter: string): string | null {
  return events.filter((e) => (e.room_id === roomId && e.kind === "flow.reconciled") || meterAlert(e, meter)).at(-1)?.id ?? null;
}

/** The test shot the controller runs (controller.py, Test Shot): the zone's Manual shot length cut to
 * whole seconds when it reads MIN_SHOT_S (5 s) or more, else TEST_SHOT_S (10 s). */
export function testShotSeconds(state: string | undefined): number {
  const asked = Number(state);
  return state !== undefined && state.trim() !== "" && Number.isFinite(asked) && asked >= 5 ? Math.trunc(asked) : 10;
}

/** A lane's spans in words, for its screen-reader label: "3 times, 06:00 to 15:40". */
export function spanWords(spans: Span[], tz: string): string {
  if (!spans.length) return "none today";
  const times = spans.length === 1 ? "once" : `${spans.length} times`;
  return `${times}, ${clock(spans[0].start, tz)} to ${clock(Math.max(...spans.map((s) => s.end)), tz)}`;
}

/** The integration's published supply (backend Task 11): its attributes carry `zone_meters` and
 * `irrigation_pumps` as `supply_get` answers them. */
export const SUPPLY_SENSOR = "sensor.crop_steering_supply_config";
