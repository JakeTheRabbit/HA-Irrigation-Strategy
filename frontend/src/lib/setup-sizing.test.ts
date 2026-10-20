import { expect, it } from "vitest";
import { sizingChangedSince } from "./setup-sizing";
import type { SetupRoom } from "./operator-types";
const room = {
  zones: [
    { id: 1, plant_count: 4, substrate_volume: 10, drippers_per_plant: 2, dripper_flow_rate: 1.2 },
  ],
} as SetupRoom;
it("detects live hydraulic edits before a stale setup draft can overwrite them", () => {
  expect(sizingChangedSince(room, structuredClone(room))).toBe(false);
  for (const key of [
    "plant_count",
    "substrate_volume",
    "drippers_per_plant",
    "dripper_flow_rate",
  ] as const) {
    const fresh = structuredClone(room);
    fresh.zones[0][key] = 20;
    expect(sizingChangedSince(room, fresh), key).toBe(true);
  }
});
it("rejects a stale draft for a removed zone", () => {
  expect(sizingChangedSince(room, { ...room, zones: [] })).toBe(true);
});
