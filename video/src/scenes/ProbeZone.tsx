import React, { useMemo } from "react";
import { useCurrentFrame, random } from "remotion";
import { C } from "../theme";
import { stepAt } from "../anim";
import type { SceneDef } from "./kit";
import { SceneSvg, SW, Pill, POT, WATER_DEEP, blobPath, dropPath, c01, ease, pop, lerp, textW } from "./_rootzone-shared";

type Show = "region" | "dripper" | "airgap" | "uneven";
type P = { pots?: number; probeAt?: number; show?: Show[]; reading?: string | null; callout?: string };

const TOP = 470, PH = 270, BENCH = TOP + PH;
const LINE_Y = 395;

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const n = Math.max(1, props.pots ?? 5);
  const probeAt = Math.min(n - 1, Math.max(0, props.probeAt ?? Math.floor(n / 2)));
  const show = props.show || ["region", "dripper", "uneven"];
  const at = (k: Show) => {
    const i = show.indexOf(k);
    return i < 0 ? 1e9 : Number.isFinite(steps[i]) ? steps[i] : stepAt(steps, i, duration, show.length) || 20 + i * 40;
  };
  const slot = 1720 / n;
  const pw = Math.min(300, slot * 0.78);
  const pbw = pw * 0.8;
  const cxOf = (i: number) => 100 + slot * (i + 0.5);
  const px = cxOf(probeAt);
  const needleX = px + pw * 0.14;
  const side = probeAt < n - 1 ? 1 : -1;
  const appear = ease(f, 0, 18);

  const tUneven = ease(f, at("uneven"), 30);
  const level = (i: number) => lerp(0.6, i === probeAt ? 0.6 : 0.2 + 0.75 * random(`pz-lv${i}`), tUneven);
  const regionP = ease(f, at("region"), 20);
  const dripP = ease(f, at("dripper"), 20);
  const airP = pop(f, at("airgap"), 22);

  const parts = useMemo(
    () =>
      Array.from({ length: n }, (_, i) =>
        Array.from({ length: 48 }, (_, j) => {
          const u = random(`pz${i}u${j}`), v = random(`pz${i}v${j}`);
          return { u, v, r: 9 + random(`pz${i}r${j}`) * 7 };
        }),
      ),
    [n],
  );

  const potPath = (cx: number) => `M ${cx - pw / 2} ${TOP} L ${cx + pw / 2} ${TOP} L ${cx + pbw / 2} ${BENCH - 6} L ${cx - pbw / 2} ${BENCH - 6} Z`;
  const reading = props.reading === undefined ? "62%" : props.reading; // null / "" hides the badge
  const insetX = px + side * (pw / 2 + 330), insetY = 230, insetR = 135;

  return (
    <SceneSvg>
      <defs>
        {Array.from({ length: n }, (_, i) => (
          <React.Fragment key={i}>
            <clipPath id={`pz-c${i}`}>
              <path d={potPath(cxOf(i))} />
            </clipPath>
            <radialGradient id={`pz-g${i}`} cx={cxOf(i) - pw * 0.26} cy={TOP + 10} r={pw * (1.05 + 0.03 * Math.sin(f / 20 + i))} gradientUnits="userSpaceOnUse">
              <stop offset="0" stopColor={C.water} stopOpacity={Math.min(0.95, 0.4 + 0.6 * level(i))} />
              <stop offset="0.5" stopColor={C.water} stopOpacity={0.55 * level(i) + 0.1 * dripP * (i === probeAt ? 1 : 0)} />
              <stop offset="1" stopColor={C.water} stopOpacity={0.08 * level(i) * (1 - dripP * (i === probeAt ? 1 : 0))} />
            </radialGradient>
          </React.Fragment>
        ))}
        <radialGradient id="pz-reg">
          <stop offset="0" stopColor={C.gold} stopOpacity={0.55} />
          <stop offset="0.7" stopColor={C.gold} stopOpacity={0.25} />
          <stop offset="1" stopColor={C.gold} stopOpacity={0} />
        </radialGradient>
        <clipPath id="pz-inset">
          <circle cx={insetX} cy={insetY} r={insetR} />
        </clipPath>
      </defs>

      <g opacity={appear}>
        {/* bench */}
        <rect x={60} y={BENCH} width={SW - 120} height={26} rx={10} fill={C.solid} />
        <rect x={120} y={BENCH + 26} width={22} height={120} fill={C.solid} opacity={0.7} />
        <rect x={SW - 142} y={BENCH + 26} width={22} height={120} fill={C.solid} opacity={0.7} />

        {/* pots */}
        {Array.from({ length: n }, (_, i) => {
          const cx = cxOf(i);
          const dim = i === probeAt ? 1 : 0.92;
          return (
            <g key={i} opacity={dim}>
              <g clipPath={`url(#pz-c${i})`}>
                <rect x={cx - pw / 2} y={TOP} width={pw} height={PH} fill={C.solidLight} />
                {parts[i].map((p, j) => (
                  <path key={j} d={blobPath(cx - pw / 2 + p.u * pw, TOP + 6 + p.v * (PH - 10), p.r, `pzb${i}-${j}`)} fill={C.solid} opacity={0.75} />
                ))}
                <rect x={cx - pw / 2} y={TOP} width={pw} height={PH} fill={`url(#pz-g${i})`} />
              </g>
              <path d={potPath(cx)} fill="none" stroke={POT} strokeWidth={12} strokeLinejoin="round" />
              <rect x={cx - pw / 2 - 14} y={TOP - 14} width={pw + 28} height={18} rx={9} fill={POT} />
              {/* unknown readings for the other pots */}
              {i !== probeAt && tUneven > 0.01 ? (
                <g transform={`translate(${cx} ${TOP + PH / 2}) scale(${pop(f, at("uneven") + 6 + Math.abs(i - probeAt) * 4, 16)})`}>
                  <circle r={46} fill={C.white} stroke={C.muted} strokeWidth={4} />
                  <text y={20} textAnchor="middle" fontSize={56} fontWeight={700} fill={C.muted} transform={`rotate(${Math.sin(f / 14 + i) * 6})`}>?</text>
                </g>
              ) : null}
            </g>
          );
        })}

        {/* drip line + drippers + drops */}
        <path d={`M 40 ${LINE_Y - 60} Q 70 ${LINE_Y} 120 ${LINE_Y} L ${SW - 80} ${LINE_Y}`} fill="none" stroke={POT} strokeWidth={12} strokeLinecap="round" />
        {Array.from({ length: n }, (_, i) => {
          const dx = cxOf(i) - pw * 0.26;
          const per = 34 + (i % 3) * 6;
          const t = ((f + i * 13) % per) / per;
          return (
            <g key={i}>
              <path d={`M ${dx} ${LINE_Y} L ${dx} ${TOP - 30}`} stroke={POT} strokeWidth={5} />
              <rect x={dx - 13} y={LINE_Y - 4} width={26} height={30} rx={7} fill={C.forest} />
              <path d={dropPath(dx, lerp(TOP - 26, TOP + 8, t * t), 7)} fill={C.water} opacity={1 - t * 0.5} />
              {i === probeAt && dripP > 0 ? (
                <circle cx={dx} cy={TOP + 10} r={30 + ((f % 40) / 40) * 40} fill="none" stroke={WATER_DEEP} strokeWidth={4} opacity={dripP * (1 - (f % 40) / 40)} />
              ) : null}
            </g>
          );
        })}
      </g>

      {/* sensing region */}
      {regionP > 0 ? (
        <g opacity={regionP}>
          <ellipse cx={needleX} cy={TOP + 85} rx={(62 + Math.sin(f / 12) * 5) * regionP} ry={(92 + Math.sin(f / 12) * 5) * regionP} fill="url(#pz-reg)" />
          <ellipse cx={needleX} cy={TOP + 85} rx={62 * regionP} ry={92 * regionP} fill="none" stroke={C.gold} strokeWidth={5} strokeDasharray="12 9" strokeDashoffset={-f * 0.8} />
        </g>
      ) : null}

      {/* probe */}
      <g opacity={appear}>
        {[-16, 0, 16].map((d) => (
          <rect key={d} x={needleX + d - 3.5} y={TOP - 24} width={7} height={140} rx={3.5} fill="#9aa3ad" stroke="#6b7480" strokeWidth={2} />
        ))}
        <rect x={needleX - 34} y={TOP - 70} width={68} height={50} rx={10} fill={POT} />
        <circle cx={needleX + 18} cy={TOP - 45} r={5} fill={C.good} opacity={0.5 + 0.5 * Math.sin(f / 6)} />
        <path d={`M ${needleX} ${TOP - 70} C ${needleX} ${TOP - 120} ${needleX + 60 * side} ${TOP - 110} ${needleX + 90 * side} ${TOP - 150}`} stroke={POT} strokeWidth={7} fill="none" strokeLinecap="round" />
      </g>
      {reading ? <Pill x={needleX + 40 * side} y={TOP - 140} text={`Probe: ${reading}`} anchor={side > 0 ? "start" : "end"} size={34} color={C.forest} p={pop(f, 8, 16)} /> : null}

      {/* region callout */}
      {regionP > 0 ? (() => {
        const text = props.callout || "The reading only describes here";
        const air = show.includes("airgap");
        const y = air ? 110 : 230;
        const w = textW(text, 38) + 46;
        const want = air ? needleX - side * (w / 2 + 40) : needleX;
        const x = Math.max(70 + w / 2, Math.min(SW - 70 - w / 2, want));
        return (
          <g>
            <path d={`M ${x} ${y + 34} L ${needleX} ${TOP - 4}`} stroke={C.gold} strokeWidth={4} strokeDasharray="8 8" opacity={regionP} />
            <Pill x={x} y={y} text={text} size={38} color={C.gold} textColor={C.ink} p={pop(f, at("region") + 8, 16)} />
          </g>
        );
      })() : null}

      {/* near / far dripper labels in the probe pot */}
      {dripP > 0 ? (
        <g>
          <Pill x={px - 12} y={BENCH + 75} text="Wetter" anchor="end" size={34} color={WATER_DEEP} p={pop(f, at("dripper") + 4, 16)} />
          <Pill x={px + 12} y={BENCH + 75} text="Drier" anchor="start" size={34} color={C.solid} p={pop(f, at("dripper") + 12, 16)} />
          <path d={`M ${px - pw * 0.26} ${BENCH + 30} L ${px - 60} ${BENCH + 50} M ${px + pw * 0.3} ${BENCH + 30} L ${px + 60} ${BENCH + 50}`} stroke={WATER_DEEP} strokeWidth={4} opacity={dripP} />
        </g>
      ) : null}

      {/* air gap magnifier */}
      {airP > 0.01 ? (
        <g opacity={c01(airP)}>
          <line x1={needleX} y1={TOP + 60} x2={insetX - side * insetR * 0.7} y2={insetY + insetR * 0.7} stroke={C.error} strokeWidth={4} strokeDasharray="8 8" />
          <circle cx={needleX} cy={TOP + 60} r={22} fill="none" stroke={C.error} strokeWidth={4} />
          <g transform={`translate(${insetX} ${insetY}) scale(${airP}) translate(${-insetX} ${-insetY})`}>
            <circle cx={insetX} cy={insetY} r={insetR + 8} fill={C.white} stroke={C.error} strokeWidth={6} />
            <g clipPath="url(#pz-inset)">
              <rect x={insetX - insetR} y={insetY - insetR} width={insetR * 2} height={insetR * 2} fill={C.waterLight} />
              {Array.from({ length: 22 }, (_, j) => {
                const bx = insetX - insetR + random(`ins-x${j}`) * insetR * 2;
                const by = insetY - insetR + random(`ins-y${j}`) * insetR * 2;
                return Math.abs(bx - insetX) < 70 ? null : <path key={j} d={blobPath(bx, by, 26, `ins${j}`)} fill={C.solid} />;
              })}
              {[-40, 0, 40].map((d, j) => (
                <g key={d}>
                  <rect x={insetX + d - 20 - 4 * Math.sin(f / 10 + j)} y={insetY - insetR} width={40 + 8 * Math.sin(f / 10 + j)} height={insetR * 2} rx={18} fill={C.white} />
                  <rect x={insetX + d - 7} y={insetY - insetR} width={14} height={insetR * 1.7} rx={7} fill="#9aa3ad" stroke="#6b7480" strokeWidth={2} />
                </g>
              ))}
            </g>
          </g>
          <Pill x={insetX} y={insetY - insetR - 40} text="Air gap: reads too dry" size={34} color={C.error} p={pop(f, at("airgap") + 14, 16)} />
        </g>
      ) : null}

      {tUneven > 0.01 ? (
        <Pill x={SW / 2} y={BENCH + 170} text="Same zone, other pots: wetter or drier?" size={38} color={C.muted} textColor={C.ink} p={pop(f, at("uneven") + 20, 16)} />
      ) : null}
    </SceneSvg>
  );
};

export default {
  Component,
  doc:
    "One probe in a row of pots (side view, cut-away, drip line with drippers dripping into every pot). Water spreads from each dripper so the near side is wetter. props: {pots?:5, probeAt?: index (default middle), show?:['region','dripper','airgap','uneven'] (default region, dripper, uneven), reading?:'62%' (null or '' hides the probe reading badge), callout?:'The reading only describes here'}. region = glowing sensing zone around the needles + callout; dripper = pulse at the probe pot's dripper + 'Wetter'/'Drier' labels; airgap = magnifier showing air pockets round the needles + 'Air gap: reads too dry' warning; uneven = other pots shift to different wetness and show '?' + 'Same zone, other pots: wetter or drier?'. steps: one per `show` item, in the order given.",
  example: { props: { pots: 5, probeAt: 2, show: ["region", "dripper", "airgap", "uneven"], reading: "62%" }, steps: [20, 70, 120, 170] },
} satisfies SceneDef<P>;
