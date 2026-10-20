import React from "react";
import { interpolate, useCurrentFrame, random } from "remotion";
import { getLength, getPointAtLength } from "@remotion/paths";
import { C } from "../theme";
import { clamp, stepAt } from "../anim";
import type { SceneDef } from "./kit";
import { Svg, Pill, Sun, Moon, monoPath, wave, lerp, textW } from "./_measure-shared";

type Pt = [number, number];
type Threshold = { label: string; value: number; to?: number; axis?: "vwc" | "ec"; showValue?: boolean };
type P = {
  hours?: number;
  start?: number;
  nightFrom?: number;
  nightTo?: number;
  vwc: Pt[];
  vwc2?: Pt[];
  vwc2Label?: string;
  ec?: Pt[];
  ecPlan?: Pt[];
  plan?: Pt[];
  shots?: number[];
  held?: number[];
  thresholds?: Threshold[];
  highlight?: { h: number; text: string; line?: "vwc" | "ec" };
  gap?: [number, number];
  now?: number;
  vwcRange?: [number, number];
  ecRange?: [number, number];
  ecName?: string;
};

const X0 = 210;
const X1 = 1690;
const Y0 = 170;
const Y1 = 815;
const N_STEPS = 8;
const VWC2 = C.plant; // second VWC line: green, dotted
const VWC2_DASH = "2 14";

const fmtH = (h: number) => {
  const hh = ((Math.floor(h) % 24) + 24) % 24;
  const mm = Math.round((h - Math.floor(h)) * 60);
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
};

function niceRange(vals: number[], step: number, pad: number): [number, number] {
  const lo = Math.floor((Math.min(...vals) - pad) / step) * step;
  const hi = Math.ceil((Math.max(...vals) + pad) / step) * step;
  return [lo, hi];
}

function interpAt(pts: Pt[], h: number) {
  if (!pts.length) return 0;
  if (h <= pts[0][0]) return pts[0][1];
  for (let i = 0; i < pts.length - 1; i++) if (h <= pts[i + 1][0]) return lerp(pts[i][1], pts[i + 1][1], (h - pts[i][0]) / Math.max(pts[i + 1][0] - pts[i][0], 1e-6));
  return pts[pts.length - 1][1];
}

// Progressive line: draws path segments in order, returns the tip point too.
function drawSegs(segs: string[], p: number) {
  const lens = segs.map((d) => (d ? getLength(d) : 0));
  const total = lens.reduce((a, b) => a + b, 0) || 1;
  let left = p * total;
  let tip: { x: number; y: number } | null = null;
  const parts = segs.map((d, i) => {
    const len = lens[i];
    const drawn = Math.max(0, Math.min(len, left));
    left -= len;
    if (drawn > 0) tip = getPointAtLength(d, drawn);
    return { d, len, drawn };
  });
  return { parts, tip: tip as { x: number; y: number } | null };
}

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const hours = props.hours ?? 24;
  const start = props.start ?? 0;
  const norm = (h: number) => (h < start ? h + 24 : h);
  const xOf = (h: number) => X0 + ((norm(h) - start) / hours) * (X1 - X0);
  const S = (i: number) => stepAt(steps, i, duration, N_STEPS);

  const vwcPts = props.vwc.map(([h, v]) => [norm(h), v] as Pt).sort((a, b) => a[0] - b[0]);
  const vwc2Pts = (props.vwc2 ?? []).map(([h, v]) => [norm(h), v] as Pt).sort((a, b) => a[0] - b[0]);
  const ecPts = (props.ec ?? []).map(([h, v]) => [norm(h), v] as Pt).sort((a, b) => a[0] - b[0]);
  const ecPlanPts = (props.ecPlan ?? []).map(([h, v]) => [norm(h), v] as Pt).sort((a, b) => a[0] - b[0]);
  const planPts = (props.plan ?? []).map(([h, v]) => [norm(h), v] as Pt).sort((a, b) => a[0] - b[0]);
  const ths = props.thresholds ?? [];

  const vVals = [...vwcPts, ...vwc2Pts, ...planPts].map((p) => p[1]).concat(ths.filter((t) => t.axis !== "ec").flatMap((t) => [t.value, t.to ?? t.value]));
  const [vLo, vHi] = props.vwcRange ?? niceRange(vVals, 10, 2);
  const eVals = [...ecPts, ...ecPlanPts].map((p) => p[1]).concat(ths.filter((t) => t.axis === "ec").flatMap((t) => [t.value, t.to ?? t.value]));
  const [eLo, eHi] = props.ecRange ?? (eVals.length ? niceRange(eVals, 1, 0.3) : [0, 4]);
  const yV = (v: number) => Y1 - ((v - vLo) / (vHi - vLo)) * (Y1 - Y0);
  const yE = (v: number) => Y1 - ((v - eLo) / (eHi - eLo)) * (Y1 - Y0);

  // Reveal timings.
  const axesP = interpolate(f, [S(0), S(0) + 20], [0, 1], clamp);
  const vwcP = interpolate(f, [S(1), S(1) + 55], [0, 1], clamp);
  const ecP = interpolate(f, [S(2), S(2) + 45], [0, 1], clamp);
  const planP = interpolate(f, [S(4), S(4) + 40], [0, 1], clamp);
  const thP = interpolate(f, [S(5), S(5) + 16], [0, 1], clamp);
  const moveP = interpolate(f, [S(6), S(6) + 36], [0, 1], { ...clamp, easing: (t) => t * t * (3 - 2 * t) });
  const hiP = interpolate(f, [S(7), S(7) + 18], [0, 1], clamp);

  // VWC split by the data gap.
  const gap = props.gap ? ([norm(props.gap[0]), norm(props.gap[1])] as Pt) : null;
  const splitGap = (pts: Pt[]) => {
    const out: Pt[][] = [[]];
    pts.forEach((p) => {
      if (gap && p[0] > gap[0] && p[0] < gap[1]) return;
      const cur = out[out.length - 1];
      if (gap && cur.length && cur[cur.length - 1][0] <= gap[0] && p[0] >= gap[1]) out.push([p]);
      else cur.push(p);
    });
    return out;
  };
  const vSegs = splitGap(vwcPts);
  const v2Paths = splitGap(vwc2Pts).filter((s) => s.length).map((s) => monoPath(s.map(([h, v]) => [xOf(h), yV(v)])));
  const v2Draw = drawSegs(v2Paths, vwcP);
  const vPaths = vSegs.filter((s) => s.length).map((s) => monoPath(s.map(([h, v]) => [xOf(h), yV(v)])));
  const vDraw = drawSegs(vPaths, vwcP);
  const ePath = ecPts.length ? monoPath(ecPts.map(([h, v]) => [xOf(h), yE(v)])) : "";
  const eDraw = drawSegs(ePath ? [ePath] : [], ecP);
  const epPath = ecPlanPts.length ? monoPath(ecPlanPts.map(([h, v]) => [xOf(h), yE(v)])) : "";
  const pPath = planPts.length ? monoPath(planPts.map(([h, v]) => [xOf(h), yV(v)])) : "";
  const vTipX = vDraw.tip ? vDraw.tip.x : X0;

  // Night bands (wrap past midnight).
  const nightBands: [number, number][] = [];
  if (props.nightFrom != null && props.nightTo != null) {
    const a = norm(props.nightFrom);
    let b = norm(props.nightTo);
    if (b <= a) b += 24;
    for (const off of [-24, 0, 24]) {
      const lo = Math.max(a + off, start);
      const hi = Math.min(b + off, start + hours);
      if (hi > lo) nightBands.push([lo, hi]);
    }
  }
  const xH = (hAbs: number) => X0 + ((hAbs - start) / hours) * (X1 - X0);

  // Ticks.
  const tStep = hours >= 12 ? 3 : 1;
  const tTicks: number[] = [];
  for (let h = Math.ceil(start / tStep) * tStep; h <= start + hours + 1e-6; h += tStep) tTicks.push(h);
  const vStep = vHi - vLo > 40 ? 20 : vHi - vLo > 30 ? 10 : 5;
  const vTicks: number[] = [];
  for (let v = vLo; v <= vHi + 1e-6; v += vStep) vTicks.push(v);
  const eStep = eHi - eLo > 3 ? 1 : 0.5;
  const eTicks: number[] = [];
  for (let v = eLo; v <= eHi + 1e-6; v += eStep) eTicks.push(Math.round(v * 10) / 10);

  // Legend entries appear as each layer arrives.
  const legend = [
    { key: "vwc", text: "VWC · measured", show: vwcP, draw: <line x1={0} y1={0} x2={48} y2={0} stroke={C.water} strokeWidth={7} strokeLinecap="round" /> },
    ...(vwc2Pts.length ? [{ key: "vwc2", text: props.vwc2Label ?? "VWC · second", show: vwcP, draw: <line x1={0} y1={0} x2={48} y2={0} stroke={VWC2} strokeWidth={7} strokeDasharray={VWC2_DASH} strokeLinecap="round" /> }] : []),
    ...(planPts.length ? [{ key: "plan", text: "Plan", show: planP, draw: <line x1={0} y1={0} x2={48} y2={0} stroke={C.water} strokeWidth={5} strokeDasharray="10 8" /> }] : []),
    ...(ecPlanPts.length ? [{ key: "ecplan", text: "EC plan", show: planP, draw: <line x1={0} y1={0} x2={48} y2={0} stroke={C.ec} strokeWidth={5} strokeDasharray="10 8" /> }] : []),
    ...(ecPts.length ? [{ key: "ec", text: props.ecName ?? "EC", show: ecP, draw: <line x1={0} y1={0} x2={48} y2={0} stroke={C.ec} strokeWidth={7} strokeLinecap="round" /> }] : []),
    ...(props.shots?.length ? [{ key: "shot", text: "Shot", show: interpolate(f, [S(3), S(3) + 12], [0, 1], clamp), draw: <circle cx={24} cy={0} r={11} fill={C.water} stroke={C.white} strokeWidth={3} /> }] : []),
  ];
  const legW = legend.map((l) => 64 + textW(l.text, 30) + 44);
  let lx = (X0 + X1) / 2 - legW.reduce((a, b) => a + b, 0) / 2;

  const sunX = nightBands.length ? null : (X0 + X1) / 2;
  const dayStart = (() => {
    // Centre of the widest non-night stretch, for the sun icon.
    const pts = [start, ...nightBands.flat(), start + hours];
    let best: [number, number] = [start, start];
    for (let i = 0; i < pts.length - 1; i += 2) if (pts[i + 1] - pts[i] > best[1] - best[0]) best = [pts[i], pts[i + 1]];
    return best;
  })()[0];
  // Width of that day stretch in px; too narrow (graph starts/ends near lights-off) → drop its label so it can't collide with the moon's.
  const dayW = (() => {
    const pts = [start, ...nightBands.flat(), start + hours];
    let w = 0;
    for (let i = 0; i < pts.length - 1; i += 2) w = Math.max(w, xH(pts[i + 1]) - xH(pts[i]));
    return w;
  })();
  const sunLabel = !nightBands.length || dayW >= 270;

  const hl = props.highlight;
  const labelFade = hl ? 1 - hiP : 1;
  const hlOnEc = hl?.line === "ec";
  const hlVal = hl ? interpAt(hlOnEc ? ecPts : vwcPts, norm(hl.h)) : 0;
  const hlX = hl ? xOf(hl.h) : 0;
  const hlY = hl ? (hlOnEc ? yE(hlVal) : yV(hlVal)) : 0;

  return (
    <Svg>
      <defs>
        <linearGradient id="dg-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={C.water} stopOpacity={0.28} />
          <stop offset="1" stopColor={C.water} stopOpacity={0.02} />
        </linearGradient>
        <linearGradient id="dg-night" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={C.night} stopOpacity={0.24} />
          <stop offset="1" stopColor={C.night} stopOpacity={0.08} />
        </linearGradient>
        <clipPath id="dg-vclip">
          <rect x={X0} y={Y0 - 40} width={Math.max(0, vTipX - X0)} height={Y1 - Y0 + 40} />
        </clipPath>
        <clipPath id="dg-v2clip">
          <rect x={X0 - 20} y={0} width={Math.max(0, (v2Draw.tip ? v2Draw.tip.x : X0) - X0 + 20 + (vwcP >= 1 ? 40 : 0))} height={Y1 + 20} />
        </clipPath>
        <clipPath id="dg-pclip">
          <rect x={X0} y={0} width={(X1 - X0) * planP} height={Y1 + 20} />
        </clipPath>
        <pattern id="dg-hatch" width="18" height="18" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="18" stroke="#a3ada5" strokeWidth="6" />
        </pattern>
      </defs>

      {/* Plot card */}
      <g opacity={axesP}>
        <rect x={X0 - 150} y={Y0 - 70} width={X1 - X0 + 300} height={Y1 - Y0 + 160} rx={28} fill={C.white} stroke={C.line} strokeWidth={2} />
        {nightBands.map(([a, b], i) => (
          <g key={i}>
            <rect x={xH(a)} y={Y0} width={xH(b) - xH(a)} height={Y1 - Y0} fill="url(#dg-night)" />
            {Array.from({ length: Math.round((xH(b) - xH(a)) / 90) }, (_, k) => (
              <circle key={k} cx={xH(a) + 30 + random(`sx${i}${k}`) * (xH(b) - xH(a) - 60)} cy={Y0 + 30 + random(`sy${i}${k}`) * 110} r={3} fill={C.night} opacity={0.25 + 0.25 * wave(f, 50 + 30 * random(`sp${i}${k}`), k)} />
            ))}
          </g>
        ))}
        {/* Grid + axes */}
        {vTicks.map((v) => (
          <g key={`v${v}`}>
            <line x1={X0} x2={X1} y1={yV(v)} y2={yV(v)} stroke={C.line} strokeWidth={2} opacity={0.7} />
            <text x={X0 - 18} y={yV(v) + 11} textAnchor="end" fontSize={32} fontWeight={600} fill={C.water}>{v}%</text>
          </g>
        ))}
        {ecPts.length || ecPlanPts.length || ths.some((t) => t.axis === "ec")
          ? eTicks.map((v) => (
              <text key={`e${v}`} x={X1 + 18} y={yE(v) + 11} fontSize={32} fontWeight={600} fill={C.ec} opacity={ecP > 0 || (ecPlanPts.length && planP > 0) ? 1 : 0}>{v.toFixed(eStep < 1 ? 1 : 0)}</text>
            ))
          : null}
        <line x1={X0} x2={X1} y1={Y1} y2={Y1} stroke={C.ink} strokeWidth={3} />
        <line x1={X0} x2={X0} y1={Y0} y2={Y1} stroke={C.water} strokeWidth={4} />
        {ecPts.length || ecPlanPts.length ? <line x1={X1} x2={X1} y1={Y0} y2={Y1} stroke={C.ec} strokeWidth={4} opacity={ecP > 0 || planP > 0 ? 1 : 0.25} /> : null}
        {tTicks.map((h) => (
          <g key={`t${h}`}>
            <line x1={xH(h)} x2={xH(h)} y1={Y1} y2={Y1 + 12} stroke={C.ink} strokeWidth={3} />
            <text x={xH(h)} y={Y1 + 50} textAnchor="middle" fontSize={30} fontWeight={600} fill={C.muted}>{fmtH(h)}</text>
          </g>
        ))}
        <text x={X0 - 18} y={Y0 - 26} textAnchor="end" fontSize={30} fontWeight={800} fill={C.water}>VWC %</text>
        {ecPts.length || ecPlanPts.length ? <text x={X1 + 18} y={Y0 - 26} fontSize={30} fontWeight={800} fill={C.ec} opacity={ecP > 0 || planP > 0 ? 1 : 0.3}>mS/cm</text> : null}
      </g>

      {/* Legend */}
      <g>
        {legend.map((l, i) => {
          const x = lx;
          lx += legW[i];
          return (
            <g key={l.key} transform={`translate(${x} ${44 + (1 - l.show) * 16})`} opacity={l.show}>
              {l.draw}
              <text x={64} y={11} fontSize={30} fontWeight={700} fill={C.ink}>{l.text}</text>
            </g>
          );
        })}
      </g>

      {/* Missing data band */}
      {gap ? (
        <g opacity={interpolate(f, [S(1) + 30, S(1) + 50], [0, 1], clamp)}>
          <rect x={xH(gap[0])} y={Y0} width={xH(gap[1]) - xH(gap[0])} height={Y1 - Y0} fill={C.white} opacity={0.75} />
          <rect x={xH(gap[0])} y={Y0} width={xH(gap[1]) - xH(gap[0])} height={Y1 - Y0} fill="url(#dg-hatch)" />
          {[gap[0], gap[1]].map((g) => <line key={g} x1={xH(g)} x2={xH(g)} y1={Y0} y2={Y1} stroke={C.muted} strokeWidth={3} strokeDasharray="8 8" />)}
          <Pill x={(xH(gap[0]) + xH(gap[1])) / 2} y={Y1 - 40} text="no data" size={30} color={C.error} border={C.error} />
        </g>
      ) : null}

      {/* Day / night icons */}
      <g opacity={axesP}>
        {nightBands.map(([a, b], i) =>
          xH(b) - xH(a) > 260 ? (
            <g key={i}>
              <Moon x={xH(a) + 56} y={Y0 + 50} r={28} f={f} />
              <text x={xH(a) + 100} y={Y0 + 61} fontSize={30} fontWeight={700} fill={C.night} opacity={0.8 * labelFade}>lights off</text>
            </g>
          ) : null,
        )}
        {nightBands.length && dayW < 90 ? null : <Sun x={sunX ?? xH(dayStart) + Math.min(56, dayW / 2)} y={Y0 + 52} r={22} f={f} />}
        {sunLabel ? <text x={(sunX ?? xH(dayStart) + 56) + 50} y={Y0 + 63} fontSize={30} fontWeight={700} fill={C.gold} opacity={labelFade}>lights on</text> : null}
      </g>

      {/* EC plan (dashed) */}
      {epPath ? <path d={epPath} clipPath="url(#dg-pclip)" fill="none" stroke={C.ec} strokeWidth={5} strokeDasharray="14 12" strokeDashoffset={-f * 0.6} opacity={0.75} /> : null}

      {/* Plan (dashed reference) */}
      {pPath ? <path d={pPath} clipPath="url(#dg-pclip)" fill="none" stroke={C.water} strokeWidth={5} strokeDasharray="14 12" strokeDashoffset={-f * 0.6} opacity={0.75} /> : null}

      {/* VWC measured */}
      {vSegs.filter((s) => s.length).map((s, i) => (
        <path key={`a${i}`} clipPath="url(#dg-vclip)" d={`${monoPath(s.map(([h, v]) => [xOf(h), yV(v)]))} L ${xOf(s[s.length - 1][0])} ${Y1} L ${xOf(s[0][0])} ${Y1} Z`} fill="url(#dg-area)" />
      ))}
      {vDraw.parts.map((p, i) => p.drawn <= 0 ? null : (
        <path key={`v${i}`} d={p.d} fill="none" stroke={C.water} strokeWidth={7} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={`${p.drawn} ${p.len + 10}`} />
      ))}
      {vDraw.tip && vwcP > 0 && vwcP < 1 ? <circle cx={vDraw.tip.x} cy={vDraw.tip.y} r={13 + 3 * wave(f, 12)} fill={C.water} stroke={C.white} strokeWidth={4} /> : null}

      {/* Second VWC line */}
      {v2Draw.parts.map((p, i) => p.drawn <= 0 ? null : (
        <path key={`v2${i}`} d={p.d} fill="none" stroke={VWC2} strokeWidth={7} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={VWC2_DASH} clipPath="url(#dg-v2clip)" />
      ))}

      {/* EC */}
      {eDraw.parts.map((p, i) => p.drawn <= 0 ? null : (
        <path key={`e${i}`} d={p.d} fill="none" stroke={C.ec} strokeWidth={6} strokeLinecap="round" strokeDasharray={`${p.drawn} ${p.len + 10}`} />
      ))}
      {eDraw.tip && ecP > 0 && ecP < 1 ? <circle cx={eDraw.tip.x} cy={eDraw.tip.y} r={11 + 3 * wave(f, 12)} fill={C.ec} stroke={C.white} strokeWidth={4} /> : null}

      {/* Shot markers */}
      {[...(props.shots ?? []).map((h) => ({ h, held: false })), ...(props.held ?? []).map((h) => ({ h, held: true }))]
        .sort((a, b) => norm(a.h) - norm(b.h))
        .map((s, i) => {
          const p = interpolate(f, [S(3) + i * 4, S(3) + i * 4 + 12], [0, 1], { ...clamp, easing: (t) => 1 - Math.pow(1 - t, 3) * Math.cos(t * 6) });
          const x = xOf(s.h);
          const yl = yV(interpAt(vwcPts, norm(s.h)));
          return (
            <g key={i} opacity={Math.min(1, p * 3)}>
              <line x1={x} x2={x} y1={Y1 - 22} y2={lerp(Y1 - 22, yl + 14, Math.min(1, p))} stroke={C.water} strokeWidth={2} strokeDasharray="4 6" opacity={0.6} />
              <circle cx={x} cy={Y1 - 22} r={Math.max(0, 12 * p)} fill={s.held ? C.white : C.water} stroke={s.held ? C.water : C.white} strokeWidth={s.held ? 4 : 3} />
            </g>
          );
        })}

      {/* Thresholds */}
      {(() => {
        // Lay out every threshold pill (and its "a → b" note), then push overlapping ones apart.
        const L = ths.map((t) => {
          const v = t.to != null ? lerp(t.value, t.to, moveP) : t.value;
          const yy = t.axis === "ec" ? yE(v) : yV(v);
          const y0 = t.axis === "ec" ? yE(t.value) : yV(t.value);
          const unit = t.axis === "ec" ? "" : "%";
          const shown = t.axis === "ec" ? v.toFixed(1) : String(Math.round(v));
          const showV = t.showValue ?? !(t.label.includes(shown) || t.label.includes(String(t.value)));
          const txt = showV ? `${t.label} · ${shown}${unit}` : t.label;
          return { v, yy, y0, unit, txt, pw: textW(txt, 30) + 36, mainY: yy - 32, noteY: yy + (yy < y0 ? 40 : -100) };
        });
        const boxes: { y: number; set: (y: number) => void }[] = [];
        L.forEach((l, i) => {
          boxes.push({ y: l.mainY, set: (y) => (l.mainY = y) });
          if (ths[i].to != null && moveP >= 1) boxes.push({ y: l.noteY, set: (y) => (l.noteY = y) });
        });
        boxes.sort((a, b) => a.y - b.y);
        for (let k = 1; k < boxes.length; k++) if (boxes[k].y < boxes[k - 1].y + 58) boxes[k].y = boxes[k - 1].y + 58;
        boxes.forEach((b) => b.set(b.y));
        return ths.map((t, i) => ({ t, i, ...L[i] }));
      })().map(({ t, i, yy, y0, unit, txt, pw, mainY, noteY }) => {
        return (
          <g key={i} opacity={thP}>
            {t.to != null && moveP > 0 ? (
              <g>
                <line x1={X0} x2={X1} y1={y0} y2={y0} stroke={C.error} strokeWidth={3} strokeDasharray="6 10" opacity={0.35} />
                <path d={`M ${X1 - pw - 60} ${y0} L ${X1 - pw - 60} ${yy + (yy < y0 ? 14 : -14)}`} stroke={C.error} strokeWidth={4} opacity={0.6} />
                <path d={`M ${X1 - pw - 72} ${yy + (yy < y0 ? 22 : -22)} L ${X1 - pw - 60} ${yy + (yy < y0 ? 6 : -6)} L ${X1 - pw - 48} ${yy + (yy < y0 ? 22 : -22)}`} fill="none" stroke={C.error} strokeWidth={4} opacity={0.6 * moveP} />
              </g>
            ) : null}
            <line x1={X0} x2={X0 + (X1 - X0) * thP} y1={yy} y2={yy} stroke={C.error} strokeWidth={4} strokeDasharray="18 10" strokeDashoffset={f * 0.8} />
            <Pill x={X1 - pw / 2 - 14} y={mainY} text={txt} size={30} color={C.white} bg={C.error} />
            {t.to != null && moveP >= 1 ? <Pill x={X1 - pw / 2 - 14} y={noteY} text={`${t.value}${unit} → ${t.to}${unit}`} size={28} color={C.error} border={C.error} opacity={interpolate(f, [S(6) + 36, S(6) + 50], [0, 1], clamp)} /> : null}
          </g>
        );
      })}

      {/* Now marker */}
      {props.now != null ? (
        <g opacity={interpolate(f, [S(1) + 40, S(1) + 56], [0, 1], clamp)}>
          <line x1={xOf(props.now)} x2={xOf(props.now)} y1={Y0} y2={Y1} stroke={C.forest} strokeWidth={4} />
          <Pill x={xOf(props.now)} y={Y0 - 4} text="now" size={28} color={C.white} bg={C.forest} scale={1 + 0.04 * wave(f, 30)} />
        </g>
      ) : null}

      {/* Highlight point */}
      {hl ? (
        <g opacity={hiP}>
          <line x1={hlOnEc ? X1 : X0} x2={hlX} y1={hlY} y2={hlY} stroke={C.forest} strokeWidth={3} strokeDasharray="8 8" />
          <line x1={hlX} x2={hlX} y1={hlY} y2={Y1} stroke={C.forest} strokeWidth={3} strokeDasharray="8 8" />
          <circle cx={hlX} cy={hlY} r={22 + 8 * (0.5 + 0.5 * wave(f, 36))} fill="none" stroke={hlOnEc ? C.ec : C.water} strokeWidth={3} opacity={0.5} />
          <circle cx={hlX} cy={hlY} r={13} fill={C.white} stroke={hlOnEc ? C.ec : C.water} strokeWidth={6} />
          {(() => {
            const w = textW(hl.text, 36) + 56;
            const bx = Math.min(Math.max(hlX, X0 + w / 2), X1 - w / 2);
            const by = hlY - 100 + 6 * wave(f, 60) - (1 - hiP) * 20;
            return (
              <g>
                <path d={`M ${hlX - 14} ${by + 30} L ${hlX} ${hlY - 26} L ${hlX + 14} ${by + 30} Z`} fill={C.forest} />
                <rect x={bx - w / 2} y={by - 34} width={w} height={68} rx={18} fill={C.forest} />
                <text x={bx} y={by + 12} textAnchor="middle" fontSize={36} fontWeight={700} fill={C.white}>{hl.text}</text>
              </g>
            );
          })()}
        </g>
      ) : null}
    </Svg>
  );
};

export default {
  Component,
  doc: "The main root-zone chart. Time axis left→right, shaded night band with moon (day gets a sun; when the graph starts/ends near lights-off the narrow day stretch drops its label so labels never overlap), blue VWC line (% on left axis) drawn progressively, optional orange EC line (mS/cm on right axis), shot event markers (filled dots; `held` = rings), dashed planning reference vs solid measured line, horizontal threshold lines that can slide from value to `to` while the measured line stays put, optional highlight bubble with read-across guides, optional 'now' marker and hatched missing-data gap (white-backed grey hatching + dashed edges, visible over night shading). props: {hours?:24, start?:0 (clock hour at the left edge; hours below start wrap to next day, e.g. 30 = 06:00 tomorrow), nightFrom?, nightTo?, vwc:[[h,v]...], vwc2?:[[h,v]...] (second VWC line, green dotted, drawn with the first), vwc2Label?:'VWC · second' (its legend text), ec?:[[h,v]...], ecName?:'Bulk EC', ecPlan?:[[h,v]...] (dashed orange EC plan line on the EC axis, legend 'EC plan', drawn with the plan step), plan?:[[h,v]...], shots?:[h...], held?:[h...], thresholds?:[{label, value, to?, axis?:'vwc'|'ec', showValue?:boolean (append ' · value%' to the pill; default true unless the label already contains the number)}] (pills that would overlap are stacked apart automatically), highlight?:{h, text, line?:'vwc'|'ec'}, gap?:[h1,h2], now?:h, vwcRange?:[lo,hi], ecRange?:[lo,hi]}. steps: [axes, VWC line, EC line, shot markers, plan line, threshold appears, threshold moves to `to`, highlight].",
  example: {
    props: {
      hours: 24,
      start: 6,
      nightFrom: 18,
      nightTo: 6,
      vwc: [[6, 46], [7, 44.5], [7.1, 49], [7.75, 48], [7.85, 52], [8.5, 51], [8.6, 55], [9.25, 54], [9.35, 58], [10, 57], [10.1, 60], [12, 57.5], [12.1, 60], [14, 57.5], [14.1, 60], [16, 57], [16.1, 59.5], [18, 57], [20, 55], [21, 54], [23.5, 51.5], [26, 49], [28, 47.5], [30, 46.5]],
      ec: [[6, 3.0], [8, 2.7], [10, 2.5], [14, 2.6], [18, 2.8], [21, 2.9], [24, 3.0], [30, 3.1]],
      ecName: "Bulk EC",
      plan: [[6, 45], [10, 60], [18, 57], [30, 45]],
      shots: [7, 7.75, 8.5, 9.25, 10, 12, 14, 16],
      thresholds: [{ label: "Night emergency", value: 35, to: 39 }],
      highlight: { h: 12.1, text: "60% at 12:06" },
      gap: [21.5, 23],
    },
    steps: [0, 20, 60, 90, 112, 140, 158, 200],
  },
} satisfies SceneDef<P>;
