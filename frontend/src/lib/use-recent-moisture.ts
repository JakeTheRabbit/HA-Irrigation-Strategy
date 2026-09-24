import { useEffect, useState } from "react";
import { DRYBACK_WINDOW_H } from "./dryback";
import type { Controller, Series } from "./types";

/**
 * The room's moisture readings over the dryback window, re-read about every five minutes;
 * null until the first answer for the current zones arrives.
 */
export function useRecentMoisture(controller: Controller): Series[] | null {
  const key = controller.room.zones
    .map((zone) => zone.vwc.entityId)
    .filter((id): id is string => Boolean(id))
    .join("|");
  const tick = Math.floor((controller.lastUpdated ?? 0) / 300_000);
  const [read, setRead] = useState<{ key: string; series: Series[] } | null>(null);
  useEffect(() => {
    let current = true;
    if (!key) {
      setRead({ key, series: [] });
      return;
    }
    // One hour more than the window, so the value held at the window's start is included.
    controller
      .history(key.split("|"), DRYBACK_WINDOW_H + 1)
      .then((series) => current && setRead({ key, series }))
      .catch(() => current && setRead({ key, series: [] }));
    return () => {
      current = false;
    };
  }, [controller.roomId, controller.connection, key, tick]);
  return read && read.key === key ? read.series : null;
}
