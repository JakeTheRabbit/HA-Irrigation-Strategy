import React from "react";
import { AbsoluteFill, Sequence, Series, interpolate, useCurrentFrame, staticFile } from "remotion";
import { Audio, Video } from "@remotion/media";
import { C, FONT, FPS } from "./theme";
import type { LessonData, SlideData, Beat } from "./types";
import { SCENES } from "./scenes";
import { clamp } from "./anim";

const HEADER = 92;
const FADE = 10;

function BeatLayer({ beat, duration, slideTitle }: { beat: Beat; duration: number; slideTitle: string }) {
  const f = useCurrentFrame();
  const Scene = SCENES[beat.type];
  const opacity = interpolate(f, [0, FADE, duration - FADE, duration], [0, 1, 1, 0], clamp);
  if (!Scene) throw new Error(`Unknown scene type: ${beat.type}`);
  const steps = beat.steps.map((s) => (s == null ? NaN : Math.round(s * FPS)));
  return (
    <AbsoluteFill style={{ opacity }}>
      <Scene props={beat.props || {}} steps={steps} duration={duration} slideTitle={slideTitle} />
    </AbsoluteFill>
  );
}

function SlideView({ slide, lessonId, index, count }: { slide: SlideData; lessonId: string; index: number; count: number }) {
  const total = Math.ceil(slide.duration * FPS);
  const f = useCurrentFrame();
  const beats = slide.beats.length ? slide.beats : [{ type: "Title", at: 0, steps: [], props: { title: slide.title } }];
  return (
    <AbsoluteFill style={{ background: C.paper, fontFamily: FONT, color: C.ink }}>
      {slide.audio.map((a) => (
        <Sequence key={a.src} from={Math.round(a.start * FPS)} durationInFrames={Math.ceil(a.duration * FPS)} layout="none">
          <Audio src={staticFile(a.src)} />
        </Sequence>
      ))}
      <div style={{ position: "absolute", left: 0, right: 0, top: 0, height: HEADER, display: "flex", alignItems: "center", gap: 28, padding: "0 64px", borderBottom: `2px solid ${C.line}`, background: C.white }}>
        <span style={{ fontWeight: 700, letterSpacing: 3, color: C.muted, fontSize: 24 }}>CROP STEERING · {lessonId}</span>
        <span style={{ fontWeight: 600, fontSize: 30, color: C.forest }}>{slide.title}</span>
        <span style={{ marginLeft: "auto", color: C.muted, fontSize: 22 }}>{index + 1} / {count}</span>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: HEADER, bottom: 8 }}>
        {beats.map((beat, i) => {
          const from = Math.round(beat.at * FPS);
          const next = i + 1 < beats.length ? Math.round(beats[i + 1].at * FPS) : total;
          const len = Math.max(FADE * 2 + 1, next - from + (i + 1 < beats.length ? FADE : 0));
          return (
            <Sequence key={i} from={from} durationInFrames={len}>
              <BeatLayer beat={beat} duration={len} slideTitle={slide.title} />
            </Sequence>
          );
        })}
      </div>
      <div style={{ position: "absolute", left: 0, bottom: 0, height: 8, width: `${interpolate(f, [0, total], [0, 100], clamp)}%`, background: C.forest }} />
    </AbsoluteFill>
  );
}

export const LESSON_INTRO = 4 * FPS;

export function Lesson({ data, intro }: { data: LessonData; intro?: string }) {
  return (
    <AbsoluteFill style={{ background: C.paper }}>
      <Series>
        {intro ? (
          <Series.Sequence durationInFrames={LESSON_INTRO}>
            <Video src={staticFile(intro)} muted />
          </Series.Sequence>
        ) : null}
        {data.slides.map((slide, i) => (
          <Series.Sequence key={slide.id} durationInFrames={Math.ceil(slide.duration * FPS)}>
            <SlideView slide={slide} lessonId={data.id} index={i} count={data.slides.length} />
          </Series.Sequence>
        ))}
      </Series>
    </AbsoluteFill>
  );
}
