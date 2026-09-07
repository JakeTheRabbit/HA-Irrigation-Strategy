import { useEffect, useId, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { number } from "@/components/dashboard";
import type { Controller, Zone } from "@/lib/types";
import {
  dailyWater,
  coreWaterValue,
  estimatePhaseShot,
  estimateRuntime,
  flowInputs,
  p1WaterBudget,
  positiveCount,
  totalSubstrateL,
  waterParameters,
  type Delivery,
} from "@/lib/water-delivery";
import "./water-delivery.css";

export interface WaterDeliveryProps {
  controller: Controller;
  zoneId: number;
  parameters?: Record<string, number>;
  fieldOverrides?: Record<string, number>;
}
const quantity = (value: number | null, unit: string, digits = 1) =>
  value === null ? "Unavailable" : `${number(value, digits)} ${unit}`;

export function DailyWaterSummary({
  controller,
  zones = controller.room.zones,
}: {
  controller: Controller;
  zones?: Zone[];
}) {
  if (!zones.length) return null;
  return (
    <section className="panel wd-daily">
      <div className="panel-heading">
        <div>
          <h2>Water delivered this grow-day</h2>
          <p>Controller-recorded estimates, from each room’s lights-on boundary.</p>
        </div>
      </div>
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Daily water by zone and per plant"
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>Zone</th>
              <th>Configured plants</th>
              <th>Zone total · all plants</th>
              <th>Average per plant today</th>
            </tr>
          </thead>
          <tbody>
            {zones.map((zone) => {
              const reading = dailyWater(zone, waterParameters(controller, zone.id).plant_count);
              return (
                <tr key={zone.id}>
                  <td data-label="Zone">{zone.name}</td>
                  <td data-label="Configured plants">{number(reading.plants, 0)}</td>
                  <td data-label="Zone total · all plants">{quantity(reading.zoneL, "L", 2)}</td>
                  <td data-label="Average per plant today">
                    {quantity(reading.mlPerPlant, "mL", 1)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="wd-note">
        Per-plant average = recorded zone litres ÷ current plant count. It assumes uniform
        distribution; individual dripper delivery is not measured. A changed plant count can change
        this average.
      </p>
    </section>
  );
}
function CoreLimitNote({
  limit,
  unit,
}: {
  limit: ReturnType<typeof coreWaterValue>;
  unit: string;
}) {
  if (!limit.changed) return null;
  return (
    <small className="wd-core-limit">
      Configured {quantity(limit.configured, unit, 2)} → controller {quantity(limit.value, unit, 2)}{" "}
      (allowed {limit.min}–{limit.max}).
    </small>
  );
}
function DeliveryValue({ delivery }: { delivery: Delivery | null }) {
  return (
    <>
      <strong>{quantity(delivery?.mlPerPlant ?? null, "mL / plant", 1)}</strong>
      <span>{quantity(delivery?.zoneL ?? null, "L / zone", 2)}</span>
    </>
  );
}

export function WaterDelivery({
  controller,
  zoneId,
  parameters,
  fieldOverrides,
}: WaterDeliveryProps) {
  const id = useId();
  const [runtime, setRuntime] = useState("120");
  useEffect(() => setRuntime("120"), [controller.roomId, zoneId]);
  const config = waterParameters(controller, zoneId, parameters, fieldOverrides);
  const live = waterParameters(controller, zoneId);
  const zone = controller.room.zones.find((item) => item.id === zoneId);
  if (!zone) return null;
  const daily = dailyWater(zone, live.plant_count);
  const totalSubstrate = totalSubstrateL(config.substrate_volume, config.plant_count);
  const seconds = runtime.trim() ? Number(runtime) : null;
  const result = estimateRuntime(flowInputs(config), seconds);
  const budget = p1WaterBudget(config);
  const dailyLimit = coreWaterValue("max_daily_volume", config.max_daily_volume);
  const capValid = config.max_shot_duration !== null && config.max_shot_duration >= 5;
  const invalid = [
    !(config.substrate_volume !== null && config.substrate_volume > 0) &&
      "substrate litres per plant",
    !positiveCount(config.plant_count) && "whole plant count",
    !positiveCount(config.drippers_per_plant) && "whole drippers per plant",
    !(config.dripper_flow_rate !== null && config.dripper_flow_rate > 0) && "positive dripper flow",
    !capValid && "maximum shot duration of at least 5 seconds",
  ].filter(Boolean);
  return (
    <section className="wd-water" aria-label={`${zone.name} water delivery`}>
      <div className="wd-title">
        <div>
          <h3>Water delivery · {zone.name}</h3>
          <p>
            Local calculation from configured flow. Editing this runtime does not change irrigation.
          </p>
        </div>
      </div>
      <dl className="wd-capacity">
        <div>
          <dt>Total substrate capacity</dt>
          <dd>
            {quantity(totalSubstrate, "L of growing medium", 2)}
            <small>
              {quantity(config.substrate_volume, "L per plant", 2)} ×{" "}
              {number(positiveCount(config.plant_count) ? config.plant_count : null, 0)} plants.
              Separate from water delivered.
            </small>
          </dd>
        </div>
        <div>
          <dt>Recorded water today · all plants</dt>
          <dd>
            {quantity(daily.zoneL, "L / zone", 2)}
            <small>
              {quantity(daily.mlPerPlant, "mL / plant average", 1)} using the current live plant
              count. Controller estimate; uniform distribution assumed.
            </small>
          </dd>
        </div>
      </dl>
      <div className="wd-flow-line">
        {number(config.drippers_per_plant, 0)} drippers per plant at{" "}
        {quantity(config.dripper_flow_rate, "L/h each", 2)}. Maximum shot duration:{" "}
        {quantity(config.max_shot_duration, "seconds", 0)}.
      </div>
      {invalid.length > 0 && (
        <p className="wd-warning">
          Unavailable or invalid: {invalid.join(", ")}. Affected estimates remain unavailable;
          supply readable settings or correct the draft.
        </p>
      )}
      <div className="wd-runtime">
        <div className="wd-runtime-input">
          <Label htmlFor={`${id}-seconds`}>Try a valve-open runtime · seconds</Label>
          <Input
            id={`${id}-seconds`}
            type="number"
            min="0"
            step="1"
            value={runtime}
            onChange={(event) => setRuntime(event.target.value)}
            aria-describedby={`${id}-basis`}
          />
          <p id={`${id}-basis`}>
            mL per plant = seconds × drippers per plant × L/h per dripper ÷ 3.6.
          </p>
        </div>
        <div className="wd-comparison" aria-live="polite">
          <div>
            <h4>Requested · {quantity(result.requested?.seconds ?? null, "s", 2)}</h4>
            <DeliveryValue delivery={result.requested} />
          </div>
          <div className="wd-effective">
            <h4>Effective · {quantity(result.effective?.seconds ?? null, "s", 0)}</h4>
            <DeliveryValue delivery={result.effective} />
          </div>
        </div>
      </div>
      <p className="wd-note">
        {result.capped
          ? "The configured maximum duration reduces this shot. "
          : result.minimumApplied
            ? "The controller’s five-second minimum increases this shot. "
            : result.rounded
              ? "The controller rounds runtime down to whole seconds. "
              : ""}
        Effective values include whole-second timing, the five-second minimum and maximum-duration
        cap. Controller parameter limits, safety gates, interruptions, pressure differences and EC
        corrections can change delivered water.
      </p>
      <details className="wd-details">
        <summary>Phase shot estimates and limits</summary>
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Phase shot runtimes and water volumes"
        >
          <table className="data-table wd-shots">
            <caption>Nominal phase shots from these settings</caption>
            <thead>
              <tr>
                <th>Phase shot</th>
                <th>Configured runtime</th>
                <th>Effective runtime</th>
                <th>Effective per plant</th>
                <th>Effective all plants</th>
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ["P1 first shot", "p1_initial_shot_size"],
                  ["P2 maintenance shot", "p2_shot_size"],
                  ["P3 emergency shot", "p3_emergency_shot_size"],
                ] as const
              ).map(([label, key]) => {
                const phase = estimatePhaseShot(config, key);
                const shot = phase.controlled;
                return (
                  <tr key={key}>
                    <td>
                      {label}
                      <small>
                        Configured {quantity(config[key], "% of substrate", 2)}; requested{" "}
                        {quantity(phase.configured.requested?.mlPerPlant ?? null, "mL / plant", 1)}
                      </small>
                    </td>
                    <td>
                      {quantity(phase.configured.requested?.seconds ?? null, "s", 1)}
                      <CoreLimitNote limit={phase.limit} unit="%" />
                    </td>
                    <td>
                      {quantity(shot.effective?.seconds ?? null, "s", 0)}
                      {phase.limit.changed && (
                        <small>
                          Before duration limit: {quantity(shot.requested?.seconds ?? null, "s", 1)}
                        </small>
                      )}
                      {shot.capped && <small>Duration capped</small>}
                    </td>
                    <td>{quantity(shot.effective?.mlPerPlant ?? null, "mL", 1)}</td>
                    <td>{quantity(shot.effective?.zoneL ?? null, "L", 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="wd-budget">
          <div>
            <h4>Conditional P1 ramp budget</h4>
            {budget ? (
              <>
                <p>
                  If all {budget.count} ramp shots occur, the controller starts at{" "}
                  {quantity(budget.initial.value, "%", 2)}, increases by{" "}
                  {quantity(budget.increment.value, "%", 2)} per shot and ends at{" "}
                  {quantity(budget.coreLastPercent, "%", 2)}:{" "}
                  <strong>{quantity(budget.effectiveMlPerPlant, "mL / plant", 1)}</strong> and{" "}
                  <strong>{quantity(budget.effectiveZoneL, "L / zone", 2)}</strong> after parameter
                  and runtime limits. For these {budget.count} shots, the configured sizes request{" "}
                  {quantity(budget.requestedZoneL, "L / zone", 2)} before limits.
                </p>
                <CoreLimitNote limit={budget.initial} unit="% initial size" />
                <CoreLimitNote limit={budget.increment} unit="% increment" />
                <CoreLimitNote limit={budget.shotsLimit} unit="shots" />
                <p className="wd-note">
                  Controller spacing: {quantity(budget.spacing.value, "minutes", 1)}. The
                  first-to-last shot span would be at least{" "}
                  {quantity(budget.minimumSpacingMinutes, "minutes", 1)}; P1 has a 120-minute phase
                  ceiling.
                </p>
                <CoreLimitNote limit={budget.spacing} unit="minutes" />
              </>
            ) : (
              <p>
                Supply valid P1 initial size, increment, maximum shots and hydraulic settings to
                calculate the ramp budget.
              </p>
            )}
            <p className="wd-note">
              This is a conditional shot series, not a daily forecast. Moisture feedback, the phase
              time limit and daily budget can end P1 sooner. P2 and P3 shot counts depend on live
              feedback and are not predicted.
            </p>
          </div>
          <div>
            <h4>Daily budget · all plants</h4>
            <strong>{quantity(dailyLimit.value, "L / zone", 2)}</strong>
            <CoreLimitNote limit={dailyLimit} unit="L / zone" />
            <p className="wd-note">
              Controller daily limit after parameter validation. Emergency rules can exceed this
              budget; it is not guaranteed daily delivery.
            </p>
          </div>
        </div>
      </details>
    </section>
  );
}
