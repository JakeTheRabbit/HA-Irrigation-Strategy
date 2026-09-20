import type { EntityState } from "./types";

const STATES = ["off", "learning", "tracking", "frozen"] as const;
// "short": the ramp ended at its maximum shots while still rising, target not reached.
const OUTCOMES = ["pending", "reached", "plateau", "suspect", "short"] as const;
const JEV = ["disabled", "ok", "unavailable"] as const;
export type AutoSetpointState = (typeof STATES)[number] | "unavailable";
/** Per-zone setpoint supervisor status: sensor.crop_steering_<prefix>zone_<N>_auto_setpoints. */
export interface AutoSetpointStatus {
  entityId: string;
  state: AutoSetpointState;
  learnedPeak: number | null;
  gain: number | null;
  dayRate: number | null;
  nightRate: number | null;
  p1Outcome: (typeof OUTCOMES)[number] | null;
  lastChange: string | null;
  jev: (typeof JEV)[number] | null;
  /** The judge's latest hourly P2 answer, and what it has changed this grow-day, in its own words. */
  jevLast: string | null;
  jevChangedToday: string | null;
  /** number.* entities the supervisor rewrites; manual edits to them do not last. */
  managed: string[];
  updated: string | null;
  /** Days the learned peak is held before the supervisor probes one point higher; 0 = probing. */
  holdDays: number | null;
  /** Why the supervisor is frozen, e.g. an armed grow plan owns the targets. */
  frozenReason: string | null;
}
const finite = (value: unknown): number | null => {
  const parsed =
    typeof value === "number" ? value : typeof value === "string" && value.trim() ? +value : NaN;
  return Number.isFinite(parsed) ? parsed : null;
};
const oneOf = <T extends string>(options: readonly T[], value: unknown): T | null =>
  options.find((option) => option === value) ?? null;
const text = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value : null;

/** The backend is built in parallel, so every attribute is optional and untrusted. */
export function parseAutoSetpoints(entity: EntityState | undefined): AutoSetpointStatus | null {
  if (!entity) return null;
  const attributes = entity.attributes;
  return {
    entityId: entity.entity_id,
    state: oneOf(STATES, entity.state) ?? "unavailable",
    learnedPeak: finite(attributes.learned_peak),
    gain: finite(attributes.gain),
    dayRate: finite(attributes.day_rate),
    nightRate: finite(attributes.night_rate),
    p1Outcome: oneOf(OUTCOMES, attributes.p1_outcome),
    lastChange: text(attributes.last_change),
    jev: oneOf(JEV, attributes.jev),
    jevLast: text(attributes.jev_last),
    jevChangedToday: text(attributes.jev_changed_today),
    managed: Array.isArray(attributes.managed)
      ? attributes.managed.filter(
          (id): id is string => typeof id === "string" && /^number\.[a-z0-9_]+$/.test(id),
        )
      : [],
    updated:
      typeof attributes.updated === "string" && Number.isFinite(Date.parse(attributes.updated))
        ? attributes.updated
        : null,
    holdDays: ((days) => (days !== null && Number.isInteger(days) && days >= 0 ? days : null))(
      finite(attributes.hold_days),
    ),
    frozenReason: text(attributes.frozen_reason),
  };
}
export const autoStateLabel = (state: AutoSetpointState) => state[0].toUpperCase() + state.slice(1);
/** Hold time beside a known learned peak: "held 3 days", or "probing higher" at 0. */
export const autoHoldText = (status: AutoSetpointStatus): string | null =>
  status.learnedPeak === null || status.holdDays === null
    ? null
    : status.holdDays === 0
      ? // Only a tracking supervisor probes; a frozen or learning one at 0 is simply not holding.
        status.state === "tracking"
        ? "probing higher"
        : null
      : `held ${status.holdDays} ${status.holdDays === 1 ? "day" : "days"}`;
/** A reason left over from an earlier freeze is not shown once the supervisor runs again. */
export const autoFrozenReason = (status: AutoSetpointStatus): string | null =>
  status.state === "frozen" ? status.frozenReason : null;
export function autoStatusText(status: AutoSetpointStatus): string {
  const hold = autoHoldText(status),
    reason = autoFrozenReason(status);
  return [
    autoStateLabel(status.state) + (reason ? `: ${reason}` : ""),
    status.learnedPeak === null
      ? "learned peak not yet known"
      : `learned peak ${status.learnedPeak.toFixed(1)}%${hold ? `, ${hold}` : ""}`,
    status.lastChange ? `last change: ${status.lastChange}` : "no changes yet",
    `Jev: ${status.jev ?? "not reported"}`,
    ...(status.jevChangedToday ? [`Jev changed today: ${status.jevChangedToday}`] : []),
    ...(status.jevLast ? [`Jev last said: ${status.jevLast}`] : []),
  ].join(" · ");
}
/** A setpoint is "Auto" only while a supervisor that owns it is running. */
export function managedBy(
  statuses: readonly (AutoSetpointStatus | null)[],
  entityId: string,
): boolean {
  return statuses.some(
    (status) =>
      !!status &&
      ["learning", "tracking", "frozen"].includes(status.state) &&
      status.managed.includes(entityId),
  );
}
