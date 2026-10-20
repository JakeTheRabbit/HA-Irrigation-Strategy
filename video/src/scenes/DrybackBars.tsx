import React from "react";
import { interpolate, useCurrentFrame, random, Easing } from "remotion";
import { C, SERIF } from "../theme";
import { clamp, stepAt } from "../anim";
import type { SceneDef } from "./kit";
import { Svg, Pill, Bracket, wave, lerp } from "./_measure-shared";

type P = { start: number; end: number; unit?: string; showRelative?: boolean; startLabel?: string; endLabel?: string };

const GW = 250; // glass width
const GT = 175; // glass top
const GB = 745; // glass bottom
const AX = 330; // start glass centre
const BX = 830; // end glass centre

const fmt = (n: number) => (Math.abs(n - Math.round(n)) < 0.05 ? String(Math.round(n)) : n.toFixed(1));

// Water body with a gently moving surface.
function water(cx: number, level: number, f: number, phase: number) {
  const x0 = cx - GW / 2 + 8;
  const x1 = cx + GW / 2 - 8;
  let d = `M ${x0} ${GB - 8}`;
  for (let i = 0; i <= 16; i++) {
    const x = lerp(x0, x1, i / 16);
    d += ` L ${x.toFixed(1)} ${(level + 5 * Math.sin(i / 2.2 + f / 9 + phase)).toFixed(1)}`;
  }
  return d + ` L ${x1} ${GB - 8} Z`;
}

const Glass: React.FC<{ cx: number; title: string; titleColor: string; max: number; children?: React.ReactNode; op: number }> = ({ cx, title, titleColor, max, children, op }) => {
  const yOf = (v: number) => GB - 8 - (v / max) * (GB - GT - 8);
  const ticks: number[] = [];
  for (let v = 0; v <= max; v += 10) ticks.push(v);
  return (
    <g opacity={op}>
      <text x={cx} y={GT - 40} textAnchor="middle" fontSize={40} fontWeight={800} fill={titleColor}>{title}</text>
      <rect x={cx - GW / 2} y={GT} width={GW} height={GB - GT} rx={26} fill={C.white} stroke={C.line} strokeWidth={4} />
      <clipPath id={`clip-${cx}`}>
        <rect x={cx - GW / 2 + 4} y={GT + 4} width={GW - 8} height={GB - GT - 8} rx={22} />
      </clipPath>
      <g clipPath={`url(#clip-${cx})`}>{children}</g>
      {ticks.map((v) => (
        <g key={v}>
          <line x1={cx - GW / 2} x2={cx - GW / 2 + (v % 20 === 0 ? 26 : 14)} y1={yOf(v)} y2={yOf(v)} stroke={C.muted} strokeWidth={3} opacity={0.5} />
          {v % 20 === 0 ? <text x={cx - GW / 2 - 14} y={yOf(v) + 10} textAnchor="end" fontSize={30} fontWeight={600} fill={C.muted}>{v}</text> : null}
        </g>
      ))}
      <rect x={cx - GW / 2} y={GT} width={GW} height={GB - GT} rx={26} fill="none" stroke={C.forest} strokeWidth={5} />
      <rect x={cx - GW / 2 + 22} y={GT + 30} width={14} height={GB - GT - 120} rx={7} fill={C.white} opacity={0.55} />
    </g>
  );
};

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const { start, end } = props;
  const unit = props.unit ?? "% VWC";
  const showRel = props.showRelative !== false;
  const n = showRel ? 4 : 3;
  const S = (i: number) => stepAt(steps, i, duration, n);
  const max = Math.ceil((start + 12) / 20) * 20;
  const yOf = (v: number) => GB - 8 - (v / max) * (GB - GT - 8);
  const fall = start - end;
  const rel = (fall / start) * 100;
  const ease = Easing.inOut(Easing.cubic);

  const aOp = interpolate(f, [S(0), S(0) + 14], [0, 1], clamp);
  const aFill = interpolate(f, [S(0), S(0) + 30], [0, start], { ...clamp, easing: ease });
  const bOp = interpolate(f, [S(1), S(1) + 14], [0, 1], clamp);
  const bFall = interpolate(f, [S(1) + 12, S(1) + 60], [0, 1], { ...clamp, easing: ease });
  const whole = Number.isInteger(start) && Number.isInteger(end);
  const bLevel = lerp(start, end, bFall);
  const bShown = whole ? Math.round(bLevel) : bLevel;
  const brP = interpolate(f, [S(2), S(2) + 20], [0, 1], { ...clamp, easing: Easing.out(Easing.back(1.4)) });
  const relP = interpolate(f, [S(3), S(3) + 24], [0, 1], clamp);
  const pieP = interpolate(f, [S(3) + 10, S(3) + 50], [0, 1], { ...clamp, easing: ease });

  const pct = unit.startsWith("%");
  const big = (v: number) => (pct ? `${fmt(v)}%` : fmt(v));
  const small = pct ? unit.slice(1).trim() : unit;

  // Evaporation / uptake droplets rising off the end glass while and after it dries.
  const drops = Array.from({ length: 6 }, (_, i) => {
    const period = 70 + 20 * random(`dp${i}`);
    const t = ((f + random(`do${i}`) * period) % period) / period;
    return { x: BX - 80 + 160 * random(`dx${i}`), y: yOf(bLevel) - 20 - t * 150, o: Math.sin(t * Math.PI) * Math.min(1, bFall * 3) };
  });

  // Pie geometry.
  const PX = 1530;
  const PY = 470;
  const PR = 190;
  const ang = (rel / 100) * 360 * pieP;
  const a1 = ((ang - 90) * Math.PI) / 180;
  const pie = `M ${PX} ${PY} L ${PX} ${PY - PR} A ${PR} ${PR} 0 ${ang > 180 ? 1 : 0} 1 ${PX + PR * Math.cos(a1)} ${PY + PR * Math.sin(a1)} Z`;

  return (
    <Svg>
      <defs>
        <linearGradient id="db-water" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={C.water} />
          <stop offset="1" stopColor="#3a7fb5" />
        </linearGradient>
        <pattern id="db-hatch" width="16" height="16" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="16" stroke={C.ec} strokeWidth="7" opacity={0.55} />
        </pattern>
      </defs>

      {/* Start glass */}
      <Glass cx={AX} title={props.startLabel ?? "Start reading"} titleColor={C.forest} max={max} op={aOp}>
        <path d={water(AX, yOf(aFill), f, 0)} fill="url(#db-water)" />
        {Array.from({ length: 5 }, (_, i) => {
          const t = ((f + i * 23) % 90) / 90;
          return <circle key={i} cx={AX - 70 + 35 * i} cy={lerp(GB - 20, yOf(aFill) + 20, t)} r={5 + (i % 2) * 3} fill={C.white} opacity={0.45 * Math.sin(t * Math.PI)} />;
        })}
        {/* Relative view: the fallen slice sits on top of the start water */}
        <rect x={AX - GW / 2} y={yOf(start) - 8} width={GW} height={(yOf(end) - yOf(start) + 8) * relP} fill={C.ec} opacity={0.9 * relP} />
        <rect x={AX - GW / 2} y={yOf(start) - 8} width={GW} height={(yOf(end) - yOf(start) + 8) * relP} fill="url(#db-hatch)" opacity={relP} />
      </Glass>

      {/* End glass */}
      <Glass cx={BX} title={props.endLabel ?? "End reading"} titleColor={C.forest} max={max} op={bOp}>
        <rect x={BX - GW / 2} y={yOf(start)} width={GW} height={Math.max(0, yOf(bLevel) - yOf(start))} fill="url(#db-hatch)" opacity={brP} />
        <path d={water(BX, yOf(bLevel), f, 1.7)} fill="url(#db-water)" />
      </Glass>
      {drops.map((d, i) => (
        <path key={i} d={`M ${d.x} ${d.y - 12} Q ${d.x + 8} ${d.y} ${d.x} ${d.y + 6} Q ${d.x - 8} ${d.y} ${d.x} ${d.y - 12} Z`} fill={C.water} opacity={0.6 * d.o * bOp} />
      ))}

      {/* Start level carried across */}
      {[[AX + GW / 2, BX - GW / 2 - 56], [BX - GW / 2, BX + GW / 2 + 10]].map(([x1, x2], i) => (
        <line key={i} x1={x1} x2={x2} y1={yOf(start)} y2={yOf(start)} stroke={C.forest} strokeWidth={4} strokeDasharray="12 10" opacity={bOp * 0.7} strokeDashoffset={-f * 0.5} />
      ))}

      {/* Readouts */}
      <g opacity={aOp}>
        <text x={AX} y={GB + 82} textAnchor="middle" fontFamily={SERIF} fontSize={76} fill={C.ink}>{big(whole ? Math.round(aFill) : aFill)}</text>
        <text x={AX} y={GB + 126} textAnchor="middle" fontSize={30} fontWeight={600} fill={C.muted}>{small}</text>
      </g>
      <g opacity={bOp}>
        <text x={BX} y={GB + 82} textAnchor="middle" fontFamily={SERIF} fontSize={76} fill={C.ink}>{big(bShown)}</text>
        <text x={BX} y={GB + 126} textAnchor="middle" fontSize={30} fontWeight={600} fill={C.muted}>{small}</text>
      </g>
      {bOp > 0 ? (
        <g opacity={bOp}>
          <path d={`M ${AX + GW / 2 + 40} ${GT - 52} Q ${(AX + BX) / 2} ${GT - 100 + 6 * wave(f, 60)} ${BX - GW / 2 - 40} ${GT - 52}`} fill="none" stroke={C.gold} strokeWidth={5} strokeDasharray="4 12" strokeLinecap="round" />
          <path d={`M ${BX - GW / 2 - 60} ${GT - 66} L ${BX - GW / 2 - 38} ${GT - 52} L ${BX - GW / 2 - 62} ${GT - 40}`} fill="none" stroke={C.gold} strokeWidth={5} strokeLinecap="round" />
          <text x={(AX + BX) / 2} y={GT - 112} textAnchor="middle" fontSize={30} fontWeight={700} fill={C.gold}>later</text>
        </g>
      ) : null}

      {/* Points bracket */}
      <Bracket x={BX + GW / 2 + 24} y1={yOf(start)} y2={yOf(end)} p={brP} color={C.ec} label={`${fmt(fall)} points`} size={44} />
      {brP > 0 ? (
        <text x={BX + GW / 2 + 70} y={yOf(end) + 66} fontSize={32} fontWeight={600} fill={C.muted} opacity={brP}>{`${fmt(start)} − ${fmt(end)} = ${fmt(fall)}`}</text>
      ) : null}

      {/* Relative: fall compared with the start */}
      {showRel ? (
        <g opacity={relP}>
          <text x={AX} y={(yOf(end) + GB) / 2 + 14} textAnchor="middle" fontSize={34} fontWeight={800} fill={C.white}>{`whole = ${fmt(start)}`}</text>
          <text x={AX} y={(yOf(start) + yOf(end)) / 2 + 12} textAnchor="middle" fontSize={34} fontWeight={800} fill={C.white}>{fmt(fall)}</text>
          <circle cx={PX} cy={PY} r={PR + 14} fill={C.white} stroke={C.line} strokeWidth={3} />
          <circle cx={PX} cy={PY} r={PR} fill={C.water} />
          <g transform={`rotate(${2 * wave(f, 120)} ${PX} ${PY})`}>
            <path d={pie} fill={C.ec} />
            <path d={pie} fill="url(#db-hatch)" />
          </g>
          <circle cx={PX} cy={PY} r={PR * 0.52} fill={C.white} />
          <text x={PX} y={PY + 26} textAnchor="middle" fontFamily={SERIF} fontSize={80} fill={C.ink}>{`${fmt(rel * pieP)}%`}</text>
          <text x={PX} y={PY - PR - 56} textAnchor="middle" fontSize={40} fontWeight={700} fill={C.ink}>{`${fmt(fall)} ÷ ${fmt(start)} × 100`}</text>
          <Pill x={PX} y={PY + PR + 72} text={`${fmt(rel)}% of the start`} size={44} color={C.white} bg={C.ec} scale={1 + 0.03 * wave(f, 40)} />
          <text x={PX} y={PY + PR + 150} textAnchor="middle" fontSize={32} fontWeight={600} fill={C.muted}>relative dryback</text>
        </g>
      ) : null}
    </Svg>
  );
};

export default {
  Component,
  doc: "Dryback as a balance: a start glass and an end glass of water (VWC scale on each). The end glass drains from the start level to the end level while droplets rise off it, a bracket measures the fall in points ('15 points'), then (showRelative) the fallen slice is hatched on the start glass and a pie fills to the fall as a share of the start ('25% of the start'). props: {start:60, end:45, unit?:'% VWC', showRelative?:true, startLabel?, endLabel?}. steps: [start reading, end reading (drain), points bracket, relative share].",
  example: { props: { start: 60, end: 45, unit: "% VWC", showRelative: true }, steps: [0, 40, 110, 160] },
} satisfies SceneDef<P>;
