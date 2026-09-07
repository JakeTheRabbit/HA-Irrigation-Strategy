import { useEffect, useId, useRef, useState, type PointerEvent } from "react";
import { SlidersHorizontal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  buildPlanningCurve,
  planningClock,
  changePlanningValue,
  type PlanningBounds,
  type PlanningPhaseId,
} from "@/lib/planning-curve";

export interface PlanningCurveProps {
  parameters: Record<string, number>;
  lightsOn: number;
  lightsOff: number;
  onChange?: (key: string, value: number) => void;
  bounds?: PlanningBounds;
  baseline?: { parameters: Record<string, number>; lightsOn: number; lightsOff: number };
  showEditors?: boolean;
  selectedPhase?: PlanningPhaseId;
  description?: string;
}
const editors = [
  { key: "p1_target_vwc", label: "P1 VWC target", unit: "% VWC", max: 100, step: 1 },
  { key: "p2_vwc_threshold", label: "P2 VWC threshold", unit: "% VWC", max: 100, step: 1 },
  { key: "dryback_target", label: "Dryback drop", unit: "% of peak drop", max: 100, step: 1 },
  { key: "ec_target_p0", label: "P0 EC target", unit: "mS/cm", max: 20, step: 0.1 },
  { key: "ec_target_p1", label: "P1 EC target", unit: "mS/cm", max: 20, step: 0.1 },
  { key: "ec_target_p2", label: "P2 EC target", unit: "mS/cm", max: 20, step: 0.1 },
  {
    key: "p1_initial_shot_size",
    label: "P1 initial shot",
    unit: "% substrate volume",
    max: 100,
    step: 1,
  },
  { key: "p2_shot_size", label: "P2 nominal shot", unit: "% substrate volume", max: 100, step: 1 },
  {
    key: "p3_emergency_vwc_threshold",
    label: "P3 emergency floor",
    unit: "% VWC",
    max: 100,
    step: 1,
  },
  {
    key: "p3_emergency_shot_size",
    label: "P3 emergency shot",
    unit: "% substrate volume",
    max: 100,
    step: 1,
  },
];
export function PlanningCurve({
  parameters,
  lightsOn,
  lightsOff,
  onChange,
  bounds,
  baseline,
  showEditors = true,
  selectedPhase,
  description,
}: PlanningCurveProps) {
  const limits =
    bounds ??
    Object.fromEntries(
      editors.map((editor) => [editor.key, { min: 0, max: editor.max, step: editor.step }]),
    );
  const id = useId();
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const dragging = useRef<string | null>(null);
  useEffect(() => {
    if (!container.current) return;
    const observer = new ResizeObserver((entries) =>
      setWidth(Math.max(270, entries[0].contentRect.width)),
    );
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  const plan = buildPlanningCurve(parameters, lightsOn, lightsOff);
  const saved = baseline
    ? buildPlanningCurve(baseline.parameters, baseline.lightsOn, baseline.lightsOff)
    : null;
  const left = 43,
    right = 42,
    top = 38,
    height = 220,
    plotWidth = width - left - right;
  const x = (hour: number) => left + (Math.min(24, Math.max(0, hour)) / 24) * plotWidth;
  const y = (value: number) => top + height * (1 - Math.min(100, Math.max(0, value)) / 100);
  const ecMax = Math.max(
    6,
    Math.ceil(
      Math.max(
        0,
        ...plan.ec.map((point) => point.value),
        ...(saved?.ec.map((point) => point.value) ?? []),
      ) * 1.15,
    ),
  );
  const ey = (value: number) => top + height * (1 - Math.min(ecMax, Math.max(0, value)) / ecMax);
  const p1 = plan.phases[1],
    p2 = plan.phases[2],
    p3 = plan.phases[3];
  const handles = [
    { key: "p1_target_vwc", hour: p1.end, position: parameters.p1_target_vwc, axis: "vwc" },
    {
      key: "p2_vwc_threshold",
      hour: (p2.start + p2.end) / 2,
      position: parameters.p2_vwc_threshold,
      axis: "vwc",
    },
    {
      key: "dryback_target",
      hour: plan.phases[0].end,
      position: plan.morningDrybackVwc,
      axis: "dryback",
    },
    {
      key: "p3_emergency_vwc_threshold",
      hour: p3.start + (24 - p3.start) * 0.72,
      position: parameters.p3_emergency_vwc_threshold,
      axis: "vwc",
    },
    ...plan.phases.slice(0, 3).map((phase) => ({
      key: `ec_target_${phase.id.toLowerCase()}`,
      hour: (phase.start + phase.end) / 2,
      position: parameters[`ec_target_${phase.id.toLowerCase()}`],
      axis: "ec",
    })),
  ].filter(
    (handle) =>
      handle.position !== null &&
      Number.isFinite(handle.position) &&
      Number.isFinite(parameters[handle.key]),
  );
  const commit = (key: string, value: number) => changePlanningValue(key, value, limits, onChange);
  function drag(event: PointerEvent<SVGCircleElement>, handle: (typeof handles)[number]) {
    if (!onChange || dragging.current !== handle.key) return;
    const svg = event.currentTarget.ownerSVGElement;
    const matrix = svg?.getScreenCTM();
    if (!svg || !matrix) return;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const local = point.matrixTransform(matrix.inverse());
    const fraction = 1 - (local.y - top) / height;
    const next =
      handle.axis === "ec"
        ? fraction * ecMax
        : handle.axis === "dryback" && plan.drybackReference
          ? (1 - (fraction * 100) / plan.drybackReference) * 100
          : fraction * 100;
    commit(handle.key, next);
  }
  const targetPath = plan.vwc
    .map((point, index) => `${index ? "L" : "M"}${x(point.hour)},${y(point.value)}`)
    .join(" ");
  return (
    <section className="panel planning-curve" aria-labelledby={`${id}-title`}>
      <div className="panel-heading">
        <div>
          <h2 id={`${id}-title`}>Daily VWC & EC plan</h2>
          <p>
            {description ??
              (onChange
                ? "Drag a target or use the precise controls. Changes follow the selected day and zone."
                : "Setpoints for the selected day and zone.")}
          </p>
        </div>
        <Badge variant="outline">Planning illustration</Badge>
      </div>
      <div className="planning-chart-key">
        <span>
          <i className="vwc-key" />
          VWC · left (%)
        </span>
        <span>
          <i className="ec-key" />
          EC target · right (mS/cm)
        </span>
      </div>
      {baseline && (
        <div className="planning-comparison-key">
          <span>
            <i />
            Saved on controller
          </span>
          <span>
            <i />
            Local draft
          </span>
          <small>Aligned to lights-on; times follow the draft schedule.</small>
        </div>
      )}
      <div ref={container} className="planning-svg-wrap">
        <svg
          viewBox={`0 0 ${width} 322`}
          width="100%"
          height="322"
          role="group"
          aria-label="Twenty-four-hour phase and setpoint planning curve"
        >
          <title>
            Setpoint illustration from lights-on to the next lights-on. Blue is VWC; dashed pink is
            EC. This is not recorded or forecast sensor data.
          </title>
          {plan.phases.map((phase) => (
            <g key={phase.id}>
              <rect
                x={x(phase.start)}
                y={top}
                width={Math.max(0, x(phase.end) - x(phase.start))}
                height={height}
                fill={phase.color}
                fillOpacity={selectedPhase === phase.id ? 0.16 : 0.06}
              />
              {x(phase.end) - x(phase.start) > 20 && (
                <text
                  x={(x(phase.start) + x(phase.end)) / 2}
                  y={20}
                  textAnchor="middle"
                  fill="var(--muted-foreground)"
                  fontSize="11"
                >
                  {phase.id}
                </text>
              )}
            </g>
          ))}
          {[0, 25, 50, 75, 100].map((tick) => (
            <g key={tick}>
              <line
                x1={left}
                x2={width - right}
                y1={y(tick)}
                y2={y(tick)}
                stroke="var(--border)"
                strokeDasharray="3 5"
              />
              <text
                x={left - 7}
                y={y(tick) + 4}
                textAnchor="end"
                fill="var(--muted-foreground)"
                fontSize="11"
              >
                {tick}%
              </text>
              <text
                x={width - right + 7}
                y={y(tick) + 4}
                fill="var(--muted-foreground)"
                fontSize="11"
              >
                {((ecMax * tick) / 100).toFixed(1)}
              </text>
            </g>
          ))}
          {[0, 6, 12, 18, 24].map((hour) => (
            <text
              key={hour}
              x={x(hour)}
              y={281}
              textAnchor="middle"
              fill="var(--muted-foreground)"
              fontSize="11"
            >
              {planningClock(lightsOn, hour)}
            </text>
          ))}
          {saved && saved.photoperiod > 0 && (
            <g opacity="0.45" aria-label="Saved controller setpoints">
              {saved.vwc.length > 0 && (
                <path
                  data-planning-line="baseline-vwc"
                  d={saved.vwc
                    .map((point, index) => `${index ? "L" : "M"}${x(point.hour)},${y(point.value)}`)
                    .join(" ")}
                  fill="none"
                  stroke="var(--muted-foreground)"
                  strokeWidth="2"
                  strokeDasharray="4 5"
                />
              )}
              {saved.phases.map((phase) => {
                const points = saved.ec.filter((point) => point.phase === phase.id);
                return points.length > 0 ? (
                  <path
                    key={phase.id}
                    data-planning-line="baseline-ec"
                    d={points
                      .map(
                        (point, index) => `${index ? "L" : "M"}${x(point.hour)},${ey(point.value)}`,
                      )
                      .join(" ")}
                    fill="none"
                    stroke="#df78b5"
                    strokeWidth="1.5"
                    strokeDasharray="2 6"
                  />
                ) : null;
              })}
              {saved.emergencyFloor !== null && (
                <line
                  data-planning-line="baseline-p3-floor"
                  x1={x(saved.phases[3].start)}
                  x2={x(24)}
                  y1={y(saved.emergencyFloor)}
                  y2={y(saved.emergencyFloor)}
                  stroke="var(--muted-foreground)"
                  strokeDasharray="4 5"
                >
                  <title>Saved P3 floor: {saved.emergencyFloor}% VWC</title>
                </line>
              )}
            </g>
          )}
          {plan.photoperiod > 0 && (
            <>
              {plan.p2Envelope && (
                <rect
                  x={x(p2.start)}
                  y={y(plan.p2Envelope[1])}
                  width={Math.max(0, x(p2.end) - x(p2.start))}
                  height={y(plan.p2Envelope[0]) - y(plan.p2Envelope[1])}
                  fill="#03a9f4"
                  fillOpacity={0.15}
                >
                  <title>Nominal P2 shot envelope assuming full retention</title>
                </rect>
              )}
              {plan.emergencyFloor !== null && (
                <line
                  data-planning-line="p3-floor"
                  x1={x(p3.start)}
                  x2={x(24)}
                  y1={y(plan.emergencyFloor)}
                  y2={y(plan.emergencyFloor)}
                  stroke="var(--destructive)"
                  strokeDasharray="3 4"
                >
                  <title>P3 emergency floor: {plan.emergencyFloor}% VWC</title>
                </line>
              )}
              {Number.isFinite(parameters.p1_initial_shot_size) &&
                plan.morningDrybackVwc !== null && (
                  <line
                    x1={x(p1.start)}
                    x2={x(p1.start)}
                    y1={y(plan.morningDrybackVwc)}
                    y2={y(plan.morningDrybackVwc + parameters.p1_initial_shot_size)}
                    stroke="#03a9f4"
                    strokeWidth="5"
                    opacity="0.45"
                  >
                    <title>
                      Nominal initial P1 shot: {parameters.p1_initial_shot_size}% substrate volume
                    </title>
                  </line>
                )}
              {targetPath && (
                <path
                  data-planning-line="vwc"
                  d={targetPath}
                  fill="none"
                  stroke="#03a9f4"
                  strokeWidth="2.5"
                />
              )}
              {plan.phases.map((phase) => {
                const points = plan.ec.filter((point) => point.phase === phase.id);
                return points.length ? (
                  <path
                    data-planning-line="ec"
                    key={phase.id}
                    d={points
                      .map(
                        (point, index) => `${index ? "L" : "M"}${x(point.hour)},${ey(point.value)}`,
                      )
                      .join(" ")}
                    fill="none"
                    stroke="#df78b5"
                    strokeWidth="2"
                    strokeDasharray="6 4"
                  />
                ) : null;
              })}
              {handles.map((handle) => {
                const editor = editors.find((item) => item.key === handle.key)!;
                const position = handle.position as number;
                const limit = limits[handle.key];
                const editable = !!onChange && !!limit;
                return (
                  <circle
                    key={handle.key}
                    cx={x(handle.hour)}
                    cy={handle.axis === "ec" ? ey(position) : y(position)}
                    r={editable ? 6 : 4}
                    fill="var(--surface)"
                    stroke={handle.axis === "ec" ? "#df78b5" : "#03a9f4"}
                    strokeWidth="2.5"
                    className={editable ? "planning-handle" : ""}
                    role={editable ? "slider" : undefined}
                    tabIndex={editable ? 0 : undefined}
                    aria-label={editable ? editor.label : undefined}
                    aria-valuemin={editable ? limit.min : undefined}
                    aria-valuemax={editable ? limit.max : undefined}
                    aria-valuenow={editable ? parameters[handle.key] : undefined}
                    aria-valuetext={
                      editable ? `${parameters[handle.key]} ${editor.unit}` : undefined
                    }
                    aria-orientation={editable ? "vertical" : undefined}
                    onPointerDown={(event) => {
                      if (!editable) return;
                      dragging.current = handle.key;
                      event.currentTarget.setPointerCapture(event.pointerId);
                    }}
                    onPointerMove={(event) => drag(event, handle)}
                    onPointerUp={(event) => {
                      dragging.current = null;
                      if (event.currentTarget.hasPointerCapture(event.pointerId))
                        event.currentTarget.releasePointerCapture(event.pointerId);
                    }}
                    onPointerCancel={() => {
                      dragging.current = null;
                    }}
                    onKeyDown={(event) => {
                      const increase = ["ArrowUp", "ArrowRight"].includes(event.key);
                      const decrease = ["ArrowDown", "ArrowLeft"].includes(event.key);
                      if (
                        !editable ||
                        (!increase && !decrease && !["Home", "End"].includes(event.key))
                      )
                        return;
                      event.preventDefault();
                      commit(
                        handle.key,
                        event.key === "Home"
                          ? limit.min
                          : event.key === "End"
                            ? limit.max
                            : parameters[handle.key] + (increase ? limit.step : -limit.step),
                      );
                    }}
                  >
                    <title>
                      {editor.label}: {parameters[handle.key]} {editor.unit}
                    </title>
                  </circle>
                );
              })}
              {plan.p1Windows.length > 0 && (
                <g data-planning-cadence="p1">
                  <line
                    x1={x(p1.start)}
                    x2={x(p1.end)}
                    y1={304}
                    y2={304}
                    stroke="#03a9f4"
                    strokeOpacity={0.4}
                  />
                  {plan.p1Windows.map((hour, index) => (
                    <line
                      key={index}
                      x1={x(hour)}
                      x2={x(hour)}
                      y1={297}
                      y2={311}
                      stroke="#03a9f4"
                      strokeWidth={2}
                    >
                      <title>
                        Eligible P1 window {index + 1}: {planningClock(lightsOn, hour)} in this
                        illustration
                      </title>
                    </line>
                  ))}
                </g>
              )}
              {x(p2.end) - x(p2.start) > 110 && (
                <text
                  x={(x(p2.start) + x(p2.end)) / 2}
                  y={307}
                  textAnchor="middle"
                  fill="var(--muted-foreground)"
                  fontSize="11"
                >
                  P2 · sensor-triggered
                </text>
              )}
              {plan.photoperiod > 0 && (
                <line
                  x1={x(plan.photoperiod)}
                  x2={x(plan.photoperiod)}
                  y1={top}
                  y2={top + height}
                  stroke="var(--muted-foreground)"
                  strokeDasharray="2 5"
                />
              )}
            </>
          )}
        </svg>
      </div>
      {plan.p1Windows.length > 0 && (
        <p className="muted small" style={{ padding: "0 16px 12px", margin: 0 }}>
          P1 ticks: up to {parameters.p1_maximum_shots} eligible shots, spaced{" "}
          {parameters.p1_time_between_shots} minutes apart. Sensor feedback can end ramp-up sooner.
          P2 watering is triggered by VWC and EC.
        </p>
      )}
      <p className="muted small" style={{ padding: "0 16px 12px", margin: 0 }}>
        P3 shows the emergency floor only. No overnight moisture trend or routine watering is
        predicted.
        {Number.isFinite(parameters.p3_emergency_shot_size)
          ? ` Its ${parameters.p3_emergency_shot_size}% emergency shot is conditional on controller safety checks.`
          : ""}
      </p>
      <div className="planning-phase-legend">
        {plan.phases.map((phase) => (
          <span key={phase.id}>
            <i style={{ background: phase.color }} />
            <strong>{phase.id}</strong> {phase.label}
            <small>
              {planningClock(lightsOn, phase.start)}–{planningClock(lightsOn, phase.end)}
            </small>
          </span>
        ))}
      </div>
      {plan.warnings.length > 0 && (
        <div className="planning-warnings" role="status">
          {plan.warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      )}
      {plan.missing.length > 0 && (
        <p className="planning-missing">
          Not supplied: {plan.missing.join(", ")}. Missing targets are not plotted.
        </p>
      )}
      {onChange && showEditors && (
        <details className="planning-editors">
          <summary>
            <SlidersHorizontal size={16} />
            Precise target controls
          </summary>
          <div className="planning-field-grid">
            {editors
              .filter((editor) => Number.isFinite(parameters[editor.key]) && !!limits[editor.key])
              .map((editor) => (
                <div key={editor.key}>
                  <Label htmlFor={`${id}-${editor.key}`}>{editor.label}</Label>
                  <div>
                    <Input
                      id={`${id}-${editor.key}`}
                      type="number"
                      min={limits[editor.key].min}
                      max={limits[editor.key].max}
                      step={limits[editor.key].step}
                      value={parameters[editor.key]}
                      onChange={(event) => {
                        if (event.target.value.trim())
                          commit(editor.key, Number(event.target.value));
                      }}
                    />
                    <span>{editor.unit}</span>
                  </div>
                </div>
              ))}
          </div>
          <p>
            Edits update this local plan. Controller settings still require review before
            application.
          </p>
        </details>
      )}
      <details className="planning-assumptions">
        <summary>How to read this plan</summary>
        <ul>
          {plan.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}
