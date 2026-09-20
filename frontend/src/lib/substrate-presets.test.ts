import { describe, expect, it } from "vitest";
import {
  SUBSTRATE_PRESETS,
  SUBSTRATE_PRESET_GROUPS,
  blockLitres,
  matchPreset,
  presetLabel,
} from "./substrate-presets";
import { SIZING_BOUNDS } from "./units";

const preset = (id: string) => SUBSTRATE_PRESETS.find((item) => item.id === id)!;

describe("substrate presets", () => {
  it("computes block volume from the stated dimensions", () => {
    expect(blockLitres(10, 10, 6.5)).toBe(0.65);
    expect(blockLitres(15, 15, 14.2)).toBe(3.2);
    expect(preset("rockwool-4in").dimensionsCm).toEqual([10, 10, 6.5]);
    expect(preset("rockwool-4in").litres).toBe(0.65);
    expect(preset("rockwool-hugo").dimensionsCm).toEqual([15, 15, 14.2]);
    expect(preset("rockwool-hugo").litres).toBe(3.2);
  });
  it("offers exactly the agreed blocks and pots, with nominal litres for US pots", () => {
    expect(SUBSTRATE_PRESETS.map((item) => [item.name, item.litres])).toEqual([
      ["Rockwool 4 in cube", 0.65],
      ["Rockwool Hugo", 3.2],
      ["1 gal pot", 3.8],
      ["2 gal pot", 7.6],
      ["3 gal pot", 11.4],
      ["5 gal pot", 18.9],
      ["7 gal pot", 26.5],
      ["5 L pot", 5],
      ["10 L pot", 10],
      ["15 L pot", 15],
      ["20 L pot", 20],
    ]);
  });
  it("keeps every preset inside the limits the integration accepts", () => {
    const { min, max } = SIZING_BOUNDS.substrate_volume;
    for (const item of SUBSTRATE_PRESETS) {
      expect(item.litres).toBeGreaterThanOrEqual(min);
      expect(item.litres).toBeLessThanOrEqual(max);
    }
  });
  it("shows the litres of every preset, and the dimensions of a block", () => {
    expect(presetLabel(preset("rockwool-4in"))).toBe(
      "Rockwool 4 in cube · 10 × 10 × 6.5 cm · 0.65 L",
    );
    expect(presetLabel(preset("rockwool-hugo"))).toBe("Rockwool Hugo · 15 × 15 × 14.2 cm · 3.2 L");
    expect(presetLabel(preset("pot-5gal"))).toBe("5 gal pot (nominal) · 18.9 L");
    expect(presetLabel(preset("pot-10l"))).toBe("10 L pot · 10 L");
    for (const item of SUBSTRATE_PRESETS) expect(presetLabel(item)).toContain(`${item.litres} L`);
  });
  it("groups every preset under a heading", () => {
    const grouped = SUBSTRATE_PRESET_GROUPS.flatMap((group) =>
      SUBSTRATE_PRESETS.filter((item) => item.group === group.id),
    );
    expect(grouped).toHaveLength(SUBSTRATE_PRESETS.length);
  });
  it("recognises a preset volume and treats anything else as custom", () => {
    expect(matchPreset(18.9)?.id).toBe("pot-5gal");
    expect(matchPreset(0.65)?.id).toBe("rockwool-4in");
    expect(matchPreset(5)?.id).toBe("pot-5l");
    // An exact 5 US gal is not the nominal 5 gal pot.
    expect(matchPreset(18.92705892)).toBeNull();
    expect(matchPreset(6)).toBeNull();
    expect(matchPreset(NaN)).toBeNull();
  });
  it("has no two presets with the same volume, so a match is unambiguous", () => {
    const volumes = SUBSTRATE_PRESETS.map((item) => item.litres);
    expect(new Set(volumes).size).toBe(volumes.length);
  });
});
