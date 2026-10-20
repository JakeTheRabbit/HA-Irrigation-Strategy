import React from "react";
import { interpolate, useCurrentFrame, random, spring, useVideoConfig } from "remotion";
import { C } from "../theme";
import { clamp, stepAt } from "../anim";
import type { SceneDef } from "./kit";
import { Svg, Pill, wave } from "./_measure-shared";

type Spot = "feed" | "bulk" | "pore" | "runoff" | "extract";
type P = { highlight: Spot[]; values?: Partial<Record<Spot, string>>; unit?: string };

const NAMES: Record<Spot, string> = { feed: "Feed EC", bulk: "Bulk EC", pore: "Pore-water EC", runoff: "Runoff EC", extract: "Extract EC" };
const WHERE: Record<Spot, string> = { feed: "tank", bulk: "probe in substrate", pore: "water between pieces", runoff: "drain cup", extract: "lab sample" };

// Geometry.
const TANK = { x: 90, y: 280, w: 250, h: 360 };
const POT = { cx: 900, top: 310, bot: 620, wt: 420, wb: 320 };
const CUP = { cx: 900, top: 690, bot: 810, w: 170 };
const BUB = { x: 1400, y: 300, r: 170 };
const JAR = { cx: 1680, top: 480, bot: 740 };
const LABEL: Record<Spot, [number, number]> = {
  feed: [TANK.x + TANK.w / 2, 740],
  bulk: [520, 390],
  pore: [BUB.x, BUB.y + BUB.r + 62],
  runoff: [640, 770],
  extract: [JAR.cx, 825],
};

const Label: React.FC<{ spot: Spot; p: number; active: boolean; f: number; value?: string; unit: string }> = ({ spot, p, active, f, value, unit }) => {
  const [x, y] = LABEL[spot];
  const s = 0.6 + 0.4 * p;
  const v = value ? `${value} ${unit}` : null;
  return (
    <g opacity={Math.min(1, p * 1.5)} transform={`translate(${x} ${y}) scale(${s * (active ? 1 + 0.025 * wave(f, 34) : 1)})`}>
      <Pill x={0} y={0} text={NAMES[spot]} size={38} color={C.white} bg={active ? C.ec : C.forest} />
      <text x={0} y={64} textAnchor="middle" fontSize={30} fontWeight={600} fill={C.muted}>{WHERE[spot]}</text>
      {v ? <Pill x={0} y={-62} text={v} size={30} color={C.ec} border={C.ec} /> : null}
    </g>
  );
};

const potX = (y: number, side: -1 | 1) => POT.cx + side * (POT.wt / 2 + ((POT.wb - POT.wt) / 2) * ((y - POT.top) / (POT.bot - POT.top)));

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const list = props.highlight ?? [];
  const unit = props.unit ?? "mS/cm";
  const S = (i: number) => stepAt(steps, i, duration, list.length);
  const lit: Record<Spot, number> = { feed: 0, bulk: 0, pore: 0, runoff: 0, extract: 0 };
  let active: Spot | null = null;
  list.forEach((s, i) => {
    lit[s] = spring({ frame: f - S(i), fps, config: { damping: 14, stiffness: 110 } });
    if (f >= S(i)) active = s;
  });
  const dim = (s: Spot) => 0.35 + 0.65 * Math.min(1, lit[s]);
  const intro = interpolate(f, [0, 15], [0, 1], clamp);

  const pipe = `M ${TANK.x + TANK.w - 40} ${TANK.y} V 110 H ${POT.cx} V 200`;
  const potD = `M ${potX(POT.top, -1)} ${POT.top} L ${potX(POT.bot, -1)} ${POT.bot} L ${potX(POT.bot, 1)} ${POT.bot} L ${potX(POT.top, 1)} ${POT.top} Z`;

  // Substrate particles inside the pot.
  const parts = Array.from({ length: 70 }, (_, i) => {
    const y = POT.top + 40 + random(`py${i}`) * (POT.bot - POT.top - 60);
    const l = potX(y, -1) + 22;
    const r = potX(y, 1) - 22;
    return { x: l + random(`px${i}`) * (r - l), y, r: 10 + random(`pr${i}`) * 10 };
  });
  const tap = { x: 1010, y: 470 };
  const bubP = Math.min(1, lit.pore);

  return (
    <Svg>
      <defs>
        <clipPath id="mm-pot">
          <path d={potD} />
        </clipPath>
        <clipPath id="mm-bub">
          <circle cx={BUB.x} cy={BUB.y} r={BUB.r} />
        </clipPath>
        <linearGradient id="mm-sub" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={C.solidLight} />
          <stop offset="1" stopColor={C.solid} />
        </linearGradient>
      </defs>

      <g opacity={intro}>
        {/* Pipe with flowing water */}
        <path d={pipe} fill="none" stroke={C.line} strokeWidth={26} strokeLinejoin="round" />
        <path d={pipe} fill="none" stroke={C.water} strokeWidth={12} strokeLinejoin="round" strokeDasharray="22 18" strokeDashoffset={-f * 3} />
        <rect x={POT.cx - 22} y={196} width={44} height={30} rx={8} fill={C.forest} />
        {Array.from({ length: 3 }, (_, k) => {
          const t = ((f + k * 12) % 36) / 36;
          return <ellipse key={k} cx={POT.cx} cy={232 + t * (POT.top + 30 - 232)} rx={7} ry={11} fill={C.water} opacity={1 - t * 0.5} />;
        })}

        {/* Tank */}
        <g opacity={dim("feed")}>
          <rect x={TANK.x} y={TANK.y} width={TANK.w} height={TANK.h} rx={24} fill={C.white} stroke={C.forest} strokeWidth={6} />
          <path d={`M ${TANK.x + 6} ${TANK.y + 80 + 6 * wave(f, 50)} Q ${TANK.x + TANK.w / 2} ${TANK.y + 66 - 6 * wave(f, 50)} ${TANK.x + TANK.w - 6} ${TANK.y + 80 + 6 * wave(f, 50)} V ${TANK.y + TANK.h - 24} Q ${TANK.x + TANK.w - 6} ${TANK.y + TANK.h - 6} ${TANK.x + TANK.w - 24} ${TANK.y + TANK.h - 6} H ${TANK.x + 24} Q ${TANK.x + 6} ${TANK.y + TANK.h - 6} ${TANK.x + 6} ${TANK.y + TANK.h - 24} Z`} fill={C.water} opacity={0.75} />
          {/* stirring paddle */}
          <line x1={TANK.x + TANK.w / 2} y1={TANK.y - 40} x2={TANK.x + TANK.w / 2} y2={TANK.y + TANK.h - 90} stroke={C.forest} strokeWidth={8} />
          <rect x={TANK.x + TANK.w / 2 - Math.abs(50 * Math.cos(f / 8)) - 4} y={TANK.y + TANK.h - 110} width={Math.abs(100 * Math.cos(f / 8)) + 8} height={36} rx={6} fill={C.forest} />
          {Array.from({ length: 8 }, (_, i) => (
            <circle key={i} cx={TANK.x + 40 + ((i * 29 + f * (1 + (i % 3))) % (TANK.w - 80))} cy={TANK.y + 130 + (i % 4) * 50 + 8 * wave(f, 30, i)} r={7} fill={i % 2 ? C.ec : C.forest} opacity={0.75} />
          ))}
        </g>

        {/* Pot + substrate */}
        <g opacity={Math.max(dim("bulk"), dim("pore"), dim("runoff"))}>
          <ellipse cx={POT.cx} cy={POT.bot + 6} rx={POT.wb / 2 + 50} ry={18} fill={C.forest} opacity={0.15} />
          <path d={potD} fill="#efe3cf" />
          <g clipPath="url(#mm-pot)">
            <rect x={POT.cx - 300} y={POT.top + 90 - 10 * wave(f, 80)} width={600} height={400} fill={C.waterLight} />
            {parts.map((p, i) => (
              <circle key={i} cx={p.x} cy={p.y} r={p.r} fill={i % 3 ? C.solid : C.root} opacity={0.75} />
            ))}
          </g>
          <path d={potD} fill="none" stroke={C.forest} strokeWidth={7} strokeLinejoin="round" />
          <rect x={potX(POT.top, -1) - 16} y={POT.top - 18} width={POT.wt + 32} height={26} rx={10} fill={C.forest} />
          {/* seedling */}
          <g transform={`translate(${POT.cx + 90} ${POT.top - 6}) rotate(${3 * wave(f, 90)})`}>
            <path d="M 0 0 C 0 -40 4 -70 0 -100" stroke={C.plant} strokeWidth={8} fill="none" strokeLinecap="round" />
            <path d="M 0 -70 C -50 -100 -70 -70 -80 -60 C -50 -50 -20 -50 0 -70 Z" fill={C.plant} />
            <path d="M 0 -95 C 40 -130 70 -110 80 -100 C 50 -80 20 -80 0 -95 Z" fill={C.plant} />
          </g>
        </g>

        {/* Probe (bulk EC) */}
        <g opacity={dim("bulk")}>
          <rect x={POT.cx - 150} y={POT.top - 90} width={80} height={60} rx={12} fill={C.forest} />
          {[-28, -8, 12].map((dx, i) => (
            <rect key={i} x={POT.cx - 110 + dx} y={POT.top - 30} width={10} height={170} rx={5} fill="#c9ccd1" stroke={C.muted} strokeWidth={2} />
          ))}
          {lit.bulk > 0 ? <ellipse cx={POT.cx - 110} cy={POT.top + 80} rx={70 + 6 * wave(f, 26)} ry={90 + 6 * wave(f, 26)} fill="none" stroke={C.ec} strokeWidth={4} strokeDasharray="10 10" strokeDashoffset={f} opacity={Math.min(1, lit.bulk)} /> : null}
        </g>

        {/* Runoff: drips into a cup */}
        <g opacity={dim("runoff")}>
          {Array.from({ length: 2 }, (_, k) => {
            const t = ((f + k * 22) % 44) / 44;
            return <ellipse key={k} cx={POT.cx} cy={POT.bot + 10 + t * (CUP.bot - 30 - POT.bot - 10)} rx={7} ry={10} fill={C.water} opacity={1 - t * 0.4} />;
          })}
          <path d={`M ${CUP.cx - CUP.w / 2} ${CUP.top} L ${CUP.cx - CUP.w / 2 + 14} ${CUP.bot} H ${CUP.cx + CUP.w / 2 - 14} L ${CUP.cx + CUP.w / 2} ${CUP.top}`} fill={C.white} stroke={C.forest} strokeWidth={6} strokeLinejoin="round" />
          <path d={`M ${CUP.cx - CUP.w / 2 + 10} ${CUP.top + 50 + 4 * wave(f, 30)} L ${CUP.cx - CUP.w / 2 + 16} ${CUP.bot - 4} H ${CUP.cx + CUP.w / 2 - 16} L ${CUP.cx + CUP.w / 2 - 10} ${CUP.top + 50 - 4 * wave(f, 30)} Z`} fill="#c99a52" opacity={0.6} />
        </g>

        {/* Lab jar */}
        <g opacity={dim("extract")}>
          <path d={`M ${CUP.cx + CUP.w / 2 + 20} ${CUP.top + 20} C 1200 800, 1400 760, ${JAR.cx - 135} ${JAR.bot - 70}`} fill="none" stroke={C.gold} strokeWidth={5} strokeDasharray="4 14" strokeLinecap="round" strokeDashoffset={-f * 1.2} />
          <path d={`M ${JAR.cx - 50} ${JAR.top} V ${JAR.top + 80} L ${JAR.cx - 120} ${JAR.bot - 20} Q ${JAR.cx - 125} ${JAR.bot} ${JAR.cx - 100} ${JAR.bot} H ${JAR.cx + 100} Q ${JAR.cx + 125} ${JAR.bot} ${JAR.cx + 120} ${JAR.bot - 20} L ${JAR.cx + 50} ${JAR.top + 80} V ${JAR.top} Z`} fill={C.white} stroke={C.forest} strokeWidth={6} strokeLinejoin="round" />
          <path d={`M ${JAR.cx - 88} ${JAR.bot - 90 + 4 * wave(f, 40)} L ${JAR.cx - 114} ${JAR.bot - 18} Q ${JAR.cx - 116} ${JAR.bot - 6} ${JAR.cx - 98} ${JAR.bot - 6} H ${JAR.cx + 98} Q ${JAR.cx + 116} ${JAR.bot - 6} ${JAR.cx + 114} ${JAR.bot - 18} L ${JAR.cx + 88} ${JAR.bot - 90 - 4 * wave(f, 40)} Z`} fill={C.ec} opacity={0.55} />
          <rect x={JAR.cx - 64} y={JAR.top - 18} width={128} height={22} rx={8} fill={C.forest} />
          {Array.from({ length: 3 }, (_, k) => {
            const t = ((f + k * 25) % 75) / 75;
            return <circle key={k} cx={JAR.cx - 30 + k * 30} cy={JAR.bot - 30 - t * 70} r={6} fill={C.white} opacity={Math.sin(t * Math.PI) * 0.8} />;
          })}
        </g>
      </g>

      {/* Zoom bubble: pore water between particles */}
      {bubP > 0 ? (
        <g opacity={bubP}>
          <path d={`M ${tap.x} ${tap.y} L ${BUB.x - BUB.r * 0.8} ${BUB.y + BUB.r * 0.6} M ${tap.x} ${tap.y} L ${BUB.x - BUB.r * 0.25} ${BUB.y + BUB.r * 0.97}`} stroke={C.forest} strokeWidth={3} strokeDasharray="8 8" opacity={0.6} />
          <circle cx={tap.x} cy={tap.y} r={30} fill="none" stroke={C.forest} strokeWidth={4} />
          <g transform={`translate(${BUB.x} ${BUB.y}) scale(${bubP}) translate(${-BUB.x} ${-BUB.y})`}>
            <circle cx={BUB.x} cy={BUB.y} r={BUB.r + 10} fill={C.white} />
            <g clipPath="url(#mm-bub)">
              <rect x={BUB.x - BUB.r} y={BUB.y - BUB.r} width={BUB.r * 2} height={BUB.r * 2} fill={C.water} opacity={0.55} />
              {Array.from({ length: 5 }, (_, i) => (
                <circle key={`a${i}`} cx={BUB.x - 120 + random(`ax${i}`) * 240} cy={BUB.y - 120 + random(`ay${i}`) * 240} r={18 + 6 * random(`ar${i}`)} fill={C.white} opacity={0.9} />
              ))}
              {[[-90, -80, 62], [40, -105, 58], [120, 0, 55], [-20, 10, 52], [-120, 75, 58], [60, 110, 64], [-30, 150, 40], [150, -110, 40]].map(([dx, dy, r], i) => (
                <circle key={i} cx={BUB.x + dx} cy={BUB.y + dy} r={r} fill={i % 3 ? C.solid : C.root} />
              ))}
              {Array.from({ length: 10 }, (_, i) => {
                const a = random(`ia${i}`) * Math.PI * 2;
                const rr = 30 + random(`ir${i}`) * 130;
                return <circle key={`i${i}`} cx={BUB.x + Math.cos(a) * rr + 10 * wave(f, 40 + i * 5, i)} cy={BUB.y + Math.sin(a) * rr + 8 * wave(f, 50 + i * 3, i * 2)} r={7} fill={i % 2 ? C.ec : C.forest} />;
              })}
            </g>
            <circle cx={BUB.x} cy={BUB.y} r={BUB.r} fill="none" stroke={C.forest} strokeWidth={7} />
          </g>
        </g>
      ) : null}

      {/* Labels */}
      {(Object.keys(NAMES) as Spot[]).map((s) =>
        lit[s] > 0 ? <Label key={s} spot={s} p={lit[s]} active={active === s} f={f} value={props.values?.[s]} unit={unit} /> : null,
      )}
      {/* Unlit spots get a faint placeholder dot */}
      {(Object.keys(NAMES) as Spot[]).map((s) =>
        lit[s] <= 0 && s !== "pore" ? <circle key={`d${s}`} cx={LABEL[s][0]} cy={LABEL[s][1]} r={10 + 3 * wave(f, 30)} fill={C.line} opacity={intro} /> : null,
      )}
    </Svg>
  );
};

export default {
  Component,
  doc: "Where an EC reading came from: side view of the water's journey — mixing tank (feed EC) → pipe and dripper → pot with a probe in the substrate (bulk EC; a zoom bubble shows the water between substrate pieces = pore-water EC) → drain cup (runoff EC) → lab jar (extract EC). Water flows continuously; each place lights up with a label (and optional value) at its step, the latest one pulsing orange; unlit places stay dimmed. props: {highlight:['feed','bulk','pore','runoff','extract'] (any subset, in reveal order), values?:{feed:'2.0', runoff:'2.4', ...}, unit?:'mS/cm'}. steps: one per highlight entry.",
  example: { props: { highlight: ["feed", "bulk", "pore", "runoff", "extract"], values: { feed: "2.0", runoff: "2.4" } }, steps: [10, 50, 90, 135, 175] },
} satisfies SceneDef<P>;
