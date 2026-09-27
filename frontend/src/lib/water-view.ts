import { createContext, createElement, useContext, useMemo, type ReactNode } from "react";
import { dailyWater, positiveCount, waterParameters } from "./water-delivery";
import type { Controller, Zone } from "./types";

/** How Water today reads: each zone's total, as it always has, or what each of its plants got. One
 * choice per room, kept in Home Assistant (select.crop_steering_<prefix>water_today_view), so everyone
 * who opens the room sees it the same way and the controller's vitals notification follows it. */
export type WaterView = "zone" | "plant";
/** The select's words for each view (the integration's WATER_TODAY_VIEWS). */
export const WATER_VIEW_OPTIONS: Record<WaterView, string> = {
  zone: "Zone total",
  plant: "Per plant",
};

export const WaterViewContext = createContext<{
  view: WaterView;
  /** False when the room has no select to keep the choice in (an older integration). */
  available: boolean;
  setView: (view: WaterView) => Promise<void>;
}>({ view: "zone", available: false, setView: async () => {} });
export const useWaterView = () => useContext(WaterViewContext);
/** What a Water today column or tile is called: the cells then say mL or L, not "per plant". */
export const waterTodayLabel = (view: WaterView) =>
  view === "plant" ? "Water today per plant" : "Water today";

/** The selected room's choice, for the whole dashboard; changing it writes the room's select. */
export function WaterViewProvider({
  controller,
  children,
}: {
  controller: Controller;
  children: ReactNode;
}) {
  const { entityId, view } = controller.room.waterView;
  const { write } = controller;
  const value = useMemo(
    () => ({
      view,
      available: entityId !== null,
      setView: async (next: WaterView) => {
        if (!entityId) throw new Error("This needs the updated Crop Steering integration.");
        const result = await write([{ entityId, value: WATER_VIEW_OPTIONS[next] }]);
        if (result.failed.length) throw new Error(result.failed[0].reason);
      },
    }),
    [entityId, view, write],
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
