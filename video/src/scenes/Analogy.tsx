import React from "react";
import { useCurrentFrame } from "remotion";
import { C, SERIF } from "../theme";
import { stepAt } from "../anim";
import type { SceneDef } from "./kit";
import { SceneSvg, SW, SH, Pill, CutPot, Arrow, Plant, POT, POSTIT, SCOUR, WATER_DEEP, blobPath, dropPath, c01, ease, pop, lerp, bandFrac, textW } from "./_rootzone-shared";

type Icon =
  | "bank" | "sponge" | "thermometer" | "dashboard" | "dimmer" | "list" | "contact" | "receipt" | "tap" | "route" | "fridge" | "postit" | "calendar" | "budget"
  | "pot" | "probe" | "dripper" | "app" | "graph" | "zone" | "setting" | "ec"
  | "person" | "handover" | "lightswitch" | "car" | "bus" | "trolley" | "toolbox" | "house" | "plane" | "phone-contact";
// value: text drawn on icons that show a number (thermometer, setting, postit, bank, dashboard).
// gauge: dashboard style — "speed" (default speedometer) or "fuel" (E→F fuel gauge).
type Side = { icon: Icon; label: string; value?: string; gauge?: "speed" | "fuel" };
type P = { left: Side; right: Side; mappings?: { from: string; to: string }[]; joiner?: string };

const INK = C.ink;
const ICONS = "bank sponge thermometer dashboard dimmer list contact phone-contact receipt tap route fridge postit calendar budget pot probe dripper app graph zone setting ec person handover lightswitch car bus trolley toolbox house plane";

// Font size that fits `t` into width `w`, capped at `max`.
const fit = (t: string, w: number, max: number) => Math.min(max, w / Math.max(1, t.length * 0.56));

// Simple flat person (head + shoulders), origin at the feet centre-line; ~300 tall at k=1.
function Person({ x = 0, y = 0, k = 1, col = C.forest, f = 0 }: { x?: number; y?: number; k?: number; col?: string; f?: number }) {
  return (
    <g transform={`translate(${x} ${y + Math.sin(f / 18) * 3}) scale(${k})`}>
      <path d="M -100 150 L -100 70 Q -100 0 0 0 Q 100 0 100 70 L 100 150 Z" fill={col} stroke={INK} strokeWidth={6} strokeLinejoin="round" />
      <circle cx={0} cy={-70} r={56} fill={C.solidLight} stroke={INK} strokeWidth={6} />
      <circle cx={-20} cy={-78} r={6} fill={INK} />
      <circle cx={20} cy={-78} r={6} fill={INK} />
      <path d="M -20 -50 Q 0 -36 20 -50" stroke={INK} strokeWidth={5} fill="none" strokeLinecap="round" />
    </g>
  );
}

function Wheel({ x, y, r, f }: { x: number; y: number; r: number; f: number }) {
  return (
    <g transform={`translate(${x} ${y}) rotate(${f * 8})`}>
      <circle r={r} fill={INK} />
      <circle r={r * 0.45} fill="#c9cfd2" />
      <line x1={-r * 0.45} x2={r * 0.45} y1={0} y2={0} stroke={INK} strokeWidth={4} />
    </g>
  );
}

// Each icon draws in a box from -150..150 around the origin and keeps moving gently.
function IconArt({ icon, f, value, gauge }: { icon: Icon; f: number; value?: string; gauge?: "speed" | "fuel" }) {
  const s = Math.sin(f / 20);
  switch (icon) {
    case "bank": {
      const drop = (f % 70) / 70;
      return (
        <g>
          <rect x={-150} y={-120} width={190} height={120} rx={18} fill={C.forest} />
          <rect x={-150} y={-95} width={190} height={22} fill="#2c5a4d" />
          <text x={-55} y={-22} textAnchor="middle" fontSize={value ? fit(value, 170, 40) : 40} fontWeight={700} fill={C.white}>{value ?? "$"}</text>
          {[0, 1, 2, 3, 4].map((i) => (
            <g key={i}>
              <ellipse cx={90} cy={130 - i * 22} rx={56} ry={18} fill={C.gold} stroke="#8f7f48" strokeWidth={4} />
            </g>
          ))}
          <ellipse cx={90} cy={lerp(-120, 130 - 5 * 22, drop * drop)} rx={56 * (0.4 + 0.6 * Math.abs(Math.cos(f / 6)))} ry={18} fill={C.gold} stroke="#8f7f48" strokeWidth={4} opacity={drop < 0.95 ? 1 : 0} />
          {[0, 1, 2].map((i) => (
            <ellipse key={i} cx={-60 + i * 50} cy={120} rx={40} ry={13} fill={C.gold} stroke="#8f7f48" strokeWidth={4} />
          ))}
        </g>
      );
    }
    case "sponge":
      return (
        <g transform={`rotate(${s * 2})`}>
          <rect x={-130} y={-80} width={260} height={150} rx={22} fill="#d9a43a" />
          <rect x={-130} y={-80} width={260} height={36} rx={14} fill={SCOUR} />
          {[[-80, -10], [-20, 20], [50, -15], [90, 30], [-95, 40], [10, 50]].map(([x, y], i) => (
            <ellipse key={i} cx={x} cy={y} rx={14} ry={10} fill={C.water} />
          ))}
          {[-70, 0, 70].map((x, i) => {
            const t = ((f + i * 11) % 30) / 30;
            return <path key={i} d={dropPath(x, lerp(80, 145, t * t), 8)} fill={C.water} opacity={1 - t} />;
          })}
        </g>
      );
    case "thermometer": {
      const lvl = 0.55 + 0.06 * s;
      return (
        <g>
          <rect x={-28} y={-140} width={56} height={220} rx={28} fill={C.white} stroke={INK} strokeWidth={6} />
          <circle cx={0} cy={100} r={46} fill={C.error} stroke={INK} strokeWidth={6} />
          <rect x={-14} y={80 - 200 * lvl} width={28} height={200 * lvl + 20} rx={10} fill={C.error} />
          {[0, 1, 2, 3, 4].map((i) => (
            <line key={i} x1={36} x2={i % 2 ? 56 : 70} y1={-110 + i * 42} y2={-110 + i * 42} stroke={INK} strokeWidth={5} strokeLinecap="round" />
          ))}
          {value ? <text x={84} y={-70} fontSize={fit(value, 150, 56)} fontWeight={700} fill={INK}>{value}</text> : null}
        </g>
      );
    }
    case "dashboard": {
      const a = -15 + 45 * s + 8 * Math.sin(f / 7);
      if (gauge === "fuel") {
        const fa = -50 + 12 * s; // needle near a quarter tank, gently wobbling
        return (
          <g>
            <path d="M -140 60 A 140 140 0 0 1 140 60" fill="none" stroke={C.line} strokeWidth={26} strokeLinecap="round" />
            <path d="M -140 60 A 140 140 0 0 1 -99 -39" fill="none" stroke={C.error} strokeWidth={26} strokeLinecap="round" />
            {Array.from({ length: 5 }, (_, i) => {
              const t = Math.PI + (i / 4) * Math.PI;
              return <line key={i} x1={Math.cos(t) * 100} y1={60 + Math.sin(t) * 100} x2={Math.cos(t) * 118} y2={60 + Math.sin(t) * 118} stroke={INK} strokeWidth={6} />;
            })}
            <text x={-118} y={112} textAnchor="middle" fontSize={44} fontWeight={700} fill={C.error}>E</text>
            <text x={118} y={112} textAnchor="middle" fontSize={44} fontWeight={700} fill={INK}>F</text>
            {/* fuel pump glyph */}
            <g transform="translate(24 -4)">
              <rect x={0} y={0} width={34} height={46} rx={5} fill={INK} />
              <rect x={6} y={6} width={22} height={13} rx={3} fill={C.white} />
              <path d="M 34 12 L 44 20 L 44 40 Q 44 46 50 44" stroke={INK} strokeWidth={5} fill="none" strokeLinecap="round" />
            </g>
            <g transform={`translate(0 60) rotate(${fa})`}>
              <path d="M -8 0 L 0 -112 L 8 0 Z" fill={C.error} />
            </g>
            <circle cx={0} cy={60} r={18} fill={INK} />
            {value ? <text x={0} y={140} textAnchor="middle" fontSize={fit(value, 190, 44)} fontWeight={700} fill={INK}>{value}</text> : null}
          </g>
        );
      }
      return (
        <g>
          <path d="M -140 60 A 140 140 0 0 1 140 60" fill="none" stroke={C.line} strokeWidth={26} strokeLinecap="round" />
          <path d="M -140 60 A 140 140 0 0 1 40 -76" fill="none" stroke={C.good} strokeWidth={26} strokeLinecap="round" />
          <path d="M 70 -60 A 140 140 0 0 1 140 60" fill="none" stroke={C.error} strokeWidth={26} strokeLinecap="round" />
          {Array.from({ length: 9 }, (_, i) => {
            const t = Math.PI + (i / 8) * Math.PI;
            return <line key={i} x1={Math.cos(t) * 100} y1={60 + Math.sin(t) * 100} x2={Math.cos(t) * 115} y2={60 + Math.sin(t) * 115} stroke={INK} strokeWidth={5} />;
          })}
          <g transform={`translate(0 60) rotate(${a})`}>
            <path d="M -8 0 L 0 -112 L 8 0 Z" fill={C.error} />
          </g>
          <circle cx={0} cy={60} r={18} fill={INK} />
          <text x={0} y={130} textAnchor="middle" fontSize={value ? fit(value, 280, 44) : 40} fontWeight={700} fill={INK}>{value ?? "km/h"}</text>
        </g>
      );
    }
    case "dimmer": {
      const k = 0.5 + 0.35 * s;
      return (
        <g>
          <circle cx={-60} cy={-70} r={90} fill={C.gold} opacity={0.15 + 0.35 * k} />
          <path d="M -95 -80 A 35 35 0 1 1 -25 -80 Q -30 -55 -42 -40 L -78 -40 Q -90 -55 -95 -80 Z" fill={`rgba(246, 205, 90, ${0.4 + 0.6 * k})`} stroke={INK} strokeWidth={5} />
          <rect x={-76} y={-38} width={32} height={22} rx={4} fill={C.muted} />
          <rect x={40} y={-140} width={110} height={280} rx={18} fill={C.white} stroke={INK} strokeWidth={6} />
          <rect x={87} y={-110} width={16} height={220} rx={8} fill={C.line} />
          <rect x={65} y={110 - 220 * k - 18} width={60} height={36} rx={10} fill={C.forest} />
        </g>
      );
    }
    case "list":
      return (
        <g transform={`rotate(${-3 + s})`}>
          <rect x={-115} y={-145} width={230} height={290} rx={14} fill={C.white} stroke={INK} strokeWidth={6} />
          {[0, 1, 2, 3].map((i) => {
            const on = (f % 160) > 20 + i * 30;
            return (
              <g key={i} transform={`translate(0 ${-90 + i * 62})`}>
                <rect x={-90} y={-18} width={36} height={36} rx={6} fill="none" stroke={INK} strokeWidth={5} />
                {on ? <path d="M -84 0 L -74 12 L -56 -12" stroke={C.good} strokeWidth={7} fill="none" strokeLinecap="round" strokeLinejoin="round" /> : null}
                <rect x={-36} y={-6} width={110 - (i % 2) * 30} height={12} rx={6} fill={C.line} />
              </g>
            );
          })}
        </g>
      );
    case "contact":
    case "phone-contact":
      return (
        <g transform={`rotate(${Math.sin(f / 2) * (f % 90 < 20 ? 3 : 0)})`}>
          {icon === "phone-contact"
            ? [0, 1].map((i) => {
                const t = ((f + i * 22) % 44) / 44;
                return (
                  <g key={i} opacity={1 - t}>
                    <path d={`M ${108 + t * 20} -110 Q ${132 + t * 26} -70 ${108 + t * 20} -30`} stroke={C.good} strokeWidth={7} fill="none" strokeLinecap="round" />
                    <path d={`M ${-108 - t * 20} -110 Q ${-132 - t * 26} -70 ${-108 - t * 20} -30`} stroke={C.good} strokeWidth={7} fill="none" strokeLinecap="round" />
                  </g>
                );
              })
            : null}
          <rect x={-90} y={-150} width={180} height={300} rx={28} fill={INK} />
          <rect x={-76} y={-120} width={152} height={236} rx={10} fill={C.white} />
          <circle cx={0} cy={-50} r={38} fill={C.leaf} stroke={C.forest} strokeWidth={5} />
          <circle cx={0} cy={-60} r={14} fill={C.forest} />
          <path d="M -24 -24 Q 0 -44 24 -24" fill={C.forest} />
          <rect x={-55} y={10} width={110} height={14} rx={7} fill={C.forest} />
          <rect x={-45} y={38} width={90} height={12} rx={6} fill={C.line} />
          <circle cx={0} cy={86} r={18} fill={C.good} />
        </g>
      );
    case "receipt": {
      const out = 30 + 25 * c01((f % 120) / 60);
      return (
        <g>
          <g transform={`translate(30 ${-out})`}>
            <path d={`M -60 -110 L 60 -110 L 60 60 ${Array.from({ length: 6 }, (_, i) => `L ${60 - (i + 0.5) * 20} ${i % 2 ? 60 : 72} L ${60 - (i + 1) * 20} 60`).join(" ")} Z`} fill={C.white} stroke={INK} strokeWidth={5} />
            {[0, 1, 2, 3].map((i) => <rect key={i} x={-40} y={-85 + i * 30} width={i === 3 ? 50 : 80} height={10} rx={5} fill={i === 3 ? C.forest : C.line} />)}
          </g>
          <rect x={-140} y={0} width={280} height={160} rx={12} fill={C.leaf} stroke={INK} strokeWidth={6} />
          <path d="M -140 0 L 0 90 L 140 0" fill="none" stroke={INK} strokeWidth={6} strokeLinejoin="round" />
        </g>
      );
    }
    case "tap":
      return (
        <g>
          <rect x={-150} y={-120} width={40} height={90} rx={8} fill={C.muted} />
          <path d="M -110 -95 L 20 -95 Q 60 -95 60 -55 L 60 -30 L 30 -30 L 30 -55 Q 30 -65 20 -65 L -110 -65 Z" fill="#9aa3ad" stroke={INK} strokeWidth={5} />
          <rect x={-40} y={-140} width={20} height={45} fill={INK} />
          <rect x={-70} y={-150} width={80} height={16} rx={8} fill={INK} transform={`rotate(${s * 8} -30 -142)`} />
          <rect x={35} y={-28} width={20} height={170} rx={10} fill={C.water} opacity={0.9} />
          <path d="M 45 -28 L 45 142" stroke={C.white} strokeWidth={5} strokeDasharray="12 18" strokeDashoffset={-f * 4} opacity={0.7} />
          <ellipse cx={45} cy={140} rx={55 + 6 * s} ry={12} fill={C.water} opacity={0.6} />
        </g>
      );
    case "route": {
      const d = "M -120 110 C -60 110 -90 20 -20 10 S 40 -70 110 -90";
      const bob = Math.abs(Math.sin(f / 10)) * 12;
      return (
        <g>
          <rect x={-150} y={-140} width={300} height={280} rx={20} fill={C.leaf} />
          {[-75, 0, 75].map((x) => <line key={x} x1={x} y1={-140} x2={x} y2={140} stroke={C.white} strokeWidth={6} />)}
          {[-70, 0, 70].map((y) => <line key={y} x1={-150} y1={y} x2={150} y2={y} stroke={C.white} strokeWidth={6} />)}
          <path d={d} fill="none" stroke={C.forest} strokeWidth={10} strokeLinecap="round" strokeDasharray="18 14" strokeDashoffset={-f * 1.5} />
          <circle cx={-120} cy={110} r={14} fill={C.forest} />
          <g transform={`translate(110 ${-90 - bob})`}>
            <path d="M 0 0 C -30 -30 -30 -70 0 -70 C 30 -70 30 -30 0 0 Z" fill={C.error} />
            <circle cx={0} cy={-46} r={10} fill={C.white} />
          </g>
        </g>
      );
    }
    case "fridge": {
      const ring = f % 60 < 30;
      return (
        <g>
          <rect x={-90} y={-110} width={180} height={260} rx={20} fill={C.white} stroke={INK} strokeWidth={6} />
          <line x1={-90} y1={-20} x2={90} y2={-20} stroke={INK} strokeWidth={6} />
          <rect x={60} y={-90} width={10} height={50} rx={5} fill={INK} />
          <rect x={60} y={0} width={10} height={70} rx={5} fill={INK} />
          <g transform={`translate(0 -135) rotate(${ring ? Math.sin(f) * 14 : 0})`}>
            <path d="M -26 10 Q -26 -30 0 -30 Q 26 -30 26 10 L 32 18 L -32 18 Z" fill={C.warn} stroke={INK} strokeWidth={4} />
            <circle cx={0} cy={24} r={7} fill={INK} />
          </g>
          {ring ? [1, 2].map((i) => <path key={i} d={`M ${40 + i * 16} -160 q 12 15 0 30`} stroke={C.warn} strokeWidth={5} fill="none" strokeLinecap="round" />) : null}
          <text x={-40} y={60} textAnchor="middle" fontSize={38} fontWeight={700} fill={C.water}>4°</text>
        </g>
      );
    }
    case "postit":
      return (
        <g transform={`rotate(${-4 + s})`}>
          <rect x={-128} y={-122} width={260} height={260} fill="#000" opacity={0.08} />
          <path d={`M -135 -135 L 135 -135 L 135 ${95 + 4 * s} Q 110 135 85 135 L -135 135 Z`} fill={POSTIT} />
          <rect x={-135} y={-135} width={270} height={26} fill="#f5d55c" />
          <text x={0} y={35} textAnchor="middle" fontFamily={SERIF} fontSize={value ? fit(value, 240, 96) : 96} fill={INK}>{value ?? "60%"}</text>
        </g>
      );
    case "calendar": {
      const day = Math.floor(f / 45) % 5;
      return (
        <g>
          <rect x={-140} y={-120} width={280} height={260} rx={16} fill={C.white} stroke={INK} strokeWidth={6} />
          <rect x={-140} y={-120} width={280} height={60} rx={16} fill={C.forest} />
          {[-80, 80].map((x) => <rect key={x} x={x - 8} y={-140} width={16} height={40} rx={8} fill={INK} />)}
          {Array.from({ length: 15 }, (_, i) => {
            const x = -105 + (i % 5) * 52, y = -30 + Math.floor(i / 5) * 55;
            const hit = i === 5 + day;
            return <rect key={i} x={x} y={y} width={40} height={40} rx={8} fill={hit ? C.gold : C.leaf} transform={hit ? `translate(${x + 20} ${y + 20}) scale(${1 + 0.1 * Math.sin(f / 5)}) translate(${-x - 20} ${-y - 20})` : undefined} />;
          })}
        </g>
      );
    }
    case "budget": {
      const b = 0.6 + 0.04 * s;
      return (
        <g>
          {[-75, 75].map((x, i) => (
            <g key={x}>
              <rect x={x - 62} y={-140} width={124} height={280} rx={12} fill={C.white} stroke={INK} strokeWidth={5} />
              <rect x={x - 30} y={110 - 200 * (i ? b + 0.12 : b)} width={60} height={200 * (i ? b + 0.12 : b)} rx={6} fill={i ? C.warn : C.good} />
              <text x={x} y={-108} textAnchor="middle" fontSize={26} fontWeight={700} fill={INK}>{i ? "Actual" : "Plan"}</text>
            </g>
          ))}
        </g>
      );
    }
    case "person":
      return (
        <g>
          <Person y={-10} k={0.92} f={f} />
          <g transform={`rotate(${-20 + 18 * s} 92 60)`}>
            <path d="M 92 60 L 140 -40" stroke={C.forest} strokeWidth={30} strokeLinecap="round" />
            <circle cx={140} cy={-46} r={20} fill={C.solidLight} stroke={INK} strokeWidth={5} />
          </g>
        </g>
      );
    case "handover": {
      const t = (Math.sin(f / 25) + 1) / 2;
      const cx = lerp(-48, 48, t);
      return (
        <g>
          <Person x={-98} y={-10} k={0.55} col={C.forest} f={f} />
          <Person x={98} y={-10} k={0.55} col={C.gold} f={f + 30} />
          <path d={`M -62 30 Q ${(cx - 62) / 2} 50 ${cx - 22} 40`} stroke={C.forest} strokeWidth={16} fill="none" strokeLinecap="round" />
          <path d={`M 62 30 Q ${(cx + 62) / 2} 50 ${cx + 22} 40`} stroke="#8f7f48" strokeWidth={16} fill="none" strokeLinecap="round" />
          <g transform={`translate(${cx} 20) rotate(${(t - 0.5) * 16})`}>
            <rect x={-38} y={-52} width={76} height={100} rx={8} fill={C.solid} stroke={INK} strokeWidth={5} />
            <rect x={-28} y={-38} width={56} height={78} rx={3} fill={C.white} />
            <rect x={-16} y={-60} width={32} height={18} rx={5} fill={C.muted} stroke={INK} strokeWidth={3} />
            {[0, 1, 2].map((i) => <rect key={i} x={-20} y={-24 + i * 20} width={40 - (i % 2) * 12} height={7} rx={3} fill={C.line} />)}
          </g>
          <path d="M -40 120 L 40 120" stroke={C.good} strokeWidth={8} strokeLinecap="round" strokeDasharray="10 12" strokeDashoffset={-f * 2} />
          <path d="M 28 108 L 44 120 L 28 132" stroke={C.good} strokeWidth={8} fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      );
    }
    case "lightswitch": {
      const on = f % 90 < 45;
      return (
        <g>
          <circle cx={-70} cy={-60} r={90} fill={C.gold} opacity={on ? 0.45 : 0} />
          <path d="M -105 -70 A 35 35 0 1 1 -35 -70 Q -40 -45 -52 -30 L -88 -30 Q -100 -45 -105 -70 Z" fill={on ? "#f6cd5a" : C.white} stroke={INK} strokeWidth={5} />
          <rect x={-86} y={-28} width={32} height={22} rx={4} fill={C.muted} />
          {on ? [0, 1, 2, 3, 4].map((i) => {
            const a = (-150 + i * 30) * Math.PI / 180;
            return <line key={i} x1={-70 + Math.cos(a) * 52} y1={-75 + Math.sin(a) * 52} x2={-70 + Math.cos(a) * 72} y2={-75 + Math.sin(a) * 72} stroke={C.warn} strokeWidth={6} strokeLinecap="round" />;
          }) : null}
          <rect x={20} y={-120} width={130} height={220} rx={18} fill={C.white} stroke={INK} strokeWidth={6} />
          <rect x={55} y={-70} width={60} height={120} rx={10} fill={C.leaf} stroke={INK} strokeWidth={4} />
          <rect x={60} y={on ? -66 : -10} width={50} height={56} rx={8} fill={C.forest} />
          <text x={85} y={140} textAnchor="middle" fontSize={36} fontWeight={700} fill={on ? C.good : C.muted}>{on ? "ON" : "OFF"}</text>
        </g>
      );
    }
    case "car":
      return (
        <g>
          {[0, 1, 2].map((i) => <rect key={i} x={((-f * 6 + i * 120) % 360 + 360) % 360 - 180} y={128} width={60} height={8} rx={4} fill={C.line} />)}
          <g transform={`translate(0 ${Math.abs(Math.sin(f / 4)) * -3})`}>
            <path d="M -145 70 L -145 20 Q -140 0 -110 -5 L -70 -60 Q -60 -70 -40 -70 L 50 -70 Q 70 -70 85 -55 L 120 -5 Q 145 0 145 20 L 145 70 Z" fill={C.water} stroke={INK} strokeWidth={6} strokeLinejoin="round" />
            <path d="M -60 -10 L -35 -52 L -5 -52 L -5 -10 Z M 10 -10 L 10 -52 L 45 -52 L 80 -10 Z" fill={C.waterLight} stroke={INK} strokeWidth={4} strokeLinejoin="round" />
            <rect x={128} y={10} width={16} height={16} rx={4} fill={C.gold} />
          </g>
          <Wheel x={-85} y={72} r={36} f={f} />
          <Wheel x={85} y={72} r={36} f={f} />
        </g>
      );
    case "bus":
      return (
        <g>
          {[0, 1, 2].map((i) => <rect key={i} x={((-f * 5 + i * 120) % 360 + 360) % 360 - 180} y={134} width={60} height={8} rx={4} fill={C.line} />)}
          <g transform={`translate(0 ${Math.abs(Math.sin(f / 5)) * -3})`}>
            <rect x={-150} y={-110} width={300} height={190} rx={24} fill={C.gold} stroke={INK} strokeWidth={6} />
            {[0, 1, 2, 3].map((i) => <rect key={i} x={-132 + i * 58} y={-88} width={46} height={56} rx={8} fill={C.waterLight} stroke={INK} strokeWidth={4} />)}
            <rect x={104} y={-88} width={32} height={150} rx={6} fill={C.waterLight} stroke={INK} strokeWidth={4} />
            <line x1={120} y1={-88} x2={120} y2={62} stroke={INK} strokeWidth={3} />
            <rect x={-150} y={0} width={254} height={14} fill={C.forest} />
            <rect x={-146} y={40} width={16} height={18} rx={4} fill={C.error} />
          </g>
          <Wheel x={-90} y={84} r={32} f={f} />
          <Wheel x={70} y={84} r={32} f={f} />
        </g>
      );
    case "trolley":
      return (
        <g transform={`translate(${Math.sin(f / 15) * 10} 0)`}>
          <path d="M -150 -110 L -110 -110 L -70 60 L 110 60" stroke={INK} strokeWidth={8} fill="none" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M -105 -80 L 140 -80 L 115 30 L -80 30 Z" fill={C.white} stroke={INK} strokeWidth={6} strokeLinejoin="round" />
          {[-50, 0, 50, 100].map((x) => <line key={x} x1={x} y1={-80} x2={x - 6} y2={30} stroke={C.line} strokeWidth={5} />)}
          <line x1={-95} y1={-25} x2={128} y2={-25} stroke={C.line} strokeWidth={5} />
          <rect x={-60} y={-130} width={60} height={56} rx={8} fill={C.ec} stroke={INK} strokeWidth={4} transform={`rotate(${-8 + s * 3} -30 -100)`} />
          <rect x={10} y={-120} width={50} height={46} rx={8} fill={C.plant} stroke={INK} strokeWidth={4} />
          <circle cx={90} cy={-98} r={24} fill={C.error} stroke={INK} strokeWidth={4} />
          <Wheel x={-50} y={100} r={22} f={f} />
          <Wheel x={90} y={100} r={22} f={f} />
        </g>
      );
    case "toolbox": {
      const lid = Math.max(0, Math.sin(f / 18)) * 10;
      return (
        <g>
          <g transform={`translate(-40 ${-lid}) rotate(-18)`}>
            <rect x={-12} y={-150} width={24} height={110} rx={6} fill="#9aa3ad" stroke={INK} strokeWidth={4} />
            <circle cx={0} cy={-150} r={26} fill="#9aa3ad" stroke={INK} strokeWidth={4} />
            <rect x={-10} y={-180} width={20} height={34} fill={C.paper} />
          </g>
          <g transform={`translate(50 ${-lid}) rotate(14)`}>
            <rect x={-8} y={-140} width={16} height={90} rx={4} fill="#9aa3ad" stroke={INK} strokeWidth={3} />
            <rect x={-18} y={-70} width={36} height={60} rx={10} fill={C.gold} stroke={INK} strokeWidth={4} />
          </g>
          <path d="M -60 -70 L -60 -100 Q -60 -112 -48 -112 L 48 -112 Q 60 -112 60 -100 L 60 -70" stroke={INK} strokeWidth={10} fill="none" />
          <rect x={-150} y={-60} width={300} height={44} rx={10} fill="#c0392b" stroke={INK} strokeWidth={6} transform={`rotate(${-lid * 0.4} -150 -16)`} />
          <rect x={-150} y={-20} width={300} height={150} rx={14} fill={C.error} stroke={INK} strokeWidth={6} />
          <rect x={-24} y={-12} width={48} height={24} rx={5} fill={C.gold} stroke={INK} strokeWidth={4} />
        </g>
      );
    }
    case "house":
      return (
        <g>
          {[0, 1, 2].map((i) => {
            const t = ((f + i * 20) % 60) / 60;
            return <circle key={i} cx={85 + t * 20} cy={-120 - t * 50} r={10 + t * 14} fill={C.line} opacity={1 - t} />;
          })}
          <rect x={70} y={-120} width={36} height={70} fill={C.solid} stroke={INK} strokeWidth={5} />
          <rect x={-120} y={-10} width={240} height={150} fill={C.white} stroke={INK} strokeWidth={6} />
          <path d="M -150 0 L 0 -130 L 150 0 Z" fill={C.forest} stroke={INK} strokeWidth={6} strokeLinejoin="round" />
          <rect x={-30} y={50} width={60} height={90} rx={6} fill={C.solid} stroke={INK} strokeWidth={5} />
          <circle cx={18} cy={98} r={5} fill={C.gold} />
          {[-82, 52].map((x) => (
            <g key={x}>
              <rect x={x} y={30} width={50} height={50} rx={4} fill="#f6cd5a" opacity={0.75 + 0.25 * Math.sin(f / 12 + x)} stroke={INK} strokeWidth={4} />
              <line x1={x + 25} y1={30} x2={x + 25} y2={80} stroke={INK} strokeWidth={3} />
            </g>
          ))}
        </g>
      );
    case "plane":
      return (
        <g>
          {[0, 1].map((i) => {
            const x = ((-f * 4 + i * 200) % 400 + 400) % 400 - 200;
            return <ellipse key={i} cx={x} cy={i ? 110 : -110} rx={60} ry={20} fill={C.waterLight} />;
          })}
          <g transform={`translate(0 ${Math.sin(f / 15) * 10}) rotate(${-6 + Math.sin(f / 15) * 2})`}>
            <path d="M -150 -10 Q -150 -30 -120 -30 L 110 -30 Q 150 -30 150 0 Q 150 20 110 20 L -120 20 Q -150 20 -150 -10 Z" fill={C.white} stroke={INK} strokeWidth={6} />
            <path d="M -130 -28 L -150 -90 L -110 -90 L -80 -28 Z" fill={C.forest} stroke={INK} strokeWidth={5} strokeLinejoin="round" />
            <path d="M -20 0 L -70 90 L -30 90 L 50 0 Z" fill={C.forest} stroke={INK} strokeWidth={5} strokeLinejoin="round" />
            {[0, 1, 2, 3, 4].map((i) => <circle key={i} cx={-60 + i * 30} cy={-8} r={7} fill={C.water} />)}
            <path d="M 120 -22 Q 142 -18 144 -4 L 118 -4 Z" fill={C.waterLight} stroke={INK} strokeWidth={3} />
          </g>
        </g>
      );
    case "pot":
      return (
        <g>
          <CutPot f={f} cx={0} top={-15} w={250} bw={200} h={160} r={11} seed="an-pot" tray={false} plant={1}
            st={{ bulk: [[145 - bandFrac(0.65) * 160, 160]], filmAbove: 0.65, filmBelow: 0.65, split: 0, drip: 0, tray: 0, stream: 0, bubblesUp: 0, airIn: 0 }} />
        </g>
      );
    case "probe":
      return (
        <g>
          <CutPot f={f} cx={0} top={-60} w={290} bw={250} h={190} r={12} seed="an-probe" tray={false} probe={1} region={1}
            st={{ bulk: [[130 - bandFrac(0.6) * 190, 140]], filmAbove: 0.6, filmBelow: 0.6, split: 0, drip: 0, tray: 0, stream: 0, bubblesUp: 0, airIn: 0 }} />
        </g>
      );
    case "dripper":
      return (
        <g>
          <path d="M -150 -110 L 150 -110" stroke={POT} strokeWidth={14} strokeLinecap="round" />
          <rect x={-20} y={-112} width={40} height={50} rx={10} fill={C.forest} />
          {[0, 1, 2].map((i) => {
            const t = ((f + i * 12) % 36) / 36;
            return <path key={i} d={dropPath(0, lerp(-50, 60, t * t), 13)} fill={C.water} opacity={1 - t * 0.6} />;
          })}
          <ellipse cx={0} cy={80} rx={60 + 30 * ((f % 36) / 36)} ry={14} fill="none" stroke={WATER_DEEP} strokeWidth={4} opacity={1 - (f % 36) / 36} />
          <rect x={-140} y={90} width={280} height={60} rx={12} fill={C.solidLight} />
        </g>
      );
    case "app": {
      const t = (f % 150) / 150;
      return (
        <g>
          <rect x={-150} y={-110} width={300} height={210} rx={16} fill={INK} />
          <rect x={-136} y={-96} width={272} height={182} rx={8} fill={C.white} />
          <rect x={-30} y={100} width={60} height={30} fill={INK} />
          <rect x={-70} y={128} width={140} height={14} rx={7} fill={INK} />
          <path d="M -120 40 L -80 -40 L -40 -10 L 0 -50 L 40 0 L 80 -30 L 120 -60" fill="none" stroke={C.water} strokeWidth={8} pathLength={1} strokeDasharray={`${t} 2`} strokeLinecap="round" strokeLinejoin="round" />
          {value ? <text x={-120} y={-62} fontSize={fit(value, 240, 30)} fontWeight={700} fill={C.forest}>{value}</text> : null}
        </g>
      );
    }
    case "graph": {
      const pts = [[-140, -80], [-60, 20], [-50, -80], [30, 20], [40, -80], [130, 30]];
      const d = pts.map(([x, y], i) => `${i ? "L" : "M"} ${x} ${y}`).join(" ");
      const t = (f % 120) / 120;
      const seg = Math.min(4, Math.floor(t * 5));
      const lt = t * 5 - seg;
      const [x0, y0] = pts[seg], [x1, y1] = pts[seg + 1];
      return (
        <g>
          <line x1={-150} y1={110} x2={150} y2={110} stroke={INK} strokeWidth={5} />
          <line x1={-150} y1={110} x2={-150} y2={-130} stroke={INK} strokeWidth={5} />
          <path d={d} fill="none" stroke={C.water} strokeWidth={9} strokeLinejoin="round" strokeLinecap="round" />
          <circle cx={lerp(x0, x1, lt)} cy={lerp(y0, y1, lt)} r={14} fill={C.forest} stroke={C.white} strokeWidth={4} />
        </g>
      );
    }
    case "zone":
      return (
        <g>
          <path d="M -150 -60 L 150 -60" stroke={POT} strokeWidth={10} strokeLinecap="round" />
          {[-100, 0, 100].map((x, i) => {
            const t = ((f + i * 10) % 30) / 30;
            return (
              <g key={x}>
                <rect x={x - 10} y={-64} width={20} height={22} rx={5} fill={C.forest} />
                <path d={dropPath(x - 15, lerp(-36, 0, t), 6)} fill={C.water} opacity={1 - t * 0.5} />
                <path d={`M ${x - 45} 10 L ${x + 45} 10 L ${x + 35} 110 L ${x - 35} 110 Z`} fill={C.solidLight} stroke={POT} strokeWidth={6} strokeLinejoin="round" />
                <rect x={x - 41} y={30 + i * 6} width={82} height={78 - i * 6} fill={C.water} opacity={0.35} />
                <Plant x={x} y={8} h={40} f={f + i * 20} scale={0.45} />
              </g>
            );
          })}
          <rect x={-150} y={115} width={300} height={16} rx={8} fill={C.solid} />
        </g>
      );
    case "setting": {
      const k = 0.55 + 0.1 * s;
      return (
        <g>
          <rect x={-140} y={-120} width={280} height={110} rx={18} fill={C.white} stroke={INK} strokeWidth={6} />
          <text x={0} y={-45} textAnchor="middle" fontFamily={SERIF} fontSize={value ? fit(value, 250, 64) : 64} fill={C.forest}>{value ?? `${Math.round(50 + 30 * k)}%`}</text>
          <rect x={-130} y={50} width={260} height={16} rx={8} fill={C.line} />
          <rect x={-130} y={50} width={260 * k} height={16} rx={8} fill={C.forest} />
          <circle cx={-130 + 260 * k} cy={58} r={26} fill={C.white} stroke={C.forest} strokeWidth={6} />
        </g>
      );
    }
    case "ec":
      return (
        <g>
          <path d={dropPath(0, 50, 100)} fill={C.waterLight} stroke={WATER_DEEP} strokeWidth={6} />
          {[[-40, 40], [30, 70], [10, 0], [-30, 100], [45, 20]].map(([x, y], i) => (
            <rect key={i} x={x - 12} y={y - 12 + Math.sin(f / 15 + i) * 8} width={24} height={24} rx={4} fill={C.white} stroke={C.ec} strokeWidth={4} transform={`rotate(${20 * i + f} ${x} ${y})`} />
          ))}
        </g>
      );
  }
  return <path d={blobPath(0, 0, 100, "x")} fill={C.line} />;
}

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const maps = props.mappings || [];
  const count = 2 + maps.length;
  const sL = Number.isFinite(steps[0]) ? steps[0] : 0;
  const sR = stepAt(steps, 1, duration, count) || 40;
  const lp = pop(f, sL, 18);
  const rp = pop(f, sR, 18);
  const ap = ease(f, sR - 6, 20);
  const cardW = 720, cardH = maps.length ? 540 : 680;
  const cy = maps.length ? 315 : SH / 2;
  // Joiner: shrink to fit the gap between the cards; if still wider, sit on a white pill over the card edges.
  const joiner = props.joiner || "is like";
  const gapW = SW - 2 * 520 - cardW; // free width between the cards
  const joinSize = Math.max(24, Math.min(34, (gapW - 16) / Math.max(1, joiner.length * 0.56)));
  const joinW = joiner.length * joinSize * 0.56 + 28;
  const cards: [Side, number, number, string][] = [
    [props.left, 520, lp, C.gold],
    [props.right, SW - 520, rp, C.forest],
  ];
  return (
    <SceneSvg>
      {cards.map(([side, cx, p, col], i) =>
        p > 0.01 ? (
          <g key={i} transform={`translate(${cx} ${cy + Math.sin(f / 30 + i * 2) * 4}) scale(${0.85 + 0.15 * Math.min(p, 1.05)})`} opacity={c01(p * 1.5)}>
            <rect x={-cardW / 2 + 8} y={-cardH / 2 + 12} width={cardW} height={cardH} rx={36} fill="#000" opacity={0.06} />
            <rect x={-cardW / 2} y={-cardH / 2} width={cardW} height={cardH} rx={36} fill={C.white} stroke={col} strokeWidth={5} />
            <text x={0} y={-cardH / 2 + 56} textAnchor="middle" fontSize={30} fontWeight={700} letterSpacing={4} fill={col === C.gold ? "#8f7f48" : C.forest}>{i ? "IN THE GROW ROOM" : "EVERYDAY"}</text>
            <g transform={`translate(0 ${-20 + (maps.length ? 0 : -20)}) scale(${maps.length ? 1.05 : 1.35})`}>
              <IconArt icon={side.icon} f={f} value={side.value} gauge={side.gauge} />
            </g>
            <text x={0} y={cardH / 2 - 44} textAnchor="middle" fontFamily={SERIF} fontSize={side.label.length > 26 ? 40 : 50} fill={C.ink}>{side.label}</text>
          </g>
        ) : null,
      )}
      {/* "is like" connector */}
      <Arrow f={f} p={ap} color={C.gold} width={12} d={`M ${520 + cardW / 2 - 10} ${cy} L ${SW - 520 - cardW / 2 - 20} ${cy}`} head={{ x: SW - 520 - cardW / 2 - 8, y: cy, angle: 0 }} />
      {ap > 0.3 ? (
        <g transform={`translate(${SW / 2} ${cy - 62}) scale(${pop(f, sR, 14)})`}>
          {joinW - 28 > gapW ? <rect x={-joinW / 2} y={-joinSize * 1.05} width={joinW} height={joinSize * 1.5} rx={joinSize * 0.75} fill={C.white} stroke={C.gold} strokeWidth={3} /> : null}
          <text textAnchor="middle" fontSize={joinSize} fontWeight={700} fill="#8f7f48">{joiner}</text>
        </g>
      ) : null}

      {maps.map((m, i) => {
        const at = stepAt(steps, 2 + i, duration, count) || sR + 30 + i * 30;
        const p = pop(f, at, 16);
        const y = cy + cardH / 2 + 80 + i * 92;
        const big = Math.max(textW(m.from, 38), textW(m.to, 38)) > 700;
        return p > 0.01 ? (
          <g key={i}>
            <Pill x={SW / 2 - 70} y={y} text={m.from} anchor="end" size={big ? 32 : 38} color="#8f7f48" textColor={C.ink} p={p} />
            <Arrow f={f} p={ease(f, at + 4, 14)} color={C.forest} width={8} flow={false} d={`M ${SW / 2 - 50} ${y} L ${SW / 2 + 40} ${y}`} head={{ x: SW / 2 + 50, y, angle: 0 }} />
            <Pill x={SW / 2 + 70} y={y} text={m.to} anchor="start" size={big ? 32 : 38} color={C.forest} p={pop(f, at + 8, 16)} />
          </g>
        ) : null;
      })}
    </SceneSvg>
  );
};

export default {
  Component,
  doc: `Two-card "this is like that" analogy: left an everyday object, right the crop-steering idea, a drawn arrow ("is like") between, and optional mapping rows (left term → right term) underneath. Every icon is a live flat SVG drawing with gentle motion. Icons (either side): ${ICONS}. ('contact' = phone showing a contact, 'phone-contact' = same phone ringing, 'person' = waving person, 'handover' = two people passing a clipboard, 'lightswitch' = bulb + ON/OFF switch, 'trolley' = shopping trolley, 'pot' = mini cut-away pot with plant, 'probe' = substrate block with probe + glowing sensing zone, 'zone' = three pots on one drip line, 'setting' = slider with a % value, 'ec' = water drop with salt crystals, 'graph' = dryback saw-tooth, 'app' = screen with a drawing chart line (its corner text comes from value, e.g. 'VWC'; none by default).) props: {left:{icon,label,value?,gauge?}, right:{icon,label,value?,gauge?}, (value?: text shown on number icons — thermometer (no number unless given, e.g. '22°'), setting (default animated %), postit (default '60%'), bank (default '$'), dashboard (default 'km/h'); gauge?: dashboard only, 'speed' (default speedometer) | 'fuel' (E→F fuel gauge)), mappings?:[{from,to}] (max 3, keep each under ~30 chars), joiner?:'is like'}. steps: [left card, right card + arrow, then one per mapping].`,
  example: {
    props: {
      left: { icon: "thermometer", label: "Kitchen thermometer" },
      right: { icon: "probe", label: "Substrate probe" },
      mappings: [
        { from: "Reads the kitchen", to: "Reads one small spot" },
        { from: "Not the bedroom", to: "Not the other pots" },
      ],
    },
    steps: [5, 45, 95, 140],
  },
} satisfies SceneDef<P>;
