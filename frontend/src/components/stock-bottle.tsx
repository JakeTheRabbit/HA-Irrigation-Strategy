import { useId } from "react";
import type { StockState, StockTankReading } from "@/lib/dosing";
import "./stock-bottle.css";

// The bottle: a cap, a neck, shoulders and a body with rounded feet, standing on y=60. The body
// holds the tank from y=60 (empty) up to y=18 (full); the neck is not counted.
const BODY =
  "M16 7 V11 C16 13.5 6 13 6 18.5 V56 Q6 60 10 60 H30 Q34 60 34 56 V18.5 C34 13 24 13.5 24 11 V7 Z";
const EMPTY = 60,
  FULL = 18;

/** The smallest a bottle is drawn, so it stays readable: a tank under 0.3³ (2.7%) of the largest is
 * drawn larger than to scale. */
export const MIN_BOTTLE = 0.3;
/** How big the bottle is drawn: `capacityScale` (the tank's capacity over the room's largest) by
 * volume, the cube root, as a real bottle holding that much; else `scale`. MIN_BOTTLE at the least. */
export const bottleSize = (scale: number, capacityScale?: number) =>
  Math.max(MIN_BOTTLE, Math.min(1, capacityScale === undefined ? scale : Math.cbrt(capacityScale)));

/** Where `litres` sits in a bottle drawn at this size, as a percentage of the drawing's height from
 * its top, so a page can label the low mark or the level beside it. */
export function bottleTop(litres: number, capacity: number, capacityScale: number): number {
  const size = bottleSize(1, capacityScale);
  const y = EMPTY - Math.max(0, Math.min(1, litres / capacity)) * (EMPTY - FULL) * size;
  return (y / 62) * 100;
}

/** Where the bottle's percent label sits (as bottleTop): in the middle of the liquid, unless too
 * little shows to hold it or that is on the dashed low line; then in the liquid above the low line
 * when there is room, else just above the level or the low line, whichever is higher. */
export function percentTop(
  litres: number,
  capacity: number,
  lowLitres: number,
  capacityScale: number,
): number {
  const HALF = 8; // half the label's height and a little, in percent of the drawing
  const top = bottleTop(litres, capacity, capacityScale);
  const low = bottleTop(lowLitres, capacity, capacityScale);
  const middle = bottleTop(litres / 2, capacity, capacityScale);
  if (litres / capacity >= 0.25 && Math.abs(middle - low) >= HALF) return middle;
  if (low - top >= 2 * HALF) return (low + top) / 2;
  return Math.min(top, low) - HALF;
}

/** A stock tank drawn as a bottle to scale: its liquid at its level and its low mark dashed across,
 * and the bottle itself `scale` of the room's largest, or drawn by volume with `capacityScale`
 * (without it the drawing is as before). Amber within half again of the low mark, red at or under
 * it (the Stock tanks page's rule). */
export function StockBottle({
  tank,
  state,
  scale = 1,
  capacityScale,
  label,
}: {
  tank: StockTankReading;
  state: StockState;
  scale?: number;
  capacityScale?: number;
  label: string;
}) {
  const clip = useId();
  const y = (litres: number) =>
    EMPTY - Math.max(0, Math.min(1, litres / tank.capacity_l)) * (EMPTY - FULL);
  const top = y(tank.level_l);
  const size = bottleSize(scale, capacityScale);
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
