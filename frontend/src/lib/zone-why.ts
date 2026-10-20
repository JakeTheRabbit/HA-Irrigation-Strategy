import { decisionEntry } from "./controller-health";
import type { JevZoneJudge } from "./jev";
import type { EntityState, Zone } from "./types";

/** Why a zone is doing what it is doing, in the controller's own words from its decision record: its
 * status for the zone, then this check's shot fired or held there. A stale zone says it is the last
 * report. Empty when the controller has said nothing about the zone. */
export function zoneReasons(
  zone: Pick<Zone, "id" | "status" | "stale">,
  decision: EntityState | undefined,
): string[] {
  const fired = decisionEntry(decision, zone.id, "fired");
  const held = decisionEntry(decision, zone.id, "blocked");
  return [
    zone.status && zone.status !== "Unavailable"
      ? `${zone.stale ? "Last report: " : ""}${zone.status}`
      : "",
    fired === null ? "" : `Watered at this check: ${fired}`,
    held === null ? "" : `Held at this check: ${held}`,
  ].filter(Boolean);
}

/** The AI's read of the zone: the reason of a judge acting on it now, else of any judge that gave
 * one. Null when none did. */
export function aiRead(
  judges: readonly JevZoneJudge[],
  acting: readonly string[],
): { title: string; why: string } | null {
  const said = judges.filter((judge) => judge.why);
  const pick = said.find((judge) => acting.includes(judge.judge)) ?? said[0];
  return pick ? { title: pick.title, why: pick.why } : null;
}
