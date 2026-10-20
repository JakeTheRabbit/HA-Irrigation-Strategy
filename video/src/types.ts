export type Word = { w: string; s: number; e: number };

// One visual beat on a slide. `at` is seconds from slide start (resolved from `cue`).
// `steps` are seconds from the beat start, resolved from spoken step phrases, so a
// component can reveal parts exactly when the narrator says them.
export type Beat = {
  type: string;
  cue?: string;
  at: number;
  steps: (number | null)[];
  props?: Record<string, unknown>;
};

export type SlideData = {
  id: string;
  title: string;
  duration: number;
  audio: { src: string; start: number; duration: number }[];
  beats: Beat[];
  words: Word[];
};

export type LessonData = { id: string; title: string; summary: string; slides: SlideData[] };

// Props every scene component receives.
export type SceneProps<P = Record<string, unknown>> = {
  props: P;
  // Frames from beat start at which each step is spoken (null = not found; treat as 0).
  steps: number[];
  // Beat length in frames.
  duration: number;
  slideTitle: string;
};
