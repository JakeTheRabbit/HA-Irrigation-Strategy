import { parseControllerTime } from "./controller-health";
import type { EntityState, States } from "./types";
import { growerWords } from "./words";

/** What the controller's AI assistant bridge publishes for a room (addons/f2_control/f2_control/brain_bridge.py):
 * `sensor.crop_steering_<prefix>jev_log` (every decision, newest first), `sensor.crop_steering_<prefix>jev`
 * (calls, tokens, errors and today's stage) and `sensor.crop_steering_<prefix>zone_N_jev` (what each judge
 * last said about the zone). Read tolerantly: a controller older than the log, or one entry missing a
 * field, must never break the page. */

/** Each judge's plain title, for an entry that carries none (brain/journal.py TITLES). */
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
  /** When the AI assistant decided (epoch ms); null when the entry's time could not be read. */
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
  /** The AI assistant's answer, in plain words. */
  verdict: string;
  /** How sure the council was, 0 to 1; null when not given. */
  p: number | null;
  /** Both phrasings of the question agreed. */
  agreed: boolean | null;
  /** What the AI assistant asked for, in plain words; "" when nothing. */
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
  const reason = growerWords(text(item.reason ?? item.note) || (legacy ? legacy[2].trim() : ""));
  const action = growerWords(text(item.action));
  const outcome =
    text(item.kind).toLowerCase() === "outcome" ||
    RESULTS[resultText] === "worked" ||
    RESULTS[resultText] === "did not work";
  let result = RESULTS[resultText] ?? "unknown";
  // A judge's alert (CS-7xx) is advice to the grower; the alert-triage judge's own call is not.
  if (result === "acted" && !outcome && judge !== "alerts" && /^CS-\d+/i.test(action))
    result = "advice";
  const title = text(item.title) || JEV_TITLES[judge] || (judge ? words(judge) : "AI assistant");
  return {
    key: `${index}:${text(item.t)}:${judge}`,
    time: entryTime(item.t ?? item.time),
    stamp: text(item.t ?? item.time),
    of: outcome ? text(item.of) : "",
    zone: zoneOf(item.zone),
    judge,
    title: title.charAt(0).toUpperCase() + title.slice(1),
    kind: outcome ? "outcome" : "decision",
    verdict: growerWords(words(item.verdict)),
    p: probability(item.p),
    agreed: agreement(item.agreed),
    action,
    result,
    resultText,
    reason,
  };
}

/** The room's live log: its one-line headline and its entries, newest first. Null when the controller
 * does not publish one (a room without the AI assistant, or a controller from before the log). */
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
  /** Which brain runs: claude_haiku, jev_legacy or rules ("" from a controller before the AI assistant). */
  provider: string;
  /** Why it is where it is (acting, dry_run, legacy, budget_spent, rules_no_key, ...): "" when not said. */
  brainState: string;
  stateWords: string;
  notice: string;
  deprecatedRoute: boolean;
  /** US$ the Claude brain has spent since the last lights-on; null on the legacy route. */
  costUsd: number | null;
  /** The brain is judging the room now. Every other state means the engine is on its own rules. */
  on: boolean;
}

/** The brain states in which it judges: anything else is rules (a published reason, a fallback). */
const BRAIN_ON = ["acting", "dry_run", "legacy"];

/** The room's brain sensor: today's calls, tokens and errors, today's stage, which brain runs and whether it is
 * on. The entity state alone never says that: under rules it reads "rules", and a Claude brain that has fallen back
 * keeps "on" with the reason in `state`. A sensor with no `state` attribute (an older controller) reads as before.
 * Null without one. */
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
    provider: text(a.provider),
    brainState: text(a.state),
    stateWords: text(a.state_words),
    notice: text(a.notice),
    deprecatedRoute: a.deprecated_route === true,
    costUsd: count(a.cost_usd_today),
    on:
      !["rules", "error", "unknown", "unavailable"].includes(text(entity.state)) &&
      (!text(a.state) || BRAIN_ON.includes(text(a.state))),
  };
}

/** What the pages say of the room's brain, in one place: the tile's word, its small text and the zone panel's
 * subtitle. Never "On" or "Acting now" while the engine is on its own rules. */
export function brainWords(room: JevRoom | null): {
  tile: string;
  detail: string;
  subtitle: string | null;
} {
  if (!room)
    return { tile: "Not on this room", detail: "The controller runs without it", subtitle: null };
  if (room.state === "error") return { tile: "Not answering", detail: "", subtitle: null };
  if (!room.on) {
    const why = room.stateWords || "Rules are running.";
    return { tile: "Rules", detail: why, subtitle: `Rules are running: ${why}` };
  }
  const tile =
    room.brainState === "dry_run"
      ? "Advising only"
      : room.brainState === "legacy"
        ? "On, retired route"
        : "On";
  return { tile, detail: "", subtitle: null };
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
/** A zone's AI assistant sensor: which judges act on it now ("watching" when none), and each judge's last word. */
export function parseJevZone(
  entity: EntityState | undefined,
): { acting: string[]; judges: JevZoneJudge[] } | null {
  if (!entity) return null;
  const state = text(entity.state);
  if (state === "rules" || text(entity.attributes?.provider) === "rules") return null;
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
              answer: growerWords(words(main?.answer)),
              p: probability(main?.p),
              agreed: agreement(main?.agreed),
              directive: growerWords(words(item.directive)),
              why: growerWords(text(item.why)),
            },
          ];
        })
      : [];
  return { acting, judges };
}

export const jevIds = (prefix: string) => ({
  answers: `sensor.crop_steering_${prefix}brain_answers`,
  log: `sensor.crop_steering_${prefix}jev_log`,
  room: `sensor.crop_steering_${prefix}jev`,
  zone: (zone: number) => `sensor.crop_steering_${prefix}zone_${zone}_jev`,
});
/** Everything the page shows of the AI assistant for one room, read from the live states. */
export function readJev(states: States, prefix: string) {
  const ids = jevIds(prefix);
  return { log: parseJevLog(states[ids.log]), room: parseJevRoom(states[ids.room]) };
}

/** One answer to a grower's "why" (sensor.crop_steering_<prefix>brain_answers, brain_bridge.why_task). */
export interface BrainAnswer {
  id: string;
  question: string;
  zone: number | null;
  answeredAt: number | null;
  answer: string;
  cannotAnswer: boolean;
}

/** The room's answers to "why", newest first, and how many questions are still with the brain. Null without the
 * sensor (a controller from before Ask why); an entry without an id or a question is left out. */
export function parseBrainAnswers(entity: EntityState | undefined): {
  answers: BrainAnswer[];
  pending: number;
  askedToday: number | null;
  limit: number | null;
} | null {
  if (!entity) return null;
  const a = entity.attributes ?? {};
  const answers = (Array.isArray(a.answers) ? a.answers : [])
    .filter(
      (item): item is Record<string, unknown> =>
        !!item && typeof item === "object" && !!text(item.id) && !!text(item.question),
    )
    .map((item) => ({
      id: text(item.id),
      question: text(item.question),
      zone: finite(item.zone),
      answeredAt: parseControllerTime(item.answered_at),
      answer: text(item.answer),
      cannotAnswer: item.cannot_answer === true,
    }))
    .reverse();
  return {
    answers,
    pending: Array.isArray(a.pending) ? a.pending.length : 0,
    askedToday: finite(a.asked_today),
    limit: finite(a.daily_limit),
  };
}

/** Workers AI input at $0.042 per million tokens; output is free (docs/AI_ASSISTANT.md). The legacy route only: the Claude
 * brain publishes what it spent (`cost_usd_today`), which wins. */
export const JEV_USD_PER_MILLION = 0.042;
export function jevCost(tokens: number | null, costUsd: number | null = null): string | null {
  if (tokens === null && costUsd === null) return null;
  const usd = costUsd ?? ((tokens ?? 0) * JEV_USD_PER_MILLION) / 1e6;
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

/** The AI assistant's answer with how sure it was: "below band vegetative, 72%". */
export function jevAnswer(entry: Pick<JevEntry, "verdict" | "p">): string {
  const verdict = entry.verdict || "no answer";
  return entry.p === null ? verdict : `${verdict}, ${Math.round(entry.p * 100)}%`;
}

/** The two setpoints the AI assistant's Setpoints judge may move on a zone. */
export const JEV_SETPOINTS = ["p2_shot_size", "p2_vwc_threshold"] as const;
export type JevSetpointKey = (typeof JEV_SETPOINTS)[number];
export interface JevSetpoints {
  /** The AI assistant moves these setpoints tonight (Auto setpoints on, no grow plan holding them). */
  managed: boolean;
  /** The grower's own value: the middle of each range. */
  home: Partial<Record<JevSetpointKey, number>>;
  /** How far the AI assistant may move each one. */
  range: Partial<Record<JevSetpointKey, [number, number]>>;
  current: Partial<Record<JevSetpointKey, number>>;
  /** The AI assistant's last change, in its own words ("2026-09-28 22:30: P2 shot 5% -> 4.5%"). */
  last: string | null;
  /** A rescue shot after a change put it back: the AI assistant leaves the zone alone until then (epoch ms). */
  pausedUntil: number | null;
}
/** A zone AI assistant sensor's `setpoints` attribute; null from a controller before it. */
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
    last: growerWords(text(item.last)) || null,
    pausedUntil: paused === null || paused === undefined ? null : entryTime(paused),
  };
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
