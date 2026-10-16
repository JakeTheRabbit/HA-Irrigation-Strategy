import { useState } from "react";
import { Check, Droplets } from "lucide-react";
import { number } from "@/components/dashboard";
import { Input } from "@/components/ui/input";
import { readRunoff, runoffMode, RUNOFF_MODES } from "@/lib/runoff";
import type { Controller } from "@/lib/types";
import { errorText } from "@/lib/utils";

const CALIBRATION: [string, string, string][] = [
  ["sump_litres_per_run", "Litres per sump run", "From a bucket test; 0 = unknown"],
  ["sump_pump_flow_lpm", "Sump pump flow (L/min)", "Used with the run time when the litres per run are 0"],
  ["runoff_attribution_min", "Runoff reaches the sump within (min)", "The longest drain delay tried"],
  ["hvac_run_power_w", "AC / dehumidifier run power (W)", "For units mapped by their power sensor"],
];

/** Equipment › Setup: the runoff estimator from the sump's water balance. Room-wide and per grow-day; it never
 * waters, holds or moves a setting. */
export function RunoffPanel({ controller }: { controller: Controller }) {
  const { states, room } = controller;
  const prefix = room.room.prefix;
  const mode = runoffMode(states, prefix);
  const estimate = readRunoff(states, prefix);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (mode === null) return null;
  const live = ["live", "demo"].includes(controller.connection);
  async function write(entityId: string, value: string | number) {
    setBusy(true);
    setError("");
    try {
      const result = await controller.write([{ entityId, value }]);
      if (result.failed.length) setError(result.failed.map((f) => f.reason).join(" "));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  const select = `select.crop_steering_${prefix}runoff_estimator`;
  return (
    <section className="panel workspace-card" data-runoff>
      <div className="workspace-section-heading">
        <div>
          <h2>
            <Droplets size={16} aria-hidden="true" /> Runoff from the sump
          </h2>
          <p className="muted">
            A room-wide estimate from the sump pump&rsquo;s runs, the AC and dehumidifier run time and the water fed.
            In a sealed room the sump takes the water fed less the change in the substrate each day; that closure
            calibrates and checks it. Needs the sump power sensor (the app&rsquo;s sump_power_sensor) and each AC
            and dehumidifier mapped above. A hint with an error band, never a measured catch.
          </p>
        </div>
      </div>
      <div className="theme-options" role="group" aria-label="Runoff estimator">
        {RUNOFF_MODES.map(([value, label]) => (
          <button
            key={value}
            className={mode === value ? "chosen" : ""}
            aria-pressed={mode === value}
            disabled={busy || !live}
            onClick={() => void write(select, value)}
          >
            <span>{label}</span>
            {mode === value && <Check size={16} />}
          </button>
        ))}
      </div>
      <p className="small muted">
        Shadow publishes the estimate. With alerts adds CS-314 when a grow-day&rsquo;s balance does not close (a leak,
        a missed sump run, a stuck float). Also to the AI gives the AI assistant the estimate as a room-wide hint.
        Nothing ever waters from it.
      </p>
      {mode !== "off" && (
        <div className="workspace-form-grid">
          {CALIBRATION.map(([key, label, hint]) => {
            const id = `number.crop_steering_${prefix}${key}`;
            return (
              <label key={key} className="grid gap-1">
                <span>{label}</span>
                <Input
                  type="number"
                  step="0.1"
                  defaultValue={states[id]?.state ?? ""}
                  disabled={!states[id] || busy || !live}
                  onBlur={(e) => {
                    const v = Number(e.target.value);
                    if (e.target.value !== "" && Number.isFinite(v) && String(v) !== states[id]?.state)
                      void write(id, v);
                  }}
                />
                <span className="small muted">{hint}</span>
              </label>
            );
          })}
        </div>
      )}
      {mode !== "off" && estimate && (
        <div className="grid gap-2" data-runoff-estimate>
          {estimate.pct !== null ? (
            <p>
              <strong>
                Runoff about {number(estimate.pct, 0)}%
                {estimate.band !== null && ` ± ${number(estimate.band, 0)}`}
              </strong>{" "}
              of the water fed ({estimate.scope}). Fit R² {estimate.r2 === null ? "—" : number(estimate.r2, 2)}, drain
              delay {estimate.delayMin ?? "—"} min, {number(estimate.litresPerRun ?? 0, 1)} L a run (
              {estimate.litresSource}).
            </p>
          ) : (
            <p>
              <strong>{estimate.status.replace(/_/g, " ")}</strong>: {estimate.why}
            </p>
          )}
          {estimate.sumpTodayL !== null && (
            <p className="small">
              Today: {number(estimate.sumpTodayL, 1)} L to the sump, about {number(estimate.runoffTodayL ?? 0, 1)} L
              runoff and {number(estimate.transpirationTodayL ?? 0, 1)} L condensate (the plants&rsquo; transpiration).
            </p>
          )}
          {estimate.perUnit.length > 0 && (
            <p className="small muted">
              {estimate.perUnit.map(([unit, lph]) => `${unit}: ${number(lph, 2)} L/h while running`).join(" · ")}
            </p>
          )}
          {estimate.days.length > 0 && (
            <ul className="small muted">
              {estimate.days.map((d) => (
                <li key={d.date}>
                  {d.date}: {d.runs} runs, {d.fedL === null ? "—" : number(d.fedL, 1)} L fed
                  {d.closureErrorPct !== null && `, balance off by ${number(d.closureErrorPct, 0)}%`}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {error && (
        <p className="small error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
