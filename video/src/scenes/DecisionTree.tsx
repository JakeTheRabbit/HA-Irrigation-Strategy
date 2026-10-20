import React from "react";
import { useCurrentFrame, Easing } from "remotion";
import { C, FONT } from "../theme";
import { usePop } from "../anim";
import { type SceneDef } from "./kit";
import { beatAt, ease, pulse, Icon } from "./_app-shared";

type Kind = "question" | "action" | "stop";
type Node = { id: string; text: string; kind?: Kind };
type Edge = { from: string; to: string; label?: string };
type P = { nodes: Node[]; edges: Edge[]; path?: string[] };

const STAGE_H = 980;
const LEFT = 96;
const WIDTH = 1728;
const FS = 34;

type Box = { x: number; y: number; w: number; h: number };

// Tidy top-to-bottom layout: leaves get equal slots in DFS order, parents sit centred over children.
function layout(nodes: Node[], edges: Edge[]) {
  const ids = nodes.map((n) => n.id);
  const kids: Record<string, string[]> = {};
  const parent: Record<string, string> = {};
  ids.forEach((id) => (kids[id] = []));
  const depth: Record<string, number> = {};
  const roots = ids.filter((id) => !edges.some((e) => e.to === id));
  const queue = [...(roots.length ? roots : ids.slice(0, 1))];
  queue.forEach((r) => (depth[r] = 0));
  while (queue.length) {
    const id = queue.shift() as string;
    for (const e of edges.filter((e) => e.from === id)) {
      if (depth[e.to] !== undefined || !kids[e.to]) continue;
      depth[e.to] = depth[id] + 1;
      parent[e.to] = id;
      kids[id].push(e.to);
      queue.push(e.to);
    }
  }
  ids.forEach((id) => (depth[id] ??= 0));
  const slot: Record<string, number> = {};
  const span: Record<string, number> = {};
  let next = 0;
  const visit = (id: string) => {
    if (!kids[id].length) {
      slot[id] = next + 0.5;
      span[id] = 1;
      next += 1;
      return;
    }
    kids[id].forEach(visit);
    slot[id] = kids[id].reduce((s, k) => s + slot[k], 0) / kids[id].length;
    span[id] = kids[id].reduce((s, k) => s + span[k], 0);
  };
  ids.filter((id) => depth[id] === 0).forEach(visit);
  const leaves = Math.max(1, next);
  const slotW = WIDTH / leaves;
  const levels = Math.max(...ids.map((id) => depth[id])) + 1;
  const w: Record<string, number> = {};
  const h: Record<string, number> = {};
  ids.forEach((id) => {
    w[id] = Math.min(600, slotW * Math.min(span[id], 1.6) - 40);
    const text = nodes.find((n) => n.id === id)?.text || "";
    const cpl = Math.max(8, (w[id] - 130) / (FS * 0.52));
    h[id] = Math.max(116, 40 + Math.ceil(text.length / cpl) * 44);
  });
  const levelH = Array.from({ length: levels }, (_, l) => Math.max(...ids.filter((id) => depth[id] === l).map((id) => h[id])));
  const used = levelH.reduce((a, b) => a + b, 0);
  const gapY = Math.min(170, (STAGE_H - 60 - used) / Math.max(1, levels - 1));
  const top0 = (STAGE_H - used - gapY * (levels - 1)) / 2;
  const levelTop: number[] = [];
  levelH.reduce((y, hh, l) => ((levelTop[l] = y), y + hh + gapY), top0);
  const box: Record<string, Box> = {};
  ids.forEach((id) => {
    const cx = LEFT + slot[id] * slotW;
    const l = depth[id];
    box[id] = { x: cx - w[id] / 2, y: levelTop[l] + (levelH[l] - h[id]) / 2, w: w[id], h: h[id] };
  });
  return box;
}

const bez = (t: number, a: number, b: number, c: number, d: number) => {
  const u = 1 - t;
  return u * u * u * a + 3 * u * u * t * b + 3 * u * t * t * c + t * t * t * d;
};

const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const f = useCurrentFrame();
  const pop = usePop(0);
  const nodes = props.nodes || [];
  const edges = (props.edges || []).filter((e) => nodes.some((n) => n.id === e.from) && nodes.some((n) => n.id === e.to));
  const path = (props.path || []).filter((id) => nodes.some((n) => n.id === id));
  const box = layout(nodes, edges);
  const at = path.map((_, i) => beatAt(steps, i, duration, path.length, 18));
  const litAt = (id: string) => {
    const i = path.indexOf(id);
    return i < 0 ? 1e9 : i === 0 ? at[0] : at[i] + 14;
  };
  const endAt = path.length ? litAt(path[path.length - 1]) : 1e9;
  const dimOthers = ease(f, endAt, endAt + 20);
  let cur: string | null = null;
  path.forEach((id) => f >= litAt(id) && (cur = id));

  const geo = (e: Edge) => {
    const a = box[e.from];
    const b = box[e.to];
    const x0 = a.x + a.w / 2;
    const y0 = a.y + a.h;
    const x1 = b.x + b.w / 2;
    const y1 = b.y;
    const my = (y0 + y1) / 2;
    return { x0, y0, x1, y1, my, d: `M ${x0} ${y0} C ${x0} ${my}, ${x1} ${my}, ${x1} ${y1 - 12}` };
  };

  return (
    <div style={{ position: "absolute", inset: 0, fontFamily: FONT, color: C.ink, opacity: pop }}>
      <svg width={1920} height={STAGE_H} style={{ position: "absolute", inset: 0 }}>
        {edges.map((e, k) => {
          const g = geo(e);
          const i = path.indexOf(e.to);
          const onPath = i > 0 && path[i - 1] === e.from;
          const t0 = onPath ? at[i] : 1e9;
          const draw = ease(f, t0, t0 + 16, Easing.inOut(Easing.quad));
          const off = onPath ? 0 : dimOthers;
          return (
            <g key={k} opacity={1 - 0.6 * off}>
              <path d={g.d} fill="none" stroke={C.line} strokeWidth={6} />
              <path d={`M ${g.x1 - 14} ${g.y1 - 22} L ${g.x1} ${g.y1 - 4} L ${g.x1 + 14} ${g.y1 - 22} Z`} fill={draw >= 1 ? C.gold : C.line} />
              {draw > 0 ? (
                <>
                  <path d={g.d} fill="none" stroke={C.gold} strokeWidth={16} opacity={0.25} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - draw} />
                  <path d={g.d} fill="none" stroke={C.gold} strokeWidth={7} pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - draw} />
                </>
              ) : null}
              {draw > 0 && draw < 1 ? (
                <circle cx={bez(draw, g.x0, g.x0, g.x1, g.x1)} cy={bez(draw, g.y0, g.my, g.my, g.y1 - 12)} r={14} fill={C.gold} stroke={C.white} strokeWidth={4} />
              ) : null}
            </g>
          );
        })}
      </svg>
      {edges.map((e, k) => {
        if (!e.label) return null;
        const g = geo(e);
        const i = path.indexOf(e.to);
        const onPath = i > 0 && path[i - 1] === e.from;
        const lit = onPath && f >= at[i];
        const x = (g.x0 + g.x1) / 2;
        return (
          <div key={k} style={{ position: "absolute", left: x - 200, width: 400, top: g.my - 26, textAlign: "center", opacity: 1 - 0.6 * (onPath ? 0 : dimOthers) }}>
            <span style={{ display: "inline-block", padding: "6px 22px", borderRadius: 24, background: lit ? C.gold : C.paper, border: `3px solid ${lit ? C.gold : C.line}`, color: lit ? C.white : C.muted, fontSize: 28, fontWeight: 800, whiteSpace: "nowrap" }}>{e.label}</span>
          </div>
        );
      })}
      {nodes.map((n) => {
        const b = box[n.id];
        const kind = n.kind || "question";
        const lit = ease(f, litAt(n.id), litAt(n.id) + 12);
        const isCur = cur === n.id;
        const glow = isCur ? pulse(f, 36) : 0;
        const onPath = path.includes(n.id);
        const fill = lit > 0.5 ? (kind === "stop" ? C.error : kind === "action" ? C.plant : C.forest) : C.white;
        const border = kind === "stop" ? C.error : kind === "action" ? C.plant : C.forest;
        const icon = kind === "stop" ? "stop" : kind === "action" ? "wrench" : "question";
        return (
          <div key={n.id} style={{ position: "absolute", left: b.x, top: b.y, width: b.w, height: b.h, borderRadius: kind === "question" ? 26 : 18, background: fill, border: `4px solid ${border}`, display: "flex", alignItems: "center", gap: 20, padding: "0 26px", opacity: onPath ? 1 : 1 - 0.6 * dimOthers, transform: `scale(${1 + 0.05 * lit * (isCur ? 1 : 0.4) + 0.012 * glow})`, boxShadow: isCur ? `0 0 ${24 + 26 * glow}px ${kind === "stop" ? "rgba(168,57,47,0.55)" : "rgba(182,166,111,0.6)"}` : "0 8px 20px rgba(24,62,53,0.08)" }}>
            <div style={{ width: 64, height: 64, borderRadius: kind === "stop" ? 14 : 32, background: lit > 0.5 ? "rgba(255,255,255,0.18)" : C.paper, display: "grid", placeItems: "center", flexShrink: 0 }}>
              <Icon name={icon} size={42} color={lit > 0.5 ? C.white : border} stroke={2.6} />
            </div>
            <div style={{ fontSize: FS, lineHeight: 1.25, fontWeight: kind === "question" ? 600 : 700, color: lit > 0.5 ? C.white : C.ink }}>{n.text}</div>
          </div>
        );
      })}
    </div>
  );
};

export default {
  Component,
  doc: "Troubleshooting flow, auto-laid-out top to bottom (tidy tree from the edges). Questions (? badge), actions (wrench) and stop nodes (red, e.g. 'Physical shutdown first'); a gold token runs down each edge of the spoken path and lights the next node; other branches dim at the end. props: {nodes:[{id, text (≤45 chars), kind:'question'|'action'|'stop'}], edges:[{from, to, label? ('Yes'/'No', ≤14 chars)}], path:[ids from root]}. Keep ≤ 4 levels and ≤ 4 leaves. steps: one spoken phrase per path node.",
  example: {
    props: {
      nodes: [
        { id: "flow", text: "Water flowing while the screen says OFF?", kind: "question" },
        { id: "shut", text: "Physical shutdown first", kind: "stop" },
        { id: "fresh", text: "Is the reading fresh?", kind: "question" },
        { id: "repair", text: "Repair the evidence: cable, power, mapping", kind: "action" },
        { id: "target", text: "Then consider one target change", kind: "action" },
      ],
      edges: [
        { from: "flow", to: "shut", label: "Yes" },
        { from: "flow", to: "fresh", label: "No" },
        { from: "fresh", to: "repair", label: "No · 4 h old" },
        { from: "fresh", to: "target", label: "Yes" },
      ],
      path: ["flow", "fresh", "repair"],
    },
    steps: [15, 75, 140],
  },
} satisfies SceneDef<P>;
