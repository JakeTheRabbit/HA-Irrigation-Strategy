import React from "react";
import { useCurrentFrame, interpolate, Easing } from "remotion";
import { C } from "../theme";
import { stepAt, clamp } from "../anim";
import type { SceneDef } from "./kit";
import { SceneSvg, CutPot, Pill, Arrow, SW, SH, bandFrac, c01, lerp, ease, pop, easeIO, useParticles, gapNear, WATER_DEEP, type PotState } from "./_rootzone-shared";

type ArrowKind = "drainage" | "evaporation" | "uptake" | "oxygen";
type P = {
  mode?: "fill" | "drain" | "dry" | "static";
  from?: number;
  to?: number;
  secs?: number;
  showRoots?: boolean;
  showProbe?: boolean;
  arrows?: ArrowKind[];
  labels?: boolean;
  caption?: string;
};

const DEF_FROM = { fill: 0.25, drain: 1, dry: 0.65, static: 0.6 };
const DEF_TO = { fill: 0.65, drain: 0.6, dry: 0.35, static: 0.6 };

// Geometry of the pot on the stage.
const CX = 820, TOP = 320, PW = 700, PBW = 560, PH = 480, PR = 19;
const BOTTOM = TOP + PH;

const ARROW_LABEL: Record<ArrowKind, string> = { drainage: "Drainage", evaporation: "Evaporation", uptake: "Plant uptake", oxygen: "Air returns" };

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const mode = props.mode || "static";
  const from = props.from ?? DEF_FROM[mode];
  const to = props.to ?? (mode === "static" ? from : DEF_TO[mode]);
  const arrows = props.arrows || [];
  const nLabels = props.labels ? 3 : 0;
  const count = 1 + arrows.length + nLabels;
  const s0 = Number.isFinite(steps[0]) ? steps[0] : 12;
  const secs = (props.secs ?? 4) * 30;
  const p = easeIO(f, s0, secs);
  const post = Math.max(0, f - (s0 + secs));
  const sTop = TOP + 4;
  const bandTop = (L: number) => BOTTOM - bandFrac(L) * (BOTTOM - sTop);

  // Water state for this frame.
  let st: PotState;
  if (mode === "fill") {
    const fp = c01(p / 0.55);
    const front = lerp(sTop - 10, BOTTOM + 30, fp);
    const q = c01((p - 0.55) / 0.45);
    const bulk: [number, number][] = q > 0 ? [[lerp(sTop, bandTop(to), q), BOTTOM + 20]] : [[sTop - 10, front], [bandTop(from), BOTTOM + 20]];
    const drip = interpolate(p, [0.5, 0.62, 1], [0, 1, 0.3], clamp) * Math.exp(-post / 70);
    st = { bulk, front: q > 0 ? undefined : front, filmAbove: q > 0 ? to : 1, filmBelow: from, split: front, drip, tray: 0.12 + 0.55 * c01((p - 0.5) / 0.5), stream: p > 0 && p < 0.72 ? 1 : interpolate(p, [0.72, 0.8], [1, 0], clamp) * (p > 0 ? 1 : 0), bubblesUp: p > 0 && p < 0.6 ? 1 : 0, airIn: 0 };
  } else if (mode === "drain") {
    const L = lerp(from, to, interpolate(p, [0, 1], [0, 1], { ...clamp, easing: Easing.out(Easing.quad) }));
    const drip = (p > 0 ? 1 - 0.7 * p : 0) * Math.exp(-post / 70);
    st = { bulk: [[bandTop(L), BOTTOM + 20]], filmAbove: L, filmBelow: L, split: 0, drip, tray: 0.15 + 0.5 * p, stream: 0, bubblesUp: 0, airIn: p > 0 && p < 1 ? 1 : interpolate(post, [0, 40], [1, 0.25], clamp) * (p > 0 ? 1 : 0) };
  } else {
    const L = mode === "dry" ? lerp(from, to, interpolate(f, [s0, s0 + secs], [0, 1], clamp)) : to;
    st = { bulk: [[bandTop(L), BOTTOM + 20]], filmAbove: L, filmBelow: L, split: 0, drip: 0, tray: 0.25, stream: 0, bubblesUp: 0, airIn: 0 };
  }

  const appear = ease(f, 0, 20);
  const roots = props.showRoots ? ease(f, 6, 50) : 0;
  const probe = props.showProbe ? ease(f, 14, 22) : 0;
  const arrowAt = (i: number) => stepAt(steps, 1 + i, duration, count) || 30 + i * 30;
  const labelAt = (i: number) => stepAt(steps, 1 + arrows.length + i, duration, count) || 40 + (arrows.length + i) * 30;

  const { particles, gaps } = useParticles(CX, TOP, PW, PBW, PH, PR, "pot");
  const solidP = particles.reduce((m, q) => (Math.hypot(q.x - 1040, q.y - 470) < Math.hypot(m.x - 1040, m.y - 470) ? q : m), particles[0]);
  const waterP = particles.reduce((m, q) => (Math.hypot(q.x - 1010, q.y - 610) < Math.hypot(m.x - 1010, m.y - 610) ? q : m), particles[0]);
  const airG = gapNear(gaps, 1000, 400);

  const levelNow = mode === "fill" ? lerp(from, to, c01((p - 0.2) / 0.8)) : mode === "drain" ? lerp(from, to, p) : mode === "dry" ? lerp(from, to, c01((f - s0) / secs)) : to;

  return (
    <SceneSvg>
      <defs>
        <radialGradient id="pcs-bg" cx="0.43" cy="0.5" r="0.6">
          <stop offset="0" stopColor={C.leaf} stopOpacity={0.9} />
          <stop offset="1" stopColor={C.leaf} stopOpacity={0} />
        </radialGradient>
      </defs>
      <ellipse cx={CX} cy={560} rx={760} ry={470} fill="url(#pcs-bg)" />
      <g opacity={appear} transform={`translate(0 ${(1 - appear) * 30 + Math.sin(f / 50) * 2})`}>
        <CutPot f={f} cx={CX} top={TOP} w={PW} bw={PBW} h={PH} r={PR} seed="pot" st={st} emitter={mode === "fill"} roots={roots} probe={probe} region={probe} plant={props.showRoots ? ease(f, 0, 30) : 0} />
      </g>

      {arrows.map((k, i) => {
        const a = ease(f, arrowAt(i), 26);
        const lp = pop(f, arrowAt(i) + 10, 16);
        if (k === "drainage")
          return (
            <g key={k}>
              <Arrow f={f} p={a} color={C.water} width={12} d={`M ${CX + 150} ${BOTTOM - 120} L ${CX + 150} ${BOTTOM + 40}`} head={{ x: CX + 150, y: BOTTOM + 52, angle: 90 }} />
              <line x1={CX + 300} y1={BOTTOM + 60} x2={CX + 410} y2={BOTTOM + 60} stroke={C.water} strokeWidth={4} strokeDasharray="6 8" opacity={lp} />
              <Pill x={CX + 440} y={BOTTOM + 60} text={ARROW_LABEL[k]} color={WATER_DEEP} p={lp} anchor="start" size={38} />
            </g>
          );
        if (k === "evaporation")
          return (
            <g key={k}>
              {[-340, -285, -230].map((dx, j) => {
                const x = CX + dx;
                const w = (y: number) => x + Math.sin(y / 18 + f / 9 + j) * 12;
                const ys = [TOP - 40, TOP - 90, TOP - 140, TOP - 190];
                const d = `M ${w(ys[0])} ${ys[0]} ` + ys.slice(1).map((y) => `L ${w(y)} ${y}`).join(" ");
                return <Arrow key={j} f={f} p={ease(f, arrowAt(i) + j * 5, 24)} color={C.muted} width={7} d={d} head={{ x: w(ys[3]) , y: ys[3] - 8, angle: -90 }} flow={false} />;
              })}
              <Pill x={CX - 380} y={TOP - 120} text={ARROW_LABEL[k]} color={C.muted} p={lp} anchor="end" size={38} />
            </g>
          );
        if (k === "uptake") {
          const d = `M ${CX + 95} ${TOP + 300} C ${CX + 90} ${TOP + 180} ${CX + 70} ${TOP + 60} ${CX + 70} ${TOP - 40}`;
          return (
            <g key={k}>
              <Arrow f={f} p={a} color={C.plant} width={11} d={d} head={{ x: CX + 70, y: TOP - 52, angle: -90 }} />
              <line x1={CX + 100} y1={TOP - 70} x2={CX + 290} y2={TOP - 150} stroke={C.plant} strokeWidth={4} strokeDasharray="6 8" opacity={lp} />
              <Pill x={CX + 310} y={TOP - 150} text={ARROW_LABEL[k]} color={C.good} p={lp} anchor="start" size={38} />
            </g>
          );
        }
        // oxygen: air moving in from above-left into the top layer
        return (
          <g key={k}>
            {[0, 1].map((j) => (
              <Arrow key={j} f={f} p={ease(f, arrowAt(i) + j * 6, 24)} color={C.gold} width={9} d={`M ${CX - 470 + j * 10} ${TOP + 40 + j * 120} Q ${CX - 380} ${TOP + 30 + j * 120} ${CX - 290 + j * 10} ${TOP + 90 + j * 120}`} head={{ x: CX - 280 + j * 10, y: TOP + 96 + j * 120, angle: 30 }} />
            ))}
            <Pill x={CX - 490} y={TOP + 110} text={ARROW_LABEL[k]} color={C.gold} p={lp} anchor="end" size={38} textColor={C.ink} />
          </g>
        );
      })}

      {props.labels
        ? [
            { t: "Solid substrate", x: solidP.x, y: solidP.y, c: C.solid, ly: 470 },
            { t: "Water", x: waterP.x + waterP.r + 3, y: waterP.y, c: WATER_DEEP, ly: 590 },
            { t: "Air", x: airG[0], y: airG[1], c: C.muted, ly: 350 },
          ].map((l, i) => {
            const lp = pop(f, labelAt(i), 16);
            const lx = 1250;
            return lp > 0.01 ? (
              <g key={l.t} opacity={c01(lp)}>
                <line x1={l.x} y1={l.y} x2={lx - 20} y2={l.ly} stroke={l.c} strokeWidth={4} />
                <circle cx={l.x} cy={l.y} r={9 + Math.sin(f / 8) * 2} fill={C.white} stroke={l.c} strokeWidth={4} />
                <Pill x={lx} y={l.ly} text={l.t} color={l.c} p={lp} anchor="start" size={40} />
              </g>
            ) : null;
          })
        : null}

      {props.showProbe ? (
        <Pill x={CX + PW * 0.2 + 190} y={TOP - 190} text="Probe" p={pop(f, 30, 16)} color={C.forest} anchor="start" size={34} />
      ) : null}

      {/* live water gauge */}
      {mode !== "static" ? (
        <g transform={`translate(1800 ${TOP + 40})`} opacity={ease(f, 8, 20)}>
          <rect x={-46} y={0} width={92} height={420} rx={46} fill={C.white} stroke={C.line} strokeWidth={4} />
          <clipPath id="pcs-g">
            <rect x={-40} y={6} width={80} height={408} rx={40} />
          </clipPath>
          <g clipPath="url(#pcs-g)">
            <rect x={-40} y={414 - 408 * levelNow + Math.sin(f / 10) * 2} width={80} height={420} fill={C.water} />
          </g>
          <text x={0} y={470} textAnchor="middle" fontSize={34} fontWeight={700} fill={C.ink}>{mode === "fill" ? (p < 1 ? "Filling" : "Held") : mode === "drain" ? (p < 1 ? "Draining" : "Drained") : "Drying"}</text>
        </g>
      ) : null}

      {props.caption ? (
        <text x={SW / 2} y={SH - 28} textAnchor="middle" fontSize={40} fontWeight={600} fill={C.forest} opacity={ease(f, 20, 20)}>{props.caption}</text>
      ) : null}
    </SceneSvg>
  );
};


export default {
  Component,
  doc:
    "Signature cut-away pot of substrate: irregular solid particles, water films + saturated water (blue) and air gaps (white), optional roots/plant and probe, tray below catching drips. props: {mode:'fill'|'drain'|'dry'|'static' (default static), from?:0-1, to?:0-1 (water level, 1 = saturated; defaults fill .25→.65, drain 1→.6, dry .65→.35, static .6), secs?:4 (length of the water change), showRoots?, showProbe? (adds probe + glowing sensing region), arrows?:['drainage','evaporation','uptake','oxygen'], labels?:true (Solid/Water/Air callouts), caption?}. fill = water pours in from an emitter, a wetting front descends, displaced air bubbles up, then excess drips into the tray and the pot settles at `to`. drain = water drips out, air bubbles re-enter from the top. dry = films thin slowly. steps: [water change starts, then one per arrow in order, then Solid, Water, Air if labels].",
  example: {
    props: { mode: "fill", from: 0.2, to: 0.65, secs: 3.5, showRoots: true, arrows: ["drainage", "uptake", "evaporation", "oxygen"], labels: true },
    steps: [10, 120, 140, 160, 180, 195, 210, 225],
  },
} satisfies SceneDef<P>;
