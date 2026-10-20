import React from "react";
import { useCurrentFrame, random } from "remotion";
import { C, SERIF } from "../theme";
import { stepAt } from "../anim";
import type { SceneDef } from "./kit";
import { SceneSvg, SW, Pill, WATER_DEEP, blobPath, c01, ease, pop, lerp } from "./_rootzone-shared";

type P = { total?: number; water: number; solid?: number; air?: number; litres?: number; label?: string };
type Kind = "water" | "solid" | "air" | "other";

const PER = 9; // frames between boxes filling

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const total = props.total ?? 10;
  const water = props.water;
  const hasSplit = props.solid != null || props.air != null;
  const solid = props.solid ?? (hasSplit ? total - water - (props.air ?? 0) : 0);
  const air = props.air ?? (hasSplit ? total - water - solid : 0);
  const other = hasSplit ? 0 : total - water;
  const count = 3 + (props.litres != null ? 1 : 0);
  const sW = Number.isFinite(steps[0]) ? steps[0] : 10;
  const sS = stepAt(steps, 1, duration, count) || sW + water * PER + 10;
  const sA = stepAt(steps, 2, duration, count) || sS + solid * PER + 10;
  const sL = props.litres != null ? stepAt(steps, 3, duration, count) || sA + 40 : 1e9;

  const kinds: Kind[] = [...Array(water).fill("water"), ...Array(solid).fill("solid"), ...Array(air).fill("air"), ...Array(other).fill("other")];
  const fillAt = (i: number) => {
    const k = kinds[i];
    if (k === "water") return sW + i * PER;
    if (k === "solid") return sS + (i - water) * PER;
    if (k === "air") return sA + (i - water - solid) * PER;
    return sS + (i - water) * PER; // "not water" boxes appear with the second phrase
  };

  const perRow = total <= 12 ? total : Math.ceil(total / 2);
  const rows = Math.ceil(total / perRow);
  const gap = 22;
  const box = Math.min(160, (1700 - gap * (perRow - 1)) / perRow);
  const rowW = perRow * box + (perRow - 1) * gap;
  const x0 = (SW - rowW) / 2;
  const y0 = rows === 1 ? 280 : 210;

  const waterShown = kinds.filter((k, i) => k === "water" && f >= fillAt(i) + 4).length;
  const pct = Math.round((waterShown / total) * 100);
  const head = ease(f, 0, 16);
  const counter = ease(f, sW, 16);
  const litresP = ease(f, sL, 20);
  const legend: [Kind, string, string, number][] = [
    ["water", "Water", C.water, water],
    ...(hasSplit ? ([["solid", "Solid", C.solid, solid], ["air", "Air", C.muted, air]] as [Kind, string, string, number][]) : ([["other", "Not water", C.muted, other]] as [Kind, string, string, number][])),
  ];

  return (
    <SceneSvg>
      <defs>
        {kinds.map((_, i) => (
          <clipPath key={i} id={`vg-${i}`}>
            <rect x={x0 + (i % perRow) * (box + gap)} y={y0 + Math.floor(i / perRow) * (box + gap)} width={box} height={box} rx={14} />
          </clipPath>
        ))}
      </defs>
      <text x={SW / 2} y={95} textAnchor="middle" fontFamily={SERIF} fontSize={58} fill={C.forest} opacity={head} transform={`translate(0 ${(1 - head) * 20})`}>
        {props.label || `One sample, ${total} equal boxes`}
      </text>
      {/* bracket over the sample */}
      <path d={`M ${x0} ${y0 - 26} L ${x0} ${y0 - 44} L ${x0 + rowW} ${y0 - 44} L ${x0 + rowW} ${y0 - 26}`} fill="none" stroke={C.line} strokeWidth={5} opacity={head} strokeLinejoin="round" />

      {kinds.map((k, i) => {
        const x = x0 + (i % perRow) * (box + gap);
        const y = y0 + Math.floor(i / perRow) * (box + gap);
        const t = fillAt(i);
        const p = ease(f, t, 14);
        const pp = pop(f, t, 14);
        const bob = Math.sin(f / 18 + i) * 2;
        return (
          <g key={i}>
            <rect x={x} y={y} width={box} height={box} rx={14} fill={C.white} stroke={C.line} strokeWidth={4} strokeDasharray="12 10" />
            <g clipPath={`url(#vg-${i})`}>
              {k === "water" && p > 0 ? (
                <g>
                  <path
                    d={`M ${x - 10} ${lerp(y + box, y + 14, p) + Math.sin(f / 8 + i) * 4} Q ${x + box / 4} ${lerp(y + box, y + 4, p) + Math.sin(f / 8 + i + 1) * 5} ${x + box / 2} ${lerp(y + box, y + 14, p)} T ${x + box + 10} ${lerp(y + box, y + 14, p) - Math.sin(f / 8 + i) * 4} L ${x + box + 10} ${y + box + 10} L ${x - 10} ${y + box + 10} Z`}
                    fill={C.water}
                  />
                  {[0, 1, 2].map((j) => {
                    const per = 60 + j * 13;
                    const tt = ((f + i * 11 + j * 23) % per) / per;
                    return <circle key={j} cx={x + box * (0.25 + 0.25 * j) + Math.sin(f / 7 + j) * 4} cy={lerp(y + box - 10, y + 30, tt)} r={4 + j} fill={C.white} opacity={0.6 * Math.sin(tt * Math.PI) * p} />;
                  })}
                </g>
              ) : null}
              {k === "solid" && pp > 0.01 ? (
                <g transform={`translate(${x + box / 2} ${y + box / 2}) scale(${pp}) translate(${-x - box / 2} ${-y - box / 2})`}>
                  <rect x={x} y={y} width={box} height={box} fill={C.solidLight} />
                  {[[0.28, 0.3], [0.7, 0.26], [0.5, 0.58], [0.22, 0.78], [0.78, 0.74], [0.95, 0.5], [0.05, 0.45]].map(([u, v], j) => (
                    <g key={j}>
                      <path d={blobPath(x + u * box, y + v * box + bob * (j % 2 ? 0.5 : -0.5), box * 0.17, `vg${i}${j}`)} fill={C.solid} />
                      <path d={blobPath(x + u * box - box * 0.04, y + v * box - box * 0.05, box * 0.07, `vgh${i}${j}`)} fill={C.solidLight} opacity={0.6} />
                    </g>
                  ))}
                </g>
              ) : null}
              {k === "air" && p > 0 ? (
                <g opacity={p}>
                  <rect x={x} y={y} width={box} height={box} fill="#eef3f6" />
                  {[0, 1, 2, 3].map((j) => {
                    const cx = x + box * (0.22 + 0.19 * j) + Math.sin(f / 15 + j * 2) * 8;
                    const cy = y + box * (0.3 + 0.4 * random(`va${i}${j}`)) + Math.cos(f / 19 + j) * 8;
                    return <circle key={j} cx={cx} cy={cy} r={box * (0.06 + 0.04 * random(`vr${i}${j}`))} fill={C.white} stroke="#b9c6cc" strokeWidth={3} />;
                  })}
                  <path d={`M ${x + 20} ${y + box * 0.75} q 20 -14 40 0 t 40 0 t 40 0`} fill="none" stroke="#b9c6cc" strokeWidth={4} strokeLinecap="round" transform={`translate(${Math.sin(f / 20) * 6} 0)`} />
                </g>
              ) : null}
              {k === "other" && pp > 0.01 ? (
                <g opacity={c01(pp)}>
                  <rect x={x} y={y} width={box} height={box} fill="#e7ebe5" />
                  <text x={x + box / 2} y={y + box * 0.66} textAnchor="middle" fontSize={box * 0.5} fontWeight={700} fill={C.muted} opacity={0.7 + 0.3 * Math.sin(f / 12 + i)}>?</text>
                </g>
              ) : null}
            </g>
            {p > 0.05 && k !== "other" ? <rect x={x} y={y} width={box} height={box} rx={14} fill="none" stroke={k === "water" ? WATER_DEEP : k === "solid" ? C.solid : "#9fb0b8"} strokeWidth={4} opacity={p} /> : null}
          </g>
        );
      })}

      {/* legend with live counts */}
      {legend.map(([k, name, col], j) => {
        const first = kinds.indexOf(k);
        const shown = kinds.filter((kk, i) => kk === k && f >= fillAt(i) + 4).length;
        const lp = first >= 0 ? pop(f, fillAt(first), 14) : 0;
        const last = kinds.lastIndexOf(k);
        const lx = rows === 1 && first >= 0 ? x0 + ((first + last) / 2) * (box + gap) + box / 2 : SW / 2 + (j - (legend.length - 1) / 2) * 330;
        return <Pill key={k} x={lx} y={y0 + rows * (box + gap) + 44} text={`${name}  ${shown}`} color={col === C.water ? WATER_DEEP : col} p={lp} size={36} />;
      })}

      {/* the counter */}
      <g opacity={counter} transform={`translate(${SW / 2} ${y0 + rows * (box + gap) + 230})`}>
        <text x={0} y={0} textAnchor="middle" fontFamily={SERIF} fontSize={104} fill={C.ink}>
          <tspan fill={WATER_DEEP}>{waterShown}</tspan>
          <tspan> / {total} = </tspan>
          <tspan fill={WATER_DEEP} fontWeight={700}>{pct}%</tspan>
          <tspan fontSize={64} fill={C.muted}> VWC</tspan>
        </text>
      </g>

      {props.litres != null && litresP > 0 ? (
        <g opacity={litresP} transform={`translate(0 ${(1 - litresP) * 24})`}>
          <rect x={SW / 2 - 560} y={y0 + rows * (box + gap) + 300} width={1120} height={110} rx={55} fill={C.white} stroke={WATER_DEEP} strokeWidth={4} />
          {/* jug */}
          <g transform={`translate(${SW / 2 - 470} ${y0 + rows * (box + gap) + 355})`}>
            <path d="M -30 -38 L 30 -38 L 26 38 L -26 38 Z" fill={C.white} stroke={C.ink} strokeWidth={4} strokeLinejoin="round" />
            <clipPath id="vg-jug">
              <path d="M -28 -36 L 28 -36 L 24 36 L -24 36 Z" />
            </clipPath>
            <rect clipPath="url(#vg-jug)" x={-40} y={36 - 72 * (water / total) * c01(litresP * 1.2) + Math.sin(f / 9) * 2} width={80} height={90} fill={C.water} />
            <path d="M 30 -24 q 22 4 18 26 q -4 16 -20 16" fill="none" stroke={C.ink} strokeWidth={4} />
          </g>
          <text x={SW / 2 + 40} y={y0 + rows * (box + gap) + 372} textAnchor="middle" fontSize={50} fontWeight={700} fill={C.ink}>
            {`${props.litres} L × ${+(water / total).toFixed(2)} = `}
            <tspan fill={WATER_DEEP}>{`${+((props.litres * water) / total).toFixed(2)} L of water`}</tspan>
          </text>
        </g>
      ) : null}
    </SceneSvg>
  );
};

export default {
  Component,
  doc:
    "VWC as equal boxes: a sample split into `total` boxes (default 10; >12 wraps to two rows). Water boxes fill one by one with rippling water, then solid boxes (substrate blobs), then air boxes (drifting bubbles); a legend counts each kind and a big live counter reads e.g. '6 / 10 = 60% VWC'. If neither solid nor air is given, the non-water boxes show '?' (\"Not water\" — use it for 'what VWC does not tell you'). Optional litres line: '5 L × 0.6 = 3 L of water' with a filling jug. props: {total?, water, solid?, air?, litres?: sample litres, label?: heading}. steps: [water starts filling, solid (or ? boxes) start, air starts, litres line].",
  example: { props: { total: 10, water: 6, solid: 2, air: 2, litres: 5 }, steps: [10, 75, 110, 150] },
} satisfies SceneDef<P>;
