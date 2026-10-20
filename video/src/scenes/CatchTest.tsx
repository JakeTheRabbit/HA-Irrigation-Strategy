import React from "react";
import { useCurrentFrame } from "remotion";
import { C, SERIF } from "../theme";
import { stepAt } from "../anim";
import { type SceneDef } from "./kit";
import { Svg, T, Drips, Stopwatch, Cup, Tick, Eye, SvgChip, ease, lin } from "./_watering-shared";

type P = { cups: number[]; seconds: number; otherZonesDry?: boolean; showStop?: boolean; decimals?: number };

const RISER_X = 250;
const VALVE_X = 350;
const PIPE_END = 1080;
const Z1 = 210; // active zone pipe
const ZONES = [Z1, 720, 860];
const CUP_BOTTOM = 540, CUP_H = 150;

const Valve: React.FC<{ x: number; y: number; open: number }> = ({ x, y, open }) => (
  <g transform={`translate(${x},${y})`}>
    <circle r={30} fill={open > 0.5 ? C.good : C.error} stroke={C.forest} strokeWidth={5} />
    <g transform={`rotate(${90 * (1 - open)})`}>
      <rect x={-46} y={-8} width={92} height={16} rx={8} fill={C.forest} />
    </g>
    <circle r={8} fill={C.white} />
  </g>
);

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const { cups, seconds, otherZonesDry = true, showStop = true } = props;
  const at = (i: number) => Math.max(i === 0 ? 14 : 0, stepAt(steps, i, duration, 4));
  const tOpen = at(0), tDry = at(1), tStop = Math.max(at(2), tOpen + 40), tConv = at(3);

  const open = ease(f, tOpen, tOpen + 12) * (showStop ? 1 - ease(f, tStop, tStop + 12) : 1);
  const run = lin(f, tOpen + 6, tStop);
  const running = open > 0.5 && run < 1;
  const flowEnd = showStop ? tStop + 6 : 1e9;
  const cap = Math.max(...cups) * 1.25;
  const n = cups.length;
  const cx = (j: number) => 520 + (j * (PIPE_END - 120 - 520)) / Math.max(1, n - 1);
  const lphs = cups.map((ml) => (ml / 1000) * 3600 / seconds);
  const dryP = ease(f, tDry, tDry + 14);
  const stopP = ease(f, tStop + 14, tStop + 30);
  const conv = (i: number) => ease(f, tConv + i * 10, tConv + i * 10 + 14);
  const flow = -f * 6;
  const intro = ease(f, 0, 14);
  const spread = Math.max(...lphs) / Math.min(...lphs) > 1.1;

  const pipe = (x1: number, y1: number, x2: number, y2: number, wet: boolean, key: string) => (
    <g key={key}>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#5d6b64" strokeWidth={24} strokeLinecap="round" />
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={wet ? C.waterLight : "#8b9891"} strokeWidth={10} strokeLinecap="round" strokeDasharray={wet ? "22 14" : undefined} strokeDashoffset={wet ? flow : 0} />
    </g>
  );

  return (
    <>
      <Svg>
        {/* Supply tank */}
        <g opacity={intro}>
          <rect x={60} y={360} width={150} height={220} rx={18} fill={C.white} stroke={C.forest} strokeWidth={5} />
          <rect x={66} y={420 + Math.sin(f / 10) * 3} width={138} height={154} rx={12} fill={C.water} opacity={0.75} />
          <T x={135} y={630} size={32} weight={700} fill={C.forest} anchor="middle">Supply</T>
        </g>
        {pipe(210, 500, RISER_X, 500, true, "feed")}
        {pipe(RISER_X, Z1, RISER_X, ZONES[2], true, "riser")}

        {/* Zones: zone 1 runs, the others stay shut */}
        {ZONES.map((y, z) => {
          const active = z === 0;
          const wet = active && open > 0.5;
          return (
            <g key={z} opacity={intro}>
              {pipe(RISER_X, y, VALVE_X - 30, y, true, `a${z}`)}
              {pipe(VALVE_X + 30, y, PIPE_END, y, wet, `b${z}`)}
              <Valve x={VALVE_X} y={y} open={active ? open : 0} />
              <T x={VALVE_X + 60} y={y - 34} size={32} weight={800} fill={active ? C.forest : C.muted}>Zone {z + 1}</T>
              {Array.from({ length: n }, (_, j) => (
                <g key={j} transform={`translate(${cx(j)},${y})`}>
                  <rect x={-12} y={10} width={24} height={26} rx={6} fill="#27302c" />
                  <rect x={-4} y={34} width={8} height={9} rx={2} fill="#27302c" />
                </g>
              ))}
              {!active && otherZonesDry ? (
                <g>
                  <Tick x={PIPE_END + 60} y={y} r={28} p={dryP} />
                  <T x={PIPE_END + 100} y={y + 11} size={32} weight={700} fill={C.good} opacity={dryP}>dry</T>
                </g>
              ) : null}
            </g>
          );
        })}
        <SvgChip x={VALVE_X} y={Z1 + 70} text={open > 0.5 ? "OPEN" : "CLOSED"} color={open > 0.5 ? C.good : C.error} size={30} />

        {/* Zone 1 catch cups */}
        {cups.map((ml, j) => {
          const cur = ml * run;
          return (
            <g key={j}>
              <Drips x={cx(j)} y0={Z1 + 48} y1={CUP_BOTTOM - CUP_H * (cur / cap) * 0.92} period={11} offset={j * 4} start={tOpen + 8} end={flowEnd} r={9} fall={12} />
              <Cup id={`ct${j}`} x={cx(j)} y={CUP_BOTTOM} w={110} h={CUP_H} level={cur / cap} />
              <T x={cx(j)} y={CUP_BOTTOM + 52} size={44} weight={800} fill={C.forest} anchor="middle">{Math.round(cur)} mL</T>
            </g>
          );
        })}

        {/* Stop check: eye on the outlet */}
        {showStop ? (
          <g opacity={stopP}>
            <line x1={cx(0) + 92} y1={Z1 - 66} x2={cx(0) + 10} y2={Z1 + 40} stroke={C.good} strokeWidth={4} strokeDasharray="8 8" strokeDashoffset={-f} />
            <line x1={cx(0) + 92} y1={Z1 - 66} x2={cx(0) + 10} y2={Z1 + 40} stroke={C.good} strokeWidth={4} strokeDasharray="8 8" strokeDashoffset={-f} />
            <Eye x={cx(0) + 120} y={Z1 - 90} size={44} lx={-0.8} ly={0.6} />
            <SvgChip x={cx(0) + 190} y={Z1 - 90} anchor="start" text="water stopped" color={C.good} size={32} />
            <Tick x={cx(0) + 190 + 13 * 32 * 0.56 + 32 * 1.3 + 36} y={Z1 - 90} r={24} p={stopP} />
          </g>
        ) : null}

        {/* Stopwatch */}
        <Stopwatch x={1500} y={190} r={110} elapsed={seconds * run} running={running} />
        <T x={1660} y={180} size={32} fill={C.muted}>timed run</T>
        <T x={1660} y={228} size={44} weight={800} fill={C.forest}>{seconds} s</T>
      </Svg>

      {/* mL → L/h conversion */}
      <div style={{ position: "absolute", left: 1250, right: 60, top: 360, height: 600, boxSizing: "border-box", background: C.white, border: `3px solid ${C.line}`, borderRadius: 28, padding: "26px 34px", display: "flex", flexDirection: "column", gap: 14, opacity: conv(0) }}>
        <div style={{ fontSize: 34, fontWeight: 800, color: C.forest }}>Cup → flow rate</div>
        <div style={{ fontFamily: SERIF, fontSize: 38, color: C.muted }}>mL ÷ 1000 × 3600 ÷ {seconds} s</div>
        {cups.map((ml, j) => (
          <div key={j} style={{ opacity: conv(j + 1), transform: `translateX(${(1 - conv(j + 1)) * 24}px)`, display: "flex", alignItems: "baseline", gap: 18, fontSize: 46, borderTop: `2px solid ${C.leaf}`, paddingTop: 10 }}>
            <span style={{ color: C.muted, fontSize: 32, width: 92 }}>Cup {j + 1}</span>
            <span style={{ fontWeight: 700, color: C.ink, width: 140 }}>{ml} mL</span>
            <span style={{ color: C.muted }}>→</span>
            <span style={{ fontWeight: 800, color: C.water }}>{lphs[j].toFixed(props.decimals ?? 2)} L/h</span>
          </div>
        ))}
        {spread ? (
          <div style={{ opacity: conv(n + 1), marginTop: "auto", alignSelf: "flex-start", background: "#fbefd9", color: C.warn, border: `3px solid ${C.warn}`, borderRadius: 999, padding: "8px 24px", fontSize: 30, fontWeight: 700 }}>
            Uneven delivery: check each dripper
          </div>
        ) : null}
      </div>
    </>
  );
};

export default {
  Component,
  doc: "Commissioning catch test: supply → riser → three zone valves; zone 1's valve opens, water runs through its drippers into separate catch cups while a stopwatch times the run and each cup counts up in mL; the other zones get green 'dry' ticks; the valve closes and an eye checks the outlet ('water stopped ✓'); a card converts each cup mL → L/h (mL ÷ 1000 × 3600 ÷ s) and flags uneven delivery. props: {cups:[30,33,37], seconds:30, otherZonesDry?:true, showStop?:true, decimals?:2 (L/h decimals; 1 gives '3.6')}. steps: [valve opens / run starts, other zones stay dry, valve closes + stop check (run ends here), convert cups to L/h].",
  example: { props: { cups: [30, 33, 37], seconds: 30, otherZonesDry: true, showStop: true }, steps: [15, 70, 120, 165] },
} satisfies SceneDef<P>;
