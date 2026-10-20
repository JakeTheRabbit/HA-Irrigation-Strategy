/** Common substrate sizes that fill the pot-volume field. Volumes are litres per plant. */
import data from "./substrate-presets.json";

export type SubstrateGroup = "block" | "nutrifield" | "slab" | "us-pot" | "metric-pot";
export interface SubstratePreset {
  id: string;
  group: SubstrateGroup;
  name: string;
  litres: number;
  /** Width × depth × height in centimetres: a block's volume comes from them. */
  dimensionsCm?: readonly [number, number, number];
}
/** A row of the data file: a stated volume, or a block's dimensions to work it out from. */
type PresetRow = Omit<SubstratePreset, "litres"> & { litres?: number };
export const SUBSTRATE_PRESET_GROUPS = data.groups as { id: SubstrateGroup; label: string }[];
/** Block volume from its outer dimensions in centimetres, to two significant figures. */
export const blockLitres = (width: number, depth: number, height: number): number =>
  Number(((width * depth * height) / 1000).toPrecision(2));
// Vendor sizes live in the data file. A stated volume wins over the outer dimensions
// (Nutrifield's 15 × 15 × 16 cm outside would be 3.6 L, not its stated 3.37 L);
// US pots are nominal trade sizes, not exact US gallons.
export const SUBSTRATE_PRESETS: readonly SubstratePreset[] = (
  data.presets as unknown as PresetRow[]
).map((row) => ({ ...row, litres: row.litres ?? blockLitres(...row.dimensionsCm!) }));
export function presetLabel(preset: SubstratePreset): string {
  return [
    preset.name + (preset.group === "us-pot" ? " (nominal)" : ""),
    ...(preset.dimensionsCm ? [`${preset.dimensionsCm.join(" × ")} cm`] : []),
    `${preset.litres} L`,
  ].join(" · ");
}
/**
 * What the picker shows. A zone keeps its pot volume, not what fills the pot, and the volume
 * cannot say: a 3.2 L coco bag holds what a Rockwool Hugo block does. So a preset shows only
 * while the volume is the one it filled in here; any other volume, typed or saved, reads Custom.
 */
export function shownPreset(picked: string | null, litres: number): string {
  const preset = SUBSTRATE_PRESETS.find((item) => item.id === picked);
  return preset && Math.abs(preset.litres - litres) < 1e-9 ? preset.id : "custom";
}
