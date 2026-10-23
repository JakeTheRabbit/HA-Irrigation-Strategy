import { dayKey } from "./time";
import { formatVolume, getDisplayUnits } from "./display-units";
import type { ParityState } from "./parity-api";
import type { CsEvent } from "./parity-types";
import type { Controller } from "./types";
import { LITRES_PER_US_GALLON } from "./units";
import { sameValue } from "./utils";

/** A room's stock tanks, as the integration's stock services return them (stock_api.py). */
export interface StockTank {
  id: string;
  name: string;
  capacity_l: number;
  level_l: number;
  /** The fixed dose per batch; a dose entity's reading takes over while it reads a number. */
  dose_ml: number;
  dose_entity: string | null;
  low_l: number;
  refilled_at: string | null;
  updated_at: string;
}
export interface StockBatch {
  at: string;
  /** fill: counted from the tank's last fill; manual: recorded by hand; pump: what a linked dosing
   * pump ran, whoever started it, drawn by the integration under its `key`; dose and batch: a
   * dose reported through stock_draw, which takes only tanks no pump is linked to (and every tank
   * before the integration watched the pumps). */
  source: "fill" | "manual" | "pump" | "dose" | "batch";
  draw_ml: Record<string, number>;
  key?: string;
}
export interface StockDocument {
  schema_version: 1;
  room_id: string;
  revision: number;
  tanks: StockTank[];
  last_batch: string | null;
  history: StockBatch[];
  /** The tank last-fill entity batches are counted from; null means batches are recorded by hand. */
  fill_entity: string | null;
  /** What one batch takes from each tank right now, in mL. */
  doses: Record<string, number>;
  low: string[];
  max_tanks: number;
  error: string | null;
}
/** What the editor sends for one tank; `id` is absent for a new one. */
export type StockTankDraft = Omit<StockTank, "id" | "refilled_at" | "updated_at"> & {
  id?: string;
};

export const stockShare = (tank: Pick<StockTank, "level_l" | "capacity_l">) =>
  tank.capacity_l > 0 ? Math.max(0, Math.min(100, (tank.level_l / tank.capacity_l) * 100)) : 0;

export const batchesLeft = (tank: Pick<StockTank, "level_l">, doseMl: number | undefined) =>
  doseMl && doseMl > 0 ? Math.floor(Math.round(tank.level_l * 1000 * 1e6) / 1e6 / doseMl) : null;

/** The tank that runs out first at today's doses, and about how many batches it has left: the
 * fewest batches, then the emptiest. Null when no tank's dose is known. */
export function nextToRunOut(
  tanks: readonly StockTank[],
  doses: Readonly<Record<string, number>>,
): { tank: StockTank; batches: number } | null {
  let next: { tank: StockTank; batches: number } | null = null;
  for (const tank of tanks) {
    const batches = batchesLeft(tank, doses[tank.id] ?? tank.dose_ml);
    if (batches === null) continue;
    if (
      !next ||
      batches < next.batches ||
      (batches === next.batches && stockShare(tank) < stockShare(next.tank))
    )
      next = { tank, batches };
  }
  return next;
}

/** The checks the integration makes (stock.py clean_tanks), so the editor can say so first. */
export function draftErrors(drafts: StockTankDraft[], max = 12): string[] {
  const errors: string[] = [];
  if (drafts.length > max) errors.push(`At most ${max} stock tanks per room.`);
  const names = new Set<string>();
  for (const tank of drafts) {
    const name = tank.name.trim();
    const label = name || "A tank";
    if (!name || name.length > 40) errors.push("Each tank needs a name of 1 to 40 characters.");
    else if (names.has(name.toLowerCase())) errors.push(`Two tanks are called ${name}.`);
    names.add(name.toLowerCase());
    if (!(tank.capacity_l >= 0.1 && tank.capacity_l <= 10000))
      errors.push(`${label}: capacity must be between 0.1 and 10000 L.`);
    if (!(tank.level_l >= 0 && tank.level_l <= tank.capacity_l))
      errors.push(`${label}: the level must be between 0 L and its capacity.`);
    if (!(tank.dose_ml >= 0 && tank.dose_ml <= 100000))
      errors.push(`${label}: the dose per batch must be between 0 and 100000 mL.`);
    if (!(tank.low_l >= 0 && tank.low_l <= tank.capacity_l))
      errors.push(`${label}: the low mark must be between 0 L and its capacity.`);
    if (tank.dose_entity && !/^(number|input_number|sensor)\.[a-z0-9_]+$/.test(tank.dose_entity))
      errors.push(`${label}: the dose entity must be a number, input_number or sensor.`);
  }
  return errors;
}

/** Inventory measurements belong to the operational card; configuration never resends a cached level. */
export function stockConfigurationPayload(tanks: StockTankDraft[]) {
  return tanks.map((tank) => {
    if (!tank.id) return { ...tank };
    const { level_l: _measuredLevel, ...configuration } = tank;
    return configuration;
  });
}

/** What a tank still covers at today's use: whole batches, whole days at one batch every
 * `batchEveryDays` (NaN when that is not known), and whether it is at or under its low mark (the
 * integration's stock.low_tanks). */
export function stockOutlook(
  tank: Pick<StockTank, "level_l" | "low_l">,
  usePerBatchL: number,
  batchEveryDays: number,
): { batches: number; daysLeft: number; belowLow: boolean } {
  // Rounded first: 0.29 L is 289.99999999999997 mL in floating point, one batch short.
  const exact =
    Math.round(tank.level_l * 1000 * 1e6) / 1e6 / (Math.round(usePerBatchL * 1000 * 1e6) / 1e6);
  return {
    batches: Math.floor(exact),
    daysLeft: Math.floor(Math.round(exact * batchEveryDays * 1e6) / 1e6),
    belowLow: tank.level_l <= tank.low_l,
  };
}

/** Sources that log a batch: a fill counted from the last-fill entity, one recorded by hand, and a
 * batch the controller dosed (one row per pump, a minute apart). */
const BATCH_SOURCES: readonly StockBatch["source"][] = ["fill", "manual", "batch"];
/** Rows this close together are one batch. */
const SAME_BATCH_MS = 30 * 60_000;

/** One batch every so many days, from the batches the history logged: null below two. */
export function batchEveryDays(history: readonly StockBatch[]): number | null {
  const times = history
    .filter((row) => BATCH_SOURCES.includes(row.source))
    .map((row) => Date.parse(row.at))
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
  const batches: number[] = [];
  for (const t of times)
    if (!batches.length || t - batches[batches.length - 1] > SAME_BATCH_MS) batches.push(t);
  if (batches.length < 2) return null;
  return (batches[batches.length - 1] - batches[0]) / (batches.length - 1) / 86_400_000;
}

const calendarDay = (key: string) => Date.parse(`${key}T00:00:00Z`);
const keyOf = (utcDay: number) => new Date(utcDay).toISOString().slice(0, 10);
/** The Monday ("YYYY-MM-DD") of the week holding `ms` on the zone's calendar. */
function mondayOf(ms: number, tz: string): string {
  const day = calendarDay(dayKey(ms, tz));
  return keyOf(day - ((new Date(day).getUTCDay() + 6) % 7) * 86_400_000);
}

/** Litres drawn from each tank per week (Monday to Sunday on the zone's calendar), from the oldest
 * week the history holds to this one, which is `partial`. A week with nothing drawn has no tanks. */
export function weeklyUse(
  history: readonly Pick<StockBatch, "at" | "draw_ml">[],
  tz: string,
  now = Date.now(),
): { week: string; byTank: Record<string, number>; partial: boolean }[] {
  const ml = new Map<string, Record<string, number>>();
  for (const row of history) {
    const t = Date.parse(row.at);
    if (!Number.isFinite(t) || t > now) continue;
    const week = mondayOf(t, tz);
    const sums = ml.get(week) ?? {};
    for (const [tank, drawn] of Object.entries(row.draw_ml)) sums[tank] = (sums[tank] ?? 0) + drawn;
    ml.set(week, sums);
  }
  if (!ml.size) return [];
  const current = mondayOf(now, tz);
  const weeks = [];
  for (
    let day = calendarDay([...ml.keys()].sort()[0]);
    day <= calendarDay(current);
    day += 7 * 86_400_000
  ) {
    const week = keyOf(day);
    const sums = ml.get(week) ?? {};
    weeks.push({
      week,
      byTank: Object.fromEntries(
        Object.entries(sums).map(([tank, drawn]) => [tank, Math.round(drawn * 1e3) / 1e6]),
      ),
      partial: week === current,
    });
  }
  return weeks;
}

/** Weeks for Used per week: the last `shown`. A full history (`kept` rows) may have lost the start of
 * its oldest week, so that week is left out, unless it is this week. */
export function weeksShown(
  history: readonly Pick<StockBatch, "at" | "draw_ml">[],
  tz: string,
  kept: number,
  shown: number,
  now = Date.now(),
) {
  const weeks = weeklyUse(history, tz, now);
  return (history.length >= kept && weeks.length > 1 ? weeks.slice(1) : weeks).slice(-shown);
}

/** One logged refill to capacity. */
export interface RefillRow {
  key: string;
  tank: string;
  /** The tank's place on the page, for its colour. */
  hue: number;
  at: number;
  /** Litres added, when the level before is known. */
  added: number | null;
  to: number;
}
const near = (a: unknown, b: unknown) =>
  typeof a === "number" && typeof b === "number" && Math.abs(a - b) <= 1e-6;
/** Refills to capacity, newest first. From the Journal's `stock.refilled` events on 3.18: a set level
 * (`full: false`) is not a refill, and a refill whose next event on that tank puts its level before
 * back (an Undo) is left out. On an older integration (`events` null), each tank's last refill, the
 * only one it keeps, unless `undone` holds it as `<tank id>@<refilled_at>`. */
export function refillRows(
  tanks: readonly StockTank[],
  events: readonly CsEvent[] | null,
  undone: ReadonlySet<string> = new Set(),
): RefillRow[] {
  const index = new Map(tanks.map((tank, i) => [tank.id, i]));
  const sorted = [...(events ?? [])].sort(
    (a, b) => Date.parse(a.ts) - Date.parse(b.ts) || (a.seq ?? 0) - (b.seq ?? 0),
  );
  const rows: RefillRow[] = events
    ? sorted.flatMap((event, n) => {
        const { tank, level_l, old_level_l, full } = event.data as Record<string, unknown>;
        const i = index.get(String(tank));
        if (i === undefined || full !== true || typeof level_l !== "number") return [];
        const next = sorted.slice(n + 1).find((e) => e.data.tank === tank)?.data;
        if (
          next &&
          next.full === false &&
          near(next.old_level_l, level_l) &&
          near(next.level_l, old_level_l)
        )
          return [];
        return [
          {
            key: event.id,
            tank: tanks[i].name,
            hue: i,
            at: Date.parse(event.ts),
            added:
              typeof old_level_l === "number"
                ? Math.round((level_l - old_level_l) * 1e4) / 1e4
                : null,
            to: level_l,
          },
        ];
      })
    : tanks.flatMap((tank, i) =>
        tank.refilled_at && !undone.has(`${tank.id}@${tank.refilled_at}`)
          ? [
              {
                key: tank.id,
                tank: tank.name,
                hue: i,
                at: Date.parse(tank.refilled_at),
                added: null,
                to: tank.capacity_l,
              },
            ]
          : [],
      );
  return rows.filter((row) => Number.isFinite(row.at)).sort((a, b) => b.at - a.at);
}

/** What Refills lists: `older` when the integration has no Journal. While the Journal reloads (after
 * every write) it keeps `last`, so the rows never flash empty; an older integration's rows need no
 * answer, so they follow `undone` at once. Null: nothing to list yet, or the Journal failed. */
export interface RefillsView {
  rows: RefillRow[];
  older: boolean;
}
export function refillsView(
  state: ParityState,
  events: readonly CsEvent[] | null,
  tanks: readonly StockTank[],
  undone: ReadonlySet<string>,
  last: RefillsView | null,
): RefillsView | null {
  if (state === "ready") return { rows: refillRows(tanks, events ?? []), older: false };
  if (state === "missing" || (state === "loading" && last?.older))
    return { rows: refillRows(tanks, null, undone), older: true };
  return state === "loading" ? last : null;
}

/** A Used per week tick: the chart's values are already in the display unit. */
export const weeklyTick = (shown: number) =>
  formatVolume(getDisplayUnits().volume === "gal" ? shown * LITRES_PER_US_GALLON : shown, 1);

/** Undo a refill: the refilled tank back at `priorLevel` through stock_refill (so the Journal records
 * the put-back), at `current`'s revision, so a change since refuses. Refuses itself when the tank no
 * longer reads the refilled level, and when the answer does not read `priorLevel` back. */
export async function undoRefill(
  controller: Pick<Controller, "operator">,
  current: StockDocument,
  tankId: string,
  refilledTo: number,
  priorLevel: number,
): Promise<StockDocument> {
  const tank = current.tanks.find((t) => t.id === tankId);
  const name = tank?.name ?? "The tank";
  if (!tank || !sameValue(String(tank.level_l), refilledTo))
    throw new Error(`${name} has changed since the refill. Nothing was put back.`);
  const doc = await controller.operator<StockDocument>("stock_refill", {
    expected_revision: current.revision,
    id: tankId,
    level_l: priorLevel,
  });
  const back = doc.tanks.find((t) => t.id === tankId);
  if (!back || !sameValue(String(back.level_l), priorLevel))
    throw new Error(
      `The controller did not confirm ${name} at its previous level. Reload and check it.`,
    );
  return doc;
}
