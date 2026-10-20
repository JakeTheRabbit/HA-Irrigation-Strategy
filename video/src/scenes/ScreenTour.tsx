import React from "react";
import { Img, staticFile, useCurrentFrame, Easing } from "remotion";
import { C, FONT } from "../theme";
import { usePop } from "../anim";
import { type SceneDef } from "./kit";
import { beatAt, ease, lerp, pulse, Cursor, NumBadge, SCREEN_SIZES } from "./_app-shared";

type Focus = { x: number; y: number; w: number; h: number; label: string };
type P = { src: string; focus: Focus[]; size?: [number, number]; url?: string; zoom?: number };

const STAGE_W = 1920;
const STAGE_H = 988;
const CHROME = 52;
const MOVE = 34; // frames per camera move
type Cam = { cx: number; cy: number; s: number };

// Camera for one focus: zoom so the box fills ~60% of the viewport, kept inside the image.
function camFor(f: Focus, iw: number, ih: number, maxZoom: number): Cam {
  const s = Math.max(1, Math.min(maxZoom, 0.62 / Math.max(f.w / iw, f.h / ih)));
  const hw = iw / (2 * s);
  const hh = ih / (2 * s);
  const cx = Math.min(iw - hw, Math.max(hw, f.x + f.w / 2));
  const cy = Math.min(ih - hh, Math.max(hh, f.y + f.h / 2));
  return { cx, cy, s };
}

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const maskId = "st" + React.useId().replace(/[^a-zA-Z0-9]/g, "");
  const file = props.src.split("/").pop() || "";
  const [iw, ih] = props.size || SCREEN_SIZES[file] || [1280, 720];
  const focus = props.focus || [];
  const n = focus.length;
  const at = focus.map((_, i) => beatAt(steps, i, duration, n, 24));

  // Viewport fitted to the stage, keeping the image aspect.
  const maxW = 1700;
  const maxH = STAGE_H - 56 - CHROME;
  const vpW = Math.min(maxW, (maxH * iw) / ih);
  const vpH = (vpW * ih) / iw;
  const base = vpW / iw;
  // Never magnify the screenshot beyond ~1.6x its native pixels (small images get less zoom).
  const maxZoom = Math.min(props.zoom ?? 2.2, Math.max(1, 1.6 / base));
  const frameX = (STAGE_W - vpW) / 2;
  const frameY = (STAGE_H - vpH - CHROME) / 2;

  // Recursive camera: each step blends from wherever the camera was when it began.
  const full: Cam = { cx: iw / 2, cy: ih / 2, s: 1 };
  const camStep = (i: number, fr: number): Cam => {
    if (i < 0) return full;
    const from = camStep(i - 1, at[i]);
    const to = camFor(focus[i], iw, ih, maxZoom);
    const t = ease(fr, at[i], at[i] + MOVE);
    return { cx: lerp(from.cx, to.cx, t), cy: lerp(from.cy, to.cy, t), s: Math.exp(lerp(Math.log(from.s), Math.log(to.s), t)) };
  };
  let curStep = -1;
  for (let i = 0; i < n; i++) if (f >= at[i]) curStep = i;
  const cam0 = camStep(curStep, f);
  // Gentle Ken Burns drift on top so the frame never sits still.
  const drift = 1 + 0.03 * (0.5 - 0.5 * Math.cos(f / 60));
  const s = cam0.s * drift;
  const k = s * base;
  const tx = vpW / 2 - cam0.cx * k;
  const ty = vpH / 2 - cam0.cy * k;
  // Focus rect in viewport pixels, padded and kept inside the viewport.
  const toScreen = (b: Focus) => {
    const x0 = Math.max(8, tx + b.x * k - 10);
    const y0 = Math.max(8, ty + b.y * k - 10);
    const x1 = Math.min(vpW - 8, tx + (b.x + b.w) * k + 10);
    const y1 = Math.min(vpH - 8, ty + (b.y + b.h) * k + 10);
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  };

  const pop = usePop(0);
  let cur = -1;
  for (let i = 0; i < n; i++) if (f >= at[i]) cur = i;
  const box = cur >= 0 ? toScreen(focus[cur]) : null;
  const settle = cur >= 0 ? ease(f, at[cur] + MOVE * 0.55, at[cur] + MOVE + 8, Easing.out(Easing.cubic)) : 0;
  const prevFade = cur > 0 ? 1 - ease(f, at[cur], at[cur] + 10) : 0;
  const dim = cur >= 0 ? (cur === 0 ? ease(f, at[0], at[0] + 18) : 1) : 0;
  const pad = 0;

  // Cursor glides between focus regions.
  const cursorAt = (i: number) => {
    const b = toScreen(focus[i]);
    return { x: b.x + b.w * 0.72, y: b.y + b.h * 0.6 };
  };
  let cx = vpW * 0.6;
  let cy = vpH * 0.7;
  if (cur >= 0) {
    const tgt = cursorAt(cur);
    const t = ease(f, at[cur] + 6, at[cur] + MOVE + 10);
    const src = cur > 0 ? cursorAt(cur - 1) : { x: cx, y: cy };
    cx = lerp(src.x, tgt.x, t) + 6 * Math.sin(f / 23);
    cy = lerp(src.y, tgt.y, t) + 5 * Math.cos(f / 29);
  } else {
    cx += 30 * Math.sin(f / 30);
    cy += 16 * Math.cos(f / 25);
  }

  return (
    <div style={{ position: "absolute", inset: 0, fontFamily: FONT }}>
      <div style={{ position: "absolute", left: frameX, top: frameY, width: vpW, height: vpH + CHROME, borderRadius: 22, overflow: "hidden", background: C.white, boxShadow: "0 30px 70px rgba(24,62,53,0.22)", border: `2px solid ${C.line}`, transform: `scale(${0.94 + 0.06 * pop})`, opacity: pop }}>
        {/* browser chrome */}
        <div style={{ height: CHROME, display: "flex", alignItems: "center", gap: 12, padding: "0 22px", background: "#eef0e8", borderBottom: `2px solid ${C.line}` }}>
          {["#e0695f", "#e7b84f", "#69b462"].map((c) => <div key={c} style={{ width: 16, height: 16, borderRadius: 8, background: c }} />)}
          <div style={{ marginLeft: 22, flex: 1, maxWidth: 760, height: 32, borderRadius: 16, background: C.white, display: "flex", alignItems: "center", padding: "0 18px", fontSize: 20, color: C.muted }}>
            {props.url || "Crop Steering · isolated demo"}
          </div>
        </div>
        {/* viewport */}
        <div style={{ position: "relative", width: vpW, height: vpH, overflow: "hidden" }}>
          <Img src={staticFile(props.src)} style={{ position: "absolute", left: 0, top: 0, width: iw, height: ih, transformOrigin: "0 0", transform: `translate(${tx}px, ${ty}px) scale(${k})` }} />
          <svg width={vpW} height={vpH} style={{ position: "absolute", inset: 0 }}>
            <defs>
              <mask id={maskId}>
                <rect width={vpW} height={vpH} fill="white" />
                {box ? <rect x={box.x - pad} y={box.y - pad} width={box.w + pad * 2} height={box.h + pad * 2} rx={16} fill="black" /> : null}
              </mask>
            </defs>
            <rect width={vpW} height={vpH} fill="rgba(16,34,28,0.58)" mask={`url(#${maskId})`} opacity={dim} />
            {cur > 0 && prevFade > 0 ? (() => {
              const b = toScreen(focus[cur - 1]);
              return <rect x={b.x - pad} y={b.y - pad} width={b.w + pad * 2} height={b.h + pad * 2} rx={16} fill="none" stroke={C.gold} strokeWidth={5} opacity={prevFade} />;
            })() : null}
            {box ? (
              <>
                <rect x={box.x - pad - 6} y={box.y - pad - 6} width={box.w + pad * 2 + 12} height={box.h + pad * 2 + 12} rx={20} fill="none" stroke={C.gold} strokeWidth={10} opacity={settle * (0.18 + 0.22 * pulse(f, 40))} />
                <rect x={box.x - pad} y={box.y - pad} width={box.w + pad * 2} height={box.h + pad * 2} rx={16} fill="none" stroke={C.gold} strokeWidth={5}
                  pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - settle} />
              </>
            ) : null}
          </svg>
          {box && cur >= 0 ? <Callout box={box} pad={pad} vpW={vpW} vpH={vpH} n={cur + 1} label={focus[cur].label} p={settle} /> : null}
          <Cursor x={cx} y={cy} press={cur >= 0 ? ease(f, at[cur] + MOVE + 4, at[cur] + MOVE + 20) : 0} />
        </div>
      </div>
      {/* step dots */}
      {n > 1 ? (
        <div style={{ position: "absolute", left: 0, right: 0, bottom: 10, display: "flex", justifyContent: "center", gap: 14 }}>
          {focus.map((_, i) => (
            <div key={i} style={{ width: i === cur ? 44 : 14, height: 14, borderRadius: 7, background: i <= cur ? C.gold : C.line }} />
          ))}
        </div>
      ) : null}
    </div>
  );
};

// Numbered label placed below the box, or above / inside if there is no room.
function Callout({ box, pad, vpW, vpH, n, label, p }: { box: { x: number; y: number; w: number; h: number }; pad: number; vpW: number; vpH: number; n: number; label: string; p: number }) {
  const H = 78;
  const estW = Math.min(vpW - 40, 120 + label.length * 19);
  const below = box.y + box.h + pad + 18;
  const above = box.y - pad - 18 - H;
  const top = below + H < vpH - 10 ? below : above > 10 ? above : Math.min(vpH - H - 16, box.y + box.h - H - 16);
  const left = Math.max(16, Math.min(vpW - estW - 16, box.x + box.w / 2 - estW / 2));
  const fromBelow = top >= box.y;
  return (
    <div style={{ position: "absolute", left, top, height: H, maxWidth: vpW - 32, display: "flex", alignItems: "center", gap: 16, padding: "0 30px 0 12px", borderRadius: H / 2, background: C.forest, color: C.white, fontSize: 34, fontWeight: 700, whiteSpace: "nowrap", boxShadow: "0 12px 28px rgba(0,0,0,0.35)", opacity: p, transform: `translateY(${(1 - p) * (fromBelow ? 24 : -24)}px) scale(${0.9 + 0.1 * p})` }}>
      <NumBadge n={n} size={56} />
      {label}
    </div>
  );
}

export default {
  Component,
  doc: "Real app screenshot in a browser frame; the camera eases (Ken Burns) to each region in turn, dims the rest, draws a gold highlight box and a numbered callout. props: {src:'img/screens/demo-overview-r3.png', focus:[{x,y,w,h,label}] in IMAGE pixels, size?:[w,h] (auto for bundled screens), url?, zoom?(max, default 2.2; automatically capped so the screenshot is never shown above ~1.6× its native pixels — small images zoom less)}. Screen sizes: 1280×720 for overview, selected-room, zone-detail, currentday, calendar, equipment-setup, probes, tank-and-feed, history-compare, ai-assistant; 984×500 calendar-profile-grid & endpoint-profiles; 934×500 probe-mapping; 521×296 currentday-graph; 618×160 settings-defaultview. steps: one spoken phrase per focus (camera starts moving on it). Keep labels ≤ 40 chars.",
  example: {
    props: {
      src: "img/screens/demo-overview-r3.png",
      focus: [
        { x: 258, y: 10, w: 278, h: 36, label: "Room chips: pick the room" },
        { x: 597, y: 273, w: 318, h: 397, label: "Zone card: one zone's address" },
        { x: 612, y: 478, w: 290, h: 45, label: "The Controller's next action" },
        { x: 1030, y: 10, w: 250, h: 36, label: "Watering and Stop all: selected room" },
      ],
    },
    steps: [20, 70, 125, 180],
  },
} satisfies SceneDef<P>;
