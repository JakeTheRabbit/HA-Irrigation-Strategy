import { afterEach, describe, expect, test } from "vitest";
import { clock, dayKey, lightsWindow, startOfDay } from "./time";
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
});
