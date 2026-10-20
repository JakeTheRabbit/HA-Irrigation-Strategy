import React from "react";
import { useCurrentFrame } from "remotion";
import { C } from "../theme";
import { type SceneDef } from "./kit";
import { SvgStage, Defs, T, Pill, Pop, Flow, Pulses, Drips, Check, Led, ease, pop, at, type Pt } from "./_system-shared";

type St = "software" | "bypass" | "physical";
type P = { stages?: St[]; room?: string };

const CTRL_LINE: Pt[] = [[800, 640], [1160, 640]];
const TIMER_LINE: Pt[] = [[1080, 250], [1250, 250], [1250, 550]];
const POWER_A: Pt[] = [[1650, 200], [1650, 340]];
const POWER_B: Pt[] = [[1650, 470], [1650, 640], [1340, 640]];
const WATER: Pt[] = [[1250, 730], [1250, 860], [1790, 860], [1790, 900]];
const PUMP: Pt = [1250, 640];

// Software "Watering OFF" vs physical isolation: another timer can still run the pump until it is isolated.
const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const stages: St[] = props.stages?.length ? props.stages : ["software", "bypass", "physical"];
  const st = {} as Record<St, number>;
  stages.forEach((s, i) => (st[s] = at(steps, i, duration, stages.length, 20)));
  const has = (s: St) => s in st;
  // Physical-only: drop the phone + Controller and show the isolation panel large and centred.
  const solo = has("physical") && !has("software") && !has("bypass");
  const tSoft = st.software ?? -1;
  const tByp = st.bypass ?? 1e9;
  const tPhys = st.physical ?? 1e9;

  const softOff = f >= tSoft; // watering switch OFF
  const toggle = has("software") ? ease(f, tSoft, 10) : 1;
  const timerActive = has("bypass") && f >= tByp;
  const isolated = has("physical") && f >= tPhys;
  const iso = isolated ? ease(f, tPhys, 14) : 0;
  const ctrlDriving = !softOff;
  const pumpOn = !isolated && (ctrlDriving || timerActive);
  const spin = pumpOn ? 1 : 0;
  const phase: St | "start" = isolated ? "physical" : timerActive ? "bypass" : softOff && has("software") ? "software" : "start";

  const verdict = {
    start: { t: solo ? "Power is still live to the pump" : "Watering ON: the Controller runs the pump", c: solo ? C.error : C.forest },
    software: { t: "Watering OFF: the Controller stops its shots", c: C.forest },
    bypass: { t: "But another timer can still run the pump!", c: C.error },
    physical: { t: "Isolated and locked: the hazard is removed", c: C.good },
  }[phase];

  return (
    <SvgStage>
      <Defs />
      {!solo ? (
      <g>
      {/* PHONE */}
      <Pop x={240} y={380} s={pop(f, 0)}>
        <rect x={90} y={40} width={300} height={600} rx={44} fill={C.forest} filter="url(#sh)" />
        <rect x={108} y={86} width={264} height={510} rx={20} fill={C.white} />
        <rect x={200} y={58} width={80} height={12} rx={6} fill="#3a5a50" />
        <T x={240} y={136} size={30} fill={C.muted} weight={600}>{props.room ?? "Room A"}</T>
        <T x={240} y={230} size={34}>Watering</T>
        <g transform="translate(240 310)">
          <rect x={-80} y={-40} width={160} height={80} rx={40} fill={toggle > 0.5 ? "#c9d0c8" : C.good} />
          <circle cx={46 - 92 * toggle} cy={0} r={32} fill={C.white} stroke="#9aa59d" strokeWidth={2} />
        </g>
        <T x={240} y={400} size={44} fill={toggle > 0.5 ? C.error : C.good}>{toggle > 0.5 ? "OFF" : "ON"}</T>
        <rect x={130} y={460} width={220} height={100} rx={16} fill={C.leaf} />
        <T x={240} y={494} size={30} weight={600}>a request</T>
        <T x={240} y={532} size={30} weight={600}>to software</T>
      </Pop>
      <path d="M392 330 L650 330 L650 566" stroke={C.forest} strokeWidth={6} fill="none" strokeDasharray="4 14" strokeLinecap="round" />
      <path d="M636 548 L650 568 L664 548" stroke={C.forest} strokeWidth={6} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <Pulses pts={[[392, 330], [650, 330], [650, 566]]} f={f} n={2} period={50} color={C.forest} r={9} />

      {/* CONTROLLER */}
      <Pop x={650} y={640} s={pop(f, 4)}>
        <rect x={500} y={570} width={300} height={140} rx={24} fill={C.forest} filter="url(#sh)" />
        <T x={650} y={616} size={32} fill={C.white}>Controller</T>
        {softOff && has("software") ? (
          <g>
            <rect x={622} y={644} width={14} height={40} rx={4} fill={C.gold} />
            <rect x={664} y={644} width={14} height={40} rx={4} fill={C.gold} />
          </g>
        ) : (
          <Led x={650} y={666} f={f} color={C.good} period={12} r={12} />
        )}
        <T x={650} y={760} size={30} fill={softOff && has("software") ? C.muted : C.good}>{softOff && has("software") ? "no shots" : "running shots"}</T>
      </Pop>
      <path d={`M800 640 L1160 640`} stroke={ctrlDriving ? C.good : C.line} strokeWidth={8} strokeLinecap="round" />
      {ctrlDriving ? <Pulses pts={CTRL_LINE} f={f} n={3} period={36} color={C.good} /> : null}
      {softOff && has("software") ? (
        <Pop x={960} y={640} s={pop(f, tSoft + 4)}>
          <rect x={948} y={596} width={24} height={88} rx={6} fill={C.error} />
        </Pop>
      ) : null}
      </g>
      ) : null}

      <g transform={solo ? "translate(" + (960 - 1385 * 0.92) + " " + (10 - 40 * 0.92) + ") scale(0.92)" : undefined}>
      {/* OLD TIMER (bypass) */}
      {has("bypass") ? (
        <Pop x={960} y={250} s={pop(f, tByp)}>
          <rect x={840} y={130} width={240} height={240} rx={28} fill={C.white} stroke={timerActive ? C.error : C.forest} strokeWidth={5} filter="url(#sh)" />
          <circle cx={960} cy={250} r={86} fill={C.paper} stroke={C.forest} strokeWidth={4} />
          {Array.from({ length: 12 }, (_, i) => <rect key={i} x={956} y={170} width={8} height={18} rx={2} fill={C.ec} transform={`rotate(${i * 30} 960 250)`} />)}
          <line x1={960} y1={250} x2={960} y2={192} stroke={C.forest} strokeWidth={7} strokeLinecap="round" transform={`rotate(${f * 4} 960 250)`} />
          <circle cx={960} cy={250} r={9} fill={C.forest} />
          <T x={960} y={94} size={34}>Old timer</T>
        </Pop>
      ) : null}
      {timerActive ? (
        <g>
          <path d="M1080 250 L1250 250 L1250 550" stroke={C.error} strokeWidth={8} fill="none" strokeLinejoin="round" />
          <Pulses pts={TIMER_LINE} f={f} n={3} period={36} color={C.error} opacity={isolated ? 0.4 : 1} />
        </g>
      ) : null}

      {/* POWER + ISOLATOR */}
      <Pop x={1650} y={150} s={pop(f, 6)}>
        <rect x={1570} y={100} width={160} height={100} rx={18} fill={C.white} stroke={C.forest} strokeWidth={4} filter="url(#sh)" />
        <path d="M1646 116 L1626 152 L1648 152 L1636 186 L1670 140 L1648 140 L1662 116 Z" fill={C.ec} />
        <T x={1650} y={70} size={30} fill={C.muted} weight={600}>Power</T>
      </Pop>
      <path d="M1650 200 L1650 340" stroke={C.ec} strokeWidth={8} />
      <Flow pts={POWER_A} f={f} color="#f3c77a" width={6} speed={3} dash={14} gap={14} />
      <path d="M1650 470 L1650 640 L1340 640" stroke={isolated ? C.line : C.ec} strokeWidth={8} fill="none" strokeLinejoin="round" />
      {!isolated ? <Flow pts={POWER_B} f={f} color="#f3c77a" width={6} speed={3} dash={14} gap={14} /> : null}
      <g>
        <rect x={1590} y={340} width={120} height={130} rx={16} fill={isolated ? "#f6dcd8" : C.white} stroke={isolated ? C.error : C.forest} strokeWidth={5} />
        <circle cx={1650} cy={405} r={38} fill={isolated ? C.error : C.gold} />
        <rect x={1640} y={369} width={20} height={72} rx={6} fill={C.white} transform={`rotate(${90 * iso} 1650 405)`} />
        <T x={1574} y={390} size={30} anchor="end">Isolation</T>
        <T x={1574} y={426} size={30} anchor="end">switch</T>
      </g>
      {isolated ? (
        <Pop x={1790} y={470} s={pop(f, tPhys + 8)}>
          <path d="M1728 400 Q1728 368 1752 368 Q1776 368 1776 400" stroke={C.forest} strokeWidth={7} fill="none" />
          <rect x={1718} y={396} width={68} height={54} rx={8} fill={C.gold} stroke={C.forest} strokeWidth={4} />
          <line x1={1752} y1={450} x2={1790} y2={490} stroke={C.forest} strokeWidth={3} />
          <g transform={`rotate(${Math.sin(f / 12) * 4} 1790 490)`}>
            <rect x={1730} y={490} width={160} height={70} rx={10} fill={C.error} />
            <T x={1810} y={526} size={30} fill={C.white}>LOCKED</T>
          </g>
        </Pop>
      ) : null}

      {/* PUMP */}
      <circle cx={PUMP[0]} cy={PUMP[1]} r={90} fill={C.white} stroke={timerActive && !isolated ? C.error : C.forest} strokeWidth={6} filter="url(#sh)" />
      <g transform={`rotate(${spin ? f * 12 : 0} ${PUMP[0]} ${PUMP[1]})`}>
        {[0, 60, 120, 180, 240, 300].map((a) => (
          <path key={a} d={`M${PUMP[0]} ${PUMP[1]} Q${PUMP[0] + 24} ${PUMP[1] - 30} ${PUMP[0]} ${PUMP[1] - 68}`} stroke={C.water} strokeWidth={10} fill="none" strokeLinecap="round" transform={`rotate(${a} ${PUMP[0]} ${PUMP[1]})`} />
        ))}
      </g>
      <circle cx={PUMP[0]} cy={PUMP[1]} r={14} fill={C.forest} />
      <T x={1140} y={790} size={32} anchor="end" fill={spin ? (timerActive ? C.error : C.good) : C.muted}>{spin ? "Pump running" : "Pump stopped"}</T>
      {timerActive && !isolated ? (
        <g>
          <circle cx={1340} cy={540} r={34 + 4 * Math.sin(f / 3)} fill={C.error} />
          <T x={1340} y={542} size={40} fill={C.white}>!</T>
        </g>
      ) : null}

      {/* WATER OUT + hand valve */}
      <path d="M1250 730 L1250 860 L1790 860 L1790 900" stroke="#a9b4ab" strokeWidth={26} fill="none" strokeLinejoin="round" />
      <path d="M1250 730 L1250 860 L1790 860 L1790 900" stroke="#dfe6dc" strokeWidth={12} fill="none" strokeLinejoin="round" />
      {spin ? <Flow pts={WATER} f={f} color={C.water} width={12} speed={5} /> : null}
      <Drips x={1790} y0={914} y1={968} f={f} rate={spin} />
      <g>
        <path d="M1470 836 L1500 860 L1470 884 Z M1530 836 L1500 860 L1530 884 Z" fill={isolated ? C.error : C.forest} />
        <rect x={1494} y={812} width={12} height={28} fill={C.forest} />
        <rect x={1456} y={800} width={88} height={18} rx={8} fill={isolated ? C.error : C.forest} transform={`rotate(${90 * iso} 1500 809)`} />
        <T x={1500} y={930} size={30}>Hand valve</T>
      </g>
      {isolated ? <Check x={1340} y={540} r={36} s={pop(f, tPhys + 20)} /> : null}

      </g>

      <Pill x={solo ? 960 : 560} y={solo ? 935 : 900} w={900} text={verdict.t} color={verdict.c} size={34} />
    </SvgStage>
  );
};

export default {
  Component,
  doc: "Software OFF vs physical isolation. Left: a phone whose Watering switch flips ON→OFF ('a request to software'); the Controller pauses ('no shots') and its command line to the pump is blocked. Then an old timer lights up and still drives the pump (red pulses, pump spins, water drips, red '!'). Finally the isolation switch turns OFF with a padlock + LOCKED tag and the hand valve closes: power beyond the isolator goes dead, pump and water stop, green check. Bottom pill states each verdict. Schematic only — no wiring steps. props: {room?:string (phone label, default 'Room A'), stages?:('software'|'bypass'|'physical')[] (default all; stages:['physical'] alone hides the phone + Controller and shows only the power → isolation switch → pump → hand valve panel, large and centred, pill 'Power is still live to the pump' → 'Isolated and locked')}. steps: one per entry of stages, in order.",
  example: { props: { stages: ["software", "bypass", "physical"] }, steps: [30, 90, 160] },
} satisfies SceneDef<P>;
