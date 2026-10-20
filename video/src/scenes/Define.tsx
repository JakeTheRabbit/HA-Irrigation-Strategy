import React from "react";
import { C, SERIF } from "../theme";
import { usePop, useReveal, fadeUp, stepAt } from "../anim";
import { Stage, type SceneDef } from "./kit";

type P = { term: string; meaning: string; example?: string; abbrev?: string };

// Term card: shows the plain meaning first-class, so a new word is never left unexplained.
const Component: SceneDef<P>["Component"] = ({ props, steps, duration }) => {
  const pop = usePop(0);
  const m = useReveal(stepAt(steps, 0, duration, 2) || 14, 20);
  const ex = useReveal(stepAt(steps, 1, duration, 2) || 40, 20);
  return (
    <Stage style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: 1500, background: C.white, borderRadius: 32, border: `4px solid ${C.forest}`, padding: "64px 80px", transform: `scale(${0.9 + 0.1 * pop})`, opacity: pop, boxShadow: "0 30px 60px rgba(24,62,53,0.12)" }}>
        <div style={{ fontSize: 28, letterSpacing: 4, fontWeight: 700, color: C.gold }}>NEW WORD</div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 28, marginTop: 12 }}>
          <span style={{ fontFamily: SERIF, fontSize: 112, color: C.forest }}>{props.term}</span>
          {props.abbrev ? <span style={{ fontSize: 40, color: C.muted }}>{props.abbrev}</span> : null}
        </div>
        <div style={{ ...fadeUp(m), fontSize: 50, lineHeight: 1.3, marginTop: 28 }}>{props.meaning}</div>
        {props.example ? (
          <div style={{ ...fadeUp(ex), marginTop: 36, padding: "22px 30px", background: C.leaf, borderRadius: 18, fontSize: 38, color: C.ink }}>
            <b>Example:</b> {props.example}
          </div>
        ) : null}
      </div>
    </Stage>
  );
};

export default {
  Component,
  doc: "Definition card for a new term. props: {term, meaning, example?, abbrev?}. steps: [phrase when meaning is said, phrase when example is said]. Use the FIRST time a term appears.",
  example: { props: { term: "VWC", abbrev: "volumetric water content", meaning: "The share of a sample's volume that is water.", example: "6 of 10 equal boxes hold water → 60% VWC" }, steps: [15, 60] },
} satisfies SceneDef<P>;
