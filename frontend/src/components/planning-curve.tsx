import { useEffect, useId, useRef, useState, type PointerEvent } from "react";
import { SlidersHorizontal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  buildPlanningCurve,
  dryRates,
  foldRecorded,
  p2Advice,
  projectDay,
  planningAxis,
  planningClock,
  changePlanningValue,
  type PlanningBounds,
  type PlanningModel,
  type PlanningPhaseId,
  type PlanningPoint,
  type PlanningProjection,
  type RecordedPoint,
  type RecordedReading,
} from "@/lib/planning-curve";
import { settingWords } from "@/lib/setting-words";

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
  /** Recorded probe readings for this zone, drawn under the targets on the same axes. */
  recorded?: { vwc: readonly RecordedReading[]; ec: readonly RecordedReading[]; now: number };
  /** Learned VWC points retained per 1% shot, when the zone's supervisor knows it. */
  retention?: number | null;
}
const trim = (value: number | null | undefined, digits = 1) =>
  typeof value === "number" && Number.isFinite(value) ? String(Number(value.toFixed(digits))) : "—";
const extremes = (points: readonly RecordedPoint[]) =>
  points.length
    ? {
        peak: points.reduce((a, b) => (b.value > a.value ? b : a)),
        trough: points.reduce((a, b) => (b.value < a.value ? b : a)),
      }
    : null;
const editors = [
  { key: "p1_target_vwc", unit: "% VWC", max: 100, step: 1 },
  { key: "p2_vwc_threshold", unit: "% VWC", max: 100, step: 1 },
  { key: "dryback_target", unit: "% of peak drop", max: 100, step: 1 },
  { key: "ec_target_p0", unit: "mS/cm", max: 20, step: 0.1 },
  { key: "ec_target_p1", unit: "mS/cm", max: 20, step: 0.1 },
  { key: "ec_target_p2", unit: "mS/cm", max: 20, step: 0.1 },
  { key: "p1_initial_shot_size", unit: "% substrate volume", max: 100, step: 1 },
  { key: "p2_shot_size", unit: "% substrate volume", max: 100, step: 1 },
  { key: "p3_emergency_vwc_threshold", unit: "% VWC", max: 100, step: 1 },
  { key: "p3_emergency_shot_size", unit: "% substrate volume", max: 100, step: 1 },
].map((editor) => ({ ...editor, label: settingWords(editor.key)?.label ?? editor.key }));
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
  recorded,
  retention,
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
  // The axis follows what is plotted; it must not move under the pointer mid-drag.
  const [heldAxis, setHeldAxis] = useState<{ min: number; max: number } | null>(null);
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
  const vwcRecorded = foldRecorded(recorded?.vwc ?? [], lightsOn, recorded?.now ?? NaN);
  const ecRecorded = foldRecorded(recorded?.ec ?? [], lightsOn, recorded?.now ?? NaN);
  const hasRecorded = vwcRecorded.today.length + vwcRecorded.previous.length > 0;
  // The day drawn the way the engine runs it, timed by this zone's own measured dry-down.
  const rates = dryRates([vwcRecorded.today, ...vwcRecorded.previous], plan.photoperiod);
  const projection = projectDay(plan, parameters, { rates, retention });
  const savedProjection =
    saved && baseline ? projectDay(saved, baseline.parameters, { rates, retention }) : null;
  const advice = projection ? p2Advice(plan, parameters, projection) : null;
  const drybackVwc = projection ? projection.drybackVwc : plan.morningDrybackVwc;
  const drybackPeak = projection ? projection.peak : plan.drybackReference;
  const previousDay = vwcRecorded.previous[0] ?? [];
  const plotted = (model: PlanningModel | null, projected: PlanningProjection | null) =>
    model
      ? [
          ...(projected?.points ?? model.vwc).map((point) => point.value),
          ...(model.p2Envelope ?? []),
          model.emergencyFloor ?? NaN,
        ]
      : [];
  const axis =
    heldAxis ??
    planningAxis([
      ...plotted(plan, projection),
      ...plotted(saved, savedProjection),
      drybackVwc ?? NaN,
      ...vwcRecorded.today.map((point) => point.value),
      ...previousDay.map((point) => point.value),
    ]);
  const span = axis.max - axis.min;
  const y = (value: number) =>
    top + height * (1 - (Math.min(axis.max, Math.max(axis.min, value)) - axis.min) / span);
  const ecMax = Math.max(
    6,
    Math.ceil(
      Math.max(
        0,
        ...plan.ec.map((point) => point.value),
        ...(saved?.ec.map((point) => point.value) ?? []),
        ...ecRecorded.today.map((point) => point.value),
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
      position: drybackVwc,
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
    const vwcAt = axis.min + fraction * span;
    const next =
      handle.axis === "ec"
        ? fraction * ecMax
        : handle.axis === "dryback" && drybackPeak
          ? (1 - vwcAt / drybackPeak) * 100
          : vwcAt;
    commit(handle.key, next);
  }
  // The reference line, with the straight P1 segment replaced by one riser per shot.
  const rampEnd = plan.vwc.findIndex((point) => point.phase === "P1");
  const drawn =
    plan.p1Steps.length && rampEnd > 0
      ? [
          ...plan.vwc.slice(0, rampEnd),
          ...plan.p1Steps.flatMap((step) => [
            { hour: step.hour, value: step.from },
            { hour: step.hour, value: step.to },
          ]),
          ...plan.vwc.slice(rampEnd),
        ]
      : plan.vwc;
  const linePath = (points: readonly { hour: number; value: number }[]) =>
    points
      .map((point, index) => `${index ? "L" : "M"}${x(point.hour)},${y(point.value)}`)
      .join(" ");
  const targetPath = linePath(projection?.points ?? drawn);
  // The axis follows the data, so pixel paths move when it rescales; this names a line by what it
  // plots, for checks that a saved line did not change while its draft did.
  const plottedValues = (points: readonly { hour: number; value: number }[]) =>
    points.map((point) => `${+point.hour.toFixed(3)}:${+point.value.toFixed(2)}`).join(" ");
  const shots =
    projection?.shots ??
    plan.p1Steps.map((step) => ({ ...step, phase: "P1" as PlanningPhaseId, emergency: false }));
  const shotCount = (phase: PlanningPhaseId) => shots.filter((shot) => shot.phase === phase).length;
  // These two describe the straight schematic, which the projected day replaces.
  const warnings = projection
    ? plan.warnings.filter(
        (warning) =>
          !/Overnight is shown flat|overnight reference reaches or crosses/.test(warning),
      )
    : plan.warnings;
  const recordedPath = (points: readonly RecordedPoint[], scale: (value: number) => number) =>
    points
      .map((point, index) => `${index ? "L" : "M"}${x(point.hour)},${scale(point.value)}`)
      .join(" ");
  const nowVwc = vwcRecorded.today.at(-1);
  const nowEc = ecRecorded.today.at(-1);
  const todayVwc = extremes(vwcRecorded.today);
  const yesterdayVwc = extremes(vwcRecorded.previous[0] ?? []);
  const at = (point: RecordedPoint) => planningClock(lightsOn, point.hour);
  const ecPath = (points: PlanningPoint[]) =>
    points
      .map(
        (point, index) =>
          `${index && !point.breakBefore ? "L" : "M"}${x(point.hour)},${ey(point.value)}`,
      )
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
        <Badge variant="outline">
          {hasRecorded ? "Targets + recorded sensor" : "Planning illustration"}
        </Badge>
      </div>
      <div className="planning-chart-key">
        <span>
          <i className="vwc-key" />
          VWC · left (%)
        </span>
        <span>
          <i className="ec-key" />
          EC schematic · right (mS/cm)
        </span>
        {hasRecorded && (
          <>
            <span>
              <i className="recorded-key" />
              Recorded, this grow-day
            </span>
            <span>
              <i className="recorded-key previous" />
              Recorded, earlier grow-days
            </span>
          </>
        )}
      </div>
      {hasRecorded && (
        <dl className="planning-recorded" aria-label="Recorded VWC for this zone">
          {nowVwc && (
            <div>
              <dt>Now</dt>
              <dd>{trim(nowVwc.value)}%</dd>
            </div>
          )}
          {todayVwc && (
            <>
              <div>
                <dt>Peak · this grow-day</dt>
                <dd>
                  {trim(todayVwc.peak.value)}% <small>{at(todayVwc.peak)}</small>
                </dd>
              </div>
              <div>
                <dt>Trough · this grow-day</dt>
                <dd>
                  {trim(todayVwc.trough.value)}% <small>{at(todayVwc.trough)}</small>
                </dd>
              </div>
            </>
          )}
          {yesterdayVwc && (
            <>
              <div>
                <dt>Peak · previous grow-day</dt>
                <dd>
                  {trim(yesterdayVwc.peak.value)}% <small>{at(yesterdayVwc.peak)}</small>
                </dd>
              </div>
              <div>
                <dt>Trough · previous grow-day</dt>
                <dd>
                  {trim(yesterdayVwc.trough.value)}% <small>{at(yesterdayVwc.trough)}</small>
                </dd>
              </div>
            </>
          )}
          {nowEc && (
            <div>
              <dt>Pore EC now</dt>
              <dd>{trim(nowEc.value, 2)}</dd>
            </div>
          )}
        </dl>
      )}
      <p className="muted small" style={{ padding: "0 16px 12px", margin: 0 }}>
        VWC is absolute water content (%). Dryback is a relative drop from the reference peak, not
        percentage points. Dashed EC connects configured phase anchors through the night; it does
        not predict EC or salt concentration.
        {drybackPeak !== null && drybackVwc !== null && (
          <>
            {" "}
            Relative dryback: {parameters.dryback_target}% of the {Number(drybackPeak.toFixed(2))}%
            VWC {projection ? "projected peak" : "reference"} gives a{" "}
            {Number(drybackVwc.toFixed(2))}% VWC dryback target.
          </>
        )}
      </p>
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
            {hasRecorded
              ? "Targets from lights-on to the next lights-on, with this zone’s recorded probe readings drawn underneath. Blue is the VWC target; dashed pink is the EC target; the dark line is recorded VWC today."
              : "Setpoint illustration from lights-on to the next lights-on. Blue is VWC; dashed pink is EC. This is not recorded or forecast sensor data."}
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
                  fontSize="12"
                >
                  {phase.id}
                </text>
              )}
            </g>
          ))}
          {[0, 25, 50, 75, 100].map((tick) => {
            const line = top + height * (1 - tick / 100);
            return (
              <g key={tick}>
                <line
                  x1={left}
                  x2={width - right}
                  y1={line}
                  y2={line}
                  stroke="var(--border)"
                  strokeDasharray="3 5"
                />
                <text
                  x={left - 7}
                  y={line + 4}
                  textAnchor="end"
                  fill="var(--muted-foreground)"
                  fontSize="12"
                >
                  {trim(axis.min + (span * tick) / 100)}%
                </text>
                <text
                  x={width - right + 7}
                  y={line + 4}
                  fill="var(--muted-foreground)"
                  fontSize="12"
                >
                  {((ecMax * tick) / 100).toFixed(1)}
                </text>
              </g>
            );
          })}
          {previousDay.length > 1 && (
            <path
              data-planning-line="recorded-vwc-previous"
              d={recordedPath(previousDay, y)}
              fill="none"
              stroke="var(--foreground)"
              strokeWidth="1.25"
              opacity="0.3"
            >
              <title>Recorded VWC, previous grow-day</title>
            </path>
          )}
          {[0, 6, 12, 18, 24].map((hour) => (
            <text
              key={hour}
              x={x(hour)}
              y={281}
              textAnchor="middle"
              fill="var(--muted-foreground)"
              fontSize="12"
            >
              {planningClock(lightsOn, hour)}
            </text>
          ))}
          {saved && saved.photoperiod > 0 && (
            <g opacity="0.45" aria-label="Saved controller setpoints">
              {saved.vwc.length > 0 && (
                <path
                  data-planning-line="baseline-vwc"
                  data-planning-values={plottedValues(savedProjection?.points ?? saved.vwc)}
                  d={linePath(savedProjection?.points ?? saved.vwc)}
                  fill="none"
                  stroke="var(--muted-foreground)"
                  strokeWidth="2"
                  strokeDasharray="4 5"
                />
              )}
              {saved.ec.length > 0 && (
                <path
                  data-planning-line="baseline-ec"
                  d={ecPath(saved.ec)}
                  fill="none"
                  stroke="#df78b5"
                  strokeWidth="1.5"
                  strokeDasharray="2 6"
                />
              )}
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
                  <title>{`Saved rescue level: ${saved.emergencyFloor}% VWC`}</title>
                </line>
              )}
            </g>
          )}
          {plan.photoperiod > 0 && (
            <>
              {plan.p2Envelope && !projection && (
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
                  data-planning-emergency={
                    plan.emergencyReferenceActive ? "reference-crosses-floor" : undefined
                  }
                  x1={x(p3.start)}
                  x2={x(24)}
                  y1={y(plan.emergencyFloor)}
                  y2={y(plan.emergencyFloor)}
                  stroke="var(--destructive)"
                  strokeDasharray="3 4"
                >
                  <title>{`Rescue shot when below ${plan.emergencyFloor}% VWC`}</title>
                </line>
              )}
              {targetPath && (
                <path
                  data-planning-line="vwc"
                  data-planning-values={plottedValues(projection?.points ?? drawn)}
                  d={targetPath}
                  fill="none"
                  stroke="#03a9f4"
                  strokeWidth="2.5"
                />
              )}
              {projection && Number.isFinite(parameters.p2_vwc_threshold) && p2.end > p2.start && (
                <g data-planning-line="p2-threshold">
                  <line
                    x1={x(p2.start)}
                    x2={x(p2.end)}
                    y1={y(parameters.p2_vwc_threshold)}
                    y2={y(parameters.p2_vwc_threshold)}
                    stroke="#42b995"
                    strokeOpacity="0.8"
                    strokeDasharray="5 4"
                  >
                    <title>{`Maintenance shot when below ${trim(parameters.p2_vwc_threshold)}% VWC: one fires whenever the zone reads below here`}</title>
                  </line>
                  <text
                    x={x(p2.end) - 6}
                    y={y(parameters.p2_vwc_threshold) + 13}
                    textAnchor="end"
                    fill="#42b995"
                    fontSize="12"
                  >
                    Maintenance trigger {trim(parameters.p2_vwc_threshold)}%
                  </text>
                  {advice && x(p2.end) - x(p2.start) > 190 && (
                    <text
                      data-planning-advice="p2"
                      x={(x(p2.start) + x(p2.end)) / 2}
                      y={y(parameters.p2_vwc_threshold) - 8}
                      textAnchor="middle"
                      fill="var(--destructive)"
                      fontSize="12"
                      fontWeight="600"
                    >
                      {advice.shots
                        ? `First P2 shot not until ${planningClock(lightsOn, advice.firstShotHour ?? 0)}`
                        : `No P2 shot: ${trim(advice.pointsToThreshold)} points to dry, ${trim(advice.hoursToThreshold)} h at this rate`}
                    </text>
                  )}
                </g>
              )}
              {drybackVwc !== null &&
                [
                  [p3.start, 24],
                  [0, plan.phases[0].end],
                ].map(([from, to]) => (
                  <line
                    key={from}
                    data-planning-line="dryback-target"
                    x1={x(from)}
                    x2={x(to)}
                    y1={y(drybackVwc)}
                    y2={y(drybackVwc)}
                    stroke="#03a9f4"
                    strokeOpacity="0.55"
                    strokeDasharray="7 4"
                  >
                    <title>
                      Dryback target: {trim(drybackVwc)}% VWC ({parameters.dryback_target}% below
                      the peak). P0 hands over to P1 once the zone has dried to here.
                    </title>
                  </line>
                ))}
              {shots.map((shot, index) => {
                const inPhase = shots.filter((other) => other.phase === shot.phase);
                return (
                  <line
                    key={`${shot.phase}-${shot.hour}`}
                    data-planning-shot={shot.phase}
                    x1={x(shot.hour)}
                    x2={x(shot.hour)}
                    y1={y(shot.from)}
                    y2={y(shot.to)}
                    stroke={shot.emergency ? "var(--destructive)" : "#03a9f4"}
                    strokeWidth="7"
                    strokeOpacity={shot.emergency ? 0.35 : 0}
                  >
                    <title>
                      {shot.emergency ? "Rescue shot" : `${shot.phase} shot`}{" "}
                      {inPhase.indexOf(shots[index]) + 1} of {inPhase.length} ·{" "}
                      {planningClock(lightsOn, shot.hour)}
                      {shot.size === null ? "" : ` · ${trim(shot.size, 2)}% of substrate`} ·{" "}
                      {trim(shot.from)}% → {trim(shot.to)}% VWC
                    </title>
                  </line>
                );
              })}
              {ecRecorded.today.length > 1 && (
                <path
                  data-planning-line="recorded-ec"
                  d={recordedPath(ecRecorded.today, ey)}
                  fill="none"
                  stroke="#b8478a"
                  strokeWidth="1.25"
                  strokeOpacity="0.75"
                >
                  <title>Recorded pore EC, this grow-day</title>
                </path>
              )}
              {vwcRecorded.today.length > 1 && (
                <path
                  data-planning-line="recorded-vwc"
                  d={recordedPath(vwcRecorded.today, y)}
                  fill="none"
                  stroke="var(--foreground)"
                  strokeWidth="1.75"
                >
                  <title>Recorded VWC, this grow-day (lights-on to lights-on)</title>
                </path>
              )}
              {nowVwc && (
                <g data-planning-now="vwc">
                  <circle
                    cx={x(nowVwc.hour)}
                    cy={y(nowVwc.value)}
                    r="3.5"
                    fill="var(--foreground)"
                  />
                  <text
                    x={Math.min(x(nowVwc.hour) + 7, width - right - 58)}
                    y={y(nowVwc.value) - 8}
                    fill="var(--foreground)"
                    fontSize="12"
                    fontWeight="600"
                  >
                    Now {trim(nowVwc.value)}%
                  </text>
                </g>
              )}
              {plan.ec.length > 0 && (
                <path
                  data-planning-line="ec"
                  d={ecPath(plan.ec)}
                  fill="none"
                  stroke="#df78b5"
                  strokeWidth="2"
                  strokeDasharray="6 4"
                >
                  <title>
                    EC phase-anchor schematic; overnight interpolates to the next morning reference,
                    not a predicted salt response
                  </title>
                </path>
              )}
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
                      setHeldAxis(axis);
                      event.currentTarget.setPointerCapture(event.pointerId);
                    }}
                    onPointerMove={(event) => drag(event, handle)}
                    onPointerUp={(event) => {
                      dragging.current = null;
                      setHeldAxis(null);
                      if (event.currentTarget.hasPointerCapture(event.pointerId))
                        event.currentTarget.releasePointerCapture(event.pointerId);
                    }}
                    onPointerCancel={() => {
                      dragging.current = null;
                      setHeldAxis(null);
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
              {shots.some((shot) => shot.phase !== "P1") ? (
                <g data-planning-cadence="projected">
                  {shots
                    .filter((shot) => shot.phase !== "P1")
                    .map((shot) => (
                      <line
                        key={`${shot.phase}-${shot.hour}`}
                        x1={x(shot.hour)}
                        x2={x(shot.hour)}
                        y1={297}
                        y2={311}
                        stroke={shot.emergency ? "var(--destructive)" : "#42b995"}
                        strokeWidth={2}
                      >
                        <title>
                          Projected {shot.emergency ? "emergency" : shot.phase} shot ·{" "}
                          {planningClock(lightsOn, shot.hour)}
                        </title>
                      </line>
                    ))}
                </g>
              ) : (
                x(p2.end) - x(p2.start) > 110 && (
                  <text
                    x={(x(p2.start) + x(p2.end)) / 2}
                    y={307}
                    textAnchor="middle"
                    fill="var(--muted-foreground)"
                    fontSize="12"
                  >
                    {projection ? "P2 · no shot projected" : "P2 · sensor-triggered"}
                  </text>
                )
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
      {projection ? (
        <div className="planning-projection" role="note">
          <p>
            <strong>Projected day.</strong> P0 dries on from {trim(projection.lightsOnVwc)}% at
            lights-on.{" "}
            {shotCount("P1")
              ? `P1 fires ${shotCount("P1")} shots, ${parameters.p1_time_between_shots} minutes apart, to ${trim(parameters.p1_target_vwc)}%.`
              : `P1 climbs to ${trim(parameters.p1_target_vwc)}% (shot count or spacing not set, so no steps are drawn).`}{" "}
            P2 fires a {trim(parameters.p2_shot_size)}% shot each time VWC falls below{" "}
            {trim(parameters.p2_vwc_threshold)}%: {shotCount("P2") || "none"} projected. P3 dries
            down overnight to {trim(projection.lightsOnVwc)}%
            {shotCount("P3") ? `, with ${shotCount("P3")} rescue shot(s) at the rescue level` : ""}.
            Hover any riser for its time and size.
          </p>
          <p>
            Dry-down: {projection.rates.day} points/h lights-on (
            {projection.measured.day
              ? "measured from this zone"
              : "a typical flowering-room rate, until this zone has history"}
            ), {projection.rates.night} points/h lights-off (
            {projection.measured.night ? "measured" : "nominal"}). Each shot is drawn retaining{" "}
            {retention && retention > 0
              ? `${trim(projection.retention, 2)} points per 1% (this zone's learned gain)`
              : "all of its water, which is the most it can do"}
            . Shot timing is a projection from those rates, not a schedule: the engine fires on the
            probe.
          </p>
          {advice && (
            <p className="planning-projection-warning" data-planning-advice="p2-text">
              <strong>
                {advice.shots
                  ? "P2 maintenance starts late."
                  : "No P2 sawtooth with these targets."}
              </strong>{" "}
              The engine fires a maintenance shot only once VWC reads below the maintenance trigger.
              From {trim(advice.pointsToThreshold + parameters.p2_vwc_threshold)}% at the start of
              P2 that is {trim(advice.pointsToThreshold)} points, about{" "}
              {trim(advice.hoursToThreshold)} hours at {projection.rates.day} points/h
              {advice.shots
                ? `, so the first shot is not until ${planningClock(lightsOn, advice.firstShotHour ?? 0)}.`
                : ", longer than P2 lasts."}{" "}
              For a sawtooth from the start of P2, drag the maintenance trigger up to about{" "}
              {trim(advice.suggestedThreshold)}%, just under the peak VWC target. Shots then repeat
              about every {trim(advice.repeatHours)} hours at this dry-down; a smaller P2 shot gives
              a finer sawtooth.
            </p>
          )}
          {drybackVwc !== null && projection.lightsOnVwc > drybackVwc + 0.5 && (
            <p className="planning-projection-warning">
              At this dry-down the zone reaches lights-on at {trim(projection.lightsOnVwc)}%, which
              is {trim(projection.lightsOnVwc - drybackVwc)} points short of the {trim(drybackVwc)}%
              dryback target. P0 would run its full {parameters.p0_maximum_wait_time ?? 60} minutes.
            </p>
          )}
        </div>
      ) : (
        plan.p1Windows.length > 0 && (
          <p className="muted small" style={{ padding: "0 16px 12px", margin: 0 }}>
            P1 shows all {plan.p1Windows.length} eligible shots as steps,{" "}
            {parameters.p1_time_between_shots} minutes apart; hover a step for its time and size.
          </p>
        )
      )}
      <p className="muted small" style={{ padding: "0 16px 12px", margin: 0 }}>
        The rescue level stays separate from the dry-down; routine watering stops at the P3
        boundary.
        {Number.isFinite(parameters.p3_emergency_shot_size)
          ? ` Its ${parameters.p3_emergency_shot_size}% rescue shot is conditional on controller safety checks.`
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
      {warnings.length > 0 && (
        <div className="planning-warnings" role="status">
          {warnings.map((warning) => (
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
