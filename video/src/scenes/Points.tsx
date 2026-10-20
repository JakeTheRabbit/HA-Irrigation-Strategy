import React from "react";
import { C } from "../theme";
import { useReveal, fadeUp, stepAt } from "../anim";
import { Stage, Heading, type SceneDef } from "./kit";

type P = { heading?: string; items: { text: string; icon?: string }[] };

// Key points that appear one by one as each is spoken.
const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const h = useReveal(0, 16);
  return (
    <Stage>
      {props.heading ? <Heading style={fadeUp(h)}>{props.heading}</Heading> : null}
      <div style={{ marginTop: 56, display: "flex", flexDirection: "column", gap: 30 }}>
        {props.items.map((item, i) => (
          <Item key={i} at={stepAt(steps, i, duration, props.items.length)} {...item} n={i + 1} />
        ))}
      </div>
    </Stage>
  );
};

function Item({ at, text, icon, n }: { at: number; text: string; icon?: string; n: number }) {
  const p = useReveal(at, 16);
  return (
    <div style={{ ...fadeUp(p, 24), display: "flex", alignItems: "center", gap: 32, background: C.white, borderRadius: 22, padding: "26px 36px", border: `2px solid ${C.line}` }}>
      <div style={{ width: 76, height: 76, borderRadius: 38, background: C.forest, color: C.white, display: "grid", placeItems: "center", fontSize: icon ? 42 : 36, fontWeight: 700, flexShrink: 0 }}>{icon || n}</div>
      <div style={{ fontSize: 46, lineHeight: 1.25 }}>{text}</div>
    </div>
  );
}

export default {
  Component,
  doc: "Numbered key points revealed in order. props: {heading?, items:[{text, icon? (emoji)}]} (max 5, ≤ 60 chars each). steps: one spoken phrase per item.",
  example: { props: { heading: "A pot holds three things", items: [{ text: "Solid material", icon: "🪨" }, { text: "Water", icon: "💧" }, { text: "Air", icon: "🌬️" }] }, steps: [10, 40, 70] },
} satisfies SceneDef<P>;
