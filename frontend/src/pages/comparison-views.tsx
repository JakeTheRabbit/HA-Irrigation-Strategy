import type { ComparisonTarget } from "@/lib/comparison-target";
import { Empty } from "@/components/dashboard";
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
          <h2>Recorded moisture & EC</h2>
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
          title="No retained history in this range"
          detail="No curve has been invented. Check Recorder retention, sensor inclusion and the selected dates."
        />
      ) : (
        <svg
          viewBox="0 0 900 310"
          role="img"
          aria-label="Recorded VWC and EC compared by grow age, with separate reference target lines"
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
  const cell = (row: ReturnType<typeof currentV.get>) =>
    row ? `${format(row.min)}–${format(row.max)} (${row.records})` : "—";
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
        aria-label="Recorded range summary, scroll for more dates"
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
                <td>{cell(currentV.get(date))}</td>
                <td>{cell(currentE.get(date))}</td>
                {loaded.previous && (
                  <>
                    <td>{cell(previousV.get(date))}</td>
                    <td>{cell(previousE.get(date))}</td>
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
