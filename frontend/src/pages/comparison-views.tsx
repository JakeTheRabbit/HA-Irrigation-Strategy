import { useEffect, useMemo, useState } from "react";
import type { ComparisonTarget } from "@/lib/comparison-target";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ReviewApply, type ApplyReceipt, type ReviewRow } from "@/components/review-apply";
import type { ComparedRun, RunsDocument } from "@/lib/comparison-types";
import { comparedRun, runCallout, runResult, stageWord, type CalloutMetric } from "@/lib/comparison";
import { formatEc, formatVolume, getDisplayUnits } from "@/lib/display-units";
import type { GrowDaysDocument, HarvestsDocument } from "@/lib/grows";
import { NOMINAL_FLOWER_DAYS, stageArc, type Stage } from "@/lib/stage-arc";
import { dayKey, dayLabel } from "@/lib/time";
import type { Controller } from "@/lib/types";
import { errorText } from "@/lib/utils";
import { Empty } from "@/components/dashboard";
import { UiTip } from "@/components/info-tip";
import { Meter } from "@/components/mini-visuals";
import type { HistoryPoint, HistoryWindow, RunRecord, RunZone } from "@/lib/comparison-types";
import { addDays, ageAt, dateInZone, daysBetween, mergeDaily } from "@/lib/comparison";
export type Loaded = {
  current: HistoryWindow;
  previous: HistoryWindow | null;
  start: number;
  end: number;
  loadedAt: number;
  currentRun: RunRecord | null;
  previousRun: RunRecord | null;
  zone: RunZone;
  previousZone: RunZone | null;
  timeZone: string;
  warning: string | null;
};
export const format = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : value.toFixed(1);
export function ComparisonChart({
  loaded,
  targets,
  label,
  dailyTarget,
}: {
  loaded: Loaded;
  targets: { vwc: number | null; ec: number | null };
  label: string;
  dailyTarget?: ComparisonTarget;
}) {
  const runStart = loaded.currentRun?.start_date || dateInZone(loaded.start, loaded.timeZone);
  const first = ageAt(loaded.start, runStart, loaded.timeZone),
    last = ageAt(loaded.end, runStart, loaded.timeZone);
  const lines: {
    name: string;
    metric: "vwc" | "ec";
    color: string;
    previous: boolean;
    points: HistoryPoint[];
    start: string;
    zone: string;
  }[] = [];
  for (const metric of ["vwc", "ec"] as const) {
    const id = loaded.zone[`${metric}_sensor`];
    lines.push({
      name: `Current ${metric.toUpperCase()}`,
      metric,
      color: metric === "vwc" ? "#03a9f4" : "#e86aa5",
      previous: false,
      points: loaded.current.series.find((s) => s.entityId === id)?.points || [],
      start: runStart,
      zone: loaded.timeZone,
    });
    if (loaded.previous && loaded.previousRun && loaded.previousZone)
      lines.push({
        name: `Previous ${metric.toUpperCase()}`,
        metric,
        color: metric === "vwc" ? "#007b83" : "#b87012",
        previous: true,
        points:
          loaded.previous.series.find(
            (s) => s.entityId === loaded.previousZone![`${metric}_sensor`],
          )?.points || [],
        start: loaded.previousRun.start_date,
        zone: loaded.previousRun.time_zone,
      });
  }
  const extrema = (metric: "vwc" | "ec") =>
    lines
      .filter((l) => l.metric === metric)
      .flatMap((l) => l.points.flatMap((p) => (p.value === null ? [] : [p.value])))
      .concat(targets[metric] === null ? [] : [targets[metric]!])
      .concat((dailyTarget?.[metric] || []).flatMap((p) => (p.value === null ? [] : [p.value])));
  const vValues = extrema("vwc"),
    eValues = extrema("ec");
  const vMin = Math.min(0, ...vValues),
    vMax = Math.max(100, ...vValues),
    eMin = Math.min(0, ...eValues),
    eMax = Math.max(6, ...eValues);
  const x = (age: number) => 58 + ((age - first) / (last - first)) * 780;
  const y = (value: number, metric: "vwc" | "ec") =>
    260 -
    ((value - (metric === "vwc" ? vMin : eMin)) /
      ((metric === "vwc" ? vMax : eMax) - (metric === "vwc" ? vMin : eMin))) *
      220;
  const path = (line: (typeof lines)[number]) => {
    let open = false;
    return line.points
      .map((point) => {
        if (point.value === null) {
          open = false;
          return "";
        }
        const age = ageAt(point.time, line.start, line.zone);
        if (age < first || age > last) {
          open = false;
          return "";
        }
        const command = open ? "L" : "M";
        open = true;
        return `${command}${x(age).toFixed(2)},${y(point.value, line.metric).toFixed(2)}`;
      })
      .join(" ");
  };
  const targetPath = (points: NonNullable<typeof dailyTarget>["vwc"], metric: "vwc" | "ec") => {
    let open = false;
    return points
      .map((point) => {
        if (
          point.value === null ||
          !Number.isFinite(point.value) ||
          point.age < first ||
          point.age > last
        ) {
          open = false;
          return "";
        }
        const command = open ? "L" : "M";
        open = true;
        return `${command}${x(point.age).toFixed(2)},${y(point.value, metric).toFixed(2)}`;
      })
      .join(" ");
  };
  const sparse = (line: (typeof lines)[number]) =>
    line.points
      .filter(
        (point, index) =>
          point.value !== null &&
          (index === 0 || line.points[index - 1].value === null) &&
          (index === line.points.length - 1 || line.points[index + 1].value === null),
      )
      .slice(0, 1600);
  const hasPoints = lines.some((line) => line.points.some((p) => p.value !== null));
  return (
    <section className="panel comparison-chart">
      <div className="panel-heading">
        <div>
          <h2>Recorded VWC and EC</h2>
          <p>
            Both runs use elapsed grow days. Each local day is aligned as a fraction of its actual
            duration, including DST.
          </p>
        </div>
      </div>
      {!hasPoints && (
        <p className="comparison-notice">
          No retained measured readings in this range. Any dotted curve below is only the selected
          planning reference.
        </p>
      )}
      {!hasPoints && !dailyTarget?.vwc.length && !dailyTarget?.ec.length ? (
        <Empty
          title="No history in this range"
          tip={<UiTip copyKey="no retained history in this range" />}
          detail="No curve has been invented. Check Recorder retention, sensor inclusion and the selected dates."
        />
      ) : (
        <svg
          viewBox="0 0 900 310"
          role="img"
          aria-label="VWC and EC by age"
        >
          <text x="58" y="18">
            VWC (%) · left
          </text>
          <text x="838" y="18" textAnchor="end">
            EC (mS/cm) · right
          </text>
          {[0, 0.25, 0.5, 0.75, 1].map((f) => (
            <g key={f}>
              <line
                x1="58"
                x2="838"
                y1={260 - f * 220}
                y2={260 - f * 220}
                className="comparison-grid"
              />
              <text x="50" y={264 - f * 220} textAnchor="end">
                {(vMin + f * (vMax - vMin)).toFixed(0)}
              </text>
              <text x="847" y={264 - f * 220}>
                {(eMin + f * (eMax - eMin)).toFixed(1)}
              </text>
            </g>
          ))}
          {[0, 0.25, 0.5, 0.75, 1].map((f) => (
            <text key={f} x={58 + f * 780} y="284" textAnchor="middle">
              Day {(1 + first + f * (last - first)).toFixed(last - first > 10 ? 0 : 1)}
            </text>
          ))}
          {lines.map((line) => (
            <path
              data-comparison-series={`${line.previous ? "previous" : "current"}-${line.metric}`}
              key={line.name}
              d={path(line)}
              fill="none"
              stroke={line.color}
              strokeWidth={line.previous ? 1.6 : 2.2}
              strokeDasharray={line.previous ? "6 3" : undefined}
            >
              <title>
                {line.name}: retained sensor readings; gaps over 30 minutes remain disconnected
              </title>
            </path>
          ))}
          {lines.flatMap((line) =>
            sparse(line).map((point) => {
              const age = ageAt(point.time, line.start, line.zone);
              return age >= first && age <= last ? (
                <circle
                  key={`${line.name}-${point.time}`}
                  cx={x(age)}
                  cy={y(point.value!, line.metric)}
                  r={2.2}
                  fill={line.color}
                >
                  <title>
                    {line.name}: isolated retained reading {point.value}
                  </title>
                </circle>
              ) : null;
            }),
          )}
          {dailyTarget &&
            (["vwc", "ec", "floor"] as const).map((metric) => (
              <path
                key={metric}
                data-comparison-series={`target-${metric}`}
                d={targetPath(dailyTarget[metric], metric === "ec" ? "ec" : "vwc")}
                fill="none"
                stroke={metric === "ec" ? "#ba4783" : metric === "floor" ? "#b87012" : "#007b83"}
                strokeDasharray={metric === "floor" ? "2 6" : "3 5"}
                strokeWidth="1.8"
              >
                <title>
                  {label}: {metric.toUpperCase()} schematic, not measured or as-operated targets
                </title>
              </path>
            ))}
          {(["vwc", "ec"] as const).map(
            (metric) =>
              targets[metric] !== null && (
                <line
                  data-comparison-series={`target-${metric}`}
                  key={metric}
                  x1="58"
                  x2="838"
                  y1={y(targets[metric]!, metric)}
                  y2={y(targets[metric]!, metric)}
                  stroke={metric === "vwc" ? "#03a9f4" : "#e86aa5"}
                  strokeDasharray="2 6"
                  strokeWidth="1.5"
                >
                  <title>
                    {label}: {metric.toUpperCase()} reference {targets[metric]}
                  </title>
                </line>
              ),
          )}
        </svg>
      )}
      <div className="comparison-legend">
        {lines.map((line) => (
          <span key={line.name}>
            <i style={{ background: line.color }} />
            {line.name}
            {line.previous ? " · dashed" : " · solid"}
          </span>
        ))}
        <span>Fine dotted lines: reference targets; amber dotted: emergency floor</span>
      </div>
      <p className="small">
        Target lines are a selected reference, not a record of targets used during either run.
        Unavailable readings and gaps over 30 minutes break the lines. Long continuous spans retain
        extrema. Buckets containing gaps can omit readings to avoid false connections; the table
        retains raw numeric extrema. Isolated readings appear as dots.
      </p>
    </section>
  );
}
export function ComparisonSummary({ loaded, monthly }: { loaded: Loaded; monthly: boolean }) {
  const dates = new Set<string>();
  const values = (
    history: HistoryWindow | null,
    zone: RunZone | null,
    metric: "vwc" | "ec",
    previous = false,
  ) => {
    const rows =
      history?.series.find((s) => s.entityId === zone?.[`${metric}_sensor`])?.daily || [];
    const aligned =
      previous && loaded.currentRun && loaded.previousRun
        ? rows.map((row) => ({
            ...row,
            date: addDays(
              loaded.currentRun!.start_date,
              daysBetween(loaded.previousRun!.start_date, row.date),
            ),
          }))
        : rows;
    const merged = mergeDaily(aligned, monthly);
    merged.forEach((row) => dates.add(row.date));
    return new Map(merged.map((row) => [row.date, row]));
  };
  const currentV = values(loaded.current, loaded.zone, "vwc"),
    currentE = values(loaded.current, loaded.zone, "ec"),
    previousV = values(loaded.previous, loaded.previousZone, "vwc", true),
    previousE = values(loaded.previous, loaded.previousZone, "ec", true);
  // Every range on one scale per measurement, as the chart's axes: VWC to 100 %, EC to 6 or more.
  const ecMax = Math.max(6, ...[...currentE.values(), ...previousE.values()].map((row) => row.max));
  const cell = (row: ReturnType<typeof currentV.get>, metric: "vwc" | "ec", previous = false) =>
    row ? (
      <>
        {`${format(row.min)}–${format(row.max)} (${row.records})`}
        <Meter
          from={row.min}
          value={row.max}
          max={metric === "vwc" ? 100 : ecMax}
          tone={previous ? "muted" : "normal"}
          label={`${previous ? "Previous run " : ""}${metric === "vwc" ? "VWC" : "EC"} from ${format(row.min)} to ${format(row.max)}`}
        />
      </>
    ) : (
      "—"
    );
  return (
    <section className="panel">
      <h2>{monthly ? "Monthly" : "Daily"} recorded ranges</h2>
      <p className="small">
        Min–max with retained state-change count in brackets; these are not time-weighted averages
        or water totals. Previous rows align by grow day into the current run's calendar. Missing
        rows do not prove continuous coverage.
      </p>
      <div
        className="comparison-table"
        tabIndex={0}
        aria-label="Recorded range summary"
      >
        <table className="data-table">
          <thead>
            <tr>
              <th>
                {monthly ? "Month" : "Date"} · {loaded.timeZone}
              </th>
              <th>VWC %</th>
              <th>EC mS/cm</th>
              {loaded.previous && (
                <>
                  <th>Previous VWC %</th>
                  <th>Previous EC mS/cm</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {[...dates].sort().map((date) => (
              <tr key={date}>
                <td>{date}</td>
                <td>{cell(currentV.get(date), "vwc")}</td>
                <td>{cell(currentE.get(date), "ec")}</td>
                {loaded.previous && (
                  <>
                    <td>{cell(previousV.get(date), "vwc", true)}</td>
                    <td>{cell(previousE.get(date), "ec", true)}</td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!dates.size && <p>No recorded values available to summarize.</p>}
    </section>
  );
}

const METRICS: {
  metric: CalloutMetric;
  title: string;
  unit: () => string;
  band: ((stage: Stage) => [number, number]) | null;
  tick: (value: number, digits: number) => string;
}[] = [
  {
    metric: "vwc",
    title: "VWC, daily mean",
    unit: () => "%",
    band: null,
    tick: (v, d) => `${v.toFixed(d)}%`,
  },
  {
    metric: "dryback",
    title: "Overnight dryback",
    unit: () => "VWC points lost lights-off",
    band: (stage) => stage.drybackPoints,
    tick: (v, d) => v.toFixed(d),
  },
  {
    metric: "pore_ec",
    title: "Pore EC, daily mean",
    unit: () => formatEc(1, 0).split(" ").slice(1).join(" "),
    band: (stage) => stage.poreEc,
    tick: (v, d) => formatEc(v, d).split(" ")[0],
  },
  {
    metric: "water",
    title: "Water per plant",
    unit: () => (getDisplayUnits().volume === "gal" ? "gallons a day" : "litres a day"),
    band: null,
    tick: (v, d) => formatVolume(v, d),
  },
];
/** A run keeps its colour while others are ticked and unticked: its card's place. */
const runColour = (index: number) => `var(--rw-run-${Math.min(index, 3)})`;
const STAGE_COLOURS = ["#2f6fb5", "#6450b0", "#7a8aa8"];
const MAX_TICKED = 3;
function niceStep(range: number) {
  const raw = range / 4 || 1;
  const power = 10 ** Math.floor(Math.log10(raw));
  const m = raw / power;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * power;
}
const percent = (x: number) => `${(x * 100).toFixed(3)}%`;
const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
const kg = (grams: number) => `${Number((grams / 1000).toFixed(3))} kg`;
/** A calendar date ("2026-09-15") as "Tue 15 Sep". */
const dateText = (date: string) => dayLabel(Date.parse(date + "T12:00:00Z"), "UTC");

/** One small multiple: each ticked run's daily line, the plan's band stage by stage where the
 * stage arc has one, today's line, and the chart's one callout with the box it was measured over. */
function RunChart({
  spec,
  runs,
  colours,
  stages,
  maxDay,
  today,
}: {
  spec: (typeof METRICS)[number];
  runs: ComparedRun[];
  colours: Map<string, string>;
  stages: Stage[];
  maxDay: number;
  today: number | null;
}) {
  const values = runs.flatMap((r) => (r.days[spec.metric] ?? []).map((d) => d.value));
  const bands = spec.band ? stages.map((s) => ({ stage: s, range: spec.band!(s) })) : [];
  const unit = spec.unit();
  const header = (
    <header>
      <h2>{spec.title}</h2>
      <span>{unit}</span>
      {!!bands.length && (
        <span className="rc-band-key">
          <i aria-hidden="true" />
          Plan target
        </span>
      )}
    </header>
  );
  if (!values.length)
    return (
      <section className="rc-chart" aria-label={spec.title} data-compare-chart={spec.metric}>
        {header}
        <p className="rc-empty">No grow-day summary of the ticked runs has this. Nothing is drawn in its place.</p>
      </section>
    );
  const callout = runCallout(spec.metric, runs, stages);
  const all = [...values, ...bands.flatMap((b) => b.range)];
  const step = niceStep(Math.max(...all) - Math.min(...all));
  const lo = Math.floor(Math.min(...all) / step) * step;
  const hi = Math.max(Math.ceil(Math.max(...all) / step) * step, lo + step);
  const digits = Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 1e6; v += step) ticks.push(Number(v.toFixed(6)));
  const x = (day: number) => (maxDay > 1 ? (day - 1) / (maxDay - 1) : 0);
  const y = (v: number) => 1 - (v - lo) / (hi - lo);
  const path = (points: { day: number; value: number }[]) =>
    points
      .map(
        (p, i) =>
          `${i && points[i - 1].day === p.day - 1 ? "L" : "M"}${(x(p.day) * 1000).toFixed(1)} ${(y(p.value) * 100).toFixed(2)}`,
      )
      .join("");
  let box = null;
  if (callout) {
    const { fromDay, toDay } = callout.box;
    const inside = runs.flatMap((r) =>
      (r.days[spec.metric] ?? []).filter((d) => d.day >= fromDay && d.day <= toDay).map((d) => d.value),
    );
    const pad = (hi - lo) * 0.04;
    box = {
      left: percent(Math.max(0, x(fromDay) - 0.008)),
      width: percent(x(toDay) - x(fromDay) + 0.016),
      top: percent(y(Math.max(...inside) + pad)),
      height: percent(y(Math.min(...inside) - pad) - y(Math.max(...inside) + pad)),
    };
  }
  const axis = [1];
  for (let d = 15; d <= maxDay - 5; d += 14) axis.push(d);
  if (maxDay > 1) axis.push(maxDay);
  const summary = `${spec.title} by day of flower: ${runs.map((r) => r.name).join(", ")}.${callout ? " " + callout.text : ""}`;
  return (
    <section className="rc-chart" aria-label={spec.title} data-compare-chart={spec.metric}>
      {header}
      <p className="rc-callout" data-callout="" hidden={!callout}>
        {callout?.text}
      </p>
      <div className="rc-plot" role="img" aria-label={summary}>
        {ticks.map((t) => (
          <span key={t} className="rc-tick" style={{ top: percent(y(t)) }}>
            <span>{spec.tick(t, digits)}</span>
          </span>
        ))}
        {bands.map(({ stage, range }) => (
          <span
            key={stage.name}
            className="rc-band"
            style={{
              left: percent(x(stage.first)),
              width: percent(x(Math.min(stage.last, maxDay)) - x(stage.first)),
              top: percent(y(range[1])),
              height: percent(y(range[0]) - y(range[1])),
            }}
          />
        ))}
        {today !== null && today <= maxDay && <span className="rc-today" style={{ left: percent(x(today)) }} />}
        <svg viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true">
          {[...runs].reverse().map((run) => (
            <path
              key={run.id}
              d={path(run.days[spec.metric] ?? [])}
              data-run-line={run.id}
              fill="none"
              stroke={colours.get(run.id)}
              strokeWidth={run.current ? 3 : 2}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
        {box && <span className="rc-box" data-callout-box="" style={box} />}
        <div className="rc-stages" aria-hidden="true">
          {stages.map((s, i) => (
            <span
              key={s.name}
              style={{
                left: percent(x(s.first)),
                width: percent(x(Math.min(s.last, maxDay)) - x(s.first)),
                background: STAGE_COLOURS[i % 3],
              }}
            />
          ))}
        </div>
        <div className="rc-axis" aria-hidden="true">
          {axis.map((d) => (
            <span key={d} style={{ left: percent(x(d)) }} data-edge={d === 1 ? "start" : d === maxDay ? "end" : undefined}>
              Day {d}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

/** History › Compare runs, room-wide (mockup 11): a card per run with what it ended with, up to
 * three runs ticked, and four small multiples of whole-room daily values from the room's grow-day
 * summaries, each with one callout where two runs differ past the metric's floor. A finished run
 * without a harvest result takes its dry weight here, through review and apply. */
export function RunCompare({ controller, runs }: { controller: Controller; runs: RunsDocument | null }) {
  const [growDays, setGrowDays] = useState<GrowDaysDocument | null>(null),
    [harvests, setHarvests] = useState<HarvestsDocument | null>(null),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0);
  const [ticked, setTicked] = useState<string[] | null>(null),
    [limit, setLimit] = useState<string | null>(null);
  const [adding, setAdding] = useState<{ runId: string; kg: string } | null>(null),
    [saved, setSaved] = useState<{ runId: string; grams: number; receipt: ApplyReceipt } | null>(null);
  useEffect(() => {
    let live = true;
    setError("");
    Promise.all([
      controller.operator<GrowDaysDocument>("grow_days_get"),
      controller.operator<HarvestsDocument>("harvests_get"),
    ])
      .then(([days, h]) => {
        if (!live) return;
        setGrowDays(days);
        setHarvests(h);
      })
      .catch((e) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [controller.roomId, controller.operator, reload]);
  useEffect(() => {
    setTicked(null);
    setAdding(null);
    setSaved(null);
    setLimit(null);
  }, [controller.roomId]);
  const doc = runs?.room_id === controller.roomId ? runs : null;
  const open = (doc?.runs ?? []).filter((run) => !run.archived);
  const current = open.find((run) => !run.end_date) ?? null;
  const cards = [
    ...(current ? [current] : []),
    ...open.filter((run) => run !== current).sort((a, b) => b.start_date.localeCompare(a.start_date)),
  ];
  const chosen = (ticked ?? cards.slice(0, MAX_TICKED).map((run) => run.id)).filter((id) =>
    cards.some((run) => run.id === id),
  );
  const colours = new Map(cards.map((run, i) => [run.id, runColour(i)]));
  const cardKey = JSON.stringify(cards.map((r) => [r.id, r.name, r.start_date, r.end_date]));
  const compared = useMemo(
    () =>
      cards
        .filter((run) => chosen.includes(run.id))
        .map((run) => comparedRun(run, growDays?.days ?? [], run === current)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cardKey, chosen.join(), growDays],
  );
  // The arc as long as the longest finished ticked run, else the guide's nominal flower.
  const lengths = cards
    .filter((run) => chosen.includes(run.id) && run.end_date)
    .map((run) => daysBetween(run.start_date, run.end_date!) + 1);
  const stages = stageArc(lengths.length ? Math.max(...lengths) : NOMINAL_FLOWER_DAYS);
  const dataDays = compared.flatMap((r) => Object.values(r.days).flatMap((d) => (d ?? []).map((p) => p.day)));
  const maxDay = Math.max(stages.at(-1)?.last ?? 1, ...dataDays);
  const todayKey = current ? dayKey(Date.now(), current.time_zone) : null;
  const today = current && todayKey ? daysBetween(current.start_date, todayKey) + 1 : null;
  const leftState = controller.states[`sensor.crop_steering_${controller.room.room.prefix}days_to_harvest`]?.state;
  const left = leftState === undefined || leftState === "" ? NaN : Number(leftState);
  const harvestDue = todayKey && Number.isInteger(left) && left >= 0 ? addDays(todayKey, left) : null;

  function toggle(id: string, name: string) {
    if (chosen.includes(id)) {
      setTicked(chosen.filter((x) => x !== id));
      setLimit(null);
    } else if (chosen.length >= MAX_TICKED) setLimit(name);
    else {
      setTicked([...chosen, id]);
      setLimit(null);
    }
  }
  const addingRun = adding ? cards.find((run) => run.id === adding.runId) : undefined;
  const grams = adding && /^\d+(\.\d{1,3})?$/.test(adding.kg.trim()) ? Math.round(Number(adding.kg) * 1000) : null;
  const rows: ReviewRow[] =
    addingRun && grams !== null && grams > 0
      ? [{ id: "dry", label: `${addingRun.name} dry weight`, before: "none", after: kg(grams) }]
      : [];
  /** Saves the dry weight and reads it back from the harvests the service answers with. */
  async function saveHarvest(): Promise<ApplyReceipt> {
    const run = addingRun!,
      written = grams!;
    const answer = await controller.operator<HarvestsDocument>("runs_set_harvest", {
      run_id: run.id,
      expected_revision: harvests!.revision,
      harvest: {
        harvest_date: run.end_date,
        room: { dry_weight_g: written, wet_weight_g: null, plants_harvested: null, canopy_m2: null },
        zones: {},
        plants: [],
        quality: null,
        notes: null,
        lab: { thc_pct: null, terpenes: {} },
      },
    });
    setHarvests(answer);
    const held = answer.harvests[run.id]?.room?.dry_weight_g ?? null;
    const receipt: ApplyReceipt =
      held === written
        ? { at: Date.now(), ok: true, failed: [], summary: `${rows[0].label} none → ${kg(written)}`, eventIds: [] }
        : {
            at: Date.now(),
            ok: false,
            failed: [{ id: "dry", holds: held === null ? "none" : kg(held) }],
            summary: "",
            eventIds: [],
          };
    setSaved({ runId: run.id, grams: written, receipt });
    if (receipt.ok) setAdding(null);
    return receipt;
  }
  /** Takes the harvest result back out, only while it is still the one saved here. */
  async function undoHarvest() {
    const { runId, grams: written } = saved!;
    const now = await controller.operator<HarvestsDocument>("harvests_get");
    const stored = now.harvests[runId];
    if (!stored || stored.room?.dry_weight_g !== written) {
      setHarvests(now);
      throw new Error("The harvest result changed since it was saved here. Reload and check before trying again.");
    }
    setHarvests(
      await controller.operator<HarvestsDocument>("runs_set_harvest", {
        run_id: runId,
        expected_revision: now.revision,
        harvest: null,
      }),
    );
  }

  if (!doc || !cards.length) return null;
  return (
    <section className="run-compare" aria-label="Runs side by side" data-run-compare="">
      <div className="rc-head">
        <p className="rc-scope">{controller.room.room.name} · whole-room daily values</p>
        <label htmlFor="rc-align">Line runs up by</label>
        <select id="rc-align" defaultValue="flower">
          <option value="flower">Day of flower</option>
          <option value="run" disabled>
            Day of run (no clone dates recorded)
          </option>
        </select>
      </div>
      <div className="rc-cards" role="group" aria-label="Runs to compare, up to three">
        {cards.map((run) => {
          const on = chosen.includes(run.id);
          const result = runResult(run, harvests?.harvests[run.id], run === current ? harvestDue : null);
          return (
            <div key={run.id} className="rc-card" data-run-card={run.id} data-on={on ? "" : undefined}>
              <span className="rc-card-top">
                <label className="rc-tick-run">
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={run === current}
                    onChange={() => toggle(run.id, run.name)}
                  />
                  <i aria-hidden="true" style={{ background: colours.get(run.id) }} />
                  {run.name}
                  {run === current ? " · this run" : ""}
                </label>
                <span className="rc-dates">from {dateText(run.start_date)}</span>
              </span>
              <span className="rc-result" data-missing={result.missing ? "" : undefined}>
                {harvests ? result.text : error ? "Harvest results could not load" : "Reading harvest results…"}
              </span>
              {harvests && result.missing && adding?.runId !== run.id && (
                <Button variant="outline" size="sm" onClick={() => setAdding({ runId: run.id, kg: "" })}>
                  Add harvest result
                </Button>
              )}
              {adding?.runId === run.id && (
                <span className="rc-add">
                  <label htmlFor={`rc-kg-${run.id}`}>Dry kg</label>
                  <Input
                    id={`rc-kg-${run.id}`}
                    inputMode="decimal"
                    autoFocus
                    value={adding.kg}
                    onChange={(e) => setAdding({ runId: run.id, kg: e.target.value })}
                  />
                </span>
              )}
            </div>
          );
        })}
      </div>
      {limit && (
        <p className="rc-limit" role="status">
          Three runs is the most that stays readable. Untick one to add {limit}.
        </p>
      )}
      {(addingRun || saved) && (
        <ReviewApply
          layout="panel"
          rows={rows}
          applyLabel={addingRun ? `Save to ${addingRun.name}` : undefined}
          discardLabel="Cancel"
          apply={saveHarvest}
          onDiscard={() => setAdding(null)}
          last={saved?.receipt ?? null}
          onReload={() => setReload((n) => n + 1)}
          timeZone={controller.timeZone}
          undo={undoHarvest}
        />
      )}
      {error && (
        <p className="comparison-notice" role="alert">
          {error}
        </p>
      )}
      <div className="rc-grid">
        {METRICS.map((spec) => (
          <RunChart
            key={spec.metric}
            spec={spec}
            runs={compared}
            colours={colours}
            stages={stages}
            maxDay={maxDay}
            today={current && chosen.includes(current.id) ? today : null}
          />
        ))}
      </div>
      <div className="rc-legend">
        {stages.map((s, i) => (
          <span key={s.name}>
            <i aria-hidden="true" style={{ background: STAGE_COLOURS[i % 3] }} />
            {capital(stageWord(s.name))} · days {s.first}–{s.last}
          </span>
        ))}
        {today !== null && (
          <span>
            <i aria-hidden="true" className="rc-today-key" />
            Today, day {today} of this run
          </span>
        )}
      </div>
    </section>
  );
}
