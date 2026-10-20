import React from "react";
import { C, FONT } from "../theme";

// Shared drawing helpers for the measurement scenes (DayGraph, DrybackBars, SaltWater,
// MeasurementMap, ReadingAge). Everything is SVG in a 1920 × 988 stage coordinate space.
export const SW = 1920;
export const SH = 988;

export const Svg: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <svg viewBox={`0 0 ${SW} ${SH}`} preserveAspectRatio="xMidYMid meet" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", fontFamily: FONT }}>
    {children}
  </svg>
);

// Gentle periodic motion: sin wave of `period` frames.
export const wave = (f: number, period: number, phase = 0) => Math.sin((f / period) * Math.PI * 2 + phase);

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

// Rough text width for pill backgrounds (DM Sans averages ~0.56 em).
export const textW = (s: string, size: number, k = 0.56) => s.length * size * k;

// Text with a rounded background, anchored at its centre.
export const Pill: React.FC<{
  x: number;
  y: number;
  text: string;
  size?: number;
  color?: string;
  bg?: string;
  border?: string;
  weight?: number;
  opacity?: number;
  scale?: number;
}> = ({ x, y, text, size = 32, color = C.ink, bg = C.white, border, weight = 700, opacity = 1, scale = 1 }) => {
  const w = textW(text, size) + size * 1.2;
  const h = size * 1.7;
  return (
    <g opacity={opacity} transform={`translate(${x} ${y}) scale(${scale})`}>
      <rect x={-w / 2} y={-h / 2} width={w} height={h} rx={h / 2} fill={bg} stroke={border ?? "none"} strokeWidth={border ? 3 : 0} />
      <text x={0} y={size * 0.35} textAnchor="middle" fontSize={size} fontWeight={weight} fill={color}>
        {text}
      </text>
    </g>
  );
};

export const Sun: React.FC<{ x: number; y: number; r?: number; f: number }> = ({ x, y, r = 26, f }) => (
  <g transform={`translate(${x} ${y}) rotate(${f * 0.6})`}>
    {Array.from({ length: 8 }, (_, i) => (
      <line key={i} x1={0} y1={-r - 8} x2={0} y2={-r - 20 - 3 * wave(f, 40, i)} stroke={C.gold} strokeWidth={6} strokeLinecap="round" transform={`rotate(${i * 45})`} />
    ))}
    <circle r={r} fill="#f2c94c" stroke={C.gold} strokeWidth={4} />
  </g>
);

export const Moon: React.FC<{ x: number; y: number; r?: number; f: number }> = ({ x, y, r = 26, f }) => (
  <g transform={`translate(${x} ${y + 4 * wave(f, 90)}) rotate(-20)`}>
    <path d={`M 0 ${-r} A ${r} ${r} 0 1 0 0 ${r} A ${r * 0.72} ${r} 0 1 1 0 ${-r} Z`} fill="#f2d77a" stroke={C.gold} strokeWidth={3} />
  </g>
);

// Monotone cubic (Fritsch–Carlson) path through points sorted by x: smooth, never overshoots.
export function monoPath(pts: [number, number][]): string {
  const n = pts.length;
  if (n === 0) return "";
  if (n === 1) return `M ${pts[0][0]} ${pts[0][1]}`;
  const dx: number[] = [];
  const m: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    dx.push(pts[i + 1][0] - pts[i][0]);
    m.push((pts[i + 1][1] - pts[i][1]) / Math.max(dx[i], 1e-6));
  }
  const t: number[] = [m[0]];
  for (let i = 1; i < n - 1; i++) t.push(m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2);
  t.push(m[n - 2]);
  for (let i = 0; i < n - 1; i++) {
    if (m[i] === 0) {
      t[i] = 0;
      t[i + 1] = 0;
      continue;
    }
    const a = t[i] / m[i];
    const b = t[i + 1] / m[i];
    const s = a * a + b * b;
    if (s > 9) {
      const k = 3 / Math.sqrt(s);
      t[i] = k * a * m[i];
      t[i + 1] = k * b * m[i];
    }
  }
  let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    d += ` C ${(pts[i][0] + h).toFixed(1)} ${(pts[i][1] + t[i] * h).toFixed(1)} ${(pts[i + 1][0] - h).toFixed(1)} ${(pts[i + 1][1] - t[i + 1] * h).toFixed(1)} ${pts[i + 1][0].toFixed(1)} ${pts[i + 1][1].toFixed(1)}`;
  }
  return d;
}

// Big check / cross marks.
export const Tick: React.FC<{ x: number; y: number; s?: number; p?: number; color?: string }> = ({ x, y, s = 40, p = 1, color = C.good }) => (
  <g transform={`translate(${x} ${y})`}>
    <circle r={s} fill={color} opacity={p} />
    <path d={`M ${-s * 0.45} 0 L ${-s * 0.1} ${s * 0.35} L ${s * 0.5} ${-s * 0.35}`} fill="none" stroke={C.white} strokeWidth={s * 0.18} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={s * 2} strokeDashoffset={s * 2 * (1 - p)} />
  </g>
);

export const Cross: React.FC<{ x: number; y: number; s?: number; p?: number; color?: string }> = ({ x, y, s = 40, p = 1, color = C.error }) => (
  <g transform={`translate(${x} ${y})`}>
    <circle r={s} fill={color} opacity={p} />
    <g stroke={C.white} strokeWidth={s * 0.18} strokeLinecap="round" opacity={p}>
      <line x1={-s * 0.38} y1={-s * 0.38} x2={s * 0.38} y2={s * 0.38} />
      <line x1={s * 0.38} y1={-s * 0.38} x2={-s * 0.38} y2={s * 0.38} />
    </g>
  </g>
);

// Vertical measuring bracket on the right of x, spanning y1..y2, with a label.
export const Bracket: React.FC<{ x: number; y1: number; y2: number; p: number; color: string; label: string; size?: number; side?: 1 | -1 }> = ({ x, y1, y2, p, color, label, size = 40, side = 1 }) => {
  const ym = (y1 + y2) / 2;
  const half = ((y2 - y1) / 2) * p;
  const k = 22 * side;
  return (
    <g opacity={Math.min(1, p * 2)}>
      <path d={`M ${x} ${ym - half} h ${k} V ${ym + half} h ${-k}`} fill="none" stroke={color} strokeWidth={6} strokeLinecap="round" strokeLinejoin="round" />
      <line x1={x + k} y1={ym} x2={x + k * 1.8} y2={ym} stroke={color} strokeWidth={6} strokeLinecap="round" />
      <Pill x={x + k * 1.8 + side * (textW(label, size) / 2 + size * 0.75)} y={ym} text={label} size={size} color={C.white} bg={color} opacity={p} />
    </g>
  );
};
