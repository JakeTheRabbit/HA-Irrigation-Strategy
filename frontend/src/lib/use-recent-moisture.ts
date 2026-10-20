import { useEffect, useState } from "react";
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
