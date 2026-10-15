import { rangeText } from "./day-chart";
import type { JevSetpointKey, JevSetpoints } from "./jev";

/** A zone's targets as a grower reads them: one short table, grouped by phase, in the order each
 * acts through the day. `key` is the setting as the controller resolves it (buildSetpointPreview's
 * parameters: the steering mode picks the dryback and EC targets). */
export interface TargetRow {
  key: string;
  label: string;
  unit: string;
  /** Digits a value is shown with. */
  digits?: number;
}
export interface TargetGroup {
  phase: "P0" | "P1" | "P2" | "P3";
  title: string;
  rows: TargetRow[];
}
export const TARGET_GROUPS: readonly TargetGroup[] = [
  {
    phase: "P0",
    title: "P0 · Morning dryback",
    rows: [
      {
        key: "p0_maximum_wait_time",
        label: "Start delay (latest first shot)",
        unit: "min",
        digits: 0,
      },
      { key: "ec_target_p0", label: "EC target", unit: "mS/cm", digits: 2 },
    ],
  },
  {
    phase: "P1",
    title: "P1 · Ramp-up",
    rows: [
      { key: "p1_target_vwc", label: "Peak target", unit: "%" },
      { key: "p1_initial_shot_size", label: "First shot", unit: "%" },
      { key: "p1_shot_size_increment", label: "Each shot adds", unit: "%", digits: 2 },
      { key: "p1_maximum_shots", label: "Most shots", unit: "shots", digits: 0 },
      { key: "p1_time_between_shots", label: "Time between shots", unit: "min", digits: 0 },
      { key: "ec_target_p1", label: "EC target", unit: "mS/cm", digits: 2 },
    ],
  },
  {
    phase: "P2",
    title: "P2 · Maintenance",
    rows: [
      { key: "p2_vwc_threshold", label: "Re-water point", unit: "%" },
      { key: "p2_shot_size", label: "Shot size", unit: "%" },
      { key: "ec_target_p2", label: "EC target", unit: "mS/cm", digits: 2 },
    ],
  },
  {
    phase: "P3",
    title: "P3 · Overnight dryback",
    rows: [
      { key: "dryback_target", label: "Dryback target", unit: "% of peak" },
      { key: "p3_emergency_vwc_threshold", label: "Rescue level", unit: "%" },
      { key: "p3_emergency_shot_size", label: "Rescue shot", unit: "%" },
    ],
  },
];

/** The setting groups Equipment › Setup keeps (model.ts group()): what the substrate holds, what turns
 * a shot's percentage into litres and seconds, and the limits that hold or add watering. Targets
 * keeps the rest. */
export const SETUP_GROUPS: readonly string[] = ["Substrate", "Hardware sizing", "Safety"];

/** How far Jev may move a target tonight, as the chip beside it says: "Jev · 4–6 %". Null for a
 * target Jev does not manage on this zone, or while it does not manage any. */
export function jevChip(setpoints: JevSetpoints | null, key: string, unit: string): string | null {
  if (!setpoints?.managed) return null;
  const range = setpoints.range[key as JevSetpointKey];
  return range ? `Jev · ${rangeText(range)}${unit ? ` ${unit}` : ""}` : null;
}
