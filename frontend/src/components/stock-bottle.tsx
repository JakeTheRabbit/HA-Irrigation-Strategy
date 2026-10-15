import { useId } from "react";
import type { StockState, StockTankReading } from "@/lib/dosing";
import "./stock-bottle.css";

// The bottle: a cap, a neck, shoulders and a body with rounded feet, standing on y=60. The body
// holds the tank from y=60 (empty) up to y=18 (full); the neck is not counted.
const BODY =
  "M16 7 V11 C16 13.5 6 13 6 18.5 V56 Q6 60 10 60 H30 Q34 60 34 56 V18.5 C34 13 24 13.5 24 11 V7 Z";
const EMPTY = 60,
  FULL = 18;

/** A stock tank drawn as a bottle to scale: its liquid at its level and its low mark dashed across,
 * and the bottle itself `scale` of the room's largest (0.3 at the least). Amber within half again of
 * the low mark, red at or under it (the Stock tanks page's rule). */
export function StockBottle({
  tank,
  state,
  scale = 1,
  label,
}: {
  tank: StockTankReading;
  state: StockState;
  scale?: number;
  label: string;
}) {
  const clip = useId();
  const y = (litres: number) =>
    EMPTY - Math.max(0, Math.min(1, litres / tank.capacity_l)) * (EMPTY - FULL);
  const top = y(tank.level_l);
  const size = Math.max(0.3, Math.min(1, scale));
  return (
    <svg
      className="stock-bottle"
      viewBox="0 0 40 62"
      role="img"
      aria-label={label}
      data-state={state}
    >
      <defs>
        <clipPath id={clip}>
          <path d={BODY} />
        </clipPath>
      </defs>
      <g transform={`translate(20 ${EMPTY}) scale(${size}) translate(-20 -${EMPTY})`}>
        <rect className="sb-cap" x="14" y="1" width="12" height="6" rx="1.5" />
        <path className="sb-shell" d={BODY} />
        <rect
          className="sb-liquid"
          x="0"
          y={top}
          width="40"
          height={EMPTY - top}
          clipPath={`url(#${clip})`}
        />
        <path className="sb-low" d={`M6 ${y(tank.low_l)} H34`} />
        <path className="sb-outline" d={BODY} />
      </g>
    </svg>
  );
}
