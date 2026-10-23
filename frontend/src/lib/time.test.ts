import { afterEach, describe, expect, test } from "vitest";
import { clock, dayEndText, dayKey, dayLabel, daysBefore, hourClock, hourTicks, lightsWindow, startOfDay } from "./time";
import { setDisplayUnits } from "./display-units";

const NZ = "Pacific/Auckland";
const HOUR = 3_600_000;

afterEach(() => setDisplayUnits({ clock: "24" }));

describe("zoned time", () => {
  test("lightsWindow 06:00–18:00 on 2026-09-27 Pacific/Auckland is 12 h", () => {
    const day = startOfDay(Date.parse("2026-09-27T12:00:00+13:00"), NZ);
    const { on, off } = lightsWindow(day, "06:00", "18:00", NZ);
    expect(on).toBe(Date.parse("2026-09-27T06:00:00+13:00"));
    expect(off - on).toBe(12 * HOUR);
  });
  test("lightsWindow 20:00–08:00 from 26 Sep crossing the NZ spring-forward is 11 h of real time", () => {
    const day = startOfDay(Date.parse("2026-09-26T12:00:00+12:00"), NZ);
    const { on, off } = lightsWindow(day, "20:00", "08:00", NZ);
    expect(on).toBe(Date.parse("2026-09-26T20:00:00+12:00"));
    expect(off).toBe(Date.parse("2026-09-27T08:00:00+13:00"));
    expect(off - on).toBe(11 * HOUR);
  });
  test("clock 14:02 in 24 h and 2:02 pm in 12 h", () => {
    const ms = Date.parse("2026-10-22T14:02:30+13:00");
    expect(clock(ms, NZ)).toBe("14:02");
    setDisplayUnits({ clock: "12" });
    expect(clock(ms, NZ)).toBe("2:02 pm");
    expect(clock(Date.parse("2026-10-22T00:05:00+13:00"), NZ)).toBe("12:05 am");
  });
  test("dayKey and startOfDay follow the zone, not the browser", () => {
    const ms = Date.parse("2026-10-22T23:30:00Z"); // 12:30 on the 23rd in Auckland
    expect(dayKey(ms, NZ)).toBe("2026-10-23");
    expect(dayKey(ms, "UTC")).toBe("2026-10-22");
    expect(startOfDay(ms, NZ)).toBe(Date.parse("2026-10-23T00:00:00+13:00"));
  });
  test("hourTicks lands on local whole hours in a +05:30 zone", () => {
    const IN = "Asia/Kolkata";
    const start = Date.parse("2026-10-22T00:00:00+05:30");
    const ticks = hourTicks(start, start + 24 * HOUR, 2, IN);
    expect(ticks).toHaveLength(12);
    expect(ticks.map((t) => clock(t, IN)).slice(0, 3)).toEqual(["00:00", "02:00", "04:00"]);
    // A span starting off the hour starts at the next local even hour.
    expect(clock(hourTicks(start + 61 * 60_000, start + 6 * HOUR, 2, IN)[0], IN)).toBe("02:00");
  });
  test("hourTicks keeps local hours across the NZ spring-forward (+12:45 Chatham too)", () => {
    const day = startOfDay(Date.parse("2026-09-27T12:00:00+13:00"), NZ);
    expect(hourTicks(day, day + 23 * HOUR, 4, NZ).map((t) => clock(t, NZ))).toEqual([
      "00:00",
      "04:00",
      "08:00",
      "12:00",
      "16:00",
      "20:00",
    ]);
    const CH = "Pacific/Chatham";
    const c = startOfDay(Date.parse("2026-10-22T12:00:00+13:45"), CH);
    expect(hourTicks(c, c + 12 * HOUR, 1, CH).map((t) => clock(t, CH))[1]).toBe("01:00");
    expect(c).toBe(Date.parse("2026-10-22T00:00:00+13:45"));
  });
  test("daysBefore keeps the zone's wall time across a daylight-saving change", () => {
    // NZ springs forward on 27 Sep 2026: seven days back from 3 Oct 14:00 is 26 Sep 14:00, 167 h.
    const now = Date.parse("2026-10-03T14:00:00+13:00");
    expect(daysBefore(now, 7, NZ)).toBe(Date.parse("2026-09-26T14:00:00+12:00"));
    expect(now - daysBefore(now, 7, NZ)).toBe(167 * HOUR);
  });
  test("dayLabel names the zone's date", () => {
    // 20:00 UTC on the 21st is already Thursday the 22nd in Auckland.
    expect(dayLabel(Date.parse("2026-10-21T20:00:00Z"), NZ)).toBe("Thu 22 Oct");
  });
});

describe("hourClock (Task 26)", () => {
  test("writes a lights hour as HH:MM, rounding to the minute without 60", () => {
    expect(hourClock(6.5)).toBe("06:30");
    expect(hourClock(6.999)).toBe("07:00");
    expect(hourClock(23.999)).toBe("00:00");
    expect(hourClock(22)).toBe("22:00");
  });
});

describe("dayEndText (Task 26 round 2)", () => {
  test("the day's last tick: 24:00 on the 24-hour clock, the display clock's midnight otherwise", () => {
    expect(dayEndText()).toBe("24:00");
    setDisplayUnits({ clock: "12" });
    expect(dayEndText()).toBe("12:00 am");
  });
});
