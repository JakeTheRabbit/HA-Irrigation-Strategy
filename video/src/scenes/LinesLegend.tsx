import React from "react";
import { useCurrentFrame, Easing } from "remotion";
import { C, FONT, SERIF } from "../theme";
import { usePop } from "../anim";
import { type SceneDef } from "./kit";
import { beatAt, ease, lerp, pulse, Icon, Cursor } from "./_app-shared";

type P = { from: number; to: number; unit?: string; showReview?: boolean; setting?: string; room?: string };

const GREY = "#8a948c";
const GREEN = "#3f9a5a";
// Chart card and plot area (stage pixels).
const CARD = { x: 96, y: 30, w: 1110, h: 920 };
const PL = { x: CARD.x + 120, y: CARD.y + 150, w: CARD.w - 170, h: CARD.h - 260 };
const PANEL = { x: 1250, w: 574 };

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const unit = props.unit ?? "%";
  const review = props.showReview !== false;
  const count = review ? 5 : 2;
  const at = Array.from({ length: count }, (_, i) => beatAt(steps, i, duration, count, 14));
  const pop = usePop(0);
  const lo = Math.min(props.from, props.to) - 6;
  const hi = Math.max(props.from, props.to) + 10;
  const yOf = (v: number) => PL.y + PL.h - ((v - lo) / (hi - lo)) * PL.h;
  const xOf = (t: number) => PL.x + t * PL.w;

  // Measured trace: dry-downs and shots, fixed history (drawn in once at the start).
  const pts: [number, number][] = [];
  for (let i = 0; i <= 120; i++) {
    const t = i / 120;
    const cyc = (t * 3.2) % 1;
    const v = props.from + 2 + 7 * Math.pow(1 - cyc, 1.4) + 0.4 * Math.sin(i * 1.7);
    pts.push([xOf(t), yOf(v)]);
  }
  const traceD = "M " + pts.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join(" L ");
  const traceDraw = ease(f, 0, 30, Easing.out(Easing.cubic));
  const last = pts[pts.length - 1];

  const drag = ease(f, at[1] + 10, at[1] + 34);
  const draftVal = lerp(props.from, props.to, drag);
  const draftOn = ease(f, at[1], at[1] + 10);
  const readAt = review ? at[4] : 1e9;
  const merge = review ? ease(f, readAt + 6, readAt + 30) : 0;
  const savedVal = lerp(props.from, props.to, merge);
  const draftOpacity = draftOn * (1 - merge);
  const labels0 = ease(f, at[0], at[0] + 16, Easing.out(Easing.back(1.6)));
  const labels1 = ease(f, at[1] + 34, at[1] + 50, Easing.out(Easing.back(1.6)));

  // Cursor path: rest → draft handle (drag) → Apply button.
  const handle = { x: xOf(1) - 4, y: yOf(draftVal) };
  const applyBtn = { x: PANEL.x + PANEL.w - 150, y: 820 };
  let cx = PL.x + PL.w * 0.75;
  let cy = PL.y + PL.h * 0.85;
  const toHandle = ease(f, at[1] - 4, at[1] + 10);
  cx = lerp(cx, handle.x + 6, toHandle);
  cy = lerp(cy, handle.y + 6, toHandle);
  if (review) {
    const toApply = ease(f, at[3] - 18, at[3]);
    cx = lerp(cx, applyBtn.x, toApply);
    cy = lerp(cy, applyBtn.y, toApply);
    const away = ease(f, at[3] + 16, at[3] + 40);
    cx += 130 * away;
    cy -= 80 * away;
  }
  cx += 4 * Math.sin(f / 19);
  cy += 3 * Math.cos(f / 23);
  const press = drag > 0 && drag < 1 ? 0.5 : review ? ease(f, at[3], at[3] + 14) : 0;

  const ticks: number[] = [];
  for (let v = Math.ceil(lo / 2) * 2; v <= hi; v += 2) ticks.push(v);
  const hours = ["06:00", "09:00", "12:00", "15:00", "18:00"];

  return (
    <div style={{ position: "absolute", inset: 0, fontFamily: FONT, color: C.ink }}>
      <div style={{ position: "absolute", left: CARD.x, top: CARD.y, width: CARD.w, height: CARD.h, borderRadius: 30, background: C.white, border: `2px solid ${C.line}`, boxShadow: "0 20px 50px rgba(24,62,53,0.1)", opacity: pop, transform: `scale(${0.96 + 0.04 * pop})` }}>
        <div style={{ position: "absolute", left: 44, top: 32, fontFamily: SERIF, fontSize: 48, color: C.forest }}>Current day · {props.setting || "Rescue floor"}</div>
        <div style={{ position: "absolute", left: 46, top: 96, fontSize: 28, color: C.muted }}>VWC {unit}</div>
      </div>
      <svg width={1920} height={988} style={{ position: "absolute", inset: 0, opacity: pop }}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={PL.x} x2={PL.x + PL.w} y1={yOf(v)} y2={yOf(v)} stroke={C.line} strokeWidth={1.5} />
            <text x={PL.x - 20} y={yOf(v) + 10} textAnchor="end" fontSize={28} fill={C.muted} fontFamily={FONT}>{v}</text>
          </g>
        ))}
        {hours.map((h, i) => (
          <text key={h} x={xOf(i / (hours.length - 1))} y={PL.y + PL.h + 50} textAnchor="middle" fontSize={28} fill={C.muted} fontFamily={FONT}>{h}</text>
        ))}
        {/* measured trace */}
        <path d={traceD} fill="none" stroke={C.water} strokeWidth={6} strokeLinejoin="round" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - traceDraw} />
        <circle cx={last[0]} cy={last[1]} r={10 + 8 * pulse(f, 30)} fill={C.water} opacity={0.25 * traceDraw} />
        <circle cx={last[0]} cy={last[1]} r={9} fill={C.water} opacity={traceDraw} />
        {/* saved reference */}
        <line x1={PL.x} x2={PL.x + PL.w} y1={yOf(savedVal)} y2={yOf(savedVal)} stroke={GREY} strokeWidth={6} strokeDasharray="22 14" opacity={traceDraw} />
        {/* draft reference */}
        <g opacity={draftOpacity}>
          <line x1={PL.x} x2={PL.x + PL.w} y1={yOf(draftVal)} y2={yOf(draftVal)} stroke={GREEN} strokeWidth={6} strokeDasharray="22 14" strokeDashoffset={-f * 0.8} />
          <circle cx={handle.x} cy={handle.y} r={16 + 3 * pulse(f, 24)} fill={C.white} stroke={GREEN} strokeWidth={6} />
        </g>
      </svg>
      {/* line labels */}
      <Label x={PL.x + 40} y={yOf(savedVal) + 26} color={GREY} p={labels0} up={false} text={`Saved reference · ${fmt(savedVal)}${unit}`} />
      <Label x={xOf(0.62)} y={yOf(Math.max(draftVal, props.from) ) - 96} color={GREEN} p={labels1 * (1 - merge)} up text={`Draft · ${fmt(draftVal)}${unit}`} />
      <Label x={xOf(0.35)} y={yOf(props.from + 10.6) - 6} color={C.water} p={labels0} up text="Measured · history, never moves" />
      {/* right panel */}
      <div style={{ position: "absolute", left: PANEL.x, top: review ? 30 : 200, width: PANEL.w, opacity: pop }}>
        <Legend f={f} at={at} />
      </div>
      {review ? <Review f={f} at={at} from={props.from} to={props.to} unit={unit} setting={props.setting || "Rescue floor"} room={props.room || "Room A"} /> : null}
      <Cursor x={cx} y={cy} press={press} opacity={ease(f, 6, 20)} />
    </div>
  );
};

const fmt = (v: number) => (Math.round(v * 10) / 10).toString();

function Label({ x, y, color, p, up, text }: { x: number; y: number; color: string; p: number; up: boolean; text: string }) {
  return (
    <div style={{ position: "absolute", left: x, top: y, opacity: Math.min(1, p), transform: `scale(${0.6 + 0.4 * p})`, transformOrigin: up ? "30px 100%" : "30px 0" }}>
      {!up ? <div style={{ width: 4, height: 18, marginLeft: 28, background: color }} /> : null}
      <div style={{ display: "inline-block", padding: "10px 22px", borderRadius: 16, background: color, color: C.white, fontSize: 32, fontWeight: 700, whiteSpace: "nowrap", boxShadow: "0 8px 18px rgba(0,0,0,0.18)" }}>{text}</div>
      {up ? <div style={{ width: 4, height: 34, marginLeft: 28, background: color }} /> : null}
    </div>
  );
}

function Legend({ f, at }: { f: number; at: number[] }) {
  const rows = [
    { col: GREY, dash: true, name: "Saved reference", sub: "target stored now", at: at[0] },
    { col: GREEN, dash: true, name: "Draft", sub: "your proposal, this browser", at: at[1] },
    { col: C.water, dash: false, name: "Measured", sub: "what the probes recorded", at: at[0] },
  ];
  return (
    <div style={{ background: C.white, borderRadius: 26, border: `2px solid ${C.line}`, padding: "26px 32px", display: "flex", flexDirection: "column", gap: 18 }}>
      {rows.map((r) => {
        const p = ease(f, r.at, r.at + 14);
        return (
          <div key={r.name} style={{ display: "flex", alignItems: "center", gap: 22, opacity: 0.3 + 0.7 * p }}>
            <svg width={80} height={20}><line x1={4} x2={76} y1={10} y2={10} stroke={r.col} strokeWidth={7} strokeDasharray={r.dash ? "16 10" : "0"} strokeLinecap="round" /></svg>
            <div>
              <div style={{ fontSize: 34, fontWeight: 700, color: C.ink }}>{r.name}</div>
              <div style={{ fontSize: 28, color: C.muted }}>{r.sub}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Review({ f, at, from, to, unit, setting, room }: { f: number; at: number[]; from: number; to: number; unit: string; setting: string; room: string }) {
  const show = ease(f, at[2], at[2] + 18, Easing.out(Easing.cubic));
  const applying = f >= at[3] && f < at[4];
  const done = ease(f, at[4], at[4] + 14, Easing.out(Easing.back(1.8)));
  const pressed = f >= at[3];
  return (
    <div style={{ position: "absolute", left: PANEL.x, top: 420, width: PANEL.w, height: 530, opacity: show, transform: `translateY(${(1 - show) * 60}px)`, background: C.white, borderRadius: 26, border: `3px solid ${C.forest}`, boxShadow: "0 24px 50px rgba(24,62,53,0.2)", padding: "28px 34px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <Icon name="review" size={46} />
        <div style={{ fontSize: 40, fontWeight: 800, color: C.forest }}>Review changes</div>
      </div>
      <div style={{ marginTop: 14, display: "inline-block", padding: "6px 18px", borderRadius: 20, background: C.leaf, fontSize: 28, fontWeight: 700, color: C.forest }}>{room}</div>
      <div style={{ marginTop: 22, padding: "18px 22px", borderRadius: 18, background: C.paper, border: `2px solid ${C.line}` }}>
        <div style={{ fontSize: 30, color: C.muted }}>{setting}</div>
        <div style={{ fontSize: 50, fontWeight: 800, color: C.ink, marginTop: 4 }}>
          <span style={{ color: GREY }}>{from}{unit}</span>
          <span style={{ margin: "0 18px", color: C.gold }}>→</span>
          <span style={{ color: GREEN }}>{to}{unit}</span>
        </div>
      </div>
      <div style={{ position: "absolute", left: 34, right: 34, bottom: 30, height: 96 }}>
        {done > 0.01 ? (
          <div style={{ position: "absolute", inset: 0, borderRadius: 20, background: C.good, color: C.white, display: "flex", alignItems: "center", justifyContent: "center", gap: 18, fontSize: 38, fontWeight: 800, transform: `scale(${0.8 + 0.2 * Math.min(1.1, done)})`, boxShadow: `0 0 ${16 + 16 * pulse(f, 40)}px rgba(63,122,79,0.5)` }}>
            <Icon name="check" size={46} color={C.white} stroke={3.4} /> Readback {to}{unit}
          </div>
        ) : (
          <div style={{ display: "flex", gap: 18, height: "100%" }}>
            {applying ? null : <div style={{ flex: 1, borderRadius: 20, border: `3px solid ${C.line}`, display: "grid", placeItems: "center", fontSize: 28, fontWeight: 700, color: C.muted }}>Back to editing</div>}
            <div style={{ flex: 1.25, borderRadius: 20, background: pressed ? C.ink : C.forest, color: C.white, display: "flex", alignItems: "center", justifyContent: "center", gap: 12, fontSize: 32, fontWeight: 800 }}>
              {applying ? (
                <>
                  <svg width={34} height={34} viewBox="0 0 34 34" style={{ transform: `rotate(${f * 12}deg)` }}><circle cx={17} cy={17} r={13} fill="none" stroke={C.gold} strokeWidth={5} strokeDasharray="50 40" /></svg>
                  Applying and verifying
                </>
              ) : "Apply 1 change"}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default {
  Component,
  doc: "Teaches the three chart lines: saved reference (grey dashed), draft (green dashed, dragged by one step) and the measured trace (solid blue, never moves); labels pop with pointers; then a Review changes card (old → new), Apply 1 change → 'Applying and verifying' → green 'Readback ✓', and the saved line moves to the new value. props: {from:30, to:31, unit?:'%', showReview?:true, setting?:'Rescue floor', room?:'Room A'}. steps: [saved+measured labels, draft drag, review card, apply click, readback] (only the first two if showReview:false).",
  example: { props: { from: 30, to: 31, unit: "%", showReview: true, setting: "Rescue floor", room: "Room A" }, steps: [20, 60, 115, 160, 200] },
} satisfies SceneDef<P>;
