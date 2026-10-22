/**
 * The dashboard's one clock: a time of day on Home Assistant's clock (its `time_zone`, the one the
 * controller keeps the grow-day on), never the browser's, so one event reads the same on every page
 * wherever the browser is. The controller store sets the zone once it knows it (use-controller.ts);
 * until then, and in a test that sets none, it is the browser's.
 */
let homeZone: string | undefined;

export function setClockTimeZone(timeZone: string | undefined) {
  homeZone = timeZone;
}

/** "14:05" (or "2:05 PM", by the browser's language); `weekday` puts the day's short name first. */
export function formatClock(
  time: number | string | Date,
  { weekday = false }: { weekday?: boolean } = {},
): string {
  return new Date(time).toLocaleString([], {
    ...(weekday ? { weekday: "short" as const } : {}),
    hour: "2-digit",
    minute: "2-digit",
    timeZone: homeZone,
  });
}
