import React from "react";
import { useCurrentFrame, Easing } from "remotion";
import { C, FONT } from "../theme";
import { useReveal, fadeUp } from "../anim";
import { Heading, type SceneDef } from "./kit";
import { beatAt, ease, lerp, pulse, Icon, NumBadge } from "./_app-shared";

type Step = { label: string; icon?: string; note?: string };
type P = { title?: string; steps: Step[]; loop?: boolean; loopLabel?: string };

const W = 1920;
const TRAVEL = 18; // frames for the token to cross an arrow

// Cubic bezier point.
const bez = (t: number, a: number, b: number, c: number, d: number) => {
  const u = 1 - t;
  return u * u * u * a + 3 * u * u * t * b + 3 * u * t * t * c + t * t * t * d;
};

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const items = (props.steps || []).slice(0, 6);
  const n = items.length;
  const at = items.map((_, i) => beatAt(steps, i, duration, n + (props.loop ? 1 : 0), 12));
  const loopAt = props.loop ? beatAt(steps, n, duration, n + 1, 12) : 1e9;
  const head = useReveal(0, 16);

  const hasNote = items.some((s) => s.note);
  const slot = 1760 / n;
  const cw = Math.min(310, slot - 84);
  const ch = 300;
  const rowY = props.title ? (hasNote ? 380 : 430) : hasNote ? 300 : 400;
  const cx = (i: number) => 80 + slot * i + slot / 2;
  // Card i lights once the token arrives (step 0 lights immediately).
  const lit = (i: number) => (i === 0 ? at[0] : at[i] + TRAVEL - 4);
  let active = -1;
  for (let i = 0; i < n; i++) if (f >= lit(i)) active = i;

  const loopOn = props.loop && f >= loopAt;
  const loopDraw = props.loop ? ease(f, loopAt, loopAt + 24) : 0;
  const bottom = rowY + ch / 2;
  const lx0 = cx(n - 1);
  const lx1 = cx(0);
  const dip = 150;
  const loopD = `M ${lx0} ${bottom + 8} C ${lx0} ${bottom + dip}, ${lx1} ${bottom + dip}, ${lx1} ${bottom + 14}`;

  return (
    <div style={{ position: "absolute", inset: 0, fontFamily: FONT, color: C.ink }}>
      {props.title ? <Heading style={{ position: "absolute", left: 96, top: 48, ...fadeUp(head) }}>{props.title}</Heading> : null}
      <svg width={W} height={988} style={{ position: "absolute", inset: 0 }}>
        {items.slice(1).map((_, k) => {
          const i = k + 1;
          const x0 = cx(i - 1) + cw / 2 + 16;
          const x1 = cx(i) - cw / 2 - 24;
          const appear = ease(f, at[i - 1] - 6, at[i - 1] + 14);
          const done = f >= at[i];
          const t = ease(f, at[i], at[i] + TRAVEL, Easing.inOut(Easing.quad));
          const col = done ? C.forest : C.line;
          return (
            <g key={i} opacity={0.35 + 0.65 * appear}>
              <line x1={x0} y1={rowY} x2={x1} y2={rowY} stroke={col} strokeWidth={8} strokeLinecap="round" strokeDasharray={done ? "0" : "4 18"} strokeDashoffset={-f * 1.2} />
              <path d={`M ${x1 - 6} ${rowY - 18} L ${x1 + 16} ${rowY} L ${x1 - 6} ${rowY + 18} Z`} fill={col} />
              {t > 0 && t < 1 ? (
                <g transform={`translate(${lerp(x0, x1, t)}, ${rowY})`}>
                  <circle r={26} fill={C.gold} opacity={0.3} />
                  <circle r={15} fill={C.gold} stroke={C.white} strokeWidth={4} />
                </g>
              ) : null}
            </g>
          );
        })}
        {props.loop ? (
          <g opacity={loopDraw}>
            <path d={loopD} fill="none" stroke={loopOn ? C.gold : C.line} strokeWidth={7} strokeDasharray="14 14" strokeDashoffset={f * 1.4} />
            <path d={`M ${lx1 - 18} ${bottom + 34} L ${lx1} ${bottom + 10} L ${lx1 + 18} ${bottom + 34} Z`} fill={loopOn ? C.gold : C.line} />
            {loopOn ? (() => {
              const t = ((f - loopAt) % 70) / 70;
              const px = bez(t, lx0, lx0, lx1, lx1);
              const py = bez(t, bottom + 8, bottom + dip, bottom + dip, bottom + 14);
              return (
                <g transform={`translate(${px}, ${py})`}>
                  <circle r={24} fill={C.gold} opacity={0.3} />
                  <circle r={14} fill={C.gold} stroke={C.white} strokeWidth={4} />
                </g>
              );
            })() : null}
          </g>
        ) : null}
      </svg>
      {props.loop && props.loopLabel ? (
        <div style={{ position: "absolute", left: (lx0 + lx1) / 2 - 400, width: 800, top: bottom + dip * 0.75 - 26, textAlign: "center", opacity: loopDraw }}>
          <span style={{ display: "inline-block", padding: "8px 26px", borderRadius: 30, background: C.paper, color: loopOn ? C.forest : C.muted, fontSize: 32, fontWeight: 700 }}>{props.loopLabel}</span>
        </div>
      ) : null}
      {items.map((s, i) => (
        <Card key={i} s={s} i={i} x={cx(i) - cw / 2} y={rowY - ch / 2} w={cw} h={ch} appearAt={at[i] - 10 - (i === 0 ? 0 : 0)} litAt={lit(i)} state={i < active ? "done" : i === active ? "active" : "todo"} f={f} />
      ))}
      {hasNote ? (
        <div style={{ position: "absolute", left: 160, right: 160, top: bottom + (props.loop ? dip + 50 : 70), height: 150 }}>
          {items.map((s, i) => {
            if (!s.note) return null;
            const inP = ease(f, lit(i), lit(i) + 14);
            const outP = i + 1 < n ? ease(f, lit(i + 1), lit(i + 1) + 10) : 0;
            const o = inP * (1 - outP);
            if (o <= 0) return null;
            return (
              <div key={i} style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", gap: 24, opacity: o, transform: `translateY(${(1 - inP) * 20}px)` }}>
                <NumBadge n={i + 1} size={60} bg={C.forest} />
                <span style={{ fontSize: 42, lineHeight: 1.25, color: C.ink }}>{s.note}</span>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
};

function Card({ s, i, x, y, w, h, appearAt, litAt, state, f }: { s: Step; i: number; x: number; y: number; w: number; h: number; appearAt: number; litAt: number; state: "done" | "active" | "todo"; f: number }) {
  const show = ease(f, appearAt, appearAt + 16, Easing.out(Easing.cubic));
  const on = ease(f, litAt, litAt + 12);
  const glow = state === "active" ? pulse(f, 40) : 0;
  const scale = 0.94 + 0.06 * show + (state === "active" ? 0.05 * on + 0.015 * glow : 0);
  const bg = state === "active" ? C.forest : state === "done" ? C.leaf : C.white;
  const fg = state === "active" ? C.white : C.forest;
  const bob = state === "active" ? Math.sin(f / 9) * 5 : 0;
  return (
    <div style={{ position: "absolute", left: x, top: y, width: w, height: h, opacity: 0.3 + 0.7 * show, transform: `scale(${scale})`, borderRadius: 30, background: bg, border: `4px solid ${state === "todo" ? C.line : C.forest}`, boxShadow: state === "active" ? `0 0 ${30 + 30 * glow}px rgba(182,166,111,${0.55 + 0.3 * glow}), 0 18px 40px rgba(24,62,53,0.25)` : "0 10px 24px rgba(24,62,53,0.08)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 18, padding: "0 16px" }}>
      <div style={{ position: "absolute", left: 16, top: 14, fontSize: 26, fontWeight: 800, color: state === "active" ? C.gold : C.muted }}>{i + 1}</div>
      {state === "done" ? (
        <div style={{ position: "absolute", right: -14, top: -14, width: 50, height: 50, borderRadius: 25, background: C.good, display: "grid", placeItems: "center", border: `3px solid ${C.white}` }}>
          <Icon name="check" size={30} color={C.white} stroke={3.2} />
        </div>
      ) : null}
      <div style={{ width: 112, height: 112, borderRadius: 56, background: state === "active" ? "rgba(255,255,255,0.14)" : C.paper, display: "grid", placeItems: "center", transform: `translateY(${bob}px)` }}>
        <Icon name={s.icon || "check"} size={64} color={fg} />
      </div>
      <div style={{ fontSize: w < 240 ? 30 : 36, fontWeight: 700, color: fg, textAlign: "center", lineHeight: 1.15 }}>{s.label}</div>
    </div>
  );
}

export default {
  Component,
  doc: "Horizontal process of 3–6 rounded steps joined by animated arrows; a gold token travels each arrow and the next step glows as it is spoken; finished steps get a green tick. Optional loop-back arrow under the row. props: {title?, steps:[{label (≤14 chars), icon (built-in: draft review apply readback restore shield preserve search check cross water clock lock calendar alert stop power probe plug chart save person question note wrench eye arm sun ruler — or an emoji), note? (≤60 chars, shown under the row while that step is active)}], loop?:boolean, loopLabel?}. steps: one spoken phrase per step, then one for the loop-back (if loop).",
  example: {
    props: {
      title: "Change one target safely",
      steps: [
        { label: "Draft", icon: "draft", note: "Propose 30 → 31 in this browser only" },
        { label: "Review", icon: "review", note: "Check room, setting, old and new value" },
        { label: "Apply", icon: "apply", note: "The only step that sends it to Home Assistant" },
        { label: "Readback", icon: "readback", note: "Read what was actually accepted" },
        { label: "Restore", icon: "restore", note: "Same path back to the starting value" },
      ],
      loop: true,
      loopLabel: "Same four steps to go back",
    },
    steps: [10, 45, 85, 125, 160, 200],
  },
} satisfies SceneDef<P>;
