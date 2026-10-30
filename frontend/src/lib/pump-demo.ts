import type { DosingDocument } from "./dosing";
import { numeric } from "./model";
import { demoEnvelope } from "./parity-demo";
import type { CalibrationPump, PumpCalibrationRecord, PumpCatalog, PumpDosingDocument, PumpModel, SolutionType } from "./pump-calibration";
import type { States } from "./types";

/** The demo integration's pump prime and calibration (dosing_api.py `pump_*`), in memory: a prime
 * is a request a stop ends; a calibration run is reported 3 s after it is asked for (demo time, on
 * the timer so a pinned clock does not stall it), or when stopped; a stop within 1.5 s, before the
 * controller took it, closes the session instead (no report comes); a prime or run asked for within
 * 1.5 s of a stop, which the controller has not taken yet, is refused busy; a commit stores the flow and
 * sets the pump's flow number. Each pump's newest calibration is the flow its flow number holds. */

/** The catalogue as dosing_get serves it (dosing.py PUMP_CATALOG). */
const dial = (perDial: number) => Object.fromEntries(Array.from({ length: 10 }, (_, i) => [String(i + 1), perDial * (i + 1)]));
export const DEMO_CATALOG: PumpCatalog = {
  hea_a3: { name: "H.E. Anderson A3", nominal_ml_min: dial(10) },
  hea_p1: { name: "H.E. Anderson P1", nominal_ml_min: dial(34) },
  hea_p2: { name: "H.E. Anderson P2", nominal_ml_min: dial(68) },
  hea_h4: { name: "H.E. Anderson H4", nominal_ml_min: dial(136) },
  peristaltic: null,
  other: null,
};
/** Each demo pump's model, what it doses, and when it was calibrated (days ago, newest first; the
 * older ones a little faster, as tubing wears). */
const SEEDS: Record<string, { model: PumpModel; solution: SolutionType; days: number[] }> = {
  part_a: { model: { catalog_id: "hea_p2", dial: 9 }, solution: "nutrient", days: [22, 83, 146] },
  part_b: { model: { catalog_id: "hea_p2", dial: 9 }, solution: "nutrient", days: [69, 131, 196] },
  veg_base: { model: { catalog_id: "hea_p2", dial: 9 }, solution: "nutrient", days: [40] },
  silica: { model: { catalog_id: "peristaltic", dial: null }, solution: "additive", days: [30] },
  finisher: { model: { catalog_id: "hea_p1", dial: 10 }, solution: "additive", days: [] },
  cleaner: { model: { catalog_id: "other", dial: null }, solution: "additive", days: [] },
};
const RUN_MS = 3000;
/** A run stopped this soon after it was asked for never started: the controller reports 0 s. */
const PICKUP_MS = 1500;
const DAY = 86_400_000;
const round = (value: number, digits: number) => Math.round(value * 10 ** digits) / 10 ** digits;
const iso = (ms: number) => new Date(ms).toISOString();
/** dosing_api.py BUSY: a timed request while the last one still waits for the controller. */
const BUSY = "Another dosing request is still waiting for the controller";
const BLOCKER = { code: "pump_calibrating", message: "Another pump's calibration is still open" };

interface Session {
  room: string;
  pump: string;
  session_id: string;
  request_id: string;
  seconds: number;
  ran_s: number | null;
  result: string | null;
  started: number;
  timer: ReturnType<typeof setTimeout>;
}
export interface DemoPumpCall {
  action: string;
  data: Record<string, unknown>;
}

export class PumpDemo {
  /** Every pump service called, in order: the browser check reads it as `window.__csPumpCalls`. */
  readonly calls: DemoPumpCall[] = [];
  private sessions = new Map<string, Session>();
  private calibrations = new Map<string, PumpCalibrationRecord[]>();
  private count = 0;
  /** When the last stop was asked for (performance.now), by room and pump. */
  private stops = new Map<string, number>();
  constructor(
    private getStates: () => States,
    private updateStates: (states: States) => void,
  ) {
    if (typeof window !== "undefined") (window as unknown as { __csPumpCalls?: DemoPumpCall[] }).__csPumpCalls = this.calls;
  }

  /** dosing_get's answer with the catalogue and each pump's model, calibrations and open session. */
  decorate(doc: DosingDocument): PumpDosingDocument {
    const out = doc as PumpDosingDocument;
    out.catalog = structuredClone(DEMO_CATALOG);
    if (!out.config) return out;
    out.config.pumps = out.config.pumps.map((pump) => {
      const seed = SEEDS[pump.id];
      const calibrations = this.history(doc.room_id, pump);
      const session = [...this.sessions.values()].find((s) => s.room === doc.room_id && s.pump === pump.id);
      const decorated: CalibrationPump = {
        ...pump,
        ...(seed ? { model: { ...seed.model }, solution_type: seed.solution } : {}),
        ...(calibrations.length ? { calibrated_ml_min: calibrations[0].ml_min, calibrations: structuredClone(calibrations) } : {}),
        ...(session
          ? {
              calibration_session: {
                session_id: session.session_id,
                request_id: session.request_id,
                seconds: session.seconds,
                ran_s: session.ran_s,
                result: session.result,
                expires_at: iso(Date.now() + 30 * 60_000),
              },
            }
          : {}),
      };
      return decorated;
    });
    return out;
  }

  /** The answer for a pump of the room's dosing setup, or for one of this demo's sessions;
   * undefined for anything else, which the generic parity demo answers. */
  call(action: string, data: Record<string, unknown>): unknown {
    const room = String(data.room_id ?? "");
    const pump = String(data.pump ?? "");
    const known =
      action === "pump_calibration_commit"
        ? [...this.sessions.values()].some((s) => s.session_id === data.session_id)
        : !!this.pumpOf(room, pump);
    if (!known) return undefined;
    this.calls.push({ action, data: structuredClone(data) });
    const now = Date.now();
    const id = (kind: string) => `demo-${kind}-${++this.count}`;
    const envelope = (answer: unknown) => demoEnvelope(answer, now, room);
    const refused = (blockers: { code: string; message: string }[], extra: Record<string, unknown>) => ({
      api: 2,
      ok: false,
      error: { code: "guard_refused", message: `The pump cannot run now: ${blockers.map((b) => b.message).join("; ")}` },
      data: { ...extra, outcome: "refused", blockers },
    });
    const invalid = (message: string) => ({ api: 2, ok: false, error: { code: "invalid", message } });
    const busy = () => {
      const at = this.stops.get(`${room}|${pump}`);
      return at !== undefined && performance.now() - at < PICKUP_MS ? { api: 2, ok: false, error: { code: "guard_refused", message: BUSY } } : null;
    };
    const blockers = () => ([...this.sessions.values()].some((s) => s.room === room && s.pump !== pump) ? [BLOCKER] : []);
    switch (action) {
      case "pump_precheck": {
        const found = blockers();
        return envelope({ ok: !found.length, blockers: found });
      }
      case "pump_prime": {
        // The integration's schema caps a prime at 1-30 s.
        if (data.seconds !== undefined && !(Number(data.seconds) >= 1 && Number(data.seconds) <= 30))
          return invalid("value must be between 1 and 30 for dictionary value @ data['seconds']");
        const found = blockers();
        if (found.length) return refused(found, { request_id: null });
        const waiting = busy();
        if (waiting) return waiting;
        return envelope({ request_id: id("prime"), outcome: "requested", blockers: [] });
      }
      case "pump_stop": {
        const key = `${room}|${pump}`;
        this.stops.set(key, performance.now());
        const session = this.sessions.get(key);
        if (session && session.ran_s === null) {
          clearTimeout(session.timer);
          const elapsed = performance.now() - session.started;
          // Not taken yet: the stop replaces the request and the session closes (dosing_api.py _replaced).
          if (elapsed < PICKUP_MS) {
            this.sessions.delete(key);
            return envelope({ request_id: id("stop"), replaced: { id: session.request_id, action: "calibrate", pump } });
          }
          session.ran_s = round(Math.min(1, elapsed / RUN_MS) * session.seconds, 1);
          session.result = "stopped";
        }
        return envelope({ request_id: id("stop"), replaced: null });
      }
      case "pump_calibrate": {
        const found = blockers();
        if (found.length) return refused(found, { session_id: null, request_id: null });
        const waiting = busy();
        if (waiting) return waiting;
        const seconds = Number(data.seconds);
        if (!(seconds >= 5 && seconds <= 120)) return invalid("a calibrate runs for 5 to 120 s");
        const key = `${room}|${pump}`;
        const old = this.sessions.get(key);
        if (old) clearTimeout(old.timer);
        const session: Session = {
          room, pump, session_id: id("pump-cal"), request_id: id("calibrate"), seconds, ran_s: null, result: null,
          started: performance.now(),
          timer: setTimeout(() => {
            session.ran_s = seconds;
            session.result = "finished";
          }, RUN_MS),
        };
        this.sessions.set(key, session);
        return envelope({ session_id: session.session_id, request_id: session.request_id, outcome: "requested", blockers: [] });
      }
      case "pump_calibration_commit": {
        const session = [...this.sessions.values()].find((s) => s.session_id === data.session_id && s.room === room);
        if (!session) return invalid("This calibration session has expired. Start again.");
        if (session.ran_s === null) return invalid("The calibration run has not been reported yet. Wait for the pump to stop.");
        if (!(session.ran_s > 0)) return invalid(`The calibration run did not run: ${session.result ?? "no time reported"}`);
        const measured = Number(data.measured_ml);
        if (!(measured > 0)) return invalid("The measured mL must be a number above 0");
        const config = this.pumpOf(room, session.pump);
        if (!config) return invalid(`unknown pump: ${session.pump}`);
        const ml_min = round((measured / session.ran_s) * 60, 2);
        const history = this.history(room, config);
        const previous = history[0]?.ml_min ?? null;
        this.calibrations.set(`${room}|${session.pump}`, [
          { id: id("calibration"), pump: session.pump, run_s: session.ran_s, measured_ml: measured, ml_min, previous_ml_min: previous, at: iso(now), by: "Demo" },
          ...history,
        ].slice(0, 30));
        this.sessions.delete(`${room}|${session.pump}`);
        const flow = config.flow_entity;
        const states = this.getStates();
        if (flow && states[flow]) this.updateStates({ ...states, [flow]: { ...states[flow], state: String(round(ml_min / 60, 4)), last_updated: iso(now) } });
        return envelope({ ml_min, previous_ml_min: previous, flow_entity_written: !!(flow && states[flow]) });
      }
    }
    return invalid(`Unsupported demo action: ${action}`);
  }

  private pumpOf(room: string, pump: string) {
    const prefix = room.replace(/^room:/, "");
    const pumps = this.getStates()[`sensor.crop_steering_${prefix}dosing_config`]?.attributes.pumps;
    return (Array.isArray(pumps) ? (pumps as CalibrationPump[]) : []).find((p) => p.id === pump) ?? null;
  }
  /** A pump's calibrations, newest first: its seeds (the newest the flow its number holds) until a
   * commit replaces them. */
  private history(room: string, pump: Pick<CalibrationPump, "id" | "flow_entity">): PumpCalibrationRecord[] {
    const key = `${room}|${pump.id}`;
    const kept = this.calibrations.get(key);
    if (kept) return kept;
    const flow = numeric(this.getStates()[pump.flow_entity]);
    const days = SEEDS[pump.id]?.days ?? [];
    if (flow === null || !(flow > 0) || !days.length) return [];
    const today = Date.now();
    const seeds: PumpCalibrationRecord[] = days.map((ago, i) => {
      const ml_min = round(flow * 60 * (1 + 0.03 * i), 2);
      return { id: `seed-${pump.id}-${i}`, pump: pump.id, run_s: 30, measured_ml: round(ml_min / 2, 2), ml_min, previous_ml_min: null, at: iso(today - ago * DAY), by: "Demo" };
    });
    seeds.forEach((s, i) => (s.previous_ml_min = seeds[i + 1]?.ml_min ?? null));
    this.calibrations.set(key, seeds);
    return seeds;
  }
}
