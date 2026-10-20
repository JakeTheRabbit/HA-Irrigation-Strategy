import React from "react";
import { useCurrentFrame } from "remotion";
import { C } from "../theme";
import { type SceneDef } from "./kit";
import { SvgStage, Defs, T, Pill, Pop, Check, Led, HaMark, pointAt, polyLen, ease, pop, at, type Pt } from "./_system-shared";

type P = { revision?: number; acknowledged?: boolean; showRevision?: boolean };

const bezQ = (a: Pt, c: Pt, b: Pt, n = 40): Pt[] =>
  Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n, u = 1 - t;
    return [u * u * a[0] + 2 * u * t * c[0] + t * t * b[0], u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]];
  });
const OUT = bezQ([700, 200], [1000, -40], [1290, 250]);
const BACK = bezQ([1290, 470], [1080, 760], [900, 560]);
const [QX, QY] = pointAt(BACK, polyLen(BACK) * 0.5);

// "Save configuration" posts a letter to the Controller; "Mapping acknowledged" is the receipt that comes back.
const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const rev = props.revision ?? 12;
  const sr = props.showRevision !== false; // false hides every revision number
  const ack = props.acknowledged !== false;
  const s0 = at(steps, 0, duration, 3, 30);
  const s1 = Math.max(at(steps, 1, duration, 3, 30), s0 + 30);
  const s2 = Math.max(at(steps, 2, duration, 3, 30), s1 + 10);

  const saved = f >= s0;
  const flyOut = Math.min(1, Math.max(0, (f - s0 - 4) / (s1 - s0 - 4)));
  const arrived = f >= s1;
  const flyBack = ack ? Math.min(1, Math.max(0, (f - s2) / 30)) : 0;
  const landed = ack && f >= s2 + 30;
  const waiting = !ack && f >= s2;

  // cursor heads for the button before the click
  const cur = ease(f, Math.max(0, s0 - 24), 20);
  const cx = 640 - 220 * cur, cy = 640 - 196 * cur;
  const press = saved && f < s0 + 6;

  const [ex, ey] = pointAt(OUT, polyLen(OUT) * easeIO(flyOut));
  const [rx, ry] = pointAt(BACK, polyLen(BACK) * easeIO(flyBack));

  const status = landed
    ? { t: sr ? `Mapping acknowledged · rev ${rev}` : "Mapping acknowledged", c: C.good }
    : waiting
      ? { t: "Saved · waiting for receipt", c: C.warn }
      : saved
        ? { t: sr ? `Saved · revision ${rev}` : "Saved", c: C.forest }
        : { t: "Unsaved changes", c: C.muted };

  return (
    <SvgStage>
      <Defs />
      {/* route hints */}
      <path d={"M" + OUT.map((p) => p.join(" ")).join(" L")} stroke={C.line} strokeWidth={5} strokeDasharray="4 16" strokeLinecap="round" fill="none" />
      <path d={"M" + BACK.map((p) => p.join(" ")).join(" L")} stroke={waiting ? C.warn : C.line} strokeWidth={5} strokeDasharray="4 16" strokeLinecap="round" fill="none" opacity={waiting ? 0.5 + 0.5 * Math.sin(f / 8) : 1} />

      {/* HOME ASSISTANT SCREEN */}
      <Pop x={420} y={330} s={pop(f, 0)}>
        <rect x={360} y={600} width={120} height={50} fill="#8c9a90" />
        <rect x={270} y={646} width={300} height={22} rx={10} fill="#8c9a90" />
        <rect x={90} y={60} width={660} height={548} rx={26} fill={C.forest} filter="url(#sh)" />
        <rect x={112} y={82} width={616} height={500} rx={12} fill={C.white} />
        <rect x={112} y={82} width={616} height={70} rx={12} fill={C.leaf} />
        <HaMark x={156} y={116} s={0.7} />
        <T x={190} y={118} anchor="start" size={30}>Crop Steering setup</T>
        {sr ? <T x={140} y={200} anchor="start" size={30} fill={C.muted} weight={600}>Revision</T> : null}
        {sr ? <T x={290} y={200} anchor="start" size={44}>{rev}</T> : null}
        {[0, 1, 2].map((i) => (
          <g key={i}>
            <rect x={140} y={240 + i * 46} width={36} height={30} rx={6} fill={C.leaf} />
            <rect x={190} y={248 + i * 46} width={[300, 240, 340][i]} height={14} rx={7} fill={C.line} />
          </g>
        ))}
        <rect x={140} y={396} width={380} height={68} rx={16} fill={press ? "#0b6fa0" : "#03a9f4"} transform={press ? "translate(0 3)" : undefined} />
        <T x={330} y={431} size={30} fill={C.white}>Save configuration</T>
        <rect x={140} y={494} width={560} height={64} rx={14} fill={landed ? "#e3f0e4" : waiting ? "#fbecd3" : C.paper} stroke={status.c} strokeWidth={3} />
        {waiting ? <Hourglass x={176} y={526} f={f} /> : landed ? <Check x={176} y={526} r={20} s={pop(f, s2 + 30)} /> : <circle cx={176} cy={526} r={9} fill={status.c} />}
        <T x={208} y={527} anchor="start" size={30} fill={status.c}>{status.t}</T>
      </Pop>
      {/* cursor */}
      <path d={`M${cx} ${cy} l0 46 l12 -12 l10 22 l9 -4 l-10 -21 l17 0 Z`} fill={C.white} stroke={C.ink} strokeWidth={3} strokeLinejoin="round" opacity={f < s0 + 20 ? cur : Math.max(0, 1 - (f - s0 - 20) / 10)} />
      {press ? <circle cx={cx} cy={cy} r={26 + (f - s0) * 4} fill="none" stroke="#03a9f4" strokeWidth={4} opacity={1 - (f - s0) / 6} /> : null}

      {/* CONTROLLER */}
      <Pop x={1520} y={350} s={pop(f, 4)}>
        <rect x={1290} y={110} width={520} height={480} rx={28} fill={C.forest} filter="url(#sh)" />
        <rect x={1270} y={220} width={40} height={64} rx={8} fill="#0f2a24" />
        <T x={1550} y={170} size={38} fill={C.white}>Controller</T>
        {/* reading panel */}
        <rect x={1340} y={220} width={420} height={150} rx={18} fill="#24584b" />
        {arrived ? (
          landed || (ack && f >= s2) ? (
            <g>
              <T x={1550} y={270} size={30} fill={C.white}>{sr ? `Accepted revision ${rev}` : "Accepted"}</T>
              <Check x={1550} y={326} r={26} s={pop(f, s2 - 4)} />
            </g>
          ) : (
            <g>
              <T x={1550} y={270} size={30} fill={C.white}>{waiting ? "No receipt sent" : sr ? `Reading revision ${rev}…` : "Reading…"}</T>
              <rect x={1380} y={318} width={340} height={14} rx={7} fill="#0f2a24" />
              <rect x={1380 + ((f * 6) % 300)} y={318} width={40} height={14} rx={7} fill={waiting ? C.warn : C.gold} />
            </g>
          )
        ) : (
          <T x={1550} y={296} size={30} fill="#9fbab0">waiting for mail</T>
        )}
        {/* heartbeat */}
        <Ecg x={1350} y={470} w={330} f={f} />
        <Led x={1730} y={470} f={f} color={C.good} period={30} r={12} />
        <T x={1550} y={548} size={30} fill="#cfe0d8" weight={600}>heartbeat = alive</T>
      </Pop>

      {/* envelope in flight */}
      {saved && flyOut < 1 ? <Envelope x={ex} y={ey} rev={sr ? rev : ""} rot={(flyOut - 0.5) * 30} s={1 - 0.3 * Math.max(0, flyOut - 0.8) / 0.2} /> : null}
      {/* receipt flying back */}
      {ack && f >= s2 ? <Receipt x={rx} y={ry + (landed ? Math.sin((f - s2) / 14) * 6 : 0)} rev={sr ? rev : ""} rot={landed ? -6 : (0.5 - flyBack) * 20} /> : null}
      {waiting ? (
        <g opacity={0.8 + 0.2 * Math.sin(f / 8)}>
          <circle cx={QX} cy={QY} r={42} fill="#fbecd3" stroke={C.warn} strokeWidth={4} />
          <T x={QX} y={QY + 2} size={40} fill={C.warn}>?</T>
        </g>
      ) : null}

      {/* analogy chips */}
      <Pop x={470} y={880} s={pop(f, s0 + 6)}>
        <Pill x={470} y={880} w={700} text="Save configuration = posting the letter" color={C.forest} size={32} />
      </Pop>
      <Pop x={1420} y={880} s={pop(f, s2 + (ack ? 30 : 4))}>
        {ack ? (
          <Pill x={1420} y={880} w={700} text="Mapping acknowledged = the receipt" color={C.good} fill="#eef6ee" size={32} />
        ) : (
          <Pill x={1420} y={880} w={700} text="No receipt yet: keep Watering OFF" color={C.warn} fill="#fdf4e4" size={32} />
        )}
      </Pop>
    </SvgStage>
  );
};

const easeIO = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);

const Envelope: React.FC<{ x: number; y: number; rev: number | ""; rot: number; s: number }> = ({ x, y, rev, rot, s }) => (
  <g transform={`translate(${x} ${y}) rotate(${rot}) scale(${s})`}>
    <rect x={-80} y={-52} width={160} height={104} rx={10} fill={C.white} stroke={C.forest} strokeWidth={4} filter="url(#sh)" />
    <path d="M-78 -48 L0 12 L78 -48" stroke={C.forest} strokeWidth={4} fill="none" strokeLinejoin="round" />
    <circle cx={0} cy={22} r={26} fill={C.error} />
    <text x={0} y={33} fontSize={30} fontWeight={800} textAnchor="middle" fill={C.white}>{rev}</text>
  </g>
);

const Receipt: React.FC<{ x: number; y: number; rev: number | ""; rot: number }> = ({ x, y, rev, rot }) => (
  <g transform={`translate(${x} ${y}) rotate(${rot})`}>
    <path d={`M-100 -80 L100 -80 L100 70 ${Array.from({ length: 10 }, (_, i) => `L${100 - (i + 0.5) * 20} ${i % 2 ? 70 : 84} `).join("")} L-100 70 Z`} fill={C.white} stroke={C.good} strokeWidth={4} filter="url(#sh)" />
    <circle cx={-56} cy={-38} r={22} fill={C.good} />
    <path d="M-66 -38 L-58 -30 L-46 -46" stroke={C.white} strokeWidth={5} fill="none" strokeLinecap="round" />
    <text x={18} y={-28} fontSize={30} fontWeight={800} textAnchor="middle" fill={C.good}>ACK</text>
    <text x={0} y={30} fontSize={30} fontWeight={700} textAnchor="middle" fill={C.ink}>{rev === "" ? "received" : `rev ${rev}`}</text>
  </g>
);

const Hourglass: React.FC<{ x: number; y: number; f: number }> = ({ x, y, f }) => (
  <g transform={`rotate(${Math.floor(f / 40) % 2 ? 180 : 0} ${x} ${y})`}>
    <path d={`M${x - 14} ${y - 18} L${x + 14} ${y - 18} L${x} ${y} L${x + 14} ${y + 18} L${x - 14} ${y + 18} L${x} ${y} Z`} fill="#fbecd3" stroke={C.warn} strokeWidth={4} strokeLinejoin="round" />
    <path d={`M${x - 8} ${y + 14} L${x + 8} ${y + 14} L${x} ${y + 4} Z`} fill={C.warn} />
  </g>
);

const Ecg: React.FC<{ x: number; y: number; w: number; f: number }> = ({ x, y, w, f }) => {
  const pts: string[] = [];
  for (let i = 0; i <= 66; i++) {
    const px = x + (i * w) / 66;
    const ph = (((i * 2 - f * 2) % 60) + 60) % 60;
    const dy = ph === 10 ? -46 : ph === 12 ? 30 : ph === 8 ? -10 : 0;
    pts.push(`${px} ${y + dy}`);
  }
  return <path d={"M" + pts.join(" L")} stroke={C.good} strokeWidth={5} fill="none" strokeLinejoin="round" />;
};

export default {
  Component,
  doc: "Save configuration is posting a letter; Mapping acknowledged is the receipt. Left: a Home Assistant 'Crop Steering setup' screen showing the revision; a cursor clicks Save configuration and an envelope stamped with the revision arcs over to the Controller box (which shows a live heartbeat — 'alive' — the whole time). The Controller reads it, then (acknowledged) a green ACK receipt flies back and the screen's status turns 'Mapping acknowledged · rev N'; or (not acknowledged) no receipt comes, the return route pulses amber with a '?', status reads 'Saved · waiting for receipt' with an hourglass and the chip says 'No receipt yet: keep Watering OFF'. props: {showRevision?:true (false hides the revision number everywhere: screen row, envelope seal, receipt, status texts), revision?:12, acknowledged?:true}. steps: [Save pressed, letter arrives at Controller, receipt returns (or waiting state shown)].",
  example: { props: { revision: 12, acknowledged: true }, steps: [30, 75, 120] },
} satisfies SceneDef<P>;
