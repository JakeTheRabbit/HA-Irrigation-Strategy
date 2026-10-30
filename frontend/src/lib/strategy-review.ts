import type { ReviewRow } from "@/components/review-apply";
import type { Drafts } from "@/pages/strategy";
import { formatEc } from "./display-units";
import { callV2 } from "./parity-api";
import type { HistoryChange } from "./parity-types";
import { buildPlanningCurve, projectDay, type DryRates } from "./planning-curve";
import type { SetpointCurveState } from "./setpoint-preview";
import { settingWords } from "./setting-words";
import { lightsWindow, startOfDay } from "./time";
import type { Change, Controller, States, WriteResult } from "./types";
import { UndoError, revertEvents } from "./undo";
import { sameValue } from "./utils";

/** Current day's review: the pending target edits as Review & apply rows, what the rest of the
 * lights-on day waters with and without them, and the Undo of the last apply. */

/** One shot the controller plans (`sensor.crop_steering_<prefix>projection_app`, attribute
 * `intents`, backend Task 15). */
export interface ProjectionIntent {
  zone: number;
  at: string;
  duration_s: number;
  source: "timer" | "engine";
  expected: boolean;
}

const HOUR = 3_600_000;
const decimals = (value: number) => {
  const text = String(value);
  return text.includes("e-") ? Number(text.split("e-")[1]) : (text.split(".")[1]?.length ?? 0);
};
/** A number at its source precision, without trailing zeros. */
const trim = (value: number, digits: number) => String(Number(value.toFixed(digits)));
const show = (value: number, unit: string, digits: number) =>
  unit === "%"
    ? `${trim(value, digits)}%`
    : unit === "mS/cm"
      ? formatEc(value, digits)
      : unit
        ? `${trim(value, digits)} ${unit}`
        : trim(value, digits);

/** The setting key an entity id names, and its zone: `number.crop_steering_<prefix>zone_2_<key>`,
 * or a room's `number.crop_steering_<prefix><key>` (the prefix is whatever leaves a named key). */
function keyOf(entityId: string): { key: string; zone: number | null } | null {
  const rest = entityId.replace(/^\w+\.crop_steering_/, "");
  const zoned = rest.match(/(?:^|_)zone_(\d+)_(.+)$/);
  if (zoned) return { key: zoned[2], zone: Number(zoned[1]) };
  const parts = rest.split("_");
  for (let i = 0; i < parts.length; i++) {
    const key = parts.slice(i).join("_");
    if (settingWords(key)) return { key, zone: null };
  }
  return null;
}

/** The changed drafts as Review & apply rows, against what the controller holds now: a draft back
 * at the held value is not a change. Notes give the signed change and what it does. A row of
 * another zone (or the room) than `zone` names it. `remove` takes a row's edit back out. */
export function targetRows(
  drafts: Drafts,
  states: States,
  zone: number,
  remove: (entityId: string) => void = () => {},
): ReviewRow[] {
  return Object.entries(drafts).flatMap(([id, draft]) => {
    const state = states[id];
    const held = state?.state;
    const owner = keyOf(id);
    const words = owner ? settingWords(owner.key) : undefined;
    const named = words
      ? /(vegetative|generative|_veg_|_gen_)/.test(owner!.key)
        ? words.label
        : words.short
      : draft.label;
    const label = owner?.zone === zone ? named : `${draft.zone} · ${named}`;
    const base = { id, label, undo: () => remove(id) };
    if (!id.startsWith("number.")) {
      if (draft.value === held) return [];
      return [{ ...base, before: held ?? "Unavailable", after: draft.value }];
    }
    const unit = String(state?.attributes.unit_of_measurement ?? "");
    const step = Number(state?.attributes.step);
    const want = draft.value.trim() === "" ? NaN : Number(draft.value);
    if (Number.isFinite(want) && sameValue(held, want, Number.isFinite(step) ? step : undefined))
      return [];
    const was = held === undefined || held.trim() === "" ? NaN : Number(held);
    const digits = Math.max(
      Number.isFinite(step) ? decimals(step) : 0,
      Number.isFinite(want) ? decimals(want) : 0,
      Number.isFinite(was) ? decimals(was) : 0,
    );
    const effect = words?.effect ?? words?.help.split(/(?<=\.)\s/)[0];
    let note = effect;
    if (Number.isFinite(want) && Number.isFinite(was)) {
      const delta = want - was;
      const sign = delta < 0 ? "-" : "+";
      const by = Math.max(1, Number.isFinite(step) ? decimals(step) : 1);
      const size =
        unit === "%"
          ? `${Math.abs(delta).toFixed(by)} pts`
          : unit === "mS/cm"
            ? formatEc(Math.abs(delta), by)
            : `${trim(Math.abs(delta), by)}${unit ? ` ${unit}` : ""}`;
      note = effect ? `${sign}${size} · ${effect}` : `${sign}${size}`;
    }
    return [
      {
        ...base,
        before: Number.isFinite(was) ? show(was, unit, digits) : "Unavailable",
        after: Number.isFinite(want) ? show(want, unit, digits) : draft.value,
        ...(note ? { note } : {}),
      },
    ];
  });
}

/** The controller's planned shots for one zone, or null where it publishes none (3.17, or the
 * sensor absent or unavailable). */
export function readProjection(
  states: States,
  prefix: string,
  zone: number,
): ProjectionIntent[] | null {
  const entity = states[`sensor.crop_steering_${prefix}projection_app`];
  const intents = entity?.attributes.intents;
  if (!entity || ["unavailable", "unknown"].includes(entity.state) || !Array.isArray(intents))
    return null;
  return intents.filter(
    (i): i is ProjectionIntent =>
      !!i &&
      typeof i === "object" &&
      i.zone === zone &&
      typeof i.at === "string" &&
      Number.isFinite(Date.parse(i.at)),
  );
}

type ProjectionOptions = { rates?: DryRates; retention?: number | null };
const positive = (value: number | undefined) =>
  typeof value === "number" && Number.isFinite(value) && value > 0;
/** Litres a second through one plant's drippers; NaN without the zone's sizing. */
const flowPerPlant = (p: Record<string, number>) =>
  positive(p.dripper_flow_rate) && positive(p.drippers_per_plant)
    ? (p.dripper_flow_rate * p.drippers_per_plant) / 3600
    : NaN;
const dayShots = (state: SetpointCurveState, options: ProjectionOptions) =>
  projectDay(
    buildPlanningCurve(state.parameters, state.lightsOn, state.lightsOff),
    state.parameters,
    options,
  )?.shots ?? [];

/** The saved targets' day as planned shots, when the controller publishes none: the same
 * projection the chart draws, each shot timed by the zone's drippers. */
export function estimatedIntents(
  saved: SetpointCurveState,
  zone: number,
  lightsOnAt: number,
  options: ProjectionOptions = {},
): ProjectionIntent[] {
  const volume = saved.parameters.substrate_volume;
  const flow = flowPerPlant(saved.parameters);
  return dayShots(saved, options).map((shot) => ({
    zone,
    at: new Date(lightsOnAt + shot.hour * HOUR).toISOString(),
    duration_s: positive(volume) && shot.size !== null ? ((shot.size / 100) * volume) / flow : NaN,
    source: "engine",
    expected: true,
  }));
}

/** The shots in [from, to) and their litres per plant. Saved is the saved plan (`saved`: the
 * controller's projection, or `estimatedIntents`). With edits is Saved plus only what the edit
 * changes: the edited targets' projection less the saved targets' (`baseline`) over the window, so a
 * projection that differs from the controller's plan never shows as an edit. Litres are NaN where
 * the zone's sizing is unknown. */
export function afternoon(
  saved: ProjectionIntent[],
  edited: SetpointCurveState,
  from: number,
  to: number,
  options: ProjectionOptions & { lightsOnAt: number; baseline: SetpointCurveState },
): { saved: { shots: number; lPerPlant: number }; edited: { shots: number; lPerPlant: number } } {
  const inWindow = (ms: number) => ms >= from && ms < to;
  const planned = saved.filter((intent) => inWindow(Date.parse(intent.at)));
  const flow = flowPerPlant(edited.parameters);
  const volume = edited.parameters.substrate_volume;
  const projected = (state: SetpointCurveState) => {
    const shots = dayShots(state, options).filter((shot) =>
      inWindow(options.lightsOnAt + shot.hour * HOUR),
    );
    return {
      shots: shots.length,
      lPerPlant: positive(volume)
        ? shots.reduce(
            (sum, shot) => sum + (shot.size === null ? NaN : (shot.size / 100) * volume),
            0,
          )
        : NaN,
    };
  };
  const plan = {
    shots: planned.length,
    lPerPlant: planned.reduce((sum, intent) => sum + intent.duration_s * flow, 0),
  };
  if (JSON.stringify(edited) === JSON.stringify(options.baseline))
    return { saved: plan, edited: plan };
  const after = projected(edited),
    before = projected(options.baseline);
  // Shots and water reach none together: no shots left is no water.
  const shots = Math.max(0, plan.shots + after.shots - before.shots);
  return {
    saved: plan,
    edited: {
      shots,
      lPerPlant: shots ? Math.max(0, plan.lPerPlant + after.lPerPlant - before.lPerPlant) : 0,
    },
  };
}

const hhmm = (hour: number) => {
  const minutes = Math.round((((hour % 24) + 24) % 24) * 60);
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
};
/** The rest of the lights-on period, on the room's clock: from now to lights-off while the lights
 * are on, else the next lights-on period (`ahead`). Null without the room's lights hours. */
export function growDayWindow(
  now: number,
  lightsOn: number,
  lightsOff: number,
  tz: string,
): { from: number; to: number; lightsOnAt: number; ahead: boolean } | null {
  if (!Number.isFinite(lightsOn) || !Number.isFinite(lightsOff)) return null;
  const window = (day: number) => lightsWindow(day, hhmm(lightsOn), hhmm(lightsOff), tz);
  const midnight = startOfDay(now, tz);
  const today = window(midnight);
  // Lights on overnight: the period may have started yesterday.
  for (const lights of [window(startOfDay(midnight - 1, tz)), today])
    if (now >= lights.on && now < lights.off)
      return { from: now, to: lights.off, lightsOnAt: lights.on, ahead: false };
  const next = now < today.on ? today : window(startOfDay(midnight + 36 * HOUR, tz));
  return { from: next.on, to: next.off, lightsOnAt: next.on, ahead: true };
}

/** The window's name: "This afternoon" from noon on the room's clock, "Rest of today" before it,
 * "Next lights-on" while the lights are off. */
export function windowTitle(window: { from: number; ahead: boolean }, tz: string): string {
  if (window.ahead) return "Next lights-on";
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hourCycle: "h23", timeZone: tz }).format(
      window.from,
    ),
  );
  return hour >= 12 ? "This afternoon" : "Rest of today";
}

/** An applied batch, kept for its Undo: the values before and after, and on 3.18 the Journal's
 * `target.changed` events for it. */
export interface LastApply {
  at: number;
  backend: "3.18" | "3.17";
  eventIds: string[];
  before: Change[];
  after: Change[];
}

/** The `target.changed` events this apply journalled (3.18): per written value, the newest
 * manual setpoint change of its key and zone since `since` from the value it had (`before`) to the
 * written one, never a put-back. A learner's or the AI's write of the same value is not this apply's.
 * A 3.17 integration has no Journal: the first call says so, or one call when only choices were
 * written (a choice has no setpoint event; its Undo writes the previous choice back on either). */
export async function appliedEventIds(
  controller: Pick<Controller, "operator">,
  roomId: string,
  prefix: string,
  after: Change[],
  before: Change[],
  since: number,
): Promise<{ backend: "3.18" | "3.17"; ids: string[] }> {
  const root = `number.crop_steering_${prefix}`;
  const ids: string[] = [];
  const query = { room_id: roomId, since: new Date(since).toISOString(), kinds: ["setpoint"] };
  let asked = false;
  for (const change of after) {
    const was = before.find((b) => b.entityId === change.entityId)?.value;
    if (
      !change.entityId.startsWith(root) ||
      typeof change.value !== "number" ||
      typeof was !== "number"
    )
      continue;
    const rest = change.entityId.slice(root.length);
    const zone = rest.match(/^zone_(\d+)_/)?.[1];
    const key = rest.replace(/^zone_\d+_/, "");
    const outcome = await callV2<{ changes?: HistoryChange[] }>(controller, "history_changes", {
      ...query,
      ...(zone ? { zone: Number(zone) } : {}),
      key,
    });
    asked = true;
    if (outcome.kind === "missing") return { backend: "3.17", ids: [] };
    if (outcome.kind !== "ok") continue;
    const found = (outcome.data?.changes ?? []).find(
      (c) =>
        c.kind === "setpoint" &&
        c.key === key &&
        c.scope === (zone ? `zone:${zone}` : "room") &&
        c.actor === "manual" &&
        (c as { detail?: unknown }).detail !== "put back" &&
        Date.parse(c.ts) >= since &&
        sameValue(String(c.old), was) &&
        sameValue(String(c.new), change.value as number),
    );
    if (found) ids.push(found.id);
  }
  // Nothing numeric written (a steering mode alone): one call still says which integration this is.
  if (!asked && (await callV2(controller, "history_changes", query)).kind === "missing")
    return { backend: "3.17", ids: [] };
  return { backend: "3.18", ids };
}

/** Undo of the last apply. On 3.18 the Journal puts its `target.changed` events back
 * (`revertEvents`; its refusal is shown as it is). On 3.17 the previous values are written again
 * with read-back, but only while the controller still holds what was applied. A choice has no
 * setpoint event, so on 3.18 too it is written back that way; a number never falls back from the
 * Journal to a write. */
export async function undoApply(
  last: LastApply,
  deps: {
    controller: Pick<Controller, "operator">;
    states: States;
    write: (changes: Change[]) => Promise<WriteResult>;
  },
): Promise<void> {
  const n = last.after.length;
  // On 3.18 the numbers go back through the Journal. A choice (a select) has no setpoint event yet,
  // so it is written back as on 3.17.
  const journalled =
    last.backend === "3.18"
      ? last.after.filter(({ entityId }) => entityId.startsWith("number."))
      : [];
  const ids = new Set(journalled.map((c) => c.entityId));
  const rewrite = last.before.filter(({ entityId }) => !ids.has(entityId));
  if (last.eventIds.length < journalled.length)
    throw new UndoError(
      "The controller has no record of this change to put back. Nothing was undone.",
      0,
      n,
    );
  if (rewrite.some(({ value }) => typeof value === "number" && !Number.isFinite(value)))
    throw new UndoError("The previous value is not known. Nothing was undone.", 0, n);
  const moved = last.after
    .filter(({ entityId }) => !ids.has(entityId))
    .some(({ entityId, value }) => {
      const state = deps.states[entityId];
      if (typeof value !== "number") return state?.state !== String(value);
      const step = Number(state?.attributes.step);
      return !sameValue(state?.state, value, Number.isFinite(step) ? step : undefined);
    });
  if (moved)
    throw new UndoError("This value has changed since you applied it. Nothing was undone.", 0, n);
  if (journalled.length) {
    try {
      await revertEvents(deps.controller, last.eventIds);
    } catch (error) {
      // Its count is of the Journal's changes; say it of the whole apply.
      if (error instanceof UndoError && rewrite.length && error.reverted)
        throw new UndoError(
          error.message.replace(/^\d+ of \d+/, `${error.reverted} of ${n}`),
          error.reverted,
          n,
        );
      throw error;
    }
  }
  if (!rewrite.length) return;
  const result = await deps.write(rewrite);
  if (result.failed.length) {
    const k = journalled.length + result.applied.length;
    const reason = result.failed[0].reason;
    throw new UndoError(k ? `${k} of ${n} put back: ${reason}` : reason, k, n);
  }
}
