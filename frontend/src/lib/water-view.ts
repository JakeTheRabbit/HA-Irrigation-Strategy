import { createContext, createElement, useContext, useMemo, useState, type ReactNode } from "react";
import { dailyWater, positiveCount, waterParameters } from "./water-delivery";
import type { Controller, Zone } from "./types";

/** How Water today reads: each zone's total, as it always has, or what each of its plants got.
 * One person's choice (Settings → Appearance), kept in this browser like the theme. */
export type WaterView = "zone" | "plant";
const KEY = "irrigation-water-view";

export function readWaterView(storage?: Pick<Storage, "getItem">): WaterView {
  try {
    return (storage ?? globalThis.localStorage)?.getItem(KEY) === "plant" ? "plant" : "zone";
  } catch {
    return "zone"; // storage refused (a private window): the default
  }
}
export function saveWaterView(view: WaterView, storage?: Pick<Storage, "setItem">) {
  try {
    (storage ?? globalThis.localStorage)?.setItem(KEY, view);
  } catch {
    // storage refused: the choice lasts this visit only
  }
}

export const WaterViewContext = createContext<{
  view: WaterView;
  setView: (view: WaterView) => void;
}>({ view: "zone", setView: () => {} });
export const useWaterView = () => useContext(WaterViewContext);
/** What a Water today column or tile is called: the cells then say mL or L, not "per plant". */
export const waterTodayLabel = (view: WaterView) =>
  view === "plant" ? "Water today per plant" : "Water today";

/** The whole dashboard reads the one choice, and a change shows everywhere at once. */
export function WaterViewProvider({ children }: { children: ReactNode }) {
  const [view, setView] = useState<WaterView>(() => readWaterView());
  const value = useMemo(
    () => ({
      view,
      setView: (next: WaterView) => {
        saveWaterView(next);
        setView(next);
      },
    }),
    [view],
  );
  return createElement(WaterViewContext.Provider, { value }, children);
}

/** The zone's configured plant count, as the Zones page's per-plant water reads it; null when it
 * is not a positive whole number. */
export function zonePlants(controller: Controller, zoneId: number): number | null {
  const plants = waterParameters(controller, zoneId).plant_count;
  return positiveCount(plants) ? plants : null;
}
export const roomPlants = (controller: Controller): Record<number, number | null> =>
  Object.fromEntries(
    controller.room.zones.map((zone) => [zone.id, zonePlants(controller, zone.id)]),
  );

/** Litres (a zone's water, or its daily limit) for each of its plants, in mL. */
export const mlPerPlant = (litres: number | null, plants: number | null) =>
  litres === null || !Number.isFinite(litres) || !positiveCount(plants)
    ? null
    : (litres * 1000) / plants;

/** Water for one plant, in mL below a litre and in litres from one up. */
export function plantAmount(ml: number): { value: number; unit: "mL" | "L"; digits: number } {
  return ml < 1000
    ? { value: ml, unit: "mL", digits: 0 }
    : { value: ml / 1000, unit: "L", digits: 1 };
}

/** The room's water today per plant: every zone whose water and plant count are known, each
 * weighted by its plants, so a big zone counts for more than a small one. */
export function roomPerPlant(zones: Zone[], plants: Record<number, number | null>) {
  let litres = 0,
    count = 0;
  for (const zone of zones) {
    const reading = dailyWater(zone, plants[zone.id] ?? null);
    if (reading.zoneL === null || reading.plants === null) continue;
    litres += reading.zoneL;
    count += reading.plants;
  }
  return count ? { ml: (litres * 1000) / count, plants: count } : null;
}
