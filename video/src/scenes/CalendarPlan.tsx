import React from "react";
import { useCurrentFrame, Easing } from "remotion";
import { C, FONT, SERIF } from "../theme";
import { usePop } from "../anim";
import { type SceneDef } from "./kit";
import { beatAt, ease, lerp, pulse, Icon, Cursor } from "./_app-shared";

type Stage = "assign" | "save" | "arm" | "active";
type Block = { days: [number, number]; label: string };
type Zone = { name: string; start?: number };
type P = { zone?: string; zones?: Zone[]; days?: number; blocks: Block[]; stages?: Stage[]; armAt?: string; lightsOn?: string };

const COLORS = [C.plant, C.ec, C.water, C.gold, C.solid];
const GRID = { x: 96, y: 190, cols: 7, w: 1240 };
const SIDE = { x: 1400, w: 424 };

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const pop = usePop(0);
  const days = Math.max(7, Math.min(21, props.days ?? 14));
  const rows = Math.ceil(days / 7);
  const gap = 10;
  const cw = (GRID.w - gap * 6) / 7;
  const chh = rows === 3 ? 140 : 190;
  const cellX = (d: number) => GRID.x + ((d - 1) % 7) * (cw + gap);
  const cellY = (d: number) => GRID.y + Math.floor((d - 1) / 7) * (chh + gap);
  const gridBottom = GRID.y + rows * (chh + gap) - gap;

  const stages: Stage[] = props.stages && props.stages.length ? props.stages : ["assign", "save", "arm", "active"];
  const stAt: Partial<Record<Stage, number>> = {};
  stages.forEach((s, i) => (stAt[s] = beatAt(steps, i, duration, stages.length, 10)));
  const has = (s: Stage) => stAt[s] !== undefined;
  const reached = (s: Stage) => has(s) && f >= (stAt[s] as number);

  // Assignment: blocks are dragged one after another.
  const blocks = (props.blocks || []).slice(0, 5);
  // Zones share the same profile blocks; each zone gets its own lane, shifted to start on its `start` day.
  const zones: Zone[] = props.zones?.length ? props.zones.slice(0, 3) : [{ name: props.zone || "Zone 1" }];
  const nz = zones.length;
  const off = (z: number) => Math.max(0, (zones[z].start ?? 1) - 1);
  const laneH = (chh - 64 - 6 * (nz - 1)) / nz;
  const aStart = has("assign") ? (stAt.assign as number) : -999;
  const aNext = has("save") ? (stAt.save as number) : has("arm") ? (stAt.arm as number) : aStart + 50 * blocks.length + 20;
  const per = has("assign") ? Math.max(24, Math.min(60, (aNext - aStart - 10) / Math.max(1, blocks.length))) : 0;
  const bStart = (j: number) => aStart + j * per;
  const fillP = (j: number) => (has("assign") ? ease(f, bStart(j) + per * 0.3, bStart(j) + per * 0.95) : 1);

  // Cursor: picks card j in the tray, drags across its days.
  const cardY = (j: number) => 250 + j * 96;
  let cx = SIDE.x + SIDE.w - 60;
  let cy = 640;
  let press = 0;
  for (let j = 0; j < blocks.length && has("assign"); j++) {
    const t0 = bStart(j);
    if (f < t0) break;
    const [d0, d1] = clampDays(blocks[j].days, days);
    const pick = { x: SIDE.x + 80, y: cardY(j) + 40 };
    const start = { x: cellX(d0) + 40, y: cellY(d0) + chh / 2 };
    const end = { x: cellX(d1) + cw - 40, y: cellY(d1) + chh / 2 };
    const a = ease(f, t0, t0 + per * 0.15);
    const b = ease(f, t0 + per * 0.15, t0 + per * 0.3);
    const c = fillP(j);
    const px = lerp(lerp(cx, pick.x, a), start.x, b);
    const py = lerp(lerp(cy, pick.y, a), start.y, b);
    cx = c > 0 ? lerp(start.x, end.x, c) : px;
    cy = c > 0 ? lerp(start.y, end.y, c) : py;
    press = b > 0 && c < 1 ? 0.5 : 0;
  }
  const saveBtn = { x: GRID.x + 200, y: 830 };
  const armBtn = { x: GRID.x + 620, y: 830 };
  for (const [s, btn] of [["save", saveBtn], ["arm", armBtn]] as [Stage, { x: number; y: number }][]) {
    if (!has(s)) continue;
    const t = stAt[s] as number;
    const m = ease(f, t - 16, t);
    cx = lerp(cx, btn.x, m);
    cy = lerp(cy, btn.y, m);
    if (f >= t && f < t + 16) press = ease(f, t, t + 16);
  }
  if (has("arm")) {
    const away = ease(f, (stAt.arm as number) + 18, (stAt.arm as number) + 40);
    cx = lerp(cx, GRID.x + GRID.w - 120, away);
    cy = lerp(cy, 640, away);
  }
  cx += 4 * Math.sin(f / 19);
  cy += 3 * Math.cos(f / 23);

  const status = reached("active") ? "Active" : reached("arm") ? "Armed" : reached("save") ? "Draft · saved" : "Draft";
  const statusCol = reached("active") ? C.good : reached("arm") ? C.gold : C.muted;
  const activeP = has("active") ? ease(f, stAt.active as number, (stAt.active as number) + 20) : 0;

  const armH = hoursBetween(props.armAt || "15:00", props.lightsOn || "06:00");
  const armHour = Number((props.armAt || "15:00").split(":")[0]) || 0;

  return (
    <div style={{ position: "absolute", inset: 0, fontFamily: FONT, color: C.ink, opacity: pop }}>
      {/* header */}
      <div style={{ position: "absolute", left: GRID.x, top: 40, display: "flex", alignItems: "center", gap: 28 }}>
        <Icon name="calendar" size={60} />
        <div style={{ fontFamily: SERIF, fontSize: 56, color: C.forest }}>{zones.map((z) => z.name).join(" + ")} · grow plan</div>
        <div style={{ padding: "10px 26px", borderRadius: 30, background: statusCol, color: C.white, fontSize: 32, fontWeight: 800, boxShadow: reached("active") ? `0 0 ${10 + 14 * pulse(f, 40)}px rgba(63,122,79,0.6)` : "none" }}>{status}</div>
      </div>
      {/* grid */}
      <div style={{ position: "absolute", left: GRID.x - 14, top: GRID.y - 14, width: GRID.w + 28, height: gridBottom - GRID.y + 28, borderRadius: 26, border: `4px solid ${activeP > 0 ? C.good : "transparent"}`, boxShadow: activeP > 0 ? `0 0 ${20 + 20 * pulse(f, 45)}px rgba(63,122,79,${0.35 * activeP})` : "none" }} />
      {Array.from({ length: days }, (_, k) => k + 1).map((d) => {
        const covered = blocks.findIndex((b) => zones.some((_, z) => {
          const [a, e] = clampDays([b.days[0] + off(z), b.days[1] + off(z)], days);
          return d >= a && d <= e;
        }));
        const today = activeP > 0 && d === 1;
        return (
          <div key={d} style={{ position: "absolute", left: cellX(d), top: cellY(d), width: cw, height: chh, borderRadius: 18, background: C.white, border: `2px ${covered < 0 && reached("save") ? "dashed" : "solid"} ${covered < 0 && reached("save") ? C.error : C.line}` }}>
            <div style={{ position: "absolute", left: 16, top: 10, fontSize: 30, fontWeight: 700, color: C.muted }}>Day {d}</div>
            {today ? <div style={{ position: "absolute", right: 12, top: 12, width: 22, height: 22, borderRadius: 11, background: C.good, boxShadow: `0 0 0 ${6 + 6 * pulse(f, 30)}px rgba(63,122,79,0.25)` }} /> : null}
          </div>
        );
      })}
      {/* block fills, one segment per row */}
      {blocks.flatMap((b, j) => zones.map((zn, z) => {
        const [d0, d1] = clampDays([b.days[0] + off(z), b.days[1] + off(z)], days);
        const p = fillP(j);
        if (p <= 0 || b.days[0] + off(z) > days) return null;
        const label = nz > 1 ? `${zn.name} · ${b.label}` : b.label;
        const total = d1 - d0 + 1;
        const upTo = d0 - 1 + total * p; // fractional day reached
        const segs: React.ReactNode[] = [];
        for (let r = Math.floor((d0 - 1) / 7); r <= Math.floor((d1 - 1) / 7); r++) {
          const s = Math.max(d0, r * 7 + 1);
          const e = Math.min(d1, r * 7 + 7);
          const eFrac = Math.min(e, upTo);
          if (eFrac <= s - 1) continue;
          const x0 = cellX(s) + 6;
          const x1 = cellX(Math.ceil(eFrac)) + cw * (eFrac - Math.ceil(eFrac) + 1) - 6;
          segs.push(
            <div key={r} style={{ position: "absolute", left: x0, top: cellY(s) + 52 + z * (laneH + 6), width: Math.max(0, x1 - x0), height: laneH, borderRadius: nz > 1 ? 10 : 14, background: COLORS[j % COLORS.length], display: "flex", alignItems: "center", paddingLeft: 20, overflow: "hidden", color: C.white, fontSize: Math.min(32, laneH * 0.62), fontWeight: 800, whiteSpace: "nowrap", boxShadow: "0 6px 14px rgba(0,0,0,0.15)" }}>
              {r === Math.floor((d0 - 1) / 7) ? label : `${label} (cont.)`}
            </div>,
          );
        }
        return <React.Fragment key={`${j}-${z}`}>{segs}</React.Fragment>;
      }))}
      {/* save stamp */}
      {has("save") ? (() => {
        const t = stAt.save as number;
        const p = ease(f, t, t + 12, Easing.out(Easing.cubic));
        const fade = has("arm") ? 1 - ease(f, stAt.arm as number, (stAt.arm as number) + 14) : 1;
        if (p <= 0 || fade <= 0) return null;
        return (
          <div style={{ position: "absolute", left: GRID.x + GRID.w / 2 - 300, top: GRID.y + (gridBottom - GRID.y) / 2 - 80, width: 600, height: 160, border: `8px solid ${C.forest}`, borderRadius: 20, color: C.forest, background: "rgba(255,254,249,0.85)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", transform: `rotate(-6deg) scale(${lerp(1.5, 1, p)})`, opacity: p * fade }}>
            <div style={{ fontSize: 58, fontWeight: 900, letterSpacing: 6 }}>SAVED</div>
            <div style={{ fontSize: 30, fontWeight: 700 }}>still a draft</div>
          </div>
        );
      })() : null}
      {/* profile tray */}
      <div style={{ position: "absolute", left: SIDE.x, top: GRID.y - 14, width: SIDE.w }}>
        <div style={{ fontSize: 32, fontWeight: 800, color: C.muted, letterSpacing: 2, marginBottom: 14 }}>PROFILES</div>
      </div>
      {blocks.map((b, j) => {
        const [d0, d1] = clampDays(b.days, days);
        const t0 = bStart(j);
        const lift = has("assign") ? ease(f, t0, t0 + per * 0.2) * (1 - ease(f, t0 + per, t0 + per + 10)) : 0;
        const done = fillP(j) >= 1;
        return (
          <div key={j} style={{ position: "absolute", left: SIDE.x, top: cardY(j), width: SIDE.w, height: 82, borderRadius: 18, background: C.white, border: `3px solid ${COLORS[j % COLORS.length]}`, display: "flex", alignItems: "center", gap: 16, padding: "0 20px", transform: `translateY(${-6 * lift}px)`, boxShadow: `0 ${4 + 14 * lift}px ${10 + 20 * lift}px rgba(24,62,53,0.18)` }}>
            <div style={{ width: 22, height: 50, borderRadius: 8, background: COLORS[j % COLORS.length] }} />
            <div style={{ fontSize: 32, fontWeight: 700, flex: 1, whiteSpace: "nowrap", overflow: "hidden" }}>{b.label}</div>
            <div style={{ fontSize: 28, color: done ? C.good : C.muted, fontWeight: 700 }}>{d0}–{d1}</div>
          </div>
        );
      })}
      {/* watering switch: separate, never changes */}
      <Watering f={f} armAt={has("arm") ? (stAt.arm as number) : null} />
      {/* action row */}
      <Action x={GRID.x} label="Review and save" icon="save" on={reached("save")} f={f} at={stAt.save} sub="checks, then stores the draft" />
      <Action x={GRID.x + 420} label="Arm plan" icon="arm" on={reached("arm")} f={f} at={stAt.arm} sub="a request, not a switch" />
      <Clock x={GRID.x + 840} f={f} armAt={stAt.arm} activeAt={stAt.active} hours={armH} armHour={armHour} lightsOn={props.lightsOn || "06:00"} />
      <Cursor x={cx} y={cy} press={press} opacity={ease(f, 4, 16)} />
    </div>
  );
};

function clampDays([a, b]: [number, number], days: number): [number, number] {
  const lo = Math.max(1, Math.min(a, b));
  return [lo, Math.min(days, Math.max(lo, Math.max(a, b)))];
}

function hoursBetween(a: string, b: string) {
  const m = (s: string) => {
    const [h, mm] = s.split(":").map(Number);
    return (h || 0) * 60 + (mm || 0);
  };
  return Math.round((((m(b) - m(a)) % 1440) + 1440) % 1440 / 6) / 10;
}

const ROW_Y = 690;

function Action({ x, label, icon, on, f, at, sub }: { x: number; label: string; icon: string; on: boolean; f: number; at?: number; sub: string }) {
  const p = at !== undefined ? ease(f, at, at + 14) : 0;
  const present = at !== undefined;
  return (
    <div style={{ position: "absolute", left: x, top: ROW_Y, width: 390, height: 220, borderRadius: 26, background: on ? C.forest : C.white, color: on ? C.white : C.forest, border: `3px solid ${present ? C.forest : C.line}`, opacity: present ? 1 : 0.35, display: "flex", flexDirection: "column", justifyContent: "center", padding: "0 30px", gap: 10, transform: `scale(${1 + 0.04 * p * (1 - ease(f, (at ?? 0) + 14, (at ?? 0) + 30))})`, boxShadow: on ? `0 16px 34px rgba(24,62,53,0.25)` : "none" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <Icon name={on ? "check" : icon} size={48} color={on ? C.gold : C.forest} />
        <div style={{ fontSize: 34, fontWeight: 800, whiteSpace: "nowrap" }}>{label}</div>
      </div>
      <div style={{ fontSize: 28, color: on ? "rgba(255,255,255,0.8)" : C.muted }}>{sub}</div>
    </div>
  );
}

function Clock({ x, f, armAt, activeAt, hours, armHour, lightsOn }: { armHour: number; x: number; f: number; armAt?: number; activeAt?: number; hours: number; lightsOn: string }) {
  const armed = armAt !== undefined && f >= armAt;
  const end = activeAt ?? (armAt !== undefined ? armAt + 90 : 0);
  const prog = armAt !== undefined ? ease(f, armAt + 10, end, Easing.inOut(Easing.quad)) : 0;
  const active = activeAt !== undefined && f >= activeAt;
  const left = Math.max(0, hours * (1 - prog));
  const ang = (armHour % 12) * 30 + prog * hours * 30;
  return (
    <div style={{ position: "absolute", left: x, top: ROW_Y, width: 400, height: 220, borderRadius: 26, background: active ? "#e3efdf" : C.white, border: `3px solid ${active ? C.good : armed ? C.gold : C.line}`, display: "flex", alignItems: "center", gap: 22, padding: "0 24px", opacity: armAt !== undefined || activeAt !== undefined ? 1 : 0.35 }}>
      <svg width={150} height={150} viewBox="0 0 100 100">
        <circle cx={50} cy={50} r={44} fill={C.white} stroke={active ? C.good : C.forest} strokeWidth={5} />
        {Array.from({ length: 12 }, (_, i) => (
          <line key={i} x1={50} y1={10} x2={50} y2={16} stroke={C.muted} strokeWidth={3} transform={`rotate(${i * 30} 50 50)`} />
        ))}
        <line x1={50} y1={50} x2={50} y2={24} stroke={C.forest} strokeWidth={5} strokeLinecap="round" transform={`rotate(${ang} 50 50)`} />
        <line x1={50} y1={50} x2={50} y2={16} stroke={C.gold} strokeWidth={3} strokeLinecap="round" transform={`rotate(${armed && !active ? f * 24 : 0} 50 50)`} />
        <circle cx={50} cy={50} r={5} fill={C.forest} />
      </svg>
      <div>
        {active ? (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 38, fontWeight: 800, color: C.good }}><Icon name="sun" size={40} color={C.good} /> Active</div>
            <div style={{ fontSize: 28, color: C.muted }}>since lights-on {lightsOn}</div>
          </>
        ) : (
          <>
            <div style={{ fontSize: 46, fontWeight: 800, color: armed ? C.forest : C.muted }}>{armed ? `${Math.ceil(left)} h` : `${hours} h`}</div>
            <div style={{ fontSize: 28, color: C.muted }}>to lights-on {lightsOn}</div>
          </>
        )}
      </div>
    </div>
  );
}

function Watering({ f, armAt }: { f: number; armAt: number | null }) {
  const note = armAt !== null ? ease(f, armAt + 8, armAt + 24) : 0;
  return (
    <div style={{ position: "absolute", left: SIDE.x, top: ROW_Y, width: SIDE.w, height: 220, borderRadius: 26, background: C.white, border: `3px dashed ${C.water}`, padding: "22px 26px" }}>
      <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: 2, color: C.water }}>TOP BAR · SEPARATE</div>
      <div style={{ display: "flex", alignItems: "center", gap: 18, marginTop: 14 }}>
        <Icon name="water" size={46} color={C.water} />
        <div style={{ fontSize: 36, fontWeight: 800 }}>Watering</div>
        <div style={{ marginLeft: "auto", width: 92, height: 50, borderRadius: 25, background: C.good, position: "relative" }}>
          <div style={{ position: "absolute", right: 5, top: 5, width: 40, height: 40, borderRadius: 20, background: C.white }} />
        </div>
      </div>
      <div style={{ marginTop: 16, fontSize: 28, fontWeight: 700, color: C.forest, opacity: note, display: "flex", alignItems: "center", gap: 10, transform: `scale(${1 + 0.04 * note * pulse(f, 40)})`, transformOrigin: "left center" }}>
        <Icon name="lock" size={32} /> Arming never touches it
      </div>
    </div>
  );
}

export default {
  Component,
  doc: "Calendar grid of grow days for one zone: profile cards are dragged from a tray onto day ranges (blocks fill day by day; uncovered days turn red-dashed once saved), then a SAVED·still a draft stamp, then Arm plan with a clock counting the hours to next lights-on, then Active (grid glows, today dot). A separate Watering switch card stays on throughout ('Arming never touches it'). props: {zone?:'Zone 1', zones?:[{name:'Zone A', start?:1}] (optional, 2–3 zones sharing the same profile blocks: each zone gets its own lane inside every day cell, labelled 'Zone A · Bulk'; start = the day that zone's block day 1 lands on, default 1, so a later-planted zone is shifted right; header reads 'Zone A + Zone B · grow plan'; omit for the single-zone default), days?:14 (7–21), blocks:[{days:[1,7], label:'Early flower'}] (max 5), stages?:['assign','save','arm','active'] (any ordered subset), armAt?:'15:00', lightsOn?:'06:00'}. steps: one per stage, in stages order (blocks share the assign step, dragged one after another).",
  example: {
    props: { zone: "Zone 1", days: 14, blocks: [{ days: [1, 7], label: "Bulk" }, { days: [8, 14], label: "Early flower" }], stages: ["assign", "save", "arm", "active"], armAt: "15:00", lightsOn: "06:00" },
    steps: [15, 105, 140, 200],
  },
} satisfies SceneDef<P>;
