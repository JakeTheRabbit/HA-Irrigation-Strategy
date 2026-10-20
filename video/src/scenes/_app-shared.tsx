import React from "react";
import { Easing, interpolate } from "remotion";
import { C } from "../theme";
import { clamp } from "../anim";

// Shared helpers for the app-explainer scenes (ScreenTour, FlowSteps, Checklist, Compare,
// LinesLegend, CalendarPlan, DecisionTree). Not a scene: the leading underscore keeps it
// out of the generated registry.

// Frame for step i: the spoken step if known, else an even spread that starts a little in.
export function beatAt(steps: number[], i: number, duration: number, count: number, lead = 15) {
  const s = steps[i];
  if (Number.isFinite(s)) return s;
  return Math.round(lead + ((duration * 0.85 - lead) * i) / Math.max(count, 1));
}

// Eased 0→1 between frames a and b (a = 1e9 means "never").
export const ease = (f: number, a: number, b: number, e: (t: number) => number = Easing.inOut(Easing.cubic)) =>
  Number.isFinite(a) ? interpolate(f, [a, Math.max(a + 1, b)], [0, 1], { ...clamp, easing: e }) : a < 0 ? 1 : 0;

// 0..1 sine pulse with the given period in frames.
export const pulse = (f: number, period = 45, phase = 0) => 0.5 + 0.5 * Math.sin(((f + phase) / period) * Math.PI * 2);

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

// Pixel sizes of the bundled screenshots, so callers can give boxes in image pixels.
export const SCREEN_SIZES: Record<string, [number, number]> = {
  "demo-ai-assistant-r3.png": [1280, 720],
  "demo-calendar-profile-grid-r3.png": [984, 500],
  "demo-calendar-r3.png": [1280, 720],
  "demo-currentday-graph-r3.png": [521, 296],
  "demo-currentday-r3.png": [1280, 720],
  "demo-endpoint-profiles-r3.png": [984, 500],
  "demo-equipment-setup-r3.png": [1280, 720],
  "demo-history-compare-r3.png": [1280, 720],
  "demo-overview-r3.png": [1280, 720],
  "demo-probe-mapping-r3.png": [934, 500],
  "demo-probes-r3.png": [1280, 720],
  "demo-selected-room-r3.png": [1280, 720],
  "demo-settings-defaultview-r3.png": [618, 160],
  "demo-tank-and-feed-r3.png": [1280, 720],
  "demo-zone-detail-r3.png": [1280, 720],
};

// Built-in line icons (24×24 grid, stroked). Anything else passed as an icon is drawn as text (emoji).
const PATHS: Record<string, string> = {
  draft: "M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4",
  review: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 100-6 3 3 0 000 6z",
  apply: "M4 12h13M12 6l6 6-6 6M21 4v16",
  readback: "M6 3h12v18l-3-2-3 2-3-2-3 2V3zM9 11l2 2 4-4",
  restore: "M4 4v6h6M4.5 10A8 8 0 1112 20",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3zM9 12l2 2 4-4",
  preserve: "M4 7h4l2-3h4l2 3h4v13H4V7zM12 17a4 4 0 100-8 4 4 0 000 8z",
  search: "M10.5 17a6.5 6.5 0 100-13 6.5 6.5 0 000 13zM15.5 15.5L21 21",
  check: "M4 12.5l5 5L20 6.5",
  cross: "M6 6l12 12M18 6L6 18",
  water: "M12 3s6 7 6 11a6 6 0 01-12 0c0-4 6-11 6-11z",
  clock: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2",
  lock: "M6 11h12v10H6V11zM8 11V8a4 4 0 018 0v3",
  calendar: "M4 6h16v15H4V6zM4 10h16M8 3v5M16 3v5",
  alert: "M12 3l10 18H2L12 3zM12 10v5M12 18v.5",
  stop: "M8 3h8l5 5v8l-5 5H8l-5-5V8l5-5zM9 9l6 6M15 9l-6 6",
  power: "M12 3v9M6.5 6.5a8 8 0 1011 0",
  probe: "M10 3h4v11l-2 7-2-7V3zM10 8h4",
  plug: "M9 3v5M15 3v5M6 8h12v4a6 6 0 01-12 0V8zM12 18v3",
  chart: "M4 4v16h16M7 15l4-5 3 3 5-7",
  save: "M5 3h11l3 3v15H5V3zM8 3v6h8V3M8 21v-7h8v7",
  person: "M12 11a4 4 0 100-8 4 4 0 000 8zM4 21c0-4 4-6 8-6s8 2 8 6",
  question: "M9 9a3 3 0 116 0c0 2-3 2.5-3 5M12 18v.5",
  note: "M6 3h9l4 4v14H6V3zM9 11h7M9 15h7M9 7h3",
  wrench: "M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 100-6 3 3 0 000 6z",
  arm: "M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M12 16a4 4 0 100-8 4 4 0 000 8z",
  sun: "M12 17a5 5 0 100-10 5 5 0 000 10zM12 1v3M12 20v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M1 12h3M20 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1",
  ruler: "M3 17L17 3l4 4L7 21l-4-4zM7 13l2 2M10 10l2 2M13 7l2 2",
};
export const ICON_NAMES = Object.keys(PATHS);

// True when `name` is a built-in icon path (not an emoji / free text).
export const hasIcon = (name: string) => !!PATHS[name];

export const Icon: React.FC<{ name?: string; size?: number; color?: string; stroke?: number }> = ({ name = "", size = 48, color = C.forest, stroke = 2.2 }) => {
  const d = PATHS[name];
  if (!d) return <span style={{ fontSize: size * 0.86, lineHeight: 1, display: "inline-block" }}>{name}</span>;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" style={{ display: "block" }}>
      <path d={d} />
    </svg>
  );
};

// Mouse pointer. `press` 0..1 shrinks it and shows a click ripple.
export const Cursor: React.FC<{ x: number; y: number; press?: number; opacity?: number }> = ({ x, y, press = 0, opacity = 1 }) => (
  <div style={{ position: "absolute", left: x, top: y, width: 0, height: 0, opacity, pointerEvents: "none", zIndex: 50 }}>
    {press > 0 && press < 1 ? (
      <div style={{ position: "absolute", left: -40 * press - 6, top: -40 * press - 6, width: 80 * press + 12, height: 80 * press + 12, borderRadius: "50%", border: `4px solid ${C.gold}`, opacity: 1 - press }} />
    ) : null}
    <svg width={44} height={52} viewBox="0 0 22 26" style={{ position: "absolute", left: -3, top: -2, transform: `scale(${1 - 0.12 * Math.sin(Math.PI * press)})`, transformOrigin: "3px 2px", filter: "drop-shadow(0 4px 6px rgba(0,0,0,0.3))" }}>
      <path d="M2 1l17 14h-8l5 8-3.5 2-5-8.5L2 22z" fill={C.forest} stroke={C.white} strokeWidth={1.6} strokeLinejoin="round" />
    </svg>
  </div>
);

// Round numbered badge used by callouts.
export const NumBadge: React.FC<{ n: number | string; size?: number; bg?: string; color?: string; style?: React.CSSProperties }> = ({ n, size = 56, bg = C.gold, color = C.white, style }) => (
  <div style={{ width: size, height: size, borderRadius: size / 2, background: bg, color, display: "grid", placeItems: "center", fontWeight: 800, fontSize: size * 0.52, flexShrink: 0, boxShadow: "0 4px 10px rgba(24,62,53,0.25)", ...style }}>{n}</div>
);

// Tone → colour mapping shared by Compare / Checklist.
export const TONE: Record<string, { fg: string; bg: string }> = {
  good: { fg: C.good, bg: "#e3efdf" },
  bad: { fg: C.error, bg: "#f6e1dc" },
  warn: { fg: C.warn, bg: "#f8ead3" },
  water: { fg: C.water, bg: "#e1eff9" },
  neutral: { fg: C.forest, bg: C.leaf },
  ec: { fg: C.ec, bg: "#f7e8d2" },
};
