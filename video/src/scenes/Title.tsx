import React from "react";
import { C } from "../theme";
import { useReveal, fadeUp } from "../anim";
import { Stage, Heading, Caption, type SceneDef } from "./kit";

type P = { title: string; subtitle?: string; eyebrow?: string };

const Component: SceneDef<P>["Component"] = ({ props }) => {
  const a = useReveal(0, 20);
  const b = useReveal(10, 20);
  return (
    <Stage style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
      {props.eyebrow ? <div style={{ ...fadeUp(a), fontSize: 30, fontWeight: 700, letterSpacing: 4, color: C.gold, marginBottom: 24 }}>{props.eyebrow.toUpperCase()}</div> : null}
      <Heading style={{ ...fadeUp(a), fontSize: 104, maxWidth: 1500 }}>{props.title}</Heading>
      {props.subtitle ? <Caption style={{ ...fadeUp(b), fontSize: 44, marginTop: 36, maxWidth: 1400 }}>{props.subtitle}</Caption> : null}
    </Stage>
  );
};

export default {
  Component,
  doc: "Big title card. props: {title, subtitle?, eyebrow?}. Use to open a section or name a new idea.",
  example: { props: { eyebrow: "New idea", title: "Dryback", subtitle: "How much the water content falls between two readings" } },
} satisfies SceneDef<P>;
