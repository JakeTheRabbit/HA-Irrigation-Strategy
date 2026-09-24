import { useEffect, useState } from "react";
import { DRYBACK_WINDOW_H, drybackTrend, type DrybackTrend } from "./dryback";
import type { Controller, Series } from "./types";

/**
 * The recorded readings of `ids` over the last `hours`, in one request, re-read about every five
 * minutes; null until the first answer for these ids arrives. No ids, no request.
 */
export function useRecentHistory(
  controller: Controller,
  ids: string[],
  hours: number,
): Series[] | null {
  const key = ids.join("|");
  const tick = Math.floor((controller.lastUpdated ?? 0) / 300_000);
  const [read, setRead] = useState<{ key: string; series: Series[] } | null>(null);
  useEffect(() => {
    let current = true;
    if (!key) {
      setRead({ key, series: [] });
      return;
    }
    controller
      .history(key.split("|"), hours)
      .then((series) => current && setRead({ key, series }))
      .catch(() => current && setRead({ key, series: [] }));
    return () => {
      current = false;
    };
  }, [controller.roomId, controller.connection, key, hours, tick]);
  return read && read.key === key ? read.series : null;
}

/**
 * The room's moisture readings over the dryback window, re-read about every five minutes;
 * null until the first answer for the current zones arrives.
 */
export function useRecentMoisture(controller: Controller): Series[] | null {
  // One hour more than the window, so the value held at the window's start is included.
  return useRecentHistory(
    controller,
    controller.room.zones
      .map((zone) => zone.vwc.entityId)
      .filter((id): id is string => Boolean(id)),
    DRYBACK_WINDOW_H + 1,
  );
}

/** Each zone's dryback from the room's recent moisture; null while the readings load. */
export function useDrybackTrends(controller: Controller): Record<number, DrybackTrend> | null {
  const moisture = useRecentMoisture(controller);
  const now = Date.now();
  return (
    moisture &&
    Object.fromEntries(
      controller.room.zones.map((zone) => [
        zone.id,
        drybackTrend(
          moisture.find((series) => series.entityId === zone.vwc.entityId)?.points ?? [],
          zone.lastIrrigation.timestamp,
          zone.vwc.value,
          now,
        ),
      ]),
    )
  );
}
