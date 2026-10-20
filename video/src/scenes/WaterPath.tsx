import React from "react";
import { useCurrentFrame } from "remotion";
import { C } from "../theme";
import { type SceneDef } from "./kit";
import { SvgStage, Defs, T, Pill, Pop, DrawLine, Flow, Drips, Eye, Check, Led, ease, pop, at, pointAt, type Pt } from "./_system-shared";

type Part = "supply" | "pump" | "filter" | "regulator" | "valve" | "drippers" | "drain" | "backflow";
type P = { parts?: Part[]; flow?: boolean; stop?: boolean };

const PIPE: Pt[] = [[330, 540], [1290, 540], [1290, 300], [1860, 300]];
const PIPE_GREY = "#a9b4ab";
// Distance along PIPE where each part sits (how far the pipe is built once it appears).
const DIST: Record<Part, number> = { supply: 40, backflow: 70, pump: 215, filter: 430, regulator: 630, valve: 820, drippers: 1770, drain: 0 };
const POTS = [1440, 1610, 1780];
const ALL: Part[] = ["supply", "pump", "filter", "regulator", "valve", "drippers", "drain", "backflow"];
// Horizontal extent [x0, x1] of each part's drawing (incl. labels), for re-centring partial diagrams.
const SPAN: Record<Part, [number, number]> = {
  supply: [70, 330], backflow: [330, 450], pump: [478, 602], filter: [700, 820], regulator: [880, 1040],
  valve: [1090, 1210], drippers: [1360, 1870], drain: [1350, 1870],
};
// x of the point at distance d along PIPE.
const pipeX = (d: number) => (d <= 960 ? 330 + d : d <= 1200 ? 1290 : 1290 + d - 1200);
// PIPE truncated to distance d (water only flows along pipe that has been built).
const cut = (d: number): Pt[] => {
  const out: Pt[] = [PIPE[0]];
  let acc = 0;
  for (let i = 1; i < PIPE.length; i++) {
    const seg = Math.hypot(PIPE[i][0] - PIPE[i - 1][0], PIPE[i][1] - PIPE[i - 1][1]);
    if (acc + seg >= d) break;
    acc += seg;
    out.push(PIPE[i]);
  }
  out.push(pointAt(PIPE, d));
  return out;
};
const EYE_W = 116;
const EYE_SIZE = 38;

// Plumbing diagram built piece by piece, then water flows; optional STOP with an eye on the outlet.
const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const parts: Part[] = props.parts?.length ? props.parts : ALL;
  const n = parts.length + (props.stop ? 1 : 0);
  const startOf = {} as Record<Part, number>;
  parts.forEach((p, i) => (startOf[p] = at(steps, i, duration, n)));
  const has = (p: Part) => p in startOf;
  const sp = (p: Part) => (has(p) ? pop(f, startOf[p]) : 0);
  const rv = (p: Part) => (has(p) ? ease(f, startOf[p], 20) : 0);

  // Pipe extent: grows from the previous built point to each part as it appears.
  let extent = 0;
  const ordered = parts.filter((p) => p !== "drain").sort((a, b) => startOf[a] - startOf[b]);
  let prev = 0;
  for (const p of ordered) {
    const e = rv(p);
    const target = Math.max(prev, DIST[p]);
    if (e > 0) extent = Math.max(extent, prev + (target - prev) * e);
    prev = target;
  }
  const L = 1770;
  const builtAt = Math.max(...parts.map((p) => startOf[p])) + 22;
  const stopAt = props.stop ? at(steps, parts.length, duration, n) : 1e9;
  const flowing = props.flow !== false;
  const flowIn = flowing ? ease(f, builtAt, 20) : 0;
  const stopP = ease(f, stopAt, 14);
  const flow = flowIn * (1 - stopP);
  // Drips continue briefly after the stop, then die away.
  const drip = flowIn * (f < stopAt ? 1 : Math.max(0, 1 - (f - stopAt) / 55));
  const stopped = props.stop && f > stopAt + 60;
  const pumpOn = flow > 0.05;

  const status = props.stop && f >= stopAt ? (stopped ? "Stopped — the outlet is dry" : "STOP: valve closed — watch the outlet") : flowIn > 0.5 ? "Water flows along the path" : "Follow the water from source to pot";
  const statusColor = props.stop && f >= stopAt ? (stopped ? C.good : C.error) : C.forest;

  // Partial diagrams: centre what is drawn (and shrink if it would overflow the stage).
  const pipeEnd = pipeX(Math.max(0, ...parts.filter((p) => p !== "drain").map((p) => DIST[p])));
  const eyeLines = stopped ? ["No more drips"] : ["Watch the", "drippers stop"];
  const eyeTW = Math.max(...eyeLines.map((l) => l.length * EYE_SIZE * 0.54));
  const siphon = has("backflow") && pipeEnd >= 1290; // anti-siphon sits at the high point, only once the pipe reaches it
  const eyeX0 = has("drippers") ? 1400 : pipeEnd - 120; // left edge of the eye label, just above the drippers/outlet
  let fit = "";
  if (parts.length < ALL.length) {
    const xs = [330, pipeEnd];
    parts.forEach((p) => xs.push(...SPAN[p]));
    if (siphon) xs.push(1190, 1390);
    if (props.stop) xs.push(eyeX0, eyeX0 + EYE_W + 20 + 13 * EYE_SIZE * 0.54 + 80);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const k = Math.min(1, 1760 / (x1 - x0));
    fit = `translate(${960 - ((x0 + x1) / 2) * k} ${450 * (1 - k)}) scale(${k})`;
  }

  const tankLevel = 330 + Math.min(60, Math.max(0, f - builtAt) * 0.12 * (1 - stopP));

  return (
    <SvgStage>
      <Defs />
      <g transform={fit}>
      {/* pipe shell + water */}
      <DrawLine pts={PIPE} p={extent / L} color={PIPE_GREY} width={30} cap="butt" />
      <DrawLine pts={PIPE} p={extent / L} color="#dfe6dc" width={16} cap="butt" />
      {flow > 0 ? <Flow pts={cut(extent)} f={f} color={C.water} width={14} speed={5} dash={30} gap={18} opacity={flow} /> : null}

      {/* supply tank */}
      {has("supply") ? (
        <Pop x={200} y={430} s={sp("supply")}>
          <rect x={70} y={230} width={260} height={390} rx={22} fill={C.white} stroke={C.forest} strokeWidth={5} filter="url(#sh)" />
          <path
            d={`M74 ${tankLevel} ${Array.from({ length: 9 }, (_, i) => `Q${74 + i * 28 + 14} ${tankLevel + Math.sin(f / 9 + i) * 8} ${74 + (i + 1) * 28} ${tankLevel}`).join(" ")} L326 600 Q326 616 310 616 L90 616 Q74 616 74 600 Z`}
            fill={C.waterLight}
          />
          <path d={`M74 ${tankLevel + 40} L326 ${tankLevel + 40} L326 600 Q326 616 310 616 L90 616 Q74 616 74 600 Z`} fill={C.water} opacity={0.35} />
          <rect x={300} y={524} width={34} height={32} fill={PIPE_GREY} />
          <T x={200} y={668}>Water</T>
          <T x={200} y={708}>source</T>
        </Pop>
      ) : null}

      {/* backflow preventer (on supply line) + anti-siphon (at the high point) */}
      {has("backflow") ? (
        <g>
          <Pop x={410} y={540} s={sp("backflow")}>
            <path d="M410 500 L450 540 L410 580 L370 540 Z" fill={C.gold} stroke={C.forest} strokeWidth={4} />
            <path d="M396 540 L424 540 M414 528 L426 540 L414 552" stroke={C.forest} strokeWidth={5} fill="none" strokeLinecap="round" strokeLinejoin="round" />
            <T x={426} y={418} size={30}>Backflow</T>
            <T x={426} y={454} size={30}>preventer</T>
          </Pop>
          {siphon ? <Pop x={1290} y={260} s={pop(f, startOf.backflow + 8)}>
            <rect x={1268} y={228} width={44} height={60} rx={8} fill={C.gold} stroke={C.forest} strokeWidth={4} />
            <path d="M1274 226 Q1290 200 1306 226" fill={C.gold} stroke={C.forest} strokeWidth={4} />
            <T x={1290} y={172} size={30}>Anti-siphon</T>
          </Pop> : null}
        </g>
      ) : null}

      {/* pump */}
      {has("pump") ? (
        <Pop x={540} y={540} s={sp("pump")}>
          <rect x={482} y={598} width={116} height={20} rx={6} fill={C.forest} />
          <circle cx={540} cy={540} r={62} fill={C.white} stroke={C.forest} strokeWidth={5} filter="url(#sh)" />
          <g transform={`rotate(${pumpOn ? f * 14 * flow : 0} 540 540)`}>
            {[0, 60, 120, 180, 240, 300].map((a) => (
              <path key={a} d="M540 540 Q556 520 540 494" stroke={C.water} strokeWidth={8} fill="none" strokeLinecap="round" transform={`rotate(${a} 540 540)`} />
            ))}
          </g>
          <circle cx={540} cy={540} r={10} fill={C.forest} />
          <Led x={590} y={490} f={f} on={pumpOn} />
          <T x={540} y={668}>Pump</T>
          <T x={540} y={706} size={30} weight={500} fill={C.muted}>(optional)</T>
        </Pop>
      ) : null}

      {/* filter */}
      {has("filter") ? (
        <Pop x={760} y={560} s={sp("filter")}>
          <rect x={722} y={506} width={76} height={110} rx={16} fill={C.white} stroke={C.forest} strokeWidth={5} filter="url(#sh)" />
          <rect x={712} y={496} width={96} height={22} rx={6} fill={C.forest} />
          {[0, 1, 2, 3].map((i) => (
            <line key={i} x1={734} x2={786} y1={540 + i * 18} y2={540 + i * 18} stroke={C.line} strokeWidth={4} />
          ))}
          {[0, 1, 2].map((i) => (
            <circle key={i} cx={742 + i * 18} cy={600 - ((f * 0.4 + i * 9) % 12)} r={4} fill={C.solid} opacity={flowIn} />
          ))}
          <T x={760} y={668}>Filter</T>
        </Pop>
      ) : null}

      {/* pressure regulator */}
      {has("regulator") ? (
        <Pop x={960} y={520} s={sp("regulator")}>
          <rect x={918} y={516} width={84} height={50} rx={12} fill={C.white} stroke={C.forest} strokeWidth={5} />
          <line x1={960} y1={516} x2={960} y2={478} stroke={C.forest} strokeWidth={6} />
          <circle cx={960} cy={444} r={42} fill={C.white} stroke={C.forest} strokeWidth={5} filter="url(#sh)" />
          <path d="M930 456 A32 32 0 0 1 990 456" stroke={C.good} strokeWidth={6} fill="none" />
          <line x1={960} y1={448} x2={960} y2={418} stroke={C.error} strokeWidth={5} strokeLinecap="round" transform={`rotate(${-50 + 50 * flowIn + Math.sin(f / 7) * 4 * flow} 960 448)`} />
          <circle cx={960} cy={448} r={6} fill={C.forest} />
          <T x={960} y={668}>Pressure</T>
          <T x={960} y={706}>regulator</T>
        </Pop>
      ) : null}

      {/* zone valve */}
      {has("valve") ? (
        <Pop x={1150} y={520} s={sp("valve")}>
          <path d="M1102 512 L1150 540 L1102 568 Z M1198 512 L1150 540 L1198 568 Z" fill={f >= stopAt ? C.error : C.forest} />
          <rect x={1132} y={470} width={36} height={52} rx={6} fill={C.white} stroke={C.forest} strokeWidth={4} />
          <rect x={1120} y={444} width={60} height={30} rx={8} fill={C.forest} />
          <Led x={1150} y={459} f={f} on={flow > 0.2} r={7} />
          <T x={1150} y={668}>Zone</T>
          <T x={1150} y={706}>valve</T>
        </Pop>
      ) : null}

      {/* drippers + pots */}
      {has("drippers") ? (
        <g>
          {POTS.map((x, i) => {
            const s = pop(f, startOf.drippers + i * 5);
            return (
              <Pop key={x} x={x} y={500} s={s}>
                <line x1={x} y1={300} x2={x} y2={352} stroke={C.forest} strokeWidth={6} />
                <rect x={x - 16} y={336} width={32} height={22} rx={6} fill={C.forest} />
                <path d={`M${x - 70} 420 L${x + 70} 420 L${x + 54} 590 L${x - 54} 590 Z`} fill={C.solid} stroke={C.forest} strokeWidth={6} strokeLinejoin="round" />
                <path d={`M${x - 62} 432 L${x + 62} 432 L${x + 58} 470 L${x - 58} 470 Z`} fill={C.solidLight} />
                <path d={`M${x} 432 q-6 -40 -40 -52 q34 0 40 30 q4 -40 36 -50 q-26 20 -36 72`} fill={C.plant} />
                <Drips x={x} y0={366} y1={428} f={f} rate={drip} phase={i * 7} />
              </Pop>
            );
          })}
          <T x={1610} y={250} opacity={rv("drippers")}>Drip line + drippers</T>
        </g>
      ) : null}

      {/* drainage tray + runoff */}
      {has("drain") ? (
        <Pop x={1610} y={640} s={sp("drain")}>
          <path d="M1350 606 L1870 606 L1856 650 L1364 650 Z" fill={C.white} stroke={C.forest} strokeWidth={5} />
          <rect x={1364} y={630} width={492} height={16} fill={C.waterLight} opacity={0.4 + 0.6 * drip} />
          {POTS.map((x, i) => (
            <Drips key={x} x={x + 30} y0={596} y1={634} f={f} rate={drip * 0.8} period={34} phase={i * 11} r={6} />
          ))}
          <line x1={1610} y1={650} x2={1610} y2={740} stroke={PIPE_GREY} strokeWidth={20} />
          {drip > 0 ? <Flow pts={[[1610, 652], [1610, 740]]} f={f} color={C.water} width={8} speed={3} dash={14} gap={14} opacity={drip} /> : null}
          <rect x={1550} y={740} width={120} height={22} rx={6} fill={C.forest} />
          {[0, 1, 2, 3].map((i) => <line key={i} x1={1566 + i * 28} x2={1566 + i * 28} y1={744} y2={758} stroke={C.white} strokeWidth={4} />)}
          <T x={1610} y={800}>Runoff to drain</T>
        </Pop>
      ) : null}

      {/* STOP state */}
      {props.stop && f >= stopAt ? (
        <g>
          <Pop x={1150} y={350} s={pop(f, stopAt)}>
            <path d={octagon(1150, 350, 58)} fill={C.error} stroke={C.white} strokeWidth={5} />
            <T x={1150} y={352} size={32} fill={C.white}>STOP</T>
          </Pop>
          <Pop x={eyeX0 + EYE_W / 2} y={162} s={pop(f, stopAt + 10)}>
            <Eye x={eyeX0 + EYE_W / 2} y={162} f={f} w={EYE_W} />
            {eyeLines.map((l, i) => (
              <T key={l} x={eyeX0 + EYE_W + 20} y={162 + (i - (eyeLines.length - 1) / 2) * 44} anchor="start" size={EYE_SIZE}>{l}</T>
            ))}
            {stopped ? <Check x={eyeX0 + EYE_W + 20 + eyeTW + 44} y={162} r={30} s={pop(f, stopAt + 60)} /> : null}
          </Pop>
        </g>
      ) : null}
      </g>

      <Pill x={720} y={880} w={980} text={status} color={statusColor} size={34} opacity={ease(f, 4, 16)} />
    </SvgStage>
  );
};

function octagon(cx: number, cy: number, r: number) {
  return "M" + Array.from({ length: 8 }, (_, i) => {
    const a = (Math.PI / 8) * (2 * i + 1);
    return `${cx + r * Math.cos(a)} ${cy + r * Math.sin(a)}`;
  }).join(" L") + " Z";
}

export default {
  Component,
  doc: "Plumbing diagram built part by part: supply tank → backflow preventer → (optional) pump → filter → pressure regulator → zone valve → drip line with drippers into pots → drainage tray to drain; 'backflow' also marks the anti-siphon at the high point. Water then flows along the pipe, drips fall. props: {parts?:('supply'|'pump'|'filter'|'regulator'|'valve'|'drippers'|'drain'|'backflow')[] (default all; omit 'pump' for a pressurised supply; with a subset the drawn diagram is re-centred and shrunk if needed so nothing runs off the stage), flow?:true, stop?:boolean}. steps: one per entry of parts, in the order given (each part appears when named), then (if stop) one for the stop — valve turns red, STOP sign, flow ceases, drips taper and a large eye label 'Watch the drippers stop' (38 px, two lines) sits just above the drippers watching the outlet until dry ('No more drips' + check).",
  example: { props: { parts: ["supply", "pump", "filter", "regulator", "valve", "drippers", "drain", "backflow"], flow: true, stop: true }, steps: [6, 18, 30, 42, 54, 66, 78, 90, 165] },
} satisfies SceneDef<P>;
