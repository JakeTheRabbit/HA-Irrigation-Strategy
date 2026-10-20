import React from "react";
import { interpolate, useCurrentFrame, random, Easing } from "remotion";
import { getLength, getPointAtLength } from "@remotion/paths";
import { C, SERIF } from "../theme";
import { clamp, stepAt } from "../anim";
import type { SceneDef } from "./kit";
import { Svg, Pill, wave, lerp } from "./_measure-shared";

type P = { readings: (number | string)[]; unit?: string; labels?: string[]; display?: string[]; labelsOnly?: boolean; compare?: { label: string; reading: number; display?: string } };

const ION_PER_UNIT = 12;
const MAX_IONS = 44;
const ionCount = (r: number) => Math.min(MAX_IONS, Math.round(r * ION_PER_UNIT));

type G = { cx: number; top: number; bot: number; wt: number; wb: number; level: number };
const glassD = (g: G, y0 = g.top) => {
  const k = (y: number) => lerp(g.wt, g.wb, (y - g.top) / (g.bot - g.top)) / 2;
  return `M ${g.cx - k(y0)} ${y0} L ${g.cx - g.wb / 2} ${g.bot - 20} Q ${g.cx - g.wb / 2} ${g.bot} ${g.cx - g.wb / 2 + 20} ${g.bot} L ${g.cx + g.wb / 2 - 20} ${g.bot} Q ${g.cx + g.wb / 2} ${g.bot} ${g.cx + g.wb / 2} ${g.bot - 20} L ${g.cx + k(y0)} ${y0} Z`;
};

// Ion j's resting place inside the water, with a slow wander.
function ionPos(g: G, j: number, f: number, seed: string) {
  const rx = random(`${seed}x${j}`);
  const ry = random(`${seed}y${j}`);
  const y = lerp(g.level + 40, g.bot - 34, ry);
  const half = lerp(g.wt, g.wb, (y - g.top) / (g.bot - g.top)) / 2 - 36;
  const x = g.cx + (rx * 2 - 1) * half;
  const sp = 50 + 40 * random(`${seed}s${j}`);
  return { x: x + 14 * wave(f, sp, j), y: y + 10 * wave(f, sp * 1.3, j * 2) };
}

const Ion: React.FC<{ x: number; y: number; plus: boolean; s?: number; o?: number }> = ({ x, y, plus, s = 1, o = 1 }) => (
  <g transform={`translate(${x} ${y}) scale(${s})`} opacity={o}>
    <circle r={15} fill={plus ? C.ec : C.forest} />
    <text y={9} textAnchor="middle" fontSize={26} fontWeight={800} fill={C.white}>{plus ? "+" : "−"}</text>
  </g>
);

const Glass: React.FC<{ g: G; f: number; id: string; children?: React.ReactNode }> = ({ g, f, id, children }) => {
  const k = (y: number) => lerp(g.wt, g.wb, (y - g.top) / (g.bot - g.top)) / 2;
  let surf = `M ${g.cx - k(g.level)} ${g.level}`;
  for (let i = 0; i <= 12; i++) {
    const x = lerp(g.cx - k(g.level), g.cx + k(g.level), i / 12);
    surf += ` L ${x.toFixed(1)} ${(g.level + 4 * Math.sin(i / 1.6 + f / 10)).toFixed(1)}`;
  }
  const waterD = `${surf} L ${g.cx + g.wb / 2} ${g.bot - 20} Q ${g.cx + g.wb / 2} ${g.bot} ${g.cx + g.wb / 2 - 20} ${g.bot} L ${g.cx - g.wb / 2 + 20} ${g.bot} Q ${g.cx - g.wb / 2} ${g.bot} ${g.cx - g.wb / 2} ${g.bot - 20} Z`;
  return (
    <g>
      <ellipse cx={g.cx} cy={g.bot + 14} rx={g.wb / 2 + 40} ry={16} fill={C.forest} opacity={0.08} />
      <path d={glassD(g)} fill={C.white} opacity={0.7} />
      <clipPath id={`sw-${id}`}>
        <path d={waterD} />
      </clipPath>
      <path d={waterD} fill={C.waterLight} />
      <g clipPath={`url(#sw-${id})`}>{children}</g>
      <path d={glassD(g)} fill="none" stroke={C.forest} strokeWidth={6} strokeLinejoin="round" />
      <path d={`M ${g.cx - k(g.top + 40) + 24} ${g.top + 40} L ${g.cx - g.wb / 2 + 26} ${g.bot - 60}`} stroke={C.white} strokeWidth={12} strokeLinecap="round" opacity={0.8} />
    </g>
  );
};

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  // String readings are words for the meter (e.g. "low", "higher"); their salt amount ramps with position.
  const raw = props.readings.length ? props.readings : [0];
  const readings = raw.map((r, i) => (typeof r === "number" ? r : 0.2 + 0.9 * i));
  const words = raw.map((r, i) => (typeof r === "string" ? r : props.display?.[i]));
  const unit = props.unit ?? "mS/cm";
  const n = readings.length;
  const S = (i: number) => stepAt(steps, i, duration, n);
  const hasCmp = !!props.compare;

  const g: G = { cx: hasCmp ? 860 : 720, top: 215, bot: 770, wt: 440, wb: 350, level: 305 };
  const MX = hasCmp ? 1500 : 1380;
  const MY = 190;

  // Which reading are we on, and the displayed (counting) value.
  let shown = readings[0];
  let idx = 0;
  for (let i = 1; i < n; i++) {
    const t = interpolate(f, [S(i) + 18, S(i) + 58], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
    if (f >= S(i)) idx = i;
    if (t > 0) shown = lerp(readings[i - 1], readings[i], t);
  }
  const intro = interpolate(f, [S(0), S(0) + 18], [0, 1], clamp);
  const maxR = Math.max(...readings, props.compare?.reading ?? 0, 0.1);

  // Ions: each belongs to the first reading that needs it, and spreads from the drop point.
  const ions = Array.from({ length: ionCount(readings[n - 1]) }, (_, j) => {
    let born = 0;
    for (let i = 0; i < n; i++)
      if (ionCount(readings[i]) > j) {
        born = i;
        break;
      }
    const t0 = born === 0 ? S(0) - 30 : S(born) + 22;
    const t = interpolate(f, [t0, t0 + 50], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
    const home = ionPos(g, j, f, "m");
    const src = { x: g.cx + 30 * (random(`sx${j}`) - 0.5), y: g.bot - 50 };
    return { x: lerp(src.x, home.x, t), y: lerp(src.y, home.y, t), o: Math.min(1, t * 2.5), plus: j % 2 === 0 };
  });

  // Salt drops for each increase.
  const drops = readings.slice(1).map((r, k) => {
    const i = k + 1;
    if (r <= readings[i - 1]) return null;
    const spoon = interpolate(f, [S(i) - 14, S(i) - 2, S(i) + 14, S(i) + 30], [0, 1, 1, 0], clamp);
    const tilt = interpolate(f, [S(i) - 4, S(i) + 8], [0, -38], clamp);
    const crystals = Array.from({ length: 6 }, (_, c) => {
      const t = interpolate(f, [S(i) + 4 + c * 2, S(i) + 24 + c * 2], [0, 1], { ...clamp, easing: Easing.in(Easing.quad) });
      const sink = interpolate(f, [S(i) + 24 + c * 2, S(i) + 64], [0, 1], clamp);
      const x = g.cx - 20 + 50 * random(`c${i}${c}`) - 25;
      const y = t < 1 ? lerp(g.top - 110, g.level, t) : lerp(g.level, g.bot - 50, sink);
      return { x, y, s: t <= 0 ? 0 : 1 - sink, r: random(`r${i}${c}`) * 90 };
    });
    return { i, spoon, tilt, crystals };
  });

  // Meter + probes.
  const p1 = g.cx + 90;
  const p2 = g.cx + 140;
  const tipY = g.bot - 120;
  const cable1 = `M ${MX - 170} ${MY + 130} C ${MX - 380} ${MY + 130}, ${p1} ${g.top - 300}, ${p1} ${g.top - 70}`;
  const cable2 = `M ${MX - 170} ${MY + 250} C ${MX - 420} ${MY + 250}, ${p2} ${g.top - 180}, ${p2} ${g.top - 70}`;
  const L1 = getLength(cable1);
  const L2 = getLength(cable2);
  const flow = Math.min(1, shown / Math.max(maxR, 0.01));
  const speed = 1 + shown * 2.2;
  // LCD: a word when given for this step, blank when labelsOnly, else the counting number.
  const word = words[idx];
  const lcd = word !== undefined ? word : props.labelsOnly ? "" : shown.toFixed(1);
  const lcdSize = Math.min(110, 290 / Math.max(1, lcd.length * 0.55));
  const showUnit = word === undefined && !props.labelsOnly;
  const label = props.labels?.[idx];

  return (
    <Svg>
      <defs>
        <linearGradient id="sw-lcd" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#d9ecd0" />
          <stop offset="1" stopColor="#b9d6ad" />
        </linearGradient>
      </defs>

      {/* Comparison glass */}
      {props.compare ? (
        <g opacity={intro}>
          {(() => {
            const cg: G = { cx: 300, top: 390, bot: 770, wt: 300, wb: 240, level: 460 };
            return (
              <g>
                <Glass g={cg} f={f} id="cmp">
                  {Array.from({ length: ionCount(props.compare.reading) }, (_, j) => {
                    const p = ionPos(cg, j, f, "c");
                    return <Ion key={j} x={p.x} y={p.y} plus={j % 2 === 0} s={0.8} />;
                  })}
                </Glass>
                <text x={cg.cx} y={cg.top - 90} textAnchor="middle" fontSize={34} fontWeight={700} fill={C.ink}>{props.compare.label}</text>
                {props.compare.display !== undefined ? (props.compare.display ? <Pill x={cg.cx} y={cg.top - 40} text={props.compare.display} size={34} color={C.white} bg={C.forest} /> : null) : props.labelsOnly ? null : <Pill x={cg.cx} y={cg.top - 40} text={`${props.compare.reading.toFixed(1)} ${unit}`} size={34} color={C.white} bg={C.forest} />}
              </g>
            );
          })()}
        </g>
      ) : null}

      {/* Main glass with ions */}
      <g opacity={intro}>
        <Glass g={g} f={f} id="main">
          {ions.map((p, j) => (
            <Ion key={j} x={p.x} y={p.y} plus={p.plus} o={p.o} />
          ))}
          {drops.map((d) =>
            d ? d.crystals.map((c, k) => (c.y > g.level ? <rect key={`${d.i}-${k}`} x={c.x - 9 * c.s} y={c.y - 9 * c.s} width={18 * c.s} height={18 * c.s} fill={C.white} stroke={C.muted} strokeWidth={2} transform={`rotate(${c.r} ${c.x} ${c.y})`} /> : null)) : null,
          )}
        </Glass>
        {/* Probes */}
        {[p1, p2].map((x, i) => (
          <g key={i}>
            <rect x={x - 9} y={g.top - 80} width={18} height={tipY - g.top + 80} rx={9} fill={C.muted} />
            <rect x={x - 9} y={tipY - 50} width={18} height={50} rx={9} fill={C.gold} />
          </g>
        ))}
        {/* Current between probe tips */}
        {flow > 0.02
          ? Array.from({ length: 4 }, (_, k) => {
              const t = ((f * speed * 0.02 + k / 4) % 1);
              return <circle key={k} cx={lerp(p1 + 10, p2 - 10, t)} cy={tipY - 25 + 10 * Math.sin(t * Math.PI * 2 + k)} r={6} fill="#f2c94c" opacity={flow * Math.sin(t * Math.PI)} />;
            })
          : null}
      </g>

      {/* Spoon and falling crystals */}
      {drops.map((d) =>
        d ? (
          <g key={d.i}>
            <g opacity={d.spoon} transform={`translate(${g.cx - 30} ${g.top - 130}) rotate(${d.tilt})`}>
              <rect x={0} y={-8} width={230} height={16} rx={8} fill={C.gold} />
              <ellipse cx={-10} cy={0} rx={56} ry={30} fill={C.gold} />
              <ellipse cx={-10} cy={-4} rx={44} ry={20} fill={C.white} opacity={d.tilt > -20 ? 1 : 0.4} />
            </g>
            {d.crystals.map((c, k) => (c.y <= g.level && c.s > 0 ? <rect key={k} x={c.x - 9} y={c.y - 9} width={18} height={18} fill={C.white} stroke={C.muted} strokeWidth={2} transform={`rotate(${c.r + f * 4} ${c.x} ${c.y})`} /> : null))}
          </g>
        ) : null,
      )}

      {/* Cables with charge flowing */}
      <g opacity={intro}>
        <path d={cable1} fill="none" stroke={C.ec} strokeWidth={8} strokeLinecap="round" />
        <path d={cable2} fill="none" stroke={C.forest} strokeWidth={8} strokeLinecap="round" />
        {[{ d: cable1, L: L1, dir: 1 }, { d: cable2, L: L2, dir: -1 }].map((c, ci) =>
          Array.from({ length: 7 }, (_, k) => {
            const u = ((((f * speed * 3 * c.dir) / c.L + k / 7) % 1) + 1) % 1;
            const pt = getPointAtLength(c.d, u * c.L)!;
            return <circle key={`${ci}-${k}`} cx={pt.x} cy={pt.y} r={7} fill="#f2c94c" stroke={C.white} strokeWidth={2} opacity={flow} />;
          }),
        )}
        {/* Meter body */}
        <g transform={`translate(${MX} ${MY + 3 * wave(f, 80)})`}>
          <rect x={-190} y={-40} width={380} height={380} rx={40} fill={C.forest} />
          <rect x={-160} y={-10} width={320} height={170} rx={20} fill="url(#sw-lcd)" />
          <text x={word !== undefined ? 0 : 130} y={75 + lcdSize * 0.32} textAnchor={word !== undefined ? "middle" : "end"} fontFamily={SERIF} fontSize={lcdSize} fill={C.forest}>{lcd}</text>
          {showUnit ? <text x={0} y={205} textAnchor="middle" fontSize={36} fontWeight={700} fill={C.white}>{unit}</text> : null}
          <rect x={-150} y={240} width={300} height={22} rx={11} fill={C.white} opacity={0.2} />
          <rect x={-150} y={240} width={300 * flow} height={22} rx={11} fill="#f2c94c" />
          <text x={0} y={310} textAnchor="middle" fontSize={30} fontWeight={600} fill={C.leaf}>conductivity</text>
          <circle cx={150} cy={-12} r={8} fill="#f2c94c" opacity={0.4 + 0.6 * flow * (0.5 + 0.5 * wave(f, 20))} />
        </g>
      </g>

      {/* State label */}
      {label ? <Pill x={g.cx} y={g.bot + 70} text={label} size={40} color={C.forest} border={C.forest} opacity={intro} /> : null}
      <g opacity={intro} transform={`translate(${MX} ${g.bot + 50})`}>
        <Ion x={-150} y={0} plus />
        <Ion x={-110} y={0} plus={false} />
        <text x={-80} y={12} fontSize={32} fontWeight={600} fill={C.muted}>{"more ions → more current"}</text>
      </g>
    </Svg>
  );
};

export default {
  Component,
  doc: "Salted water explains EC. A glass of water; at each step a spoon tips salt crystals in, they sink and dissolve into + / − ions that wander through the water, and a conductivity meter with two probes counts up to the next reading while charge dots flow faster along its cables. Optional comparison glass on the left with its own reading. props: {readings:[0.2,1.0,2.0], unit?:'mS/cm', labels?:['Tap water','+1 spoon','+2 spoons'], compare?:{label:'Plain water', reading:0.0, display?:string ('' hides its pill)}, display?:[string per reading] (meter shows that word instead of the number, e.g. ['low','higher']; unit hidden), labelsOnly?:false (true = no number/unit on the meter or compare pill), readings may also be words directly (['low','higher']) — salt amount then ramps by position}. steps: one per reading (readings[i] is reached at steps[i]; the first is shown from the start).",
  example: { props: { readings: [0.2, 1.0, 2.0], unit: "mS/cm", labels: ["Tap water", "+ 1 spoon of salt", "+ 2 spoons of salt"], compare: { label: "Plain water", reading: 0.0 } }, steps: [0, 60, 150] },
} satisfies SceneDef<P>;
