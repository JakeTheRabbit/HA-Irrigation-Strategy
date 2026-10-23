import type { PillTone } from "@/components/mini-visuals";
import { parseControllerTime, readHeartbeat } from "./controller-health";
import { numeric } from "./model";
import type { SetupCandidate } from "./operator-types";
import { formatVolume } from "./display-units";
import { OVER_PCT, MINIMUM_PCT, reservoirView, tankLevelId } from "./reservoir";
import { batchesLeft, type StockDocument } from "./stock";
import type { EntityState, States } from "./types";

/** Batch-tank dosing (docs/DOSING.md): a room's dosing configuration as the integration publishes
 * it, the controller's live status, and what Equipment › Dosing works out from the two. Nothing
 * here writes anything: every action is a `dosing_request` the controller carries out. */

export const MAX_PUMPS = 8;
/** The controller drops a request older than this ("too old to act on"). */
export const REQUEST_TTL_MS = 120_000;

export interface DosingPump {
  id: string;
  name: string;
  volume_entity: string;
  start_entity: string;
  dosing_entity: string;
  /** A sensor dosing entity reads dosing while its state starts with this. */
  dosing_prefix: string;
  power_entity: string;
  flow_entity: string;
  max_ml: number;
  restore_volume: boolean;
  /** The id of the room's stock tank this pump doses from, or null: the integration draws what the
   * pump runs off it, whoever starts the dose. */
  stock_tank: string | null;
  /** The pump's pH role for pH auto-correct (docs/DOSING.md): one pump per role in a room. Absent from
   * an integration from before it. */
  ph_role?: PhRole | null;
}
export type PhRole = "ph_up" | "ph_down";
export const PH_ROLE_LABELS: Record<PhRole, string> = { ph_up: "pH up", ph_down: "pH down" };
export interface RecipeLine {
  pump: string;
  ml: number;
  /** Read at batch start; it wins over `ml`. */
  ml_entity: string | null;
}
export interface DosingBatch {
  fill_valve: string | null;
  full_entity: string | null;
  full_state: string;
  fill_timeout_min: number;
  mix_pump: string | null;
  mix_valves: string[];
  mix_power_sensor: string | null;
  mix_min_w: number;
  premix_min: number;
  postmix_min: number;
  close_entities: string[];
  hold_entity: string | null;
  filled_at_entity: string | null;
  recipe: RecipeLine[];
}
export type DosingAction = "dose" | "batch" | "stop";
export interface DosingRequest {
  id: string;
  action: DosingAction;
  pump: string | null;
  ml: number | null;
  at: string | null;
  by: string | null;
}
export interface DosingConfig {
  revision: number;
  pumps: DosingPump[];
  batch: DosingBatch;
  request: DosingRequest | null;
  updated_at: string | null;
}
/** A feed recipe of the room (dosing.py clean_feed): what a batch doses while it is in use, and the
 * feed EC it mixes to (mS/cm), when declared. */
export interface FeedRecipe {
  id: string;
  name: string;
  doses: RecipeLine[];
  ec: number | null;
}
/** The room's feed recipes and the schedule of them by week, as `dosing_get` holds them. */
export interface FeedSetup {
  recipes: FeedRecipe[];
  schedule: { start: string | null; weeks: string[] };
  stage: string | null;
  held_until: string | null;
}
/** Which recipe the room doses today and why (dosing.py feed_now). */
export interface FeedNow {
  recipe: string | null;
  recipe_id: string | null;
  ec: number | null;
  week: number | null;
  weeks: number;
  start: string | null;
  held_until: string | null;
  source: "schedule" | "held" | "hand" | "batch";
}
/** What `dosing_get` and `dosing_save` answer. */
export interface DosingDocument {
  schema_version: number;
  room_id: string;
  /** `feed`: the recipes and their schedule; absent from an integration from before them. */
  config: (DosingConfig & { feed?: FeedSetup | null }) | null;
  feed_now?: FeedNow | null;
  candidates: SetupCandidate[];
  /** The user is an administrator; absent from an integration from before it. */
  can_edit?: boolean | null;
  error: string | null;
}
/** What `dosing_request` answers. */
export interface DosingRequestResult {
  request: DosingRequest | null;
  error: string | null;
}

export const BATCH_STEPS = [
  "hold",
  "close",
  "fill",
  "mix",
  "premix",
  "dose",
  "postmix",
  "finish",
] as const;
export type BatchStep = (typeof BATCH_STEPS)[number];
export interface LastDose {
  ml: number;
  at: string | null;
  result: string;
}
export interface PumpRuntime {
  state: "idle" | "dosing" | "unavailable";
  flow_ml_s: number | null;
  target_ml: number | null;
  started_at: string | null;
  expected_s: number | null;
  last: LastDose | null;
}
export interface StepRecord {
  step: BatchStep;
  state: "done" | "running" | "skipped" | "failed";
  at: string | null;
  note: string | null;
}
export interface BatchRuntime {
  step: BatchStep | "idle";
  pump: string | null;
  started_at: string | null;
  step_started_at: string | null;
  steps: StepRecord[];
  result: string | null;
  ended_at: string | null;
}
export interface HistoryEntry {
  kind: "dose" | "batch";
  at: string | null;
  ended_at: string | null;
  result: string;
  doses: Record<string, number>;
  by: string | null;
}
/** The controller's check of a finished batch's tank, read 5 min after its mix stops
 * (dosing_runner._judge_mix): its EC and pH as read, against the room's feed bands. */
export interface MixCheck {
  batch: string | null;
  due: string | null;
  verdict: "good" | "off target" | "not read" | null;
  checked_at: string | null;
  why: string | null;
  gave_up_at: string | null;
  ec: number | null;
  ph: number | null;
  /** The probes the check covered: _judge_mix sets a key only for a probe that is mapped and has a
   * band, so a probe missing here was never part of the check (a null one read nothing). */
  probes: ("ec" | "ph")[];
}
/** `sensor.crop_steering_<prefix>dosing`, the controller's report. */
export interface DosingStatus {
  state: "idle" | "dosing" | "batch" | "unavailable";
  pumps: Record<string, PumpRuntime>;
  batch: BatchRuntime;
  handled: string | null;
  handled_result: string | null;
  history: HistoryEntry[];
  /** The last batch's mix check; absent or null from a controller from before it, or with none. */
  mix?: MixCheck | null;
  /** The controller's last publish, refreshed at least every 60 s; null from a controller from
   * before it. */
  updated_at: string | null;
}

export const dosingConfigId = (prefix: string) => `sensor.crop_steering_${prefix}dosing_config`;
export const dosingStatusId = (prefix: string) => `sensor.crop_steering_${prefix}dosing`;

// Reading what Home Assistant holds: anything missing or garbled falls back, never throws.
type Raw = Record<string, unknown>;
const ENTITY = /^[a-z_]+\.[a-z0-9_]+$/;
const UNREADABLE = ["unknown", "unavailable", ""];
const record = (value: unknown): Raw =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Raw) : {};
const text = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value : null;
const entityId = (value: unknown): string | null =>
  typeof value === "string" && ENTITY.test(value) ? value : null;
const entityIds = (value: unknown): string[] =>
  Array.isArray(value) ? value.flatMap((item) => entityId(item) ?? []) : [];
const count = (value: unknown): number | null => {
  const parsed =
    typeof value === "number"
      ? value
      : typeof value === "string" && value.trim()
        ? Number(value)
        : Number.NaN;
  return Number.isFinite(parsed) ? parsed : null;
};

function parsePump(value: unknown): DosingPump | null {
  const raw = record(value);
  const id = typeof raw.id === "string" && /^[a-z0-9_]{1,24}$/.test(raw.id) ? raw.id : null;
  if (!id) return null;
  return {
    id,
    name: text(raw.name)?.trim() ?? id,
    volume_entity: entityId(raw.volume_entity) ?? "",
    start_entity: entityId(raw.start_entity) ?? "",
    dosing_entity: entityId(raw.dosing_entity) ?? "",
    dosing_prefix: text(raw.dosing_prefix) ?? "Dosing",
    power_entity: entityId(raw.power_entity) ?? "",
    flow_entity: entityId(raw.flow_entity) ?? "",
    max_ml: count(raw.max_ml) ?? 0,
    restore_volume: raw.restore_volume !== false,
    stock_tank: text(raw.stock_tank)?.trim() ?? null,
    ph_role: raw.ph_role === "ph_up" || raw.ph_role === "ph_down" ? raw.ph_role : null,
  };
}
function parseBatch(value: unknown): DosingBatch {
  const raw = record(value);
  return {
    fill_valve: entityId(raw.fill_valve),
    full_entity: entityId(raw.full_entity),
    full_state: text(raw.full_state) ?? "on",
    fill_timeout_min: count(raw.fill_timeout_min) ?? 20,
    mix_pump: entityId(raw.mix_pump),
    mix_valves: entityIds(raw.mix_valves),
    mix_power_sensor: entityId(raw.mix_power_sensor),
    mix_min_w: Math.max(0, count(raw.mix_min_w) ?? 0),
    premix_min: Math.max(0, count(raw.premix_min) ?? 0),
    postmix_min: Math.max(0, count(raw.postmix_min) ?? 0),
    close_entities: entityIds(raw.close_entities),
    hold_entity: entityId(raw.hold_entity),
    filled_at_entity: entityId(raw.filled_at_entity),
    recipe: (Array.isArray(raw.recipe) ? raw.recipe : []).flatMap((item) => {
      const line = record(item);
      return typeof line.pump === "string" && line.pump
        ? [
            {
              pump: line.pump,
              ml: Math.max(0, count(line.ml) ?? 0),
              ml_entity: entityId(line.ml_entity),
            },
          ]
        : [];
    }),
  };
}
function parseRequest(value: unknown): DosingRequest | null {
  const raw = record(value);
  const action = (["dose", "batch", "stop"] as const).find((item) => item === raw.action);
  if (!text(raw.id) || !action) return null;
  return {
    id: String(raw.id),
    action,
    pump: text(raw.pump),
    ml: count(raw.ml),
    at: text(raw.at),
    by: text(raw.by),
  };
}
/** A configuration as `dosing_get` returns it; null when there is none. */
export function parseConfig(value: unknown): DosingConfig | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Raw;
  const seen = new Set<string>();
  const pumps = (Array.isArray(raw.pumps) ? raw.pumps : []).flatMap((item) => {
    const pump = parsePump(item);
    if (!pump || seen.has(pump.id)) return [];
    seen.add(pump.id);
    return [pump];
  });
  return {
    revision: count(raw.revision) ?? 0,
    pumps: pumps.slice(0, MAX_PUMPS),
    batch: parseBatch(raw.batch),
    request: parseRequest(raw.request),
    updated_at: text(raw.updated_at),
  };
}
/** The integration's `dosing_config` sensor: its state is the revision. */
export function readConfig(entity: EntityState | undefined): DosingConfig | null {
  if (!entity || UNREADABLE.includes(entity.state)) return null;
  return parseConfig({ ...entity.attributes, revision: entity.state });
}
/** The controller's `dosing` sensor; null when the controller has never posted it. */
export function readStatus(entity: EntityState | undefined): DosingStatus | null {
  if (!entity) return null;
  const raw = entity.attributes ?? {};
  const pumps: Record<string, PumpRuntime> = {};
  for (const [id, value] of Object.entries(record(raw.pumps))) {
    const pump = record(value),
      last = record(pump.last);
    const ml = count(last.ml);
    pumps[id] = {
      state: pump.state === "dosing" ? "dosing" : pump.state === "idle" ? "idle" : "unavailable",
      flow_ml_s: count(pump.flow_ml_s),
      target_ml: count(pump.target_ml),
      started_at: text(pump.started_at),
      expected_s: count(pump.expected_s),
      last: ml === null ? null : { ml, at: text(last.at), result: text(last.result) ?? "" },
    };
  }
  const batch = record(raw.batch);
  const steps = (Array.isArray(batch.steps) ? batch.steps : []).flatMap((item): StepRecord[] => {
    const step = record(item);
    const name = BATCH_STEPS.find((value) => value === step.step);
    const state = (["done", "running", "skipped", "failed"] as const).find(
      (value) => value === step.state,
    );
    return name && state ? [{ step: name, state, at: text(step.at), note: text(step.note) }] : [];
  });
  const history = (Array.isArray(raw.history) ? raw.history : []).flatMap(
    (item): HistoryEntry[] => {
      const entry = record(item);
      const kind = entry.kind === "batch" || entry.kind === "dose" ? entry.kind : null;
      if (!kind) return [];
      const doses: Record<string, number> = {};
      for (const [id, ml] of Object.entries(record(entry.doses)))
        if (count(ml) !== null) doses[id] = count(ml)!;
      return [
        {
          kind,
          at: text(entry.at),
          ended_at: text(entry.ended_at),
          result: text(entry.result) ?? "",
          doses,
          by: text(entry.by),
        },
      ];
    },
  );
  return {
    state:
      (["idle", "dosing", "batch"] as const).find((value) => value === entity.state) ??
      "unavailable",
    pumps,
    batch: {
      step: BATCH_STEPS.find((value) => value === batch.step) ?? "idle",
      pump: text(batch.pump),
      started_at: text(batch.started_at),
      step_started_at: text(batch.step_started_at),
      steps,
      result: text(batch.result),
      ended_at: text(batch.ended_at),
    },
    handled: text(raw.handled),
    handled_result: text(raw.handled_result),
    history: history.slice(0, 20),
    mix: readMix(raw.mix),
    updated_at: text(raw.updated_at),
  };
}
function readMix(value: unknown): MixCheck | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = record(value);
  const verdict = (["good", "off target", "not read"] as const).find((v) => v === raw.verdict);
  return {
    batch: text(raw.batch),
    due: text(raw.due),
    verdict: verdict ?? null,
    checked_at: text(raw.checked_at),
    why: text(raw.why),
    gave_up_at: text(raw.gave_up_at),
    ec: count(raw.ec),
    ph: count(raw.ph),
    probes: (["ec", "ph"] as const).filter((key) => key in raw),
  };
}

/** The controller refreshes its dosing report at least every 60 s: three refreshes missed, it has
 * stopped reporting. */
export const STATUS_STALE_MS = 180_000;
/** Whether the controller can act on a dosing request in this room now, and if not, why. */
export interface Reach {
  live: boolean;
  reason: string | null;
}
export function controllerReach(
  states: States,
  prefix: string,
  status: DosingStatus | null,
  now: number,
): Reach {
  // The dosing report's own time says whether it is current; a controller from before it has only
  // its heartbeat to go by.
  const updated = parseControllerTime(status?.updated_at);
  if (updated !== null) {
    if (now - updated > STATUS_STALE_MS)
      return { live: false, reason: "The controller has stopped reporting." };
  } else {
    const beat = readHeartbeat(states[`sensor.crop_steering_${prefix}ai_heartbeat`], now);
    if (beat.health === "missing" || beat.health === "unreadable")
      return { live: false, reason: "The controller is not running." };
    if (beat.health === "stale")
      return { live: false, reason: "The controller has stopped reporting." };
    if (beat.health === "stopped")
      return { live: false, reason: "The controller app has stopped." };
  }
  if (!status)
    return {
      live: false,
      reason: "The controller does not report dosing yet: update the controller app.",
    };
  if (status.state === "unavailable")
    return { live: false, reason: "The controller cannot read this room's dosing setup." };
  return { live: true, reason: null };
}

/** The pump's own report: dosing, not dosing, or null when it reports nothing. */
export function deviceDosing(pump: DosingPump, states: States): boolean | null {
  const entity = states[pump.dosing_entity];
  if (!entity || UNREADABLE.includes(entity.state)) return null;
  return pump.dosing_entity.startsWith("binary_sensor.")
    ? entity.state === "on"
    : entity.state.startsWith(pump.dosing_prefix || "Dosing");
}

export type PumpState = "idle" | "dosing" | "unavailable" | "uncalibrated";
/** A pump card's pill: dosing green, not calibrated amber, idle and unavailable grey. */
export const PUMP_STATES: Record<PumpState, { label: string; tone: PillTone }> = {
  idle: { label: "Idle", tone: "neutral" },
  dosing: { label: "Dosing", tone: "on" },
  unavailable: { label: "Unavailable", tone: "unknown" },
  uncalibrated: { label: "Not calibrated", tone: "warn" },
};
export interface DoseProgress {
  target: number;
  /** Seconds since the dose started, and the seconds it should take (ml / flow). */
  elapsed: number;
  expected: number;
  /** 0-1, elapsed against expected. */
  share: number;
  /** The estimated mL dosed so far. */
  ml: number;
  overdue: boolean;
}
/** A running dose: elapsed against expected, and the estimated mL so far. */
export function doseProgress(runtime: PumpRuntime | null, now: number): DoseProgress | null {
  if (runtime?.state !== "dosing") return null;
  const target = runtime.target_ml ?? 0;
  const started = Date.parse(runtime.started_at ?? "");
  const expected = runtime.expected_s ?? (runtime.flow_ml_s ? target / runtime.flow_ml_s : 0);
  if (!(target > 0) || !(expected > 0) || !Number.isFinite(started)) return null;
  const elapsed = Math.max(0, (now - started) / 1000);
  const share = Math.min(1, elapsed / expected);
  return { target, elapsed, expected, share, ml: target * share, overdue: elapsed > expected };
}
/** When the controller switches a pump off that is still dosing: expected × 1.25 + 20 s. */
/** The controller's limits (DOSING.md): the least flow it trusts, the longest dose it runs, and
 * the latest it lets one go before cutting the power. */
export const MIN_FLOW_ML_S = 0.05;
export const MAX_DOSE_S = 20 * 60;
export const MAX_DEADLINE_S = MAX_DOSE_S + 60;
export const doseDeadline = (expected: number) => Math.min(expected * 1.25 + 20, MAX_DEADLINE_S);

export interface PumpView {
  pump: DosingPump;
  state: PumpState;
  /** Why it is unavailable or not calibrated. */
  reason: string | null;
  /** The calibrated flow in mL/s, as its flow entity reads now. */
  flow: number | null;
  runtime: PumpRuntime | null;
  progress: DoseProgress | null;
  last: LastDose | null;
}
/** A pump as its card shows it. A pump that reports dosing is shown dosing whatever else is wrong:
 * a motor running is the one thing never hidden. */
export function pumpView(
  pump: DosingPump,
  status: DosingStatus | null,
  reach: Reach,
  states: States,
  now: number,
): PumpView {
  const runtime = status?.pumps[pump.id] ?? null;
  const flowEntity = states[pump.flow_entity];
  const flow = flowEntity ? numeric(flowEntity) : (runtime?.flow_ml_s ?? null);
  const view = (state: PumpState, reason: string | null = null): PumpView => ({
    pump,
    state,
    reason,
    flow,
    runtime,
    progress: doseProgress(runtime, now),
    last: runtime?.last ?? null,
  });
  if (runtime?.state === "dosing" || deviceDosing(pump, states) === true) return view("dosing");
  if (!reach.live) return view("unavailable", reach.reason);
  if (runtime?.state === "unavailable")
    return view("unavailable", "The controller reports this pump unavailable.");
  for (const [id, what] of [
    [pump.dosing_entity, "dosing state"],
    [pump.flow_entity, "flow"],
    [pump.volume_entity, "dose volume"],
    [pump.start_entity, "start"],
    [pump.power_entity, "power switch"],
  ] as const) {
    if (!id) return view("unavailable", `Its ${what} is not mapped.`);
    if (!states[id]) return view("unavailable", `${id} is missing in Home Assistant.`);
    if (states[id].state === "unavailable") return view("unavailable", `${id} is unavailable.`);
  }
  if (deviceDosing(pump, states) === null)
    return view("unavailable", `${pump.dosing_entity} reports nothing.`);
  if (!(flow !== null && flow >= MIN_FLOW_ML_S))
    return view(
      "uncalibrated",
      flow === null
        ? `Its flow (${pump.flow_entity}) reads nothing: calibrate it before dosing.`
        : `Its flow reads ${flow} mL/s: calibrate it before dosing.`,
    );
  return view("idle");
}

/** The device name the pump's entities share ("doser_1_silica"), else its start entity. */
export function hardwareLabel(pump: DosingPump): string {
  const ids = [
    pump.volume_entity,
    pump.start_entity,
    pump.dosing_entity,
    pump.power_entity,
    pump.flow_entity,
  ]
    .filter(Boolean)
    .map((id) => id.slice(id.indexOf(".") + 1));
  if (!ids.length) return "not mapped";
  let prefix = ids[0];
  for (const id of ids.slice(1)) while (!id.startsWith(prefix)) prefix = prefix.slice(0, -1);
  prefix = prefix.replace(/_+$/, "");
  return prefix.length >= 3 ? prefix : pump.start_entity || ids[0];
}

/** A stock tank as the integration's stock sensor lists it. */
export interface StockTankReading {
  id: string;
  name: string;
  level_l: number;
  capacity_l: number;
  low_l: number;
}
export const stockSensorId = (prefix: string) => `sensor.crop_steering_${prefix}stock_low`;
/** The room's stock tanks from `sensor.crop_steering_<prefix>stock_low`; one without an id (an
 * integration from before dosing) or a usable level and capacity is left out. */
export function stockTanks(states: States, prefix: string): StockTankReading[] {
  const tanks = states[stockSensorId(prefix)]?.attributes.tanks;
  return (Array.isArray(tanks) ? tanks : []).flatMap((item) => {
    const raw = record(item);
    const id = text(raw.id),
      level = count(raw.level_l),
      capacity = count(raw.capacity_l);
    return id && level !== null && capacity !== null && capacity > 0
      ? [
          {
            id,
            name: text(raw.name)?.trim() ?? id,
            level_l: Math.max(0, level),
            capacity_l: capacity,
            low_l: Math.max(0, count(raw.low_l) ?? 0),
          },
        ]
      : [];
  });
}
/** A pump's stock tank, by the Stock tanks page's own rule: amber within half again of its low
 * mark, red at or under it. */
export type StockState = "ok" | "low" | "very-low";
export function stockState(tank: Pick<StockTankReading, "level_l" | "low_l">): StockState {
  if (tank.level_l <= tank.low_l) return "very-low";
  return tank.level_l <= tank.low_l * 1.5 ? "low" : "ok";
}
export const STOCK_STATES: Record<StockState, string> = {
  ok: "",
  low: "Low",
  "very-low": "Very low",
};
/** What a pump takes from its stock tank each time: its recipe amount, per batch, or (the recipe
 * passing it by) its last dose. */
export interface StockDraw {
  ml: number;
  per: "batch" | "dose";
}
export function pumpDraw(pump: string, rows: RecipeRow[], last: LastDose | null): StockDraw | null {
  const row = rows.find((item) => item.pump === pump && item.ml > 0 && !item.unreadable);
  if (row) return { ml: row.ml, per: "batch" };
  return last && last.ml > 0 ? { ml: last.ml, per: "dose" } : null;
}
/** Whole batches, or doses, a tank still covers at its pump's draw. */
export interface StockLeft {
  count: number;
  per: "batch" | "dose";
}
export function stockLeft(level_l: number, draw: StockDraw | null): StockLeft | null {
  if (!draw) return null;
  const count = batchesLeft({ level_l }, draw.ml);
  return count === null ? null : { count, per: draw.per };
}
/** "about 7 batches left", "about 1 dose left", "less than one batch left". */
export function leftWords(left: StockLeft | null): string | null {
  if (!left) return null;
  const [one, many] = left.per === "batch" ? ["batch", "batches"] : ["dose", "doses"];
  return left.count
    ? `about ${left.count} ${left.count === 1 ? one : many} left`
    : `less than one ${one} left`;
}
/** A pump's stock tank, found by the pump's `stock_tank`; `tank` is null while the integration lists
 * no tank by that id. Null when the pump has none. */
export interface PumpStock {
  id: string;
  tank: StockTankReading | null;
  state: StockState;
  left: StockLeft | null;
}
export function pumpStock(
  pump: DosingPump,
  tanks: StockTankReading[],
  rows: RecipeRow[],
  last: LastDose | null,
): PumpStock | null {
  if (!pump.stock_tank) return null;
  const tank = tanks.find((item) => item.id === pump.stock_tank) ?? null;
  return {
    id: pump.stock_tank,
    tank,
    state: tank ? stockState(tank) : "ok",
    left: tank ? stockLeft(tank.level_l, pumpDraw(pump.id, rows, last)) : null,
  };
}

export interface RecipeRow {
  pump: string;
  name: string;
  /** What the batch doses: the entity's reading when it has one, else the fixed amount. */
  ml: number;
  fixed: number;
  entity: string | null;
  /** The amount comes from the entity's reading. */
  fromEntity: boolean;
  /** The amount entity reads nothing: the controller refuses the batch, it never falls back to the
   * fixed amount. */
  unreadable: boolean;
  flow: number | null;
  seconds: number | null;
  /** 0 mL: the batch passes this pump by. */
  skipped: boolean;
  /** The recipe names a pump the room does not have. */
  unknown: boolean;
}
export function recipeRows(config: DosingConfig, states: States): RecipeRow[] {
  return config.batch.recipe.map((line) => {
    const pump = config.pumps.find((item) => item.id === line.pump);
    const reading = line.ml_entity ? numeric(states[line.ml_entity]) : null;
    const unreadable = !!line.ml_entity && reading === null;
    const ml = unreadable ? 0 : Math.max(0, reading ?? line.ml);
    const flow = pump ? numeric(states[pump.flow_entity]) : null;
    return {
      pump: line.pump,
      name: pump?.name ?? line.pump,
      ml,
      fixed: line.ml,
      entity: line.ml_entity,
      fromEntity: reading !== null,
      unreadable,
      flow,
      seconds: ml > 0 && flow !== null && flow >= MIN_FLOW_ML_S ? ml / flow : null,
      skipped: !unreadable && ml <= 0,
      unknown: !pump,
    };
  });
}
/** The recipe's total and how long its doses take; `ml` is null while an amount entity reads
 * nothing, and `seconds` while a dosed pump's flow or amount is unknown. */
export function recipeTotals(rows: RecipeRow[]) {
  const dosed = rows.filter((row) => !row.skipped);
  return {
    pumps: dosed.length,
    ml: dosed.some((row) => row.unreadable) ? null : dosed.reduce((sum, row) => sum + row.ml, 0),
    seconds: dosed.every((row) => row.seconds !== null)
      ? dosed.reduce((sum, row) => sum + row.seconds!, 0)
      : null,
  };
}
/** A batch's expected time: its doses and both mixes. Filling comes on top, up to its timeout. */
export function batchTime(config: DosingConfig, rows: RecipeRow[]) {
  const dosing = recipeTotals(rows).seconds;
  return {
    seconds:
      dosing === null ? null : dosing + (config.batch.premix_min + config.batch.postmix_min) * 60,
    fillMax: config.batch.fill_valve ? config.batch.fill_timeout_min * 60 : 0,
  };
}

export const STEP_LABELS: Record<BatchStep, string> = {
  hold: "Hold watering",
  close: "Close the feed",
  fill: "Fill the tank",
  mix: "Start mixing",
  premix: "Mix before dosing",
  dose: "Dose the recipe",
  postmix: "Mix after dosing",
  finish: "Finish",
};
export interface StepView {
  step: BatchStep;
  label: string;
  detail: string;
  state: "done" | "running" | "skipped" | "failed" | "waiting";
  at: string | null;
  note: string | null;
}
const plural = (n: number, one: string, many = one + "s") => `${n} ${n === 1 ? one : many}`;
/** What each step will do with this configuration, and whether it is passed by. While a batch runs
 * the float says nothing of the plan: the batch filled it, or found it full. */
function plannedStep(step: BatchStep, config: DosingConfig, states: States, running: boolean) {
  const batch = config.batch;
  const dosed = recipeRows(config, states).filter((row) => !row.skipped).length;
  const full =
    !running && !!batch.full_entity && states[batch.full_entity]?.state === batch.full_state;
  switch (step) {
    case "hold":
      return {
        detail: "Watering held; a shot already running finishes first",
        skip: false,
      };
    case "close":
      return {
        detail: batch.close_entities.length
          ? `The held rooms' valves and pumps, and ${plural(batch.close_entities.length, "switch", "switches")}, off`
          : "The held rooms' valves and pumps off",
        skip: false,
      };
    case "fill":
      return !batch.fill_valve
        ? { detail: "Passed by: no fill valve, the tank is filled by hand", skip: true }
        : full
          ? { detail: "Passed by while the float reads full", skip: true }
          : {
              detail: `Until the float reads full, ${batch.fill_timeout_min} min at most`,
              skip: false,
            };
    case "mix":
      return !batch.mix_pump && !batch.mix_valves.length
        ? { detail: "Passed by: no mixing pump", skip: true }
        : {
            detail:
              (batch.mix_pump ? "Mixing pump on" : "Mixing valves open") +
              (batch.mix_valves.length && batch.mix_pump
                ? `, ${plural(batch.mix_valves.length, "valve")} opened first`
                : "") +
              (batch.mix_pump && batch.mix_min_w > 0
                ? `; it must draw ${batch.mix_min_w} W within 20 s`
                : ""),
            skip: false,
          };
    case "premix":
    case "postmix": {
      const minutes = step === "premix" ? batch.premix_min : batch.postmix_min;
      return minutes > 0
        ? { detail: `${minutes} min`, skip: false }
        : { detail: "Passed by: 0 min", skip: true };
    }
    case "dose":
      return dosed
        ? { detail: `${plural(dosed, "pump")} in order`, skip: false }
        : { detail: "Nothing to dose: every amount is 0 mL", skip: true };
    case "finish":
      return {
        detail:
          "Mixing off, watering released" +
          (batch.filled_at_entity ? ", the fill time stamped" : ""),
        skip: false,
      };
  }
}
/** The batch's steps with their state: the running batch's as the controller reports them, else
 * the plan for the next one. */
export function batchSteps(
  config: DosingConfig,
  status: DosingStatus | null,
  states: States,
): StepView[] {
  const running = !!status && status.batch.step !== "idle";
  const records = new Map(running ? status!.batch.steps.map((item) => [item.step, item]) : []);
  const names = new Map(config.pumps.map((pump) => [pump.id, pump.name]));
  return BATCH_STEPS.map((step) => {
    const plan = plannedStep(step, config, states, running);
    const record = records.get(step);
    const current = running && status!.batch.step === step;
    const pump = current && step === "dose" ? status!.batch.pump : null;
    return {
      step,
      label: STEP_LABELS[step],
      detail: pump ? `Dosing ${names.get(pump) ?? pump}` : plan.detail,
      state: current ? "running" : record ? record.state : plan.skip ? "skipped" : "waiting",
      at: record?.at ?? (current ? status!.batch.step_started_at : null),
      note: record?.note ?? null,
    };
  });
}

/** A request the page sent and what became of it: still waiting for the controller, taken (with
 * the controller's word on it), or left too long for the controller ever to act on it. */
export interface RequestStage {
  stage: "waiting" | "taken" | "expired";
  request: DosingRequest;
  result: string | null;
}
/** As the integration counts it, a request is pending while the controller has not published it as
 * handled and it is less than 120 s old; one whose time cannot be read is not pending. */
export function requestStage(
  config: DosingConfig | null,
  status: DosingStatus | null,
  now: number,
): RequestStage | null {
  const request = config?.request;
  if (!request) return null;
  if (status?.handled === request.id)
    return { stage: "taken", request, result: status.handled_result };
  const age = now - Date.parse(request.at ?? "");
  return { stage: age < REQUEST_TTL_MS ? "waiting" : "expired", request, result: null };
}
/** A dose or batch cannot be sent while another request waits: `dosing_request` refuses it. */
export const requestWaiting = (stage: RequestStage | null) => stage?.stage === "waiting";

/** Whether this user may dose, make a batch and change the setup: `dosing_get`'s `can_edit`, or
 * from an integration from before it, whether Home Assistant says the user is an administrator. */
export const canEdit = (doc: DosingDocument | null, admin: boolean | null) =>
  typeof doc?.can_edit === "boolean" ? doc.can_edit : admin !== false;

/** A dose's or batch's result in a pill: finished green, stopped amber, a fault red. */
export function resultTone(result: string): PillTone {
  // A fault first: hardware that won't read off, a cut, no evidence it ran, an early end.
  if (/does not read off|ran past|not confirmed|ended early|fail|refused/i.test(result)) return "off";
  if (/^finished;/i.test(result)) return "warn"; // finished, with a warning after it
  if (/^finished/i.test(result)) return "on";
  if (/^stopped/i.test(result)) return "warn";
  return "neutral";
}
export const resultWords = (result: string) =>
  result ? result.charAt(0).toUpperCase() + result.slice(1) : "No result";

/** The integration's refusals in words. */
export function dosingError(error: string, save = false): string {
  if (error === "busy")
    return save
      ? "A dosing request is waiting for the controller. Save once it has been taken."
      : "Another request is still waiting for the controller. Wait for it, or send Stop.";
  if (error === "revision")
    return "The dosing setup changed elsewhere and has been read again. Review your changes, then save.";
  return error;
}

// The dosing setup editor: a draft keyed by a local key, so a new pump gets its id from its name
// when it is saved and the recipe follows it.
export const PUMP_FIELDS = [
  "volume_entity",
  "start_entity",
  "dosing_entity",
  "power_entity",
  "flow_entity",
] as const;
export const DOMAINS: Record<string, readonly string[]> = {
  volume_entity: ["number", "input_number"],
  start_entity: ["button", "input_button", "script"],
  dosing_entity: ["binary_sensor", "sensor"],
  power_entity: ["switch"],
  flow_entity: ["number", "input_number", "sensor"],
  fill_valve: ["switch"],
  full_entity: ["binary_sensor", "sensor"],
  mix_pump: ["switch"],
  mix_valves: ["switch"],
  mix_power_sensor: ["sensor"],
  close_entities: ["switch"],
  hold_entity: ["input_boolean"],
  filled_at_entity: ["input_datetime"],
  ml_entity: ["number", "input_number", "sensor"],
};
export const inDomain = (field: string, id: string) =>
  (DOMAINS[field] ?? []).includes(id.split(".")[0]) && ENTITY.test(id);

export interface PumpDraft extends Omit<DosingPump, "id"> {
  key: string;
  /** Null until saved: a new pump's id comes from its name. */
  id: string | null;
}
/** The recipe's `pump` holds each pump's draft key. */
export interface SetupDraft {
  pumps: PumpDraft[];
  batch: DosingBatch;
}
export const blankPump = (key: string): PumpDraft => ({
  key,
  id: null,
  name: "",
  volume_entity: "",
  start_entity: "",
  dosing_entity: "",
  dosing_prefix: "Dosing",
  power_entity: "",
  flow_entity: "",
  max_ml: 2000,
  restore_volume: true,
  stock_tank: null,
  ph_role: null,
});
export function setupDraft(config: DosingConfig | null): SetupDraft {
  const batch = config?.batch ?? parseBatch({ premix_min: 2, postmix_min: 5 });
  return {
    pumps: (config?.pumps ?? []).map((pump) => ({ ...pump, key: pump.id })),
    batch: structuredClone(batch),
  };
}
/** An id for a new pump from its name, unlike any other in the room: [a-z0-9_]{1,24}. */
export function newPumpId(name: string, taken: ReadonlySet<string>): string {
  const base =
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 24) || "pump";
  let id = base;
  for (let n = 2; taken.has(id); n++) id = base.slice(0, 24 - String(n).length - 1) + "_" + n;
  return id;
}
/** What `dosing_save` is sent: every pump with its id, the recipe by those ids. */
export function setupPayload(draft: SetupDraft): { pumps: DosingPump[]; batch: DosingBatch } {
  const taken = new Set(draft.pumps.flatMap((pump) => pump.id ?? []));
  const ids = new Map<string, string>();
  const pumps = draft.pumps.map(({ key, id, ...pump }) => {
    const final = id ?? newPumpId(pump.name, taken);
    taken.add(final);
    ids.set(key, final);
    return { id: final, ...pump, name: pump.name.trim() };
  });
  return {
    pumps,
    batch: {
      ...draft.batch,
      recipe: draft.batch.recipe.map((line) => ({
        ...line,
        pump: ids.get(line.pump) ?? line.pump,
      })),
    },
  };
}
const within = (value: number, min: number, max: number) =>
  Number.isFinite(value) && value >= min && value <= max;
/** The checks the integration makes on a save (dosing.py), so the editor can say so first. `tanks`
 * are the ids of the room's stock tanks; null skips that check. */
export function setupErrors(draft: SetupDraft, tanks: readonly string[] | null = null): string[] {
  const errors: string[] = [];
  const { pumps, batch } = draft;
  if (pumps.length > MAX_PUMPS) errors.push(`At most ${MAX_PUMPS} dosing pumps per room.`);
  const names = new Set<string>();
  // Each stock tank's pump: at most one per tank.
  const drawn = new Map<string, string>();
  for (const [index, pump] of pumps.entries()) {
    const name = pump.name.trim();
    const label = name || `Pump ${index + 1}`;
    if (!name || name.length > 40) errors.push(`${label}: give it a name of 1 to 40 characters.`);
    else if (names.has(name.toLowerCase())) errors.push(`Two pumps are called ${name}.`);
    names.add(name.toLowerCase());
    for (const field of PUMP_FIELDS)
      if (!pump[field] || !inDomain(field, pump[field]))
        errors.push(`${label}: map its ${FIELD_LABELS[field].toLowerCase()}.`);
    if (pump.dosing_entity.startsWith("sensor.") && !pump.dosing_prefix.trim())
      errors.push(`${label}: say what its dosing sensor reads while it doses.`);
    if (!within(pump.max_ml, 1, 5000))
      errors.push(`${label}: the largest dose must be between 1 and 5000 mL.`);
    if (pump.stock_tank) {
      if (tanks && !tanks.includes(pump.stock_tank))
        errors.push(`${label}: its stock tank is not one of this room's.`);
      const other = drawn.get(pump.stock_tank);
      if (other) errors.push(`${other} and ${label} are linked to the same stock tank.`);
      drawn.set(pump.stock_tank, label);
    }
  }
  for (const role of ["ph_up", "ph_down"] as const)
    if (pumps.filter((pump) => pump.ph_role === role).length > 1)
      errors.push(`Only one pump can have the ${PH_ROLE_LABELS[role]} role.`);
  const optional = [
    "fill_valve",
    "full_entity",
    "mix_pump",
    "mix_power_sensor",
    "hold_entity",
    "filled_at_entity",
  ] as const;
  for (const field of optional) {
    const id = batch[field];
    if (id && !inDomain(field, id))
      errors.push(`${FIELD_LABELS[field]}: ${id} is not a ${DOMAINS[field].join(" or ")}.`);
  }
  if (batch.fill_valve && !batch.full_entity)
    errors.push("A fill valve needs the float that says the tank is full.");
  if (!batch.full_state.trim()) errors.push("Say which state of the float means full.");
  if (!within(batch.fill_timeout_min, 1, 60))
    errors.push("The fill timeout must be between 1 and 60 minutes.");
  if (!within(batch.mix_min_w, 0, 100_000))
    errors.push("The mixing pump's power must be 0 W or more.");
  if (!within(batch.premix_min, 0, 30))
    errors.push("Mixing before dosing must be between 0 and 30 minutes.");
  if (!within(batch.postmix_min, 0, 60))
    errors.push("Mixing after dosing must be between 0 and 60 minutes.");
  if (batch.mix_valves.length > 4) errors.push("At most 4 mixing valves.");
  if (batch.close_entities.length > 16) errors.push("At most 16 switches to switch off.");
  for (const [field, list] of [
    ["mix_valves", batch.mix_valves],
    ["close_entities", batch.close_entities],
  ] as const)
    if (list.some((id) => !inDomain(field, id)))
      errors.push(`${FIELD_LABELS[field]}: switches only.`);
  const powers = new Set(pumps.map((pump) => pump.power_entity).filter(Boolean));
  const hardware = [batch.fill_valve, batch.mix_pump, ...batch.mix_valves, ...batch.close_entities];
  for (const id of new Set(hardware))
    if (id && powers.has(id))
      errors.push(`${id} is a dosing pump's power switch; it cannot also be batch hardware.`);
  const keys = new Map(pumps.map((pump) => [pump.key, pump]));
  const used = new Set<string>();
  for (const line of batch.recipe) {
    const pump = keys.get(line.pump);
    if (!pump) {
      errors.push("The recipe names a pump the room does not have.");
      continue;
    }
    const label = pump.name.trim() || "A pump";
    if (used.has(line.pump)) errors.push(`${label} is in the recipe twice.`);
    used.add(line.pump);
    if (!within(line.ml, 0, pump.max_ml || 5000))
      errors.push(`${label}: its recipe amount must be between 0 and ${pump.max_ml} mL.`);
    if (line.ml_entity && !inDomain("ml_entity", line.ml_entity))
      errors.push(`${label}: its recipe entity must be a number, input_number or sensor.`);
  }
  return [...new Set(errors)];
}
export const FIELD_LABELS: Record<string, string> = {
  volume_entity: "Dose volume",
  start_entity: "Start",
  dosing_entity: "Dosing state",
  dosing_prefix: "Reads dosing when it starts with",
  power_entity: "Power switch",
  flow_entity: "Calibrated flow",
  max_ml: "Largest dose (mL)",
  restore_volume: "Put the dose volume back",
  stock_tank: "Stock tank",
  ph_role: "pH auto-correct",
  fill_valve: "Fill valve",
  full_entity: "Full float",
  full_state: "Full when the float reads",
  fill_timeout_min: "Fill timeout (min)",
  mix_pump: "Mixing pump",
  mix_valves: "Mixing valves",
  mix_power_sensor: "Mixing pump power",
  mix_min_w: "Power it must draw (W)",
  premix_min: "Mix before dosing (min)",
  postmix_min: "Mix after dosing (min)",
  close_entities: "Switched off before filling",
  hold_entity: "Batch flag",
  filled_at_entity: "Fill time stamp",
  ml_entity: "Amount from an entity",
};

/** A saved setup against the one before it, for the review; `tanks` name the stock tanks. */
export function setupChanges(
  before: DosingConfig | null,
  after: { pumps: DosingPump[]; batch: DosingBatch },
  tanks: readonly { id: string; name: string }[] = [],
): { label: string; before: string; after: string }[] {
  const changes: { label: string; before: string; after: string }[] = [];
  const show = (value: unknown) =>
    value === null || value === "" || (Array.isArray(value) && !value.length)
      ? "none"
      : Array.isArray(value)
        ? value.join(", ")
        : String(value);
  const add = (label: string, from: unknown, to: unknown) => {
    if (show(from) !== show(to)) changes.push({ label, before: show(from), after: show(to) });
  };
  const old = new Map((before?.pumps ?? []).map((pump) => [pump.id, pump]));
  add(
    "Pumps",
    (before?.pumps ?? []).map((pump) => pump.name),
    after.pumps.map((pump) => pump.name),
  );
  const tank = (id: string | null) =>
    id ? (tanks.find((item) => item.id === id)?.name ?? id) : null;
  for (const pump of after.pumps) {
    const was = old.get(pump.id);
    if (!was) continue;
    for (const field of [...PUMP_FIELDS, "dosing_prefix", "max_ml", "restore_volume"] as const)
      add(`${pump.name} · ${FIELD_LABELS[field]}`, was[field], pump[field]);
    add(`${pump.name} · ${FIELD_LABELS.stock_tank}`, tank(was.stock_tank), tank(pump.stock_tank));
    const role = (value?: PhRole | null) => (value ? PH_ROLE_LABELS[value] : null);
    add(`${pump.name} · ${FIELD_LABELS.ph_role}`, role(was.ph_role), role(pump.ph_role));
  }
  const name = (pumps: DosingPump[], id: string) =>
    pumps.find((pump) => pump.id === id)?.name ?? id;
  add(
    "Recipe",
    (before?.batch.recipe ?? []).map(
      (line) => `${name(before!.pumps, line.pump)} ${line.ml_entity ?? line.ml + " mL"}`,
    ),
    after.batch.recipe.map(
      (line) => `${name(after.pumps, line.pump)} ${line.ml_entity ?? line.ml + " mL"}`,
    ),
  );
  const batch = before?.batch ?? parseBatch({});
  for (const field of [
    "fill_valve",
    "full_entity",
    "full_state",
    "fill_timeout_min",
    "mix_pump",
    "mix_valves",
    "mix_power_sensor",
    "mix_min_w",
    "premix_min",
    "postmix_min",
    "close_entities",
    "hold_entity",
    "filled_at_entity",
  ] as const)
    add(FIELD_LABELS[field], batch[field], after.batch[field]);
  return changes;
}

// ------------------------------------------------------------------ Feed & dosing page

/** The controller reads a finished batch's tank this long after its mix stops (MIX_SETTLE_S). */
export const MIX_SETTLE_MIN = 5;
const readable = (entity: EntityState | undefined) =>
  !!entity && !UNREADABLE.includes(entity.state);

/** The guards around the batch tank, each armed or not: every dose read back (the controller reads
 * the pump's power switch back, and the pump's dosing state), the overfill cut and the minimum on the controller's tank level, the mix pump's
 * power read back, and the fill's timeout. The page counts how many are armed. */
export function protections(doc: DosingDocument, states: States): { label: string; ok: boolean }[] {
  const config = doc.config;
  const prefix = doc.room_id.startsWith("room:") ? doc.room_id.slice(5) : "";
  const pumps = config?.pumps ?? [];
  const batch = config?.batch ?? parseBatch({});
  const level = states[tankLevelId(prefix)];
  const levelRead = readable(level) && Number.isFinite(Number(level!.state));
  const minimum = count(level?.attributes.minimum_pct) ?? MINIMUM_PCT;
  const mixOn = batch.mix_pump ? states[batch.mix_pump]?.state === "on" : false;
  const watts = batch.mix_power_sensor ? numeric(states[batch.mix_power_sensor]) : null;
  const kw = watts === null || !mixOn ? "" : ` · ${Number((watts / 1000).toFixed(3))} kW`;
  return [
    {
      label: "Read-back on every dose",
      ok:
        pumps.length > 0 &&
        pumps.every(
          (pump) => readable(states[pump.power_entity]) && readable(states[pump.dosing_entity]),
        ),
    },
    { label: `Overfill cut ${OVER_PCT}%`, ok: levelRead },
    { label: `Minimum ${minimum}%`, ok: levelRead },
    {
      label: batch.mix_pump ? `Mix pump ${mixOn ? "on" : "off"}${kw}` : "Mix pump on",
      ok:
        !!batch.mix_pump &&
        !!batch.mix_power_sensor &&
        readable(states[batch.mix_power_sensor]) &&
        batch.mix_min_w > 0,
    },
    { label: `Timeout ${batch.fill_timeout_min} min`, ok: !!batch.fill_valve },
  ];
}

/** Whether the controller checks a finished batch's mix (dosing_runner._mix_bands): a feed EC or pH
 * probe mapped (engine_config `feed_<q>_sensor`) whose band has a bound above 0, or a band that can't
 * be read (the check is planned and waits for it). A band setting the room does not have is no bound. */
export function mixChecked(
  states: States,
  prefix: string,
  engine: Record<string, unknown>,
): boolean {
  return (["ec", "ph"] as const).some(
    (quantity) =>
      !!engine[`feed_${quantity}_sensor`] &&
      (["min", "max"] as const).some((end) => {
        const setting = states[`number.crop_steering_${prefix}irrigation_${quantity}_${end}`];
        if (!setting) return false;
        const value = Number(setting.state);
        return !readable(setting) || !Number.isFinite(value) || value > 0;
      }),
  );
}

/** The recipe the room doses today: the feed recipe in use, else the batch's own. */
export function recipeInUse(doc: DosingDocument): { name: string | null; lines: RecipeLine[] } {
  const config = doc.config;
  const id = doc.feed_now?.recipe_id ?? null;
  const recipe = id ? config?.feed?.recipes.find((item) => item.id === id) : undefined;
  return recipe
    ? { name: recipe.name, lines: recipe.doses }
    : { name: null, lines: config?.batch.recipe ?? [] };
}

/** What the page knows of the tank for the next batch: its level, the litres in 1 %, how fast it
 * falls (from its recorded level), the level the next batch is made at, and whether the controller
 * checks the mix after it (a feed probe with a band). */
export interface NextBatchInput {
  states: States;
  levelPct: number | null;
  litresPerPct: number | null;
  pctPerHour: number | null;
  atPct: number;
  checks: boolean;
}
export interface NextBatch {
  /** When the tank reaches `atPct` at its present fall; null when that is not known. */
  at: number | null;
  /** About how many litres the fill adds, from `atPct` to full; null until the litres in 1 % are
   * learned. */
  litres: number | null;
  doses: { name: string; ml: number }[];
  steps: { name: "premix" | "dose" | "postmix" | "check"; min: number }[];
  stockWarning: string | null;
}
/** The next batch: when, how much water, what it doses and how long its steps take, and the stock
 * tank that one batch takes below its low line. Nothing is guessed: what is not known is null. */
export function nextBatch(
  doc: DosingDocument,
  stock: StockDocument | null,
  now: number,
  input: NextBatchInput,
): NextBatch {
  const config = doc.config;
  const { levelPct, pctPerHour, litresPerPct, atPct } = input;
  const at =
    levelPct === null
      ? null
      : levelPct <= atPct
        ? now
        : pctPerHour !== null && pctPerHour > 0
          ? now + ((levelPct - atPct) / pctPerHour) * 3_600_000
          : null;
  const litres =
    litresPerPct !== null && litresPerPct > 0
      ? Math.round((100 - atPct) * litresPerPct * 10) / 10
      : null;
  const rows = config
    ? recipeRows(
        { ...config, batch: { ...config.batch, recipe: recipeInUse(doc).lines } },
        input.states,
      ).filter((row) => !row.skipped && !row.unreadable)
    : [];
  const doseS = recipeTotals(rows).seconds;
  const steps: NextBatch["steps"] = [];
  if (config) {
    if (config.batch.premix_min > 0) steps.push({ name: "premix", min: config.batch.premix_min });
    if (doseS !== null && rows.length) steps.push({ name: "dose", min: Math.ceil(doseS / 60) });
    if (config.batch.postmix_min > 0)
      steps.push({ name: "postmix", min: config.batch.postmix_min });
    if (input.checks) steps.push({ name: "check", min: MIX_SETTLE_MIN });
  }
  let stockWarning: string | null = null;
  for (const tank of stock?.tanks ?? []) {
    const dose = stock?.doses[tank.id] ?? tank.dose_ml;
    if (!(dose > 0)) continue;
    const after = Math.max(0, tank.level_l - dose / 1000);
    if (after >= tank.low_l) continue;
    const left = batchesLeft({ level_l: after }, dose) ?? 0;
    stockWarning = `${tank.name} after this batch: ${formatVolume(after, 1)}, ${left} ${left === 1 ? "batch" : "batches"} left`;
    break;
  }
  return {
    at,
    litres,
    doses: rows.map((row) => ({ name: row.name, ml: row.ml })),
    steps,
    stockWarning,
  };
}

/** A rise of the recorded level smaller than this (%) is the level sensor's jitter, not a fill. */
const LEVEL_JITTER_PCT = 1;
/** Where the newest run of the recorded level that does not rise (past jitter) starts. */
function fallStart(points: readonly { time: number; value: number }[]): number {
  let start = points.length - 1;
  while (start > 0 && points[start - 1].value >= points[start].value - LEVEL_JITTER_PCT) start--;
  return start;
}

/** How fast the tank's level falls, % per hour, since its last rise (a fill): the newest run of the
 * recorded level that does not rise past jitter, from the last reading at its peak. Null with under
 * an hour of it, or a level that is not falling. */
export function levelFall(points: readonly { time: number; value: number }[]): number | null {
  if (points.length < 2) return null;
  let start = fallStart(points);
  // A tank that sat full is not falling yet: the run starts where it last left its peak (within
  // jitter of it).
  const peak = Math.max(...points.slice(start).map((point) => point.value));
  while (start < points.length - 1 && points[start + 1].value >= peak - LEVEL_JITTER_PCT) start++;
  const first = points[start],
    last = points[points.length - 1];
  const hours = (last.time - first.time) / 3_600_000;
  if (hours < 1 || !(first.value > last.value)) return null;
  return (first.value - last.value) / hours;
}

/** Why the next batch has no time: no level read, the recorded level still loading or not
 * loaded, less than an hour of it, a fall under an hour old, or an hour and more that does not fall.
 * `points` are the recorded level then the reading now. */
export function levelFallUnknown(
  levelKnown: boolean,
  history: "loading" | "failed" | "loaded",
  points: readonly { time: number; value: number }[],
): string {
  if (!levelKnown) return "Not known: no tank level is read";
  if (history === "loading") return "Not known yet: the recorded tank level is still loading";
  if (history === "failed") return "Not known: the recorded tank level could not be loaded";
  const span = points.length ? points[points.length - 1].time - points[0].time : 0;
  if (span < 3_600_000) return "Not known yet: less than an hour of tank level is recorded";
  // The last run that does not rise, as levelFall walks it: below its start, the tank is falling.
  const start = fallStart(points);
  return points[start].value > points[points.length - 1].value
    ? "Not known yet: the tank has been falling for less than an hour"
    : "Not known yet: the tank level is not falling";
}

/** The level the next batch is made at, and the reading that says when: the refill reminder on its
 * own level entity (`batch.level_entity`, dosing_runner), else the minimum on the controller's tank
 * level (`sensor.crop_steering_<prefix>tank_level`). The time is worked out from the same entity as
 * the mark. */
export function batchLevel(
  states: States,
  prefix: string,
): { atPct: number; entityId: string; pct: number | null } {
  const batch = record(record(states[dosingConfigId(prefix)]?.attributes).batch);
  const remind = count(batch.remind_pct);
  const own = entityId(batch.level_entity);
  if (remind !== null && remind > 0 && own) {
    const entity = states[own];
    const pct = readable(entity) ? count(entity!.state) : null;
    return { atPct: remind, entityId: own, pct };
  }
  const guard = reservoirView(states, prefix);
  return { atPct: guard.minimum, entityId: tankLevelId(prefix), pct: guard.level };
}
