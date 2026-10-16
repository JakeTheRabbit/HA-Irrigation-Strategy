import type { States } from "./types";

/** The room's runoff estimate from the controller's sump water balance (addons/f2_control/f2_control/
 * runoff_balance.py): room-wide and per grow-day, a hint with an error band, never a measured catch. */

export type RunoffMode = "off" | "shadow" | "shown_alerts" | "ai";
export const RUNOFF_MODES: [RunoffMode, string][] = [
  ["off", "Off"],
  ["shadow", "Shadow"],
  ["shown_alerts", "With alerts"],
  ["ai", "Also to the AI"],
];
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);

export function runoffMode(states: States, prefix: string): RunoffMode | null {
  const s = states[`select.crop_steering_${prefix}runoff_estimator`];
  if (!s) return null; // an integration without the estimator
  return (RUNOFF_MODES.find(([m]) => m === s.state)?.[0] ?? "off") as RunoffMode;
}

export interface RunoffDay {
  date: string;
  runs: number;
  fedL: number | null;
  deltaSubstrateL: number | null;
  closureErrorPct: number | null;
}
export interface Runoff {
  /** The runoff % of the water fed, or null with `status` saying why. */
  pct: number | null;
  status: string;
  why: string;
  band: number | null;
  r2: number | null;
  litresPerRun: number | null;
  litresSource: string;
  delayMin: number | null;
  transpirationTodayL: number | null;
  runoffTodayL: number | null;
  sumpTodayL: number | null;
  perUnit: [string, number][];
  days: RunoffDay[];
  scope: string;
}
export function readRunoff(states: States, prefix: string): Runoff | null {
  const s = states[`sensor.crop_steering_${prefix}runoff_estimate_app`];
  if (!s) return null;
  const a = s.attributes;
  const pct = Number(s.state);
  const units = a.litres_per_hour && typeof a.litres_per_hour === "object" ? a.litres_per_hour : {};
  return {
    pct: s.state !== "" && Number.isFinite(pct) ? pct : null,
    status: s.state,
    why: typeof a.why === "string" ? a.why : "",
    band: num(a.band_pct),
    r2: num(a.r2),
    litresPerRun: num(a.litres_per_run),
    litresSource: typeof a.litres_per_run_source === "string" ? a.litres_per_run_source : "",
    delayMin: num(a.drain_delay_min),
    transpirationTodayL: num(a.transpiration_today_l),
    runoffTodayL: num(a.runoff_today_l),
    sumpTodayL: num(a.sump_today_l),
    perUnit: Object.entries(units as Record<string, unknown>).flatMap(([k, v]) =>
      num(v) === null ? [] : [[k, v as number] as [string, number]],
    ),
    days: (Array.isArray(a.days) ? a.days : []).flatMap((d) => {
      if (!d || typeof d !== "object") return [];
      const r = d as Record<string, unknown>;
      return typeof r.date === "string"
        ? [
            {
              date: r.date.slice(0, 10),
              runs: num(r.runs) ?? 0,
              fedL: num(r.fed_l),
              deltaSubstrateL: num(r.delta_substrate_l),
              closureErrorPct: num(r.closure_error_pct),
            },
          ]
        : [];
    }),
    scope: typeof a.scope === "string" ? a.scope : "room-wide estimate",
  };
}
