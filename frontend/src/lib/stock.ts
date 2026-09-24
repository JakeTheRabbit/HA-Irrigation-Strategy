import type { Tone } from "@/components/mini-visuals";

/** A room's stock tanks, as the integration's stock services return them (stock_api.py). */
export interface StockTank {
  id: string;
  name: string;
  capacity_l: number;
  level_l: number;
  /** The fixed dose per batch; a dose entity's reading takes over while it reads a number. */
  dose_ml: number;
  dose_entity: string | null;
  low_l: number;
  refilled_at: string | null;
  updated_at: string;
}
export interface StockBatch {
  at: string;
  source: "fill" | "manual";
  draw_ml: Record<string, number>;
}
export interface StockDocument {
  schema_version: 1;
  room_id: string;
  revision: number;
  tanks: StockTank[];
  last_batch: string | null;
  history: StockBatch[];
  /** The tank last-fill entity batches are counted from; null means batches are recorded by hand. */
  fill_entity: string | null;
  /** What one batch takes from each tank right now, in mL. */
  doses: Record<string, number>;
  low: string[];
  max_tanks: number;
  error: string | null;
}
/** What the editor sends for one tank; `id` is absent for a new one. */
export type StockTankDraft = Omit<StockTank, "id" | "refilled_at" | "updated_at"> & {
  id?: string;
};

export const stockShare = (tank: Pick<StockTank, "level_l" | "capacity_l">) =>
  tank.capacity_l > 0 ? Math.max(0, Math.min(100, (tank.level_l / tank.capacity_l) * 100)) : 0;

export const batchesLeft = (tank: Pick<StockTank, "level_l">, doseMl: number | undefined) =>
  doseMl && doseMl > 0 ? Math.floor(Math.round(tank.level_l * 1000 * 1e6) / 1e6 / doseMl) : null;

/** Red at or under the low mark, amber within half as much again, normal above. */
export function stockTone(tank: Pick<StockTank, "level_l" | "low_l">): Tone {
  if (tank.level_l <= tank.low_l) return "over";
  return tank.level_l <= tank.low_l * 1.5 ? "high" : "normal";
}

/** The checks the integration makes (stock.py clean_tanks), so the editor can say so first. */
export function draftErrors(drafts: StockTankDraft[], max = 12): string[] {
  const errors: string[] = [];
  if (drafts.length > max) errors.push(`At most ${max} stock tanks per room.`);
  const names = new Set<string>();
  for (const tank of drafts) {
    const name = tank.name.trim();
    const label = name || "A tank";
    if (!name || name.length > 40) errors.push("Each tank needs a name of 1 to 40 characters.");
    else if (names.has(name.toLowerCase())) errors.push(`Two tanks are called ${name}.`);
    names.add(name.toLowerCase());
    if (!(tank.capacity_l >= 0.1 && tank.capacity_l <= 10000))
      errors.push(`${label}: capacity must be between 0.1 and 10000 L.`);
    if (!(tank.level_l >= 0 && tank.level_l <= tank.capacity_l))
      errors.push(`${label}: the level must be between 0 L and its capacity.`);
    if (!(tank.dose_ml >= 0 && tank.dose_ml <= 100000))
      errors.push(`${label}: the dose per batch must be between 0 and 100000 mL.`);
    if (!(tank.low_l >= 0 && tank.low_l <= tank.capacity_l))
      errors.push(`${label}: the low mark must be between 0 L and its capacity.`);
    if (tank.dose_entity && !/^(number|input_number|sensor)\.[a-z0-9_]+$/.test(tank.dose_entity))
      errors.push(`${label}: the dose entity must be a number, input_number or sensor.`);
  }
  return errors;
}
