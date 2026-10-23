import { formatEc } from "./display-units";
import { facilityView, type FacilityRoom, type FacilityZone, type ZoneSensor } from "./facility-view";
import { gauge, type GaugeModel } from "./hmi";
import type { CsEvent } from "./parity-types";
import { stageArc, stageNow } from "./stage-arc";
import { clock, dayKey, dayLabel, startOfDay } from "./time";
import type { Controller, States } from "./types";
import { plantAmount } from "./water-view";

/** The Room page (mockup 03): the room's zones as rows, each with its water against the room's
 * median, its gauges against their targets, its sensors with their trouble in place, and who
 * paused it. Pure over one controller snapshot. */

/** A sensor of the zone, and when it has gone silent: since when and what the zone does without it. */
export type RoomSensor = ZoneSensor & {
  /** "Front", without the room's and zone's names. */
  short: string;
  silent: { since: string; text: string } | null;
};
export interface RoomZoneRow {
  zone: number;
  /** Water per plant today (mL) and the room's median over the zones watered today. */
  drink: { ml: number; median: number } | null;
  gauges: GaugeModel[];
  sensors: RoomSensor[];
  paused: { by: string | null; at: number; why: string | null } | null;
  /** The zone as the All rooms page reads it. */
  view: FacilityZone;
  /** The zone's open problem, unless one of its sensors already says it. */
  problem: string | null;
}
export interface RoomView {
  room: FacilityRoom;
  rows: RoomZoneRow[];
  /** Where the grow is on its stage arc: the stage now and its last day ("Stretch ends day 21"). */
  stageEnd: { name: string; day: number } | null;
}

/** The Home Assistant person (`person.*`) whose `user_id` is this user's, by name; else null. */
export function personName(states: States, userId: string | null): string | null {
  if (!userId) return null;
  const person = Object.values(states).find(
    (entity) => entity.entity_id.startsWith("person.") && entity.attributes.user_id === userId,
  );
  if (!person) return null;
  const name = person.attributes.friendly_name;
  return typeof name === "string" && name.trim() ? name.trim() : null;
}

const median = (values: number[]) => {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};
const amount = (ml: number) => {
  const { value, unit, digits } = plantAmount(ml);
  return `${Number(value.toFixed(digits))} ${unit}`;
};

/** "+1 mL vs median 160 mL", "−2 mL vs median 160 mL"; a zone without water today says so. */
export function drinkDelta(drink: { ml: number; median: number }): string {
  if (drink.ml <= 0) return "Not watered today";
  const delta = Math.round(drink.ml) - Math.round(drink.median);
  return `${delta > 0 ? "+" : delta < 0 ? "−" : "±"}${amount(Math.abs(delta))} vs median ${amount(drink.median)}`;
}

/** The sensor's own name in its zone's row: "Room B Zone 1 front" reads "Front". */
export function sensorShortName(name: string, context: string[]): string {
  let short = name;
  for (const word of context)
    if (short.toLowerCase().startsWith(word.toLowerCase())) short = short.slice(word.length).trim();
  return short ? short.charAt(0).toUpperCase() + short.slice(1) : "Sensor";
}

/** A silent sensor's card: "silent 3 h" and "Last heard 11:08. Left out: the zone reads the front
 * sensor only." The zone's other sensors that report are the ones it still reads. */
function silence(sensor: ZoneSensor, others: RoomSensor[], timeZone: string, now: number) {
  if (sensor.health !== "stale") return null;
  const heard = Math.max(
    ...[sensor.vwc?.reported, sensor.ec?.reported].filter((t): t is number => typeof t === "number"),
  );
  const since = /^Silent (.+?)(,|$)/.exec(sensor.text)?.[1];
  const leftOut = [sensor.vwc, sensor.ec].some((probe) => probe?.used === false);
  const reading = others
    .filter((other) => other.health === "ok")
    .map((other) => other.short.toLowerCase());
  const parts = [
    Number.isFinite(heard) ? `Last heard ${when(heard, timeZone, now)}.` : "Not heard from.",
    leftOut &&
      (reading.length
        ? `Left out: the zone reads the ${reading.join(" and ")} sensor${reading.length > 1 ? "s" : ""} only.`
        : "Left out: the zone has no other sensor reading."),
  ].filter(Boolean);
  return { since: since ? `silent ${since}` : "silent", text: parts.join(" ") };
}

/** The day of `at` as words: "" today, "yesterday", else "Thu 22 Oct". */
function dayWords(at: number, timeZone: string, now: number) {
  const day = dayKey(at, timeZone);
  if (day === dayKey(now, timeZone)) return "";
  if (day === dayKey(startOfDay(now, timeZone) - 1, timeZone)) return "yesterday";
  return dayLabel(at, timeZone);
}
/** "09:52" today, "yesterday 09:52", else "Thu 22 Oct 09:52". */
function when(at: number, timeZone: string, now: number) {
  const day = dayWords(at, timeZone, now);
  return `${day ? `${day} ` : ""}${clock(at, timeZone)}`;
}

/** "Paused by Ben at 09:52 (slab change).", "Paused at 09:52.", "Paused yesterday at 07:52." */
export function pausedText(
  paused: { by: string | null; at: number; why: string | null },
  timeZone: string,
  now: number,
): string {
  const day = dayWords(paused.at, timeZone, now);
  const at = `${day === "yesterday" ? "yesterday " : day ? `on ${day} ` : ""}at ${clock(paused.at, timeZone)}`;
  return `Paused${paused.by ? ` by ${paused.by}` : ""} ${at}${paused.why ? ` (${paused.why})` : ""}.`;
}

/** The switch's own change and the Journal's record of it are the same moment, give or take. */
const SAME_CHANGE_MS = 120_000;
/** The Journal event that switched the zone off: a config or target change of its enable switch. */
function switchedOff(event: CsEvent, zone: number, entityId: string | null) {
  if (event.zone !== zone || (event.kind !== "config.changed" && event.kind !== "target.changed"))
    return false;
  const data = event.data;
  if (entityId && data.entity_id === entityId) return true;
  const diff = Array.isArray(data.diff) ? (data.diff as { path?: unknown; new?: unknown }[]) : [];
  return (
    data.key === `zone_${zone}_enabled` ||
    diff.some((row) => typeof row?.path === "string" && /\.enabled$/.test(row.path) && row.new === false)
  );
}
/** Who paused the zone, when and why: the Journal's newest change of its switch while it agrees with
 * the switch's own last change; else only when the switch changed. */
function pausedBy(controller: Controller, view: FacilityZone, now: number): RoomZoneRow["paused"] {
  const { zone } = view;
  if (zone.enabled !== false) return null;
  const entity = zone.enabledEntity ? controller.states[zone.enabledEntity] : undefined;
  const changed = Date.parse(entity?.last_changed ?? "");
  const event = [...controller.recentEvents]
    .filter(
      (e) =>
        e.room_id === controller.roomId &&
        Date.parse(e.ts) <= now &&
        switchedOff(e, zone.id, zone.enabledEntity),
    )
    .sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts))[0];
  const at = event ? Date.parse(event.ts) : NaN;
  if (event && (!Number.isFinite(changed) || at >= changed - SAME_CHANGE_MS)) {
    const why = event.data.reason;
    return {
      by: personName(controller.states, event.source.user_id ?? null),
      at,
      why: typeof why === "string" && why.trim() ? why.trim() : null,
    };
  }
  return Number.isFinite(changed) ? { by: null, at: changed, why: null } : null;
}

/** The selected room for its page: the All rooms reading of it, its zone rows, and its stage's end. */
export function roomView(controller: Controller, now: number): RoomView | null {
  const tz = controller.timeZone;
  const format = {
    clock: (time: number) => clock(time, tz),
    number: (value: number, digits = 1) => String(Number(value.toFixed(digits))),
    perPlant: amount,
  };
  const room = facilityView(controller, format, now).find((item) => item.room.id === controller.roomId);
  if (!room) return null;
  const arc = room.growDay ? stageNow(stageArc(room.growDay.of ?? undefined), room.growDay.day, now) : null;
  const stage = {
    poreEc: room.stage?.poreEc ?? arc?.stage.poreEc ?? null,
    dryback: room.stage?.drybackPoints ?? arc?.stage.drybackPoints ?? null,
  };
  const watered = room.zones
    .map((z) => z.mlPerPlant)
    .filter((ml): ml is number => ml !== null && ml > 0);
  const middle = watered.length ? median(watered) : null;
  const rows = room.zones.map((view): RoomZoneRow => {
    const { zone } = view;
    const context = [room.room.name, zone.name];
    const sensors: RoomSensor[] = view.sensors.map((s) => ({
      ...s,
      short: sensorShortName(s.name, context),
      silent: null,
    }));
    for (const sensor of sensors)
      sensor.silent = silence(
        sensor,
        sensors.filter((other) => other !== sensor),
        tz,
        now,
      );
    // An open alert about one of the zone's sensors is said on that sensor.
    const told = sensors.some(
      (s) => s.health !== "ok" && view.problem?.toLowerCase().startsWith(`${s.short.toLowerCase()} sensor`),
    );
    const ecDigits = 1;
    return {
      zone: zone.id,
      drink:
        view.mlPerPlant === null || middle === null
          ? null
          : { ml: view.mlPerPlant, median: middle },
      gauges: [
        // The re-water point to the peak target; outside it is a problem only while the zone
        // holds it (P2). It ramps up to it in P1 and dries back from it overnight.
        gauge({
          label: "VWC",
          value: zone.vwc.value,
          unit: "%",
          band: view.rewater !== null && view.target !== null ? [view.rewater, view.target] : null,
          tolerance: zone.phase === "P2" ? 2 : Number.POSITIVE_INFINITY,
          quality: zone.vwc.value === null ? "no reading" : undefined,
        }),
        gauge({
          label: "Dryback",
          value: view.drybackPoints,
          unit: " pt",
          band: stage.dryback,
        }),
        gauge({
          label: "Pore EC",
          value: zone.ec.value,
          unit: "",
          digits: ecDigits,
          band: stage.poreEc,
          points: "mS/cm",
        }),
      ],
      sensors,
      paused: pausedBy(controller, view, now),
      view,
      problem: told ? null : view.problem,
    };
  });
  return {
    room,
    rows,
    stageEnd: arc && arc.next ? { name: stageShortName(arc.stage.name), day: arc.stage.last } : null,
  };
}

/** The arc's stage by its short name: "flower setting (stretch)" reads "Stretch". */
function stageShortName(name: string) {
  const short = /\(([^)]+)\)/.exec(name)?.[1] ?? name;
  return short.charAt(0).toUpperCase() + short.slice(1);
}

/** The zone rows of the selected room (mockup 03). */
export function roomZoneRows(controller: Controller, now: number): RoomZoneRow[] {
  return roomView(controller, now)?.rows ?? [];
}

/** A gauge's target as its label says it: "target 62–68%", "target 3.5–5.0". */
export function targetText(model: GaugeModel): string | null {
  const unit = model.unit.trim() === "%" ? "%" : "";
  const fix = (value: number) =>
    model.label === "Pore EC" ? formatEc(value, 1).replace(/\s*mS\/cm$/, "") : String(Number(value.toFixed(model.digits)));
  if (model.band) return `target ${fix(model.band[0])}–${fix(model.band[1])}${unit}`;
  if (model.target !== null) return `target ${fix(model.target)}${unit}`;
  return null;
}
