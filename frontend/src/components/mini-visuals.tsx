import type { Reading } from "@/lib/dryback";
import "./mini-visuals.css";

export type Tone = "normal" | "high" | "over";

const share = (value: number | null, max: number) =>
  value === null || !(max > 0) ? 0 : Math.max(0, Math.min(100, (value / max) * 100));

export interface MiniBar {
  id: string;
  label: string;
  value: number | null;
  title: string;
  tone?: Tone;
}

/** One small vertical bar per zone, labelled with the zone's number. */
export function MiniBars({ bars, max, label }: { bars: MiniBar[]; max: number; label: string }) {
  return (
    <div className="mini-bars" role="img" aria-label={label}>
      {bars.map((bar) => (
        <span className="mini-bar" key={bar.id} title={bar.title}>
          <span className="mini-bar-track">
            <span
              className="mini-bar-fill"
              data-tone={bar.tone ?? "normal"}
              style={{ height: `${share(bar.value, max)}%` }}
            />
          </span>
          <span className="mini-bar-label">{bar.label}</span>
        </span>
      ))}
    </div>
  );
}

/** A slim horizontal bar filled to `value` of `max`, with an optional marker line at `mark`. */
export function Meter({
  value,
  max,
  mark,
  tone = "normal",
  label,
}: {
  value: number;
  max: number;
  mark?: number | null;
  tone?: Tone;
  label: string;
}) {
  return (
    <span className="meter" role="img" aria-label={label}>
      <span className="meter-fill" data-tone={tone} style={{ width: `${share(value, max)}%` }} />
      {mark !== null && mark !== undefined && Number.isFinite(mark) && (
        <span className="meter-mark" style={{ left: `${share(mark, max)}%` }} />
      )}
    </span>
  );
}

/** A line of recent readings, scaled to their own range. */
export function Sparkline({
  points,
  label,
  width = 72,
  height = 22,
}: {
  points: Reading[];
  label: string;
  width?: number;
  height?: number;
}) {
  if (points.length < 2) return null;
  const t0 = points[0].time,
    span = points.at(-1)!.time - t0 || 1;
  const values = points.map((point) => point.value);
  const lo = Math.min(...values),
    hi = Math.max(...values);
  const y = (value: number) =>
    hi === lo ? height / 2 : height - 1.5 - ((value - lo) / (hi - lo)) * (height - 3);
  const path = points
    .map(
      (point, i) =>
        `${i ? "L" : "M"}${(1 + ((point.time - t0) / span) * (width - 2)).toFixed(1)} ${y(point.value).toFixed(1)}`,
    )
    .join(" ");
  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={label}
    >
      <path d={path} />
    </svg>
  );
}
