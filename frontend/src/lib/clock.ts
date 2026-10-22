/**
 * The dashboard's one clock: a time of day, a date and a calendar day on Home Assistant's clock (its
 * `time_zone`, the one the controller keeps the grow-day on), never the browser's, so one event
 * reads the same on every page wherever the browser is. The controller store sets the zone once it
 * knows it (use-controller.ts); until then, and in a test that sets none, it is the browser's.
 */
let homeZone: string | undefined;
const rejected = new Set<string>();

/** A zone this browser does not know falls back to the browser's own, with one warning. */
export function setClockTimeZone(timeZone: string | undefined) {
  homeZone = undefined;
  if (!timeZone) return;
  try {
    new Intl.DateTimeFormat("en", { timeZone });
    homeZone = timeZone;
  } catch {
    if (!rejected.has(timeZone))
      console.warn(`Time zone ${timeZone} is unknown to this browser: times show in its own.`);
    rejected.add(timeZone);
  }
}

/** A date and/or time with `options`, on Home Assistant's clock. */
export function formatDateTime(
  time: number | string | Date,
  options: Intl.DateTimeFormatOptions,
): string {
  return new Date(time).toLocaleString([], { ...options, timeZone: homeZone });
}

/** "14:05" (or "2:05 PM", by the browser's language); `weekday` puts the day's short name first. */
export function formatClock(
  time: number | string | Date,
  { weekday = false }: { weekday?: boolean } = {},
): string {
  return formatDateTime(time, {
    ...(weekday ? { weekday: "short" as const } : {}),
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** How many calendar days `at` is before `now` (negative after) on Home Assistant's calendar. */
export function calendarDays(at: number, now: number): number {
  const day = (ms: number) => {
    const parts = Object.fromEntries(
      new Intl.DateTimeFormat("en-CA", {
        year: "numeric",
        month: "numeric",
        day: "numeric",
        timeZone: homeZone,
      })
        .formatToParts(ms)
        .map((part) => [part.type, Number(part.value)]),
    );
    return Date.UTC(parts.year, parts.month - 1, parts.day) / 86_400_000;
  };
  return day(now) - day(at);
}

/** A full date and time, as a hover title or a "last reported" line shows it. */
export const DATE_TIME: Intl.DateTimeFormatOptions = { dateStyle: "short", timeStyle: "short" };
