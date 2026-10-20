import React from "react";
import { random, useCurrentFrame } from "remotion";
import { C } from "../theme";
import { stepAt } from "../anim";
import { type SceneDef } from "./kit";
import { Svg, T, Drop, Sun, Moon, SvgChip, ease, lin, trim } from "./_watering-shared";

type PhaseId = "P0" | "P1" | "P2" | "P3";
type P = { highlight?: PhaseId | "all"; lightsOn?: string; lightsOff?: string; showFloor?: boolean; showRescue?: boolean; only?: PhaseId };

const X0 = 150, X1 = 1780;
const WID = [0.17, 0.2, 0.25, 0.38]; // schematic widths: day phases stretched so labels fit
const CY0 = 200, CY1 = 560; // chart band
const V0 = 42, V1 = 66;
const vy = (v: number) => CY1 - ((v - V0) / (V1 - V0)) * (CY1 - CY0);
const RISE = 0.03;

type Phase = { id: PhaseId; name: string; job: string; color: string; dark?: boolean; v0: number; rate: number; shots: number[]; size: number };

// VWC within a phase at fraction u: steady drying plus a quick riser per shot.
const vAt = (ph: Phase, u: number) => ph.v0 - ph.rate * u + ph.shots.reduce((s, us) => s + ph.size * Math.min(1, Math.max(0, (u - us) / RISE)), 0);

function buildPhases(rescue: boolean): Phase[] {
  const p0: Phase = { id: "P0", name: "Morning wait", job: "no water yet", color: C.gold, v0: 52, rate: 4, shots: [], size: 0 };
  const p1: Phase = { id: "P1", name: "Refill", job: "shots step it up", color: C.water, v0: 48, rate: 0.8, shots: [0.1, 0.32, 0.54, 0.76], size: 3.6 };
  const p2v0 = vAt(p1, 1);
  const p2: Phase = { id: "P2", name: "Maintain", job: "shot at the threshold", color: C.plant, v0: p2v0, rate: 14, shots: [], size: 4 };
  for (let u = (p2v0 - 58) / p2.rate; u < 0.95; u += p2.size / p2.rate + RISE) p2.shots.push(u);
  const p3v0 = vAt(p2, 1);
  const p3: Phase = rescue
    ? { id: "P3", name: "Overnight dryback", job: "rescue shot only below the floor", color: C.night, dark: true, v0: p3v0, rate: (p3v0 - 47) / 0.8, shots: [0.8], size: 4 }
    : { id: "P3", name: "Overnight dryback", job: "lights off · no water", color: C.night, dark: true, v0: p3v0, rate: 9, shots: [], size: 0 };
  return [p0, p1, p2, p3];
}

const hours = (t: string) => { const [h, m] = t.split(":").map(Number); return (h || 0) + (m || 0) / 60; };

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const { highlight, lightsOn = "06:00", lightsOff = "18:00", showFloor = true, showRescue = false } = props;
  const phases = buildPhases(showRescue);
  // only: a single phase spans the whole chart; the others collapse to zero width and never appear.
  const oi = props.only ? phases.findIndex((p) => p.id === props.only) : -1;
  const xs: number[] = [X0];
  WID.forEach((w, i) => xs.push(oi >= 0 ? (i < oi ? X0 : X1) : xs[xs.length - 1] + w * (X1 - X0)));
  const xOff = xs[3];
  const dayH = ((hours(lightsOff) - hours(lightsOn)) % 24 + 24) % 24 || 24;

  const starts = oi >= 0
    ? phases.map((_, i) => (i === oi ? Math.max(10, stepAt(steps, 0, duration, 1)) : 1e9))
    : phases.map((_, i) => Math.max(i === 0 ? 10 : 0, stepAt(steps, i, duration, 4)));
  const lens = starts.map((s, i) => Math.min(48, Math.max(26, (starts[i + 1] ?? s + 60) - s - 6)));
  const prog = starts.map((s, i) => lin(f, s, s + lens[i]));
  const rev = starts.map((s) => ease(f, s - 4, s + 14));
  const latest = rev.reduce((k, r, i) => (r > 0 ? i : k), 0);
  const emph = (i: number) => (highlight === "all" ? true : highlight ? phases[i].id === highlight : i === latest);

  // Trace path through every revealed phase, up to the drawing head.
  let d = "";
  let head: [number, number] | null = null;
  phases.forEach((ph, i) => {
    if (prog[i] <= 0) return;
    const w = xs[i + 1] - xs[i];
    const n = Math.max(2, Math.round(160 * prog[i]));
    for (let k = 0; k <= n; k++) {
      const u = (k / n) * prog[i];
      const x = xs[i] + u * w, y = vy(vAt(ph, u));
      d += `${d ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)} `;
      head = [x, y];
    }
  });
  const area = head ? `${d} L ${(head as [number, number])[0]} ${CY1} L ${X0} ${CY1} Z` : "";

  const sunRise = ease(f, 0, 22);
  const moonPop = ease(f, starts[3] - 6, starts[3] + 12);

  return (
    <Svg>
      <defs>
        <clipPath id="pd-sky"><rect x={X0} y={30} width={X1 - X0} height={120} rx={20} /></clipPath>
        <linearGradient id="pd-day" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#fbefc4" /><stop offset="1" stopColor="#fff8e2" /></linearGradient>
      </defs>

      {/* Sky strip: daylight then night */}
      <g clipPath="url(#pd-sky)">
        <rect x={X0} y={30} width={xOff - X0} height={120} fill="url(#pd-day)" />
        <rect x={xOff} y={30} width={X1 - xOff} height={120} fill={C.night} />
        {Array.from({ length: 22 }, (_, i) => {
          const sx = xOff + 120 + random(`sx${i}`) * (X1 - xOff - 140), sy = random(`sy${i}`) < 0.5 ? 42 + random(`sz${i}`) * 16 : 134 + random(`sz${i}`) * 10;
          return <circle key={i} cx={sx} cy={sy} r={1.5 + random(`sr${i}`) * 2.5} fill="#fff" opacity={0.35 + 0.6 * Math.abs(Math.sin(f / 14 + i * 1.3))} />;
        })}
        {xOff > X0 ? <Sun x={X0 + 70} y={170 - 80 * sunRise} r={30} /> : null}
        <g opacity={moonPop} transform={`translate(0,${(1 - moonPop) * 30})`}><Moon x={xOff + 66} y={90} r={30} /></g>
      </g>
      {xOff > X0 ? <T x={X0 + 140} y={101} size={36} weight={700} fill={C.forest} opacity={sunRise}>Lights on</T> : null}
      {oi < 0 ? <T x={xOff - 30} y={101} size={32} weight={600} fill={C.muted} anchor="end" opacity={sunRise}>{trim(dayH, 1)} h of light</T> : null}
      <T x={xOff + 130} y={101} size={36} weight={700} fill="#fff" opacity={moonPop}>Lights off</T>
      {oi < 0 ? <T x={X1 - 30} y={101} size={32} weight={600} fill="#c9d3e6" anchor="end" opacity={moonPop}>{trim(24 - dayH, 1)} h dark</T> : null}

      {/* Phase columns behind the trace */}
      {phases.map((ph, i) => (
        <rect key={ph.id} x={xs[i] + 3} y={CY0 - 20} width={xs[i + 1] - xs[i] - 6} height={CY1 - CY0 + 20} rx={14} fill={ph.color} opacity={rev[i] * (emph(i) ? (ph.dark ? 0.1 : 0.16) : 0.05)} />
      ))}
      {[50, 60].map((v) => (
        <g key={v}>
          <line x1={X0} x2={X1} y1={vy(v)} y2={vy(v)} stroke={C.line} strokeWidth={2} />
          <T x={X0 - 14} y={vy(v) + 11} size={30} fill={C.muted} anchor="end">{v}%</T>
        </g>
      ))}
      <T x={X0 - 14} y={CY0 + 4} size={30} weight={700} fill={C.water} anchor="end">VWC</T>
      <line x1={X0} x2={X1} y1={CY1} y2={CY1} stroke={C.muted} strokeWidth={3} />

      <g opacity={rev[0] * (0.75 + 0.25 * Math.sin(f / 9))}>
        <path d={`M ${xs[0] + 150} ${vy(57)} l 0 44 m -14 -16 l 14 18 l 14 -18`} stroke={C.gold} strokeWidth={5} fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <T x={xs[0] + 124} y={vy(57) + 34} size={30} weight={700} fill={C.gold} anchor="end">drying</T>
      </g>

      {/* Phase reference lines */}
      <g opacity={rev[1]}>
        <line x1={xs[1] + 10} x2={xs[2] - 10} y1={vy(62)} y2={vy(62)} stroke={C.water} strokeWidth={4} strokeDasharray="14 10" />
        <T x={xs[1] + 14} y={vy(62) - 16} size={30} weight={700} fill={C.water}>P1 target</T>
      </g>
      <g opacity={rev[2]}>
        <line x1={xs[2] + 10} x2={xs[3] - 10} y1={vy(58)} y2={vy(58)} stroke={C.plant} strokeWidth={4} strokeDasharray="14 10" />
        <T x={xs[2] + 14} y={vy(58) + 40} size={30} weight={700} fill={C.plant}>re-water threshold</T>
      </g>
      {showFloor ? (
        <g opacity={rev[3]}>
          <line x1={xs[3] + 10} x2={xs[4] - 10} y1={vy(47)} y2={vy(47)} stroke={C.error} strokeWidth={5} strokeDasharray="16 10" />
          <T x={xs[4] - 14} y={vy(47) + 40} size={30} weight={700} fill={C.error} anchor="end">Rescue floor</T>
        </g>
      ) : null}

      {area ? <path d={area} fill={C.waterLight} opacity={0.45} /> : null}
      {d ? <path d={d} fill="none" stroke={C.water} strokeWidth={7} strokeLinejoin="round" strokeLinecap="round" /> : null}

      {/* Shots: a drop falls onto each riser as the trace reaches it */}
      {phases.map((ph, i) =>
        ph.shots.map((us, k) => {
          const x = xs[i] + us * (xs[i + 1] - xs[i]);
          const t = starts[i] + us * lens[i];
          const yTop = vy(vAt(ph, us + RISE));
          const fall = lin(f, t - 14, t);
          const settled = f >= t;
          const ring = lin(f, t, t + 16);
          const rescue = ph.id === "P3";
          return (
            <g key={`${ph.id}-${k}`}>
              {f >= t - 14 && !settled ? <Drop x={x} y={150 + (yTop - 40 - 150) * fall * fall} r={14} /> : null}
              {settled ? <Drop x={x} y={yTop - 34 + Math.sin(f / 9 + k) * 3} r={12} fill={rescue ? C.error : C.water} /> : null}
              {ring > 0 && ring < 1 ? <circle cx={x} cy={yTop} r={8 + 30 * ring} fill="none" stroke={C.water} strokeWidth={4} opacity={1 - ring} /> : null}
              {rescue && settled ? <SvgChip x={x} y={yTop - 92} text="rescue shot" color={C.error} size={30} opacity={ring > 0 ? Math.min(1, ring * 2) : 1} /> : null}
            </g>
          );
        }),
      )}
      {head ? (
        <g>
          <circle cx={(head as [number, number])[0]} cy={(head as [number, number])[1]} r={16 + 4 * Math.sin(f / 6)} fill={C.water} opacity={0.25} />
          <circle cx={(head as [number, number])[0]} cy={(head as [number, number])[1]} r={9} fill={C.forest} />
        </g>
      ) : null}

      {/* Phase bands */}
      {phases.map((ph, i) => {
        const e = emph(i);
        const r = rev[i];
        const glow = e && highlight !== "all" ? 0.5 + 0.5 * Math.sin(f / 10) : 0;
        const x = xs[i] + 6, w = xs[i + 1] - xs[i] - 12;
        const tx = x + 22;
        const ink = ph.dark ? "#fff" : C.ink;
        return (
          <g key={ph.id} opacity={r * (e ? 1 : 0.55)} transform={`translate(0,${(1 - r) * 30 - (e ? 8 : 0)})`}>
            <rect x={x} y={600} width={w} height={196} rx={22} fill={ph.dark ? C.night : C.white} stroke={ph.color} strokeWidth={e ? 6 : 3} />
            <rect x={x} y={600} width={w} height={14} rx={7} fill={ph.color} />
            {glow ? <rect x={x - 6} y={594} width={w + 12} height={208} rx={26} fill="none" stroke={ph.color} strokeWidth={3} opacity={glow * 0.6} /> : null}
            <T x={tx} y={672} size={52} weight={800} fill={ph.dark ? "#f4ecc8" : ph.color}>{ph.id}</T>
            <T x={tx} y={724} size={36} weight={700} fill={ink}>{ph.name}</T>
            <T x={tx} y={770} size={30} fill={ph.dark ? "#c9d3e6" : C.muted}>{ph.job}</T>
          </g>
        );
      })}

      {/* Clock axis */}
      {([[X0, lightsOn, ""], [xOff, lightsOff, ""], [X1, lightsOn, " next day"]] as [number, string, string][]).map(([x, t, s], i) => (
        <g key={i} opacity={oi >= 0 ? 0 : i === 1 ? moonPop : sunRise}>
          <line x1={x} x2={x} y1={808} y2={836} stroke={C.forest} strokeWidth={4} />
          <T x={x} y={878} size={34} weight={700} fill={C.forest} anchor={i === 2 ? "end" : i === 0 ? "start" : "middle"}>{t}{s}</T>
        </g>
      ))}
      <g opacity={rev[1]}>
        <Drop x={X0 + 18} y={936} r={14} />
        <T x={X0 + 46} y={948} size={32} fill={C.ink}>one shot (one watering)</T>
      </g>
      {showFloor ? (
        <g opacity={rev[3]}>
          <line x1={X0 + 520} x2={X0 + 600} y1={937} y2={937} stroke={C.error} strokeWidth={5} strokeDasharray="16 10" />
          <T x={X0 + 620} y={948} size={32} fill={C.ink}>Rescue floor: an alarm line, not a target</T>
        </g>
      ) : null}
    </Svg>
  );
};

export default {
  Component,
  doc: "The grow-day as a timeline from lights-on to next lights-on: sun/moon sky strip, a VWC trace drawn phase by phase with water-drop shots, and four phase bands P0 (morning wait), P1 (refill shots stepping up), P2 (maintain: a shot each time VWC touches the re-water threshold), P3 (overnight dryback, Rescue floor, optional rescue shot). Phase widths are schematic. props: {highlight?:'P0'|'P1'|'P2'|'P3'|'all' (omitted = the newest revealed phase is emphasised), lightsOn:'06:00', lightsOff:'18:00', showFloor?:true, showRescue?:false, only?:'P0'|'P1'|'P2'|'P3' (show just that phase: its band, trace and sky span the full width on their own, no clock axis; steps: [that phase])}. steps: [P0 said, P1 said, P2 said, P3 said] — each phase band + its part of the trace appears at its step.",
  example: { props: { lightsOn: "06:00", lightsOff: "18:00", showFloor: true, showRescue: true }, steps: [12, 60, 110, 160] },
} satisfies SceneDef<P>;
