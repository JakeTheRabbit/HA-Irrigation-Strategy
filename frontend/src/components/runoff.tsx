import { Droplets } from "lucide-react";
import { number } from "@/components/dashboard";
import { readRunoff, runoffMode } from "@/lib/runoff";
import type { Controller } from "@/lib/types";

/** Equipment › Setup: the runoff estimator from the sump's water balance. Room-wide and per grow-day; it never
 * waters, holds or moves a setting. */
export function RunoffPanel({ controller }: { controller: Controller }) {
  const { states, room } = controller;
  const prefix = room.room.prefix;
  const mode = runoffMode(states, prefix);
  const estimate = readRunoff(states, prefix);
  if (mode === null) return null;
  return (
    <section className="panel workspace-card" data-runoff>
      <div className="workspace-section-heading">
        <div>
          <h2>
            <Droplets size={16} aria-hidden="true" /> Runoff from the sump
          </h2>
          <p className="muted">
            A room-wide estimate from the sump pump&rsquo;s runs, the AC and dehumidifier run time
            and the water fed. In a sealed room the sump takes the water fed less the change in the
            substrate each day; that closure calibrates and checks it. Needs the sump power sensor
            (the app&rsquo;s sump_power_sensor) and each AC and dehumidifier mapped above. A hint
            with an error band, never a measured catch.
          </p>
        </div>
      </div>
      <p className="small muted">
        Estimator mode: {mode}. Edit calibration in the Runoff settings below.
      </p>
      {mode !== "off" && estimate && (
        <div className="grid gap-2" data-runoff-estimate>
          {estimate.pct !== null ? (
            <p>
              <strong>
                Runoff about {number(estimate.pct, 0)}%
                {estimate.band !== null && ` ± ${number(estimate.band, 0)}`}
              </strong>{" "}
              of the water fed ({estimate.scope}). Fit R²{" "}
              {estimate.r2 === null ? "—" : number(estimate.r2, 2)}, drain delay{" "}
              {estimate.delayMin ?? "—"} min, {number(estimate.litresPerRun ?? 0, 1)} L a run (
              {estimate.litresSource}).
            </p>
          ) : (
            <p>
              <strong>{estimate.status.replace(/_/g, " ")}</strong>: {estimate.why}
            </p>
          )}
          {estimate.sumpTodayL !== null && (
            <p className="small">
              Today: {number(estimate.sumpTodayL, 1)} L to the sump, about{" "}
              {number(estimate.runoffTodayL ?? 0, 1)} L runoff and{" "}
              {number(estimate.transpirationTodayL ?? 0, 1)} L condensate (the plants&rsquo;
              transpiration).
            </p>
          )}
          {estimate.perUnit.length > 0 && (
            <p className="small muted">
              {estimate.perUnit
                .map(([unit, lph]) => `${unit}: ${number(lph, 2)} L/h while running`)
                .join(" · ")}
            </p>
          )}
          {estimate.days.length > 0 && (
            <ul className="small muted">
              {estimate.days.map((d) => (
                <li key={d.date}>
                  {d.date}: {d.runs} runs, {d.fedL === null ? "—" : number(d.fedL, 1)} L fed
                  {d.closureErrorPct !== null &&
                    `, balance off by ${number(d.closureErrorPct, 0)}%`}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
