import React from "react";
import { C, FONT, SERIF } from "../theme";
import type { SceneProps } from "../types";

// Every scene module default-exports a SceneDef. `doc` and `example` feed the gallery
// and the authoring catalogue (CATALOG.md) used when scripting lessons.
export type SceneDef<P = any> = {
  Component: React.FC<SceneProps<P>>;
  doc: string;
  example: { props: P; steps?: number[] };
};

// Standard stage: 1920 × 980 area below the header, with generous margins.
export const Stage: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <div style={{ position: "absolute", inset: 0, padding: "48px 96px", fontFamily: FONT, color: C.ink, ...style }}>{children}</div>
);

export const Heading: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <div style={{ fontFamily: SERIF, fontSize: 64, lineHeight: 1.1, color: C.forest, ...style }}>{children}</div>
);

export const Caption: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <div style={{ fontSize: 34, color: C.muted, lineHeight: 1.35, ...style }}>{children}</div>
);

// Rounded label chip used for diagram callouts.
export const Chip: React.FC<{ children: React.ReactNode; color?: string; style?: React.CSSProperties }> = ({ children, color = C.forest, style }) => (
  <div style={{ display: "inline-flex", alignItems: "center", gap: 12, padding: "12px 22px", borderRadius: 999, background: C.white, border: `3px solid ${color}`, color, fontWeight: 700, fontSize: 32, ...style }}>{children}</div>
);
