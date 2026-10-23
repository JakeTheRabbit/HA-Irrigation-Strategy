import { number } from "@/components/dashboard";
import "./primitives.css";

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** Degrees swept from the left end of a half-circle scale, 0 at `min`, 180 at `max`. */
export function arcAngle(value: number, min: number, max: number): number {
  return Math.round((clamp((value - min) / (max - min), 0, 1) || 0) * 180);
}

// A 200 × 112 box: the half circle is centred on (100, 100).
const point = (deg: number, r: number) => {
  const t = Math.PI * (1 - deg / 180);
  return [100 + r * Math.cos(t), 100 - r * Math.sin(t)] as const;
};
const fixed = (n: number) => n.toFixed(1);
const arc = (from: number, to: number, r: number) => {
  const [x1, y1] = point(from, r),
    [x2, y2] = point(to, r);
  return `M${fixed(x1)} ${fixed(y1)} A${r} ${r} 0 0 1 ${fixed(x2)} ${fixed(y2)}`;
};
const tick = (deg: number) => {
  const [x1, y1] = point(deg, 86),
    [x2, y2] = point(deg, 64);
  return { x1: fixed(x1), y1: fixed(y1), x2: fixed(x2), y2: fixed(y2) };
};

/** A half-circle gauge: grey track from `min` to `max`, the band it should sit in shaded with a
 * tick at each end, and a needle at the value. The tone colours the needle; the caller decides it. */
export function ArcGauge({
  value,
  min,
  max,
  band,
  tone,
  label,
  unit = "",
}: {
  value: number;
  min: number;
  max: number;
  band: [number, number];
  tone: "ok" | "warn" | "bad";
  label: string;
  unit?: string;
}) {
  const angle = arcAngle(value, min, max);
  const lo = arcAngle(band[0], min, max),
    hi = arcAngle(band[1], min, max);
  const [nx, ny] = point(angle, 70);
  const words = `${label} ${number(value)}${unit}, target band ${number(band[0])}–${number(band[1])}${unit}`;
  return (
    <svg
      className="arc-gauge"
      viewBox="0 0 200 112"
      width={170}
      height={95}
      role="img"
      aria-label={words}
      data-angle={angle}
      data-tone={tone}
    >
      <path className="arc-gauge-track" d={arc(0, 180, 75)} />
      {hi > lo && <path className="arc-gauge-band" d={arc(lo, hi, 75)} />}
      <line className="arc-gauge-tick" {...tick(lo)} />
      <line className="arc-gauge-tick" {...tick(hi)} />
      <line className="arc-gauge-needle" x1="100" y1="100" x2={fixed(nx)} y2={fixed(ny)} />
      <circle className="arc-gauge-hub" cx="100" cy="100" r="7" />
      <text className="arc-gauge-end" x="14" y="111">
        {number(min)}
        {unit}
      </text>
      <text className="arc-gauge-end" x="186" y="111" textAnchor="end">
        {number(max)}
        {unit}
      </text>
    </svg>
  );
}
