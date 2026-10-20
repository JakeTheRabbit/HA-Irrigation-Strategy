import { useId } from "react";
import type { PumpState } from "@/lib/dosing";
import "./peristaltic-pump.css";

// The head's centre, the tube loop's radius and the rollers' orbit, in the drawing's units.
const CX = 60,
  CY = 54,
  LOOP = 23,
  ORBIT = 15;
const ROLLERS = [-90, 30, 150].map((degrees) => ({
  x: CX + ORBIT * Math.cos((degrees * Math.PI) / 180),
  y: CY + ORBIT * Math.sin((degrees * Math.PI) / 180),
}));
// Where the tube leaves the loop at each side, straight down out of the head.
const SIDE = 16;
const LOOP_Y = CY + Math.sqrt(LOOP ** 2 - SIDE ** 2);
const TUBE = `M${CX - SIDE} 132 V${LOOP_Y.toFixed(2)} A${LOOP} ${LOOP} 0 1 1 ${CX + SIDE} ${LOOP_Y.toFixed(2)} V132`;

/** A peristaltic dosing pump, drawn: a round head on its plate, three rollers pressing a tube loop,
 * the tube's two ends coming down out of it. The rotor turns while the pump doses and stands still
 * under reduced motion; a pump that cannot be read has a question mark on its head. */
export function PeristalticPump({ state, label }: { state: PumpState; label: string }) {
  const id = useId();
  return (
    <svg
      className="peristaltic"
      viewBox="0 0 120 132"
      role="img"
      aria-label={label}
      data-state={state}
    >
      <defs>
        <radialGradient id={`${id}-head`} cx="38%" cy="32%" r="75%">
          <stop offset="0%" className="pp-cream-light" />
          <stop offset="100%" className="pp-cream-dark" />
        </radialGradient>
        <radialGradient id={`${id}-glow`}>
          <stop offset="62%" className="pp-glow-in" />
          <stop offset="100%" className="pp-glow-out" />
        </radialGradient>
      </defs>
      <circle className="pp-glow" cx={CX} cy={CY} r="58" fill={`url(#${id}-glow)`} />
      <rect className="pp-plate" x="13" y="7" width="94" height="94" rx="16" />
      {[
        [23, 17],
        [97, 17],
        [23, 91],
        [97, 91],
      ].map(([x, y]) => (
        <circle key={`${x}-${y}`} className="pp-screw" cx={x} cy={y} r="2.4" />
      ))}
      <circle className="pp-head" cx={CX} cy={CY} r="38" fill={`url(#${id}-head)`} />
      <circle className="pp-recess" cx={CX} cy={CY} r="30.5" />
      <path className="pp-tube" d={TUBE} />
      <path className="pp-liquid" d={TUBE} />
      <g className="pp-rotor">
        <path
          className="pp-arm"
          d={`M${ROLLERS.map(({ x, y }) => `${x.toFixed(2)} ${y.toFixed(2)}`).join(" L")} Z`}
        />
        {ROLLERS.map(({ x, y }) => (
          <g key={`${x}`}>
            <circle className="pp-roller" cx={x} cy={y} r="6.3" />
            <circle className="pp-axle" cx={x} cy={y} r="1.6" />
          </g>
        ))}
        <circle className="pp-hub" cx={CX} cy={CY} r="5" />
      </g>
      <path className="pp-shine" d={`M${CX - 29} ${CY - 12} A31 31 0 0 1 ${CX - 10} ${CY - 29}`} />
      {state === "unavailable" && (
        <text className="pp-unknown" x={CX} y={CY + 9} textAnchor="middle">
          ?
        </text>
      )}
    </svg>
  );
}
