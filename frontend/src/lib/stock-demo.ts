import { dosingConfigId, dosingStatusId, readConfig, readStatus, stockSensorId } from "./dosing";
import type { OperatorAction } from "./operator-types";
import {
  batchesLeft,
  draftErrors,
  type StockBatch,
  type StockDocument,
  type StockTank,
  type StockTankDraft,
} from "./stock";
import type { States } from "./types";

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));
const HISTORY = 30;
/** The stock services, and stock_draw, which only the controller calls. */
export type StockAction = OperatorAction | "stock_draw";

/** Each demo room's stock tanks, one per dosing pump and named after its nutrient; the demo's dosing
 * setup links each pump to its own. [id, name, capacity L, level L, per batch mL (the recipe's), low
 * mark L]. Flower 2's Bloom is getting low; Flower 1's Fade is new and full. */
const DEMO_TANKS: Record<string, [string, string, number, number, number, number][]> = {
  "": [
    ["balance", "Balance", 10, 6.9, 300, 2],
    ["bloom", "Bloom", 20, 5.4, 1800, 4],
    ["core", "Core", 20, 12.9, 1080, 4],
    ["cleanse", "Cleanse", 5, 3.9, 200, 1],
  ],
  f1_: [
    ["grow", "Grow", 20, 14.2, 1080, 4],
    ["cleanse", "Cleanse", 5, 3.6, 200, 1],
    ["balance", "Balance", 10, 7.4, 180, 2],
    ["fade", "Fade", 10, 10, 0, 2],
    ["core", "Core", 20, 11.5, 0, 4],
    ["bloom", "Bloom", 20, 16.2, 1800, 4],
  ],
};
const prefixOf = (roomId: string) => (roomId.startsWith("room:") ? roomId.slice(5) : "");

/** A demo room's stock as the integration holds it: its tanks, with batches counted from the room's
 * tank last-fill entity. */
export function demoStock(roomId: string, now: number, states: States): StockDocument {
  const prefix = prefixOf(roomId);
  const hoursAgo = (hours: number) => new Date(now - hours * 3_600_000).toISOString();
  const tanks = (DEMO_TANKS[prefix] ?? []).map(
    ([id, name, capacity, level, dose, low]): StockTank => ({
      id,
      name,
      capacity_l: capacity,
      level_l: level,
      dose_ml: dose,
      dose_entity: null,
      low_l: low,
      refilled_at: hoursAgo(24 * 9),
      updated_at: hoursAgo(20),
    }),
  );
  const fill =
    states[`sensor.crop_steering_${prefix}engine_config`]?.attributes.tank_last_fill_sensor;
  const fillEntity = typeof fill === "string" && fill ? fill : null;
  const last = fillEntity ? Date.parse(states[fillEntity]?.state ?? "") : Number.NaN;
  return {
    schema_version: 1,
    room_id: roomId,
    revision: 1,
    tanks,
    last_batch: Number.isFinite(last) ? new Date(last).toISOString() : null,
    history: [],
    fill_entity: fillEntity,
    doses: Object.fromEntries(tanks.map((t) => [t.id, t.dose_ml])),
    low: tanks.filter((t) => t.level_l <= t.low_l).map((t) => t.id),
    max_tanks: 12,
    error: null,
  };
}

/** Each stock tank's dosing pump, from the room's dosing setup (stock tank id -> pump id). */
export const stockLinks = (states: States, prefix: string) =>
  new Map(
    (readConfig(states[dosingConfigId(prefix)])?.pumps ?? []).flatMap((pump) =>
      pump.stock_tank ? [[pump.stock_tank, pump.id] as const] : [],
    ),
  );

/** The attributes of the integration's stock sensor: every tank, with the pump linked to it. */
export function stockAttributes(doc: StockDocument, links: ReadonlyMap<string, string>) {
  return {
    tanks: doc.tanks.map((tank) => {
      const dose = doc.doses[tank.id] ?? tank.dose_ml;
      return {
        id: tank.id,
        pump: links.get(tank.id) ?? null,
        name: tank.name,
        level_l: tank.level_l,
        capacity_l: tank.capacity_l,
        percent: Math.round((tank.level_l / tank.capacity_l) * 1000) / 10,
        low_l: tank.low_l,
        dose_ml: dose,
        batches_left: batchesLeft(tank, dose),
        low: tank.level_l <= tank.low_l,
      };
    }),
    last_batch: doc.last_batch,
    error: doc.error,
  };
}

/** What the demo's controller drew for the doses already in a room's dosing history: a draw per dose
 * from its pump's linked tank, a batch's doses a minute apart up to its end. Newest first. */
function pastDraws(states: States, roomId: string): StockBatch[] {
  const prefix = prefixOf(roomId);
  const links = new Map([...stockLinks(states, prefix)].map(([tank, pump]) => [pump, tank]));
  return (readStatus(states[dosingStatusId(prefix)])?.history ?? []).flatMap((entry) => {
    const end = Date.parse(entry.ended_at ?? entry.at ?? "");
    const doses = Object.entries(entry.doses).filter(([pump, ml]) => links.has(pump) && ml > 0);
    if (!Number.isFinite(end)) return [];
    return doses
      .map(([pump, ml], index) => ({
        at: new Date(end - (doses.length - 1 - index) * 60_000).toISOString(),
        source: entry.kind,
        draw_ml: { [links.get(pump)!]: ml },
      }))
      .reverse();
  });
}

/** The integration's stock services in memory (stock.py / stock_api.py), for demo mode, with
 * stock_draw as the controller calls it. Every change rewrites the room's stock sensor. */
export class StockDemo {
  private docs = new Map<string, StockDocument>();
  /** Each room's counted draw keys: a draw sent again changes nothing. */
  private keys = new Map<string, Set<string>>();
  /** The demo as it started: its tanks drew what its dosing history had dosed before then. */
  private start: States;
  constructor(
    private getStates: () => States,
    private updateStates?: (states: States) => void,
  ) {
    this.start = getStates();
  }

  private doc(roomId: string) {
    let doc = this.docs.get(roomId);
    if (!doc) {
      doc = demoStock(roomId, Date.now(), this.getStates());
      doc.history = pastDraws(this.start, roomId);
      this.docs.set(roomId, doc);
    }
    return doc;
  }

  private finish(doc: StockDocument) {
    doc.revision++;
    doc.doses = Object.fromEntries(doc.tanks.map((t) => [t.id, t.dose_ml]));
    doc.low = doc.tanks.filter((t) => t.level_l <= t.low_l).map((t) => t.id);
    this.publish(doc.room_id);
    return clone(doc);
  }

  /** Rewrites the room's stock sensor, as the integration does when its tanks change or a saved
   * dosing setup links a pump to another tank. */
  publish(roomId: string) {
    if (!this.updateStates) return;
    const doc = this.doc(roomId);
    const prefix = prefixOf(roomId);
    const states = this.getStates();
    const id = stockSensorId(prefix);
    const old = states[id];
    const state = String(doc.low.length);
    const stamp = new Date().toISOString();
    this.updateStates({
      ...states,
      [id]: {
        entity_id: id,
        state,
        attributes: {
          ...(old?.attributes ?? { friendly_name: "Stock tanks low" }),
          ...stockAttributes(doc, stockLinks(states, prefix)),
        },
        last_changed: old?.state === state ? old.last_changed : stamp,
        last_updated: stamp,
      },
    });
  }

  /** stock_draw (stock.py draw_dosed): what the controller dosed out of linked tanks, counted once
   * per key; an id that is not one of the room's tanks is skipped. True when anything was drawn. */
  private draw(doc: StockDocument, data: Record<string, unknown>): boolean {
    const draws = data.draws;
    const source = (["dose", "batch"] as const).find((item) => item === data.source);
    if (!draws || typeof draws !== "object" || Array.isArray(draws))
      throw new Error("Send the draws as stock tank ids to mL.");
    if (!source) throw new Error("A draw's source is dose or batch.");
    const amounts = Object.entries(draws as Record<string, unknown>);
    for (const [id, ml] of amounts)
      if (typeof ml !== "number" || !Number.isFinite(ml) || ml < 0)
        throw new Error(`The draw from ${id} must be a number of mL, 0 or more.`);
    const key = String(data.key ?? "");
    const keys = this.keys.get(doc.room_id) ?? new Set<string>();
    this.keys.set(doc.room_id, keys);
    if (keys.has(key)) return false;
    const taken: Record<string, number> = {};
    for (const [id, ml] of amounts as [string, number][]) {
      const tank = doc.tanks.find((item) => item.id === id);
      if (!tank) continue;
      const before = tank.level_l;
      tank.level_l = Math.round(Math.max(0, before - ml / 1000) * 1e4) / 1e4;
      taken[id] = Math.round((before - tank.level_l) * 1e4) / 10;
    }
    if (!Object.keys(taken).length) return false;
    keys.add(key);
    doc.history = [
      { at: new Date().toISOString(), source, draw_ml: taken, key },
      ...doc.history,
    ].slice(0, HISTORY);
    return true;
  }

  call(action: StockAction, data: Record<string, unknown>): StockDocument {
    const doc = this.doc(String(data.room_id));
    if (action === "stock_get") {
      doc.low = doc.tanks.filter((t) => t.level_l <= t.low_l).map((t) => t.id);
      return clone(doc);
    }
    // The controller cannot know the revision; the key makes a repeat harmless.
    if (action === "stock_draw") return this.draw(doc, data) ? this.finish(doc) : clone(doc);
    if (data.expected_revision !== doc.revision)
      throw new Error("Stock tanks changed elsewhere. Reload before saving.");
    const now = new Date().toISOString();
    if (action === "stock_save") {
      const drafts = data.tanks as StockTankDraft[];
      const errors = draftErrors(drafts, doc.max_tanks);
      if (errors.length) throw new Error(errors.join(" "));
      const known = new Map(doc.tanks.map((t) => [t.id, t]));
      const taken = new Set(drafts.flatMap((d) => (d.id && known.has(d.id) ? [d.id] : [])));
      doc.tanks = drafts.map((draft) => {
        const old = draft.id ? known.get(draft.id) : undefined;
        let id = old?.id;
        if (!id) {
          const base = draft.name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "") || "stock";
          id = base;
          for (let n = 2; taken.has(id); n++) id = `${base}_${n}`;
          taken.add(id);
        }
        return {
          id,
          name: draft.name.trim(),
          capacity_l: draft.capacity_l,
          level_l: Math.min(draft.level_l, draft.capacity_l),
          dose_ml: draft.dose_ml,
          dose_entity: draft.dose_entity || null,
          low_l: Math.min(draft.low_l, draft.capacity_l),
          refilled_at: old?.refilled_at ?? null,
          updated_at: now,
        };
      });
    } else if (action === "stock_refill") {
      const tank = doc.tanks.find((t) => t.id === data.id);
      if (!tank) throw new Error(`There is no stock tank ${String(data.id)}.`);
      const level = data.level_l;
      if (level === undefined || level === null) {
        tank.level_l = tank.capacity_l;
        tank.refilled_at = now;
      } else if (typeof level === "number" && level >= 0 && level <= tank.capacity_l) {
        tank.level_l = level;
      } else throw new Error("The level must be between 0 L and the tank's capacity.");
      tank.updated_at = now;
    } else if (action === "stock_record_batch") {
      const draw: Record<string, number> = {};
      for (const tank of doc.tanks) {
        const before = tank.level_l;
        tank.level_l = Math.round(Math.max(0, before - tank.dose_ml / 1000) * 1e4) / 1e4;
        draw[tank.id] = Math.round((before - tank.level_l) * 1e4) / 10;
      }
      doc.history = [{ at: now, source: "manual" as const, draw_ml: draw }, ...doc.history].slice(0, 30);
    } else throw new Error("Unsupported demo action.");
    return this.finish(doc);
  }
}
