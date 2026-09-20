/** Common substrate sizes that fill the pot-volume field. Volumes are litres per plant. */
export type SubstrateGroup = "block" | "us-pot" | "metric-pot";
export interface SubstratePreset {
  id: string;
  group: SubstrateGroup;
  name: string;
  litres: number;
  /** Width × depth × height of a block, the source of its volume. */
  dimensionsCm?: readonly [number, number, number];
}
export const SUBSTRATE_PRESET_GROUPS: { id: SubstrateGroup; label: string }[] = [
  { id: "block", label: "Rockwool blocks · volume from dimensions" },
  { id: "us-pot", label: "Pots · nominal US gallons" },
  { id: "metric-pot", label: "Pots · litres" },
];
/** Block volume from its outer dimensions in centimetres, to two significant figures. */
export const blockLitres = (width: number, depth: number, height: number): number =>
  Number(((width * depth * height) / 1000).toPrecision(2));
const block = (id: string, name: string, ...dimensionsCm: [number, number, number]) => ({
  id,
  group: "block" as const,
  name,
  litres: blockLitres(...dimensionsCm),
  dimensionsCm,
});
const pot = (group: "us-pot" | "metric-pot", size: number, litres: number) => ({
  id: `pot-${size}${group === "us-pot" ? "gal" : "l"}`,
  group,
  name: `${size} ${group === "us-pot" ? "gal" : "L"} pot`,
  litres,
});
export const SUBSTRATE_PRESETS: readonly SubstratePreset[] = [
  block("rockwool-4in", "Rockwool 4 in cube", 10, 10, 6.5),
  block("rockwool-hugo", "Rockwool Hugo", 15, 15, 14.2),
  // Nominal trade sizes, not exact US gallons.
  pot("us-pot", 1, 3.8),
  pot("us-pot", 2, 7.6),
  pot("us-pot", 3, 11.4),
  pot("us-pot", 5, 18.9),
  pot("us-pot", 7, 26.5),
  ...[5, 10, 15, 20].map((size) => pot("metric-pot", size, size)),
];
export function presetLabel(preset: SubstratePreset): string {
  return [
    preset.name + (preset.group === "us-pot" ? " (nominal)" : ""),
    ...(preset.dimensionsCm ? [`${preset.dimensionsCm.join(" × ")} cm`] : []),
    `${preset.litres} L`,
  ].join(" · ");
}
/** The preset whose volume the draft currently holds; null is "Custom". */
export const matchPreset = (litres: number): SubstratePreset | null =>
  SUBSTRATE_PRESETS.find((preset) => Math.abs(preset.litres - litres) < 1e-9) ?? null;
