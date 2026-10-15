import type { Notice } from "./types";

/** When a zone needs a person, and why, in words: the rules behind the flag on a Today card. A card
 * is quiet unless one of them holds. Pure, so every rule is tested on its own. */

export type AttentionLevel = "critical" | "warning";
export type AttentionRule =
  "not-watered" | "probe" | "alert" | "rescue" | "pore-ec" | "water" | "jev-paused";
export interface AttentionReason {
  rule: AttentionRule;
  level: AttentionLevel;
  text: string;
}
export interface Reading {
  time: number;
  value: number;
}
export interface ZoneFacts {
  id: number;
  name: string;
  phase: string;
  /** The zone's moisture and pore EC now; null when the reading is not usable. */
  vwc: number | null;
  ec: number | null;
  /** Why a reading is not usable ("not reporting", "stale"), or null when it is. */
  vwcIssue: string | null;
  ecIssue: string | null;
  /** Probes the zone's combined reading leaves out, with the integration's reason. */
  excluded: { probe: string; reason: string; kind: "vwc" | "ec" }[];
  /** Water per plant today, in mL; null when the zone's water or plant count is unknown. */
  mlPerPlant: number | null;
  /** The P2 re-water point: a maintenance shot fires under it. */
  rewater: number | null;
  /** Today's moisture readings, oldest first. */
  readings: Reading[];
  /** When the zone's last shot started (epoch ms). */
  lastShot: number | null;
  /** Until when Jev leaves this zone's setpoints alone after putting a change back (epoch ms). */
  jevPausedUntil: number | null;
  /** The controller is watering the zone: not when the room, its watering or the zone is off. */
  watering: boolean;
}
export interface RescueShot {
  zoneId: number;
  time: number;
}
export interface AttentionInput {
  now: number;
  zones: ZoneFacts[];
  /** The stage's pore EC band, else null. */
  poreEc: readonly [number, number] | null;
  /** The room's open notices; a zone's own ones flag its card. */
  notices: readonly Notice[];
  /** Rescue (P3 emergency) shots the controller recorded. */
  rescues: readonly RescueShot[];
  /** Formats a clock time, a number and a volume per plant (the page's own words for them). */
  format: {
    clock: (time: number) => string;
    number: (value: number, digits?: number) => string;
    perPlant: (ml: number) => string;
  };
}

/** How long a zone may sit under its re-water point in P2 without a shot before it is flagged. */
export const DRY_MINUTES = 60;
/** How far back a rescue shot still flags its zone. */
export const RESCUE_HOURS = 12;
/** Water per plant flags outside these shares of the room's. */
export const WATER_LOW = 0.7;
export const WATER_HIGH = 1.4;
/** Too early in the grow-day to compare water (a few shots in, one shot is a big share). */
export const WATER_MIN_ML = 100;

/** Since when the latest readings have all been under `level`: the first reading of that run. Null
 * when the newest reading is not under it. */
export function underSince(readings: readonly Reading[], level: number): number | null {
  let since: number | null = null;
  for (let index = readings.length - 1; index >= 0; index--) {
    if (!(readings[index].value < level)) break;
    since = readings[index].time;
  }
  return since;
}

/** The share the room's water per plant is compared with: the median of every zone (the zone's own
 * included); with two zones, the other one. Null with fewer than two. */
export function roomReference(
  zones: readonly Pick<ZoneFacts, "id" | "name" | "mlPerPlant">[],
  zoneId: number,
): { ml: number; name: string | null } | null {
  const known = zones.filter(
    (zone) => zone.mlPerPlant !== null && Number.isFinite(zone.mlPerPlant),
  );
  if (known.length < 2 || !known.some((zone) => zone.id === zoneId)) return null;
  if (known.length === 2) {
    const other = known.find((zone) => zone.id !== zoneId)!;
    return { ml: other.mlPerPlant!, name: other.name };
  }
  const values = known.map((zone) => zone.mlPerPlant!).sort((a, b) => a - b);
  const middle = values.length / 2;
  const ml =
    values.length % 2 ? values[Math.floor(middle)] : (values[middle - 1] + values[middle]) / 2;
  return { ml, name: null };
}

const ORDER: AttentionRule[] = [
  "not-watered",
  "probe",
  "alert",
  "rescue",
  "pore-ec",
  "water",
  "jev-paused",
];

/** Each zone's reasons, most urgent first: critical before warning, then in the order above. A
 * zone with none is not in the map. */
export function zoneAttention(input: AttentionInput): Map<number, AttentionReason[]> {
  const { now, zones, poreEc, notices, rescues, format } = input;
  const result = new Map<number, AttentionReason[]>();
  for (const zone of zones) {
    const reasons: AttentionReason[] = [];
    const add = (rule: AttentionRule, level: AttentionLevel, text: string) =>
      reasons.push({ rule, level, text });

    // Under its re-water point in maintenance, and no shot since it went under.
    if (zone.watering && zone.phase === "P2" && zone.rewater !== null && zone.vwc !== null) {
      const since = underSince(zone.readings, zone.rewater);
      const minutes = since === null ? 0 : Math.floor((now - since) / 60_000);
      if (
        zone.vwc < zone.rewater &&
        minutes > DRY_MINUTES &&
        (zone.lastShot === null || zone.lastShot < since!)
      )
        add(
          "not-watered",
          "critical",
          `Under its re-water point (${format.number(zone.rewater)}%) for ${minutes} min, no shot`,
        );
    }

    // A probe the controller cannot use: the moisture probe stops the zone's steering.
    if (zone.vwcIssue) add("probe", "critical", `Moisture probe ${zone.vwcIssue}`);
    if (zone.ecIssue) add("probe", "warning", `Pore EC probe ${zone.ecIssue}`);
    for (const kind of ["vwc", "ec"] as const) {
      const out = zone.excluded.filter((item) => item.kind === kind);
      if (out.length)
        add(
          "probe",
          "warning",
          `${out.length === 1 ? "A" : out.length} ${kind === "vwc" ? "moisture" : "pore EC"} probe${
            out.length === 1 ? "" : "s"
          } left out: ${[...new Set(out.map((item) => item.reason))].join(", ")}`,
        );
    }

    // The zone's own open notices; its sensor notice says what the probe rule already said.
    for (const notice of notices)
      if (
        notice.zoneId === zone.id &&
        notice.severity !== "info" &&
        !(notice.id.endsWith("-sensors") && (zone.vwcIssue || zone.ecIssue))
      )
        add("alert", notice.severity, notice.title);

    const rescue = rescues
      .filter(
        (shot) =>
          shot.zoneId === zone.id &&
          shot.time <= now &&
          now - shot.time <= RESCUE_HOURS * 3_600_000,
      )
      .sort((a, b) => b.time - a.time)[0];
    if (rescue) add("rescue", "warning", `Rescue shot at ${format.clock(rescue.time)}`);

    if (zone.ec !== null && poreEc && (zone.ec < poreEc[0] || zone.ec > poreEc[1]))
      add(
        "pore-ec",
        "warning",
        `Pore EC ${format.number(zone.ec)}, ${zone.ec < poreEc[0] ? "under" : "over"} the stage’s ${format.number(poreEc[0])}–${format.number(poreEc[1])}`,
      );

    const reference = roomReference(zones, zone.id);
    if (reference && zone.mlPerPlant !== null && reference.ml >= WATER_MIN_ML) {
      const share = zone.mlPerPlant / reference.ml;
      if (share > WATER_HIGH || share < WATER_LOW)
        add(
          "water",
          "warning",
          `${format.perPlant(zone.mlPerPlant)}/plant today, ${format.number(share)}× ${reference.name ?? "the room"}`,
        );
    }

    if (zone.jevPausedUntil !== null && zone.jevPausedUntil > now)
      add(
        "jev-paused",
        "warning",
        `Jev’s setpoint changes paused until ${format.clock(zone.jevPausedUntil)} after a revert`,
      );

    if (reasons.length)
      result.set(
        zone.id,
        reasons.sort(
          (a, b) =>
            (a.level === "critical" ? 0 : 1) - (b.level === "critical" ? 0 : 1) ||
            ORDER.indexOf(a.rule) - ORDER.indexOf(b.rule),
        ),
      );
  }
  return result;
}
