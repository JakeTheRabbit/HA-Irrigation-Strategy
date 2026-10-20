/** The setup wizard: a new room's steps, each with the live check the setup API reports for it.
 *
 * Switch on waits for the safety checks only (valves mapped and reading OFF, probes reporting in a
 * usable unit, a test shot that was seen), and names the first one that has not passed. Sizing still on
 * the generic defaults, a controller not reporting and odd lights hours are warnings: they never hold
 * Switch on. The wizard only ever holds its own button; the room's Watering switch is never locked. */
import type { Commissioning, CommissioningCheck, SetupRoom } from "./operator-types";

export const WIZARD_STEPS = [
  { step: 0, check: "controller", label: "Before you start" },
  { step: 1, check: "room", label: "Room" },
  { step: 2, check: "valves", label: "Valves & pump" },
  { step: 3, check: "probes", label: "Probes" },
  { step: 4, check: "sizing", label: "Sizing" },
  { step: 6, check: "test_shot", label: "Test shot" },
  { step: 7, check: null, label: "Switch on" },
] as const;

export type StepMark = "done" | "attention" | "todo";

/** ✓ passed, ! a warning to look at (never blocking), ○ still to do. */
export function stepMark(check: CommissioningCheck | undefined): StepMark {
  if (!check) return "todo";
  return check.ok ? "done" : check.blocking ? "todo" : "attention";
}

export const MARK_SYMBOL: Record<StepMark, string> = { done: "✓", attention: "!", todo: "○" };

/** Whether Switch on may be pressed, and if not, the step and problem holding it. Worked out from the
 * checks themselves, not from the API's summary, so a check the API marks blocking always holds it. */
export function switchOn(status: Commissioning): { enabled: boolean; reason: string | null } {
  const failing = status.checks.find((c) => c.blocking && !c.ok);
  if (!failing) return { enabled: true, reason: null };
  const label = WIZARD_STEPS.find((s) => s.check === failing.id)?.label || failing.id;
  return { enabled: false, reason: label + ": " + (failing.problems[0] || "not checked yet") };
}

/** Warnings that do not hold Switch on, in step order. */
export function warnings(status: Commissioning): string[] {
  return status.checks.filter((c) => !c.blocking && !c.ok).flatMap((c) => c.problems);
}

/** The wizard is for a room still being set up: a room from before, or one the wizard finished,
 * never sees it, and nor does a room on an integration without the readiness API. */
export function needsWizard(room: SetupRoom | null | undefined): boolean {
  return !!room?.active && !!room.commissioning && !room.commissioning.commissioned;
}
