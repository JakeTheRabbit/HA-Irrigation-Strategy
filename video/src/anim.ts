import { interpolate, spring, useCurrentFrame, useVideoConfig, Easing } from "remotion";

// Shared motion helpers so every scene animates with the same feel.
export const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

// 0→1 ease over `len` frames starting at `start`.
export function useReveal(start = 0, len = 18) {
  const f = useCurrentFrame();
  return interpolate(f, [start, start + len], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
}

// Spring pop-in starting at `start`.
export function usePop(start = 0) {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: f - start, fps, config: { damping: 14, stiffness: 120 } });
}

// Linear progress 0→1 between two frames.
export function useProgress(start: number, end: number) {
  const f = useCurrentFrame();
  return interpolate(f, [start, Math.max(start + 1, end)], [0, 1], clamp);
}

// Frame at which step i is spoken, falling back to an even spread across the beat.
export function stepAt(steps: number[], i: number, duration: number, count = steps.length || 1) {
  const s = steps[i];
  if (Number.isFinite(s)) return s;
  return Math.round((duration * i) / Math.max(count, 1) * 0.8);
}

export const fadeUp = (p: number, dist = 30) => ({ opacity: p, transform: `translateY(${(1 - p) * dist}px)` });
