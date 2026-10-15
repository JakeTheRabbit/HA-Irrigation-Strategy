import { describe, expect, it } from "vitest";
import data from "./substrate-presets.json";
import {
  SUBSTRATE_PRESETS,
  SUBSTRATE_PRESET_GROUPS,
  blockLitres,
  presetLabel,
  shownPreset,
} from "./substrate-presets";
import { SIZING_BOUNDS } from "./units";

const preset = (id: string) => SUBSTRATE_PRESETS.find((item) => item.id === id)!;

describe("substrate presets", () => {
  it("computes block volume from the stated dimensions", () => {
    expect(blockLitres(10, 10, 6.5)).toBe(0.65);
    expect(blockLitres(15, 15, 14.2)).toBe(3.2);
    expect(preset("rockwool-4in").dimensionsCm).toEqual([10, 10, 6.5]);
    expect(preset("rockwool-4in").litres).toBe(0.65);
    expect(preset("rockwool-delta-10").litres).toBe(1);
    expect(preset("rockwool-hugo").dimensionsCm).toEqual([15, 15, 14.2]);
    expect(preset("rockwool-hugo").litres).toBe(3.2);
  });
  it("offers exactly the agreed blocks, slabs and pots, with nominal litres for US pots", () => {
    expect(SUBSTRATE_PRESETS.map((item) => [item.name, item.litres])).toEqual([
      ["Rockwool 4 in cube", 0.65],
      ["Rockwool Delta 10", 1],
      ["Rockwool Hugo", 3.2],
      ["Nutrifield 0.9 gal", 3.37],
      ["Nutrifield 1.5 gal", 5.8],
      ["Rockwool uni-slab", 5],
      ["Rockwool Mama block", 8],
      ["Rockwool slab", 10],
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
  it("keeps vendor sizes in the data file, each row a stated volume or a block's dimensions", () => {
    expect(data.presets.map((row) => row.id)).toEqual(SUBSTRATE_PRESETS.map((item) => item.id));
    const ids = SUBSTRATE_PRESETS.map((item) => item.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const row of data.presets as {
      group: string;
      litres?: number;
      dimensionsCm?: number[];
    }[]) {
      expect(row.litres !== undefined || row.dimensionsCm?.length === 3).toBe(true);
      if (row.group === "block") expect(row.litres).toBeUndefined();
    }
  });
  it("keeps every preset inside the limits the integration accepts", () => {
    const { min, max } = SIZING_BOUNDS.substrate_volume;
    for (const item of SUBSTRATE_PRESETS) {
      expect(item.litres).toBeGreaterThanOrEqual(min);
      expect(item.litres).toBeLessThanOrEqual(max);
    }
  });
  it("shows the litres of every preset, and the dimensions it has", () => {
    expect(presetLabel(preset("rockwool-4in"))).toBe(
      "Rockwool 4 in cube · 10 × 10 × 6.5 cm · 0.65 L",
    );
    expect(presetLabel(preset("rockwool-hugo"))).toBe("Rockwool Hugo · 15 × 15 × 14.2 cm · 3.2 L");
    // Nutrifield's own litres, under its own heading: not worked out from the dimensions.
    expect(presetLabel(preset("nutrifield-15x15x16"))).toBe(
      "Nutrifield 0.9 gal · 15 × 15 × 16 cm · 3.37 L",
    );
    expect(presetLabel(preset("nutrifield-18x18x18"))).toBe(
      "Nutrifield 1.5 gal · 18 × 18 × 18 cm · 5.8 L",
    );
    expect(presetLabel(preset("rockwool-slab"))).toBe("Rockwool slab · 10 L");
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
  it("never names a pot from its volume: only the preset picked here shows", () => {
    // A saved or typed volume reads Custom even when a preset holds the same litres.
    expect(shownPreset(null, 3.2)).toBe("custom");
    expect(shownPreset(null, 18.9)).toBe("custom");
    expect(shownPreset("rockwool-hugo", 3.2)).toBe("rockwool-hugo");
    // Two presets share 10 L; the one picked is the one shown.
    expect(shownPreset("pot-10l", 10)).toBe("pot-10l");
    expect(shownPreset("rockwool-slab", 10)).toBe("rockwool-slab");
    // Typing another volume after a pick goes back to Custom.
    expect(shownPreset("rockwool-hugo", 3.3)).toBe("custom");
    expect(shownPreset("pot-5gal", 18.92705892)).toBe("custom");
    expect(shownPreset("pot-5gal", NaN)).toBe("custom");
    expect(shownPreset("no-such-preset", 5)).toBe("custom");
  });
});
