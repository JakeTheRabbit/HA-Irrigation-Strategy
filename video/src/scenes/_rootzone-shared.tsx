import React, { useMemo } from "react";
import { interpolate, random, Easing } from "remotion";
import { C, FONT } from "../theme";
import { clamp } from "../anim";

// Shared drawing helpers for the root-zone scenes (PotCrossSection, SpongeDemo, VolumeGrid,
// ProbeZone, Analogy). Everything is a pure function of the frame number passed in.

export const SW = 1920;
export const SH = 988;
export const SPONGE = "#f2c14e";
export const SPONGE_DARK = "#c99a2e";
export const SCOUR = "#3f7a4f";
export const POSTIT = "#ffe27a";
export const WATER_DEEP = "#2f7fbf";
export const ROOT_LIGHT = "#f6ecd8";
export const POT = "#2c3a4f";

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const c01 = (v: number) => Math.max(0, Math.min(1, v));
export const ease = (f: number, start: number, len = 18) =>
  interpolate(f, [start, start + len], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
export const easeIO = (f: number, start: number, len: number) =>
  interpolate(f, [start, start + Math.max(1, len)], [0, 1], { ...clamp, easing: Easing.inOut(Easing.cubic) });
// Spring-ish overshoot pop 0→1 (pure, no fps needed).
export const pop = (f: number, start: number, len = 16) =>
  interpolate(f, [start, start + len * 0.6, start + len], [0, 1.08, 1], { ...clamp, easing: Easing.out(Easing.quad) });

type Pt = [number, number];

// Closed smooth curve through points (Catmull-Rom → cubic Bézier).
export function closedCurve(p: Pt[]): string {
  const n = p.length;
  let d = `M ${p[0][0].toFixed(1)} ${p[0][1].toFixed(1)}`;
  for (let i = 0; i < n; i++) {
    const p0 = p[(i - 1 + n) % n], p1 = p[i], p2 = p[(i + 1) % n], p3 = p[(i + 2) % n];
    const c1: Pt = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2: Pt = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C ${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d + " Z";
}

// Open smooth curve through points.
export function openCurve(p: Pt[]): string {
  const n = p.length;
  let d = `M ${p[0][0].toFixed(1)} ${p[0][1].toFixed(1)}`;
  for (let i = 0; i < n - 1; i++) {
    const p0 = p[Math.max(0, i - 1)], p1 = p[i], p2 = p[i + 1], p3 = p[Math.min(n - 1, i + 2)];
    const c1: Pt = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2: Pt = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C ${c1[0].toFixed(1)} ${c1[1].toFixed(1)} ${c2[0].toFixed(1)} ${c2[1].toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}

// Irregular rounded particle.
export function blobPath(cx: number, cy: number, r: number, seed: string, pts = 7, irr = 0.26): string {
  const rot = random(seed + "rot") * Math.PI * 2;
  const p: Pt[] = [];
  for (let i = 0; i < pts; i++) {
    const a = rot + (i / pts) * Math.PI * 2;
    const rr = r * (1 - irr / 2 + irr * random(seed + i));
    p.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr * 0.9]);
  }
  return closedCurve(p);
}

export function dropPath(x: number, y: number, r: number): string {
  // Teardrop with the point upward, centred on the round bottom at (x, y).
  return `M ${x} ${y - r * 2.1} C ${x + r * 0.35} ${y - r * 1.3} ${x + r} ${y - r * 0.8} ${x + r} ${y} A ${r} ${r} 0 0 1 ${x - r} ${y} C ${x - r} ${y - r * 0.8} ${x - r * 0.35} ${y - r * 1.3} ${x} ${y - r * 2.1} Z`;
}

export const textW = (s: string, size: number) => s.length * size * 0.54;

// Rounded label pill drawn in SVG. p = 0..1 reveal.
export const Pill: React.FC<{
  x: number; y: number; text: string; p?: number; color?: string; size?: number;
  anchor?: "start" | "middle" | "end"; fill?: string; textColor?: string; bold?: boolean;
}> = ({ x, y, text, p = 1, color = C.forest, size = 36, anchor = "middle", fill = C.white, textColor, bold = true }) => {
  if (p <= 0.001) return null;
  const w = textW(text, size) + size * 1.2;
  const h = size * 1.75;
  const cx = anchor === "start" ? x + w / 2 : anchor === "end" ? x - w / 2 : x;
  const s = 0.7 + 0.3 * Math.min(p, 1.08);
  return (
    <g transform={`translate(${cx} ${y}) scale(${s})`} opacity={c01(p * 1.4)}>
      <rect x={-w / 2} y={-h / 2} width={w} height={h} rx={h / 2} fill={fill} stroke={color} strokeWidth={3.5} />
      <text x={0} y={size * 0.36} textAnchor="middle" fontFamily={FONT} fontWeight={bold ? 700 : 500} fontSize={size} fill={textColor || color}>{text}</text>
    </g>
  );
};

// Animated drawn arrow: path draws in (p 0→1), then a dashed flow travels along it forever.
export const Arrow: React.FC<{
  d: string; p: number; f: number; color?: string; width?: number; head: { x: number; y: number; angle: number }; flow?: boolean;
}> = ({ d, p, f, color = C.forest, width = 10, head, flow = true }) => {
  if (p <= 0.001) return null;
  const hp = c01((p - 0.75) / 0.25);
  return (
    <g>
      <path d={d} pathLength={1} fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" strokeDasharray={`${c01(p)} 2`} opacity={0.95} />
      {flow && p >= 1 ? (
        <path d={d} pathLength={100} fill="none" stroke={C.white} strokeWidth={width * 0.36} strokeLinecap="round" strokeDasharray="3 9" strokeDashoffset={-f * 0.5} opacity={0.75} />
      ) : null}
      <g transform={`translate(${head.x} ${head.y}) rotate(${head.angle}) scale(${hp})`}>
        <path d={`M ${width * 2.4} 0 L ${-width * 1.2} ${-width * 1.9} L ${-width * 0.5} 0 L ${-width * 1.2} ${width * 1.9} Z`} fill={color} />
      </g>
    </g>
  );
};

// Leaf (simple pointed ellipse) pointing along +x from origin.
export const leafPath = (len: number, wid: number) =>
  `M 0 0 C ${len * 0.3} ${-wid} ${len * 0.75} ${-wid * 0.8} ${len} 0 C ${len * 0.75} ${wid * 0.8} ${len * 0.3} ${wid} 0 0 Z`;

// Fan-leaf plant with gentle sway. Base at (x, y), grows upward `h` px.
export const Plant: React.FC<{ x: number; y: number; h: number; f: number; scale?: number; p?: number }> = ({ x, y, h, f, scale = 1, p = 1 }) => {
  const sway = Math.sin(f / 38) * 2.2;
  const fan = (cx: number, cy: number, s: number, rot: number, k: number) => (
    <g key={k} transform={`translate(${cx} ${cy}) rotate(${rot + Math.sin(f / 30 + k) * 3}) scale(${s})`}>
      {[-70, -35, 0, 35, 70].map((a, i) => (
        <path key={i} d={leafPath(i === 2 ? 95 : i === 1 || i === 3 ? 80 : 55, 15)} transform={`rotate(${-90 + a})`} fill={i % 2 ? "#5d9a68" : C.plant} />
      ))}
    </g>
  );
  return (
    <g transform={`translate(${x} ${y}) scale(${scale * p}) rotate(${sway})`}>
      <path d={`M 0 0 C 4 ${-h * 0.35} -4 ${-h * 0.7} 0 ${-h}`} stroke={C.plant} strokeWidth={10} fill="none" strokeLinecap="round" />
      {fan(0, -h, 0.95, 0, 1)}
      {fan(0, -h * 0.62, 0.8, -58, 2)}
      {fan(0, -h * 0.62, 0.8, 58, 3)}
      {fan(0, -h * 0.3, 0.62, -75, 4)}
      {fan(0, -h * 0.3, 0.62, 75, 5)}
    </g>
  );
};

// ---------------------------------------------------------------------------------------
// Cut-away pot of substrate: particles, water films/bulk water, air gaps, roots, drips.
// ---------------------------------------------------------------------------------------

export type Particle = { x: number; y: number; r: number; d: string; hl: string; row: number };

export function useParticles(cx: number, top: number, w: number, bw: number, h: number, r: number, seed: string) {
  return useMemo(() => {
    const out: Particle[] = [];
    const gaps: Pt[] = [];
    const s = r * 2.55;
    const rowH = s * 0.86;
    const sTop = top + r * 0.9;
    const bottom = top + h;
    let row = 0;
    const rows: Particle[][] = [];
    for (let y = sTop; y < bottom - r * 0.4; y += rowH, row++) {
      const t = (y - top) / h;
      const half = lerp(w, bw, t) / 2;
      const off = row % 2 ? s / 2 : 0;
      const cur: Particle[] = [];
      for (let x = cx - half - s + off; x < cx + half + s; x += s) {
        const k = `${seed}-${row}-${Math.round(x)}`;
        const px = x + (random(k + "x") - 0.5) * s * 0.3;
        const py = y + (random(k + "y") - 0.5) * rowH * 0.3;
        const pr = r * (0.82 + 0.36 * random(k + "r"));
        const p: Particle = { x: px, y: py, r: pr, d: blobPath(px, py, pr, k), hl: blobPath(px - pr * 0.22, py - pr * 0.28, pr * 0.48, k + "h", 6, 0.3), row };
        out.push(p);
        cur.push(p);
      }
      rows.push(cur);
    }
    for (let i = 0; i + 1 < rows.length; i++) {
      for (let j = 0; j + 1 < rows[i].length; j++) {
        const a = rows[i][j], b = rows[i][j + 1];
        const c = rows[i + 1].reduce((m, q) => (Math.abs(q.x - (a.x + b.x) / 2) < Math.abs(m.x - (a.x + b.x) / 2) ? q : m), rows[i + 1][0]);
        gaps.push([(a.x + b.x + c.x) / 3, (a.y + b.y + c.y) / 3]);
      }
    }
    return { particles: out, gaps, sTop: top + 4, bottom };
  }, [cx, top, w, bw, h, r, seed]);
}

// Height fraction of the saturated "perched" band that sits at the bottom of a pot for level L.
export const bandFrac = (L: number) => (L >= 1 ? 1 : Math.pow(c01((L - 0.45) / 0.55), 2));
// Water-film thickness around each particle for level L.
export const filmFor = (L: number, r: number) => 1 + r * 0.42 * Math.pow(c01(L), 1.1);

export type PotState = {
  bulk: [number, number][]; // saturated bands [yTop, yBottom] (absolute)
  front?: number; // fingered wetting front y (bottom edge of the first band) during fill
  filmAbove: number; // film level above `split`
  filmBelow: number; // film level below `split`
  split: number;
  drip: number; // 0..1 drip rate out of the bottom
  tray: number; // 0..1 tray water
  stream: number; // 0..1 water pouring in from the emitter
  bubblesUp: number; // displaced air rising through saturated water
  airIn: number; // air entering the top as water drains
};

export const CutPot: React.FC<{
  f: number; cx: number; top: number; w: number; bw: number; h: number; r?: number; seed?: string;
  st: PotState; emitter?: boolean; roots?: number; probe?: number; region?: number; plant?: number; tray?: boolean;
}> = ({ f, cx, top, w, bw, h, r = 19, seed = "pot", st, emitter = false, roots = 0, probe = 0, region = 0, plant = 0, tray = true }) => {
  const { particles, sTop, bottom } = useParticles(cx, top, w, bw, h, r, seed);
  const id = `cp-${seed}`;
  const L = cx - w / 2, R = cx + w / 2;
  const interior = `M ${L} ${top} L ${R} ${top} L ${cx + bw / 2} ${bottom} L ${cx - bw / 2} ${bottom} Z`;
  const k = Math.min(1, w / 700);
  const wall = Math.max(10, 22 * k);
  const wave = (x: number, amp: number, k: number) => amp * (Math.sin(x * 0.028 + f * 0.12 + k) * 0.6 + Math.sin(x * 0.071 - f * 0.08 + k * 2) * 0.4);
  const band = (y0: number, y1: number, fingered: boolean, k: number) => {
    const xs: number[] = [];
    for (let x = L - 20; x <= R + 20; x += 14) xs.push(x);
    const topEdge = xs.map((x) => `${x} ${(y0 + (y0 > sTop + 6 ? wave(x, 5, k) : 0)).toFixed(1)}`);
    const botEdge = xs
      .slice()
      .reverse()
      .map((x) => `${x} ${(fingered ? y1 + 16 * Math.sin(x * 0.045 + k) * Math.sin(x * 0.013 + 1.3) + 6 * Math.sin(x * 0.11 + f * 0.05) : y1).toFixed(1)}`);
    return `M ${topEdge.join(" L ")} L ${botEdge.join(" L ")} Z`;
  };
  const trayTop = bottom + 62, trayH = 52, trayW = bw * 1.55;
  const trayWater = trayTop + trayH - 6 - st.tray * (trayH - 16);
  const holes = [-0.27, 0, 0.27].map((u) => cx + u * bw);
  const probeX = cx + w * 0.2;
  const rootTips: Pt[][] = [
    [[0, 0], [-8, 60], [-30, 150], [-60, 250], [-120, 340], [-150, 430]],
    [[0, 0], [12, 80], [30, 180], [70, 270], [110, 360], [170, 440]],
    [[0, 0], [2, 110], [-4, 230], [6, 340], [-10, 470]],
    [[-30, 150], [-90, 180], [-170, 210], [-230, 260]],
    [[30, 180], [100, 200], [170, 240], [230, 230]],
    [[-60, 250], [-30, 310], [-40, 380]],
    [[70, 270], [40, 330], [60, 400]],
    [[6, 340], [-60, 380], [-100, 440]],
    [[-4, 230], [60, 280], [90, 330]],
  ];
  const rootW = [11, 11, 9, 6, 6, 4, 4, 4, 4];
  const sway = Math.sin(f / 40) * 3;
  // Bubbles: rising through saturated water (fill) or entering from the top (drain).
  const bubbles: React.ReactNode[] = [];
  if (st.bubblesUp > 0.01 && st.bulk.length) {
    const [y0, y1] = st.bulk[0];
    for (let i = 0; i < 14; i++) {
      const per = 50 + random(`bu${i}`) * 40;
      const t = ((f + random(`bo${i}`) * per) % per) / per;
      const x = lerp(L + 40, R - 40, random(`bx${i}`)) + Math.sin(f / 9 + i) * 5;
      const y = lerp(y1, y0, t);
      bubbles.push(<circle key={`u${i}`} cx={x} cy={y} r={4 + random(`br${i}`) * 5} fill={C.white} stroke={WATER_DEEP} strokeWidth={1.5} opacity={st.bubblesUp * Math.sin(t * Math.PI)} />);
    }
  }
  if (st.airIn > 0.01) {
    for (let i = 0; i < 12; i++) {
      const per = 70 + random(`ai${i}`) * 40;
      const t = ((f + random(`ao${i}`) * per) % per) / per;
      const x = lerp(L + 50, R - 50, random(`ax${i}`)) + Math.sin(f / 11 + i) * 6;
      const y = lerp(sTop - 10, sTop + h * 0.45, t);
      bubbles.push(<circle key={`a${i}`} cx={x} cy={y} r={5 + random(`ar${i}`) * 4} fill={C.white} stroke={C.muted} strokeWidth={1.5} opacity={st.airIn * Math.sin(t * Math.PI)} />);
    }
  }
  // Sparkles inside saturated water.
  const sparkles = st.bulk.flatMap(([y0, y1], b) =>
    Array.from({ length: 10 }, (_, i) => {
      const x = lerp(L + 30, R - 30, random(`sp${b}${i}`));
      const y = lerp(y0 + 8, y1 - 8, random(`sq${b}${i}`));
      const o = Math.max(0, Math.sin(f / 14 + i * 1.7));
      return y1 - y0 > 20 ? <rect key={`${b}-${i}`} x={x + Math.sin(f / 20 + i) * 8} y={y} width={16} height={3} rx={1.5} fill={C.white} opacity={o * 0.7} /> : null;
    }),
  );
  return (
    <g>
      <defs>
        <clipPath id={id}>
          <path d={interior} />
        </clipPath>
        <radialGradient id={`${id}-reg`}>
          <stop offset="0" stopColor={C.gold} stopOpacity={0.45} />
          <stop offset="0.7" stopColor={C.gold} stopOpacity={0.2} />
          <stop offset="1" stopColor={C.gold} stopOpacity={0} />
        </radialGradient>
      </defs>
      {/* tray */}
      {tray ? (
        <g>
          <path d={`M ${cx - trayW / 2} ${trayTop} L ${cx + trayW / 2} ${trayTop} L ${cx + trayW / 2 - 18} ${trayTop + trayH} L ${cx - trayW / 2 + 18} ${trayTop + trayH} Z`} fill={C.white} stroke={POT} strokeWidth={6} strokeLinejoin="round" />
          <path d={`M ${cx - trayW / 2 + 12} ${trayWater + Math.sin(f / 10) * 1.5} Q ${cx} ${trayWater - 4 + Math.sin(f / 8) * 2} ${cx + trayW / 2 - 12} ${trayWater - Math.sin(f / 10) * 1.5} L ${cx + trayW / 2 - 21} ${trayTop + trayH - 3} L ${cx - trayW / 2 + 21} ${trayTop + trayH - 3} Z`} fill={C.water} opacity={0.85} />
        </g>
      ) : null}
      {/* drips into the tray */}
      {st.drip > 0.03
        ? holes.map((hx, i) => {
            const per = 22 + i * 5;
            const t = ((f + i * 9) % per) / per;
            const y = lerp(bottom + 4, trayWater, t * t);
            const rip = ((f + i * 9 - per * 0.95) % per) / per;
            return (
              <g key={i} opacity={c01(st.drip * 1.6)}>
                <path d={dropPath(hx, y, 7 + 5 * st.drip)} fill={C.water} />
                <ellipse cx={hx} cy={trayWater} rx={6 + rip * 26} ry={2 + rip * 5} fill="none" stroke={WATER_DEEP} strokeWidth={2} opacity={(1 - rip) * 0.8} />
              </g>
            );
          })
        : null}
      {/* interior */}
      <g clipPath={`url(#${id})`}>
        <rect x={L - 30} y={top - 30} width={w + 60} height={h + 60} fill={C.air} />
        {st.bulk.map(([y0, y1], i) => (y1 - y0 > 1 ? <path key={i} d={band(y0, y1, i === 0 && st.front != null, i)} fill={C.water} /> : null))}
        {particles.map((p, i) => {
          const lv = p.y < st.split ? st.filmAbove : st.filmBelow;
          const film = filmFor(lv, p.r) * (1 + 0.06 * Math.sin(f / 16 + i));
          return <path key={`f${i}`} d={p.d} fill={C.water} stroke={C.water} strokeWidth={film * 2} strokeLinejoin="round" />;
        })}
        {particles.map((p, i) => (
          <g key={`p${i}`}>
            <path d={p.d} fill={C.solid} />
            <path d={p.hl} fill={C.solidLight} opacity={0.55} />
          </g>
        ))}
        {sparkles}
        {bubbles}
        {/* roots */}
        {roots > 0 ? (
          <g transform={`translate(${cx} ${sTop - 6}) skewX(${sway * 0.4})`}>
            {rootTips.map((pts, i) => {
              const d = openCurve(pts.map(([x, y]) => [x * (w / 700), y * (h / 560)] as Pt));
              const g = c01(roots * 1.25 - (i > 2 ? 0.25 : 0));
              return (
                <g key={i}>
                  <path d={d} pathLength={1} fill="none" stroke={C.root} strokeWidth={rootW[i] + 4} strokeLinecap="round" strokeDasharray={`${g} 2`} />
                  <path d={d} pathLength={1} fill="none" stroke={ROOT_LIGHT} strokeWidth={rootW[i]} strokeLinecap="round" strokeDasharray={`${g} 2`} />
                </g>
              );
            })}
          </g>
        ) : null}
        {/* sensing region */}
        {region > 0 ? (
          <g opacity={region}>
            <ellipse cx={probeX} cy={sTop + h * 0.2} rx={(105 + Math.sin(f / 12) * 6) * k} ry={(135 + Math.sin(f / 12) * 6) * k} fill={`url(#${id}-reg)`} />
            <ellipse cx={probeX} cy={sTop + h * 0.2} rx={105 * k} ry={135 * k} fill="none" stroke={C.gold} strokeWidth={5} strokeDasharray="14 10" strokeDashoffset={-f * 0.8} />
          </g>
        ) : null}
        {/* surface shading */}
        <rect x={L - 30} y={top - 30} width={w + 60} height={40} fill={C.solid} opacity={0.18} />
      </g>
      {/* probe */}
      {probe > 0 ? (
        <g opacity={c01(probe * 2)} transform={`translate(0 ${(1 - probe) * -80}) translate(${probeX} ${top}) scale(${k}) translate(${-probeX} ${-top})`}>
          {[-22, 0, 22].map((dx) => (
            <rect key={dx} x={probeX + dx - 4} y={top - 20} width={8} height={(h * 0.32) / k} rx={4} fill="#9aa3ad" stroke="#6b7480" strokeWidth={2} />
          ))}
          <rect x={probeX - 44} y={top - 74} width={88} height={60} rx={12} fill={POT} />
          <circle cx={probeX + 26} cy={top - 44} r={6} fill={C.good} opacity={0.6 + 0.4 * Math.sin(f / 6)} />
          <path d={`M ${probeX} ${top - 74} C ${probeX} ${top - 130} ${probeX + 120} ${top - 110} ${probeX + 170} ${top - 160}`} stroke={POT} strokeWidth={8} fill="none" strokeLinecap="round" />
        </g>
      ) : null}
      {/* pot walls (cut-away: side walls + base with drain holes) */}
      <path d={`M ${L - wall / 2} ${top - 18} L ${cx - bw / 2 - wall / 2} ${bottom + wall / 2}`} stroke={POT} strokeWidth={wall} strokeLinecap="round" />
      <path d={`M ${R + wall / 2} ${top - 18} L ${cx + bw / 2 + wall / 2} ${bottom + wall / 2}`} stroke={POT} strokeWidth={wall} strokeLinecap="round" />
      {[[cx - bw / 2 - wall / 2, holes[0] - 14], [holes[0] + 14, holes[1] - 14], [holes[1] + 14, holes[2] - 14], [holes[2] + 14, cx + bw / 2 + wall / 2]].map(([a, b], i) => (
        <line key={i} x1={a} y1={bottom + wall / 2} x2={b} y2={bottom + wall / 2} stroke={POT} strokeWidth={wall} strokeLinecap="round" />
      ))}
      {tray
        ? [-0.36, 0.36].map((u) => <rect key={u} x={cx + u * bw - 26} y={bottom + wall / 2} width={52} height={62 - wall / 2} rx={6} fill={POT} />)
        : null}
      <rect x={L - wall - 14} y={top - 34} width={w + wall * 2 + 28} height={26} rx={13} fill={POT} />
      {/* emitter + stream */}
      {emitter ? (
        <g>
          <path d={`M ${cx - w * 0.22} ${top - 300} L ${cx - w * 0.22} ${top - 172}`} stroke={POT} strokeWidth={10} strokeLinecap="round" />
          <rect x={cx - w * 0.22 - 16} y={top - 180} width={32} height={34} rx={8} fill={C.forest} />
        </g>
      ) : null}
      {st.stream > 0.01 ? (
        <g opacity={c01(st.stream * 3)}>
          <path d={`M ${cx - w * 0.22} ${top - 150} L ${cx - w * 0.22} ${top + 6}`} stroke={C.water} strokeWidth={14 * st.stream} strokeLinecap="round" />
          <path d={`M ${cx - w * 0.22} ${top - 150} L ${cx - w * 0.22} ${top + 6}`} stroke={C.white} strokeWidth={4 * st.stream} strokeDasharray="10 16" strokeDashoffset={-f * 4} opacity={0.7} />
          <ellipse cx={cx - w * 0.22} cy={top + 8} rx={50 * st.stream + Math.sin(f / 4) * 4} ry={10 * st.stream} fill={C.water} opacity={0.8} />
        </g>
      ) : null}
      {plant > 0 ? <Plant x={cx} y={top - 8} h={130} f={f} p={plant} scale={1.15 * Math.sqrt(k)} /> : null}
    </g>
  );
};

// Particles positions for leader lines.
export function gapNear(gaps: Pt[], x: number, y: number): Pt {
  return gaps.reduce((m, g) => (Math.hypot(g[0] - x, g[1] - y) < Math.hypot(m[0] - x, m[1] - y) ? g : m), gaps[0]);
}

// Full-stage SVG canvas. The beat layer is a 1080-tall box shifted 92 px down, so size the SVG
// explicitly to the visible 1920 × 988 area instead of 100%.
export const SceneSvg: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <svg viewBox={`0 0 ${SW} ${SH}`} width={SW} height={SH} style={{ position: "absolute", left: 0, top: 0, fontFamily: FONT }}>
    {children}
  </svg>
);
