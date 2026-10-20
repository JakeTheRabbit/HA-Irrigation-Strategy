import { SIZING_BOUNDS, displayNumber } from "./units";

/** Catch test: run one dripper into a measuring cup for a timed period. Arithmetic only;
 * nothing here operates a valve or writes a setting. */
export function calibrateDripper(collectedMl: number, minutes: number): number | null {
  if (
    !Number.isFinite(collectedMl) ||
    !Number.isFinite(minutes) ||
    collectedMl <= 0 ||
    minutes <= 0
  )
    return null;
  return ((collectedMl / 1000) * 60) / minutes;
}

export type CatchTestResult =
  | { flow: number; error: null }
  /** `field` is the entry the message is about. */
  | { flow: null; error: string; field: "seconds" | "ml" | "both" };
/** Dripper flow in L/h from millilitres caught over a run time in seconds, to the two decimals a
 * timed catch can resolve, and only when it is a flow the integration accepts for one dripper. */
export function catchTest(collectedMl: number, seconds: number): CatchTestResult {
  const fail = (field: "seconds" | "ml" | "both", error: string): CatchTestResult => ({
    flow: null,
    error,
    field,
  });
  const numbers = "Enter the run time in seconds and the water caught in mL as numbers.";
  if (!Number.isFinite(collectedMl) || !Number.isFinite(seconds))
    return fail(
      Number.isFinite(seconds) ? "ml" : Number.isFinite(collectedMl) ? "seconds" : "both",
      numbers,
    );
  if (seconds <= 0) return fail("seconds", "Run time must be more than 0 seconds.");
  if (collectedMl <= 0) return fail("ml", "Water caught must be more than 0 mL.");
  const raw = calibrateDripper(collectedMl, seconds / 60);
  // Only absurd magnitudes get here: a run time that underflows, or a flow that overflows.
  if (raw === null || !Number.isFinite(raw)) return fail("both", numbers);
  const flow = Number(raw.toFixed(2)),
    { min, max } = SIZING_BOUNDS.dripper_flow_rate;
  if (flow < min)
    return fail(
      "both",
      `That works out to ${displayNumber(raw)} L/h, below the ${min} L/h minimum for a dripper. Check the seconds and the mL.`,
    );
  if (flow > max)
    return fail(
      "both",
      `That works out to ${displayNumber(raw)} L/h, above the ${max} L/h maximum for a dripper. Enter what one dripper delivered, not the whole zone.`,
    );
  return { flow, error: null };
}
