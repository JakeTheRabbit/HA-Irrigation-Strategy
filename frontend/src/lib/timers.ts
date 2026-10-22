import type { SentenceToken } from "@/components/primitives/sentence";
import type { ApplyReceipt, ReviewRow } from "@/components/review-apply";
import { formatVolume, getDisplayUnits } from "./display-units";
import { callV2, type V2Outcome } from "./parity-api";
import type { TimerPreview, TimerProgram, TimerProgramListItem, TimerWindow } from "./parity-types";
import type { TimelineBlock, TimelineRow } from "./shot-timeline";
import { clock, dayKey, dayLabel, startOfDay, wallHhmm, wallInstant } from "./time";
import type { Controller } from "./types";
import { revertEvents } from "./undo";

/** Timer programs (I3, mockup 07): a program in words, its editor's sentence, what its next 24 hours
 * water, the integration's refusals on their fields, and the receipt of a save read back from the
 * program list. Pure apart from `readPrograms` and `restoreDeleted`. */

export const TIMER_TYPE_LABEL: Record<TimerProgram["type"], string> = {
  one_off: "One-off",
  recycle: "Recycle",
  simple: "Simple",
};
export const TIMER_TYPE_HELP: Record<TimerProgram["type"], string> = {
  one_off: "One shot at a set time.",
  recycle: "Repeats on an interval inside the window.",
  simple: "A set number of shots a day, spread evenly over the window.",
};
export const WINDOW_LABEL: Record<TimerWindow["kind"], string> = {
  all: "All day",
  lights_on: "Lights on",
  lights_off: "Lights off",
  custom: "Custom",
};
export const WINDOW_HELP: Record<TimerWindow["kind"], string> = {
  all: "Around the clock.",
  lights_on: "Only while the room's lights are on.",
  lights_off: "Only while the room's lights are off.",
  custom: "Only between the From and To times.",
};

const DURATIONS = [30, 60, 90, 120, 180, 240, 300];
const EVERY = [10, 15, 20, 30, 45, 60, 90, 120];
const TIMES = [1, 2, 3, 4, 6, 8, 12, 24];
const DAY = 86_400_000;

/** "90 s", "2 min". */
export const durText = (s: number) => (s < 60 || s % 60 ? `${Number(s.toFixed(1))} s` : `${s / 60} min`);
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
/** A stored "HH:MM" on the display clock. */
function hhmmText(text: string | undefined): string {
  if (!text || getDisplayUnits().clock === "24") return text ?? "";
  const [h, m] = text.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "am" : "pm"}`;
}
const timesText = (n: number) => (n === 1 ? "Once a day" : `${n} times a day`);

/** `names`: `room` is the room's name, each zone number its label (cultivar or use). One zone keeps
 * its label: "Veg zone 2 (clones)"; zones in a run read "Veg zones 1–2". */
export function zonesText(zones: number[], names: Record<string, string>): string {
  const list = [...new Set(zones)].sort((a, b) => a - b);
  const room = names.room ? `${names.room} zone` : "Zone";
  if (!list.length) return "no zones yet";
  if (list.length === 1) return `${room} ${list[0]}${names[list[0]] ? ` (${names[list[0]]})` : ""}`;
  const run = list.every((z, i) => !i || z === list[i - 1] + 1);
  return `${room}s ${run ? `${list[0]}–${list.at(-1)}` : list.join(", ")}`;
}
function windowText(w: TimerWindow): string {
  if (w.kind === "custom") return `${hhmmText(w.from)}–${hhmmText(w.to)}`;
  return w.kind === "all" ? "all day" : w.kind === "lights_on" ? "while lights are on" : "while lights are off";
}

/** The program in words, as its card and the editor's title read it (mockup 07). */
export function timerTitle(p: TimerProgram, zoneNames: Record<string, string>, timeZone = "UTC"): string {
  const zones = zonesText(p.zones, zoneNames);
  const dur = durText(p.duration_s);
  if (p.type === "one_off") {
    const at = Date.parse(p.start_at ?? "");
    return Number.isFinite(at)
      ? `Once at ${clock(at, timeZone)} for ${dur}, ${dayLabel(at, timeZone)}, ${zones}`
      : `Once for ${dur}, ${zones}`;
  }
  const how = p.type === "simple" ? timesText(p.frequency_per_day ?? 0) : `Every ${p.interval_min} min`;
  return `${how} for ${dur}, ${windowText(p.window)}, ${zones}`;
}

const choices = (list: number[], current: number | null, label: (n: number) => string) =>
  [...new Set([...list, ...(current !== null && Number.isFinite(current) ? [current] : [])])]
    .sort((a, b) => a - b)
    .map((n) => ({ value: String(n), label: label(n) }));

/** The editor's Amount sentence. Each word starts a row on a phone and names the choices after it:
 * "Run for [2 min] every [30 min] from [08:00] to [12:00]". A one-off is "Run for [3 min] at [20:00]
 * on [Fri 23 Oct]", on the room's clock. The zones and the window are chosen beside it. */
export function timerTokens(
  draft: TimerProgram,
  set: (p: TimerProgram) => void,
  ctx: { now: number; timeZone: string },
): (string | SentenceToken)[] {
  const { now, timeZone: tz } = ctx;
  const parts: (string | SentenceToken)[] = [
    "Run for",
    {
      id: "duration_s",
      kind: "select",
      label: "Run for",
      value: String(draft.duration_s),
      options: choices(DURATIONS, draft.duration_s, durText),
      onChange: (v) => set({ ...draft, duration_s: Number(v) }),
    },
  ];
  if (draft.type === "recycle")
    parts.push("every", {
      id: "interval_min",
      kind: "select",
      label: "Every",
      value: String(draft.interval_min),
      options: choices(EVERY, draft.interval_min, (n) => `${n} min`),
      onChange: (v) => set({ ...draft, interval_min: Number(v) }),
    });
  if (draft.type === "simple")
    parts.push(",", {
      id: "frequency_per_day",
      kind: "select",
      label: "Times a day",
      value: String(draft.frequency_per_day),
      options: choices(TIMES, draft.frequency_per_day, timesText),
      onChange: (v) => set({ ...draft, frequency_per_day: Number(v) }),
    });
  if (draft.type === "one_off") {
    const parsed = Date.parse(draft.start_at ?? "");
    const at = Number.isFinite(parsed) ? parsed : now;
    const time = wallHhmm(at, tz);
    const today = startOfDay(now, tz);
    const days = Array.from({ length: 8 }, (_, i) => startOfDay(today + i * DAY + DAY / 2, tz));
    if (!days.some((d) => dayKey(d, tz) === dayKey(at, tz))) days.unshift(startOfDay(at, tz));
    const write = (day: number, hhmm: string) => set({ ...draft, start_at: new Date(wallInstant(day, hhmm, tz)).toISOString() });
    parts.push(
      "at",
      { id: "at", kind: "time", label: "At", value: time, onChange: (v) => write(at, v) },
      "on",
      {
        id: "day",
        kind: "select",
        label: "Day",
        value: dayKey(at, tz),
        options: days.map((d) => ({
          value: dayKey(d, tz),
          label: d === today ? "Today" : d === days[days.indexOf(today) + 1] ? "Tomorrow" : dayLabel(d, tz),
        })),
        onChange: (v) => write(days.find((d) => dayKey(d, tz) === v) ?? at, time),
      },
    );
  } else if (draft.window.kind === "custom") {
    const edit = (key: "from" | "to") => (v: string) => set({ ...draft, window: { ...draft.window, [key]: v } });
    parts.push(
      "from",
      { id: "from", kind: "time", label: "From", value: draft.window.from ?? "08:00", onChange: edit("from") },
      "to",
      { id: "to", kind: "time", label: "To", value: draft.window.to ?? "12:00", onChange: edit("to") },
    );
  }
  return parts;
}

const minutesText = (s: number) => (s < 60 ? `${Number(s.toFixed(1))} s` : `${Number((s / 60).toFixed(1))} min`);
const litres = (l: number) => formatVolume(l, Math.min(2, (String(l).split(".")[1] ?? "").length));
const known = (rate: number | undefined): rate is number => typeof rate === "number" && Number.isFinite(rate) && rate > 0;

/** What a preview waters: "8 shots · 16 min · about 1.2 L per plant." and, where a zone's shots pass
 * its daily limit, "Stops after shot 10: daily limit 1.5 L per plant." Litres only with every zone's
 * own rate (litres a plant a second, from its drippers); without one, shots and minutes only.
 * `dailyMaxL` is litres a plant: one for every zone, or each zone's. */
export function consequence(
  preview: TimerPreview,
  lPerPlantPerSecond: Record<number, number>,
  dailyMaxL: number | null | Record<number, number | null>,
): string {
  if (!preview.shots) return "No shots in the next 24 hours.";
  const head = `${plural(preview.shots, "shot")} · ${minutesText(preview.total_s)}`;
  const zones = [...new Set(preview.preview.map((s) => s.zone))].sort((a, b) => a - b);
  if (!zones.every((z) => known(lPerPlantPerSecond[z]))) return `${head}.`;
  const ordered = [...preview.preview].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const perPlant = Math.max(
    ...zones.map((z) => ordered.filter((s) => s.zone === z).reduce((sum, s) => sum + s.duration_s * lPerPlantPerSecond[z], 0)),
  );
  let text = `${head} · about ${formatVolume(perPlant, 1)} per plant.`;
  for (const zone of zones) {
    const limit = typeof dailyMaxL === "number" || dailyMaxL === null ? dailyMaxL : (dailyMaxL[zone] ?? null);
    if (limit === null || !Number.isFinite(limit)) continue;
    const stop = stopAfter(ordered.filter((s) => s.zone === zone), lPerPlantPerSecond[zone], limit);
    if (stop === null) continue;
    const who = zones.length > 1 ? `Zone ${zone} stops` : "Stops";
    text += ` ${stop ? `${who} after shot ${stop}` : `${who} before its first shot`}: daily limit ${litres(limit)} per plant.`;
    break;
  }
  return text;
}
/** How many of a zone's shots fit under its limit; null when all do. */
function stopAfter(shots: { duration_s: number }[], rate: number, limit: number): number | null {
  let sum = 0;
  for (const [i, s] of shots.entries()) {
    sum += s.duration_s * rate;
    if (sum > limit + 1e-9) return i;
  }
  return null;
}

/** The integration's refusal of a program, on the field it is about (timers.validate's words). */
export function fieldErrors(error: string | null): { field: string; message: string }[] {
  if (!error) return [];
  const message = error[0].toUpperCase() + error.slice(1);
  const rules: [RegExp, string][] = [
    [/^end must be after start/i, "end"],
    [/^(pick at least one zone|zones must|zone \d+ is)/i, "zones"],
    [/^duration/i, "duration_s"],
    [/^interval/i, "interval_min"],
    [/^frequency/i, "frequency_per_day"],
    [/^start_at/i, "start_at"],
    [/^(window|time must|sync time)/i, "window"],
    [/^type must/i, "type"],
  ];
  return [{ field: rules.find(([re]) => re.test(error))?.[1] ?? "program", message }];
}

/** "today 14:30", "tomorrow 08:00", else "Tue 20:00", on the room's clock. */
export function nextShotWords(at: string, now: number, tz: string): string {
  const ms = Date.parse(at);
  const day = dayKey(ms, tz);
  const word =
    day === dayKey(now, tz)
      ? "today"
      : day === dayKey(startOfDay(now, tz) + DAY + DAY / 2, tz)
        ? "tomorrow"
        : dayLabel(ms, tz).split(" ")[0];
  return `${word} ${clock(ms, tz)}`;
}
/** A program card's status line. */
export function programStatus(p: TimerProgramListItem, now: number, tz: string): string {
  if (!p.active) return "Draft · not running";
  return p.next_at ? `On · next shot ${nextShotWords(p.next_at, now, tz)}` : "On · no shot in the next 8 days";
}

/** As the integration refuses a save: a zone already in another running program. */
export function sharedZoneError(draft: TimerProgram, programs: TimerProgram[]): string | null {
  if (!draft.active) return null;
  for (const zone of draft.zones) {
    const owner = programs.find((p) => p.id !== draft.id && p.active && p.zones.includes(zone));
    if (owner) return `Zone ${zone} is already in timer '${owner.name}'`;
  }
  return null;
}

/** The program as the integration stores it: the fields its type uses, nothing listed. */
export function programBody(p: TimerProgram): Record<string, unknown> {
  return {
    ...(p.id ? { id: p.id } : {}),
    name: p.name,
    type: p.type,
    zones: [...p.zones],
    duration_s: p.duration_s,
    active: p.active,
    ...(p.type === "one_off" ? { start_at: p.start_at } : { window: p.window }),
    ...(p.type === "recycle" ? { interval_min: p.interval_min } : {}),
    ...(p.type === "simple" ? { frequency_per_day: p.frequency_per_day } : {}),
    ...(p.type === "recycle" && p.sync_time ? { sync_time: p.sync_time } : {}),
  };
}

type Field = "type" | "zones" | "duration_s" | "interval_min" | "frequency_per_day" | "start_at" | "window" | "active";
const FIELD_LABEL: Record<Field, string> = {
  type: "Type",
  zones: "Zones",
  duration_s: "Run for",
  interval_min: "Every",
  frequency_per_day: "Times a day",
  start_at: "Starts",
  window: "When",
  active: "Running",
};
function fieldsOf(p: TimerProgram): Field[] {
  return [
    "type",
    "zones",
    "duration_s",
    ...(p.type === "recycle" ? (["interval_min"] as const) : []),
    ...(p.type === "simple" ? (["frequency_per_day"] as const) : []),
    ...(p.type === "one_off" ? (["start_at"] as const) : (["window"] as const)),
    "active",
  ];
}
function fieldKey(field: Field, p: TimerProgram): string {
  if (field === "zones") return JSON.stringify([...p.zones].sort((a, b) => a - b));
  if (field === "start_at") return String(Date.parse(p.start_at ?? ""));
  if (field === "window")
    return JSON.stringify(p.window.kind === "custom" ? [p.window.kind, p.window.from, p.window.to] : [p.window.kind]);
  return JSON.stringify(p[field] ?? null);
}
function fieldText(field: Field, p: TimerProgram, names: Record<string, string>, tz: string): string {
  const v = p[field];
  if (v === null || v === undefined) return "None";
  if (field === "type") return TIMER_TYPE_LABEL[p.type];
  if (field === "zones") return p.zones.length ? zonesText(p.zones, names) : "None";
  if (field === "duration_s") return durText(p.duration_s);
  if (field === "interval_min") return `${p.interval_min} min`;
  if (field === "frequency_per_day") return timesText(p.frequency_per_day ?? 0);
  if (field === "active") return p.active ? "On" : "Off";
  if (field === "window") return p.window.kind === "custom" ? windowText(p.window) : WINDOW_LABEL[p.window.kind];
  const at = Date.parse(p.start_at ?? "");
  return Number.isFinite(at) ? `${dayLabel(at, tz)} ${clock(at, tz)}` : String(p.start_at);
}
/** Whether two programs hold the same settings (ids and listing aside). */
export const sameProgram = (a: TimerProgram, b: TimerProgram) =>
  fieldsOf(a).length === fieldsOf(b).length && fieldsOf(a).every((f) => fieldKey(f, a) === fieldKey(f, b));

/** The edit as Review & apply rows: each changed field, before and after. A new program is one
 * row. `revert(field)` takes a row's edit back out of the draft ("program": the whole draft). */
export function programRows(
  saved: TimerProgram | null,
  draft: TimerProgram,
  names: Record<string, string>,
  tz: string,
  revert: (field: string) => void,
): ReviewRow[] {
  if (!saved)
    return [{ id: "program", label: "New program", before: "None", after: timerTitle(draft, names, tz), undo: () => revert("program") }];
  return fieldsOf(draft)
    .filter((f) => fieldKey(f, saved) !== fieldKey(f, draft))
    .map((f) => ({
      id: f,
      label: FIELD_LABEL[f],
      before: fieldText(f, saved, names, tz),
      after: fieldText(f, draft, names, tz),
      undo: () => revert(f),
    }));
}

/** A save's receipt, row by row, from the program list read after it: a row is written and read
 * back only when the listed program holds its field as sent; one that does not is "still" what the
 * list holds. A list that could not be read claims nothing. `sent` carries the saved id. */
export function readBackReceipt(
  rows: ReviewRow[],
  sent: TimerProgram,
  read: { kind: "ok"; programs: TimerProgram[] } | { kind: "error" },
  ctx: { names: Record<string, string>; tz: string },
  now: number,
  eventIds: string[],
): ApplyReceipt {
  if (read.kind !== "ok")
    return { at: now, ok: false, unconfirmed: true, failed: rows.map((r) => ({ id: r.id, holds: r.before })), summary: "", eventIds };
  const held = read.programs.find((p) => p.id === sent.id);
  const failed = rows
    .filter((r) =>
      !held ? true : r.id === "program" ? !sameProgram(held, sent) : fieldKey(r.id as Field, held) !== fieldKey(r.id as Field, sent),
    )
    .map((r) => ({
      id: r.id,
      holds: !held ? "None" : r.id === "program" ? timerTitle(held, ctx.names, ctx.tz) : fieldText(r.id as Field, held, ctx.names, ctx.tz),
    }));
  const bad = new Set(failed.map((f) => f.id));
  return {
    at: now,
    ok: !failed.length,
    failed,
    summary: rows
      .filter((r) => !bad.has(r.id))
      .map((r) => `${r.label} ${r.before} → ${r.after}`)
      .join(" · "),
    eventIds,
  };
}

/** One room's programs and revision. */
export async function readPrograms(
  controller: Pick<Controller, "operator">,
  roomId: string,
): Promise<V2Outcome<{ programs: TimerProgramListItem[]; revision: number | null; error?: string | null }>> {
  return callV2(controller, "timer_program_list", { room_id: roomId });
}

/** Undo of a delete: the Journal puts the programs back (`revertEvents`). A deleted program comes
 * back under a new id (`renewed`); answers the id it has now. */
export async function restoreDeleted(
  controller: Pick<Controller, "operator">,
  eventIds: string[],
  oldId: string,
): Promise<string> {
  const results = await revertEvents(controller, eventIds);
  return results.flatMap((r) => r.renewed ?? []).find((r) => r.old_id === oldId)?.id ?? oldId;
}

export type IrrigationMode = "steering" | "timer" | "off";
/** The line under a zone's irrigation mode: what a switch does before it is applied (`pending`),
 * else what the mode leaves the zone with now. */
export function modeNote(o: {
  zone: number;
  mode: string;
  hasProbe: boolean;
  covered: boolean;
  pending: boolean;
}): string | null {
  if (o.pending) {
    if (o.mode === "timer")
      return `Zone ${o.zone} stops steering and waters only by its timers.${o.covered ? "" : " No running program covers it, so it will not be watered."}`;
    if (o.mode === "off") return `Zone ${o.zone} gets no shots at all, rescue shots included.`;
    return `Zone ${o.zone} steers by its probe again; its timers stop watering it.`;
  }
  if (o.mode === "timer" && !o.covered) return "No running program covers this zone: it will not be watered.";
  if (o.mode === "off") return "Off: no shots at all, rescue shots included.";
  if (!o.hasProbe) return "No probe, so steering is not offered.";
  return null;
}

/** The preview as ShotTimeline rows, one per zone of the draft. A shot past the zone's daily limit
 * is drawn blocked; on a pump that runs one zone at a time, each later zone's shot waits for the
 * one before (drawn waiting, that much later). */
export function previewRows(
  shots: TimerPreview["preview"],
  o: {
    roomName: string;
    zones: { zone: number; label: string; sublabel: string }[];
    rates: Record<number, number>;
    dailyMax: Record<number, number | null>;
    oneAtATime: boolean;
    lights: { on: number; off: number }[];
  },
): TimelineRow[] {
  const order = o.zones.map((z) => z.zone);
  return o.zones.map(({ zone, label, sublabel }) => {
    const rate = known(o.rates[zone]) ? o.rates[zone] : null;
    const limit = o.dailyMax[zone] ?? null;
    let sum = 0;
    const blocks = shots
      .filter((s) => s.zone === zone)
      .sort((a, b) => Date.parse(a.at) - Date.parse(b.at))
      .map((s): TimelineBlock => {
        const wait = o.oneAtATime ? order.indexOf(zone) * s.duration_s : 0;
        const start = Date.parse(s.at) + wait * 1000;
        const perPlant = rate === null ? null : s.duration_s * rate;
        sum += perPlant ?? 0;
        const blocked = perPlant !== null && limit !== null && sum > limit + 1e-9;
        return {
          id: `${zone}:${s.at}`,
          glyph: blocked ? "failed" : wait ? "queued" : "planned",
          start,
          end: start + s.duration_s * 1000,
          requestedAt: wait ? Date.parse(s.at) : null,
          pumpWaitS: wait || null,
          litres: null,
          meteredL: null,
          litresPerPlant: perPlant,
          reason: blocked ? "Blocked by the daily limit" : wait ? "Waits for the pump" : "This program",
          phase: null,
          vwcBefore: null,
          vwcExpected: null,
          source: "timer",
          code: null,
          eventId: null,
          skippable: false,
          zone,
          roomId: o.roomName,
          running: false,
          skipped: false,
        };
      });
    return { key: `preview:${zone}`, roomId: o.roomName, zone, label, sublabel, blocks, lights: o.lights };
  });
}

/** The Daily max card: the zone nearest its limit, its watering minutes in the preview against the
 * minutes its limit allows (null without its rate or limit). */
export function dailyUse(
  shots: TimerPreview["preview"],
  zones: number[],
  rates: Record<number, number>,
  dailyMax: Record<number, number | null>,
): { zone: number; usedMin: number; allowedMin: number | null } | null {
  const rows = zones.map((zone) => {
    const usedMin = shots.filter((s) => s.zone === zone).reduce((sum, s) => sum + s.duration_s, 0) / 60;
    const limit = dailyMax[zone] ?? null;
    const allowedMin = known(rates[zone]) && limit !== null && Number.isFinite(limit) ? limit / rates[zone] / 60 : null;
    return { zone, usedMin, allowedMin };
  });
  if (!rows.length) return null;
  const share = (r: (typeof rows)[number]) => (r.allowedMin ? r.usedMin / r.allowedMin : -1);
  return rows.reduce((a, b) => (share(b) > share(a) ? b : a));
}

/** A new program's start: 2 min every 30 min while the lights are on, on these zones. */
export const newProgram = (roomId: string, zones: number[], n: number): TimerProgram => ({
  id: "",
  room_id: roomId,
  name: `Timer ${n}`,
  zones,
  type: "recycle",
  duration_s: 120,
  interval_min: 30,
  frequency_per_day: null,
  start_at: null,
  window: { kind: "lights_on" },
  active: true,
});
/** "Most mother rooms use 2 min every 2 h during lights-on." */
export const motherRoomProgram = (roomId: string, zones: number[]): TimerProgram => ({
  ...newProgram(roomId, zones, 1),
  name: "Mother room timer",
  interval_min: 120,
});
