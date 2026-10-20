import React, { useMemo } from "react";
import { useCurrentFrame, interpolate, interpolateColors, random } from "remotion";
import { C, SERIF } from "../theme";
import { stepAt, clamp } from "../anim";
import type { SceneDef } from "./kit";
import { SceneSvg, SW, SH, SPONGE, SCOUR, POSTIT, WATER_DEEP, Pill, c01, lerp, ease, pop, dropPath, textW } from "./_rootzone-shared";

type Stage = "dry" | "soaked" | "drained" | "note";
type P = { stages?: Stage[]; note?: { from: string; to?: string; label?: string }; captions?: Partial<Record<Stage, string>> };

const WET: Record<Stage, number> = { dry: 0, soaked: 1, drained: 0.8, note: -1 };
const CAP: Record<Stage, string> = {
  dry: "Dry: the holes hold air",
  soaked: "Soaked: every hole is full of water",
  drained: "Drip stops: water is still held",
  note: "The note changed. The sponge did not.",
};
const CHIP: Record<Stage, string> = { dry: "Dry", soaked: "Soaked", drained: "Drained", note: "The note" };

const SPW = 440, SPH = 270, SCR = 54; // sponge body size and scourer layer

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const stages = props.stages || ["dry", "soaked", "drained", "note"];
  const hasNote = stages.includes("note");
  const noteChange = !!(props.note && props.note.to);
  const count = stages.length + (noteChange ? 1 : 0);
  const at = stages.map((_, i) => (i === 0 ? (Number.isFinite(steps[0]) ? steps[0] : 0) : stepAt(steps, i, duration, count)));
  const changeAt = noteChange ? stepAt(steps, stages.length, duration, count) : 1e9;
  let cur = 0;
  at.forEach((a, i) => (f >= a ? (cur = i) : null));
  const stage = stages[cur];

  // Wetness 0..1, chained through stages (note keeps the previous wetness).
  let w = WET[stages[0]] < 0 ? 0.8 : WET[stages[0]];
  stages.forEach((s, i) => {
    if (i === 0 || WET[s] < 0) return;
    w = lerp(w, WET[s], ease(f, at[i] + (s === "soaked" ? 22 : 0), s === "drained" ? 60 : 24));
  });

  const sx = hasNote ? lerp(860, 640, ease(f, at[stages.indexOf("note")] - 6, 24)) : 860;
  const baseY = 430;
  // Dunk: down into the basin and back up at the start of "soaked".
  const si = stages.indexOf("soaked");
  const dunk = si >= 0 ? interpolate(f - at[si], [0, 16, 30, 48], [0, 1, 1, 0], clamp) : 0;
  const sy = baseY + dunk * 300;
  const sway = Math.sin(f / 42) * 1.6 * (1 - dunk);
  const swell = 0.94 + 0.06 * c01(w * 1.5);

  // Drip rate: full after soaking, tapering to zero through "drained".
  const di = stages.indexOf("drained");
  let drip = si >= 0 && f >= at[si] + 40 ? 1 : 0;
  if (di >= 0) drip *= interpolate(f, [at[di], at[di] + 75], [1, 0], clamp);
  const stopped = di >= 0 && f > at[di] + 75;

  const pores = useMemo(
    () =>
      Array.from({ length: 40 }, (_, i) => {
        const col = i % 10, row = Math.floor(i / 10);
        const x = -SPW / 2 + 32 + (col + (row % 2) * 0.5) * ((SPW - 64) / 10.5) + (random(`spx${i}`) - 0.5) * 22;
        const y = -SPH / 2 + SCR + 30 + row * ((SPH - SCR - 60) / 3) + (random(`spy${i}`) - 0.5) * 20;
        const big = random(`spb${i}`) > 0.62;
        const r = big ? 13 + random(`spr${i}`) * 7 : 5 + random(`spr${i}`) * 5;
        return { x, y, r, big, rot: random(`spt${i}`) * 60 - 30 };
      }),
    [],
  );
  const body = interpolateColors(w, [0, 1], ["#f7dc8f", "#d9a43a"]);
  const poreC = interpolateColors(w, [0, 0.5, 1], ["#d9b55f", "#8fb7c9", C.water]);
  const basinTop = 690, basinBot = 900, waterY = 740 + Math.sin(f / 12) * 2;
  const bx0 = sx - 400, bx1 = sx + 400;
  const dripXs = [-170, -100, -30, 40, 110, 170];
  const sBottom = sy + (SPH / 2) * swell;

  const notePop = hasNote ? pop(f, at[stages.indexOf("note")], 20) : 0;
  const strike = ease(f, changeAt, 14);
  const write = ease(f, changeAt + 12, 20);

  return (
    <SceneSvg>
      <defs>
        <clipPath id="sp-body">
          <rect x={-SPW / 2} y={-SPH / 2} width={SPW} height={SPH} rx={34} />
        </clipPath>
        <linearGradient id="sp-sheen" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity={0} />
          <stop offset="0.5" stopColor="#fff" stopOpacity={0.45} />
          <stop offset="1" stopColor="#fff" stopOpacity={0} />
        </linearGradient>
      </defs>

      {/* stage tracker */}
      {stages.map((s, i) => {
        const gap = 330;
        const x = SW / 2 + (i - (stages.length - 1) / 2) * gap;
        const active = i === cur, done = i < cur;
        const label = `${i + 1}  ${CHIP[s]}`;
        const wd = textW(label, 34) + 50;
        return (
          <g key={s} opacity={ease(f, i * 4, 16)}>
            {i > 0 ? <line x1={x - gap + (textW(`${i}  ${CHIP[stages[i - 1]]}`, 34) + 50) / 2 + 10} y1={60} x2={x - wd / 2 - 10} y2={60} stroke={done || active ? C.forest : C.line} strokeWidth={4} strokeDasharray={done || active ? "0" : "8 8"} /> : null}
            <rect x={x - wd / 2} y={30} width={wd} height={60} rx={30} fill={active ? C.forest : C.white} stroke={done || active ? C.forest : C.line} strokeWidth={3} transform={active ? `translate(${x} 60) scale(${1 + 0.03 * Math.sin(f / 10)}) translate(${-x} -60)` : undefined} />
            <text x={x} y={72} textAnchor="middle" fontSize={34} fontWeight={700} fill={active ? C.white : done ? C.forest : C.muted}>{label}</text>
          </g>
        );
      })}

      {/* basin back + water */}
      <path d={`M ${bx0} ${basinTop} L ${bx1} ${basinTop} L ${bx1 - 40} ${basinBot} Q ${sx} ${basinBot + 30} ${bx0 + 40} ${basinBot} Z`} fill="#e3e8e4" stroke="#9aa6a0" strokeWidth={6} strokeLinejoin="round" />

      {/* string + peg */}
      <line x1={sx} y1={120} x2={sx} y2={sy - SPH / 2 - 20} stroke={C.muted} strokeWidth={4} />
      {/* sponge */}
      <g transform={`translate(${sx} ${sy}) rotate(${sway} 0 ${-SPH / 2}) scale(1 ${swell})`}>
        <rect x={-SPW / 2 + 8} y={-SPH / 2 + 14} width={SPW} height={SPH} rx={34} fill="#000" opacity={0.08} />
        <g clipPath="url(#sp-body)">
          <rect x={-SPW / 2} y={-SPH / 2} width={SPW} height={SPH} fill={body} />
          {pores.map((p, i) => (
            <g key={i} transform={`translate(${p.x} ${p.y}) rotate(${p.rot})`}>
              <ellipse rx={p.r * 1.25} ry={p.r} fill={poreC} />
              {p.big ? <ellipse cx={-p.r * 0.2} cy={-p.r * 0.25} rx={p.r * 0.75 * (1 - c01((w - 0.6) / 0.4) * (stage === "soaked" ? 1 : 0.55))} ry={p.r * 0.55 * (1 - c01((w - 0.6) / 0.4) * (stage === "soaked" ? 1 : 0.55))} fill={C.white} opacity={0.85} /> : null}
              {w > 0.5 ? <ellipse cx={p.r * 0.3} cy={-p.r * 0.35} rx={p.r * 0.3} ry={p.r * 0.18} fill="#fff" opacity={0.5 * (0.6 + 0.4 * Math.sin(f / 9 + i))} /> : null}
            </g>
          ))}
          <rect x={-SPW / 2} y={-SPH / 2} width={SPW} height={SCR} fill={SCOUR} />
          {Array.from({ length: 22 }, (_, i) => (
            <path key={i} d={`M ${-SPW / 2 + i * 21} ${-SPH / 2 + 6} l 14 ${SCR - 14}`} stroke="#2f6440" strokeWidth={4} strokeLinecap="round" />
          ))}
          {w > 0.3 ? <rect x={-SPW / 2 + ((f * 6) % (SPW * 3)) - SPW} y={-SPH / 2} width={160} height={SPH} fill="url(#sp-sheen)" opacity={w} transform="skewX(-20)" /> : null}
          <rect x={-SPW / 2} y={-SPH / 2} width={SPW} height={SPH} rx={34} fill="none" stroke={interpolateColors(w, [0, 1], [SPONGE, "#b9862a"])} strokeWidth={8} />
        </g>
        <rect x={-30} y={-SPH / 2 - 44} width={60} height={70} rx={10} fill={C.solid} />
        <rect x={-30} y={-SPH / 2 - 44} width={60} height={16} rx={6} fill={C.solidLight} />
      </g>

      {/* drips */}
      {drip > 0.02
        ? dripXs.map((dx, i) => {
            const per = 16 + (i % 3) * 5;
            const t = ((f + i * 7) % per) / per;
            const y = lerp(sBottom, waterY, t * t);
            return <path key={i} d={dropPath(sx + dx + Math.sin(f / 40) * 4, y, 7 + 4 * drip)} fill={C.water} opacity={c01(drip * 1.5)} />;
          })
        : null}
      {drip > 0.6 ? dripXs.slice(1, 5).map((dx, i) => <line key={i} x1={sx + dx} y1={sBottom} x2={sx + dx} y2={sBottom + 40 * drip} stroke={C.water} strokeWidth={6} strokeLinecap="round" opacity={0.7} />) : null}

      {/* basin water in front (sponge looks submerged when dunked) */}
      <path d={`M ${bx0 + 14} ${waterY} Q ${sx - 200} ${waterY - 6 + Math.sin(f / 7) * 3} ${sx} ${waterY} T ${bx1 - 14} ${waterY} L ${bx1 - 44} ${basinBot - 6} Q ${sx} ${basinBot + 22} ${bx0 + 44} ${basinBot - 6} Z`} fill={C.water} opacity={0.82} />
      {[0, 1, 2].map((i) => {
        const r = ((f + i * 20) % 60) / 60;
        return drip > 0.02 || dunk > 0 ? <ellipse key={i} cx={sx + (i - 1) * 90} cy={waterY + 6} rx={20 + r * 90} ry={4 + r * 12} fill="none" stroke={C.white} strokeWidth={3} opacity={(1 - r) * 0.8} /> : null;
      })}
      <path d={`M ${bx0} ${basinTop} L ${bx1} ${basinTop}`} stroke="#9aa6a0" strokeWidth={10} strokeLinecap="round" />

      {/* no-squeeze + stopped badge */}
      {di >= 0 && f >= at[di] ? (
        <g opacity={ease(f, at[di], 16)}>
          <Pill x={sx + SPW / 2 + 40} y={baseY - 60} text="No squeezing" anchor="start" size={34} color={C.error} p={pop(f, at[di], 16)} />
          <Pill x={sx + SPW / 2 + 40} y={baseY + 40} text={stopped ? "Drip stopped" : "Dripping…"} anchor="start" size={34} color={stopped ? C.good : WATER_DEEP} p={1} />
          {/* little timer */}
          <g transform={`translate(${sx + SPW / 2 + 70} ${baseY + 130})`}>
            <circle r={30} fill={C.white} stroke={C.forest} strokeWidth={4} />
            <path d={`M 0 0 L 0 -22`} stroke={C.forest} strokeWidth={4} strokeLinecap="round" transform={`rotate(${interpolate(f, [at[di], at[di] + 75], [0, 360], clamp)})`} />
          </g>
        </g>
      ) : null}

      {/* Post-it */}
      {hasNote && notePop > 0.01 ? (
        <g transform={`translate(1400 ${baseY - 20}) rotate(${-4 + Math.sin(f / 50) * 0.8}) scale(${notePop})`}>
          <rect x={-190 + 8} y={-190 + 12} width={380} height={380} fill="#000" opacity={0.1} />
          <path d={`M -190 -190 L 190 -190 L 190 ${150 + Math.sin(f / 20) * 3} Q 150 190 110 190 L -190 190 Z`} fill={POSTIT} />
          <path d={`M 190 ${150 + Math.sin(f / 20) * 3} Q 150 160 110 190 Q 150 ${178 + Math.sin(f / 20) * 2} 190 ${150 + Math.sin(f / 20) * 3} Z`} fill="#e9c94f" />
          <rect x={-190} y={-190} width={380} height={34} fill="#f5d55c" />
          <text x={0} y={-90} textAnchor="middle" fontSize={36} fill={C.muted} fontWeight={600}>{props.note?.label || "Water level"}</text>
          <text x={0} y={noteChange && write > 0 ? -5 : 40} textAnchor="middle" fontFamily={SERIF} fontSize={noteChange && write > 0 ? 70 : 110} fill={noteChange && strike > 0 ? C.muted : C.ink}>{props.note?.from || "60%"}</text>
          {noteChange ? (
            <>
              <line x1={-90} y1={noteChange && write > 0 ? -30 : 5} x2={-90 + 180 * strike} y2={noteChange && write > 0 ? -20 : 15} stroke={C.error} strokeWidth={8} strokeLinecap="round" />
              <text x={0} y={120} textAnchor="middle" fontFamily={SERIF} fontSize={120} fill={C.error} opacity={write} transform={`translate(0 ${(1 - write) * 20})`}>{props.note?.to}</text>
            </>
          ) : null}
        </g>
      ) : null}
      {hasNote && noteChange && f > changeAt + 30 ? (
        <g opacity={ease(f, changeAt + 30, 16)}>
          <line x1={sx + SPW / 2 + 30} y1={baseY + 230} x2={1200} y2={baseY + 230} stroke={C.line} strokeWidth={4} strokeDasharray="10 10" />
          <text x={(sx + SPW / 2 + 1200) / 2 + 15} y={baseY + 215} textAnchor="middle" fontSize={64} fontWeight={700} fill={C.error}>≠</text>
        </g>
      ) : null}

      {/* caption */}
      <g key={stage} opacity={ease(f, at[cur] + 6, 16)}>
        <text x={SW / 2} y={SH - 26} textAnchor="middle" fontSize={44} fontWeight={700} fill={C.forest}>{props.captions?.[stage] || CAP[stage]}</text>
      </g>
    </SceneSvg>
  );
};

export default {
  Component,
  doc:
    "Kitchen-sponge lifecycle hanging over a sink. Stages: 'dry' (pale, holes hold air) → 'soaked' (dunked into the basin, lifted dark and dripping = saturation) → 'drained' (no squeezing; drips slow and stop over ~2.5 s, water still held = container capacity) → 'note' (a Post-it beside it; if note.to is given the number is crossed out and rewritten while the sponge stays exactly the same). A numbered stage tracker sits on top and a caption under the sink. props: {stages?:['dry','soaked','drained','note'], note?:{from:'60%', to?:'70%', label?:'Water level'}, captions?:{dry?,soaked?,drained?,note?}}. steps: one per stage (when it starts), then one more for the note change if note.to is set.",
  example: { props: { stages: ["dry", "soaked", "drained", "note"], note: { from: "60%", to: "70%" } }, steps: [0, 30, 90, 160, 195] },
} satisfies SceneDef<P>;
