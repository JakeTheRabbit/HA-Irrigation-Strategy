import { useEffect, useRef, useState } from "react";
import { number } from "@/components/dashboard";
import "./primitives.css";

const clamp01 = (v: number) => Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0));

/** A circle filled clockwise from the top to `share` (0–1). */
function RingArc({ size, stroke, share }: { size: number; stroke: number; share: number }) {
  const r = (size - stroke) / 2,
    c = size / 2,
    length = 2 * Math.PI * r;
  return (
    <>
      <circle className="ring-track" cx={c} cy={c} r={r} strokeWidth={stroke} />
      <circle
        className="ring-fill"
        cx={c}
        cy={c}
        r={r}
        strokeWidth={stroke}
        strokeDasharray={`${(length * clamp01(share)).toFixed(2)} ${length.toFixed(2)}`}
        transform={`rotate(-90 ${c} ${c})`}
      />
    </>
  );
}

/** A small ring with the percentage inside and the label beside it. */
export function HealthRing({ pct, label }: { pct: number; label: string }) {
  const tone = pct >= 90 ? "ok" : pct >= 70 ? "warn" : "bad";
  return (
    <span className="health-ring" data-tone={tone}>
      <svg viewBox="0 0 56 56" width={56} height={56} role="img" aria-label={`${label} ${number(pct)}%`}>
        <RingArc size={56} stroke={6} share={pct / 100} />
        <text x="28" y="33" textAnchor="middle" aria-hidden="true">
          {number(pct)}
        </text>
      </svg>
      <span className="health-ring-label">{label}</span>
    </span>
  );
}

const ANNOUNCE_EVERY_MS = 5_000;

/** Whether a live reading may be spoken now: at most once every 5 s, and at once on reaching
 * Steady. `lastMs` is when the last announcement was made, or null for none yet. */
export function announceThrottle(nowMs: number, lastMs: number | null, reachedSteady = false): boolean {
  return reachedSteady || lastMs === null || nowMs - lastMs >= ANNOUNCE_EVERY_MS;
}

const STATE_WORD = { settling: "Settling…", steady: "Steady", offline: "Offline" } as const;

/** A large ring around a live reading that fills as the reading holds still. Screen readers hear
 * the reading at most every 5 s, and when it turns Steady. */
export function StabilityRing({
  value,
  caption,
  state,
  progress,
}: {
  value: string;
  caption: string;
  state: "settling" | "steady" | "offline";
  /** 0–1: how far through the hold-still window the reading is. */
  progress: number;
}) {
  const [spoken, setSpoken] = useState("");
  const last = useRef<{ at: number | null; state: string }>({ at: null, state });
  useEffect(() => {
    const now = Date.now();
    const reachedSteady = state === "steady" && last.current.state !== "steady";
    if (announceThrottle(now, last.current.at, reachedSteady)) {
      setSpoken(`${caption} ${value}, ${STATE_WORD[state]}`);
      last.current.at = now;
    }
    last.current.state = state;
  }, [value, caption, state]);
  return (
    <div className="stability-ring" data-state={state}>
      <svg viewBox="0 0 264 264" aria-hidden="true">
        <RingArc size={264} stroke={16} share={state === "steady" ? 1 : progress} />
      </svg>
      <div className="stability-ring-body" aria-hidden="true">
        <span className="stability-ring-caption">{caption}</span>
        <span className="stability-ring-value">{value}</span>
        <span className="stability-ring-state">{STATE_WORD[state]}</span>
      </div>
      <span className="sr-only" role="status">
        {spoken}
      </span>
    </div>
  );
}
