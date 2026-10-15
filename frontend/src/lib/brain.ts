import { useSyncExternalStore } from "react";
import { HEARTBEAT_STALE_MS, parseControllerTime } from "./controller-health";
import { jevIds } from "./jev";
import { roomStatus } from "./model";
import type { Controller, EntityState } from "./types";

/** The AI assistant's panel, read from the room's brain sensor `sensor.crop_steering_<prefix>jev` (its id is
 * kept for upgraded installs). The controller publishes it on every provider, under rules too
 * (jev_bridge.panel and publish_rules). `key_set` is the only word about the key this page reads: the key
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
 * else is the old Jev connection, the only brain those controllers had. */
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

/** What each judge is called, and what it may change when it acts. */
export const BRAIN_JUDGES: Record<string, { title: string; may: string }> = {
  dawn: {
    title: "Morning start",
    may: "Start filling earlier, never later than the rules would, within the morning-dryback window",
  },
  ramp: {
    title: "Filling hand-over",
    may: "Stop filling and start holding earlier, once the minimum filling shots are in",
  },
  dusk: {
    title: "Day end",
    may: "Stop daytime shots earlier, within limits; never for a zone steered vegetative",
  },
  salt: {
    title: "Pore EC",
    may: "The mode of the EC steer (steer, hold or ease back), inside the limits of the controller",
  },
  probe: {
    title: "Probe trust",
    may: "Leave a probe out of the zone reading for 90 min unless renewed",
  },
  setpoints: {
    title: "Setpoints",
    may: "Shot size or re-water point, one small step a day, only with Auto setpoints on",
  },
  shot: { title: "Shot landing", may: "Flags shots that did not land" },
  night: {
    title: "Night low",
    may: "Flags real drying against a probe fault near the floor; the rescue shot fires either way",
  },
  zones: { title: "Zone comparison", may: "Flags a zone drinking very differently" },
  stage: { title: "Stage check", may: "Flags a zone off its stage's plan" },
  plan: {
    title: "Grow plan",
    may: "Says what a drift from the grower's plan means; applies today's plan day only while a stale probe holds it",
  },
  alerts: { title: "Alert note", may: "Adds one line to an alert card" },
};
export const judgeTitle = (judge: string) =>
  BRAIN_JUDGES[judge]?.title ??
  (judge ? judge.charAt(0).toUpperCase() + judge.slice(1).replaceAll("_", " ") : "Judge");

/** Money in dollars, never tokens. */
export const money = (usd: number) => `$${usd.toFixed(2)}`;
const clock = (time: number) =>
  new Date(time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });

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
        "AI assistant on the old Jev connection",
        "It still works, but the connection is retired. Switch to Claude Haiku: same judges, one key.",
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
      return "Old Jev connection (deprecated). Switch to Claude Haiku: same judges, one key.";
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
