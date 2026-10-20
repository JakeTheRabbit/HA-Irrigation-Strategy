import React from "react";
import { Composition, staticFile, type CalculateMetadataFunction } from "remotion";
import { Lesson, LESSON_INTRO } from "./Lesson";
import { Gallery, GALLERY_ITEMS, ScenePreview } from "./Gallery";
import { FPS, W, H } from "./theme";
import type { LessonData } from "./types";

const IDS = "A1 A2 A3 A4 A5 A6 B1 B2 B3 B4 C1 C2a C2b C3 C4 C5 C6 C7 D1 D2 D3 D4 D5 D6".split(" ");

type Props = { id: string; data?: LessonData; intro?: string };

const load: CalculateMetadataFunction<Props> = async ({ props }) => {
  const data: LessonData = await (await fetch(staticFile(`data/${props.id}.json`))).json();
  const frames = data.slides.reduce((n, s) => n + Math.ceil(s.duration * FPS), 0) + (props.intro ? LESSON_INTRO : 0);
  return { durationInFrames: frames, props: { ...props, data } };
};

export const Root: React.FC = () => (
  <>
    {IDS.map((id) => (
      <Composition
        key={id}
        id={`lesson-${id}`}
        component={({ data, intro }: Props) => (data ? <Lesson data={data} intro={intro} /> : null)}
        durationInFrames={FPS}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={{ id } as Props}
        calculateMetadata={load}
      />
    ))}
    <Composition id="gallery" component={Gallery} durationInFrames={GALLERY_ITEMS.length * 6 * FPS} fps={FPS} width={W} height={H} />
    <Composition id="scene" component={ScenePreview} durationInFrames={8 * FPS} fps={FPS} width={W} height={H} defaultProps={{ name: "Title" }} />
  </>
);
