import type { ReactNode } from "react";
import { number } from "@/components/dashboard";
import "./zone-gauges.css";

const clamp = (value: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, value));

/** One reading as a short bar: the band it should sit in shaded, a tick where it is now. Calm in
 * band; out of band the tick sits outside the shading and the value carries ▲ or ▼. */
export function MiniGauge({
  label,
  value,
  unit = "",
  digits = 1,
  band,
  scale,
}: {
  label: string;
  value: number | null;
  unit?: string;
  digits?: number;
  band: readonly [number, number] | null;
  /** The bar's ends; the band and the value are drawn within them. */
  scale: readonly [number, number];
}) {
  const [lo, hi] = scale;
  const at = (v: number) => `${(clamp((v - lo) / (hi - lo), 0, 1) * 100).toFixed(1)}%`;
  const state =
    value === null || !band ? "none" : value < band[0] ? "low" : value > band[1] ? "high" : "ok";
  const words =
    value === null
      ? `${label} unavailable`
      : `${label} ${number(value, digits)}${unit}${
          band
            ? state === "ok"
              ? ", in band"
              : `, ${state === "low" ? "under" : "over"} ${number(band[0], digits)}–${
                  Number.isFinite(band[1]) ? number(band[1], digits) : "∞"
                }`
            : ""
        }`;
  return (
    <div className="mini-gauge" data-state={state} role="img" aria-label={words}>
      <span className="mini-gauge-label">{label}</span>
      <span className="mini-gauge-track" aria-hidden="true">
        {band && (
          <span
            className="mini-gauge-band"
            style={{
              left: at(band[0]),
              width: `calc(${at(Number.isFinite(band[1]) ? band[1] : hi)} - ${at(band[0])})`,
            }}
          />
        )}
        {value !== null && <span className="mini-gauge-tick" style={{ left: at(value) }} />}
      </span>
      <span className="mini-gauge-value" aria-hidden="true">
        {value === null ? "—" : `${number(value, digits)}${unit}`}
        {state === "low" ? " ▼" : state === "high" ? " ▲" : ""}
      </span>
    </div>
  );
}

/** Water per plant as a bar against the room's median zone (the tick): a zone drinking far less or
 * more than its neighbours stands out. */
export function DrinkBar({
  ml,
  median,
  max,
  text,
}: {
  ml: number | null;
  median: number | null;
  max: number;
  text: ReactNode;
}) {
  const at = (v: number) => `${(clamp(v / max, 0, 1) * 100).toFixed(1)}%`;
  const ratio = ml !== null && median ? ml / median : null;
  const state = ratio === null ? "none" : ratio < 0.7 ? "low" : ratio > 1.4 ? "high" : "ok";
  return (
    <div className="drink-bar" data-state={state}>
      <span className="drink-bar-text">{text}</span>
      <span className="drink-bar-track" aria-hidden="true">
        {ml !== null && <span className="drink-bar-fill" style={{ width: at(ml) }} />}
        {median !== null && <span className="drink-bar-median" style={{ left: at(median) }} />}
      </span>
    </div>
  );
}

/** Today's shots as drops: an empty row is a zone that has not been watered. */
export function ShotDots({ shots }: { shots: number | null }) {
  if (shots === null) return null;
  const shown = Math.min(shots, 16);
  return (
    <span className="shot-dots" role="img" aria-label={`${shots} shots today`}>
      {Array.from({ length: Math.max(shown, 1) }, (_, i) => (
        <span key={i} className="shot-dot" data-empty={shots === 0 || undefined} />
      ))}
      {shots > shown && <span className="shot-more">+{shots - shown}</span>}
      <span className="shot-count">{shots === 0 ? "No shots yet" : `${shots} shot${shots === 1 ? "" : "s"}`}</span>
    </span>
  );
}
