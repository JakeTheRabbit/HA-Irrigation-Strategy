import type { CsEvent } from "./parity-types";

/** One shot in a zone's log: when it started and ended, its phase ("" when unknown), the water each
 * plant got (null without a plant count), whether that water was metered or only commanded, how
 * long it ran (null when the source does not say) and VWC as the shot began. */
export interface ShotLogRow {
  at: number;
  end: number;
  phase: string;
  mlPerPlant: number | null;
  metered: boolean;
  seconds: number | null;
  vwcBefore: number | null;
}

const MIN = 60_000;
const num = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : null);
const perPlant = (litres: number | null, plants: number | null) =>
  litres === null || !plants || plants <= 0 ? null : (litres * 1000) / plants;

/** This zone's completed shots since `dayStart`, newest first, from the Journal. The phase sits on
 * `shot.started`, joined to its `shot.completed` by `correlation.intent_id`. Litres are the metered
 * ones, else the commanded. Aborted shots are not in the log. */
export function shotLog(events: CsEvent[], zone: number, dayStart: number, plants: number | null): ShotLogRow[] {
  const started = new Map<string, CsEvent>();
  for (const e of events)
    if (e.kind === "shot.started" && e.zone === zone && e.correlation?.intent_id) started.set(e.correlation.intent_id, e);
  const rows: ShotLogRow[] = [];
  for (const e of events) {
    if (e.kind !== "shot.completed" || e.zone !== zone) continue;
    const start = e.correlation?.intent_id ? started.get(e.correlation.intent_id) : undefined;
    const end = Date.parse(e.ts);
    const seconds = num(e.data.elapsed_s);
    const at = start ? Date.parse(start.ts) : end - (seconds ?? 0) * 1000;
    if (!(at >= dayStart)) continue;
    const metered = num(e.data.metered_l);
    rows.push({
      at,
      end,
      phase: typeof start?.data.phase === "string" ? start.data.phase : "",
      mlPerPlant: perPlant(metered ?? num(e.data.commanded_l), plants),
      metered: metered !== null,
      seconds,
      vwcBefore: num(e.data.vwc_before) ?? num(start?.data.vwc_before),
    });
  }
  return rows.sort((a, b) => b.at - a.at);
}

/** The same rows from a 3.17 integration's shot table (`zone_N_shot_log_app.shots`): its start, its
 * kind ("p2_topup" is P2) and its litres. It keeps no run time and no VWC. Null without a table. */
export function tableShotLog(raw: unknown, dayStart: number, plants: number | null): ShotLogRow[] | null {
  if (!Array.isArray(raw)) return null;
  return raw
    .flatMap((item): ShotLogRow[] => {
      const r = item && typeof item === "object" ? (item as Record<string, unknown>) : null;
      const at = typeof r?.start === "string" ? Date.parse(r.start) : NaN;
      if (!r || !(at >= dayStart)) return [];
      const phase = /^p([0-3])/i.exec(String(r.kind ?? ""));
      return [
        {
          at,
          end: at,
          phase: phase ? `P${phase[1]}` : "",
          mlPerPlant: perPlant(num(r.litres), plants),
          metered: true,
          seconds: null,
          vwcBefore: null,
        },
      ];
    })
    .sort((a, b) => b.at - a.at);
}

/** VWC once a shot has settled: of the readings at or after the shot's end, the one nearest
 * `shotEnd + settleMs`, null without one inside 15 min of it. */
export function vwcAfter(series: { t: number; v: number }[], shotEnd: number, settleMs = 300_000): number | null {
  const target = shotEnd + settleMs;
  let best: { t: number; v: number } | null = null;
  for (const point of series)
    if (point.t >= shotEnd && Math.abs(point.t - target) <= 15 * MIN && (!best || Math.abs(point.t - target) < Math.abs(best.t - target)))
      best = point;
  return best?.v ?? null;
}

/** VWC as a shot began, where the source does not say: the last reading at or before it, inside
 * 15 min. */
export function vwcBefore(series: { t: number; v: number }[], start: number): number | null {
  let best: { t: number; v: number } | null = null;
  for (const point of series) if (point.t <= start && point.t >= start - 15 * MIN && (!best || point.t > best.t)) best = point;
  return best?.v ?? null;
}
