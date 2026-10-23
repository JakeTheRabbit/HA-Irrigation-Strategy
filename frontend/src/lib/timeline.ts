import type { LogEvent } from "./types";

/** When the controller's activity records happened: its feed stamps them by ISO time or by "HH:MM". */

/** An activity record's time: an ISO stamp, or the controller's feed "HH:MM" on `reference`'s day
 * (the day before when that is still to come: the same wall-clock time, across a daylight-saving
 * change too). */
export function eventTime(stamp: string, reference: number): number | null {
  const clockOnly = stamp.match(/^(\d{1,2}):(\d{2})$/);
  if (!clockOnly) {
    const time = Date.parse(stamp);
    return Number.isFinite(time) ? time : null;
  }
  const date = new Date(reference);
  date.setHours(Number(clockOnly[1]), Number(clockOnly[2]), 0, 0);
  if (date.getTime() > reference + 5 * 60_000) date.setDate(date.getDate() - 1);
  return date.getTime();
}

/** Each record's time. The feed is newest first and says only "HH:MM": each line is read on the day
 * of the newer line before it, so a clock that goes forward down the list has crossed midnight. */
export function eventTimes(events: readonly LogEvent[], now: number): (number | null)[] {
  let newer = now;
  return events.map((event) => {
    const time = eventTime(event.timestamp, newer);
    if (time !== null && /^\d{1,2}:\d{2}$/.test(event.timestamp)) newer = time;
    return time;
  });
}
