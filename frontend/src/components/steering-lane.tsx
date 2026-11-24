import type { ReactNode } from "react";
import type { PhaseBand, Reading, Shot, Span } from "@/lib/day-timeline";
import { clock, hourTicks } from "@/lib/time";
import "./steering-lane.css";

const PHASE_NAME: Record<string, string> = { P0: "Hold", P1: "Ramp", P2: "Maintenance", P3: "Dryback" };
const at = (span: Span, time: number) => ((time - span.start) / (span.end - span.start)) * 100;
const pct = (span: Span, time: number) => `${Math.max(0, Math.min(100, at(span, time))).toFixed(2)}%`;

/** The room's clock above its zones: lights-on, the phases, the hours and now. Every lane below
 * shares its axis. */
export function DayRail({
  span,
  lightsOn,
  lightsOff,
  phases,
  now,
  timeZone,
}: {
  span: Span;
  lightsOn: number;
  lightsOff: number;
  phases: PhaseBand[];
  now: number;
  timeZone: string;
}) {
  const nowIn = now > span.start && now < span.end;
  const ticks = [
    span.start,
    ...hourTicks(span.start, span.end, 3, timeZone).filter((t) => t > span.start && t < span.end),
    span.end,
  ].filter(
    (t, i, all) =>
      (!nowIn || Math.abs(t - now) > (span.end - span.start) * 0.05) &&
      // An hour tick too near an edge label would print over it.
      (i === 0 || i === all.length - 1 || Math.min(t - span.start, span.end - t) > (span.end - span.start) * 0.09),
  );
  return (
    <div
      className="day-rail"
      role="img"
      aria-label={`Lights ${clock(lightsOn, timeZone)} to ${clock(lightsOff, timeZone)}${
        phases.length ? `; ${phases.map((p) => `${p.phase} from ${clock(p.start, timeZone)}`).join(", ")}` : ""
      }; now ${clock(now, timeZone)}`}
    >
      <div className="day-rail-track">
        <span className="day-rail-lights" style={{ left: pct(span, lightsOn), width: `${at(span, lightsOff) - at(span, lightsOn)}%` }} />
        {phases.map((p) => (
          <span
            key={`${p.phase}-${p.start}`}
            className="day-rail-phase"
            data-phase={p.phase}
            style={{ left: pct(span, p.start), width: `${Math.max(0, at(span, p.end) - at(span, p.start))}%` }}
          >
            <b>{p.phase}</b> <span className="day-rail-name">{PHASE_NAME[p.phase] ?? ""}</span>
          </span>
        ))}
      </div>
      <div className="day-rail-ticks" aria-hidden="true">
        {ticks.map((t, i) => (
          <span key={t} style={{ left: pct(span, t) }} data-edge={i === 0 ? "start" : i === ticks.length - 1 ? "end" : undefined}>
            {clock(t, timeZone)}
          </span>
        ))}
        {nowIn && (
          <span className="day-rail-now-label" style={{ left: pct(span, now) }}>
            Now
          </span>
        )}
      </div>
      {nowIn && <span className="lane-now" style={{ left: pct(span, now) }} />}
    </div>
  );
}

/** A zone's moisture through the day on the room's axis: its target band labelled in place, the
 * recorded VWC, a tick per shot and now. `readings` null while the recorder has not answered. */
export function VwcLane({
  span,
  readings,
  shots,
  band,
  bandText,
  domain,
  lightsOn,
  lightsOff,
  now,
  flag,
  height,
}: {
  span: Span;
  readings: Reading[] | null;
  shots: Shot[];
  band: [number, number] | null;
  bandText: string | null;
  domain: [number, number];
  lightsOn: number;
  lightsOff: number;
  now: number;
  flag?: { level: "warning" | "critical"; text: ReactNode } | null;
  height?: number;
}) {
  const [lo, hi] = domain;
  const y = (v: number) => 100 - ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * 100;
  const x = (t: number) => at(span, t) * 10;
  const d = (readings ?? [])
    .filter((r) => r.time >= span.start && r.time <= span.end)
    .map((r, i) => `${i ? "L" : "M"}${x(r.time).toFixed(1)},${y(r.value).toFixed(2)}`)
    .join("");
  const nowIn = now > span.start && now < span.end;
  return (
    <div className="vwc-lane" style={height ? { height } : undefined}>
      <div className="vwc-lane-plot">
        <svg viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true">
          <rect className="lane-night" x="0" y="0" width={x(lightsOn)} height="100" />
          <rect className="lane-night" x={x(lightsOff)} y="0" width={Math.max(0, 1000 - x(lightsOff))} height="100" />
          {band && (
            <>
              <rect className="lane-band" x="0" y={y(band[1])} width="1000" height={Math.max(0.5, y(band[0]) - y(band[1]))} />
              <line className="lane-band-edge" x1="0" x2="1000" y1={y(band[1])} y2={y(band[1])} vectorEffect="non-scaling-stroke" />
              <line className="lane-band-edge" x1="0" x2="1000" y1={y(band[0])} y2={y(band[0])} vectorEffect="non-scaling-stroke" />
            </>
          )}
          {d && <path className="lane-vwc" d={d} vectorEffect="non-scaling-stroke" />}
        </svg>
        {band && bandText && (
          <span className="lane-band-label" style={{ top: `${y((band[0] + band[1]) / 2)}%` }}>
            {bandText}
          </span>
        )}
        {readings === null && <span className="lane-loading">Loading today's readings…</span>}
        {nowIn && <span className="lane-now" style={{ left: pct(span, now) }} />}
        {flag && (
          <span
            className="lane-flag"
            data-level={flag.level}
            // After now while there is room; late in the day it ends at now instead.
            style={
              nowIn && at(span, now) > 55
                ? { right: `calc(${(100 - at(span, now)).toFixed(2)}% + 8px)` }
                : { left: `calc(${pct(span, nowIn ? now : span.start)} + 8px)` }
            }
          >
            {flag.text}
          </span>
        )}
      </div>
      <div className="vwc-lane-shots" role="img" aria-label={`${shots.length} shot${shots.length === 1 ? "" : "s"} so far`}>
        {shots.map((s) => (
          <span key={s.start} className="lane-shot" data-open={s.open || undefined} style={{ left: pct(span, s.start) }} />
        ))}
      </div>
    </div>
  );
}

/** One VWC scale for every lane of a room, so the zones compare by eye: the readings and bands,
 * padded, never narrower than ten points. */
export function vwcDomain(values: (number | null)[]): [number, number] {
  const known = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (!known.length) return [30, 80];
  let lo = Math.floor(Math.min(...known) - 3),
    hi = Math.ceil(Math.max(...known) + 3);
  if (hi - lo < 10) {
    const mid = (hi + lo) / 2;
    lo = Math.floor(mid - 5);
    hi = Math.ceil(mid + 5);
  }
  return [Math.max(0, lo), Math.min(100, hi)];
}
