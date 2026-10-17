import { useEffect, useId, useRef, useState, type PointerEvent } from "react";
import { SlidersHorizontal } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { UiTip } from "@/components/info-tip";
import { CheckChip, GaugeRow, QualityChip, StatusLine } from "@/components/hmi";
import { gauge, probeGaps, valueAt, PROBE_GAP_VWC } from "@/lib/hmi";
import { referenceDryback } from "@/lib/day-chart";
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
  initialShowEc?: boolean;
  selectedPhase?: PlanningPhaseId;
  description?: string;
  /** Recorded probe readings for this zone, drawn under the targets on the same axes, cut into
   * grow-days on the clock of `timeZone` (Home Assistant's; the browser's when omitted). */
  recorded?: {
    vwc: readonly RecordedReading[];
    ec: readonly RecordedReading[];
    now: number;
    timeZone?: string;
  };
  /** Learned VWC points retained per 1% shot, when the zone's supervisor knows it. */
  retention?: number | null;
  /** The zone's name and its phase now, for the status line. */
  zoneName?: string;
  phase?: string | null;
  /** The pore EC band of the growth stage, when there is one. */
  ecBand?: [number, number] | null;
  /** The stage's reference overnight dryback, in VWC points, when there is one. */
  drybackPoints?: [number, number] | null;
}
const trim = (value: number | null | undefined, digits = 1) =>
  typeof value === "number" && Number.isFinite(value) ? String(Number(value.toFixed(digits))) : "—";
const PHASE_WORDS: Record<string, string> = {
  P0: "Morning dryback",
  P1: "Ramp",
  P2: "Maintenance",
  P3: "Overnight dryback",
};
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
/** Chart geometry: phase names over the plot, the clock under it, then one row of shot ticks. */
const TOP = 26,
  HEIGHT = 172,
  CLOCK_Y = TOP + HEIGHT + 17,
  SHOT_Y = CLOCK_Y + 10,
  SVG_HEIGHT = SHOT_Y + 14;
export function PlanningCurve({
  parameters,
  lightsOn,
  lightsOff,
  onChange,
  bounds,
  baseline,
  showEditors = true,
  initialShowEc = false,
  selectedPhase,
  description,
  recorded,
  retention,
  zoneName,
  phase,
  ecBand,
  drybackPoints,
}: PlanningCurveProps) {
  const limits =
    bounds ??
    Object.fromEntries(
      editors.map((editor) => [editor.key, { min: 0, max: editor.max, step: editor.step }]),
    );
  const id = useId();
  const container = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [showEc, setShowEc] = useState(initialShowEc);
  const [showEarlier, setShowEarlier] = useState(true);
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
  // A draft is only a draft while it differs from what the controller has.
  const dirty =
    !!baseline &&
    (baseline.lightsOn !== lightsOn ||
      baseline.lightsOff !== lightsOff ||
      [...new Set([...Object.keys(parameters), ...Object.keys(baseline.parameters)])].some(
        (key) => parameters[key] !== baseline.parameters[key],
      ));
  const left = 43,
    right = showEc ? 42 : 14,
    plotWidth = width - left - right;
  const x = (hour: number) => left + (Math.min(24, Math.max(0, hour)) / 24) * plotWidth;
  const fold = (readings: readonly RecordedReading[] = []) =>
    foldRecorded(readings, lightsOn, recorded?.now ?? NaN, recorded?.timeZone);
  // A probe dropout reads 0 %: it is a gap in the data, not a dry zone, so it is left out of the
  // lines and of the peak, and the card says so.
  const vwcFolded = fold(recorded?.vwc);
  const todaySplit = probeGaps(vwcFolded.today);
  const hourOf = (time: number) =>
    vwcFolded.today.find((point) => point.time === time)?.hour ?? NaN;
  const gaps = todaySplit.gaps.map((gap) => ({
    ...gap,
    from: hourOf(gap.start),
    to: hourOf(gap.end),
  }));
  const vwcRecorded = {
    today: todaySplit.clean,
    previous: vwcFolded.previous.map((day) => probeGaps(day).clean),
  };
  const ecRecorded = fold(recorded?.ec);
  const ecToday = probeGaps(ecRecorded.today, 0).clean;
  const hasRecorded = vwcRecorded.today.length + vwcRecorded.previous.length > 0;
  const nowHour = recorded
    ? (fold([{ time: recorded.now, value: 1 }]).today[0]?.hour ?? null)
    : null;
  // The day drawn the way the engine runs it, timed by this zone's own measured dryback.
  const rates = dryRates([vwcRecorded.today, ...vwcRecorded.previous], plan.photoperiod);
  const projection = projectDay(plan, parameters, { rates, retention });
  const savedProjection =
    saved && baseline ? projectDay(saved, baseline.parameters, { rates, retention }) : null;
  const advice = projection ? p2Advice(plan, parameters, projection) : null;
  const drybackVwc = projection ? projection.drybackVwc : plan.morningDrybackVwc;
  const drybackPeak = projection ? projection.peak : plan.drybackReference;
  const previousDay = vwcRecorded.previous[0] ?? [];
  // The previous grow-day's peak and low, from its usable readings: a quiet line under the gauges.
  const previous =
    previousDay.length > 1
      ? {
          peak: previousDay.reduce((a, b) => (b.value > a.value ? b : a)),
          low: previousDay.reduce((a, b) => (b.value < a.value ? b : a)),
        }
      : null;
  // The stage's reference dryback as VWC levels under the peak, drawn as a muted band overnight.
  const referenceBand: [number, number] | null =
    drybackPoints && drybackPeak
      ? [drybackPeak - drybackPoints[1], drybackPeak - drybackPoints[0]]
      : null;
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
      ...(referenceBand ?? []),
      ...vwcRecorded.today.map((point) => point.value),
      ...(showEarlier ? previousDay.map((point) => point.value) : []),
    ]);
  const span = axis.max - axis.min;
  const y = (value: number) =>
    TOP + HEIGHT * (1 - (Math.min(axis.max, Math.max(axis.min, value)) - axis.min) / span);
  const ecMax = Math.max(
    6,
    Math.ceil(
      Math.max(
        0,
        ...plan.ec.map((point) => point.value),
        ...(saved?.ec.map((point) => point.value) ?? []),
        ...ecToday.map((point) => point.value),
      ) * 1.15,
    ),
  );
  const ey = (value: number) => TOP + HEIGHT * (1 - Math.min(ecMax, Math.max(0, value)) / ecMax);
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
    const fraction = 1 - (local.y - TOP) / HEIGHT;
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
  const targetPoints = projection?.points ?? drawn;
  const targetPath = linePath(targetPoints);
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
  // A recorded line breaks across a probe gap instead of joining over it.
  const recordedPath = (points: readonly RecordedPoint[], scale: (value: number) => number) =>
    points
      .map((point, index) => {
        const broken =
          index > 0 &&
          todaySplit.gaps.some(
            (gap) => gap.start > points[index - 1].time && gap.start < point.time,
          );
        return `${index && !broken ? "L" : "M"}${x(point.hour)},${scale(point.value)}`;
      })
      .join(" ");
  const inGap = (vwcFolded.today.at(-1)?.value ?? Infinity) <= PROBE_GAP_VWC;
  const nowVwc = inGap ? undefined : vwcRecorded.today.at(-1);
  const nowEc = ecToday.at(-1);
  const at = (hour: number) => planningClock(lightsOn, hour);
  const ecPath = (points: PlanningPoint[]) =>
    points
      .map(
        (point, index) =>
          `${index && !point.breakBefore ? "L" : "M"}${x(point.hour)},${ey(point.value)}`,
      )
      .join(" ");

  // The four key values, each against its target.
  const phaseNow =
    phase && /^P[0-3]$/.test(phase)
      ? phase
      : nowHour === null
        ? null
        : (plan.phases.find((item) => nowHour >= item.start && nowHour < item.end)?.id ?? null);
  const todayPeak = vwcRecorded.today.length
    ? Math.max(...vwcRecorded.today.map((point) => point.value))
    : null;
  const p1Done = nowHour !== null && nowHour >= p1.end;
  const ecTarget =
    phaseNow && phaseNow !== "P3" ? parameters[`ec_target_${phaseNow.toLowerCase()}`] : NaN;
  const gauges = hasRecorded
    ? [
        {
          id: "vwc-now",
          model: gauge({
            label: "VWC now",
            value: nowVwc?.value ?? null,
            target: nowHour === null ? null : valueAt(targetPoints, nowHour),
            unit: "%",
            tolerance: 5,
            quality: inGap ? "probe gap" : undefined,
          }),
        },
        {
          id: "peak",
          model: gauge({
            label: "Peak today",
            value: todayPeak,
            target: parameters.p1_target_vwc,
            unit: "%",
            tolerance: 3,
            underIsNormal: !p1Done,
          }),
        },
        {
          id: "dryback",
          model: gauge({
            label: "Dryback so far",
            value: todayPeak && nowVwc ? ((todayPeak - nowVwc.value) / todayPeak) * 100 : null,
            target: parameters.dryback_target,
            reference: referenceDryback(drybackPoints, todayPeak),
            unit: "%",
            points: "%",
            tolerance: 3,
            underIsNormal: true,
            quality: inGap ? "probe gap" : undefined,
          }),
        },
        {
          id: "pore-ec",
          model: gauge({
            label: "Pore EC",
            value: nowEc?.value ?? null,
            band: ecBand ?? null,
            target: ecBand ? null : ecTarget,
            tolerance: Number.isFinite(ecTarget) ? ecTarget * 0.15 : 0,
            unit: "",
            digits: 2,
            points: "mS/cm",
          }),
        },
      ]
    : [];
  const offPlan = gauges.some((item) => item.model.state === "abnormal");

  // At most one advisory: the first that applies. Its fix goes into the draft only.
  const suggestedDryback =
    projection && drybackVwc !== null && drybackPeak
      ? Math.floor((1 - projection.lightsOnVwc / drybackPeak) * 100 * 2) / 2
      : null;
  const check = advice
    ? {
        kind: "p2",
        text: `${
          advice.shots
            ? `The first maintenance shot is at ${at(advice.firstShotHour ?? 0)}, late in P2.`
            : "P2 gives no maintenance shot before P3."
        } Raise the re-water point to ${trim(advice.suggestedThreshold)}%.`,
        apply: () => commit("p2_vwc_threshold", advice.suggestedThreshold),
      }
    : projection && drybackVwc !== null && projection.lightsOnVwc > drybackVwc + 0.5
      ? {
          kind: "dryback",
          text: `The zone gets to ${trim(projection.lightsOnVwc)}% at lights-on, ${trim(projection.lightsOnVwc - drybackVwc)} points short of the dryback target.${
            suggestedDryback !== null && suggestedDryback > 0
              ? ` Set the dryback target to ${trim(suggestedDryback)}%.`
              : ""
          }`,
          apply:
            suggestedDryback !== null && suggestedDryback > 0
              ? () => commit("dryback_target", suggestedDryback)
              : null,
        }
      : warnings.length
        ? { kind: "warning", text: warnings[0], apply: null }
        : null;
  const canApply = (key: string) => !!onChange && !!limits[key];

  const phaseEnd = (id: PlanningPhaseId) =>
    projection?.points.filter((point) => point.phase === id).at(-1)?.value ?? null;
  const rows = plan.photoperiod
    ? plan.phases.map((item) => ({
        id: item.id,
        name: `${item.id} ${PHASE_WORDS[item.id] ?? item.label}`,
        starts: at(item.start),
        target:
          item.id === "P0"
            ? drybackVwc === null
              ? "—"
              : `${trim(drybackVwc)}% (${trim(parameters.dryback_target)}% dryback)`
            : item.id === "P1"
              ? `${trim(parameters.p1_target_vwc)}%`
              : item.id === "P2"
                ? `re-water ${trim(parameters.p2_vwc_threshold)}%`
                : `rescue floor ${trim(parameters.p3_emergency_vwc_threshold)}%`,
        shots: projection || item.id === "P1" ? String(shotCount(item.id)) : "—",
        end: `${at(item.end)}${
          item.id === "P3"
            ? projection
              ? ` · ${trim(projection.lightsOnVwc)}%`
              : ""
            : phaseEnd(item.id) !== null
              ? ` · ${trim(phaseEnd(item.id))}%`
              : ""
        }`,
      }))
    : [];

  return (
    <section className="panel planning-curve" aria-labelledby={`${id}-title`}>
      <div className="panel-heading">
        <div>
          <div className="label-with-tip">
            <h2 id={`${id}-title`}>Daily VWC and EC plan</h2>
            <UiTip copyKey="daily vwc & ec plan" />
          </div>
          <p>
            {description ??
              (onChange
                ? "Drag a target or use the precise controls. Changes follow the selected day and zone."
                : "Setpoints for the selected day and zone.")}
          </p>
        </div>
      </div>
      <div className="planning-hmi">
        <StatusLine
          name={zoneName}
          phase={phaseNow ? `${phaseNow} · ${PHASE_WORDS[phaseNow]}` : null}
          state={
            hasRecorded
              ? { text: offPlan ? "off plan" : "on plan", abnormal: offPlan }
              : { text: "plan only, no readings", abnormal: false }
          }
        >
          {dirty && <span className="hmi-chip">draft not applied</span>}
          {gaps.length > 0 && (
            <QualityChip
              data-probe-gap
              title="The probe gave no usable reading. These readings are not drawn and are not used."
            >
              Probe gap{" "}
              {gaps
                .map((gap) =>
                  gap.from === gap.to ? at(gap.from) : `${at(gap.from)}–${at(gap.to)}`,
                )
                .join(", ")}
            </QualityChip>
          )}
        </StatusLine>
        {previous && (
          <p className="planning-previous" data-planning-previous>
            Previous grow-day: peak {trim(previous.peak.value)}% at {at(previous.peak.hour)} · low{" "}
            {trim(previous.low.value)}% at {at(previous.low.hour)}
          </p>
        )}
        {gauges.length > 0 && (
          <GaugeRow
            className="planning-recorded"
            gauges={gauges}
            label="Recorded VWC and EC against the plan"
          />
        )}
      </div>
      <div className="planning-legend" role="group" aria-label="Chart key">
        <span>
          <i className="key-recorded" aria-hidden="true" />
          Recorded
        </span>
        <span>
          <i className="key-target" aria-hidden="true" />
          {dirty ? "Saved target" : "Target"}
        </span>
        {dirty && (
          <span>
            <i className="key-draft" aria-hidden="true" />
            Draft
          </span>
        )}
        <span>
          <i className="key-shot" aria-hidden="true" />
          Shot
        </span>
        <span>
          <i className="key-limit" aria-hidden="true" />
          Re-water, dryback, rescue
        </span>
        {referenceBand && (
          <span>
            <i className="key-reference" aria-hidden="true" />
            Reference dryback
          </span>
        )}
        {gaps.length > 0 && (
          <span>
            <i className="key-gap" aria-hidden="true" />
            Probe gap
          </span>
        )}
        <span className="planning-legend-toggles">
          {previousDay.length > 1 && (
            <button
              type="button"
              className="planning-toggle"
              aria-pressed={showEarlier}
              onClick={() => setShowEarlier(!showEarlier)}
            >
              <i className="key-earlier" aria-hidden="true" />
              Earlier days
            </button>
          )}
          <button
            type="button"
            className="planning-toggle"
            aria-pressed={showEc}
            onClick={() => setShowEc(!showEc)}
          >
            <i className="key-ec" aria-hidden="true" />
            EC
          </button>
        </span>
      </div>
      <div ref={container} className="planning-svg-wrap">
        <svg
          viewBox={`0 0 ${width} ${SVG_HEIGHT}`}
          width="100%"
          height={SVG_HEIGHT}
          role="group"
          aria-label="24-hour phase and setpoint chart"
        >
          <title>
            {hasRecorded
              ? "Targets from lights-on to the next lights-on. The dashed line is the target; the solid line is the VWC that the probe recorded on this grow-day."
              : "Setpoint illustration from lights-on to the next lights-on. This is not recorded or forecast sensor data."}
          </title>
          {plan.phases.map((phase, index) => (
            <g key={phase.id} data-planning-phase={phase.id}>
              <rect
                x={x(phase.start)}
                y={TOP}
                width={Math.max(0, x(phase.end) - x(phase.start))}
                height={HEIGHT}
                fill="var(--muted-foreground)"
                fillOpacity={selectedPhase === phase.id ? 0.14 : index % 2 ? 0.07 : 0.025}
              />
              {x(phase.end) - x(phase.start) > 20 && (
                <text
                  x={(x(phase.start) + x(phase.end)) / 2}
                  y={TOP - 8}
                  textAnchor="middle"
                  fill="var(--muted-foreground)"
                  fontSize="12"
                  fontWeight="600"
                >
                  {phase.id}
                </text>
              )}
            </g>
          ))}
          {[0, 25, 50, 75, 100].map((tick) => {
            const line = TOP + HEIGHT * (1 - tick / 100);
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
                {showEc && (
                  <text
                    x={width - right + 7}
                    y={line + 4}
                    fill="var(--muted-foreground)"
                    fontSize="12"
                  >
                    {((ecMax * tick) / 100).toFixed(1)}
                  </text>
                )}
              </g>
            );
          })}
          {gaps.map((gap) => (
            <g key={gap.start} data-probe-gap>
              <rect
                x={x(gap.from) - 2}
                y={TOP}
                width={Math.max(4, x(gap.to) - x(gap.from) + 4)}
                height={HEIGHT}
                fill="var(--muted-foreground)"
                fillOpacity={0.18}
              >
                <title>{`Probe gap ${at(gap.from)}–${at(gap.to)}: no usable reading`}</title>
              </rect>
              <text
                x={x(gap.from)}
                y={TOP + HEIGHT - 6}
                textAnchor="middle"
                fill="var(--muted-foreground)"
                fontSize="12"
                fontStyle="italic"
              >
                gap
              </text>
            </g>
          ))}
          {previousDay.length > 1 && (
            <path
              data-planning-line="recorded-vwc-previous"
              d={recordedPath(previousDay, y)}
              display={showEarlier ? undefined : "none"}
              fill="none"
              stroke="var(--foreground)"
              strokeWidth="1.25"
              opacity="0.22"
            >
              <title>Recorded VWC, previous grow-day</title>
            </path>
          )}
          {[0, 6, 12, 18, 24].map((hour) => (
            <text
              key={hour}
              x={x(hour)}
              y={CLOCK_Y}
              textAnchor={hour === 0 ? "start" : hour === 24 ? "end" : "middle"}
              fill="var(--muted-foreground)"
              fontSize="12"
            >
              {planningClock(lightsOn, hour)}
            </text>
          ))}
          {saved && saved.photoperiod > 0 && (
            <g opacity={dirty ? 0.75 : 0} aria-label="Saved controller setpoints">
              {saved.vwc.length > 0 && (
                <path
                  data-planning-line="baseline-vwc"
                  data-planning-values={plottedValues(savedProjection?.points ?? saved.vwc)}
                  d={linePath(savedProjection?.points ?? saved.vwc)}
                  fill="none"
                  stroke="var(--muted-foreground)"
                  strokeWidth="1.75"
                  strokeDasharray="6 4"
                />
              )}
              {saved.ec.length > 0 && (
                <path
                  data-planning-line="baseline-ec"
                  d={ecPath(saved.ec)}
                  display={showEc ? undefined : "none"}
                  fill="none"
                  stroke="var(--muted-foreground)"
                  strokeWidth="1.25"
                  strokeDasharray="2 5"
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
                  <title>{`Saved rescue floor: ${saved.emergencyFloor}% VWC`}</title>
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
                  fill="var(--muted-foreground)"
                  fillOpacity={0.12}
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
                  stroke={
                    plan.emergencyReferenceActive ? "var(--warning)" : "var(--muted-foreground)"
                  }
                  strokeDasharray="2 4"
                >
                  <title>{`Rescue shot when below ${plan.emergencyFloor}% VWC`}</title>
                </line>
              )}
              {targetPath && (
                <path
                  data-planning-line="vwc"
                  data-planning-draft={dirty ? "" : undefined}
                  data-planning-values={plottedValues(targetPoints)}
                  d={targetPath}
                  fill="none"
                  stroke={dirty ? "var(--primary)" : "var(--muted-foreground)"}
                  strokeWidth={dirty ? 2.25 : 1.75}
                  strokeDasharray="6 4"
                />
              )}
              {projection && Number.isFinite(parameters.p2_vwc_threshold) && p2.end > p2.start && (
                <g data-planning-line="p2-threshold">
                  <line
                    x1={x(p2.start)}
                    x2={x(p2.end)}
                    y1={y(parameters.p2_vwc_threshold)}
                    y2={y(parameters.p2_vwc_threshold)}
                    stroke="var(--muted-foreground)"
                    strokeOpacity="0.8"
                    strokeDasharray="2 4"
                  >
                    <title>{`Maintenance shot when below ${trim(parameters.p2_vwc_threshold)}% VWC: one fires whenever the zone reads below here`}</title>
                  </line>
                  {x(p2.end) - x(p2.start) > 110 && (
                    <text
                      x={x(p2.end) - 6}
                      y={y(parameters.p2_vwc_threshold) + 13}
                      textAnchor="end"
                      fill="var(--muted-foreground)"
                      fontSize="12"
                    >
                      Re-water {trim(parameters.p2_vwc_threshold)}%
                    </text>
                  )}
                </g>
              )}
              {referenceBand &&
                [
                  [p3.start, 24],
                  [0, plan.phases[0].end],
                ].map(([from, to]) => (
                  <rect
                    key={from}
                    data-planning-line="reference-dryback"
                    x={x(from)}
                    y={y(referenceBand[1])}
                    width={Math.max(0, x(to) - x(from))}
                    height={Math.max(1, y(referenceBand[0]) - y(referenceBand[1]))}
                    fill="var(--muted-foreground)"
                    fillOpacity={0.14}
                  >
                    <title>
                      {`Reference dryback for the stage: ${trim(drybackPoints![0])}–${trim(drybackPoints![1])} points under the ${trim(drybackPeak)}% peak (${trim(referenceBand[0])}–${trim(referenceBand[1])}% VWC)`}
                    </title>
                  </rect>
                ))}
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
                    stroke="var(--muted-foreground)"
                    strokeOpacity="0.7"
                    strokeDasharray="2 4"
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
                    y1={SHOT_Y - 6}
                    y2={SHOT_Y + 6}
                    stroke={shot.emergency ? "var(--warning)" : "var(--muted-foreground)"}
                    strokeWidth="2"
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
              <g data-planning-ec display={showEc ? undefined : "none"}>
                {ecToday.length > 1 && (
                  <path
                    data-planning-line="recorded-ec"
                    d={recordedPath(ecToday, ey)}
                    fill="none"
                    stroke="var(--foreground)"
                    strokeWidth="1"
                    strokeOpacity="0.55"
                  >
                    <title>Recorded pore EC, this grow-day</title>
                  </path>
                )}
                {plan.ec.length > 0 && (
                  <path
                    data-planning-line="ec"
                    d={ecPath(plan.ec)}
                    fill="none"
                    stroke="var(--muted-foreground)"
                    strokeWidth="1.5"
                    strokeDasharray="1 4"
                    strokeLinecap="round"
                  >
                    <title>
                      EC phase-anchor schematic; overnight interpolates to the next morning
                      reference, not a predicted salt response
                    </title>
                  </path>
                )}
              </g>
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
                <circle
                  data-planning-now="vwc"
                  cx={x(nowVwc.hour)}
                  cy={y(nowVwc.value)}
                  r="3.5"
                  fill="var(--foreground)"
                >
                  <title>{`Now ${trim(nowVwc.value)}%`}</title>
                </circle>
              )}
              {handles.map((handle) => {
                const editor = editors.find((item) => item.key === handle.key)!;
                const position = handle.position as number;
                const limit = limits[handle.key];
                const editable = !!onChange && !!limit;
                const isEc = handle.axis === "ec";
                return (
                  <circle
                    key={handle.key}
                    cx={x(handle.hour)}
                    cy={isEc ? ey(position) : y(position)}
                    r={editable ? 5.5 : 3.5}
                    display={isEc && !showEc ? "none" : undefined}
                    fill="var(--surface)"
                    stroke={dirty ? "var(--primary)" : "var(--muted-foreground)"}
                    strokeWidth="2"
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
              {plan.photoperiod > 0 && (
                <line
                  x1={x(plan.photoperiod)}
                  x2={x(plan.photoperiod)}
                  y1={TOP}
                  y2={TOP + HEIGHT}
                  stroke="var(--muted-foreground)"
                  strokeDasharray="2 5"
                />
              )}
            </>
          )}
        </svg>
      </div>
      {check && (
        <CheckChip
          className="hmi-check planning-check"
          data-planning-advice={check.kind}
          text={check.text}
          action={
            check.apply && canApply(check.kind === "p2" ? "p2_vwc_threshold" : "dryback_target")
              ? { label: "Apply to draft", run: check.apply }
              : null
          }
        />
      )}
      {rows.length > 0 && (
        <div
          className="planning-projection"
          role="region"
          aria-label="Projected day by phase"
          tabIndex={0}
        >
          <table>
            <caption>
              {projection ? (
                <>
                  <strong>Projected day.</strong> Dryback rate{" "}
                  {projection.measured.day
                    ? "measured from this zone"
                    : "of a typical flowering room, until this zone has history"}
                  .
                </>
              ) : (
                <strong>Planned phases.</strong>
              )}
            </caption>
            <thead>
              <tr>
                <th scope="col">Phase</th>
                <th scope="col">Starts</th>
                <th scope="col">Target</th>
                <th scope="col">Shots</th>
                <th scope="col">Expected end</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} data-phase-row={row.id}>
                  <th scope="row">{row.name}</th>
                  <td>{row.starts}</td>
                  <td>{row.target}</td>
                  <td>{row.shots}</td>
                  <td>{row.end}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
        <summary>How this is worked out</summary>
        <ul>
          <li>
            VWC is absolute water content (%). Dryback is a relative drop from the reference peak,
            not percentage points.
            {drybackPeak !== null && drybackVwc !== null && (
              <>
                {" "}
                A {parameters.dryback_target}% dryback from the {Number(drybackPeak.toFixed(2))}%
                VWC {projection ? "projected peak" : "reference"} gives a{" "}
                {Number(drybackVwc.toFixed(2))}% VWC dryback target.
              </>
            )}
          </li>
          <li>
            Dashed EC connects configured phase anchors through the night; it does not predict EC or
            salt concentration. Use the EC button to show it.
          </li>
          {projection && (
            <li>
              Dryback rate: {projection.rates.day} points/h with the lights on (
              {projection.measured.day ? "measured" : "nominal"}), {projection.rates.night} points/h
              with the lights off ({projection.measured.night ? "measured" : "nominal"}). Each shot
              keeps{" "}
              {retention && retention > 0
                ? `${trim(projection.retention, 2)} points per 1% (the learned gain of this zone)`
                : "all of its water, which is the most it can keep"}
              . The shot times are a projection from these rates, not a schedule: the controller
              fires on the probe.
            </li>
          )}
          {advice && (
            <li data-planning-advice="p2-text">
              The controller gives a maintenance shot only when VWC falls below the re-water point.
              From {trim(advice.pointsToThreshold + parameters.p2_vwc_threshold)}% at the start of
              P2 that is {trim(advice.pointsToThreshold)} points, about{" "}
              {trim(advice.hoursToThreshold)} hours at this rate. At{" "}
              {trim(advice.suggestedThreshold)}% the shots repeat about every{" "}
              {trim(advice.repeatHours)} hours; a smaller P2 shot gives smaller steps.
            </li>
          )}
          <li>
            The rescue floor is separate from the dryback; routine shots stop at the P3 boundary.
            {Number.isFinite(parameters.p3_emergency_shot_size)
              ? ` Its ${parameters.p3_emergency_shot_size}% rescue shot is conditional on controller safety checks.`
              : ""}
          </li>
          <li>
            The P3 boundary is at lights-off here; the controller can stop earlier on the measured
            dryback. P2 can also change for EC and safety limits.
          </li>
          {gaps.length > 0 && (
            <li>
              A reading of {PROBE_GAP_VWC}% VWC or less is a probe gap, not a dry zone. Those
              readings are not drawn, and the peak and the dryback do not use them.
            </li>
          )}
          {baseline && (
            <li>
              The saved line and the draft line are aligned to lights-on; the times follow the draft
              schedule.
            </li>
          )}
          {plan.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
          {warnings.slice(check?.kind === "warning" ? 1 : 0).map((warning) => (
            <li key={warning} className="planning-warning">
              {warning}
            </li>
          ))}
          {plan.missing.length > 0 && (
            <li className="planning-missing">
              Not supplied: {plan.missing.join(", ")}. Missing targets are not plotted.
            </li>
          )}
        </ul>
      </details>
    </section>
  );
}
