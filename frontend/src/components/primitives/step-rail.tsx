import { useEffect, useRef } from "react";
import { Check } from "lucide-react";
import "./primitives.css";

/** The steps of a wizard. `current` is the 1-based number of the step in progress; earlier steps
 * show as done. When `current` changes, focus moves to the new step's heading, never on first
 * render. `compact` (phone) draws a bar per step with the current title as a heading below. */
export function StepRail({
  steps,
  current,
  compact = false,
}: {
  steps: { title: string; detail: string }[];
  current: number;
  compact?: boolean;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const shown = useRef(current);
  useEffect(() => {
    if (shown.current === current) return;
    shown.current = current;
    heading.current?.focus();
  }, [current]);
  const now = steps[current - 1];
  const state = (i: number) => (i + 1 < current ? "done" : i + 1 === current ? "current" : "next");
  if (compact)
    return (
      <div className="step-rail" data-compact="" data-current={current}>
        <ol className="step-rail-bars" aria-label={`Step ${current} of ${steps.length}`}>
          {steps.map((step, i) => (
            <li
              key={i}
              data-done={state(i) === "done" ? "" : undefined}
              aria-current={state(i) === "current" ? "step" : undefined}
            >
              <span className="sr-only">{step.title}</span>
            </li>
          ))}
        </ol>
        {now && (
          <h2 className="step-rail-heading" tabIndex={-1} ref={heading}>
            {now.title}
          </h2>
        )}
      </div>
    );
  return (
    <ol className="step-rail" data-current={current} aria-label={`Step ${current} of ${steps.length}`}>
      {steps.map((step, i) => (
        <li
          key={i}
          data-done={state(i) === "done" ? "" : undefined}
          aria-current={state(i) === "current" ? "step" : undefined}
        >
          <span className="step-rail-dot" aria-hidden="true">
            {state(i) === "done" ? <Check size={18} strokeWidth={3} /> : i + 1}
          </span>
          <span className="step-rail-text">
            <h2
              className="step-rail-title"
              tabIndex={state(i) === "current" ? -1 : undefined}
              ref={state(i) === "current" ? heading : undefined}
            >
              {step.title}
            </h2>
            <span>{step.detail}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}
