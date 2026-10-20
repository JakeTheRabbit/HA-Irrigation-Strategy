import React from "react";
import { interpolate, spring, Easing } from "remotion";
import { C, FONT } from "../theme";
import { clamp } from "../anim";

// Shared SVG helpers for the "system" scenes (WaterPath, SystemMap, HostSetup, OneOwner,
// SafetyStop, AckReceipt). Everything is a pure function of the frame passed in, so these
// can be used inside .map() without hook-order concerns.

export const SW = 1920;
export const SH = 988;
export type Pt = [number, number];

export const SvgStage: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <svg width={SW} height={SH} viewBox={`0 0 ${SW} ${SH}`} style={{ position: "absolute", inset: 0 }} fontFamily={FONT}>
    {children}
  </svg>
);

// 0→1 cubic ease-out over `len` frames from `start`.
export const ease = (f: number, start: number, len = 18) =>
  interpolate(f, [start, start + len], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });

// Spring pop (may overshoot slightly) from `start`.
export const pop = (f: number, start: number, fps = 30) =>
  f < start ? 0 : spring({ frame: f - start, fps, config: { damping: 14, stiffness: 120 } });

// Steps → frames with an even fallback spread (mirrors anim.stepAt but tolerates nulls/short arrays).
export const at = (steps: number[] | undefined, i: number, duration: number, count: number, lead = 6) => {
  const s = steps?.[i];
  if (typeof s === "number" && Number.isFinite(s)) return s;
  return Math.round(lead + ((duration * 0.8 - lead) * i) / Math.max(count, 1));
};

// Scale a group about a point.
export const Pop: React.FC<{ x: number; y: number; s: number; children: React.ReactNode; opacity?: number }> = ({ x, y, s, children, opacity }) => (
  <g opacity={opacity ?? Math.min(1, Math.max(0, s))} transform={`translate(${x} ${y}) scale(${Math.max(0.0001, s)}) translate(${-x} ${-y})`}>
    {children}
  </g>
);

export const T: React.FC<{
  x: number; y: number; size?: number; weight?: number; fill?: string; anchor?: "start" | "middle" | "end";
  children: React.ReactNode; opacity?: number; ls?: number; family?: string;
}> = ({ x, y, size = 32, weight = 700, fill = C.ink, anchor = "middle", children, opacity, ls, family }) => (
  <text x={x} y={y} fontSize={size} fontWeight={weight} fill={fill} textAnchor={anchor} opacity={opacity} letterSpacing={ls} fontFamily={family} dominantBaseline="middle">
    {children}
  </text>
);

// Pill label with a white background (good for labels over lines).
export const Pill: React.FC<{ x: number; y: number; w: number; text: string; color?: string; fill?: string; size?: number; textFill?: string; opacity?: number }> = ({
  x, y, w, text, color = C.forest, fill = C.white, size = 30, textFill, opacity,
}) => (
  <g opacity={opacity}>
    <rect x={x - w / 2} y={y - size * 0.95} width={w} height={size * 1.9} rx={size * 0.95} fill={fill} stroke={color} strokeWidth={3} />
    <T x={x} y={y + 1} size={size} fill={textFill ?? color}>{text}</T>
  </g>
);

export const pathD = (pts: Pt[]) => "M" + pts.map((p) => `${p[0]} ${p[1]}`).join(" L");

export const polyLen = (pts: Pt[]) => {
  let d = 0;
  for (let i = 1; i < pts.length; i++) d += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
  return d;
};

export const pointAt = (pts: Pt[], dist: number): Pt => {
  let d = Math.max(0, dist);
  for (let i = 1; i < pts.length; i++) {
    const seg = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    if (d <= seg) {
      const t = seg ? d / seg : 0;
      return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * t, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * t];
    }
    d -= seg;
  }
  return pts[pts.length - 1];
};

// Polyline drawn progressively (p = 0..1).
export const DrawLine: React.FC<{ pts: Pt[]; p: number; color: string; width: number; dash?: string; cap?: "round" | "butt"; opacity?: number }> = ({
  pts, p, color, width, dash, cap = "round", opacity,
}) => {
  const L = polyLen(pts);
  if (p <= 0) return null;
  if (dash) {
    // dashed line: clip by drawing only the visible prefix of points
    const end = pointAt(pts, L * p);
    const out: Pt[] = [pts[0]];
    let acc = 0;
    for (let i = 1; i < pts.length; i++) {
      const seg = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
      if (acc + seg >= L * p) break;
      acc += seg;
      out.push(pts[i]);
    }
    out.push(end);
    return <path d={pathD(out)} fill="none" stroke={color} strokeWidth={width} strokeDasharray={dash} strokeLinecap={cap} strokeLinejoin="round" opacity={opacity} />;
  }
  return (
    <path d={pathD(pts)} fill="none" stroke={color} strokeWidth={width} strokeLinecap={cap} strokeLinejoin="round" strokeDasharray={`${L * p} ${L + 10}`} opacity={opacity} />
  );
};

// Moving dashes along a path (flowing water / current).
export const Flow: React.FC<{ pts: Pt[]; f: number; color: string; width: number; speed?: number; dash?: number; gap?: number; opacity?: number }> = ({
  pts, f, color, width, speed = 4, dash = 26, gap = 22, opacity = 1,
}) => (
  <path d={pathD(pts)} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={`${dash} ${gap}`} strokeDashoffset={-f * speed} opacity={opacity} />
);

// Dots travelling along a polyline (data packets).
export const Pulses: React.FC<{ pts: Pt[]; f: number; n?: number; period?: number; color: string; r?: number; opacity?: number }> = ({
  pts, f, n = 3, period = 45, color, r = 11, opacity = 1,
}) => {
  const L = polyLen(pts);
  return (
    <g opacity={opacity}>
      {Array.from({ length: n }, (_, i) => {
        const t = (((f / period + i / n) % 1) + 1) % 1;
        const [x, y] = pointAt(pts, L * t);
        const fade = Math.min(1, t * 6, (1 - t) * 6);
        return (
          <g key={i} opacity={fade}>
            <circle cx={x} cy={y} r={r * 1.9} fill={color} opacity={0.22} />
            <circle cx={x} cy={y} r={r} fill={color} />
          </g>
        );
      })}
    </g>
  );
};

export const Check: React.FC<{ x: number; y: number; r?: number; color?: string; s?: number }> = ({ x, y, r = 34, color = C.good, s = 1 }) => (
  <Pop x={x} y={y} s={s}>
    <circle cx={x} cy={y} r={r} fill={color} />
    <path d={`M${x - r * 0.45} ${y + r * 0.02} L${x - r * 0.12} ${y + r * 0.36} L${x + r * 0.5} ${y - r * 0.34}`} fill="none" stroke={C.white} strokeWidth={r * 0.22} strokeLinecap="round" strokeLinejoin="round" />
  </Pop>
);

export const Cross: React.FC<{ x: number; y: number; r?: number; color?: string; s?: number }> = ({ x, y, r = 34, color = C.error, s = 1 }) => (
  <Pop x={x} y={y} s={s}>
    <circle cx={x} cy={y} r={r} fill={color} />
    <path d={`M${x - r * 0.38} ${y - r * 0.38} L${x + r * 0.38} ${y + r * 0.38} M${x + r * 0.38} ${y - r * 0.38} L${x - r * 0.38} ${y + r * 0.38}`} stroke={C.white} strokeWidth={r * 0.22} strokeLinecap="round" />
  </Pop>
);

// Blinking LED; `on` false = dark.
export const Led: React.FC<{ x: number; y: number; f: number; color?: string; period?: number; phase?: number; r?: number; on?: boolean }> = ({
  x, y, f, color = C.good, period = 30, phase = 0, r = 9, on = true,
}) => {
  const lit = on && ((f + phase) % period) < period * 0.55;
  return (
    <g>
      {lit ? <circle cx={x} cy={y} r={r * 2.2} fill={color} opacity={0.25} /> : null}
      <circle cx={x} cy={y} r={r} fill={lit ? color : "#5b665f"} stroke={C.forest} strokeWidth={1.5} />
    </g>
  );
};

// Eye icon (for "watch the outlet").
export const Eye: React.FC<{ x: number; y: number; w?: number; f: number; color?: string }> = ({ x, y, w = 110, f, color = C.forest }) => {
  const h = w * 0.55;
  const blink = (f % 75) > 70 ? 0.15 : 1;
  const look = Math.sin(f / 14) * w * 0.08;
  return (
    <g>
      <path d={`M${x - w / 2} ${y} Q${x} ${y - h * blink} ${x + w / 2} ${y} Q${x} ${y + h * blink} ${x - w / 2} ${y} Z`} fill={C.white} stroke={color} strokeWidth={5} />
      {blink > 0.5 ? (
        <>
          <circle cx={x + look} cy={y} r={h * 0.36} fill={color} />
          <circle cx={x + look + h * 0.1} cy={y - h * 0.1} r={h * 0.1} fill={C.white} />
        </>
      ) : null}
    </g>
  );
};

// Falling drops below a point (looping), `rate` 0..1 scales how many are visible.
export const Drips: React.FC<{ x: number; y0: number; y1: number; f: number; rate?: number; period?: number; phase?: number; color?: string; r?: number }> = ({
  x, y0, y1, f, rate = 1, period = 24, phase = 0, color = C.water, r = 9,
}) => {
  if (rate <= 0) return null;
  return (
    <g>
      {[0, 0.5].map((o, i) => {
        const t = ((((f + phase) / period + o) % 1) + 1) % 1;
        const y = y0 + (y1 - y0) * t * t;
        return (
          <path key={i} opacity={rate * Math.min(1, (1 - t) * 4)} d={`M${x} ${y - r * 1.6} Q${x + r} ${y} ${x} ${y + r} Q${x - r} ${y} ${x} ${y - r * 1.6} Z`} fill={color} />
        );
      })}
    </g>
  );
};

// Numbered stage badge.
export const Badge: React.FC<{ x: number; y: number; n: number | string; color?: string; r?: number }> = ({ x, y, n, color = C.forest, r = 26 }) => (
  <g>
    <circle cx={x} cy={y} r={r} fill={color} />
    <T x={x} y={y + 1} size={r * 1.15} fill={C.white}>{n}</T>
  </g>
);

// Small "Home Assistant" house mark.
export const HaMark: React.FC<{ x: number; y: number; s?: number; color?: string }> = ({ x, y, s = 1, color = "#41bdf5" }) => (
  <g transform={`translate(${x} ${y}) scale(${s})`}>
    <path d="M-30 4 L0 -26 L30 4 L30 30 L-30 30 Z" fill={color} />
    <circle cx={0} cy={6} r={6} fill={C.white} />
    <path d="M0 12 L0 30 M0 18 L-10 10 M0 22 L10 14" stroke={C.white} strokeWidth={3.5} strokeLinecap="round" />
  </g>
);

// Soft drop shadow filter def; include once per SVG and use filter="url(#sh)".
export const Defs: React.FC = () => (
  <defs>
    <filter id="sh" x="-20%" y="-20%" width="140%" height="150%">
      <feDropShadow dx="0" dy="10" stdDeviation="12" floodColor="#183e35" floodOpacity="0.13" />
    </filter>
    <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="10" />
    </filter>
  </defs>
);

// Card with header strip.
export const Card: React.FC<{ x: number; y: number; w: number; h: number; title?: string; color?: string; fill?: string; children?: React.ReactNode; opacity?: number; dim?: boolean; glow?: boolean }> = ({
  x, y, w, h, title, color = C.forest, fill = C.white, children, opacity = 1, dim, glow,
}) => (
  <g opacity={opacity * (dim ? 0.35 : 1)}>
    {glow ? <rect x={x - 10} y={y - 10} width={w + 20} height={h + 20} rx={34} fill="none" stroke={C.gold} strokeWidth={8} opacity={0.9} /> : null}
    <rect x={x} y={y} width={w} height={h} rx={26} fill={fill} stroke={color} strokeWidth={4} filter="url(#sh)" />
    {title ? <T x={x + 28} y={y + 38} size={30} fill={color} anchor="start" ls={3}>{title}</T> : null}
    {children}
  </g>
);
