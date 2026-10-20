import React from "react";
import { useCurrentFrame } from "remotion";
import { C } from "../theme";
import { type SceneDef } from "./kit";
import { SvgStage, Defs, T, Pop, Card, Badge, Check, Cross, Led, HaMark, Pulses, ease, pop, at } from "./_system-shared";

type Stage = "parts" | "write" | "boot" | "browser";
type P = { device?: "pi" | "pc"; stages?: Stage[]; cardLabel?: string };

const URL = "homeassistant.local:8123";
const ORDER: Stage[] = ["parts", "write", "boot", "browser"];
// Native panel boxes [x, y, w, h] in the full four-panel layout.
const BOX: Record<Stage, [number, number, number, number]> = {
  parts: [40, 24, 480, 936], write: [550, 24, 740, 936], boot: [1320, 24, 560, 446], browser: [1320, 500, 560, 460],
};

// When some panels are omitted, re-lay the rest side by side, scaled up and centred on the stage.
function layout(shown: Stage[]): Record<Stage, string> {
  const out = {} as Record<Stage, string>;
  if (shown.length === 4) { ORDER.forEach((s) => (out[s] = "")); return out; }
  const GAP = 40;
  const sumW = shown.reduce((a, s) => a + BOX[s][2], 0);
  const maxH = Math.max(...shown.map((s) => BOX[s][3]));
  const k = Math.min((1840 - GAP * (shown.length - 1)) / sumW, 936 / maxH, 1.9);
  let x = (1920 - (sumW * k + GAP * (shown.length - 1))) / 2;
  shown.forEach((s) => {
    const [bx, by, w, h] = BOX[s];
    out[s] = `translate(${x} ${494 - (h * k) / 2}) scale(${k}) translate(${-bx} ${-by})`;
    x += w * k + GAP;
  });
  return out;
}

// Preparing the host: lay out parts → write the image (right drive only) → boot on Ethernet → open in browser.
const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const pi = props.device !== "pc";
  const stages: Stage[] = props.stages?.length ? props.stages : ["parts", "write", "boot", "browser"];
  const st = {} as Record<Stage, number>;
  stages.forEach((s, i) => (st[s] = at(steps, i, duration, stages.length)));
  const has = (s: Stage) => s in st;
  const card = pi ? "SD card" : "Internal disk";
  const size = pi ? "64 GB" : "256 GB";
  const tf = layout(ORDER.filter(has));

  // write-stage timeline
  const w0 = st.write ?? 0;
  const choose = ease(f, w0 + 8, 14);
  const warn = pop(f, w0 + 18);
  const prog = has("write") ? Math.min(1, Math.max(0, (f - (w0 + 26)) / 60)) : 0;
  const done = prog >= 1;
  // boot / browser
  const b0 = st.boot ?? 0;
  const booted = f > b0 + 40;
  const r0 = st.browser ?? 0;
  const typed = Math.floor(Math.max(0, Math.min(URL.length, (f - r0 - 6) * 1.1)));
  const pageIn = ease(f, r0 + 6 + URL.length / 1.1 + 4, 16);

  return (
    <SvgStage>
      <Defs />
      {/* 1 PARTS */}
      {has("parts") ? (
        <g transform={tf.parts}><Pop x={280} y={490} s={pop(f, st.parts)}>
          <Card x={40} y={24} w={480} h={936}>
            <Badge x={86} y={74} n={1} />
            <T x={126} y={76} anchor="start" size={36}>Parts</T>
            {pi ? <PiBoard x={280} y={270} f={f} s={1.12} /> : <MiniPc x={280} y={270} f={f} s={1.2} />}
            <T x={280} y={420} size={32}>{pi ? "Raspberry Pi 4 or 5" : "Small PC (x86-64)"}</T>
            {/* storage */}
            <g transform={`translate(160 560) rotate(${Math.sin(f / 20) * 3})`}>
              {pi ? <SdCard x={0} y={0} /> : <DiskIcon x={0} y={0} color="#5b6b74" />}
            </g>
            <T x={160} y={660} size={30}>{props.cardLabel ?? (pi ? "64 GB card" : "Internal disk")}</T>
            {/* power supply */}
            <g transform="translate(400 560)">
              <rect x={-44} y={-50} width={88} height={84} rx={14} fill={C.white} stroke={C.forest} strokeWidth={4} />
              <path d="M-10 -24 L8 -24 L-4 0 L10 0 L-10 26 L-4 4 L-16 4 Z" fill={C.ec} />
              <path d="M0 34 Q0 70 -40 74" stroke={C.forest} strokeWidth={6} fill="none" />
            </g>
            <T x={400} y={660} size={30}>Power supply</T>
            {/* Ethernet cable */}
            <g transform="translate(280 790)">
              <path d={`M-150 0 C-90 ${-60 + Math.sin(f / 15) * 8} -30 ${60 - Math.sin(f / 15) * 8} 30 0 S 120 -40 150 0`} stroke="#3a6fb0" strokeWidth={9} fill="none" strokeLinecap="round" />
              <rect x={-186} y={-16} width={40} height={32} rx={5} fill={C.white} stroke="#3a6fb0" strokeWidth={4} />
              <rect x={146} y={-16} width={40} height={32} rx={5} fill={C.white} stroke="#3a6fb0" strokeWidth={4} />
            </g>
            <T x={280} y={880} size={30}>Ethernet cable</T>
          </Card>
        </Pop></g>
      ) : null}

      {/* 2 WRITE */}
      {has("write") ? (
        <g transform={tf.write}><Pop x={920} y={490} s={pop(f, st.write)}>
          <Card x={550} y={24} w={740} h={936}>
            <Badge x={596} y={74} n={2} />
            <T x={636} y={76} anchor="start" size={36}>Write the image</T>
            {/* laptop */}
            <rect x={610} y={120} width={620} height={380} rx={18} fill={C.forest} />
            <rect x={628} y={138} width={584} height={344} rx={8} fill={C.white} />
            <path d="M570 500 L1270 500 L1246 532 L594 532 Z" fill="#8c9a90" />
            <T x={652} y={176} anchor="start" size={30} fill={C.muted}>{pi ? "Raspberry Pi Imager" : "Disks · Restore image"}</T>
            <rect x={652} y={204} width={536} height={58} rx={12} fill={C.leaf} />
            <HaMark x={688} y={236} s={0.6} />
            <T x={716} y={234} anchor="start" size={30}>Home Assistant OS</T>
            <rect x={652} y={276} width={536} height={58} rx={12} fill={C.white} stroke={choose > 0.5 ? C.good : C.line} strokeWidth={4} />
            <T x={672} y={306} anchor="start" size={30}>{`Storage: ${card} · ${size}`}</T>
            {/* progress */}
            <rect x={652} y={372} width={536} height={34} rx={17} fill={C.leaf} />
            <rect x={652} y={372} width={Math.max(34, 536 * prog)} height={34} rx={17} fill={done ? C.good : C.water} opacity={prog > 0 ? 1 : 0} />
            {prog > 0 && !done ? <rect x={652 + 536 * prog - 60} y={372} width={40} height={34} fill={C.white} opacity={0.35 * Math.abs(Math.sin(f / 5))} /> : null}
            <T x={920} y={444} size={30} fill={done ? C.good : C.ink}>{prog <= 0 ? "Ready to write" : done ? "Write finished ✓" : `Writing… ${Math.round(prog * 100)}%`}</T>
            {/* warning */}
            <Pop x={920} y={610} s={warn}>
              <rect x={590} y={570} width={660} height={84} rx={18} fill="#fbecd3" stroke={C.warn} strokeWidth={4} />
              <path d="M638 636 L664 588 L690 636 Z" fill={C.warn} />
              <T x={664} y={622} size={30} fill={C.white}>!</T>
              <T x={712} y={613} anchor="start" size={32} fill="#8a5414">This erases the selected drive</T>
            </Pop>
            {/* drive choice */}
            <g opacity={choose}>
              <g transform={`translate(740 ${790 + (1 - choose) * 30})`}>
                <rect x={-150} y={-90} width={300} height={220} rx={20} fill={C.white} stroke={C.good} strokeWidth={5} />
                {pi ? <SdCard x={0} y={-10} /> : <DiskIcon x={0} y={-10} color="#5b6b74" />}
                <T x={0} y={90} size={30}>{`${card} ${size}`}</T>
              </g>
              <Check x={872} y={694} r={30} s={pop(f, w0 + 12)} />
              <g transform={`translate(1100 ${790 + (1 - choose) * 30})`} opacity={0.55}>
                <rect x={-150} y={-90} width={300} height={220} rx={20} fill={C.white} stroke={C.error} strokeWidth={5} />
                <DiskIcon x={0} y={-10} color="#7a6a5a" photo />
                <T x={0} y={90} size={30}>Photos 1 TB</T>
                <line x1={-120} y1={-60} x2={120} y2={100} stroke={C.error} strokeWidth={8} strokeLinecap="round" />
              </g>
              <Cross x={1232} y={694} r={30} s={pop(f, w0 + 16)} />
            </g>
          </Card>
        </Pop></g>
      ) : null}

      {/* 3 BOOT */}
      {has("boot") ? (
        <g transform={tf.boot}><Pop x={1600} y={250} s={pop(f, st.boot)}>
          <Card x={1320} y={24} w={560} h={446}>
            <Badge x={1366} y={74} n={3} />
            <T x={1406} y={76} anchor="start" size={36}>Boot on Ethernet</T>
            {pi ? <PiBoard x={1470} y={260} f={f} s={0.72} booting /> : <MiniPc x={1470} y={260} f={f} s={0.72} />}
            {/* router */}
            <rect x={1700} y={250} width={140} height={70} rx={14} fill={C.white} stroke={C.forest} strokeWidth={4} />
            <path d="M1724 250 L1714 196 M1816 250 L1826 196" stroke={C.forest} strokeWidth={5} strokeLinecap="round" />
            {[0, 1, 2].map((i) => <Led key={i} x={1736 + i * 34} y={286} f={f} phase={i * 7} period={14} r={7} color={C.good} />)}
            <path d="M1580 300 C1630 300 1650 286 1700 286" stroke="#3a6fb0" strokeWidth={8} fill="none" />
            <Pulses pts={[[1582, 300], [1640, 296], [1700, 286]]} f={f} n={2} period={30} color={C.water} r={6} opacity={booted ? 1 : 0.4} />
            <T x={1770} y={360} size={30}>Router</T>
            <T x={1600} y={420} size={32} fill={booted ? C.good : C.muted}>{booted ? "Started — on the network" : "Starting up…"}</T>
          </Card>
        </Pop></g>
      ) : null}

      {/* 4 BROWSER */}
      {has("browser") ? (
        <g transform={tf.browser}><Pop x={1600} y={730} s={pop(f, st.browser)}>
          <Card x={1320} y={500} w={560} h={460}>
            <Badge x={1366} y={550} n={4} />
            <T x={1406} y={552} anchor="start" size={36}>Open in a browser</T>
            <rect x={1346} y={596} width={508} height={340} rx={14} fill={C.white} stroke={C.forest} strokeWidth={4} />
            <rect x={1346} y={596} width={508} height={64} rx={14} fill={C.leaf} />
            {[0, 1, 2].map((i) => <circle key={i} cx={1372 + i * 22} cy={628} r={7} fill={[C.error, C.warn, C.good][i]} />)}
            <rect x={1440} y={608} width={400} height={42} rx={21} fill={C.white} stroke={C.line} strokeWidth={2} />
            <T x={1456} y={630} anchor="start" size={30} weight={600}>{URL.slice(0, typed)}{typed < URL.length && Math.floor(f / 8) % 2 ? "|" : ""}</T>
            <g opacity={pageIn}>
              <HaMark x={1600} y={740} s={1.6} />
              <T x={1600} y={826} size={34}>Welcome home!</T>
              <rect x={1478} y={856} width={244} height={56} rx={28} fill="#03a9f4" />
              <T x={1600} y={885} size={30} fill={C.white}>Get started</T>
            </g>
          </Card>
        </Pop></g>
      ) : null}
    </SvgStage>
  );
};

const PiBoard: React.FC<{ x: number; y: number; f: number; s?: number; booting?: boolean }> = ({ x, y, f, s = 1, booting }) => (
  <g transform={`translate(${x} ${y}) scale(${s})`}>
    <rect x={-150} y={-100} width={300} height={200} rx={16} fill="#2f8a4f" stroke={C.forest} strokeWidth={4} />
    {[[-132, -82], [118, -82], [-132, 82], [118, 82]].map(([a, b], i) => <circle key={i} cx={a + 7} cy={b} r={7} fill="#f2e9c9" />)}
    <rect x={-110} y={-92} width={200} height={20} rx={4} fill="#1d3b2c" />
    {Array.from({ length: 20 }, (_, i) => <circle key={i} cx={-104 + i * 10} cy={-82} r={3} fill={C.gold} />)}
    <rect x={-70} y={-36} width={74} height={74} rx={8} fill="#c9cfd2" stroke="#8b979c" strokeWidth={3} />
    <rect x={20} y={-30} width={52} height={52} rx={6} fill="#1e2a26" />
    <rect x={112} y={-70} width={50} height={40} rx={4} fill="#c9cfd2" stroke="#8b979c" strokeWidth={3} />
    <rect x={112} y={-20} width={50} height={40} rx={4} fill="#c9cfd2" stroke="#8b979c" strokeWidth={3} />
    <rect x={112} y={30} width={50} height={52} rx={4} fill="#c9cfd2" stroke="#8b979c" strokeWidth={3} />
    <Led x={-120} y={50} f={f} color={C.error} period={1000} r={8} />
    <Led x={-96} y={50} f={f} color={C.good} period={booting ? 7 : 26} r={8} />
  </g>
);

const MiniPc: React.FC<{ x: number; y: number; f: number; s?: number }> = ({ x, y, f, s = 1 }) => (
  <g transform={`translate(${x} ${y}) scale(${s})`}>
    <rect x={-150} y={-80} width={300} height={160} rx={22} fill="#3b4a46" stroke={C.forest} strokeWidth={4} />
    {Array.from({ length: 6 }, (_, i) => <rect key={i} x={-110 + i * 30} y={-50} width={14} height={50} rx={4} fill="#2a3532" />)}
    <rect x={60} y={30} width={60} height={14} rx={4} fill="#2a3532" />
    <Led x={-110} y={40} f={f} color={C.water} period={24} r={8} />
  </g>
);

const SdCard: React.FC<{ x: number; y: number }> = ({ x, y }) => (
  <g transform={`translate(${x} ${y})`}>
    <path d="M-40 -60 L24 -60 L44 -40 L44 60 L-44 60 L-44 -56 Z" fill="#2d3b48" stroke={C.forest} strokeWidth={3} />
    {[0, 1, 2, 3].map((i) => <rect key={i} x={-34 + i * 16} y={-54} width={10} height={20} rx={2} fill={C.gold} />)}
    <rect x={-32} y={0} width={64} height={34} rx={4} fill={C.white} />
    <text x={0} y={23} fontSize={20} fontWeight={800} textAnchor="middle" fill="#2d3b48">64GB</text>
  </g>
);

const DiskIcon: React.FC<{ x: number; y: number; color: string; photo?: boolean }> = ({ x, y, color, photo }) => (
  <g transform={`translate(${x} ${y})`}>
    <rect x={-64} y={-56} width={128} height={112} rx={14} fill={color} stroke={C.forest} strokeWidth={3} />
    {photo ? (
      <g>
        <rect x={-38} y={-34} width={76} height={56} rx={6} fill={C.white} />
        <path d="M-32 16 L-10 -8 L6 8 L16 -2 L32 16 Z" fill={C.plant} />
        <circle cx={18} cy={-18} r={7} fill={C.gold} />
      </g>
    ) : (
      <circle cx={0} cy={-4} r={30} fill="#c9cfd2" stroke="#8b979c" strokeWidth={3} />
    )}
    <circle cx={46} cy={40} r={5} fill={C.good} />
  </g>
);

export default {
  Component,
  doc: "Preparing the host computer in four numbered panels: 1 Parts (Raspberry Pi board or small PC, 64 GB card / internal disk, power supply, Ethernet cable) · 2 Write the image (laptop running Imager/Disks, the right drive ticked, the 1 TB photo drive crossed out, amber 'This erases the selected drive' warning, progress bar to 'Write finished') · 3 Boot on Ethernet (board LEDs flicker, cable to router with data pulses) · 4 Open in a browser (types homeassistant.local:8123, then 'Welcome home!'). props: {device?:'pi'|'pc' (default pi), cardLabel?:string (Parts-panel storage caption, default '64 GB card' / 'Internal disk', e.g. '32 GB or more'), stages?:('parts'|'write'|'boot'|'browser')[] (default all; omitted panels are not drawn and the remaining panels are re-laid out side by side, scaled up and centred — one panel shows large in the middle)}. steps: one per entry of stages, in order. The write panel needs ~90 frames after its step to finish its progress bar.",
  example: { props: { device: "pi", stages: ["parts", "write", "boot", "browser"] }, steps: [6, 30, 130, 170] },
} satisfies SceneDef<P>;
