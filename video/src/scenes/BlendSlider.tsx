import React from "react";
import { useCurrentFrame } from "remotion";
import { C, SERIF } from "../theme";
import { stepAt } from "../anim";
import { type SceneDef } from "./kit";
import { Svg, T, Plant, Pot, ease, trim } from "./_watering-shared";

type P = { label: string; unit: string; a: number; b: number; positions: number[] };

const TX0 = 520, TX1 = 1400, TY = 420;
const MOVE = 34;

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const { label, unit, a, b } = props;
  const positions = props.positions && props.positions.length ? props.positions : [50];
  const starts = positions.map((_, i) => Math.max(i === 0 ? 18 : 0, stepAt(steps, i, duration, positions.length)));

  // Knob position: starts at 0 (vegetative end), glides to each position at its step.
  let pos = 0, cur = -1;
  positions.forEach((p, i) => {
    const t = ease(f, starts[i], starts[i] + MOVE);
    if (t > 0) { pos = pos + (p - pos) * t; cur = i; }
  });
  const kx = TX0 + ((TX1 - TX0) * pos) / 100;
  const val = a + ((b - a) * pos) / 100;
  const target = cur >= 0 ? positions[cur] : 0;
  const frac = target / 100;
  const diff = b - a;
  const res = a + diff * frac;
  const fIn = cur >= 0 ? ease(f, starts[cur] + MOVE - 6, starts[cur] + MOVE + 12) : 0;
  const intro = ease(f, 0, 18);
  const gen = pos / 100;

  const chips = [
    `${trim(b)} − ${trim(a)} = ${trim(diff)}`,
    `${trim(target)} ÷ 100 = ${trim(frac, 3)}`,
    `${trim(frac, 3)} × ${trim(diff)} = ${trim(diff * frac)}`,
    `${trim(a)} + ${trim(diff * frac)} = ${trim(res)}`,
  ];
  const chipNames = ["difference", "slider as a fraction", "share of the difference", "add to vegetative"];

  return (
    <>
      <Svg>
        <defs>
          <linearGradient id="bs-track" x1="0" x2="1">
            <stop offset="0" stopColor={C.plant} />
            <stop offset="1" stopColor={C.gold} />
          </linearGradient>
        </defs>
        <T x={960} y={74} size={52} weight={800} fill={C.forest} anchor="middle" opacity={intro}>{label}</T>

        {/* Endpoint cards with their plants */}
        {([["Vegetative", a, C.plant, 250, "veg", 1 - gen], ["Generative", b, C.gold, 1670, "flower", gen]] as const).map(([name, v, col, cx, kind, w]) => (
          <g key={name} opacity={intro}>
            <rect x={cx - 170} y={140} width={340} height={520} rx={28} fill={C.white} stroke={col} strokeWidth={3 + 5 * w} />
            <rect x={cx - 170} y={140} width={340} height={520} rx={28} fill={col} opacity={0.06 + 0.12 * w} />
            <Plant x={cx} y={404} s={0.7} kind={kind} seed={kind === "veg" ? 1 : 3} leafScale={kind === "veg" ? 1.1 : 0.85} />
            <Pot x={cx} y={400} w={150} h={84} />
            <T x={cx} y={548} size={36} weight={700} fill={kind === "veg" ? C.plant : "#8c7b3f"} anchor="middle">{name}</T>
            <T x={cx} y={622} size={60} weight={800} fill={C.ink} anchor="middle">{trim(v)} {unit}</T>
          </g>
        ))}

        {/* Track */}
        <g opacity={intro}>
          <rect x={TX0 - 24} y={TY - 22} width={TX1 - TX0 + 48} height={44} rx={22} fill="url(#bs-track)" />
          <rect x={TX0 - 24} y={TY - 22} width={TX1 - TX0 + 48} height={44} rx={22} fill="none" stroke={C.forest} strokeWidth={3} opacity={0.4} />
          {[0, 25, 50, 75, 100].map((p) => {
            const x = TX0 + ((TX1 - TX0) * p) / 100;
            return (
              <g key={p}>
                <line x1={x} x2={x} y1={TY + 34} y2={TY + 54} stroke={C.muted} strokeWidth={4} />
                <T x={x} y={TY + 94} size={34} weight={600} fill={C.muted} anchor="middle">{p}</T>
              </g>
            );
          })}
          <T x={TX0 - 24} y={TY + 150} size={30} fill={C.plant} weight={700}>← more vegetative</T>
          <T x={TX1 + 24} y={TY + 150} size={30} fill="#8c7b3f" weight={700} anchor="end">more generative →</T>
        </g>

        {/* Live value bubble */}
        <g transform={`translate(${kx},${TY - 150})`} opacity={intro}>
          <rect x={-130} y={-56} width={260} height={96} rx={22} fill={C.forest} />
          <path d="M -18 38 L 0 62 L 18 38 Z" fill={C.forest} />
          <T x={0} y={14} size={50} weight={800} fill={C.white} anchor="middle">{trim(Math.round(val * 10) / 10, 1)} {unit}</T>
        </g>

        {/* Knob */}
        <g transform={`translate(${kx},${TY})`} opacity={intro}>
          <circle r={70 + 5 * Math.sin(f / 8)} fill={C.water} opacity={0.14} />
          <circle r={56} fill={C.white} stroke={C.forest} strokeWidth={6} />
          <T x={0} y={13} size={36} weight={800} fill={C.forest} anchor="middle">{Math.round(pos)}</T>
        </g>
      </Svg>

      {/* Formula and the four steps */}
      <div style={{ position: "absolute", left: 96, right: 96, top: 700, height: 268, boxSizing: "border-box", background: C.white, border: `3px solid ${C.line}`, borderRadius: 28, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 22, opacity: fIn, transform: `translateY(${(1 - fIn) * 20}px)` }}>
        <div style={{ fontFamily: SERIF, fontSize: 70, color: C.ink }}>
          {trim(a)} + ({trim(b)} − {trim(a)}) × {trim(frac, 3)} ={" "}
          <span style={{ background: C.forest, color: C.white, borderRadius: 14, padding: "0 18px", fontWeight: 700 }}>{trim(res)} {unit}</span>
        </div>
        <div style={{ display: "flex", gap: 18, alignItems: "stretch" }}>
          {chips.map((c, i) => {
            const p = cur >= 0 ? ease(f, starts[cur] + MOVE + 4 + i * 6, starts[cur] + MOVE + 18 + i * 6) : 0;
            return (
              <div key={i} style={{ opacity: p, display: "flex", flexDirection: "column", alignItems: "center", padding: "6px 22px", borderRadius: 16, background: C.leaf, minWidth: 330 }}>
                <span style={{ fontSize: 28, color: C.muted, fontWeight: 600 }}>{i + 1}. {chipNames[i]}</span>
                <span style={{ fontSize: 38, fontWeight: 700, color: C.forest }}>{c}</span>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
};

export default {
  Component,
  doc: "Steering slider as a dimmer: vegetative endpoint card (leafy plant) on the left, generative endpoint card (flowering plant) on the right, a 0–100 track with a knob and a live value bubble that counts as the knob glides; the blend formula 'a + (b − a) × fraction = result' and its four steps appear when the knob settles. props: {label:'Maximum wait', unit:'min', a:30 (vegetative), b:50 (generative), positions:[50,25,75]}. steps: one per position — the knob moves to positions[i] at steps[i] (starts at 0).",
  example: { props: { label: "Maximum wait (P0)", unit: "min", a: 30, b: 50, positions: [50, 25, 75] }, steps: [20, 95, 165] },
} satisfies SceneDef<P>;
