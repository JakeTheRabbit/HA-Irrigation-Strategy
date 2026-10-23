import { afterEach, describe, expect, it, vi } from "vitest";
import { calendarDays, formatClock, formatDateTime, setClockTimeZone } from "./clock";
import { dayWord } from "./utils";
import { tickLabel } from "./tank-history";

const at = Date.UTC(2026, 0, 1, 0, 30); // 13:30 in Auckland, 19:30 the evening before in New York
const inZone = (timeZone: string, weekday = false) =>
  new Date(at).toLocaleString([], {
    ...(weekday ? { weekday: "short" as const } : {}),
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  });

afterEach(() => setClockTimeZone(undefined));

describe("one clock for every page", () => {
  it("tells the time on Home Assistant's clock, whatever the browser's", () => {
    setClockTimeZone("Pacific/Auckland");
    expect(formatClock(at)).toBe(inZone("Pacific/Auckland"));
    expect(formatClock(new Date(at).toISOString())).toBe(inZone("Pacific/Auckland"));
    expect(formatClock(at, { weekday: true })).toBe(inZone("Pacific/Auckland", true));
    setClockTimeZone("America/New_York");
    expect(formatClock(at)).toBe(inZone("America/New_York"));
  });
  it("is what the charts' hour labels say too", () => {
    setClockTimeZone("America/New_York");
    expect(tickLabel(at, 24)).toBe(inZone("America/New_York"));
  });
});

describe("the day, on Home Assistant's calendar", () => {
  // `at` is 1 January 13:30 in Auckland but still 31 December 19:30 in New York; this is
  // 31 December in both (05:00 New York, 23:00 Auckland).
  const lateEvening = Date.UTC(2025, 11, 31, 10, 0);
  it("counts days in Home Assistant's zone, not the browser's", () => {
    setClockTimeZone("America/New_York");
    expect(calendarDays(lateEvening, at)).toBe(0); // both 31 December in New York
    expect(dayWord(lateEvening, at)).toBe("");
    setClockTimeZone("Pacific/Auckland");
    expect(calendarDays(Date.UTC(2025, 11, 31, 9, 0), at)).toBe(1); // 31 Dec 22:00 Auckland
    expect(dayWord(Date.UTC(2025, 11, 31, 9, 0), at)).toBe("Yesterday");
  });
  it("formats a date and time on Home Assistant's clock", () => {
    setClockTimeZone("America/New_York");
    const options = { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" } as const;
    expect(formatDateTime(at, options)).toBe(
      new Date(at).toLocaleString([], { ...options, timeZone: "America/New_York" }),
    );
  });
  it("falls back to the browser's zone, once and with a warning, for a zone this browser rejects", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    setClockTimeZone("Mars/Olympus_Mons");
    expect(formatClock(at)).toBe(new Date(at).toLocaleString([], { hour: "2-digit", minute: "2-digit" }));
    setClockTimeZone("Mars/Olympus_Mons");
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });
});
