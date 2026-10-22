import { getDisplayUnits } from "./display-units";

/** Wall-clock maths in a named time zone (Home Assistant's, `controller.timeZone`), whatever the
 * viewer's own. Every page's time of day and day boundary comes from here. */

const formats = new Map<string, Intl.DateTimeFormat>();
function format(tz: string) {
  let f = formats.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    formats.set(tz, f);
  }
  return f;
}

interface Wall {
  y: number;
  m: number;
  d: number;
  h: number;
  min: number;
  s: number;
}
function wall(ms: number, tz: string): Wall {
  const p: Record<string, number> = {};
  for (const part of format(tz).formatToParts(ms)) if (part.type !== "literal") p[part.type] = Number(part.value);
  return { y: p.year, m: p.month, d: p.day, h: p.hour % 24, min: p.minute, s: p.second };
}
/** How far the zone's wall clock is ahead of UTC at `ms`. */
function offset(ms: number, tz: string) {
  const w = wall(ms, tz);
  return Date.UTC(w.y, w.m - 1, w.d, w.h, w.min, w.s) - (ms - (((ms % 1000) + 1000) % 1000));
}
/** The instant the zone's clock reads this wall time (`d` may overflow into the next month). */
function zoned(y: number, m: number, d: number, h: number, min: number, tz: string) {
  const guess = Date.UTC(y, m - 1, d, h, min);
  const first = guess - offset(guess, tz);
  return guess - offset(first, tz);
}
const pad = (n: number) => String(n).padStart(2, "0");
const hhmm = (text: string) => {
  const [h, m] = text.split(":").map(Number);
  return { h: h || 0, m: m || 0 };
};

/** "14:02", or "2:02 pm" with the 12-hour clock of the display units. */
export function clock(ms: number, tz: string): string {
  const { h, min } = wall(ms, tz);
  if (getDisplayUnits().clock === "24") return `${pad(h)}:${pad(min)}`;
  return `${h % 12 || 12}:${pad(min)} ${h < 12 ? "am" : "pm"}`;
}
/** The zone's calendar date: "2026-10-22". */
export function dayKey(ms: number, tz: string): string {
  const { y, m, d } = wall(ms, tz);
  return `${y}-${pad(m)}-${pad(d)}`;
}
/** Midnight of the zone's calendar date holding `ms`. */
export function startOfDay(ms: number, tz: string): number {
  const { y, m, d } = wall(ms, tz);
  return zoned(y, m, d, 0, 0, tz);
}
/** Lights on and off for the date holding `dayStartMs`, by the wall clock: an off time at or
 * before the on time is the next morning, so a daylight-saving night is an hour shorter or longer. */
export function lightsWindow(dayStartMs: number, onHHMM: string, offHHMM: string, tz: string): { on: number; off: number } {
  const { y, m, d } = wall(dayStartMs, tz);
  const on = hhmm(onHHMM),
    off = hhmm(offHHMM);
  const nextDay = off.h * 60 + off.m <= on.h * 60 + on.m ? 1 : 0;
  return { on: zoned(y, m, d, on.h, on.m, tz), off: zoned(y, m, d + nextDay, off.h, off.m, tz) };
}
