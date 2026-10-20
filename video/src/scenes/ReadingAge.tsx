import React from "react";
import { interpolate, interpolateColors, useCurrentFrame, spring, useVideoConfig } from "remotion";
import { C, SERIF } from "../theme";
import { clamp, stepAt } from "../anim";
import type { SceneDef } from "./kit";
import { Svg, Pill, Tick, Cross, wave } from "./_measure-shared";

type Reading = { name: string; at: string; value?: string };
type P = { now: string; readings: Reading[]; staleAfter?: number; units?: { value: string; unit: string } };

const CX = 390;
const CY = 400;
const R = 255;
const CARD_X = 800;
const CARD_W = 1020;
const CARD_H = 172;

const mins = (t: string) => {
  const [h, m] = t.split(":").map(Number);
  return (h || 0) * 60 + (m || 0);
};
const ageOf = (now: string, at: string) => (mins(now) - mins(at) + 1440) % 1440;
const fmtAge = (m: number) => {
  const r = Math.round(m);
  if (r < 60) return `${r} min old`;
  const h = Math.floor(r / 60);
  const mm = r % 60;
  return mm ? `${h} h ${mm} min old` : `${h} h old`;
};
const ageColor = (m: number, stale: number) => interpolateColors(m, [0, stale * 0.25, stale * 0.6, stale], [C.good, C.good, C.warn, C.error]);
const ang = (m: number) => ((m % 720) / 720) * 360; // 12-hour dial, degrees from 12 o'clock
const pt = (deg: number, r: number) => [CX + r * Math.sin((deg * Math.PI) / 180), CY - r * Math.cos((deg * Math.PI) / 180)];

function wedge(fromDeg: number, sweep: number, r: number) {
  const [x0, y0] = pt(fromDeg, r);
  const [x1, y1] = pt(fromDeg + sweep, r);
  return `M ${CX} ${CY} L ${x0} ${y0} A ${r} ${r} 0 ${sweep > 180 ? 1 : 0} 1 ${x1} ${y1} Z`;
}

const Card: React.FC<{ r: Reading; i: number; at: number; now: string; stale: number; active: boolean; y: number }> = ({ r, i, at, now, stale, active, y }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame: f - at, fps, config: { damping: 15, stiffness: 120 } });
  const age = ageOf(now, r.at);
  const count = interpolate(f, [at + 6, at + 36], [0, age], { ...clamp, easing: (t) => 1 - Math.pow(1 - t, 3) });
  const col = ageColor(count, stale);
  const isStale = age > stale;
  const stamp = isStale ? spring({ frame: f - at - 40, fps, config: { damping: 9, stiffness: 160 } }) : 0;
  const chip = fmtAge(count);
  if (f < at) return null;
  return (
    <g opacity={Math.min(1, pop * 1.4)} transform={`translate(${(1 - pop) * 80} 0)`}>
      <rect x={CARD_X} y={y} width={CARD_W} height={CARD_H} rx={26} fill={C.white} stroke={active ? col : C.line} strokeWidth={active ? 5 : 3} />
      <rect x={CARD_X} y={y} width={18} height={CARD_H} rx={9} fill={col} />
      {/* probe icon */}
      <g transform={`translate(${CARD_X + 80} ${y + CARD_H / 2})`}>
        <rect x={-26} y={-44} width={52} height={40} rx={10} fill={C.forest} />
        {[-14, 0, 14].map((dx) => (
          <rect key={dx} x={dx - 4} y={-4} width={8} height={48} rx={4} fill="#c9ccd1" stroke={C.muted} strokeWidth={1.5} />
        ))}
        <circle cx={18} cy={-34} r={5} fill={col} opacity={0.5 + 0.5 * wave(f, 24, i)} />
      </g>
      <text x={CARD_X + 150} y={y + 70} fontSize={44} fontWeight={800} fill={C.ink}>{r.name}</text>
      <text x={CARD_X + 150} y={y + 128} fontSize={32} fontWeight={600} fill={C.muted}>{`last update ${r.at}`}</text>
      {r.value ? <text x={CARD_X + 600} y={y + 108} textAnchor="middle" fontFamily={SERIF} fontSize={72} fill={isStale ? C.muted : C.ink} opacity={isStale ? 1 - 0.75 * Math.min(1, stamp) : 1}>{r.value}</text> : null}
      <Pill x={CARD_X + 870} y={y + CARD_H / 2} text={chip} size={34} color={C.white} bg={col} />
      {isStale ? (
        <g opacity={Math.min(1, stamp)} transform={`translate(${CARD_X + 600} ${y + CARD_H / 2}) rotate(-12) scale(${2 - Math.min(1, stamp)})`}>
          <rect x={-120} y={-44} width={240} height={88} rx={12} fill="none" stroke={C.error} strokeWidth={7} />
          <text y={22} textAnchor="middle" fontSize={60} fontWeight={900} letterSpacing={8} fill={C.error}>STALE</text>
        </g>
      ) : null}
    </g>
  );
};

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const rs = props.readings ?? [];
  const stale = props.staleAfter ?? 60;
  const n = rs.length + (props.units ? 1 : 0);
  const S = (i: number) => stepAt(steps, i, duration, n) || (i === 0 ? 12 : 0);
  const nowM = mins(props.now);
  const clockP = spring({ frame: f, fps, config: { damping: 16, stiffness: 100 } });

  let activeI = -1;
  rs.forEach((_, i) => {
    if (f >= S(i)) activeI = i;
  });
  const act = activeI >= 0 ? rs[activeI] : null;
  const actAge = act ? ageOf(props.now, act.at) : 0;
  const sweepP = act ? interpolate(f, [S(activeI) + 6, S(activeI) + 36], [0, 1], clamp) : 0;
  const sweep = Math.min(actAge, 719) / 2 * sweepP; // degrees on a 12-h dial
  const wedgeCol = act ? ageColor(actAge * sweepP, stale) : C.good;

  // Cards stack; units panel after them.
  const gap = 28;
  const total = rs.length * CARD_H + (rs.length - 1) * gap + (props.units ? 250 : 0);
  const top = Math.max(40, (900 - total) / 2);
  const unitsY = top + rs.length * (CARD_H + gap) + 10;
  const uP = props.units ? spring({ frame: f - S(rs.length), fps, config: { damping: 15, stiffness: 120 } }) : 0;

  const hourA = ang(nowM);
  const minA = (nowM % 60) * 6;
  const secA = (f / fps) * 6 * 4; // a brisk sweep so it always visibly moves

  return (
    <Svg>
      {/* Clock */}
      <g transform={`translate(${CX} ${CY}) scale(${0.85 + 0.15 * clockP}) translate(${-CX} ${-CY})`} opacity={Math.min(1, clockP * 1.5)}>
        <circle cx={CX} cy={CY + 14} r={R + 22} fill={C.forest} opacity={0.1} />
        <circle cx={CX} cy={CY} r={R + 22} fill={C.forest} />
        <circle cx={CX} cy={CY} r={R} fill={C.white} />
        {act ? <path d={wedge(hourA - sweep, sweep, R - 8)} fill={wedgeCol} opacity={0.22} /> : null}
        {act && sweepP > 0 ? (() => {
          const [x, y] = pt(hourA - sweep, R - 8);
          return <line x1={CX} y1={CY} x2={x} y2={y} stroke={wedgeCol} strokeWidth={5} strokeDasharray="10 8" />;
        })() : null}
        {Array.from({ length: 60 }, (_, i) => {
          const [x0, y0] = pt(i * 6, R - 14);
          const [x1, y1] = pt(i * 6, R - (i % 5 === 0 ? 40 : 26));
          return <line key={i} x1={x0} y1={y0} x2={x1} y2={y1} stroke={C.forest} strokeWidth={i % 5 === 0 ? 6 : 2} strokeLinecap="round" opacity={i % 5 === 0 ? 1 : 0.5} />;
        })}
        {Array.from({ length: 12 }, (_, i) => {
          const [x, y] = pt((i + 1) * 30, R - 78);
          return <text key={i} x={x} y={y + 13} textAnchor="middle" fontSize={38} fontWeight={700} fill={C.ink}>{i + 1}</text>;
        })}
        {/* hands */}
        {(() => {
          const [hx, hy] = pt(hourA, R * 0.5);
          const [mx, my] = pt(minA, R * 0.6);
          const [sx, sy] = pt(secA, R * 0.82);
          return (
            <g strokeLinecap="round">
              <line x1={CX} y1={CY} x2={hx} y2={hy} stroke={C.forest} strokeWidth={16} />
              <line x1={CX} y1={CY} x2={mx} y2={my} stroke={C.forest} strokeWidth={10} />
              <line x1={CX} y1={CY} x2={sx} y2={sy} stroke={C.ec} strokeWidth={4} />
              <circle cx={CX} cy={CY} r={14} fill={C.ec} />
            </g>
          );
        })()}
      </g>
      <Pill x={CX} y={CY + R + 90} text={`now ${props.now}`} size={44} color={C.white} bg={C.forest} opacity={Math.min(1, clockP)} />
      {act && sweepP > 0 ? (
        <text x={CX} y={CY + R + 170} textAnchor="middle" fontSize={34} fontWeight={700} fill={wedgeCol} opacity={sweepP}>{`${props.now} − ${act.at} = ${fmtAge(actAge * sweepP).replace(" old", "")}`}</text>
      ) : null}

      {/* Reading cards */}
      {rs.map((r, i) => (
        <Card key={i} r={r} i={i} at={S(i)} now={props.now} stale={stale} active={i === activeI} y={top + i * (CARD_H + gap)} />
      ))}

      {/* Units check */}
      {props.units && uP > 0.01 ? (
        <g opacity={Math.min(1, uP * 1.4)} transform={`translate(0 ${(1 - uP) * 40})`}>
          <text x={CARD_X} y={unitsY + 30} fontSize={30} fontWeight={800} letterSpacing={3} fill={C.gold}>CHECK THE UNITS</text>
          <rect x={CARD_X} y={unitsY + 50} width={CARD_W} height={90} rx={20} fill={C.white} stroke={C.good} strokeWidth={4} />
          <text x={CARD_X + 40} y={unitsY + 110} fontSize={44} fontWeight={700} fill={C.ink}>{`${props.units.value} ${props.units.unit} × 100 = ${Math.round(parseFloat(props.units.value) * 1000) / 10}%`}</text>
          <Tick x={CARD_X + CARD_W - 60} y={unitsY + 95} s={30} p={interpolate(f, [S(rs.length) + 10, S(rs.length) + 26], [0, 1], clamp)} />
          <rect x={CARD_X} y={unitsY + 155} width={CARD_W} height={90} rx={20} fill={C.white} stroke={C.error} strokeWidth={4} />
          <text x={CARD_X + 40} y={unitsY + 215} fontSize={44} fontWeight={700} fill={C.error}>{`${props.units.value}%`}</text>
          <line x1={CARD_X + 34} x2={CARD_X + 40 + `${props.units.value}%`.length * 27} y1={unitsY + 200} y2={unitsY + 200} stroke={C.error} strokeWidth={5} opacity={interpolate(f, [S(rs.length) + 24, S(rs.length) + 40], [0, 1], clamp)} />
          <text x={CARD_X + 280} y={unitsY + 213} fontSize={32} fontWeight={600} fill={C.muted}>forgot to × 100</text>
          <Cross x={CARD_X + CARD_W - 60} y={unitsY + 200} s={30} p={interpolate(f, [S(rs.length) + 24, S(rs.length) + 40], [0, 1], clamp)} />
        </g>
      ) : null}
    </Svg>
  );
};

export default {
  Component,
  doc: "How old is a reading? A wall clock shows 'now' (sweeping second hand); each probe's reading card slides in with its last-update time, its age counts up quickly ('4 h old', full value ~1.2 s after the card appears), the clock shades the wedge from the reading time to now, and colour runs green → amber → red with a STALE stamp past staleAfter minutes. Optional units check panel: '0.45 m³/m³ × 100 = 45%' ✓ vs '0.45%' ✗. props: {now:'14:00', readings:[{name:'Probe A', at:'10:00', value?:'48%'}, ...], staleAfter?:60 (minutes), units?:{value:'0.45', unit:'m³/m³'}}. steps: one per reading card, then one for the units check.",
  example: { props: { now: "14:00", readings: [{ name: "Probe A", at: "10:00", value: "48%" }, { name: "Probe B", at: "13:59", value: "43%" }], units: { value: "0.45", unit: "m³/m³" } }, steps: [15, 100, 170] },
} satisfies SceneDef<P>;
