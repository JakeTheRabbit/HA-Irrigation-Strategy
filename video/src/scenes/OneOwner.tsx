import React from "react";
import { useCurrentFrame } from "remotion";
import { C } from "../theme";
import { type SceneDef } from "./kit";
import { SvgStage, Defs, T, Pill, Pop, Pulses, Drips, Check, Cross, Led, HaMark, pathD, pointAt, polyLen, ease, pop, at, type Pt } from "./_system-shared";

type P = { stage?: "conflict" | "resolved" | "both" };

const bez = (a: Pt, b: Pt, c: Pt, d: Pt, n = 40): Pt[] =>
  Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n, u = 1 - t;
    return [u * u * u * a[0] + 3 * u * u * t * b[0] + 3 * u * t * t * c[0] + t * t * t * d[0], u * u * u * a[1] + 3 * u * u * t * b[1] + 3 * u * t * t * c[1] + t * t * t * d[1]];
  });
const WIRE_L = bez([330, 440], [330, 660], [700, 600], [930, 668]);
const WIRE_R = bez([1590, 440], [1590, 660], [1220, 600], [990, 668]);
const VX = 960, VY = 790;

// Two controllers on one valve clash; resolved to one owner with the old link cut.
const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const mode = props.stage ?? "both";
  const s0 = at(steps, 0, duration, 2);
  const s1 = mode === "both" ? at(steps, 1, duration, 2, 6) : mode === "resolved" ? -1000 : 1e9;
  const intro = pop(f, mode === "resolved" ? 0 : s0);
  const resolved = f >= s1;
  const r = mode === "resolved" ? 1 : ease(f, s1, 18);
  const conflict = !resolved && f >= s0 + 10;
  const openAt = (g: number) => (g >= s1 ? Math.floor(g / 45) % 2 === 0 : g >= s0 + 10 ? Math.floor(g / 9) % 2 === 0 : false);
  const open = openAt(f);
  // valve-state trace over the last 4 s
  const trace = Array.from({ length: 121 }, (_, i) => {
    const g = f - 120 + i;
    return [700 + i * 4.3, g < s0 ? 430 : openAt(g) ? 330 : 430] as Pt;
  });
  const shake = conflict ? Math.sin(f * 1.7) * 6 : 0;
  const cut = pointAt(WIRE_L, polyLen(WIRE_L) * 0.45);
  const leftA = WIRE_L.filter((_, i) => i / 40 < 0.43);
  const leftB = WIRE_L.filter((_, i) => i / 40 > 0.49);
  const gap = 18 * r;

  return (
    <SvgStage>
      <Defs />
      {/* wires */}
      {resolved ? (
        <g>
          <path d={pathD(leftA)} stroke="#b8c0b8" strokeWidth={10} fill="none" strokeLinecap="round" transform={`translate(${-gap} ${-gap * 0.4})`} />
          <path d={pathD(leftB)} stroke="#b8c0b8" strokeWidth={10} fill="none" strokeLinecap="round" transform={`translate(${gap} ${gap * 0.4})`} />
        </g>
      ) : (
        <path d={pathD(WIRE_L)} stroke={conflict ? C.ec : C.line} strokeWidth={10} fill="none" strokeLinecap="round" opacity={intro} />
      )}
      <path d={pathD(WIRE_R)} stroke={resolved ? C.good : conflict ? C.water : C.line} strokeWidth={10} fill="none" strokeLinecap="round" opacity={intro} />
      {conflict ? (
        <g>
          <Pulses pts={WIRE_L} f={f} n={3} period={36} color={C.ec} r={12} />
          <Pulses pts={WIRE_R} f={f + 18} n={3} period={36} color={C.water} r={12} />
        </g>
      ) : null}
      {resolved ? <Pulses pts={WIRE_R} f={f} n={2} period={60} color={C.good} r={11} /> : null}

      {/* old timer */}
      <Pop x={330} y={300} s={intro}>
        <g opacity={1 - 0.55 * r}>
          <rect x={190} y={150} width={280} height={280} rx={30} fill={C.white} stroke={C.forest} strokeWidth={5} filter="url(#sh)" />
          <circle cx={330} cy={290} r={100} fill={C.paper} stroke={C.forest} strokeWidth={5} />
          {Array.from({ length: 24 }, (_, i) => (
            <rect key={i} x={326} y={196} width={8} height={22} rx={2} fill={i % 3 === 0 ? C.ec : C.line} transform={`rotate(${i * 15} 330 290)`} />
          ))}
          <line x1={330} y1={290} x2={330} y2={220} stroke={C.forest} strokeWidth={8} strokeLinecap="round" transform={`rotate(${f * 3} 330 290)`} />
          <circle cx={330} cy={290} r={10} fill={C.forest} />
          <T x={330} y={110} size={36}>Old timer</T>
        </g>
      </Pop>

      {/* new Controller */}
      <Pop x={1590} y={300} s={intro}>
        <rect x={1450} y={150} width={280} height={280} rx={30} fill={C.forest} filter="url(#sh)" />
        <HaMark x={1590} y={260} s={1.5} />
        <Led x={1690} y={190} f={f} color={C.good} period={20} r={9} />
        <rect x={1490} y={340} width={200} height={50} rx={12} fill="#24584b" />
        <T x={1590} y={366} size={30} fill={C.white}>Crop Steering</T>
        <T x={1590} y={110} size={36}>New Controller</T>
      </Pop>

      {/* conflicting commands */}
      {conflict ? (
        <g>
          <Pop x={610} y={540} s={pop(f, s0 + 10)}>
            <Bubble x={610} y={540} text="OPEN!" color={C.ec} on={Math.floor(f / 9) % 2 === 0} />
          </Pop>
          <Pop x={1310} y={540} s={pop(f, s0 + 16)}>
            <Bubble x={1310} y={540} text="CLOSE!" color={C.water} on={Math.floor(f / 9) % 2 === 1} />
          </Pop>
        </g>
      ) : null}

      {/* valve-state trace */}
      <g opacity={intro}>
        <rect x={680} y={290} width={560} height={180} rx={18} fill={C.white} stroke={C.line} strokeWidth={3} />
        <T x={700} y={265} anchor="start" size={30} fill={C.muted}>Valve state</T>
        <T x={664} y={330} anchor="end" size={30} weight={600} fill={C.muted}>open</T>
        <T x={664} y={430} anchor="end" size={30} weight={600} fill={C.muted}>closed</T>
        <path d={stepD(trace)} stroke={f >= s0 + 10 ? C.error : C.muted} strokeWidth={6} fill="none" strokeLinejoin="round" />
        {resolved ? <path d={stepD(trace.slice(Math.max(0, 120 - (f - s1))))} stroke={C.good} strokeWidth={7} fill="none" strokeLinejoin="round" /> : null}
        <circle cx={trace[120][0]} cy={trace[120][1]} r={10} fill={conflict ? C.error : resolved ? C.good : C.muted} />
      </g>

      {/* pipe + valve */}
      <g opacity={intro}>
        <path d={`M520 ${VY} L1400 ${VY}`} stroke="#a9b4ab" strokeWidth={32} />
        <path d={`M520 ${VY} L1400 ${VY}`} stroke="#dfe6dc" strokeWidth={16} />
        {open ? <path d={`M${VX} ${VY} L1400 ${VY}`} stroke={C.water} strokeWidth={14} strokeDasharray="26 18" strokeDashoffset={-f * 5} /> : null}
        <path d={`M520 ${VY} L${VX} ${VY}`} stroke={C.water} strokeWidth={14} strokeDasharray="26 18" strokeDashoffset={open ? -f * 5 : 0} opacity={0.6} />
        <rect x={1392} y={VY - 16} width={30} height={64} fill="#a9b4ab" />
        <Drips x={1407} y0={VY + 56} y1={VY + 150} f={f} rate={open ? 1 : 0} />
        <g transform={`translate(${shake} 0)`}>
          <path d={`M${VX - 60} ${VY - 36} L${VX} ${VY} L${VX - 60} ${VY + 36} Z M${VX + 60} ${VY - 36} L${VX} ${VY} L${VX + 60} ${VY + 36} Z`} fill={conflict ? (open ? C.good : C.error) : resolved ? (open ? C.good : C.forest) : C.forest} />
          <rect x={VX - 24} y={VY - 100} width={48} height={70} rx={8} fill={C.white} stroke={C.forest} strokeWidth={4} />
          <rect x={VX - 50} y={VY - 130} width={100} height={40} rx={10} fill={C.forest} />
        </g>
        <T x={VX} y={VY + 90} size={34}>Zone valve</T>
        <T x={VX} y={VY + 132} size={30} weight={500} fill={open ? C.good : C.muted}>{open ? "open" : "closed"}</T>
      </g>

      {/* clash burst */}
      {conflict ? (
        <g>
          <path d={star(VX, VY - 215, 70 + 10 * Math.sin(f / 2), 36, 10)} fill={C.error} opacity={0.9} />
          <T x={VX} y={VY - 213} size={34} fill={C.white}>!</T>
        </g>
      ) : null}

      {/* resolution */}
      {resolved ? (
        <g>
          <Scissors x={cut[0]} y={cut[1] - 4} s={pop(f, s1)} f={f - s1} />
          <Cross x={cut[0] - 40} y={cut[1] + 70} r={26} s={pop(f, s1 + 8)} />
          <T x={cut[0] + 6} y={cut[1] + 130} size={30} fill={C.error} opacity={r}>link removed</T>
          <Check x={VX} y={VY - 215} r={44} s={pop(f, s1 + 12)} />
          <Pill x={1290} y={600} w={240} text="sole owner" color={C.good} size={30} opacity={r} />
        </g>
      ) : null}

      <Pill
        x={960} y={70} w={resolved ? 620 : 640}
        text={resolved ? "One owner per output" : conflict ? "Two owners → mixed commands" : "Who switches this valve?"}
        color={resolved ? C.good : conflict ? C.error : C.forest} size={36} opacity={ease(f, 0, 14)}
      />
    </SvgStage>
  );
};

const Bubble: React.FC<{ x: number; y: number; text: string; color: string; on: boolean }> = ({ x, y, text, color, on }) => (
  <g opacity={on ? 1 : 0.45}>
    <rect x={x - 100} y={y - 40} width={200} height={80} rx={22} fill={on ? color : C.white} stroke={color} strokeWidth={4} />
    <T x={x} y={y + 2} size={36} fill={on ? C.white : color}>{text}</T>
  </g>
);

const Scissors: React.FC<{ x: number; y: number; s: number; f: number }> = ({ x, y, s, f }) => {
  const a = 18 * Math.abs(Math.sin(Math.min(f, 24) / 4));
  return (
    <Pop x={x} y={y} s={s}>
      <g transform={`translate(${x} ${y})`}>
        <g transform={`rotate(${-a})`}>
          <path d="M0 0 L70 -10" stroke={C.forest} strokeWidth={9} strokeLinecap="round" />
          <circle cx={-26} cy={10} r={16} fill="none" stroke={C.error} strokeWidth={7} />
        </g>
        <g transform={`rotate(${a})`}>
          <path d="M0 0 L70 10" stroke={C.forest} strokeWidth={9} strokeLinecap="round" />
          <circle cx={-26} cy={-10} r={16} fill="none" stroke={C.error} strokeWidth={7} />
        </g>
      </g>
    </Pop>
  );
};

const stepD = (t: Pt[]) => (t.length ? pathD(t.flatMap((p, i) => (i ? [[p[0], t[i - 1][1]] as Pt, p] : [p]))) : "");

function star(cx: number, cy: number, R: number, r: number, n: number) {
  return "M" + Array.from({ length: n * 2 }, (_, i) => {
    const a = (Math.PI * i) / n - Math.PI / 2, rr = i % 2 ? r : R;
    return `${cx + rr * Math.cos(a)} ${cy + rr * Math.sin(a)}`;
  }).join(" L") + " Z";
}

export default {
  Component,
  doc: "One owner per output: an old timer (left) and the new Crop Steering Controller (right) are both wired to one zone valve. Conflict: pulses run down both wires, 'OPEN!' / 'CLOSE!' bubbles alternate, the valve flickers open/closed and shakes under a red clash burst. Resolved: scissors cut the timer's wire (greyed, 'link removed'), the Controller's wire turns green ('sole owner'), green check over a calmly cycling valve. props: {stage?:'conflict'|'resolved'|'both' (default both)}. steps: [conflict appears, resolve (only used when stage='both')].",
  example: { props: { stage: "both" }, steps: [6, 120] },
} satisfies SceneDef<P>;
