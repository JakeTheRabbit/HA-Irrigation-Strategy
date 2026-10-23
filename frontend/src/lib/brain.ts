import { useSyncExternalStore } from "react";
import { HEARTBEAT_STALE_MS, parseControllerTime } from "./controller-health";
import { attachOutcomes, JEV_TITLES, jevIds, type JevEntry } from "./jev";
import { roomStatus } from "./model";
import type { CsEvent } from "./parity-types";
import type { Controller, EntityState, Room, States } from "./types";
import { formatClock } from "./clock";

/** The AI assistant's panel, read from the room's brain sensor `sensor.crop_steering_<prefix>jev` (its id is
 * kept for upgraded installs). The controller publishes it on every provider, under rules too
 * (brain_bridge.panel and publish_rules). `key_set` is the only word about the key this page reads: the key
 * itself lives in the controller's options, which the page never reads. */

export interface BrainDecision {
  time: number | null;
  zone: number | null;
  judge: string;
  answer: string;
  p: number | null;
  agreed: boolean | null;
  result: string;
  why: string;
}

/** One difference code found between the grower's plan and the room (plan_adherence.panel). */
export interface BrainPlanDrift {
  kind: string;
  zone: number | null;
  line: string;
  suggestion: string;
  why: string;
  /** advise, acted (the controller applied today's plan day) or would act (advising only). */
  action: string;
}
/** Whether the room runs its grow plan: the `plan` attribute, published under every brain. Null with no plan. */
export interface BrainPlan {
  status: string;
  headline: string;
  bridged: boolean;
  drifts: BrainPlanDrift[];
}

export interface BrainPanel {
  /** rules, claude_haiku or jev_legacy; "" from a controller before the AI assistant. */
  provider: string;
  model: string | null;
  /** acting or dry_run; null under rules. */
  mode: string | null;
  /** Why the brain is where it is: every value but acting, dry_run and legacy means rules run. */
  state: string;
  stateWords: string;
  fallbackSince: number | null;
  keySet: boolean | null;
  spentUsd: number | null;
  budgetUsd: number | null;
  budgetLeftUsd: number | null;
  projectedUsd: number | null;
  resetsAt: number | null;
  calls: number | null;
  cacheHitRatio: number | null;
  lastDecision: BrainDecision | null;
  judgesActing: string[];
  judgesAdvising: string[];
  declined: string[];
  notice: string;
  deprecatedRoute: boolean;
  plan: BrainPlan | null;
}

const text = (value: unknown): string =>
  typeof value === "string" ? value.trim() : typeof value === "number" ? String(value) : "";
const finite = (value: unknown): number | null => {
  const number = typeof value === "string" && value.trim() ? Number(value) : value;
  return typeof number === "number" && Number.isFinite(number) ? number : null;
};
const amount = (value: unknown) => {
  const number = finite(value);
  return number !== null && number >= 0 ? number : null;
};
const names = (value: unknown) =>
  Array.isArray(value) ? value.map((item) => text(item).toLowerCase()).filter(Boolean) : [];
function when(value: unknown): number | null {
  const stamp = text(value);
  if (!stamp) return null;
  return parseControllerTime(stamp) ?? parseControllerTime(`${stamp}:00`) ?? null;
}

/** The states in which the brain judges the room; every other one is rules. */
export const BRAIN_JUDGING = ["acting", "dry_run", "legacy"];

/** The brain sensor as the panel reads it; null without one. A sensor from a controller before the panel
 * (no `state` attribute) reads from its entity state: "rules" is rules, "error" is not answering, anything
 * else is the first AI route, the only brain those controllers had. */
export function parseBrainPlan(value: unknown): BrainPlan | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const p = value as Record<string, unknown>;
  const headline = text(p.headline);
  if (!headline) return null;
  const drifts = (Array.isArray(p.drifts) ? p.drifts : [])
    .filter((d): d is Record<string, unknown> => !!d && typeof d === "object" && !Array.isArray(d))
    .map((d) => {
      const zone = finite(d.zone);
      return {
        kind: text(d.class),
        zone: zone !== null && Number.isInteger(zone) && zone >= 1 ? zone : null,
        line: text(d.line),
        suggestion: text(d.suggestion),
        why: text(d.why),
        action: text(d.action) || "advise",
      };
    })
    .filter((d) => d.line);
  return { status: text(p.status), headline, bridged: p.bridged === true, drifts };
}

export function parseBrainPanel(entity: EntityState | undefined): BrainPanel | null {
  if (!entity) return null;
  const a = entity.attributes ?? {};
  const sensor = text(entity.state);
  const state =
    text(a.state) ||
    (sensor === "rules" ? "rules" : sensor === "error" ? "unavailable" : "legacy");
  const decision = a.last_decision;
  let lastDecision: BrainDecision | null = null;
  if (decision && typeof decision === "object" && !Array.isArray(decision)) {
    const d = decision as Record<string, unknown>;
    const zone = finite(text(d.zone).replace(/^z(?:one)?\s*/i, ""));
    const p = finite(d.p);
    lastDecision = {
      time: when(d.time),
      zone: zone !== null && Number.isInteger(zone) && zone >= 1 ? zone : null,
      judge: text(d.judge).toLowerCase(),
      answer: text(d.answer).replaceAll("_", " "),
      p: p !== null && p >= 0 && p <= 1 ? p : null,
      agreed: typeof d.agreed === "boolean" ? d.agreed : null,
      result: text(d.result).replaceAll("_", " ").toLowerCase(),
      why: text(d.why),
    };
  }
  return {
    provider: text(a.provider) || (state === "rules" ? "rules" : ""),
    model: text(a.model) || null,
    mode: text(a.mode) || null,
    state,
    stateWords: text(a.state_words),
    fallbackSince: when(a.fallback_since),
    keySet: typeof a.key_set === "boolean" ? a.key_set : null,
    spentUsd: amount(a.spent_usd ?? a.cost_usd_today),
    budgetUsd: amount(a.budget_usd),
    budgetLeftUsd: amount(a.budget_left_usd),
    projectedUsd: amount(a.projected_usd),
    resetsAt: when(a.resets_at),
    calls: amount(a.calls_today),
    cacheHitRatio: amount(a.cache_hit_ratio),
    lastDecision,
    judgesActing: names(a.judges_acting),
    judgesAdvising: names(a.judges_advising),
    declined: names(a.declined),
    notice: text(a.notice),
    deprecatedRoute: a.deprecated_route === true,
    plan: parseBrainPlan(a.plan),
  };
}

export type BrainTone = "positive" | "info" | "warning" | "neutral";
export interface BrainView {
  /** The header chip's words. */
  chip: string;
  headline: string;
  body: string;
  tone: BrainTone;
  /** One line for judges it would not answer; null when none. */
  declined: string | null;
}

/** What each judge may change when it acts (its name: judgeTitle). */
export const BRAIN_JUDGES: Record<string, { may: string }> = {
  dawn: {
    may: "Start filling earlier, never later than the rules would, within the morning-dryback window",
  },
  ramp: {
    may: "Stop filling and start holding earlier, once the minimum filling shots are in",
  },
  dusk: {
    may: "Stop daytime shots earlier, within limits; never for a zone steered vegetative",
  },
  salt: {
    may: "The mode of the EC steer (steer, hold or ease back), inside the limits of the controller",
  },
  probe: {
    may: "Leave a probe out of the zone reading for 90 min unless renewed",
  },
  setpoints: {
    may: "Shot size or re-water point, one small step a day, only with Auto setpoints on",
  },
  shot: { may: "Flags shots that did not land" },
  night: {
    may: "Flags real drying against a probe fault near the floor; the rescue shot fires either way",
  },
  zones: { may: "Flags a zone drinking very differently" },
  stage: { may: "Flags a zone off its stage's plan" },
  plan: {
    may: "Says what a drift from the grower's plan means; applies today's plan day only while a stale probe holds it",
  },
  alerts: { may: "Adds one line to an alert card" },
};
/** What the AI assistant may do in a room, in the integration's order (const.AI_POWERS): one switch each,
 * `switch.crop_steering_<prefix>ai_power_<key>`. With a power off, the AI assistant only advises on it. */
export const AI_POWERS = [
  { key: "advance_phase", label: "Start the next phase early", default: true },
  { key: "ramp_control", label: "End the morning ramp", default: true },
  { key: "set_probe_aside", label: "Set a probe aside", default: true },
  { key: "ec_mode", label: "Change the EC steer", default: true },
  { key: "nudge_setpoints", label: "Adjust maintenance watering", default: true },
  { key: "plan_catch_up", label: "Apply today's plan day", default: true },
  {
    key: "set_targets_from_achievable",
    label: "Set targets from what a zone reaches",
    default: false,
  },
  { key: "tune_shot_sizes", label: "Tune shot sizes", default: false },
] as const;
export type AiPowerKey = (typeof AI_POWERS)[number]["key"];
export const aiPowerId = (prefix: string, key: string) =>
  `switch.crop_steering_${prefix}ai_power_${key}`;
export interface AiPower {
  key: AiPowerKey;
  label: string;
  entityId: string;
  /** The switch's state; the default while the switch is missing. */
  on: boolean;
  default: boolean;
  /** No usable switch (an integration before the powers, or unavailable): shown at its default, read-only. */
  missing: boolean;
}
/** The room's powers from their switches, the one source of truth; a missing switch reads as its default. */
export function parsePowers(states: States, prefix: string): AiPower[] {
  return AI_POWERS.map((power) => {
    const entityId = aiPowerId(prefix, power.key);
    const state = states[entityId]?.state;
    const missing = state !== "on" && state !== "off";
    return {
      key: power.key,
      label: power.label,
      entityId,
      on: missing ? power.default : state === "on",
      default: power.default,
      missing,
    };
  });
}
/** The judges Settings › AI assistant lists, in the controller's order (brain_bridge.ALL, less the ones
 * that only write reports or answers). `act`: the judge can change something, through its power's switch
 * (brain_bridge.JUDGE_POWER); with the power off it only advises. `alerts` and `advice` judges have no
 * switch: the controller's ai_judges option decides whether they are asked, and an acting judge that
 * option leaves out is not asked either, whatever its switch. */
export const JUDGES: {
  id: string;
  blurb: string;
  power: "act" | "alerts" | "advice";
  powerKey?: AiPowerKey;
}[] = [
  { id: "dawn", blurb: "Starts the morning ramp sooner when the night dryback is big enough.", power: "act", powerKey: "advance_phase" },
  { id: "ramp", blurb: "Ends the ramp once the slab is full, not when new feed passes the probe.", power: "act", powerKey: "ramp_control" },
  { id: "salt", blurb: "Lets EC stacking move the re-water point, hold it or move it back.", power: "act", powerKey: "ec_mode" },
  { id: "dusk", blurb: "Stops the day's shots early on generative zones.", power: "act", powerKey: "advance_phase" },
  { id: "probe", blurb: "Sets a stuck, drifting or misplaced probe aside.", power: "act", powerKey: "set_probe_aside" },
  { id: "shot", blurb: "Checks 20 min after each shot that the water reached the slab.", power: "alerts" },
  { id: "night", blurb: "Tells a dry slab from a bad probe near the rescue floor.", power: "alerts" },
  { id: "zones", blurb: "Explains a zone drinking far more or less than the others.", power: "alerts" },
  { id: "channel", blurb: "Spots water running past the slab or the probe.", power: "alerts" },
  { id: "stage", blurb: "Checks today's dryback and pore EC suit the stage.", power: "advice" },
  { id: "setpoints", blurb: "Moves one setting one step each night, inside your range.", power: "act", powerKey: "nudge_setpoints" },
  { id: "balance", blurb: "Suggests moving tomorrow's water toward the room's.", power: "advice" },
  { id: "targets", blurb: "Writes tomorrow's field capacity, peak, re-water and dryback targets.", power: "act", powerKey: "set_targets_from_achievable" },
  { id: "shotsize", blurb: "Writes ramp and maintenance shot sizes after lights-off.", power: "act", powerKey: "tune_shot_sizes" },
  { id: "plan", blurb: "Applies today's plan day while a stale probe holds the plan.", power: "act", powerKey: "plan_catch_up" },
];

export interface JudgeCell {
  on: boolean;
  /** The power switch this cell writes; null where the judge has no switch in the room. */
  entityId: string | null;
  /** Shown in place of a working switch: why there is none, or why it never asks here. */
  note?: string;
}
export interface JudgeRow {
  id: string;
  name: string;
  blurb: string;
  power: "act" | "alerts" | "advice";
  /** The other judge on the same power switch: one switch turns both. */
  shares?: string;
  /** What else decides whether its switch does anything (shown on the switch). */
  hint?: string;
  /** The Capabilities feature of its power switch (`ai_power_<key>`), on the first judge of that
   * switch only: a "?feature=" link lands on this row. */
  feature?: string;
  perRoom: Record<string, JudgeCell>;
}

/** Always asked whatever ai_judges says (brain_bridge.POWER_JUDGES), or never in the room's judge list (the
 * grow plan is a task, not a judge). Targets and Shot sizes: their switches alone decide. The grow plan runs
 * only when ai_judges names plan (brain_bridge.build), which no published list shows: its switch says so. */
const ALWAYS_ASKED = ["targets", "shotsize", "plan"];
const PLAN_HINT = "Also needs plan in the controller app's judge list (ai_judges), as it is by default";
/** Every judge, with one cell per room: a judge that can act is its power's switch (missing: "No switch";
 * left out of the room's published judge list: "Not asked"; Pore EC where EC stacking is off: "stacking
 * off"); an alert or advice judge is on when the room's brain sensor lists it among the judges it asks,
 * read only. */
export function judgeMatrix(states: States, rooms: Room[]): JudgeRow[] {
  return JUDGES.map((judge) => {
    const partner = judge.powerKey
      ? JUDGES.find((other) => other !== judge && other.powerKey === judge.powerKey)
      : undefined;
    const perRoom = Object.fromEntries(
      rooms.map((room): [string, JudgeCell] => {
        const asked = states[jevIds(room.prefix).room]?.attributes.judges;
        if (judge.powerKey) {
          const entityId = aiPowerId(room.prefix, judge.powerKey);
          const state = states[entityId]?.state;
          if (state !== "on" && state !== "off") return [room.id, { on: false, entityId: null, note: "No switch" }];
          if (Array.isArray(asked) && !ALWAYS_ASKED.includes(judge.id) && !asked.includes(judge.id))
            return [room.id, { on: false, entityId: null, note: "Not asked" }];
          const stacking = states[`switch.crop_steering_${room.prefix}ec_stacking_enabled`]?.state;
          if (judge.id === "salt" && stacking === "off")
            return [room.id, { on: false, entityId, note: "stacking off" }];
          return [room.id, { on: state === "on", entityId }];
        }
        return [
          room.id,
          Array.isArray(asked)
            ? { on: asked.includes(judge.id), entityId: null, note: "Set in the controller app" }
            : { on: false, entityId: null, note: "Not reported" },
        ];
      }),
    );
    const { powerKey: _power, ...row } = judge;
    const feature =
      judge.powerKey && JUDGES.find((other) => other.powerKey === judge.powerKey) === judge
        ? `ai_power_${judge.powerKey}`
        : undefined;
    return {
      ...row,
      ...(feature ? { feature } : {}),
      name: judgeTitle(judge.id),
      ...(partner ? { shares: judgeTitle(partner.id) } : {}),
      ...(judge.id === "plan" ? { hint: PLAN_HINT } : {}),
      perRoom,
    };
  });
}

/** A cell whose state is known: a switch, or a judge the controller lists. */
export const judgeKnown = (cell: JudgeCell) =>
  cell.note === undefined || cell.note === "Set in the controller app";
/** "k of n on": over the cells with a known state. */
export function judgeCount(rows: JudgeRow[]): { on: number; of: number } {
  const cells = rows.flatMap((row) => Object.values(row.perRoom)).filter(judgeKnown);
  return { on: cells.filter((cell) => cell.on).length, of: cells.length };
}

/** Whether a judge switch moved since this page wrote `written` to it, so Undo must not put it back. The
 * write's read-back proved the value; until Home Assistant sends that state, the entity is still the one
 * from before the write (`before`, its last_updated then), which is no newer change. */
export function undoStale(entity: EntityState | undefined, written: boolean, before: string | undefined) {
  if (!entity) return true;
  if (entity.state === (written ? "on" : "off")) return false;
  return entity.last_updated !== before;
}

/** One thing the AI assistant did, and what its check found. */
export interface AiOutcome {
  id: string;
  /** When it decided (epoch ms). */
  at: number;
  roomId: string;
  zone: number | null;
  judge: string;
  /** What it did, as the controller wrote it. */
  text: string;
  /** What the check found; "" while it is still measuring, or when nothing checks it. */
  result: string;
  /** "not checked": the judge has no later check (only ramp, salt, dusk, setpoints, targets and plan do). */
  verdict: "worked" | "measuring" | "did not work" | "not checked";
  /** The target band and the value the check read, only when the controller sent both. */
  band: [number, number] | null;
  value: number | null;
}

/** Judges whose decisions the controller checks later: outcome_after_min (ramp 60, salt 240, dusk 120,
 * setpoints and targets 1440 min) and the grow plan's 6 h check. Any other decision never gets an outcome. */
const CHECKED = ["ramp", "salt", "dusk", "setpoints", "targets", "plan"];
const pending = (judge: string): AiOutcome["verdict"] => (CHECKED.includes(judge) ? "measuring" : "not checked");

/** Ledger labels the controller records as engine words (brain_bridge: the grow plan's "catch_up"). */
const ACTION_WORDS: Record<string, string> = { catch_up: "Applied today's plan day" };

const ledgerOf = (event: CsEvent) => {
  const id = event.correlation?.ledger_id;
  return id === null || id === undefined || id === "" ? null : `${event.room_id}|${id}`;
};

/** The AI assistant's decisions from the Journal (`ai.judgement`), each with the `ai.outcome` that judges
 * it, newest first. An outcome names its decision's ledger row (correlation.ledger_id); one without a
 * ledger id goes to the next decision without one in the same room, zone and judge (source.detail). Refused
 * decisions changed nothing and are left out. */
export function outcomes(events: readonly CsEvent[]): AiOutcome[] {
  const sorted = [...events]
    .filter((e) => e.kind === "ai.judgement" || e.kind === "ai.outcome")
    .sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts));
  const used = new Set<string>();
  const rows: AiOutcome[] = [];
  sorted.forEach((event, index) => {
    if (event.kind !== "ai.judgement") return;
    const data = event.data;
    if (event.outcome === "refused" || data.action === "refused") return;
    const ledger = ledgerOf(event);
    const found = sorted.slice(index + 1).find(
      (other) =>
        other.kind === "ai.outcome" &&
        !used.has(other.id) &&
        (ledger
          ? ledgerOf(other) === ledger
          : !ledgerOf(other) &&
            other.room_id === event.room_id &&
            other.zone === event.zone &&
            other.source.detail === event.source.detail),
    );
    if (found) used.add(found.id);
    const good = found?.data.good;
    const band = found?.data.band;
    const value = finite(found?.data.value);
    const bandOk =
      Array.isArray(band) && band.length === 2 && band.every((n) => finite(n) !== null) && value !== null;
    const judge = text(data.judge) || text(event.source.detail);
    rows.push({
      id: event.id,
      at: Date.parse(event.ts),
      roomId: event.room_id,
      zone: event.zone,
      judge,
      text: ACTION_WORDS[text(data.label)] ?? (text(data.label) || text(data.action)).replaceAll("_", " "),
      result: found ? text(found.data.what) : "",
      verdict: good === true ? "worked" : good === false ? "did not work" : pending(judge),
      band: bandOk ? [Number(band[0]), Number(band[1])] : null,
      value: bandOk ? value : null,
    });
  });
  return rows.reverse();
}

/** The same rows from a 3.17 room's decision log (sensor.crop_steering_<prefix>jev_log): each decision
 * that acted, with the outcome entry that names it (`of`: its stamp, or its time before 3.4). Advice is
 * left out: nothing checks it, and so is any decision before `since`. */
export function outcomesFromLog(entries: readonly JevEntry[], roomId: string, since = -Infinity): AiOutcome[] {
  const attached = attachOutcomes(entries).outcomes;
  return entries
    .filter((e) => e.kind === "decision" && e.time !== null && e.time >= since && e.result === "acted")
    .map((e) => {
      const found = attached.get(e.key)?.[0];
      return {
        id: `${roomId}|${e.key}`,
        at: e.time!,
        roomId,
        zone: e.zone,
        judge: e.judge,
        text: e.action || e.verdict,
        result: found ? found.verdict || found.reason : "",
        verdict:
          found?.result === "worked" ? "worked" : found?.result === "did not work" ? "did not work" : pending(e.judge),
        band: null,
        value: null,
      };
    });
}

export const judgeTitle = (judge: string) =>
  JEV_TITLES[judge] ??
  (judge ? judge.charAt(0).toUpperCase() + judge.slice(1).replaceAll("_", " ") : "Judge");

/** The model the controller prices (brain/client.py PRICES), also after a router prefix; null for any other. */
const PRICED = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"];
export const modelKey = (model: string) => {
  const name = model.slice(model.lastIndexOf("/") + 1);
  return PRICED.includes(name) ? name : null;
};

/** "A", "A and B", "A, B, and C". */
export const listWords = (names: readonly string[]) =>
  new Intl.ListFormat("en", { type: "conjunction" }).format(names);

/** Money in dollars, never tokens. */
export const money = (usd: number) => `$${usd.toFixed(2)}`;
const clock = (time: number) => formatClock(time);

/** The panel in grower words (ui-spec 5.2). `stale`: the controller has stopped reporting; `wateringOff`: the
 * room's watering switch is off. Both only matter while the brain could judge. */
export function brainView(
  panel: BrainPanel | null,
  { stale = false, wateringOff = false }: { stale?: boolean; wateringOff?: boolean } = {},
): BrainView {
  const say = (chip: string, headline: string, body: string, tone: BrainTone): BrainView => ({
    chip,
    headline,
    body,
    tone,
    declined: panel?.declined.length
      ? `It would not answer the ${panel.declined
          .map((judge) => judgeTitle(judge).toLowerCase())
          .join(" and ")} check 3 times in a row; rules decide that one.`
      : null,
  });
  const rules = say(
    "AI off",
    "Watering by rules",
    "The controller waters from your probes and targets. The AI assistant is not configured. Settings › AI assistant tells how to add it.",
    "neutral",
  );
  if (!panel) return rules;
  if (BRAIN_JUDGING.includes(panel.state)) {
    if (stale)
      return say(
        "AI paused",
        "Readings too old to judge",
        "The AI stays out until the probes and the controller report again.",
        "warning",
      );
    if (wateringOff)
      return say("AI idle", "Watering is off", "Nothing for the AI to act on.", "neutral");
  }
  const since = panel.fallbackSince === null ? "" : ` since ${clock(panel.fallbackSince)}`;
  switch (panel.state) {
    case "acting":
      return say(
        "AI acting",
        "AI assistant is acting",
        "It can make small changes inside the limits below. Every change shows here.",
        "positive",
      );
    case "dry_run":
      return say(
        "AI advising",
        "AI assistant is advising only",
        "It records what it would have done. Nothing is changed.",
        "info",
      );
    case "legacy":
      return say(
        "AI acting",
        "AI assistant on the first AI route",
        "An older controller app still runs it. Update the controller app: it moves to Claude Haiku, with every judge, when it has an Anthropic key.",
        "info",
      );
    case "budget_spent": {
      const spent =
        panel.spentUsd === null
          ? "Today's budget is spent"
          : `${money(panel.spentUsd)} spent${panel.fallbackSince === null ? "" : ` at ${clock(panel.fallbackSince)}`}`;
      const reset = panel.resetsAt === null ? "" : ` at ${clock(panel.resetsAt)}`;
      return say(
        "AI paused: budget",
        "Daily AI limit reached",
        `${spent}. Rules only until lights-on${reset}.`,
        "warning",
      );
    }
    case "paused":
    case "unavailable":
      return say(
        "AI paused: not answering",
        `AI not answering${since}`,
        "The controller continues to water by its rules. The AI assistant tries again automatically.",
        "warning",
      );
    case "rules_no_key":
    case "auth_failed":
      return say(
        "AI paused: no key",
        "No working Anthropic key",
        "Add or replace the key in the controller app. Then restart the app. Until then, the rules continue.",
        "warning",
      );
    case "model_invalid":
      return say(
        "AI off",
        "This release does not know that model's price",
        panel.stateWords || "Use claude-haiku-5-5, claude-sonnet-5-5 or claude-opus-5-5.",
        "warning",
      );
    case "sdk_missing":
      return say(
        "AI off",
        "Not available on this device",
        "The AI assistant cannot run on 32-bit ARM. Rules are running.",
        "neutral",
      );
    case "brain_off":
    case "start_failed":
      return say(
        "AI off",
        "AI assistant off",
        panel.stateWords ||
          "The AI assistant could not start, so the controller uses its rules. The app log gives the cause.",
        panel.state === "start_failed" ? "warning" : "neutral",
      );
    default:
      return rules;
  }
}

/** Settings › AI assistant: which brain, in words. */
export function providerWords(panel: BrainPanel | null): string {
  switch (panel?.provider) {
    case "rules":
      return "Rules only";
    case "claude_haiku":
      return "Claude Haiku (Anthropic)";
    case "jev_legacy":
      return "First AI route (removed). Update the controller app and add an Anthropic key: it moves to Claude Haiku.";
    default:
      return "Not reported by the controller";
  }
}
/** The key's status: whether one is saved, and whether Anthropic refused it. Never the key. */
export function keyWords(panel: BrainPanel | null): string {
  if (panel?.state === "auth_failed") return "Rejected by Anthropic (check it was copied whole)";
  if (panel?.keySet === true) return "Saved in the controller";
  if (panel?.keySet === false) return "Not set";
  return "Not reported by the controller";
}
export const modeWords = (panel: BrainPanel | null) =>
  panel?.mode === "dry_run" ? "Advising only" : panel?.mode === "acting" ? "Acting" : "Not running";

/** How sure the last decision was, in words, with the number for those who want it. */
export function confidenceWords(p: number | null, agreed: boolean | null): string {
  if (p === null) return "";
  const sure = p >= 0.85 ? "Sure" : p >= 0.65 ? "Fairly sure" : "Unsure";
  const both =
    agreed === true
      ? ": both readings of the question agreed"
      : agreed === false
        ? ": the two readings of the question differed"
        : "";
  return `${sure}${both}, ${p.toFixed(2)}`;
}

/** The demo's brain states (ui-spec 7), so every panel state can be seen without a controller. */
export const BRAIN_DEMO_STATES = [
  ["rules", "Rules only"],
  ["acting", "Acting"],
  ["advising", "Advising"],
  ["budget", "Budget reached"],
  ["not_answering", "Not answering"],
  ["no_key", "No key"],
  ["stale", "Stale readings"],
] as const;
export type BrainDemoState = (typeof BRAIN_DEMO_STATES)[number][0];
const isDemoState = (value: string | null): value is BrainDemoState =>
  BRAIN_DEMO_STATES.some(([key]) => key === value);

/** The brain sensor the demo shows in `state`, built on the demo's own (its stage stays). */
export function demoBrainEntity(
  demo: BrainDemoState,
  base: EntityState | undefined,
  now = Date.now(),
): EntityState {
  const stamp = (offset: number) => {
    const at = new Date(now + offset);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${pad(at.getHours())}:${pad(at.getMinutes())}:00`;
  };
  const claude = {
    provider: "claude_haiku",
    model: "claude-haiku-5-5",
    mode: demo === "advising" ? "dry_run" : "acting",
    key_set: true,
    budget_usd: 1,
    spent_usd: 0.13,
    budget_left_usd: 0.87,
    projected_usd: 0.31,
    resets_at: stamp(9 * 3_600_000),
    calls_today: 142,
    cache_hit_ratio: 0.86,
    last_decision: {
      time: stamp(-40 * 60_000),
      zone: 2,
      judge: "salt",
      answer: "below_band_vegetative",
      p: 0.78,
      agreed: true,
      result: "acted",
      why: "Pore EC sits under the stage band while moisture is on target. Holding the EC steer keeps the salt where it is.",
    },
    judges_acting: ["dawn", "dusk", "probe", "ramp", "salt", "setpoints"],
    judges_advising: ["night", "shot", "stage", "zones", "alerts"],
    declined: [] as string[],
    notice: null,
    deprecated_route: false,
    fallback_since: null as string | null,
  };
  const states: Record<BrainDemoState, Record<string, unknown>> = {
    rules: {
      provider: "rules",
      model: null,
      mode: null,
      state: "rules",
      key_set: false,
      judges_acting: [],
      fallback_since: stamp(-6 * 3_600_000),
    },
    acting: { ...claude, state: "acting" },
    advising: { ...claude, state: "dry_run", judges_acting: [], declined: ["night"] },
    budget: {
      ...claude,
      state: "budget_spent",
      spent_usd: 1,
      budget_left_usd: 0,
      judges_acting: [],
      fallback_since: stamp(-2 * 3_600_000),
    },
    not_answering: {
      ...claude,
      state: "unavailable",
      judges_acting: [],
      fallback_since: stamp(-75 * 60_000),
    },
    no_key: {
      provider: "rules",
      model: null,
      mode: null,
      state: "rules_no_key",
      key_set: false,
      judges_acting: [],
    },
    stale: { ...claude, state: "acting" },
  };
  const attributes = states[demo];
  return {
    entity_id: base?.entity_id ?? "sensor.crop_steering_jev",
    state: attributes.provider === "rules" ? "rules" : "on",
    attributes: { ...(base?.attributes ?? {}), ...attributes, state_words: "" },
    last_updated: base?.last_updated ?? new Date(now).toISOString(),
    last_changed: base?.last_changed ?? new Date(now).toISOString(),
  };
}

// The demo switcher's choice, shared by every view of the brain in this tab; `?brain=` opens on a state.
let demoState: BrainDemoState = (() => {
  if (typeof window === "undefined") return "acting";
  const asked = new URLSearchParams(window.location.search).get("brain");
  return isDemoState(asked) ? asked : "acting";
})();
const listeners = new Set<() => void>();
export function setDemoBrain(state: BrainDemoState) {
  demoState = state;
  listeners.forEach((listener) => listener());
}
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};
const snapshot = () => demoState;

/** The selected room's brain, as every view of it shows it: the panel, its words, and the demo's state. */
export function useBrain(controller: Controller, now = Date.now()) {
  const demo = useSyncExternalStore(subscribe, snapshot, snapshot);
  const { states, room } = controller;
  const sensor = states[jevIds(room.room.prefix).room];
  const panel = parseBrainPanel(controller.demo ? demoBrainEntity(demo, sensor, now) : sensor);
  const reported = room.room.id ? roomStatus(states, room.room, now).reportedAt : null;
  const stale = controller.demo
    ? demo === "stale"
    : reported === null || now - reported > HEARTBEAT_STALE_MS;
  const view = brainView(panel, { stale, wateringOff: room.engine.enabled === false });
  return { panel, view, demo };
}
