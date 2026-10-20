import React from "react";
import { interpolate, Easing, useCurrentFrame } from "remotion";
import { C, FONT, SERIF } from "../theme";

// Shared flat-illustration pieces for the watering scenes (PhaseDay, DripperFlow,
// BlendSlider, PlantBalance, CatchTest). Every animation is a pure function of the frame.

export const SW = 1920;
export const SH = 988;

const cl = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
export const ease = (f: number, a: number, b: number) => interpolate(f, [a, Math.max(a + 1, b)], [0, 1], { ...cl, easing: Easing.inOut(Easing.cubic) });
export const lin = (f: number, a: number, b: number) => interpolate(f, [a, Math.max(a + 1, b)], [0, 1], cl);
export const trim = (n: number, dp = 2) => String(+n.toFixed(dp));

export const Svg: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <svg width={SW} height={SH} viewBox={`0 0 ${SW} ${SH}`} style={{ position: "absolute", inset: 0, fontFamily: FONT }}>
    {children}
  </svg>
);

type TP = { x: number; y: number; size?: number; weight?: number; fill?: string; anchor?: "start" | "middle" | "end"; serif?: boolean; opacity?: number; children: React.ReactNode };
export const T: React.FC<TP> = ({ x, y, size = 32, weight = 500, fill = C.ink, anchor = "start", serif, opacity = 1, children }) => (
  <text x={x} y={y} fontSize={size} fontWeight={weight} fill={fill} textAnchor={anchor} opacity={opacity} fontFamily={serif ? SERIF : FONT}>
    {children}
  </text>
);

// Water drop with its tip at (0, -1.5r) and round belly centred on (0, 0.35r).
export const dropPath = (r: number) =>
  `M0 ${-1.5 * r} C ${0.55 * r} ${-0.7 * r} ${r} ${-0.2 * r} ${r} ${0.35 * r} A ${r} ${r} 0 0 1 ${-r} ${0.35 * r} C ${-r} ${-0.2 * r} ${-0.55 * r} ${-0.7 * r} 0 ${-1.5 * r} Z`;

export const Drop: React.FC<{ x: number; y: number; r?: number; fill?: string; opacity?: number }> = ({ x, y, r = 14, fill = C.water, opacity = 1 }) => (
  <g transform={`translate(${x},${y})`} opacity={opacity}>
    <path d={dropPath(r)} fill={fill} />
    <ellipse cx={-0.35 * r} cy={0.15 * r} rx={0.18 * r} ry={0.32 * r} fill="#fff" opacity={0.55} />
  </g>
);

// Repeating drips from (x, y0) falling to y1, spawned every `period` frames while start <= spawn < end.
export const Drips: React.FC<{ x: number; y0: number; y1: number; period?: number; offset?: number; start?: number; end?: number; r?: number; fall?: number }> = ({
  x, y0, y1, period = 18, offset = 0, start = 0, end = 1e9, r = 9, fall = 14,
}) => {
  const f = useCurrentFrame();
  const out: React.ReactNode[] = [];
  const nHi = Math.floor((f + offset) / period);
  for (let n = nHi; n >= nHi - Math.ceil((fall + 12) / period) - 1; n--) {
    const s = n * period - offset;
    if (s < start || s >= end) continue;
    const t = (f - s) / fall;
    if (t >= 0 && t < 1) out.push(<Drop key={`d${n}`} x={x} y={y0 + (y1 - y0) * t * t} r={r} />);
    const ts = (f - s - fall) / 12;
    if (ts >= 0 && ts < 1) out.push(<ellipse key={`s${n}`} cx={x} cy={y1} rx={6 + 22 * ts} ry={2 + 6 * ts} fill="none" stroke={C.water} strokeWidth={3} opacity={1 - ts} />);
  }
  return <g>{out}</g>;
};

// Stopwatch: hand sweeps one turn per 60 s; the shaded wedge shows elapsed time.
export const Stopwatch: React.FC<{ x: number; y: number; r?: number; elapsed: number; running?: boolean }> = ({ x, y, r = 110, elapsed, running }) => {
  const f = useCurrentFrame();
  const a = ((elapsed % 60) / 60) * Math.PI * 2;
  const wedge = elapsed >= 60 ? null : (() => {
    const ex = Math.sin(a) * (r - 14), ey = -Math.cos(a) * (r - 14);
    return `M0 0 L0 ${-(r - 14)} A ${r - 14} ${r - 14} 0 ${a > Math.PI ? 1 : 0} 1 ${ex} ${ey} Z`;
  })();
  const blink = running ? 1 : 0.65 + 0.35 * Math.cos(f / 6);
  return (
    <g transform={`translate(${x},${y})`}>
      <rect x={-18} y={-r - 34} width={36} height={26} rx={6} fill={C.forest} />
      <rect x={-34} y={-r - 44} width={68} height={16} rx={8} fill={C.forest} />
      <circle r={r + 10} fill={C.forest} />
      <circle r={r} fill={C.white} />
      {wedge ? <path d={wedge} fill={C.waterLight} /> : <circle r={r - 14} fill={C.waterLight} />}
      {Array.from({ length: 12 }, (_, i) => {
        const t = (i / 12) * Math.PI * 2;
        return <line key={i} x1={Math.sin(t) * (r - 6)} y1={-Math.cos(t) * (r - 6)} x2={Math.sin(t) * (r - (i % 3 ? 16 : 26))} y2={-Math.cos(t) * (r - (i % 3 ? 16 : 26))} stroke={C.forest} strokeWidth={i % 3 ? 3 : 6} strokeLinecap="round" />;
      })}
      <line x1={0} y1={0} x2={Math.sin(a) * (r - 22)} y2={-Math.cos(a) * (r - 22)} stroke={C.error} strokeWidth={7} strokeLinecap="round" />
      <circle r={10} fill={C.error} />
      <rect x={-r * 0.46} y={r * 0.2} width={r * 0.92} height={r * 0.44} rx={r * 0.22} fill={C.white} stroke={C.forest} strokeWidth={3} />
      <text y={r * 0.54} textAnchor="middle" fontSize={r * 0.36} fontWeight={700} fill={C.forest} opacity={blink} fontFamily={FONT}>
        {Math.floor(elapsed)} s
      </text>
    </g>
  );
};

// Cannabis-style fan leaf; petiole base at origin, pointing up (rotate with `angle`).
export const FanLeaf: React.FC<{ x: number; y: number; angle: number; size: number; color?: string }> = ({ x, y, angle, size, color = C.plant }) => {
  const pet = size * 0.28;
  const fingers = [-78, -40, 0, 40, 78];
  const lens = [0.48, 0.78, 1, 0.78, 0.48];
  return (
    <g transform={`translate(${x},${y}) rotate(${angle})`}>
      <line x1={0} y1={0} x2={0} y2={-pet} stroke={color} strokeWidth={size * 0.05} strokeLinecap="round" />
      {fingers.map((fa, i) => {
        const L = size * lens[i], w = L * 0.16;
        return (
          <g key={i} transform={`translate(0,${-pet}) rotate(${fa})`}>
            <path d={`M0 0 Q ${w} ${-L * 0.42} 0 ${-L} Q ${-w} ${-L * 0.42} 0 0 Z`} fill={color} />
            <line x1={0} y1={-L * 0.08} x2={0} y2={-L * 0.85} stroke="#fff" strokeOpacity={0.35} strokeWidth={Math.max(1.5, size * 0.012)} />
          </g>
        );
      })}
    </g>
  );
};

// Flower cluster (bud) with pistils; centred at (x, y).
export const Bud: React.FC<{ x: number; y: number; size: number; scale?: number }> = ({ x, y, size, scale = 1 }) => {
  const s = size * scale;
  const blobs: [number, number, number][] = [[0, -0.55, 0.42], [-0.32, -0.18, 0.4], [0.32, -0.18, 0.4], [0, 0.12, 0.46], [-0.22, 0.42, 0.34], [0.22, 0.42, 0.34], [0, -0.95, 0.3]];
  return (
    <g transform={`translate(${x},${y})`}>
      {blobs.map(([bx, by, br], i) => <circle key={i} cx={bx * s} cy={by * s} r={br * s} fill={i % 2 ? "#cdb877" : C.gold} />)}
      {blobs.map(([bx, by], i) => (
        <path key={`p${i}`} d={`M${bx * s} ${by * s} q ${s * 0.12} ${-s * 0.18} ${s * 0.26} ${-s * 0.14}`} stroke={C.ec} strokeWidth={Math.max(2, s * 0.05)} fill="none" strokeLinecap="round" />
      ))}
      <circle cx={-0.12 * s} cy={-0.62 * s} r={0.1 * s} fill="#fff" opacity={0.4} />
    </g>
  );
};

// A potted plant's top growth, base at (x, y) (soil level). kind "flower" adds buds.
export const Plant: React.FC<{ x: number; y: number; s?: number; kind?: "veg" | "flower"; seed?: number; leafScale?: number; budScale?: number; leafColor?: string; leafFilter?: string; budFilter?: string }> = ({
  x, y, s = 1, kind = "veg", seed = 0, leafScale = 1, budScale = 1, leafColor = C.plant, leafFilter, budFilter,
}) => {
  const f = useCurrentFrame();
  const sway = Math.sin(f / 38 + seed * 1.7) * 2.2;
  const H = 250 * s;
  const ls = s * leafScale;
  const nodes: [number, number, number][] = [[0.3, -58, 1.0], [0.3, 58, 1.0], [0.55, -50, 0.86], [0.55, 50, 0.86], [0.78, -40, 0.68], [0.78, 40, 0.68]];
  return (
    <g transform={`translate(${x},${y}) rotate(${sway})`}>
      <g filter={leafFilter}>
      <path d={`M0 0 C ${6 * s} ${-H * 0.35} ${-6 * s} ${-H * 0.7} 0 ${-H}`} stroke="#3f7348" strokeWidth={9 * s} fill="none" strokeLinecap="round" />
      {nodes.map(([h, a, k], i) => (
        <FanLeaf key={i} x={0} y={-H * h} angle={a + Math.sin(f / 30 + i + seed) * 3} size={95 * ls * k} color={i % 2 ? leafColor : shade(leafColor)} />
      ))}
      </g>
      {kind === "flower" ? (
        <g filter={budFilter}>
          <Bud x={-48 * s} y={-H * 0.6} size={26 * s} scale={budScale} />
          <Bud x={48 * s} y={-H * 0.6} size={26 * s} scale={budScale} />
          <Bud x={0} y={-H - 18 * s} size={40 * s} scale={budScale} />
        </g>
      ) : (
        <FanLeaf x={0} y={-H} angle={Math.sin(f / 26 + seed) * 4} size={70 * ls} color={leafColor} />
      )}
    </g>
  );
};

const shade = (c: string) => (c === C.plant ? "#5e9a69" : c);

// Plant pot: top-centre at (x, y).
export const Pot: React.FC<{ x: number; y: number; w?: number; h?: number }> = ({ x, y, w = 200, h = 150 }) => (
  <g transform={`translate(${x},${y})`}>
    <ellipse cx={0} cy={4} rx={w / 2 - 6} ry={14} fill={C.solid} />
    <path d={`M ${-w / 2} 10 L ${w / 2} 10 L ${w * 0.4} ${h} L ${-w * 0.4} ${h} Z`} fill="#33544a" />
    <rect x={-w / 2 - 8} y={0} width={w + 16} height={26} rx={8} fill={C.forest} />
  </g>
);

// Clear catch cup; bottom-centre at (x, y). level 0..1.
export const Cup: React.FC<{ x: number; y: number; w?: number; h?: number; level: number; id: string; tint?: string }> = ({ x, y, w = 80, h = 120, level, id, tint = C.water }) => {
  const f = useCurrentFrame();
  const tw = w, bw = w * 0.78;
  const d = `M ${-tw / 2} ${-h} L ${tw / 2} ${-h} L ${bw / 2} 0 L ${-bw / 2} 0 Z`;
  const wy = -h * Math.min(1, Math.max(0, level)) * 0.92;
  const wave = Math.sin(f / 5) * 2.5 * (level > 0.01 ? 1 : 0);
  return (
    <g transform={`translate(${x},${y})`}>
      <defs>
        <clipPath id={`cup-${id}`}><path d={d} /></clipPath>
      </defs>
      <path d={d} fill="#ffffff" opacity={0.8} />
      <g clipPath={`url(#cup-${id})`}>
        <path d={`M ${-tw} ${wy + wave} Q ${-tw / 4} ${wy - wave} 0 ${wy + wave} T ${tw} ${wy + wave} L ${tw} 4 L ${-tw} 4 Z`} fill={tint} opacity={0.75} />
      </g>
      {[0.25, 0.5, 0.75].map((g) => <line key={g} x1={-tw * 0.36} x2={-tw * 0.18} y1={-h * g} y2={-h * g} stroke={C.muted} strokeWidth={2} opacity={0.6} />)}
      <path d={d} fill="none" stroke={C.forest} strokeWidth={4} strokeLinejoin="round" />
    </g>
  );
};

export const Tick: React.FC<{ x: number; y: number; r?: number; p?: number; color?: string }> = ({ x, y, r = 26, p = 1, color = C.good }) => (
  <g transform={`translate(${x},${y}) scale(${p})`} opacity={Math.min(1, p * 1.5)}>
    <circle r={r} fill={color} />
    <path d={`M ${-r * 0.45} ${0} L ${-r * 0.1} ${r * 0.35} L ${r * 0.5} ${-r * 0.35}`} stroke="#fff" strokeWidth={r * 0.22} fill="none" strokeLinecap="round" strokeLinejoin="round" />
  </g>
);

// Eye looking in direction (lx, ly) (unit-ish), with a periodic blink.
export const Eye: React.FC<{ x: number; y: number; size?: number; lx?: number; ly?: number }> = ({ x, y, size = 50, lx = 0, ly = 0.4 }) => {
  const f = useCurrentFrame();
  const ph = f % 75;
  const open = ph < 66 ? 1 : Math.abs(ph - 70.5) / 4.5;
  const w = size, h = size * 0.62 * open;
  return (
    <g transform={`translate(${x},${y})`}>
      <path d={`M ${-w} 0 Q 0 ${-h * 1.6} ${w} 0 Q 0 ${h * 1.6} ${-w} 0 Z`} fill="#fff" stroke={C.forest} strokeWidth={5} />
      {open > 0.25 ? (
        <>
          <circle cx={lx * w * 0.35} cy={ly * h * 0.5} r={size * 0.36 * Math.min(1, open * 1.2)} fill={C.water} />
          <circle cx={lx * w * 0.35} cy={ly * h * 0.5} r={size * 0.17 * Math.min(1, open * 1.2)} fill={C.forest} />
          <circle cx={lx * w * 0.35 - size * 0.1} cy={ly * h * 0.5 - size * 0.1} r={size * 0.07} fill="#fff" />
        </>
      ) : null}
    </g>
  );
};

export const Sun: React.FC<{ x: number; y: number; r?: number }> = ({ x, y, r = 32 }) => {
  const f = useCurrentFrame();
  return (
    <g transform={`translate(${x},${y})`}>
      <g transform={`rotate(${f * 0.8})`}>
        {Array.from({ length: 10 }, (_, i) => (
          <line key={i} x1={0} y1={-r - 8} x2={0} y2={-r - 22 - 4 * Math.sin(f / 8 + i)} stroke={C.warn} strokeWidth={6} strokeLinecap="round" transform={`rotate(${i * 36})`} />
        ))}
      </g>
      <circle r={r} fill="#f2c14e" stroke={C.warn} strokeWidth={4} />
    </g>
  );
};

export const Moon: React.FC<{ x: number; y: number; r?: number }> = ({ x, y, r = 32 }) => {
  const f = useCurrentFrame();
  return (
    <g transform={`translate(${x},${y}) rotate(${-20 + Math.sin(f / 40) * 6})`}>
      <path d={`M 0 ${-r} A ${r} ${r} 0 1 0 0 ${r} A ${r * 0.72} ${r} 0 1 1 0 ${-r} Z`} fill="#f4ecc8" />
    </g>
  );
};

// Rounded chip drawn in SVG; width estimated from text length.
export const SvgChip: React.FC<{ x: number; y: number; text: string; color?: string; size?: number; fill?: string; textFill?: string; anchor?: "start" | "middle" | "end"; opacity?: number }> = ({
  x, y, text, color = C.forest, size = 32, fill = C.white, textFill, anchor = "middle", opacity = 1,
}) => {
  const w = text.length * size * 0.56 + size * 1.3;
  const h = size * 1.7;
  const left = anchor === "middle" ? x - w / 2 : anchor === "end" ? x - w : x;
  return (
    <g opacity={opacity}>
      <rect x={left} y={y - h / 2} width={w} height={h} rx={h / 2} fill={fill} stroke={color} strokeWidth={3.5} />
      <text x={left + w / 2} y={y + size * 0.35} textAnchor="middle" fontSize={size} fontWeight={700} fill={textFill || color} fontFamily={FONT}>{text}</text>
    </g>
  );
};
