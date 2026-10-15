import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createDemo } from "./demo";
import { buildRoom, discoverRooms } from "./model";
import { OperatorDemo } from "./operator-demo";
import type { SetupDocument } from "./operator-types";
import {
  ecType,
  fusionMethod,
  probeChoicePayload,
  probeChoices,
  probeHealth,
  roomProbeIds,
  STUCK_MS,
  zoneProbes,
} from "./probes";

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
  it("carries each probe's reading quality and reason, when the integration gives them", () => {
    expect(zoneProbes(room.zones[2], states, now)[0]).toMatchObject({
      quality: null,
      reason: null,
    });
    const fusedId = room.zones[2].vwc.entityId!;
    const fused = states[fusedId];
    const first = (fused.attributes.used as string[])[0];
    const graded = {
      ...states,
      [fusedId]: {
        ...fused,
        attributes: {
          ...fused.attributes,
          quality: { [first]: { quality: "suspect", reason: "stale" } },
        },
      },
    };
    expect(zoneProbes(room.zones[2], graded, now)[0]).toMatchObject({
      id: first,
      quality: "suspect",
      reason: "stale",
    });
  });
  it("stands the combined sensor in for its probes on an older integration", () => {
    const f1 = buildRoom(
      states,
      discoverRooms(states).find((item) => item.prefix === "room_b_")!,
    );
    const probes = zoneProbes(f1.zones[0], states, now);
    expect(probes.map((probe) => [probe.id, probe.used, probe.health])).toEqual([
      ["sensor.crop_steering_room_b_vwc_zone_1", null, "ok"],
      ["sensor.crop_steering_room_b_ec_zone_1", null, "ok"],
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

describe("how a zone's reading is made from its probes", () => {
  const fused = (attributes: Record<string, unknown>) =>
    ({ entity_id: "sensor.crop_steering_vwc_zone_1", state: "51", attributes }) as never;
  it("names the method the zone steered by", () => {
    expect(fusionMethod(fused({ method: "Median", steered_by: "Median" }))).toBe(
      "median of its probes",
    );
    expect(fusionMethod(fused({ method: "Lowest", steered_by: "Lowest" }))).toBe(
      "lowest of its probes",
    );
  });
  it("says why Lowest or Highest fell back to the median", () => {
    expect(fusionMethod(fused({ method: "Lowest", steered_by: "Median" }))).toBe(
      "median of its probes: Lowest needs three that agree",
    );
  });
  it("says nothing for an older integration", () => {
    expect(fusionMethod(fused({ used: ["sensor.a"] }))).toBeNull();
    expect(fusionMethod(undefined)).toBeNull();
  });
});

describe("which EC a zone with pore and bulk EC probes steers on", () => {
  const fused = (attributes: Record<string, unknown>) =>
    ({ entity_id: "sensor.crop_steering_ec_zone_1", state: "3.0", attributes }) as never;
  it("says pore, and bulk with why", () => {
    expect(ecType(fused({ ec_type: "pore" }))).toBe("steers on its pore EC probes");
    expect(ecType(fused({ ec_type: "bulk" }))).toBe(
      "steers on its bulk EC probes: no pore EC probe is reporting",
    );
  });
  it("says nothing for a zone without both, or an older integration", () => {
    expect(ecType(fused({ used: ["sensor.a"] }))).toBeNull();
    expect(ecType(undefined)).toBeNull();
  });
});

describe("which of a zone's probes count, and its primary", () => {
  it("is a probe left out by choice, not a fault", () => {
    expect(health({ excluded: "not counted", state: "unavailable" })).toEqual({
      health: "not-counted",
      text: "Does not count",
    });
  });
  it("sends only the choice, and shows it once saved", async () => {
    let states = createDemo(now);
    const demo = new OperatorDemo(
      () => states,
      (next) => (states = next),
    );
    const zones = () =>
      buildRoom(
        states,
        discoverRooms(states).find((item) => item.prefix === "")!,
      ).zones;
    const before = zones().flatMap((zone) => zoneProbes(zone, states, now));
    const choices = probeChoices(before);
    expect(choices["1:vwc"]).toEqual({ unused: [], primary: "" });
    choices["1:vwc"] = { unused: ["sensor.demo_z1_back_vwc"], primary: "sensor.demo_z1_front_vwc" };
    const setup = await demo.call<SetupDocument>("setup_read", {});
    const room = setup.rooms.find((item) => item.prefix === "")!;
    const payload = probeChoicePayload(room, choices);
    expect(Object.keys(payload)).toEqual(["entry_id", "expected_revision", "zones"]);
    expect(payload.zones[0]).toEqual({
      id: 1,
      active: true,
      vwc_unused: ["sensor.demo_z1_back_vwc"],
      vwc_primary: "sensor.demo_z1_front_vwc",
      ec_unused: [],
      ec_primary: "",
    });
    await demo.call("setup_save", payload);
    const after = zoneProbes(zones()[0], states, now);
    expect(after.map((probe) => [probe.name, probe.health, probe.primary])).toEqual([
      ["Zone 1 front VWC", "ok", true],
      ["Zone 1 back VWC", "not-counted", false],
      ["Zone 1 front EC", "ok", false],
      ["Zone 1 back EC", "ok", false],
    ]);
    expect(probeChoices(after)["1:vwc"]).toEqual(choices["1:vwc"]);
  });
});
