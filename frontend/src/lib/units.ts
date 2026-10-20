/** Units for the zone sizing fields. Setup drafts, payloads and limits are always metric;
 * a unit only changes what the operator types and reads. */
export const LITRES_PER_US_GALLON = 3.785411784;
export type UnitSystem = "metric" | "us";
export type SizingKey = "substrate_volume" | "dripper_flow_rate";
export interface SizingUnit {
  system: UnitSystem;
  /** Beside a value: "US gal". */
  symbol: string;
  /** Picker option text. */
  name: string;
  /** Metric value = typed value × factor. */
  factor: number;
}
export const SIZING_UNITS: Record<"volume" | "flow", Record<UnitSystem, SizingUnit>> = {
  volume: {
    metric: { system: "metric", symbol: "L", name: "Litres (L)", factor: 1 },
    us: {
      system: "us",
      symbol: "US gal",
      name: "US gallons (US gal)",
      factor: LITRES_PER_US_GALLON,
    },
  },
  flow: {
    metric: { system: "metric", symbol: "L/h", name: "Litres per hour (L/h)", factor: 1 },
    us: {
      system: "us",
      symbol: "US GPH",
      name: "US gallons per hour (US GPH)",
      factor: LITRES_PER_US_GALLON,
    },
  },
};
/** Mirrors SIZING in custom_components/crop_steering/setup_api.py, in litres and L/h. */
export const SIZING_BOUNDS: Record<SizingKey, { min: number; max: number }> = {
  substrate_volume: { min: 0.1, max: 200 },
  dripper_flow_rate: { min: 0.1, max: 50 },
};
const FIELDS: Record<SizingKey, { name: string; per: string; metric: SizingUnit; saved: string }> =
  {
    substrate_volume: {
      name: "Pot volume",
      per: "per plant",
      metric: SIZING_UNITS.volume.metric,
      saved: "litres",
    },
    dripper_flow_rate: {
      name: "Dripper flow",
      per: "each",
      metric: SIZING_UNITS.flow.metric,
      saved: "litres per hour",
    },
  };

/** Binary floating-point noise only (18.927058919999997 → 18.92705892); the factor stays exact. */
const clean = (value: number) => Number(value.toPrecision(12));
/** What the draft holds for a typed value. Metric entries pass through untouched. */
export const toMetric = (typed: number, unit: SizingUnit): number =>
  !Number.isFinite(typed) ? NaN : unit.factor === 1 ? typed : clean(typed * unit.factor);
export const fromMetric = (metric: number, unit: SizingUnit): number =>
  Number.isFinite(metric) ? metric / unit.factor : NaN;
/** Display rounding only; never feed the result back into a draft. */
export const displayNumber = (value: number, digits = 3): string =>
  Number.isFinite(value) ? String(Number(value.toFixed(digits))) : "";

export const sizingLabel = (key: SizingKey, unit: SizingUnit) =>
  `${FIELDS[key].name} · ${unit.symbol} ${FIELDS[key].per}`;
/** The saved metric value, shown beside an entry typed in another unit. */
export function metricNote(metric: number, key: SizingKey, unit: SizingUnit): string | null {
  if (unit.factor === 1 || !Number.isFinite(metric)) return null;
  const field = FIELDS[key];
  return `= ${displayNumber(metric)} ${field.metric.symbol} ${field.per}, saved in ${field.saved}`;
}
/** Review line: the metric value being saved, plus what was typed when that was another unit. */
export function reviewValue(metric: number, key: SizingKey, unit: SizingUnit): string {
  const saved = `${displayNumber(metric)} ${FIELDS[key].metric.symbol}`;
  return unit.factor === 1
    ? saved
    : `${saved} (${displayNumber(fromMetric(metric, unit))} ${unit.symbol})`;
}
/** Empty when the integration would accept the value. Limits are quoted in the unit being typed,
 * rounded inwards so the quoted range is never wider than the real one. */
export function sizingError(metric: number, key: SizingKey, unit: SizingUnit): string {
  const field = FIELDS[key],
    { min, max } = SIZING_BOUNDS[key];
  if (!Number.isFinite(metric)) return `Enter the ${field.name.toLowerCase()} in ${unit.symbol}.`;
  if (metric >= min && metric <= max) return "";
  const range = `${min}–${max} ${field.metric.symbol}`;
  if (unit.factor === 1) return `${field.name} must be ${range}.`;
  const low = Math.ceil((min / unit.factor) * 1000) / 1000,
    high = Math.floor((max / unit.factor) * 1000) / 1000;
  return `${field.name} must be ${low}–${high} ${unit.symbol} (${range}).`;
}

/** Unit system of the Home Assistant page embedding this dashboard, from its `hass` object.
 * Null when not embedded or unreadable: the caller must not guess. */
export function unitSystemFromHass(hass: unknown): UnitSystem | null {
  const config = (hass as { config?: { unit_system?: { volume?: unknown } } | null } | undefined)
    ?.config;
  const volume = config?.unit_system?.volume;
  return volume === "gal" ? "us" : volume === "L" ? "metric" : null;
}
export const rememberedUnitSystem = (stored: string | null): UnitSystem | null =>
  stored === "metric" || stored === "us" ? stored : null;
/** Home Assistant's unit system when known, else this browser's last choice, else metric. */
export const initialUnitSystem = (ha: UnitSystem | null, stored: string | null): UnitSystem =>
  ha ?? rememberedUnitSystem(stored) ?? "metric";
