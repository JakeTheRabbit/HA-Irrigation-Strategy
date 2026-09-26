import { describe, expect, it } from "vitest";
import { mlPerPlant, plantAmount, readWaterView, roomPerPlant, saveWaterView } from "./water-view";
import type { Zone } from "./types";

const zone = (id: number, value: number | null, unit = "L") =>
  ({ id, name: `Zone ${id}`, water: { value, unit } }) as unknown as Zone;
const memory = () => {
  const saved = new Map<string, string>();
  return {
    getItem: (key: string) => saved.get(key) ?? null,
    setItem: (key: string, value: string) => void saved.set(key, value),
  };
};
const refusing = {
  getItem: () => {
    throw new Error("storage refused");
  },
  setItem: () => {
    throw new Error("storage refused");
  },
};

describe("the choice between zone total and per plant", () => {
  it("is the zone total until someone chooses per plant, in this browser", () => {
    const storage = memory();
    expect(readWaterView(storage)).toBe("zone");
    saveWaterView("plant", storage);
    expect(readWaterView(storage)).toBe("plant");
    saveWaterView("zone", storage);
    expect(readWaterView(storage)).toBe("zone");
  });
  it("falls back to the zone total when storage is refused or holds anything else", () => {
    expect(readWaterView(refusing)).toBe("zone");
    expect(() => saveWaterView("plant", refusing)).not.toThrow();
    const storage = memory();
    storage.setItem("irrigation-water-view", "per-plant");
    expect(readWaterView(storage)).toBe("zone");
  });
});

describe("water per plant", () => {
  it("divides a zone's litres by its plants, in mL", () => {
    expect(mlPerPlant(5.3, 36)).toBeCloseTo(147.22, 2);
    expect(mlPerPlant(40, 36)).toBeCloseTo(1111.11, 2); // a 40 L daily limit
  });
  it("is nothing without a whole, positive plant count or a reading", () => {
    for (const plants of [null, 0, -3, 2.5]) expect(mlPerPlant(5.3, plants)).toBeNull();
    expect(mlPerPlant(null, 36)).toBeNull();
  });
  it("reads in mL below a litre and in litres from one up", () => {
    expect(plantAmount(147.2)).toEqual({ value: 147.2, unit: "mL", digits: 0 });
    expect(plantAmount(1111.1)).toEqual({ value: 1.1111, unit: "L", digits: 1 });
  });
  it("across the room, weights each zone by its plants and leaves out a zone it cannot divide", () => {
    const zones = [zone(1, 5.3), zone(2, 6.2), zone(3, 7.1), zone(4, 9)];
    const plants = { 1: 36, 2: 36, 3: 72, 4: null };
    const room = roomPerPlant(zones, plants)!;
    expect(room.plants).toBe(144);
    expect(room.ml).toBeCloseTo(((5.3 + 6.2 + 7.1) * 1000) / 144, 6);
  });
  it("reads a zone recorded in mL as litres", () => {
    expect(roomPerPlant([zone(1, 3600, "mL")], { 1: 36 })!.ml).toBeCloseTo(100, 6);
    expect(roomPerPlant([zone(1, null)], { 1: 36 })).toBeNull();
  });
});
