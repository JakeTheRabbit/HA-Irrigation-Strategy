import type { SteeringProfile } from "./operator-types";

/** Irrigation › Calendar reference rows (Settings › Display): climate and feed bands a grower writes beside
 * a profile's irrigation endpoints. They drive nothing: the controller never gets them. The zone
 * page's climate gauges colour a value outside today's band. Stored in the plan, in the profile. */
export const REFERENCE_ROWS = [
  {
    key: "temp_day",
    label: "Air temperature, lights on",
    unit: "°",
    min: -20,
    max: 130,
    step: 0.1,
  },
  {
    key: "temp_night",
    label: "Air temperature, lights off",
    unit: "°",
    min: -20,
    max: 130,
    step: 0.1,
  },
  { key: "humidity", label: "Humidity", unit: "%", min: 0, max: 100, step: 1 },
  { key: "vpd", label: "VPD", unit: "kPa", min: 0, max: 5, step: 0.01 },
  { key: "co2", label: "CO2", unit: "ppm", min: 0, max: 5000, step: 10 },
  { key: "ppfd", label: "PPFD", unit: "µmol/m²/s", min: 0, max: 3000, step: 10 },
  { key: "dli", label: "DLI", unit: "mol/m²/day", min: 0, max: 100, step: 0.1 },
  { key: "feed_ph", label: "Feed pH", unit: "pH", min: 0, max: 14, step: 0.1 },
] as const;
export type ReferenceKey = (typeof REFERENCE_ROWS)[number]["key"];
export type Reference = Partial<Record<ReferenceKey, [number, number]>>;

/** Only whole bands, low under or at high, inside each row's range. */
export function cleanReference(reference: Reference | undefined): Reference {
  const out: Reference = {};
  for (const row of REFERENCE_ROWS) {
    const band = reference?.[row.key];
    if (
      Array.isArray(band) &&
      band.length === 2 &&
      band.every((value) => Number.isFinite(value) && value >= row.min && value <= row.max) &&
      band[0] <= band[1]
    )
      out[row.key] = [band[0], band[1]];
  }
  return out;
}

/** The profile with these bands, as typed (a half-typed band stays in the draft; the integration
 * keeps only whole bands); without the key at all when every row is empty, as a plan saved before
 * the rows. */
export function withReference(profile: SteeringProfile, reference: Reference): SteeringProfile {
  const { reference: _old, ...rest } = profile;
  const kept = Object.fromEntries(
    Object.entries(reference).filter(
      ([, band]) => Array.isArray(band) && band.some((value) => Number.isFinite(value)),
    ),
  ) as Reference;
  return Object.keys(kept).length ? { ...rest, reference: kept } : rest;
}

/** The climate bands for now, for the zone page's gauges: the day or night temperature by the
 * lights. */
export function climateBands(
  reference: Reference | undefined,
  lightsOn: boolean,
): Partial<Record<"temperature" | "humidity" | "vpd", [number, number]>> {
  const clean = cleanReference(reference);
  const temperature = lightsOn ? clean.temp_day : clean.temp_night;
  return {
    ...(temperature ? { temperature } : {}),
    ...(clean.humidity ? { humidity: clean.humidity } : {}),
    ...(clean.vpd ? { vpd: clean.vpd } : {}),
  };
}
