/** Grows side by side from the room's grow-day summaries (crop_steering.grow_days_get) and the harvests
 * (crop_steering.harvests_get): each run's days lined up by grow day, its statistics, and its yield against water
 * and steering. Read-only: nothing here changes watering. */
import { daysBetween } from "./comparison";
import type { RunRecord } from "./comparison-types";

export interface Band {
  min: number | null;
  max: number | null;
  mean: number | null;
}
export interface ProbeDay {
  kind: "vwc" | "ec";
  entity_id: string;
  name: string | null;
  unit: string | null;
  peak: number | null;
  trough: number | null;
  mean: number | null;
  used_share: number | null;
}
/** One zone's grow-day, as the controller summarised it at the next lights-on. */
export interface GrowDay {
  date: string;
  zone: number;
  partial: boolean;
  backfilled: string | null;
  vwc: { peak: number | null; trough: number | null; mean: number | null } | null;
  ec: Band | null;
  feed_ec?: Band | null;
  feed_ph?: Band | null;
  plateau?: { value: number | null; how: string | null; shots: number } | null;
  p0?: { dryback_pct: number | null; drop_pts: number | null; landing: number | null } | null;
  night?: { rate: number | null; shots: number } | null;
  p1_stall?: boolean;
  shots?: Record<string, number>;
  rescues?: number;
  litres: number | null;
  plant_count?: number | null;
  litres_per_plant?: number | null;
  alerts?: string[];
  mode?: string | null;
  probes?: ProbeDay[];
}
export interface GrowDaysDocument {
  room_id: string;
  days: GrowDay[];
  first: string | null;
  last: string | null;
  count: number;
}
export interface HarvestWeights {
  wet_weight_g: number | null;
  dry_weight_g: number | null;
  plants_harvested: number | null;
  canopy_m2: number | null;
}
export interface Harvest {
  harvest_date: string | null;
  room: HarvestWeights | null;
  zones: Record<string, HarvestWeights>;
  plants: { label: string | null; zone: number | null; wet_g: number | null; dry_g: number | null }[];
  quality: string | null;
  notes: string | null;
  lab: { thc_pct: number | null; terpenes: Record<string, number | null> };
  updated_at?: string | null;
}
export interface HarvestsDocument {
  room_id: string;
  revision: number;
  harvests: Record<string, Harvest>;
}

/** "room": the zones averaged; a number: that zone. */
export type GrowScope = "room" | number;

/** Grow day `n` of a run (1 is its start date). */
export const dayOfRun = (run: RunRecord, date: string) => daysBetween(run.start_date, date) + 1;

/** A run's last date: its end, else the newest summary. */
function lastDate(run: RunRecord, days: GrowDay[]) {
  return run.end_date ?? days.reduce((last, d) => (d.date > last ? d.date : last), run.start_date);
}

const mean = (values: number[]) =>
  values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
const nums = (values: (number | null | undefined)[]) =>
  values.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
export function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** One point of a grow's line: grow day n, its values for the scope (the zones averaged for the room). */
export interface GrowPoint {
  day: number;
  date: string;
  vwcPeak: number | null;
  vwcTrough: number | null;
  vwcBand: [number, number] | null;
  p0Dryback: number | null;
  nightRate: number | null;
  ecMean: number | null;
  litresPerPlant: number | null;
  shots: number | null;
  rescue: boolean;
  stall: boolean;
  partial: boolean;
  backfilled: boolean;
}

/** A run's summaries in its date range, one point per grow day, for one zone or the room. */
export function growPoints(run: RunRecord, days: GrowDay[], scope: GrowScope): GrowPoint[] {
  const last = lastDate(run, days);
  const inRun = days.filter(
    (d) => d.date >= run.start_date && d.date <= last && (scope === "room" || d.zone === scope),
  );
  const byDate = new Map<string, GrowDay[]>();
  for (const d of inRun) byDate.set(d.date, [...(byDate.get(d.date) ?? []), d]);
  return [...byDate.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, rows]) => {
      const avg = (pick: (d: GrowDay) => number | null | undefined) => mean(nums(rows.map(pick)));
      const peak = avg((d) => d.vwc?.peak),
        trough = avg((d) => d.vwc?.trough);
      const shots = rows.map((d) => Object.values(d.shots ?? {}).reduce((a, b) => a + b, 0));
      return {
        day: dayOfRun(run, date),
        date,
        vwcPeak: peak,
        vwcTrough: trough,
        vwcBand: peak !== null && trough !== null ? [trough, peak] : null,
        p0Dryback: avg((d) => d.p0?.dryback_pct),
        nightRate: avg((d) => d.night?.rate),
        ecMean: avg((d) => d.ec?.mean),
        litresPerPlant: avg((d) => d.litres_per_plant),
        shots: rows.some((d) => d.shots) ? (mean(shots) ?? null) : null,
        rescue: rows.some((d) => (d.rescues ?? 0) > 0),
        stall: rows.some((d) => d.p1_stall),
        partial: rows.some((d) => d.partial),
        backfilled: rows.some((d) => !!d.backfilled),
      };
    });
}

export interface GrowStats {
  days: number;
  litresPerPlant: number | null;
  dailyLitresPerPlant: number | null;
  dailyLitresSpread: number | null;
  p0Dryback: number | null;
  nightRate: number | null;
  ecMin: number | null;
  ecMax: number | null;
  ecMedian: number | null;
  vwcPeakMedian: number | null;
  vwcTroughMedian: number | null;
  rescues: number;
  stallDays: number;
  alerts: Record<string, number>;
  modes: Record<string, number>;
  /** Total litres fed to the scope over the run (for grams per litre). */
  litres: number | null;
}

/** A grow's statistics for one zone or the room. */
export function growStats(run: RunRecord, days: GrowDay[], scope: GrowScope): GrowStats {
  const last = lastDate(run, days);
  const rows = days.filter(
    (d) => d.date >= run.start_date && d.date <= last && (scope === "room" || d.zone === scope),
  );
  const points = growPoints(run, days, scope);
  const daily = nums(points.map((p) => p.litresPerPlant));
  const avg = mean(daily);
  const spread =
    daily.length > 1 && avg !== null
      ? Math.sqrt(daily.reduce((s, v) => s + (v - avg) ** 2, 0) / (daily.length - 1))
      : null;
  const ec = nums(rows.flatMap((d) => [d.ec?.min, d.ec?.max]));
  const count = (pick: (d: GrowDay) => string[]) => {
    const out: Record<string, number> = {};
    for (const d of rows) for (const key of pick(d)) out[key] = (out[key] ?? 0) + 1;
    return out;
  };
  const litres = nums(rows.map((d) => d.litres));
  return {
    days: points.length,
    litresPerPlant: daily.length ? daily.reduce((a, b) => a + b, 0) : null,
    dailyLitresPerPlant: avg,
    dailyLitresSpread: spread,
    p0Dryback: mean(nums(points.map((p) => p.p0Dryback))),
    nightRate: mean(nums(points.map((p) => p.nightRate))),
    ecMin: ec.length ? Math.min(...ec) : null,
    ecMax: ec.length ? Math.max(...ec) : null,
    ecMedian: median(nums(rows.map((d) => d.ec?.mean))),
    vwcPeakMedian: median(nums(points.map((p) => p.vwcPeak))),
    vwcTroughMedian: median(nums(points.map((p) => p.vwcTrough))),
    rescues: rows.reduce((s, d) => s + (d.rescues ?? 0), 0),
    stallDays: points.filter((p) => p.stall).length,
    alerts: count((d) => d.alerts ?? []),
    modes: count((d) => (d.mode ? [d.mode] : [])),
    litres: litres.length ? litres.reduce((a, b) => a + b, 0) : null,
  };
}

export interface YieldFigures {
  dryG: number | null;
  wetG: number | null;
  gramsPerPlant: number | null;
  gramsPerM2: number | null;
  gramsPerLitre: number | null;
  dryWetRatio: number | null;
}

/** Worked out when read, never stored: grams per plant, g/m2, g per litre fed and the dry/wet ratio. The room's
 * weights, else the zones' summed; a zone's own weights for a zone. Plants: the harvest's count, else the plant
 * entries, else the run's registered plants. */
export function yieldFigures(
  harvest: Harvest | undefined,
  run: RunRecord,
  scope: GrowScope,
  litres: number | null,
): YieldFigures {
  const none = {
    dryG: null,
    wetG: null,
    gramsPerPlant: null,
    gramsPerM2: null,
    gramsPerLitre: null,
    dryWetRatio: null,
  };
  if (!harvest) return none;
  const zones = Object.values(harvest.zones ?? {});
  const sum = (key: keyof HarvestWeights) => {
    const values = nums(zones.map((z) => z[key]));
    return values.length ? values.reduce((a, b) => a + b, 0) : null;
  };
  const pick = (key: keyof HarvestWeights) =>
    scope === "room"
      ? (harvest.room?.[key] ?? sum(key))
      : (harvest.zones?.[String(scope)]?.[key] ?? null);
  const plantRows = harvest.plants.filter((p) => scope === "room" || p.zone === scope);
  const registered = nums(
    run.zones.filter((z) => scope === "room" || z.zone_id === scope).map((z) => z.plant_count),
  );
  const dry = pick("dry_weight_g") ?? (plantRows.length ? sumOf(plantRows.map((p) => p.dry_g)) : null);
  const wet = pick("wet_weight_g") ?? (plantRows.length ? sumOf(plantRows.map((p) => p.wet_g)) : null);
  const plants =
    pick("plants_harvested") ||
    (plantRows.length ? plantRows.length : null) ||
    (registered.length ? registered.reduce((a, b) => a + b, 0) : null);
  const area = pick("canopy_m2");
  return {
    dryG: dry,
    wetG: wet,
    gramsPerPlant: dry !== null && plants ? dry / plants : null,
    gramsPerM2: dry !== null && area ? dry / area : null,
    gramsPerLitre: dry !== null && litres ? dry / litres : null,
    dryWetRatio: dry !== null && wet ? dry / wet : null,
  };
}
function sumOf(values: (number | null)[]) {
  const n = nums(values);
  return n.length ? n.reduce((a, b) => a + b, 0) : null;
}

/** The summary of grow day `day` of `run` for a zone, or null. */
export function dayOf(run: RunRecord, days: GrowDay[], zone: number, day: number): GrowDay | null {
  return days.find((d) => d.zone === zone && dayOfRun(run, d.date) === day && d.date >= run.start_date &&
    (!run.end_date || d.date <= run.end_date)) ?? null;
}

/** Fewer grows than this is a record, not a trend: no fit line, and the page says so. */
export const TREND_MIN_GROWS = 5;
