import { findSession } from "./client";
import { displayEntityId } from "./display";
import type { Controller } from "./types";
import { LITRES_PER_US_GALLON, initialUnitSystem, unitSystemFromHass, VOLUME_CHOICE_KEY } from "./units";

/** How the dashboard shows EC, temperature, volume and the time of day. Display only: storage and
 * every service stay in mS/cm, °C and litres. Filled from the selected room's display options
 * (`ec_unit`, `temp_unit`, `volume_unit`, `clock` on sensor.crop_steering_<prefix>display). */
export type EcUnit = "mS/cm" | "ppm500" | "ppm700";
export type TempUnit = "C" | "F";
export type VolumeUnit = "L" | "gal";
export type ClockStyle = "24" | "12";
export interface DisplayUnits {
  ec: EcUnit;
  temp: TempUnit;
  volume: VolumeUnit;
  clock: ClockStyle;
}
/** What a room asks for: `volume: "auto"` follows Home Assistant's unit system (lib/units.ts). */
export type DisplayUnitSettings = Omit<DisplayUnits, "volume"> & { volume: VolumeUnit | "auto" };

/** This browser's choice where the integration has no unit options (3.17). */
export const UNITS_STORAGE_KEY = "crop-steering.units";
const DEFAULTS: DisplayUnitSettings = { ec: "mS/cm", temp: "C", volume: "auto", clock: "24" };
const EC: readonly string[] = ["mS/cm", "ppm500", "ppm700"];
const TEMP: readonly string[] = ["C", "F"];
const VOLUME: readonly string[] = ["auto", "L", "gal"];

let current: DisplayUnitSettings = { ...DEFAULTS };

function readLocal(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** `auto` is resolved at read time, with the rule the zone sizing fields use: Home Assistant's
 * unit system, else this browser's last sizing choice, else litres. */
function resolveVolume(volume: DisplayUnitSettings["volume"]): VolumeUnit {
  if (volume !== "auto") return volume;
  return initialUnitSystem(unitSystemFromHass(findSession()), readLocal(VOLUME_CHOICE_KEY)) === "us" ? "gal" : "L";
}

export function getDisplayUnits(): DisplayUnits {
  return { ...current, volume: resolveVolume(current.volume) };
}
export function setDisplayUnits(u: Partial<DisplayUnitSettings>): void {
  current = { ...current, ...u };
}

const clockOf = (value: unknown): ClockStyle | undefined =>
  value === 12 || value === "12" ? "12" : value === 24 || value === "24" ? "24" : undefined;
const pick = <T extends string>(value: unknown, allowed: readonly string[]): T | undefined =>
  typeof value === "string" && allowed.includes(value) ? (value as T) : undefined;

/** The settings from a room's display attributes; each one it lacks comes from this browser's
 * stored choice (JSON under `crop-steering.units`), else the default. */
export function readDisplayUnits(
  attributes: Record<string, unknown> | undefined,
  stored: string | null,
): DisplayUnitSettings {
  let local: Record<string, unknown> = {};
  try {
    const parsed: unknown = stored ? JSON.parse(stored) : null;
    if (parsed && typeof parsed === "object") local = parsed as Record<string, unknown>;
  } catch {
    /* A damaged choice reads as none. */
  }
  const a = attributes ?? {};
  return {
    ec: pick<EcUnit>(a.ec_unit, EC) ?? pick<EcUnit>(local.ec, EC) ?? DEFAULTS.ec,
    temp: pick<TempUnit>(a.temp_unit, TEMP) ?? pick<TempUnit>(local.temp, TEMP) ?? DEFAULTS.temp,
    volume:
      pick<DisplayUnitSettings["volume"]>(a.volume_unit, VOLUME) ??
      pick<DisplayUnitSettings["volume"]>(local.volume, VOLUME) ??
      DEFAULTS.volume,
    clock: clockOf(a.clock) ?? clockOf(local.clock) ?? DEFAULTS.clock,
  };
}

/** Called once by the app shell: fills the store from the selected room before its pages render. */
export function useDisplayUnits(controller: Controller): DisplayUnits {
  const prefix = controller.roomId.replace(/^room:/, "");
  setDisplayUnits(readDisplayUnits(controller.states[displayEntityId(prefix)]?.attributes, readLocal(UNITS_STORAGE_KEY)));
  return getDisplayUnits();
}

/** Never more digits than the source has. */
const fixed = (value: number, digits: number) => value.toFixed(Math.max(0, digits));

export function formatEc(ms: number, sourceDigits: number): string {
  const { ec } = getDisplayUnits();
  if (ec === "mS/cm") return `${fixed(ms, sourceDigits)} mS/cm`;
  // 0.1 mS/cm is 50 or 70 ppm: whole ppm is already finer than any EC probe reads.
  return `${fixed(ms * (ec === "ppm500" ? 500 : 700), 0)} ppm`;
}
export function formatTemp(c: number, sourceDigits: number): string {
  return getDisplayUnits().temp === "F" ? `${fixed((c * 9) / 5 + 32, sourceDigits)} °F` : `${fixed(c, sourceDigits)} °C`;
}
export function formatVolume(l: number, sourceDigits: number): string {
  return getDisplayUnits().volume === "gal"
    ? `${fixed(l / LITRES_PER_US_GALLON, sourceDigits)} gal`
    : `${fixed(l, sourceDigits)} L`;
}
/** A typed EC back to mS/cm: ppm when the text says so or the display shows ppm. */
export function parseEc(text: string): number | null {
  const match = /^\s*(-?\d+(?:[.,]\d+)?)\s*(mS\/cm|ppm)?\s*$/i.exec(text);
  if (!match) return null;
  const value = Number(match[1].replace(",", "."));
  const { ec } = getDisplayUnits();
  const unit = match[2]?.toLowerCase() ?? (ec === "mS/cm" ? "ms/cm" : "ppm");
  if (unit === "ms/cm") return value;
  return Number((value / (ec === "ppm700" ? 700 : 500)).toPrecision(12));
}
