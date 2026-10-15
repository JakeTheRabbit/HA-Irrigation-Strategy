import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createDemo } from "./demo";
import { buildRoom, discoverRooms } from "./model";
import { probeHealth, roomProbeIds, STUCK_MS, zoneProbes } from "./probes";

const now = new Date(2026, 8, 28, 16, 0).getTime();
const H = 3_600_000;
const health = (input: Partial<Parameters<typeof probeHealth>[0]>) =>
  probeHealth({
    kind: "vwc",
    state: "58.2",
    unit: "%",
    reported: now - 60_000,
    changed: now - 10 * 60_000,
    excluded: null,
    now,
    ...input,
  });

describe("a probe's health", () => {
  it("is OK while it reads, in range, and moves", () => {
    expect(health({})).toEqual({ health: "ok", text: "OK" });
  });
  it("takes the integration's reason for leaving it out first", () => {
    expect(health({ excluded: "not reporting", reported: now - 3 * H })).toEqual({
      health: "stale",
      text: "Silent 3 h, left out of the zone's reading",
    });
    expect(health({ excluded: "out of range", state: "4.2" }).health).toBe("out-of-range");
    expect(health({ excluded: "no reading", state: "58" }).health).toBe("no-reading");
    expect(health({ excluded: "calibrating" })).toEqual({
      health: "left-out",
      text: "Left out: calibrating",
    });
  });
  it("finds what the integration cannot say: no reading, a value out of range, a stuck one", () => {
    expect(health({ state: "unavailable" })).toEqual({ health: "no-reading", text: "No reading" });
    expect(health({ state: "121" }).text).toBe("Reads 121 %: out of range");
    expect(health({ kind: "ec", state: "25", unit: "mS/cm" }).health).toBe("out-of-range");
    expect(health({ changed: now - 4 * H })).toEqual({
      health: "stuck",
      text: "Unchanged for 4 h",
    });
    // Pore EC sits still for hours overnight before it counts as stuck.
    expect(health({ kind: "ec", state: "4.1", changed: now - 4 * H }).health).toBe("ok");
    expect(health({ kind: "ec", state: "4.1", changed: now - STUCK_MS.ec - 60_000 }).health).toBe(
      "stuck",
    );
  });
  it("is stale when the zone's own reading says so, for a combined sensor standing in", () => {
    expect(health({ stale: true, reported: null })).toEqual({
      health: "stale",
      text: "Not reporting",
    });
  });
});

describe("a zone's probes", () => {
  // The room reads the clock to tell a fresh reading: pinned to the demo's.
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(now);
  });
  afterEach(() => vi.useRealTimers());
  const states = createDemo(now);
  const room = buildRoom(
    states,
    discoverRooms(states).find((item) => item.prefix === "")!,
  );
  it("lists each probe the integration names, moisture first, the used ones before the rest", () => {
    const probes = zoneProbes(room.zones[2], states, now);
    expect(probes.map((probe) => [probe.kind, probe.name, probe.used, probe.health])).toEqual([
      ["vwc", "Zone 3 front VWC", true, "ok"],
      ["vwc", "Zone 3 back VWC", true, "ok"],
      ["ec", "Zone 3 front EC", true, "ok"],
      ["ec", "Zone 3 back EC", false, "stale"],
    ]);
    expect(probes[3].text).toBe("Silent 3 h, left out of the zone's reading");
    expect(probes[0].value).toBe(60.8);
  });
  it("stands the combined sensor in for its probes on an older integration", () => {
    const f1 = buildRoom(
      states,
      discoverRooms(states).find((item) => item.prefix === "f1_")!,
    );
    const probes = zoneProbes(f1.zones[0], states, now);
    expect(probes.map((probe) => [probe.id, probe.used, probe.health])).toEqual([
      ["sensor.crop_steering_f1_vwc_zone_1", null, "ok"],
      ["sensor.crop_steering_f1_ec_zone_1", null, "ok"],
    ]);
  });
  it("names every probe of the room once, for the page to watch and draw", () => {
    expect(roomProbeIds(room.zones, states)).toEqual(
      [1, 2, 3]
        .flatMap((zone) =>
          ["front", "back"].flatMap((side) =>
            ["vwc", "ec"].map((kind) => `sensor.demo_z${zone}_${side}_${kind}`),
          ),
        )
        .sort(),
    );
  });
});
