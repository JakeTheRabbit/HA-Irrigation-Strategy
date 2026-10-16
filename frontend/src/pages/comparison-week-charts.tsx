import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { number } from "@/components/dashboard";
import {
  chartRows,
  chartSummary,
  type ChartKey,
  type ChartRow,
  type RunWeek,
} from "@/lib/run-weeks";

export interface ChartRun {
  name: string;
  weeks: RunWeek[];
}

/** The run's line or bar colour: comparison.css sets each per theme. */
const colour = (run: number) => `var(--rw-run-${Math.min(run, 3)})`;
const tooltipStyle = {
  background: "var(--surface)",
  color: "var(--foreground)",
  border: "1px solid var(--border)",
  borderRadius: 8,
};

interface Spec {
  id: string;
  title: string;
  /** What a line pair means, under the title. */
  detail: string;
  unit: string;
  digits: number;
  /** Digits on the axis: whole shots, two places of a litre. */
  tickDigits: number;
  /** One line per run, or a solid (high) and a dotted (low) line per run. */
  keys: readonly ChartKey[];
  bars?: boolean;
  /** The summary reads this key. */
  summary: ChartKey;
  zero: boolean;
}
const LINE: Partial<Record<ChartKey, string>> = {
  peak: "peak",
  trough: "trough",
  ecHigh: "high",
  ecLow: "low",
};
const SPECS: Spec[] = [
  {
    id: "moisture",
    title: "Moisture",
    detail: "Each week’s typical daily peak (solid) and trough (dotted), in %.",
    unit: " %",
    digits: 0,
    tickDigits: 0,
    keys: ["peak", "trough"],
    summary: "peak",
    zero: false,
  },
  {
    id: "dryback",
    title: "Dryback",
    detail: "The drop from the typical day’s peak to its trough, as a percentage of the peak.",
    unit: " %",
    digits: 0,
    tickDigits: 0,
    keys: ["dryback"],
    bars: true,
    summary: "dryback",
    zero: true,
  },
  {
    id: "pore-ec",
    title: "Pore EC",
    detail: "Each week’s typical daily high (solid) and low (dotted), in mS/cm.",
    unit: "",
    digits: 1,
    tickDigits: 1,
    keys: ["ecHigh", "ecLow"],
    summary: "ecHigh",
    zero: false,
  },
  {
    id: "water",
    title: "Water per plant a day",
    detail: "Litres, averaged over the week’s recorded grow-days.",
    unit: " L",
    digits: 2,
    tickDigits: 2,
    keys: ["water"],
    summary: "water",
    zero: true,
  },
  {
    id: "shots",
    title: "Shots a day",
    detail: "Shots, averaged over the week’s recorded grow-days.",
    unit: "",
    digits: 1,
    tickDigits: 0,
    keys: ["shots"],
    summary: "shots",
    zero: true,
  },
];

function Chart({ spec, runs, rows }: { spec: Spec; runs: ChartRun[]; rows: ChartRow[] }) {
  const recorded = runs.some((_, run) =>
    rows.some((row) => spec.keys.some((key) => row[`r${run}_${key}`] !== null)),
  );
  const summary = chartSummary(spec.title, runs, spec.summary, spec.unit, spec.digits);
  const axis = {
    tickLine: false,
    axisLine: false,
    stroke: "var(--muted-foreground)",
  } as const;
  const grid = <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="var(--border)" />;
  const x = <XAxis dataKey="label" {...axis} interval="preserveStartEnd" minTickGap={4} />;
  const y = (
    <YAxis
      {...axis}
      width={44}
      domain={spec.zero ? [0, "auto"] : ["auto", "auto"]}
      allowDecimals={spec.tickDigits > 0}
      tickFormatter={(value) => number(Number(value), spec.tickDigits)}
    />
  );
  const tooltip = (
    <Tooltip
      contentStyle={tooltipStyle}
      itemStyle={{ color: "var(--foreground)" }}
      cursor={spec.bars ? { fill: "var(--muted)" } : { stroke: "var(--border)" }}
      labelFormatter={(label) => `Grow week ${String(label).slice(1)}`}
      formatter={(value, name) => [
        value === null || value === undefined
          ? "—"
          : `${number(Number(value), spec.digits)}${spec.unit}`,
        name,
      ]}
    />
  );
  const name = (run: number, key: ChartKey) =>
    spec.keys.length > 1 ? `${runs[run].name} · ${LINE[key]}` : runs[run].name;
  // A long run scrolls sideways at phone width instead of crushing its weeks together.
  const minWidth = `max(100%, ${rows.length * (spec.bars ? runs.length * 0.9 + 0.8 : 1.9)}rem)`;
  let chart: ReactNode;
  if (spec.bars)
    chart = (
      <BarChart
        data={rows}
        margin={{ top: 8, right: 6, bottom: 0, left: 0 }}
        accessibilityLayer={false}
      >
        {grid}
        {x}
        {y}
        {tooltip}
        {runs.map((_, run) => (
          <Bar
            key={run}
            dataKey={`r${run}_${spec.keys[0]}`}
            name={name(run, spec.keys[0])}
            fill={colour(run)}
            radius={[3, 3, 0, 0]}
            maxBarSize={22}
            isAnimationActive={false}
          />
        ))}
      </BarChart>
    );
  else
    chart = (
      <LineChart
        data={rows}
        margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
        accessibilityLayer={false}
      >
        {grid}
        {x}
        {y}
        {tooltip}
        {runs.flatMap((_, run) =>
          spec.keys.map((key, index) => (
            <Line
              key={`${run}-${key}`}
              dataKey={`r${run}_${key}`}
              name={name(run, key)}
              type="linear"
              stroke={colour(run)}
              strokeWidth={index ? 1.6 : 2.2}
              strokeDasharray={index ? "2 4" : undefined}
              dot={{ r: index ? 2 : 3, fill: colour(run), strokeWidth: 0 }}
              activeDot={{ r: 4 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          )),
        )}
      </LineChart>
    );
  return (
    <figure className="rw-chart" data-rw-chart={spec.id} aria-labelledby={`rw-chart-${spec.id}`}>
      <figcaption>
        <h3 id={`rw-chart-${spec.id}`}>{spec.title}</h3>
        <p>{spec.detail}</p>
      </figcaption>
      {recorded ? (
        <div
          className="rw-chart-scroll"
          tabIndex={0}
          role="region"
          aria-label={`${spec.title} chart`}
        >
          <div className="rw-chart-plot" role="img" aria-label={summary} style={{ minWidth }}>
            <ResponsiveContainer width="100%" height="100%">
              {chart}
            </ResponsiveContainer>
          </div>
        </div>
      ) : (
        <p className="rw-chart-empty" role="note">
          No record of this for {runs.length > 1 ? "either run" : "this run"}. Nothing is drawn in
          its place.
        </p>
      )}
    </figure>
  );
}

/** Compare runs, by grow week: each run's weeks as lines on one chart per measure, and its dryback
 * as bars. The table under them keeps the figures. */
export function RunWeekCharts({ runs }: { runs: ChartRun[] }) {
  const rows = chartRows(runs.map((run) => run.weeks));
  if (!rows.length) return null;
  return (
    <section className="rw-charts" aria-label="Charts by grow week">
      <div className="rw-chart-key" aria-hidden="true">
        {runs.map((run, index) => (
          <span key={index}>
            <i style={{ background: colour(index) }} />
            {run.name}
          </span>
        ))}
      </div>
      <div className="rw-chart-grid">
        {SPECS.map((spec) => (
          <Chart key={spec.id} spec={spec} runs={runs} rows={rows} />
        ))}
      </div>
    </section>
  );
}
