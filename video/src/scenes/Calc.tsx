import React from "react";
import { C, SERIF } from "../theme";
import { useReveal, fadeUp, stepAt } from "../anim";
import { Stage, Heading, type SceneDef } from "./kit";

type P = { heading?: string; lines: { expr: string; note?: string }[]; answer?: string };

// Worked arithmetic: each line appears when spoken; the answer box lands last.
const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const n = props.lines.length + (props.answer ? 1 : 0);
  const h = useReveal(0, 16);
  const ans = useReveal(stepAt(steps, props.lines.length, duration, n), 18);
  return (
    <Stage>
      {props.heading ? <Heading style={fadeUp(h)}>{props.heading}</Heading> : null}
      <div style={{ marginTop: 48, display: "flex", flexDirection: "column", gap: 24 }}>
        {props.lines.map((line, i) => (
          <Line key={i} at={stepAt(steps, i, duration, n)} {...line} />
        ))}
      </div>
      {props.answer ? (
        <div style={{ ...fadeUp(ans), marginTop: 44, display: "inline-block", padding: "26px 44px", borderRadius: 22, background: C.forest, color: C.white, fontSize: 56, fontWeight: 700 }}>{props.answer}</div>
      ) : null}
    </Stage>
  );
};

function Line({ at, expr, note }: { at: number; expr: string; note?: string }) {
  const p = useReveal(at, 14);
  return (
    <div style={{ ...fadeUp(p, 16), display: "flex", alignItems: "baseline", gap: 40 }}>
      <span style={{ fontFamily: SERIF, fontSize: 76, color: C.ink, minWidth: 760 }}>{expr}</span>
      {note ? <span style={{ fontSize: 38, color: C.muted }}>{note}</span> : null}
    </div>
  );
}

export default {
  Component,
  doc: "Step-by-step worked calculation. props: {heading?, lines:[{expr:'60 − 45 = 15', note?:'percentage points'}], answer?}. steps: one spoken phrase per line, then one for the answer.",
  example: { props: { heading: "Size of the fall", lines: [{ expr: "60 − 45 = 15", note: "percentage points" }, { expr: "15 ÷ 60 = 0.25" }, { expr: "0.25 × 100 = 25%", note: "relative dryback" }], answer: "15 points · 25% relative" }, steps: [10, 40, 70, 100] },
} satisfies SceneDef<P>;
