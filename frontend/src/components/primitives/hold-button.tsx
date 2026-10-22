import { useEffect, useId, useMemo, useRef, useState, type CSSProperties } from "react";
import "./primitives.css";

/** Every way a hold can end. Each one stops a `while-held` action. */
export type HoldEnd =
  | "pointerup"
  | "pointercancel"
  | "lostpointercapture"
  | "blur"
  | "visibilitychange"
  | "keyup"
  | "unmount"
  | "max";

/** The hold logic, free of the DOM.
 * - `while-held`: `onStart` on press; `onStop` exactly once when the hold ends, however it ends,
 *   or after `maxSeconds`.
 * - `hold-to-confirm`: `onStart` once after `confirmMs` of unbroken hold; ending earlier cancels.
 *   `onStop` is not used. */
export function holdController({
  mode,
  maxSeconds,
  confirmMs = 1500,
  onStart,
  onStop,
}: {
  mode: "while-held" | "hold-to-confirm";
  maxSeconds: number;
  confirmMs?: number;
  onStart(): void;
  onStop?(): void;
}) {
  let pressed = false;
  let running = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const release = (_reason: HoldEnd) => {
    if (!pressed) return;
    pressed = false;
    clearTimeout(timer);
    timer = undefined;
    if (running) {
      running = false;
      onStop?.();
    }
  };
  const press = () => {
    if (pressed) return;
    pressed = true;
    if (mode === "while-held") {
      running = true;
      timer = setTimeout(() => release("max"), maxSeconds * 1000);
      onStart();
    } else {
      timer = setTimeout(() => {
        timer = undefined;
        onStart();
      }, confirmMs);
    }
  };
  return { press, release, active: () => running, pressed: () => pressed };
}

/** Whether an input event is a real press: a trusted primary-button pointer down, or a trusted,
 * non-repeating Space. Enter, clicks and script-made events never count. */
export function isRealPress(e: {
  type: string;
  isTrusted: boolean;
  button?: number;
  isPrimary?: boolean;
  key?: string;
  repeat?: boolean;
}): boolean {
  if (!e.isTrusted) return false;
  if (e.type === "pointerdown") return e.button === 0 && e.isPrimary === true;
  if (e.type === "keydown") return e.key === " " && !e.repeat;
  return false;
}

type Phase = "idle" | "holding" | "running";

/** A button for a physical action. `while-held` runs the action only while it is held (pump
 * prime); `hold-to-confirm` starts a fixed action after an unbroken hold (test shot). Pointer or
 * Space only. With `disabledReason` it does nothing and shows why. */
export function HoldButton({
  mode,
  label,
  srLabel,
  maxSeconds,
  confirmMs = 1500,
  disabledReason,
  onStart,
  onStop,
}: {
  mode: "while-held" | "hold-to-confirm";
  label: string;
  /** Read after the label: what holding does and how it ends. */
  srLabel: string;
  maxSeconds: number;
  confirmMs?: number;
  disabledReason?: string;
  onStart(): void;
  onStop?(): void;
}) {
  const reasonId = useId();
  const [phase, setPhase] = useState<Phase>("idle");
  const latest = useRef({ onStart, onStop });
  latest.current = { onStart, onStop };
  const hold = useMemo(
    () =>
      holdController({
        mode,
        maxSeconds,
        confirmMs,
        onStart: () => {
          navigator.vibrate?.(30);
          setPhase(mode === "while-held" ? "running" : "idle");
          latest.current.onStart();
        },
        onStop: () => {
          setPhase("idle");
          latest.current.onStop?.();
        },
      }),
    [mode, maxSeconds, confirmMs],
  );
  const end = (reason: HoldEnd) => {
    hold.release(reason);
    setPhase("idle");
  };
  useEffect(() => {
    const blur = () => end("blur");
    const visibility = () => document.visibilityState === "hidden" && end("visibilitychange");
    window.addEventListener("blur", blur);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      window.removeEventListener("blur", blur);
      document.removeEventListener("visibilitychange", visibility);
      hold.release("unmount");
    };
  }, [hold]); // `end` only closes over `hold`.

  const start = () => {
    hold.press();
    if (mode === "hold-to-confirm") setPhase("holding");
  };
  const status =
    phase === "running" ? "Running · let go to stop" : phase === "holding" ? "Keep holding…" : null;

  if (disabledReason)
    return (
      <span className="hold-button-wrap">
        <button
          type="button"
          className="hold-button"
          data-mode={mode}
          data-state="disabled"
          aria-disabled="true"
          aria-describedby={reasonId}
        >
          <span>{label}</span>
          <span className="sr-only">{srLabel}</span>
        </button>
        <span className="hold-button-reason" id={reasonId}>
          {disabledReason}
        </span>
      </span>
    );
  return (
    <span className="hold-button-wrap">
      <button
        type="button"
        className="hold-button"
        data-mode={mode}
        data-state={phase}
        aria-pressed={mode === "while-held" ? phase === "running" : undefined}
        style={{ "--confirm-ms": `${confirmMs}ms` } as CSSProperties}
        onPointerDown={(e) => {
          if (!isRealPress({ type: "pointerdown", isTrusted: e.nativeEvent.isTrusted, button: e.button, isPrimary: e.isPrimary }))
            return;
          try {
            e.currentTarget.setPointerCapture(e.pointerId);
          } catch {
            // Capture can fail on a pointer that already lifted; the up/cancel handlers still end it.
          }
          start();
        }}
        onPointerUp={() => end("pointerup")}
        onPointerCancel={() => end("pointercancel")}
        onLostPointerCapture={() => end("lostpointercapture")}
        onBlur={() => end("blur")}
        onContextMenu={(e) => e.preventDefault()}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.preventDefault();
          if (e.key !== " ") return;
          e.preventDefault();
          if (isRealPress({ type: "keydown", isTrusted: e.nativeEvent.isTrusted, key: e.key, repeat: e.repeat })) start();
        }}
        onKeyUp={(e) => {
          if (e.key !== " ") return;
          e.preventDefault();
          end("keyup");
        }}
      >
        {mode === "hold-to-confirm" && <span className="hold-button-fill" aria-hidden="true" />}
        <span>{label}</span>
        <span className="sr-only">{srLabel}</span>
        {status && <span className="hold-button-status">{status}</span>}
      </button>
    </span>
  );
}
