import React from "react";
import { useCurrentFrame } from "remotion";
import { C } from "../theme";
import { type SceneDef } from "./kit";
import { SvgStage, Defs, T, Pill, Pop, Card, Flow, Pulses, Drips, Led, HaMark, ease, pop, at, type Pt } from "./_system-shared";

type Key = "host" | "integration" | "controller" | "probe" | "bridge" | "switch" | "shutdown" | "supply";
type P = { highlight?: Key[]; showDataFlow?: boolean };

const DATA_IN: Pt[] = [[362, 330], [700, 330]];
const DATA_OUT: Pt[] = [[1252, 400], [1520, 400]];
const TO_VALVE: Pt[] = [[1670, 520], [1670, 760]];
const PIPE: Pt[] = [[600, 830], [1640, 830], [1700, 830], [1760, 830]];

// The five jobs of an automated system as connected cards, with live data flow.
const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const flowOn = props.showDataFlow !== false;
  const n = 5 + (flowOn ? 1 : 0);
  const s = [0, 1, 2, 3, 4].map((i) => at(steps, i, duration, n));
  const dataAt = at(steps, 5, duration, n);
  const hl = props.highlight ?? [];
  const lit = (k: Key) => hl.includes(k);
  const dim = (k: Key | Key[]) => hl.length > 0 && !(Array.isArray(k) ? k.some(lit) : lit(k));
  const pPlan = pop(f, s[0]), pMeas = pop(f, s[1]), pSup = pop(f, s[2]), pSw = pop(f, s[3]), pProt = pop(f, s[4]);
  const data = flowOn ? ease(f, dataAt, 16) : 0;
  const waterOn = data > 0 && Math.floor(f / 60) % 2 === 0 ? 1 : 0; // valve opens for alternate 2 s windows once data flows
  const water = data * waterOn;

  return (
    <SvgStage>
      <Defs />
      {/* connecting lines (static, under cards) */}
      <g opacity={Math.min(pMeas, pPlan)}>
        <line x1={DATA_IN[0][0]} y1={330} x2={700} y2={330} stroke={C.line} strokeWidth={8} strokeLinecap="round" />
      </g>
      <g opacity={Math.min(pSw, pPlan)}>
        <line x1={1252} y1={400} x2={1520} y2={400} stroke={C.line} strokeWidth={8} strokeLinecap="round" />
      </g>
      <g opacity={Math.min(pSw, pSup)}>
        <line x1={1670} y1={520} x2={1670} y2={760} stroke={C.line} strokeWidth={8} strokeLinecap="round" />
      </g>

      {/* PLAN: host computer with Home Assistant, integration + Controller inside */}
      <Pop x={960} y={300} s={pPlan}>
        <Card x={640} y={30} w={640} h={530} title="PLAN" dim={dim(["host", "integration", "controller"])} glow={lit("host")}>
          <T x={1252} y={68} size={30} anchor="end" fill={C.muted} weight={600}>Host computer</T>
          <rect x={664} y={96} width={592} height={440} rx={20} fill={C.leaf} />
          <HaMark x={712} y={140} s={0.9} />
          <T x={752} y={142} anchor="start" size={34}>Home Assistant</T>
          <Led x={1226} y={140} f={f} period={40} />
          {/* integration */}
          <g opacity={dim("integration") && !dim("host") ? 0.45 : 1}>
            {lit("integration") ? <rect x={672} y={182} width={278} height={346} rx={22} fill="none" stroke={C.gold} strokeWidth={7} /> : null}
            <rect x={682} y={192} width={258} height={326} rx={18} fill={C.white} stroke={C.forest} strokeWidth={4} />
            <rect x={722} y={222} width={178} height={110} rx={10} fill={C.paper} stroke={C.forest} strokeWidth={3} />
            <path d={`M736 310 ${Array.from({ length: 7 }, (_, i) => `L${736 + i * 25} ${300 - 30 * Math.abs(Math.sin((f + i * 12) / 22))}`).join(" ")}`} stroke={C.water} strokeWidth={5} fill="none" strokeLinejoin="round" />
            <T x={811} y={380} size={32}>Crop Steering</T>
            <T x={811} y={418} size={32}>integration</T>
            <T x={811} y={470} size={30} weight={500} fill={C.muted}>screens + data</T>
          </g>
          {/* controller */}
          <g opacity={dim("controller") && !dim("host") ? 0.45 : 1}>
            {lit("controller") ? <rect x={970} y={182} width={278} height={346} rx={22} fill="none" stroke={C.gold} strokeWidth={7} /> : null}
            <rect x={980} y={192} width={258} height={326} rx={18} fill={C.white} stroke={C.forest} strokeWidth={4} />
            <Gear x={1109} y={278} r={52} rot={f * 2} />
            <T x={1109} y={380} size={32}>Controller</T>
            <T x={1109} y={418} size={32}>app</T>
            <T x={1109} y={470} size={30} weight={500} fill={C.muted}>decides shots</T>
          </g>
          {data > 0 ? (
            <g opacity={data}>
              <Pulses pts={[[942, 300], [978, 300]]} f={f} n={1} period={24} color={C.ec} r={7} />
              <Pulses pts={[[978, 340], [942, 340]]} f={f + 12} n={1} period={24} color={C.water} r={7} />
            </g>
          ) : null}
        </Card>
      </Pop>
      <Pill x={960} y={606} w={760} text="Two separate parts, both on the host" color={C.forest} size={32} opacity={ease(f, s[0] + 14, 18) * (hl.length && !lit("integration") && !lit("controller") && !lit("host") ? 0.35 : 1)} />

      {/* MEASURE: probe in a pot (+ optional bridge between card and host) */}
      <Pop x={250} y={300} s={pMeas}>
        <Card x={60} y={30} w={380} h={530} title="MEASURE" dim={dim(["probe", "bridge"]) } glow={lit("probe")}>
          <path d="M140 280 L360 280 L336 500 L164 500 Z" fill={C.forest} />
          <path d="M150 294 L350 294 L344 340 L156 340 Z" fill={C.solidLight} />
          <path d="M210 294 q-8 -60 -60 -80 q50 0 62 44 q6 -60 52 -76 q-40 30 -54 112" fill={C.plant} />
          <rect x={276} y={200} width={36} height={56} rx={8} fill={C.ec} stroke={C.forest} strokeWidth={3} />
          {[0, 1, 2].map((i) => <rect key={i} x={280 + i * 11} y={256} width={6} height={110} fill="#7d8a83" />)}
          <path d="M294 200 Q294 160 330 160 L362 160 L362 330" stroke={C.forest} strokeWidth={6} fill="none" />
          <Led x={294} y={228} f={f} color={C.water} period={20} r={6} />
          <T x={250} y={530} size={30}>Moisture / EC probe</T>
        </Card>
      </Pop>
      {/* bridge */}
      <Pop x={540} y={330} s={pop(f, s[1] + 8)}>
        <g opacity={dim("bridge") ? 0.35 : 1}>
          {lit("bridge") ? <rect x={474} y={280} width={132} height={100} rx={22} fill="none" stroke={C.gold} strokeWidth={7} /> : null}
          <rect x={484} y={290} width={112} height={80} rx={16} fill={C.white} stroke={C.forest} strokeWidth={4} />
          <path d="M520 290 L510 250 M560 290 L570 250" stroke={C.forest} strokeWidth={4} />
          <Led x={540} y={330} f={f} color={C.ec} period={16} phase={4} r={8} />
          <T x={540} y={418} size={30}>Bridge</T>
          <T x={540} y={454} size={30} weight={500} fill={C.muted}>(optional)</T>
        </g>
      </Pop>

      {/* SWITCH: relay / valve control */}
      <Pop x={1670} y={300} s={pSw}>
        <Card x={1480} y={30} w={380} h={530} title="SWITCH" dim={dim("switch")} glow={lit("switch")}>
          <rect x={1560} y={150} width={220} height={190} rx={18} fill={C.leaf} stroke={C.forest} strokeWidth={4} />
          <rect x={1590} y={182} width={70} height={110} rx={8} fill={C.white} stroke={C.forest} strokeWidth={3} />
          {[0, 1, 2, 3, 4].map((i) => <line key={i} x1={1598} x2={1652} y1={196 + i * 20} y2={196 + i * 20} stroke={C.ec} strokeWidth={5} />)}
          <path d={`M1690 ${water ? 214 : 196} L1748 214`} stroke={C.forest} strokeWidth={6} strokeLinecap="round" />
          <circle cx={1690} cy={214} r={7} fill={C.forest} />
          <circle cx={1752} cy={214} r={7} fill={C.forest} />
          <Led x={1720} y={290} f={f} on={water > 0} color={C.good} period={10} r={10} />
          <T x={1670} y={400} size={32}>Relay</T>
          <T x={1670} y={440} size={30} weight={500} fill={C.muted}>switches the valve</T>
        </Card>
      </Pop>

      {/* SUPPLY: water path */}
      <Pop x={1140} y={810} s={pSup}>
        <Card x={430} y={680} w={1430} h={280} title="SUPPLY" dim={dim("supply")} glow={lit("supply")}>
          <path d="M600 830 L1760 830" stroke="#a9b4ab" strokeWidth={26} />
          <path d="M600 830 L1760 830" stroke="#dfe6dc" strokeWidth={12} />
          {water > 0 ? <Flow pts={PIPE} f={f} color={C.water} width={12} speed={5} opacity={water} /> : null}
          <rect x={470} y={740} width={130} height={180} rx={16} fill={C.white} stroke={C.forest} strokeWidth={4} />
          <rect x={474} y={790 + Math.sin(f / 10) * 4} width={122} height={126} rx={12} fill={C.waterLight} />
          <T x={1000} y={890} size={30} weight={500} fill={C.muted}>tank → pump → filter → valve → dripper</T>
          {[800, 960, 1120].map((x) => <rect key={x} x={x - 26} y={812} width={52} height={36} rx={8} fill={C.white} stroke={C.forest} strokeWidth={3} />)}
          <path d="M1640 808 L1670 830 L1640 852 Z M1700 808 L1670 830 L1700 852 Z" fill={water ? C.good : C.forest} />
          <rect x={1656} y={764} width={28} height={44} rx={5} fill={C.forest} />
          <rect x={1764} y={760} width={20} height={70} fill="#a9b4ab" />
          <Drips x={1774} y0={846} y1={920} f={f} rate={water} />
        </Card>
      </Pop>

      {/* PROTECT: physical shutdown + independent protection */}
      <Pop x={225} y={810} s={pProt}>
        <Card x={60} y={680} w={330} h={280} title="PROTECT" color={C.error} dim={dim("shutdown")} glow={lit("shutdown")}>
          <rect x={92} y={746} width={110} height={130} rx={14} fill={C.white} stroke={C.error} strokeWidth={4} />
          <circle cx={147} cy={811} r={34} fill={C.error} />
          <rect x={141} y={779} width={12} height={64} rx={4} fill={C.white} transform={`rotate(${90} 147 811)`} />
          <ShieldMark x={300} y={808} f={f} />
          <T x={225} y={918} size={30}>Physical shutdown</T>
        </Card>
      </Pop>
      <g opacity={pProt * (dim("shutdown") ? 0.35 : 1)}>
        <path d="M390 840 L430 840" stroke={C.error} strokeWidth={5} strokeDasharray="10 8" />
      </g>

      {/* live data */}
      {data > 0 ? (
        <g opacity={data}>
          <Pulses pts={DATA_IN} f={f} n={3} period={50} color={C.water} />
          <Pulses pts={DATA_OUT} f={f} n={2} period={40} color={C.ec} />
          <Pulses pts={TO_VALVE} f={f} n={2} period={40} color={C.ec} opacity={water ? 1 : 0.35} />
          <Pill x={540} y={190} w={190} text="readings" color={C.water} size={30} />
          <Pill x={1386} y={340} w={200} text="commands" color={C.ec} size={30} />
        </g>
      ) : null}
    </SvgStage>
  );
};

const Gear: React.FC<{ x: number; y: number; r: number; rot: number }> = ({ x, y, r, rot }) => (
  <g transform={`rotate(${rot} ${x} ${y})`}>
    {Array.from({ length: 8 }, (_, i) => (
      <rect key={i} x={x - r * 0.18} y={y - r * 1.12} width={r * 0.36} height={r * 0.4} rx={4} fill={C.forest} transform={`rotate(${i * 45} ${x} ${y})`} />
    ))}
    <circle cx={x} cy={y} r={r * 0.82} fill={C.forest} />
    <circle cx={x} cy={y} r={r * 0.34} fill={C.white} />
  </g>
);

const ShieldMark: React.FC<{ x: number; y: number; f: number }> = ({ x, y, f }) => (
  <g>
    <circle cx={x} cy={y} r={46 + 6 * Math.sin(f / 12)} fill={C.error} opacity={0.1} />
    <path d={`M${x} ${y - 40} L${x + 34} ${y - 26} L${x + 30} ${y + 12} Q${x + 22} ${y + 34} ${x} ${y + 44} Q${x - 22} ${y + 34} ${x - 30} ${y + 12} L${x - 34} ${y - 26} Z`} fill={C.white} stroke={C.error} strokeWidth={4} />
    <path d={`M${x - 14} ${y + 2} L${x - 3} ${y + 14} L${x + 16} ${y - 10}`} stroke={C.error} strokeWidth={6} fill="none" strokeLinecap="round" strokeLinejoin="round" />
  </g>
);

export default {
  Component,
  doc: "The five jobs of an automated system as connected cards: PLAN (host computer running Home Assistant, containing two SEPARATE boxes — the Crop Steering integration and the Controller app — with a 'Two separate parts, both on the host' pill), MEASURE (moisture/EC probe in a pot + optional bridge), SUPPLY (tank → valve → dripper), SWITCH (relay), PROTECT (physical shutdown + independent protection). Data pulses run probe → bridge → integration ↔ controller → relay → valve, and the valve opens/drips in 2 s cycles. props: {highlight?:('host'|'integration'|'controller'|'probe'|'bridge'|'switch'|'shutdown'|'supply')[] (others dim, highlighted get a gold ring), showDataFlow?:true}. steps: [plan, measure, supply, switch, protect, data flow starts].",
  example: { props: { highlight: [], showDataFlow: true }, steps: [6, 30, 54, 78, 102, 126] },
} satisfies SceneDef<P>;
