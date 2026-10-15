import { parseControllerTime } from "./controller-health";
import type { EntityState, States } from "./types";

/** What the controller's Jev bridge publishes for a room (addons/f2_control/f2_control/jev_bridge.py):
 * `sensor.crop_steering_<prefix>jev_log` (every decision, newest first), `sensor.crop_steering_<prefix>jev`
 * (calls, tokens, errors and today's stage) and `sensor.crop_steering_<prefix>zone_N_jev` (what each judge
 * last said about the zone). Read tolerantly: a controller older than the log, or one entry missing a
 * field, must never break the page. */

/** Each judge's plain title, for an entry that carries none (jev/journal.py TITLES). */
export const JEV_TITLES: Record<string, string> = {
  dawn: "Morning start",
  ramp: "Ramp hand-over",
  salt: "Pore EC",
  dusk: "Day end",
  probe: "Probe trust",
  shot: "Shot landing",
  night: "Night low",
  zones: "Zone comparison",
  stage: "Stage arc",
  setpoints: "Setpoints",
  alerts: "Alert triage",
};

export type JevResult =
  "acted" | "advice" | "refused" | "no action" | "waiting" | "worked" | "did not work" | "unknown";

export interface JevEntry {
  /** Unique within one list, for React keys. */
  key: string;
  /** When Jev decided (epoch ms); null when the entry's time could not be read. */
  time: number | null;
  /** The entry's time as the controller wrote it: what an outcome's `of` names. */
  stamp: string;
  /** An outcome: the `stamp` of the decision it checks ("" from a controller before 3.4). */
  of: string;
  /** The zone it was about; null for the room (an alert-triage call without a zone). */
  zone: number | null;
  judge: string;
  title: string;
  kind: "decision" | "outcome";
  /** Jev's answer, in plain words. */
  verdict: string;
  /** How sure the council was, 0 to 1; null when not given. */
  p: number | null;
  /** Both phrasings of the question agreed. */
  agreed: boolean | null;
  /** What Jev asked for, in plain words; "" when nothing. */
  action: string;
  /** What code did with it. An alert a judge raised is advice: it never moves water. */
  result: JevResult;
  /** The result as the controller wrote it, shown when it is not one this page knows. */
  resultText: string;
  /** Code's why; for a refusal, the envelope's reason. */
  reason: string;
}

const text = (value: unknown): string =>
  typeof value === "string" ? value.trim() : typeof value === "number" ? String(value) : "";
const words = (value: unknown) => text(value).replaceAll("_", " ");
const finite = (value: unknown): number | null => {
  const number = typeof value === "string" && value.trim() ? Number(value) : value;
  return typeof number === "number" && Number.isFinite(number) ? number : null;
};

function entryTime(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value))
    return value > 1e12 ? value : value * 1000; // ms, or seconds since the epoch
  return parseControllerTime(text(value));
}
function zoneOf(value: unknown): number | null {
  const number = finite(typeof value === "string" ? value.replace(/^z(?:one)?\s*/i, "") : value);
  return number !== null && Number.isInteger(number) && number >= 1 ? number : null;
}
function probability(value: unknown): number | null {
  let p = finite(value);
  if (p === null || p < 0) return null;
  if (p > 1) p = p <= 100 ? p / 100 : null; // a percentage
  return p;
}
function agreement(value: unknown): boolean | null {
  if (typeof value === "boolean") return value;
  const word = text(value).toLowerCase();
  return word === "true" ? true : word === "false" ? false : null;
}
const RESULTS: Record<string, JevResult> = {
  acted: "acted",
  refused: "refused",
  "no action": "no action",
  waiting: "waiting",
  worked: "worked",
  "did not work": "did not work",
  "didn't work": "did not work",
};

/** One published entry, or null when it is not an object at all. */
export function parseJevEntry(raw: unknown, index = 0): JevEntry | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const item = raw as Record<string, unknown>;
  const judge = text(item.judge).toLowerCase();
  // An older controller wrote the refusal's why into the result: "refused: <why>".
  const written = text(item.result);
  const legacy = written.match(/^(refused|waiting|no[ _]action)\s*[:—-]\s*(.+)$/i);
  const resultText = (legacy ? legacy[1] : written).replaceAll("_", " ").toLowerCase();
  const reason = text(item.reason ?? item.note) || (legacy ? legacy[2].trim() : "");
  const action = text(item.action);
  const outcome =
    text(item.kind).toLowerCase() === "outcome" ||
    RESULTS[resultText] === "worked" ||
    RESULTS[resultText] === "did not work";
  let result = RESULTS[resultText] ?? "unknown";
  // A judge's alert (CS-7xx) is advice to the grower; the alert-triage judge's own call is not.
  if (result === "acted" && !outcome && judge !== "alerts" && /^CS-\d+/i.test(action))
    result = "advice";
  const title = text(item.title) || JEV_TITLES[judge] || (judge ? words(judge) : "Jev");
  return {
    key: `${index}:${text(item.t)}:${judge}`,
    time: entryTime(item.t ?? item.time),
    stamp: text(item.t ?? item.time),
    of: outcome ? text(item.of) : "",
    zone: zoneOf(item.zone),
    judge,
    title: title.charAt(0).toUpperCase() + title.slice(1),
    kind: outcome ? "outcome" : "decision",
    verdict: words(item.verdict),
    p: probability(item.p),
    agreed: agreement(item.agreed),
    action,
    result,
    resultText,
    reason,
  };
}

/** The room's live log: its one-line headline and its entries, newest first. Null when the controller
 * does not publish one (a room without Jev, or a controller from before the log). */
export function parseJevLog(
  entity: EntityState | undefined,
): { headline: string; entries: JevEntry[] } | null {
  if (!entity) return null;
  const raw = entity.attributes?.entries;
  const entries = (Array.isArray(raw) ? raw : [])
    .map((item, index) => parseJevEntry(item, index))
    .filter((entry): entry is JevEntry => entry !== null);
  // Newest first, as published; an entry without a readable time keeps its place at the end.
  const order = new Map(entries.map((entry, index) => [entry, index]));
  entries.sort((a, b) =>
    a.time !== null && b.time !== null
      ? b.time - a.time
      : a.time === null && b.time === null
        ? order.get(a)! - order.get(b)!
        : a.time === null
          ? 1
          : -1,
  );
  const state = text(entity.state);
  return {
    headline: ["unknown", "unavailable"].includes(state) ? "" : state,
    entries,
  };
}

export interface JevStage {
  /** Day of flower (day 1 = the first day of 12/12) and the flower's nominal length. */
  day: number | null;
  days: number | null;
  /** The owner's stage name, e.g. "flower bulk". */
  name: string;
  steering: string | null;
  stageDays: [number, number] | null;
  peak: string | null;
  poreEc: [number, number] | null;
  drybackPoints: [number, number] | null;
  runoffPct: [number, number] | null;
}
function pair(value: unknown): [number, number] | null {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const [a, b] = value.map(finite);
  if (a === null || b === null) return null;
  return a <= b ? [a, b] : [b, a];
}
/** Today's row of the stage arc, as `sensor.crop_steering_<prefix>jev` publishes it; null when the flower
 * day is unknown. */
export function parseJevStage(value: unknown): JevStage | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const stage = value as Record<string, unknown>;
  const name = words(stage.name);
  if (!name) return null;
  const day = finite(stage.day),
    days = finite(stage.days);
  return {
    day: day !== null && day >= 1 ? Math.round(day) : null,
    days: days !== null && days >= 1 ? Math.round(days) : null,
    name,
    steering: words(stage.steering).toLowerCase() || null,
    stageDays: pair(stage.stage_days),
    peak: words(stage.peak) || null,
    poreEc: pair(stage.pore_ec),
    drybackPoints: pair(stage.dryback_points),
    runoffPct: pair(stage.runoff_pct),
  };
}

export interface JevRoom {
  state: string;
  calls: number | null;
  tokens: number | null;
  errors: number | null;
  lastError: string;
  judges: string[];
  judgeErrors: Record<string, string>;
  stage: JevStage | null;
}
/** The room's Jev sensor: today's calls, tokens and errors, and today's stage. Null without one. */
export function parseJevRoom(entity: EntityState | undefined): JevRoom | null {
  if (!entity) return null;
  const a = entity.attributes ?? {};
  const count = (value: unknown) => {
    const number = finite(value);
    return number !== null && number >= 0 ? number : null;
  };
  const errors =
    a.judge_errors && typeof a.judge_errors === "object" && !Array.isArray(a.judge_errors)
      ? Object.fromEntries(
          Object.entries(a.judge_errors as Record<string, unknown>)
            .map(([key, value]) => [key, text(value)] as const)
            .filter(([, value]) => value),
        )
      : {};
  return {
    state: text(entity.state),
    calls: count(a.calls_today),
    tokens: count(a.input_tokens_today),
    errors: count(a.errors_today),
    lastError: text(a.last_error),
    judges: Array.isArray(a.judges) ? a.judges.map(text).filter(Boolean) : [],
    judgeErrors: errors,
    stage: parseJevStage(a.stage),
  };
}

export interface JevZoneJudge {
  judge: string;
  title: string;
  answer: string;
  p: number | null;
  agreed: boolean | null;
  directive: string;
  why: string;
}
/** A zone's Jev sensor: which judges act on it now ("watching" when none), and each judge's last word. */
export function parseJevZone(
  entity: EntityState | undefined,
): { acting: string[]; judges: JevZoneJudge[] } | null {
  if (!entity) return null;
  const state = text(entity.state);
  const acting =
    !state || ["watching", "unknown", "unavailable"].includes(state)
      ? []
      : state
          .split(",")
          .map((name) => name.trim().toLowerCase())
          .filter(Boolean);
  const raw = entity.attributes?.judges;
  const judges =
    raw && typeof raw === "object" && !Array.isArray(raw)
      ? Object.entries(raw as Record<string, unknown>).flatMap(([judge, value]) => {
          if (!value || typeof value !== "object") return [];
          const item = value as Record<string, unknown>;
          const verdicts =
            item.verdicts && typeof item.verdicts === "object"
              ? Object.values(item.verdicts as Record<string, unknown>)
              : [];
          const main = verdicts.find(
            (v): v is Record<string, unknown> => !!v && typeof v === "object",
          );
          return [
            {
              judge,
              title: JEV_TITLES[judge] ?? words(judge),
              answer: words(main?.answer),
              p: probability(main?.p),
              agreed: agreement(main?.agreed),
              directive: words(item.directive),
              why: text(item.why),
            },
          ];
        })
      : [];
  return { acting, judges };
}

export const jevIds = (prefix: string) => ({
  log: `sensor.crop_steering_${prefix}jev_log`,
  room: `sensor.crop_steering_${prefix}jev`,
  zone: (zone: number) => `sensor.crop_steering_${prefix}zone_${zone}_jev`,
});
/** Everything the page shows of Jev for one room, read from the live states. */
export function readJev(states: States, prefix: string) {
  const ids = jevIds(prefix);
  return { log: parseJevLog(states[ids.log]), room: parseJevRoom(states[ids.room]) };
}

/** Workers AI input at $0.042 per million tokens; output is free (docs/JEV.md). */
export const JEV_USD_PER_MILLION = 0.042;
export function jevCost(tokens: number | null): string | null {
  if (tokens === null) return null;
  const usd = (tokens * JEV_USD_PER_MILLION) / 1e6;
  return usd < 0.01 ? "under $0.01" : `≈ $${usd < 1 ? usd.toFixed(2) : usd.toFixed(1)}`;
}

export type JevTone = "on" | "off" | "warn" | "water" | "neutral";
/** The result pill's words and colour. Filled on the day chart only when code acted. */
export function jevResult(entry: JevEntry): { label: string; tone: JevTone; acted: boolean } {
  switch (entry.result) {
    case "acted":
      return { label: "Acted", tone: "on", acted: true };
    case "advice":
      return { label: "Advice", tone: "water", acted: false };
    case "refused":
      return { label: "Refused", tone: "warn", acted: false };
    case "no action":
      return { label: "No action", tone: "neutral", acted: false };
    case "waiting":
      return { label: "Waiting", tone: "neutral", acted: false };
    case "worked":
      return { label: "Worked", tone: "on", acted: false };
    case "did not work":
      return { label: "Didn’t work", tone: "off", acted: false };
    default:
      return {
        label: entry.resultText
          ? entry.resultText.charAt(0).toUpperCase() + entry.resultText.slice(1)
          : "Unknown",
        tone: "neutral",
        acted: false,
      };
  }
}

/** Jev's answer with how sure it was: "below band vegetative, 72%". */
export function jevAnswer(entry: Pick<JevEntry, "verdict" | "p">): string {
  const verdict = entry.verdict || "no answer";
  return entry.p === null ? verdict : `${verdict}, ${Math.round(entry.p * 100)}%`;
}

/** The two setpoints Jev's Setpoints judge may move on a zone. */
export const JEV_SETPOINTS = ["p2_shot_size", "p2_vwc_threshold"] as const;
export type JevSetpointKey = (typeof JEV_SETPOINTS)[number];
export interface JevSetpoints {
  /** Jev moves these setpoints tonight (Auto setpoints on, no grow plan holding them). */
  managed: boolean;
  /** The grower's own value: the middle of each range. */
  home: Partial<Record<JevSetpointKey, number>>;
  /** How far Jev may move each one. */
  range: Partial<Record<JevSetpointKey, [number, number]>>;
  current: Partial<Record<JevSetpointKey, number>>;
  /** Jev's last change, in its own words ("2026-09-28 22:30: P2 shot 5% -> 4.5%"). */
  last: string | null;
  /** A rescue shot after a change put it back: Jev leaves the zone alone until then (epoch ms). */
  pausedUntil: number | null;
}
/** A zone Jev sensor's `setpoints` attribute; null from a controller before it. */
export function parseJevSetpoints(entity: EntityState | undefined): JevSetpoints | null {
  const raw = entity?.attributes?.setpoints;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const item = raw as Record<string, unknown>;
  const numbers = (value: unknown) =>
    Object.fromEntries(
      JEV_SETPOINTS.flatMap((key) => {
        const number =
          value && typeof value === "object"
            ? finite((value as Record<string, unknown>)[key])
            : null;
        return number === null ? [] : [[key, number]];
      }),
    ) as Partial<Record<JevSetpointKey, number>>;
  const ranges = Object.fromEntries(
    JEV_SETPOINTS.flatMap((key) => {
      const band =
        item.range && typeof item.range === "object"
          ? pair((item.range as Record<string, unknown>)[key])
          : null;
      return band ? [[key, band]] : [];
    }),
  ) as Partial<Record<JevSetpointKey, [number, number]>>;
  const paused = item.paused_until ?? item.frozen_until;
  return {
    managed: item.managed === true,
    home: numbers(item.home),
    range: ranges,
    current: numbers(item.current),
    last: text(item.last) || null,
    pausedUntil: paused === null || paused === undefined ? null : entryTime(paused),
  };
}

/** What a decision changed, when it changed something: a phase brought forward, a setpoint moved, a
 * probe set aside, the EC steer's mode, or an alert raised. Null for everything else (no action,
 * waiting, refused, an outcome, and a setpoint the grower set by hand, which Jev only noted). */
export type JevChange = "phase" | "setpoint" | "probe" | "ec" | "alert" | "other";
export function jevChange(entry: JevEntry): JevChange | null {
  if (entry.kind !== "decision") return null;
  const action = entry.action.toLowerCase();
  if (entry.result === "advice") return /^cs-\d+/.test(action) ? "alert" : null;
  if (entry.result !== "acted" || !action) return null;
  if (entry.judge === "alerts" || /^cs-\d+/.test(action)) return "alert";
  if (entry.judge === "setpoints") return entry.verdict === "set by hand" ? null : "setpoint";
  if (
    /^(start the ramp|hand over to maintenance|end the day's watering|move to p[0-3])/.test(action)
  )
    return "phase";
  if (action.startsWith("set the probe aside")) return "probe";
  if (action.includes("ec steer")) return "ec";
  return "other";
}
/** A change in a few words. An alert triage entry names its code, its title and how it was sent. */
export function jevChangeText(entry: JevEntry): string {
  if (entry.judge === "alerts") {
    const [code, how] = entry.action.split(/:\s*/, 2);
    return `${code}: ${entry.reason || "alert"}${how ? ` (${how})` : ""}`;
  }
  return entry.action.replaceAll("->", "→");
}
/** The decisions since `since` that changed something, newest first. One alert raised twice (by
 * its judge, then by the triage that sent it) is one change. */
export function jevChanges(entries: readonly JevEntry[], since: number): JevEntry[] {
  const seen = new Set<string>();
  return entries.filter((entry) => {
    if (entry.time === null || entry.time < since || !jevChange(entry)) return false;
    const code = jevChange(entry) === "alert" ? entry.action.match(/^CS-\d+/i)?.[0] : undefined;
    if (!code) return true;
    const key = `${entry.zone}:${code.toUpperCase()}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** Outcome entries attached to the decision each checks: same judge and zone, and `of` naming the
 * decision's time. `rest` keeps the entries, newest first, without the attached outcomes; an
 * outcome that names no decision on the list stays in it, on a row of its own. */
export function attachOutcomes(entries: readonly JevEntry[]): {
  rest: JevEntry[];
  outcomes: Map<string, JevEntry[]>;
} {
  const outcomes = new Map<string, JevEntry[]>();
  const attached = new Set<JevEntry>();
  const decisions = entries.filter((entry) => entry.kind === "decision");
  for (const outcome of entries) {
    if (outcome.kind !== "outcome" || !outcome.of) continue;
    // To the minute or to the second: both name the same decision.
    const at = entryTime(outcome.of) ?? entryTime(`${outcome.of}:00`);
    const decision = decisions.find(
      (entry) =>
        entry.judge === outcome.judge &&
        entry.zone === outcome.zone &&
        (entry.stamp === outcome.of || (at !== null && entry.time === at)),
    );
    if (!decision) continue;
    outcomes.set(decision.key, [...(outcomes.get(decision.key) ?? []), outcome]);
    attached.add(outcome);
  }
  return { rest: entries.filter((entry) => !attached.has(entry)), outcomes };
}
/** An outcome in words for its badge: what it checked, and how it turned out. */
export function outcomeText(outcome: JevEntry): string {
  const worked = outcome.result === "worked";
  const what = outcome.verdict ? `After “${outcome.verdict}”: ` : "";
  return `${what}${worked ? "worked" : "did not work"}${outcome.reason ? `. ${outcome.reason}` : ""}`;
}
