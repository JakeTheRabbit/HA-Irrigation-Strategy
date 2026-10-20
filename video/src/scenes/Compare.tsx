import React from "react";
import { useCurrentFrame, Easing } from "remotion";
import { C, FONT, SERIF } from "../theme";
import { type SceneDef } from "./kit";
import { beatAt, ease, pulse, Icon, TONE, hasIcon } from "./_app-shared";

type Tone = "good" | "bad" | "warn" | "water" | "neutral" | "ec";
type Col = { title: string; icon?: string; tone?: Tone; items: string[] };
type P = { left: Col; right: Col; verdict?: string; order?: "columns" | "pairs" };

const COL_W = 790;
// Icon names used by other scenes (Analogy etc.) → nearest built-in; anything else unknown → neutral note.
const ALIAS: Record<string, string> = {
  setting: "wrench", settings: "wrench", slider: "wrench", toolbox: "wrench", tools: "wrench",
  probe: "probe", sensor: "probe", pot: "water", zone: "water", dripper: "water", tap: "water", sponge: "water", drop: "water", ec: "water", irrigation: "water",
  app: "chart", graph: "chart", dashboard: "chart", screen: "chart", budget: "chart", thermometer: "chart",
  contact: "person", "phone-contact": "person", phone: "person", handover: "person", people: "person", user: "person",
  list: "note", postit: "note", receipt: "note", plan: "calendar", time: "clock", timer: "clock", warning: "alert", error: "cross", ok: "check", tick: "check",
  lightswitch: "power", switch: "power", bank: "save", fridge: "lock",
};
// Built-in name, alias, emoji/symbol (non-ASCII) as given, else "note" — never prints a raw word.
const iconName = (n: string) => (hasIcon(n) ? n : ALIAS[n.toLowerCase()] ?? (/^[\w\s.,'-]*$/.test(n) ? "note" : n));
const TOP = 40;

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const L = { ...props.left, items: (props.left.items || []).slice(0, 5) };
  const R = { ...props.right, items: (props.right.items || []).slice(0, 5) };
  // Step order → which item appears when.
  const seq: [0 | 1, number][] = [];
  if (props.order === "pairs") {
    for (let i = 0; i < Math.max(L.items.length, R.items.length); i++) {
      if (i < L.items.length) seq.push([0, i]);
      if (i < R.items.length) seq.push([1, i]);
    }
  } else {
    L.items.forEach((_, i) => seq.push([0, i]));
    R.items.forEach((_, i) => seq.push([1, i]));
  }
  const total = seq.length + (props.verdict ? 1 : 0);
  const atOf: number[][] = [[], []];
  seq.forEach(([c, i], k) => (atOf[c][i] = beatAt(steps, k, duration, total, 20)));
  const verdictAt = beatAt(steps, seq.length, duration, total, 20);
  const head = ease(f, 0, 18, Easing.out(Easing.cubic));
  const v = props.verdict ? ease(f, verdictAt, verdictAt + 18, Easing.out(Easing.back(1.4))) : 0;

  return (
    <div style={{ position: "absolute", inset: 0, fontFamily: FONT, color: C.ink }}>
      <Column col={L} x={96} at={atOf[0]} f={f} head={head} fallback="neutral" side={-1} hasVerdict={!!props.verdict} />
      <Column col={R} x={1920 - 96 - COL_W} at={atOf[1]} f={f} head={head} fallback="water" side={1} hasVerdict={!!props.verdict} />
      {/* VS badge */}
      <div style={{ position: "absolute", left: 960 - 56, top: TOP + 40 - 4 * pulse(f, 50), width: 112, height: 112, borderRadius: 56, background: C.white, border: `4px solid ${C.gold}`, display: "grid", placeItems: "center", fontFamily: SERIF, fontSize: 44, color: C.forest, opacity: head, boxShadow: `0 0 ${12 + 18 * pulse(f, 50)}px rgba(182,166,111,0.5)` }}>vs</div>
      {props.verdict ? (
        <div style={{ position: "absolute", left: 160, right: 160, top: 810, minHeight: 130, borderRadius: 30, background: C.forest, color: C.white, display: "flex", alignItems: "center", gap: 30, padding: "20px 48px", opacity: Math.min(1, v), transform: `translateY(${(1 - v) * 50}px) scale(${0.96 + 0.04 * v})`, boxShadow: `0 20px 40px rgba(24,62,53,${0.2 + 0.1 * pulse(f, 60)})` }}>
          <div style={{ width: 80, height: 80, borderRadius: 40, background: C.gold, display: "grid", placeItems: "center", flexShrink: 0 }}>
            <Icon name="check" size={48} color={C.white} stroke={3.2} />
          </div>
          <div style={{ fontSize: 44, fontWeight: 700, lineHeight: 1.2 }}>{props.verdict}</div>
        </div>
      ) : null}
    </div>
  );
};

function Column({ col, x, at, f, head, fallback, side, hasVerdict }: { hasVerdict: boolean; col: Col; x: number; at: number[]; f: number; head: number; fallback: Tone; side: number }) {
  const tone = TONE[col.tone || fallback];
  const bullet = col.tone === "good" ? "check" : col.tone === "bad" ? "cross" : null;
  return (
    <div style={{ position: "absolute", left: x, top: TOP, width: COL_W, opacity: head, transform: `translateX(${(1 - head) * 60 * side}px)` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 26, padding: "26px 36px", borderRadius: "30px 30px 0 0", background: tone.fg, color: C.white }}>
        <div style={{ width: 92, height: 92, borderRadius: 46, background: "rgba(255,255,255,0.18)", display: "grid", placeItems: "center", transform: `translateY(${Math.sin(f / 18 + side) * 4}px)` }}>
          <Icon name={iconName(col.icon || (bullet ?? "note"))} size={56} color={C.white} />
        </div>
        <div style={{ fontFamily: SERIF, fontSize: 56, lineHeight: 1.05 }}>{col.title}</div>
      </div>
      <div style={{ background: C.white, borderRadius: "0 0 30px 30px", border: `3px solid ${tone.fg}`, borderTop: "none", padding: "22px 30px 30px", minHeight: hasVerdict ? 500 : 700, display: "flex", flexDirection: "column", gap: 16 }}>
        {col.items.map((t, i) => {
          const p = ease(f, at[i], at[i] + 16, Easing.out(Easing.cubic));
          const fresh = 1 - ease(f, at[i] + 10, at[i] + 60);
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 22, padding: "16px 20px", borderRadius: 18, background: fresh > 0 && p > 0 ? tone.bg : "transparent", opacity: p, transform: `translateX(${(1 - p) * 40 * side}px)` }}>
              <div style={{ width: 54, height: 54, borderRadius: 27, background: tone.bg, border: `3px solid ${tone.fg}`, display: "grid", placeItems: "center", flexShrink: 0 }}>
                {bullet ? <Icon name={bullet} size={32} color={tone.fg} stroke={3.2} /> : <div style={{ width: 16, height: 16, borderRadius: 8, background: tone.fg }} />}
              </div>
              <div style={{ fontSize: 38, lineHeight: 1.2 }}>{t}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default {
  Component,
  doc: "Two columns side by side (Measured vs Reference, Budget vs Statement, Do vs Don't, Saved vs Draft) with a pulsing 'vs' badge; items slide in as spoken; optional verdict banner lands last. props: {left:{title, icon? (built-in name or emoji; other scenes' icon names like setting/probe/pot/app/graph/zone map to the nearest built-in, any other unknown word shows a neutral note icon), tone?:'good'|'bad'|'warn'|'water'|'neutral'|'ec', items:[string ≤40 chars] (max 5)}, right:{same}, verdict? (≤70 chars), order?:'columns'(default: all left, then all right)|'pairs'(left1,right1,left2…)}. tone good/bad gives ✓/× bullets. steps: one per item in that order, then one for the verdict.",
  example: {
    props: {
      left: { title: "Budget = targets", icon: "note", tone: "neutral", items: ["What you planned", "Saved at a known moment", "Can change next month"] },
      right: { title: "Statement = History", icon: "chart", tone: "water", items: ["What the probes recorded", "Can't be edited", "Gaps stay empty, not zero"] },
      verdict: "Compare matched periods, and date every reference",
      order: "pairs",
    },
    steps: [15, 40, 70, 95, 125, 150, 185],
  },
} satisfies SceneDef<P>;
