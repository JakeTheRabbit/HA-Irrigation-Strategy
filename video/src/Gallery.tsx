import React from "react";
import { AbsoluteFill, Series } from "remotion";
import { C, FONT, FPS } from "./theme";
import { DEFS } from "./scenes";

// Every scene's example, 6 seconds each, for visual review (remotion studio → gallery).
export const GALLERY_ITEMS = Object.entries(DEFS);

// One scene's example for 8 s: `remotion still src/index.ts scene out.png --props=<file with {"name":"X"}>`.
export const ScenePreview: React.FC<{ name: string }> = ({ name }) => {
  const def = DEFS[name];
  return (
    <AbsoluteFill style={{ background: C.paper, fontFamily: FONT }}>
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: 92, background: C.white, borderBottom: `2px solid ${C.line}`, display: "flex", alignItems: "center", padding: "0 64px", fontSize: 30, fontWeight: 600, color: C.forest }}>{name}</div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 92, bottom: 8 }}>
        {def ? <def.Component props={def.example.props} steps={def.example.steps || []} duration={8 * FPS} slideTitle={name} /> : null}
      </div>
    </AbsoluteFill>
  );
};

export const Gallery: React.FC = () => (
  <AbsoluteFill style={{ background: C.paper, fontFamily: FONT }}>
    <Series>
      {GALLERY_ITEMS.map(([name, def]) => (
        <Series.Sequence key={name} durationInFrames={6 * FPS}>
          <div style={{ position: "absolute", left: 0, right: 0, top: 92, bottom: 8 }}>
            <def.Component props={def.example.props} steps={def.example.steps || []} duration={6 * FPS} slideTitle={name} />
          </div>
          <div style={{ position: "absolute", top: 24, left: 64, fontSize: 32, fontWeight: 700, color: C.muted }}>{name}</div>
        </Series.Sequence>
      ))}
    </Series>
  </AbsoluteFill>
);
