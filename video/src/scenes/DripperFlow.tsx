import React from "react";
import { useCurrentFrame } from "remotion";
import { C, SERIF } from "../theme";
import { stepAt } from "../anim";
import { type SceneDef } from "./kit";
import { Svg, T, Drips, Stopwatch, Plant, Pot, Cup, SvgChip, ease, lin, trim } from "./_watering-shared";

type P = { plants: number; drippersPerPlant: number; lph: number; seconds: number; showZone?: boolean; uneven?: number[]; decimals?: number; mlDecimals?: number; mode?: "flow" };

const AREA_X0 = 80, AREA_X1 = 1420;
const PIPE_Y = 412, CUP_BOTTOM = 588, CUP_H = 108;

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const { plants, drippersPerPlant: n, lph, seconds, showZone = true, uneven } = props;
  const shown = Math.max(1, Math.min(plants, 4));
  const slot = (AREA_X1 - AREA_X0) / shown;
  const perPlantLph = n * lph;
  const perPlantL = (perPlantLph * seconds) / 3600;
  const perDripperMl = (lph * seconds) / 3.6;
  const zoneL = perPlantL * plants;
  const flowOnly = props.mode === "flow"; // flow calculation only: no cups, no mL
  const dec = props.decimals ?? 3;
  const mlDec = props.mlDecimals ?? 0;
  const fmtMl = (ml: number) => (mlDec > 0 ? trim(ml, mlDec) : String(Math.round(ml)));

  const lines = flowOnly ? 1 : showZone ? 3 : 2;
  const at = (i: number) => Math.max(i === 0 ? 24 : 0, stepAt(steps, i, duration, lines));
  const f0 = 12;
  const fillLen = Math.min(120, Math.max(60, Math.round(duration * 0.45)));
  const run = lin(f, f0, f0 + fillLen);
  const running = run > 0 && run < 1;
  const cupMl = (j: number) => (uneven && uneven.length ? uneven[j % uneven.length] : perDripperMl);
  const cap = Math.max(perDripperMl, ...(uneven || [0])) * 1.3;
  const median = uneven && uneven.length ? [...uneven].sort((a, b) => a - b)[Math.floor(uneven.length / 2)] : perDripperMl;
  const flow = -f * 5;

  const cupW = Math.min(76, (slot - 60) / n - 14);
  const cupGap = cupW + 28;

  const cups: React.ReactNode[] = [];
  const labels: React.ReactNode[] = [];
  const emitters: React.ReactNode[] = [];
  for (let p = 0; p < shown; p++) {
    const cx = AREA_X0 + slot * (p + 0.5);
    for (let k = 0; k < n; k++) {
      const j = p * n + k;
      const x = cx + (k - (n - 1) / 2) * cupGap;
      const ml = cupMl(j) * run;
      const low = !!uneven && cupMl(j) < median * 0.9;
      if (flowOnly) {
        cups.push(<Drips key={`d${j}`} x={x} y0={PIPE_Y + 36} y1={CUP_BOTTOM - 20} period={16} offset={j * 5} start={f0} end={f0 + Math.max(fillLen, duration)} r={8} fall={12} />);
      } else {
      cups.push(<Cup key={`c${j}`} id={`df${j}`} x={x} y={CUP_BOTTOM} w={cupW} h={CUP_H} level={ml / cap} tint={low && run >= 1 ? C.warn : C.water} />);
      cups.push(<Drips key={`d${j}`} x={x} y0={PIPE_Y + 36} y1={CUP_BOTTOM - CUP_H * (ml / cap) * 0.92} period={16} offset={j * 5} start={f0} end={f0 + fillLen} r={8} fall={12} />);
      }
      emitters.push(
        <g key={`e${j}`} transform={`translate(${x},${PIPE_Y})`}>
          <rect x={-11} y={6} width={22} height={24} rx={6} fill="#27302c" />
          <rect x={-4} y={28} width={8} height={8} rx={2} fill="#27302c" />
        </g>,
      );
      if (!flowOnly) labels.push(
        <T key={`l${j}`} x={x} y={CUP_BOTTOM + 40} size={Math.min(30, (cupGap - 6) / ((fmtMl(cupMl(j)).length + 3) * 0.56))} weight={700} fill={low && run >= 1 ? C.warn : C.forest} anchor="middle">
          {fmtMl(ml)} mL
        </T>,
      );
    }
  }

  const all: { parts: [string, boolean?][] }[] = [
    { parts: [[`${n} dripper${n === 1 ? "" : "s"} × ${lph} L/h = `], [`${trim(perPlantLph)} L/h`, true], [" per plant"]] },
    { parts: [[`${trim(perPlantLph)} × ${seconds} s ÷ 3600 = ${trim(perPlantL, dec)} L = `], [`${fmtMl(perPlantL * 1000)} mL`, true]] },
    { parts: [[`× ${plants} plants = `], [`${trim(zoneL, 2)} L`, true], [" per zone"]] },
  ];
  const calc = all.slice(0, lines);

  const perPlantShown = Array.from({ length: n }, (_, k) => cupMl(k)).reduce((a, b) => a + b, 0) * run;

  return (
    <>
      <Svg>
        {/* plants and pots */}
        {Array.from({ length: shown }, (_, p) => {
          const cx = AREA_X0 + slot * (p + 0.5);
          return (
            <g key={p}>
              <Plant x={cx} y={276} s={0.76} seed={p} />
              <Pot x={cx} y={272} w={200} h={118} />
            </g>
          );
        })}
        {/* drip line */}
        <rect x={AREA_X0 - 30} y={PIPE_Y - 12} width={AREA_X1 - AREA_X0 + 60} height={24} rx={12} fill="#2f3a35" />
        <line x1={AREA_X0 - 24} x2={AREA_X1 + 24} y1={PIPE_Y} y2={PIPE_Y} stroke={C.waterLight} strokeWidth={8} strokeDasharray="22 16" strokeDashoffset={running ? flow : 0} opacity={running ? 1 : 0.35} />
        {emitters}
        {cups}
        {labels}
        {plants > shown ? <SvgChip x={1690} y={546} text={`${shown} of ${plants} plants shown`} size={30} color={C.muted} /> : null}
        <SvgChip x={1690} y={606} text={`dripper: ${lph} L/h`} size={30} color={C.water} />

        {/* stopwatch + live per-plant total */}
        {flowOnly ? (
          <g>
            <T x={1690} y={300} size={32} fill={C.muted} anchor="middle">per plant</T>
            <T x={1690} y={380} size={72} weight={800} fill={C.water} anchor="middle">{trim(perPlantLph)} L/h</T>
            <T x={1690} y={440} size={30} fill={C.muted} anchor="middle">{`${n} × ${lph} L/h`}</T>
          </g>
        ) : (
          <g>
            <Stopwatch x={1690} y={176} r={112} elapsed={seconds * run} running={running} />
            <T x={1690} y={372} size={32} fill={C.muted} anchor="middle">per plant</T>
            <T x={1690} y={440} size={64} weight={800} fill={C.water} anchor="middle">{fmtMl(perPlantShown)} mL</T>
            <T x={1690} y={488} size={30} fill={C.muted} anchor="middle">in {Math.round(seconds * run)} s</T>
          </g>
        )}
      </Svg>

      {/* calculation strip */}
      <div style={{ position: "absolute", left: 80, right: 80, top: 664, height: 300, boxSizing: "border-box", background: C.white, border: `3px solid ${C.line}`, borderRadius: 28, padding: "18px 44px", display: "flex", flexDirection: "column", justifyContent: "center", gap: 6 }}>
        {calc.map((line, i) => {
          const p = ease(f, at(i), at(i) + 16);
          const cur = i === calc.length - 1 || f < at(i + 1);
          return (
            <div key={i} style={{ opacity: p, transform: `translateX(${(1 - p) * -30}px)`, display: "flex", alignItems: "center", gap: 26, fontFamily: SERIF, fontSize: lines === 3 ? 54 : lines === 1 ? 70 : 62, color: cur ? C.ink : C.muted, lineHeight: 1.2 }}>
              <span style={{ width: 52, height: 52, borderRadius: 26, background: cur ? C.water : C.line, color: C.white, fontFamily: "inherit", fontSize: 32, display: "grid", placeItems: "center", flexShrink: 0 }}>{i + 1}</span>
              <span>
                {line.parts.map(([t, b], k) => (
                  <span key={k} style={b ? { color: C.forest, fontWeight: 700, background: cur ? C.waterLight : "transparent", borderRadius: 10, padding: "0 10px" } : undefined}>{t}</span>
                ))}
              </span>
            </div>
          );
        })}
      </div>
    </>
  );
};

export default {
  Component,
  doc: "Drippers as small taps: a row of potted plants on a drip line, each dripper dripping into its own catch cup while a stopwatch runs and a live 'per plant' total counts up; a calculation strip builds flow → shot volume → zone volume. props: {plants:12, drippersPerPlant:2, lph:4, seconds:30, showZone?:true, uneven?:[mL per cup...] (catch test: cups end at those levels, low ones turn amber), decimals?:3 (litre decimals in line 2), mlDecimals?:0 (mL decimals everywhere, e.g. decimals:4 + mlDecimals:1 → '0.0667 L = 66.7 mL'), mode?:'flow' (flow calculation only: drippers drip, no cups/mL/stopwatch, right side shows 'N L/h per plant', strip shows line 1 only; seconds still required but unused)}. Shows up to 4 plants. steps: [line 1 'N drippers × L/h = per plant', line 2 '× s ÷ 3600 = L = mL', line 3 '× plants = L per zone' (if showZone)].",
  example: { props: { plants: 12, drippersPerPlant: 2, lph: 4, seconds: 30, showZone: true }, steps: [40, 110, 170] },
} satisfies SceneDef<P>;
