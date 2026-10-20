import React from "react";
import { useCurrentFrame, useVideoConfig, spring } from "remotion";
import { C } from "../theme";
import { stepAt } from "../anim";
import { type SceneDef } from "./kit";
import { Svg, T, Plant, FanLeaf, Bud, SvgChip, ease } from "./_watering-shared";

type P = { tilt: "veg" | "gen" | "balanced"; labels?: { veg?: string; gen?: string; message?: string; sub?: string } };

const PX = 520; // plant centre
const SOIL = 520; // soil line of the cutaway pot
const FX = 1430, FY = 600; // see-saw pivot
const ARM = 330;

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { tilt = "balanced", labels = {} } = props;
  const at = (i: number) => Math.max(i === 0 ? 12 : 0, stepAt(steps, i, duration, 4));
  const vegOn = ease(f, at(0), at(0) + 18);
  const genOn = ease(f, at(1), at(1) + 18);
  const tiltP = spring({ frame: f - at(2), fps, config: { damping: 9, stiffness: 70 } });
  const msg = ease(f, at(3), at(3) + 18);
  const intro = ease(f, 0, 16);

  const dir = tilt === "veg" ? -1 : tilt === "gen" ? 1 : 0;
  const angle = dir * 11 * tiltP + Math.sin(f / 22) * (dir ? 0.8 : 1.6);
  const rad = (angle * Math.PI) / 180;
  const end = (side: -1 | 1) => ({ x: FX + side * ARM * Math.cos(rad), y: FY + side * ARM * Math.sin(rad) });
  const L = end(-1), R = end(1);
  const lean = Math.max(0, tiltP);
  const glowV = vegOn * (0.55 + 0.45 * Math.sin(f / 9));
  const glowG = genOn * (0.55 + 0.45 * Math.sin(f / 9 + 1.5));

  // Roots: branching paths below the soil line.
  const roots = [
    "M0 0 C -10 60 -60 110 -90 190", "M0 0 C 10 70 50 120 80 200", "M0 0 C 0 80 -6 150 4 230",
    "M-40 90 C -80 110 -120 130 -130 170", "M40 100 C 80 120 110 150 120 185", "M-60 150 C -40 180 -60 210 -40 240", "M60 160 C 40 190 60 215 40 240",
  ];

  return (
    <>
      <Svg>
        <defs>
          <filter id="pb-gv" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="0" stdDeviation="10" floodColor="#58c26d" floodOpacity={glowV} /></filter>
          <filter id="pb-gg" x="-50%" y="-50%" width="200%" height="200%"><feDropShadow dx="0" dy="0" stdDeviation="10" floodColor="#f0c44a" floodOpacity={glowG} /></filter>
          <clipPath id="pb-pot"><path d={`M ${PX - 200} ${SOIL} L ${PX + 200} ${SOIL} L ${PX + 160} ${SOIL + 330} L ${PX - 160} ${SOIL + 330} Z`} /></clipPath>
        </defs>

        {/* Cutaway pot with roots */}
        <g opacity={intro}>
          <path d={`M ${PX - 200} ${SOIL} L ${PX + 200} ${SOIL} L ${PX + 160} ${SOIL + 330} L ${PX - 160} ${SOIL + 330} Z`} fill={C.solidLight} />
          <g clipPath="url(#pb-pot)">
            {Array.from({ length: 40 }, (_, i) => <circle key={i} cx={PX - 190 + ((i * 97) % 380)} cy={SOIL + 20 + ((i * 53) % 300)} r={4 + (i % 3) * 2} fill={C.solid} opacity={0.35} />)}
            <g transform={`translate(${PX},${SOIL})`} filter="url(#pb-gv)">
              {roots.map((d, i) => <path key={i} d={d} stroke={C.root} strokeWidth={i < 3 ? 9 : 6} fill="none" strokeLinecap="round" strokeDasharray="400" strokeDashoffset={400 * (1 - Math.min(1, intro + 0.0)) + Math.sin(f / 20 + i) * 2} />)}
            </g>
          </g>
          <path d={`M ${PX - 200} ${SOIL} L ${PX + 200} ${SOIL} L ${PX + 160} ${SOIL + 330} L ${PX - 160} ${SOIL + 330} Z`} fill="none" stroke={C.forest} strokeWidth={6} strokeLinejoin="round" />
          <rect x={PX - 214} y={SOIL - 14} width={428} height={28} rx={10} fill={C.forest} />
        </g>

        {/* Plant: leaves/shoots glow green, flowers glow gold */}
        <g opacity={intro}>
          <Plant x={PX} y={SOIL - 14} s={1.3} kind="flower" seed={2} leafFilter="url(#pb-gv)" budFilter="url(#pb-gg)" leafScale={1.3 + 0.12 * (dir < 0 ? lean : 0)} budScale={1 + 0.25 * (dir > 0 ? lean : 0)} />
        </g>

        {/* Callouts */}
        <g opacity={vegOn}>
          {([["Shoots", 190, PX - 14, 225], ["Leaves", 360, PX - 95, 380], ["Roots", 700, PX - 70, 690]] as const).map(([t, y, tx, ty]) => (
            <g key={t}>
              <line x1={210} y1={y} x2={tx} y2={ty} stroke={C.plant} strokeWidth={3} strokeDasharray="6 6" />
              <SvgChip x={140} y={y} text={t} color={C.plant} size={32} />
            </g>
          ))}
        </g>
        <g opacity={genOn}>
          <line x1={PX + 90} y1={311} x2={800} y2={252} stroke="#a8923f" strokeWidth={3} strokeDasharray="6 6" />
          <line x1={PX + 40} y1={160} x2={800} y2={228} stroke="#a8923f" strokeWidth={3} strokeDasharray="6 6" />
          <SvgChip x={890} y={240} text="Flowers" color="#a8923f" size={32} />
        </g>

        {/* See-saw */}
        <g opacity={intro}>
          <path d={`M ${FX} ${FY} L ${FX - 80} ${FY + 150} L ${FX + 80} ${FY + 150} Z`} fill={C.forest} />
          <rect x={FX - 140} y={FY + 146} width={280} height={18} rx={9} fill={C.forest} opacity={0.6} />
          <g transform={`rotate(${angle} ${FX} ${FY})`}>
            <rect x={FX - ARM - 30} y={FY - 26} width={2 * ARM + 60} height={26} rx={13} fill={C.solid} />
            <rect x={FX - ARM - 30} y={FY - 26} width={(2 * ARM + 60) / 2} height={26} rx={13} fill={C.plant} opacity={0.5} />
            <rect x={FX} y={FY - 26} width={(2 * ARM + 60) / 2} height={26} rx={13} fill={C.gold} opacity={0.6} />
          </g>
          <circle cx={FX} cy={FY} r={14} fill={C.white} stroke={C.forest} strokeWidth={5} />
          {/* Pans stay upright at the beam ends */}
          {([[L, "veg"], [R, "gen"]] as const).map(([p, k]) => (
            <g key={k} transform={`translate(${p.x},${p.y - 26})`}>
              <circle cy={-72} r={68} fill={C.white} stroke={k === "veg" ? C.plant : C.gold} strokeWidth={6} />
              {k === "veg" ? <FanLeaf x={0} y={-22} angle={Math.sin(f / 18) * 5} size={92} /> : <Bud x={0} y={-72} size={44} />}
              <T x={0} y={-160} size={36} weight={800} fill={k === "veg" ? C.plant : "#8c7b3f"} anchor="middle">{k === "veg" ? labels.veg || "Vegetative" : labels.gen || "Generative"}</T>
            </g>
          ))}
          {/* Bias weight lands on the heavier side */}
          {dir !== 0 ? (() => {
            const drop = ease(f, at(2) - 14, at(2));
            const d = dir * (ARM - 175);
            const wx = FX + d * Math.cos(rad), wy = FY - 26 + d * Math.sin(rad) - (1 - drop) * 220;
            return (
              <g opacity={drop} transform={`translate(${wx},${wy}) rotate(${angle})`}>
                <path d="M -50 0 L 50 0 L 40 -70 L -40 -70 Z" fill={C.forest} />
                <rect x={-18} y={-92} width={36} height={26} rx={10} fill="none" stroke={C.forest} strokeWidth={8} />
                <T x={0} y={-22} size={30} weight={800} fill={C.white} anchor="middle">bias</T>
              </g>
            );
          })() : null}
        </g>
      </Svg>

      {/* Message */}
      <div style={{ position: "absolute", left: 1000, right: 60, top: 800, display: "flex", flexDirection: "column", alignItems: "center", gap: 10, opacity: msg, transform: `translateY(${(1 - msg) * 24}px)` }}>
        <div style={{ background: C.forest, color: C.white, borderRadius: 999, padding: "16px 38px", fontSize: 42, fontWeight: 700 }}>{labels.message || "A bias is an influence, not a switch"}</div>
        <div style={{ fontSize: 32, color: C.muted }}>{labels.sub || "The plant keeps growing both — the balance only leans."}</div>
      </div>
    </>
  );
};

export default {
  Component,
  doc: "Vegetative vs generative growth on one illustrated plant (cutaway pot): roots, leaves and shoots glow green; flowers glow gold. A see-saw (Vegetative ↔ Generative) tilts when a 'bias' weight lands on one side, and keeps gently rocking; both kinds of growth stay on the plant. props: {tilt:'veg'|'gen'|'balanced', labels?:{veg?, gen?, message?:'A bias is an influence, not a switch', sub?}}. steps: [vegetative parts named, generative parts named, the tilt/bias, the message].",
  example: { props: { tilt: "gen" }, steps: [15, 60, 110, 165] },
} satisfies SceneDef<P>;
