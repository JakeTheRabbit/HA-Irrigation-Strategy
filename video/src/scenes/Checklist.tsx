import React from "react";
import { useCurrentFrame, Easing } from "remotion";
import { C, FONT, SERIF } from "../theme";
import { usePop } from "../anim";
import { type SceneDef } from "./kit";
import { beatAt, ease, lerp, pulse, Icon, Cursor } from "./_app-shared";

type State = "ok" | "unknown" | "fail";
type Item = { text: string; state?: State };
type P = { title: string; items: Item[] };

const LOOK: Record<State, { col: string; tint: string; label: string; icon: string }> = {
  ok: { col: C.good, tint: "#e3efdf", label: "Confirmed", icon: "check" },
  unknown: { col: C.warn, tint: "#f8ead3", label: "Unknown", icon: "question" },
  fail: { col: C.error, tint: "#f6e1dc", label: "Failed", icon: "cross" },
};

const BOARD = { x: 150, y: 34, w: 1060, h: 920 };

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const items = (props.items || []).slice(0, 7);
  const n = items.length;
  const at = items.map((_, i) => beatAt(steps, i, duration, n, 18));
  const pop = usePop(0);
  const listTop = BOARD.y + 230;
  // Rows share the paper below the title (paper ends 34 px above the board bottom).
  const rowH = Math.min(108, (BOARD.y + BOARD.h - 50 - listTop) / Math.max(n, 1));
  // One font size for all rows: the largest (≤38) at which every item's wrapped text fits its row.
  const fits = (fs: number) => items.every((it) => {
    const avail = BOARD.w - 180 - 140 - ((it.state || "ok") !== "ok" ? 140 : 0);
    const lines = Math.ceil((it.text.length * fs * 0.5) / avail);
    return lines * fs * 1.15 <= rowH - 12;
  });
  let fontSize = 38;
  while (fontSize > 24 && !fits(fontSize)) fontSize--;
  const rowY = (i: number) => listTop + i * rowH;
  const boxX = BOARD.x + 90;

  let cur = -1;
  for (let i = 0; i < n; i++) if (f >= at[i]) cur = i;
  // Pen/cursor: hovers near the next box, slides to each box as it is ticked.
  const target = (i: number) => ({ x: boxX + 44, y: rowY(i) + rowH / 2 + 4 });
  let px = BOARD.x + BOARD.w - 160;
  let py = listTop - 40;
  if (cur >= 0) {
    const from = cur > 0 ? target(cur - 1) : { x: px, y: py };
    const t = ease(f, at[cur] - 10, at[cur] + 4);
    const to = target(cur);
    px = lerp(from.x, to.x, t);
    py = lerp(from.y, to.y, t);
  }
  px += 5 * Math.sin(f / 17);
  py += 4 * Math.cos(f / 21);

  const states = Array.from(new Set(items.map((it) => it.state || "ok"))) as State[];
  const order: State[] = (["ok", "unknown", "fail"] as State[]).filter((s) => states.includes(s));

  return (
    <div style={{ position: "absolute", inset: 0, fontFamily: FONT, color: C.ink }}>
      <div style={{ position: "absolute", left: BOARD.x, top: BOARD.y, width: BOARD.w, height: BOARD.h, transform: `translateY(${(1 - pop) * 60}px) rotate(${-0.6 + 0.3 * Math.sin(f / 80)}deg)`, opacity: pop }}>
        {/* board */}
        <div style={{ position: "absolute", inset: 0, borderRadius: 40, background: C.solid, boxShadow: "0 30px 60px rgba(60,40,20,0.28)" }} />
        {/* paper */}
        <div style={{ position: "absolute", left: 34, right: 34, top: 70, bottom: 34, borderRadius: 14, background: C.white, boxShadow: "0 4px 10px rgba(0,0,0,0.12)" }} />
        {/* clip */}
        <div style={{ position: "absolute", left: BOARD.w / 2 - 150, top: -18, width: 300, height: 100, borderRadius: 22, background: "linear-gradient(#cfd4cc, #9da49b)", border: "3px solid #7f877d", boxShadow: "0 8px 14px rgba(0,0,0,0.2)" }}>
          <div style={{ position: "absolute", left: 120, top: 18, width: 60, height: 30, borderRadius: 15, background: C.paper, border: "3px solid #7f877d" }} />
        </div>
        <div style={{ position: "absolute", left: 90, right: 90, top: 120, fontFamily: SERIF, fontSize: Math.min(58, 1700 / Math.max(1, props.title.length)), color: C.forest, lineHeight: 1.4, whiteSpace: "nowrap" }}>{props.title}</div>
        <div style={{ position: "absolute", left: 90, right: 90, top: 205, height: 4, background: C.gold, borderRadius: 2 }} />
      </div>
      {items.map((it, i) => (
        <Row key={i} it={it} i={i} at={at[i]} x={boxX} y={rowY(i)} h={rowH} w={BOARD.w - 180} f={f} pop={pop} fs={fontSize} />
      ))}
      <Cursor x={px} y={py} press={cur >= 0 ? ease(f, at[cur] + 2, at[cur] + 16) : 0} opacity={pop} />
      {/* tally */}
      <div style={{ position: "absolute", left: 1320, top: 200, width: 460, display: "flex", flexDirection: "column", gap: 34 }}>
        {order.map((s) => {
          const count = items.filter((it, i) => (it.state || "ok") === s && f >= at[i]).length;
          const lastAt = Math.max(-999, ...items.map((it, i) => ((it.state || "ok") === s && f >= at[i] ? at[i] : -999)));
          const bump = lastAt > -999 ? 1 - ease(f, lastAt, lastAt + 14) : 0;
          const L = LOOK[s];
          return (
            <div key={s} style={{ display: "flex", alignItems: "center", gap: 28, padding: "26px 34px", borderRadius: 28, background: count ? L.tint : C.white, border: `3px solid ${count ? L.col : C.line}`, opacity: pop }}>
              <div style={{ width: 84, height: 84, borderRadius: 42, background: count ? L.col : C.line, display: "grid", placeItems: "center", transform: `scale(${1 + 0.18 * bump})` }}>
                <Icon name={L.icon} size={50} color={C.white} stroke={3} />
              </div>
              <div>
                <div style={{ fontSize: 76, fontWeight: 800, lineHeight: 1, color: count ? L.col : C.muted, transform: `scale(${1 + 0.15 * bump})`, transformOrigin: "left center" }}>{count}</div>
                <div style={{ fontSize: 32, fontWeight: 600, color: C.muted }}>{L.label}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

function Row({ it, i, at, x, y, h, w, f, pop, fs = 38 }: { it: Item; i: number; at: number; x: number; y: number; h: number; w: number; f: number; pop: number; fs?: number }) {
  const s = it.state || "ok";
  const L = LOOK[s];
  const mark = ease(f, at, at + 14, Easing.out(Easing.cubic));
  const tint = ease(f, at + 4, at + 18);
  const isNext = f < at && f >= at - 30;
  const bx = Math.min(64, h - 20);
  const by = (h - bx) / 2;
  return (
    <div style={{ position: "absolute", left: x - 20, top: y, width: w, height: h, opacity: pop * (0.45 + 0.55 * ease(f, at - 24, at)) }}>
      <div style={{ position: "absolute", inset: "6px 0", borderRadius: 18, background: L.tint, opacity: tint * 0.9 }} />
      <svg width={bx + 8} height={bx + 8} style={{ position: "absolute", left: 16, top: by - 4 }}>
        <rect x={4} y={4} width={bx} height={bx} rx={12} fill={C.white} stroke={mark > 0 ? L.col : isNext ? C.gold : C.muted} strokeWidth={isNext ? 4 + 2 * pulse(f, 20) : 4} />
        {s === "ok" ? <path d="M18 38 L31 51 L56 22" fill="none" stroke={L.col} strokeWidth={9} strokeLinecap="round" strokeLinejoin="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - mark} /> : null}
        {s === "fail" ? (
          <g stroke={L.col} strokeWidth={9} strokeLinecap="round">
            <path d="M20 20 L52 52" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - Math.min(1, mark * 2)} />
            <path d="M52 20 L20 52" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - Math.max(0, mark * 2 - 1)} />
          </g>
        ) : null}
        {s === "unknown" ? (
          <text x={36} y={56} textAnchor="middle" fontSize={54} fontWeight={800} fill={L.col} fontFamily={FONT} opacity={mark} transform={`translate(36 36) scale(${0.4 + 0.6 * mark}) translate(-36 -36)`}>?</text>
        ) : null}
      </svg>
      <div style={{ position: "absolute", left: 120, right: 20, top: 0, height: h, display: "flex", alignItems: "center", fontSize: fs, lineHeight: 1.15, color: C.ink, fontWeight: mark > 0.5 ? 600 : 400 }}>
        <span>{it.text}</span>
        {s !== "ok" && mark > 0 ? (
          <span style={{ marginLeft: "auto", paddingLeft: 20, fontSize: Math.min(30, fs), fontWeight: 700, color: L.col, opacity: mark, whiteSpace: "nowrap" }}>{L.label.toLowerCase()}</span>
        ) : null}
      </div>
    </div>
  );
}

export default {
  Component,
  doc: "Clipboard checklist; each item is ticked as it is spoken (green ✓), or marked amber ? (state 'unknown') or red × (state 'fail'); a tally on the right counts confirmed / unknown / failed. props: {title, items:[{text, state?:'ok'|'unknown'|'fail'}]} (max 7; rows and font auto-shrink so long items wrap and still fit the clipboard). The tally counts each item the moment its mark appears. steps: one spoken phrase per item.",
  example: {
    props: {
      title: "Morning preflight · Room A, Zone 1",
      items: [
        { text: "Controller reported 1 min ago" },
        { text: "Probe reported 2 min ago" },
        { text: "Phase P1, reason shown" },
        { text: "Pump state", state: "unknown" },
        { text: "Tank level and low float agree", state: "fail" },
        { text: "Delivery labelled estimated" },
      ],
    },
    steps: [20, 50, 80, 115, 150, 185],
  },
} satisfies SceneDef<P>;
