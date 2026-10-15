import { jevCost, JEV_TITLES, type JevRoom } from "@/lib/jev";
import "./jev-status.css";

/** Today's calls, tokens, errors and what they cost. */
export function jevUsage(jev: JevRoom | null, short = false): string {
  if (!jev) return short ? "" : "The controller does not report Jev’s usage.";
  const calls =
    jev.calls === null
      ? null
      : `${jev.calls.toLocaleString()} call${jev.calls === 1 ? "" : "s"} today`;
  const cost = jevCost(jev.tokens);
  if (short) return [calls, cost].filter(Boolean).join(" · ");
  return [
    calls,
    jev.tokens === null ? null : `${jev.tokens.toLocaleString()} input tokens`,
    cost,
    jev.errors === null ? null : `${jev.errors} error${jev.errors === 1 ? "" : "s"}`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Jev not answering, or a judge failing: said once. With `lastError`, also the day's last error
 * when nothing is wrong now. */
export function JevTrouble({
  jev,
  lastError = true,
}: {
  jev: JevRoom | null;
  lastError?: boolean;
}) {
  if (!jev) return null;
  const failing = Object.keys(jev.judgeErrors);
  const down = jev.state === "error";
  if (!down && !failing.length && !(lastError && jev.errors && jev.lastError)) return null;
  const said = (text: string) => (/[.!?)]$/.test(text) ? text : `${text}.`);
  const why = jev.lastError ? `: ${said(jev.lastError)}` : ".";
  const judges = failing
    .map((judge) => `${JEV_TITLES[judge] ?? judge} (${jev.judgeErrors[judge]})`)
    .join("; ");
  return (
    <p className="jev-trouble" role="note">
      {down
        ? `Jev is not answering${why} The controller carries on without it.`
        : failing.length
          ? `A judge failed: ${said(judges)} The others carry on.`
          : `Last error today${why}`}
    </p>
  );
}
