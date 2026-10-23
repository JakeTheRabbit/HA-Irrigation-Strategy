import type { DosingConfig, DosingDocument, DosingPump } from "./dosing";
import { monthName } from "./time";

/** Equipment › Pump calibration (G3): prime a dosing pump's line while held, run it 30 s into a
 * measuring jug, and turn the mL measured into its flow (dosing_api.py `pump_*`). The integration
 * works the flow out (`ml_min`); this file only words what it reports. */

/** How long a prime may run and how long the calibration run is, in seconds. */
export const PRIME_SECONDS = 30;
export const RUN_SECONDS = 30;
/** A pump is due a calibration this many days after its last one. */
export const CALIBRATE_EVERY_DAYS = 60;
/** A result further than this from the catalogue (or its last calibration), in %, is worth a rerun. */
export const FAR_OFF_PCT = 25;
const DAY_MS = 86_400_000;

export type SolutionType = "nutrient" | "ph_up" | "ph_down" | "additive";
export const SOLUTION_LABELS: Record<SolutionType, string> = {
  nutrient: "Nutrient",
  ph_up: "pH up",
  ph_down: "pH down",
  additive: "Additive",
};
export interface PumpModel {
  catalog_id: string;
  dial: number | null;
}
/** One stored calibration, newest first in `calibrations`. */
export interface PumpCalibrationRecord {
  id: string;
  pump: string;
  run_s: number;
  measured_ml: number;
  ml_min: number;
  previous_ml_min: number | null;
  at: string;
  by: string | null;
}
/** A pump's open calibration session, as dosing_get shows it. `ran_s` is null until the controller
 * reports the run. */
export interface PumpSession {
  session_id: string;
  request_id: string;
  seconds: number;
  ran_s: number | null;
  result: string | null;
  expires_at: string;
}
export interface CalibrationPump extends DosingPump {
  model?: PumpModel | null;
  solution_type?: SolutionType | null;
  calibrated_ml_min?: number | null;
  calibrations?: PumpCalibrationRecord[];
  primed_at?: string | null;
  calibration_session?: PumpSession;
}
/** dosing_get's `catalog`: each model's name and dial → nominal mL/min, or null (no table). */
export type PumpCatalog = Record<string, { name: string; nominal_ml_min: Record<string, number> } | null>;
export interface PumpDosingDocument extends Omit<DosingDocument, "config"> {
  config: (Omit<DosingConfig, "pumps"> & { pumps: CalibrationPump[] }) | null;
  catalog?: PumpCatalog;
}

/** Days since the last calibration (whole days) and whether it is due; never calibrated is due. */
export function calibrationDue(lastAt: number | null, everyDays: number, now: number): { days: number | null; due: boolean } {
  if (lastAt === null) return { days: null, due: true };
  const days = Math.max(0, Math.floor((now - lastAt) / DAY_MS));
  return { days, due: days >= everyDays };
}

/** "300 mL/min — 7% above the catalogue figure." `mlMin` is the integration's own number. */
export function rateSentence(mlMin: number, nominal: number | null): string {
  if (nominal === null || !(nominal > 0)) return `${mlMin} mL/min. This pump has no catalogue figure to compare with.`;
  const pct = Math.round(((mlMin - nominal) / nominal) * 100);
  if (pct === 0) return `${mlMin} mL/min — the same as the catalogue figure.`;
  return `${mlMin} mL/min — ${Math.abs(pct)}% ${pct > 0 ? "above" : "below"} the catalogue figure.`;
}

/** "Down 12% since March — tubing may be wearing.": the newest calibration against the oldest kept,
 * when it has dropped 10% or more. */
export function wearNote(history: { at: number; mlMin: number }[], tz = "UTC"): string | null {
  if (history.length < 2) return null;
  const sorted = [...history].sort((a, b) => a.at - b.at);
  const first = sorted[0],
    last = sorted[sorted.length - 1];
  if (!(first.mlMin > 0)) return null;
  const pct = Math.round(((first.mlMin - last.mlMin) / first.mlMin) * 100);
  if (pct < 10) return null;
  return `Down ${pct}% since ${monthName(first.at, tz, last.at - first.at > 330 * DAY_MS)} — tubing may be wearing.`;
}

/** Whether the controller has reported the calibration run yet. */
export function runState(session: { ran_s?: number | null } | null): "waiting" | "ran" {
  return typeof session?.ran_s === "number" ? "ran" : "waiting";
}
/** Whether Run is offered: no run asked for yet, or the last one was reported at 0 s (stopped
 * before the controller started it). A new run replaces the old session (the backend's pump_open
 * closes it). */
export function canStartRun(sessionId: string | null | undefined, session: { ran_s?: number | null } | null): boolean {
  return !sessionId || (typeof session?.ran_s === "number" && session.ran_s <= 0);
}

/** What the pump drawing claims: running only once the controller accepted the prime; a
 * calibration run is only asked for until the controller reports it. */
export function pumpMotion(
  name: string,
  { priming, primeOk, waiting }: { priming: boolean; primeOk: boolean | undefined; waiting: boolean },
): { active: boolean; text: string } {
  if (priming && primeOk === true) return { active: true, text: `${name} is running` };
  if (waiting) return { active: false, text: `Asked ${name} to run ${RUN_SECONDS} s` };
  return { active: false, text: name };
}
/** The prime button's words: priming only once accepted; a refusal drops back to the plain label. */
export function primeLabel(priming: boolean, primeOk: boolean | undefined): string {
  if (!priming || primeOk === false) return "Hold to prime";
  return primeOk ? "Priming… let go to stop" : "Asking to prime… let go to stop";
}

/** What holding the prime button sends: a 30 s prime on press, a stop on release. The stop goes
 * however the hold ends (HoldButton's while-held mode calls `onStop` exactly once). */
export function primeActions(
  send: (action: "pump_prime" | "pump_stop", data: Record<string, unknown>) => Promise<unknown>,
  roomId: string,
  pump: string,
): { onStart(): void; onStop(): void } {
  return {
    onStart: () => void send("pump_prime", { room_id: roomId, pump, seconds: PRIME_SECONDS }),
    onStop: () => void send("pump_stop", { room_id: roomId, pump }),
  };
}

/** The catalogue's nominal flow for a pump's model and dial, mL/min, or null. */
export function nominalOf(pump: Pick<CalibrationPump, "model">, catalog: PumpCatalog | undefined): number | null {
  const model = pump.model;
  if (!model || !catalog) return null;
  const table = catalog[model.catalog_id];
  const value = table && model.dial !== null ? table.nominal_ml_min[String(model.dial)] : undefined;
  return typeof value === "number" ? value : null;
}
/** The pump head, in words: "H.E. Anderson P1, dial 8 · 272 mL/min nominal". */
export function headWords(pump: Pick<CalibrationPump, "model">, catalog: PumpCatalog | undefined): string {
  const model = pump.model;
  if (!model) return "Model not set";
  const nominal = nominalOf(pump, catalog);
  const table = catalog?.[model.catalog_id];
  if (table && nominal !== null) return `${table.name}, dial ${model.dial} · ${nominal} mL/min nominal`;
  return `${model.catalog_id === "peristaltic" ? "Peristaltic" : "Other pump"} · no catalogue figure`;
}

/** A pump's calibrations, oldest first, as times and flows. */
export function pumpHistory(pump: Pick<CalibrationPump, "calibrations">): { at: number; mlMin: number }[] {
  return (pump.calibrations ?? [])
    .map((c) => ({ at: Date.parse(c.at), mlMin: c.ml_min }))
    .filter((c) => Number.isFinite(c.at) && Number.isFinite(c.mlMin))
    .sort((a, b) => a.at - b.at);
}
/** The newest calibration, or null. */
export function lastCalibration(pump: Pick<CalibrationPump, "calibrations">): { at: number; mlMin: number } | null {
  const history = pumpHistory(pump);
  return history.length ? history[history.length - 1] : null;
}

/** mL measured over the seconds the controller reported → mL/min, the integration's sum to 2
 * decimals; null when it cannot be worked out. */
export function estimateRate(measuredMl: number, ranS: number): number | null {
  if (!(measuredMl > 0) || !(ranS > 0) || !Number.isFinite(measuredMl)) return null;
  return Math.round((measuredMl / ranS) * 60 * 100) / 100;
}
/** How far a flow is from a reference, in whole %, or null without one. */
export function offBy(mlMin: number, reference: number | null): number | null {
  return reference && reference > 0 ? Math.round(((mlMin - reference) / reference) * 100) : null;
}
/** A typed mL: a number above 0, else null. */
export function parseMl(text: string): number | null {
  const value = Number(text.trim().replace(",", "."));
  return text.trim() !== "" && Number.isFinite(value) && value > 0 ? value : null;
}
