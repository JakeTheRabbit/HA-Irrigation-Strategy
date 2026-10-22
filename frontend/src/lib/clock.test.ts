import { afterEach, describe, expect, it } from "vitest";
import { formatClock, setClockTimeZone } from "./clock";
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
