import type { ReactNode } from "react";
import type { PhaseBand, Reading, Shot, Span } from "@/lib/day-timeline";
import { clock, hourTicks } from "@/lib/time";
import { NOW_KEY, type KeyItem } from "./chart-key";
import "./steering-lane.css";

const PHASE_NAME: Record<string, string> = { P0: "Hold", P1: "Ramp", P2: "Maintenance", P3: "Dryback" };
const at = (span: Span, time: number) => ((time - span.start) / (span.end - span.start)) * 100;
const pct = (span: Span, time: number) => `${Math.max(0, Math.min(100, at(span, time))).toFixed(2)}%`;

export type SteeringTone = "vwc" | "ec" | "neutral";

/** A compact horizontal position-vs-band bar shared across All rooms, Room, Zone and Current day:
 * shows where a live value sits relative to its target band or single target, using each series's
 * own calm hue on stock Home Assistant neutral surfaces and warning amber only when out of band. */
export function TargetTrack({
  value,
  band,
  target,
  min,
  max,
  tone = "neutral",
  abnormal = false,
}: {
  value: number | null;
  band?: readonly [number, number] | null;
  target?: number | null;
  min?: number;
  max?: number;
  tone?: SteeringTone;
  abnormal?: boolean;
}) {
  const known = [
    value,
    target ?? null,
    ...(band ?? []),
  ].filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (!known.length || (!band && (target == null || !Number.isFinite(target)))) return null;
  const loKnown = Math.min(...known);
  const hiKnown = Math.max(...known);
  const pad = Math.max((hiKnown - loKnown) * 0.25, hiKnown * 0.06, 0.5);
  const lo = min ?? Math.max(0, loKnown - pad);
  const hi = max ?? hiKnown + pad;
  const span = Math.max(hi - lo, 1e-6);
  const pos = (v: number) => `${Math.max(0, Math.min(100, ((v - lo) / span) * 100)).toFixed(2)}%`;
  const bandLeft = band ? Math.max(0, Math.min(100, ((band[0] - lo) / span) * 100)) : null;
  const bandRight = band ? Math.max(0, Math.min(100, ((band[1] - lo) / span) * 100)) : null;
  return (
    <span
      className="target-track"
      data-tone={tone}
      data-abnormal={abnormal ? "" : undefined}
      aria-hidden="true"
    >
      {bandLeft !== null && bandRight !== null && (
        <span
          className="target-track-band"
          style={{
            left: `${bandLeft.toFixed(2)}%`,
            width: `${Math.max(3, bandRight - bandLeft).toFixed(2)}%`,
          }}
        />
      )}
      {!band && target != null && Number.isFinite(target) && (
        <span className="target-track-mark" style={{ left: pos(target) }} />
      )}
      {value !== null && Number.isFinite(value) && (
        <span className="target-track-pip" style={{ left: pos(value) }} />
      )}
    </span>
  );
}

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
 * recorded VWC with a live endpoint dot, a tick per shot and now. `readings` null while loading. */
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
  abnormal = false,
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
  abnormal?: boolean;
  flag?: { level: "warning" | "critical"; text: ReactNode } | null;
  height?: number;
}) {
  const [lo, hi] = domain;
  const y = (v: number) => 100 - ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * 100;
  const x = (t: number) => at(span, t) * 10;
  const inSpan = (readings ?? []).filter((r) => r.time >= span.start && r.time <= span.end);
  // Break the trace across long probe gaps (> 30 min) instead of drawing a false straight line.
  const d = inSpan
    .map((r, i) => {
      const gap = i > 0 && r.time - inSpan[i - 1].time > 30 * 60_000;
      return `${i && !gap ? "L" : "M"}${x(r.time).toFixed(1)},${y(r.value).toFixed(2)}`;
    })
    .join("");
  const last = inSpan.at(-1) ?? null;
  const nowIn = now > span.start && now < span.end;
  return (
    <div className="vwc-lane" style={height ? { height } : undefined}>
      <div className="vwc-lane-plot">
        <svg viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true">
          <rect className="lane-night" x="0" y="0" width={x(lightsOn)} height="100" />
          <rect className="lane-night" x={x(lightsOff)} y="0" width={Math.max(0, 1000 - x(lightsOff))} height="100" />
          {band && (
            <>
              <rect className="lane-band lane-band-vwc" x="0" y={y(band[1])} width="1000" height={Math.max(0.5, y(band[0]) - y(band[1]))} />
              <line className="lane-band-edge lane-band-edge-vwc" x1="0" x2="1000" y1={y(band[1])} y2={y(band[1])} vectorEffect="non-scaling-stroke" />
              <line className="lane-band-edge lane-band-edge-vwc" x1="0" x2="1000" y1={y(band[0])} y2={y(band[0])} vectorEffect="non-scaling-stroke" />
            </>
          )}
          {d && <path className="lane-vwc" d={d} vectorEffect="non-scaling-stroke" />}
        </svg>
        {last && (
          <span
            className="lane-live-dot"
            data-series="vwc"
            data-abnormal={abnormal ? "" : undefined}
            style={{ left: pct(span, last.time), top: `${y(last.value).toFixed(2)}%` }}
            aria-hidden="true"
          />
        )}
        {band && bandText && (
          <span className="lane-band-label lane-band-label-vwc" style={{ top: `${y((band[0] + band[1]) / 2)}%` }}>
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

/** A zone's pore EC through the day on the exact same room clock as VwcLane: green target band,
 * recorded pore EC curve and live endpoint dot. */
export function EcLane({
  span,
  readings,
  band,
  bandText,
  domain,
  lightsOn,
  lightsOff,
  now,
  abnormal = false,
  height = 38,
}: {
  span: Span;
  readings: Reading[] | null;
  band: [number, number] | null;
  bandText: string | null;
  domain: [number, number];
  lightsOn: number;
  lightsOff: number;
  now: number;
  abnormal?: boolean;
  height?: number;
}) {
  const [lo, hi] = domain;
  const y = (v: number) => 100 - ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * 100;
  const x = (t: number) => at(span, t) * 10;
  const inSpan = (readings ?? []).filter((r) => r.time >= span.start && r.time <= span.end);
  if (readings !== null && inSpan.length === 0) return null;
  const d = inSpan
    .map((r, i) => `${i ? "L" : "M"}${x(r.time).toFixed(1)},${y(r.value).toFixed(2)}`)
    .join("");
  const last = inSpan.at(-1) ?? null;
  const nowIn = now > span.start && now < span.end;
  return (
    <div
      className="ec-lane"
      style={{ height }}
      role="img"
      aria-label={`Pore EC through the day${bandText ? `, ${bandText}` : ""}`}
    >
      <div className="ec-lane-plot">
        <svg viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true">
          <rect className="lane-night" x="0" y="0" width={x(lightsOn)} height="100" />
          <rect className="lane-night" x={x(lightsOff)} y="0" width={Math.max(0, 1000 - x(lightsOff))} height="100" />
          {band && (
            <>
              <rect className="lane-band lane-band-ec" x="0" y={y(band[1])} width="1000" height={Math.max(0.5, y(band[0]) - y(band[1]))} />
              <line className="lane-band-edge lane-band-edge-ec" x1="0" x2="1000" y1={y(band[1])} y2={y(band[1])} vectorEffect="non-scaling-stroke" />
              <line className="lane-band-edge lane-band-edge-ec" x1="0" x2="1000" y1={y(band[0])} y2={y(band[0])} vectorEffect="non-scaling-stroke" />
            </>
          )}
          {d && <path className="lane-ec" d={d} vectorEffect="non-scaling-stroke" />}
        </svg>
        {last && (
          <span
            className="lane-live-dot"
            data-series="ec"
            data-abnormal={abnormal ? "" : undefined}
            style={{ left: pct(span, last.time), top: `${y(last.value).toFixed(2)}%` }}
            aria-hidden="true"
          />
        )}
        {band && bandText && (
          <span className="lane-band-label lane-band-label-ec" style={{ top: `${y((band[0] + band[1]) / 2)}%` }}>
            {bandText}
          </span>
        )}
        {nowIn && <span className="lane-now" style={{ left: pct(span, now) }} />}
      </div>
    </div>
  );
}

/** What one zone's lanes draw, for the room's key. */
export interface LaneMarks {
  vwc: boolean;
  vwcBand: boolean;
  ec: boolean;
  ecBand: boolean;
  shots: boolean;
  flag?: "warning" | "critical" | null;
}

/** What a zone's VwcLane and EcLane draw from the same props (readings null while loading). */
export function laneMarks(
  span: Span,
  vwc: Reading[] | null,
  ec: Reading[] | null,
  shots: Shot[],
  vwcBand: boolean,
  ecBand: boolean,
  flag: LaneMarks["flag"] = null,
): LaneMarks {
  const inSpan = (readings: Reading[]) => readings.some((r) => r.time >= span.start && r.time <= span.end);
  // EcLane is left out when it has no readings in the span; while loading it shows its band alone.
  const ecShown = ec === null || inSpan(ec);
  return { vwc: !!vwc && inSpan(vwc), vwcBand, ec: !!ec && inSpan(ec), ecBand: ecBand && ecShown, shots: shots.length > 0, flag };
}

/** The key for a DayRail and the VwcLane/EcLane rows under it: only what they draw. */
export function laneKeyItems({
  span,
  now,
  lightsOn,
  lightsOff,
  phases,
  lanes,
}: {
  span: Span;
  now: number;
  lightsOn: number;
  lightsOff: number;
  phases: boolean;
  lanes: LaneMarks[];
}): KeyItem[] {
  const any = (mark: keyof LaneMarks) => lanes.some((lane) => !!lane[mark]);
  const items: KeyItem[] = [];
  if (lightsOff > lightsOn) items.push({ mark: "band", color: "#ffb300", label: "Lights on" });
  if (lanes.length && (lightsOn > span.start || lightsOff < span.end))
    items.push({ mark: "band", color: "color-mix(in srgb, var(--foreground) 20%, transparent)", label: "Lights off" });
  if (phases)
    items.push({ mark: "tick", color: "var(--border)", label: "Phase start", detail: "P0 hold · P1 ramp · P2 maintenance · P3 dryback" });
  if (any("vwc")) items.push({ mark: "line", color: "var(--series-vwc, var(--primary))", label: "VWC", detail: "breaks where readings stop" });
  if (any("vwcBand")) items.push({ mark: "band", color: "var(--band-vwc-edge)", label: "VWC target band" });
  if (any("ec")) items.push({ mark: "line", color: "var(--series-ec)", label: "Pore EC" });
  if (any("ecBand")) items.push({ mark: "band", color: "var(--band-ec-edge)", label: "Pore EC target band" });
  if (any("vwc") || any("ec"))
    items.push({ mark: "point", color: "var(--series-vwc, var(--primary))", label: "Latest reading", detail: "amber when out of target" });
  if (any("shots")) items.push({ mark: "tick", color: "var(--series-vwc, var(--primary))", label: "Shot", detail: "outlined while running" });
  if (lanes.some((lane) => lane.flag === "warning")) items.push({ mark: "band", color: "var(--warning-mark)", label: "Problem" });
  if (lanes.some((lane) => lane.flag === "critical")) items.push({ mark: "band", color: "var(--destructive)", label: "Open alert" });
  if (now > span.start && now < span.end) items.push(NOW_KEY);
  return items;
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

/** One pore EC scale for every lane of a room, so the zones compare by eye. */
export function ecDomain(values: (number | null)[]): [number, number] {
  const known = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (!known.length) return [0, 6];
  let lo = Math.max(0, Math.floor((Math.min(...known) - 0.5) * 2) / 2),
    hi = Math.ceil((Math.max(...known) + 0.5) * 2) / 2;
  if (hi - lo < 1.5) {
    const mid = (hi + lo) / 2;
    lo = Math.max(0, mid - 0.75);
    hi = mid + 0.75;
  }
  return [lo, hi];
}
