import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
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
  | "disabled"
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

/** Ends the hold when this pointer lifts or is cancelled anywhere on `target` (the window). Used
 * when pointer capture fails, so a release outside the button still stops the action. Returns the
 * cleanup. */
export function endOnWindowRelease(
  target: EventTarget,
  pointerId: number,
  end: (reason: "pointerup" | "pointercancel") => void,
): () => void {
  const listener = (e: Event) => {
    if ((e as PointerEvent).pointerId === pointerId) end(e.type as "pointerup" | "pointercancel");
  };
  target.addEventListener("pointerup", listener);
  target.addEventListener("pointercancel", listener);
  return () => {
    target.removeEventListener("pointerup", listener);
    target.removeEventListener("pointercancel", listener);
  };
}

type Phase = "idle" | "holding" | "running";

/** A button for a physical action. `while-held` runs the action only while it is held (pump
 * prime); `hold-to-confirm` starts a fixed action after an unbroken hold (test shot). Pointer or
 * Space only. With `disabledReason` it does nothing and shows why; becoming disabled mid-hold
 * stops the action at once.
 *
 * Keep `mode`, `maxSeconds` and `confirmMs` stable during a hold: a change rebuilds the controller,
 * which stops the running action. */
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
  const stopWindowWatch = useRef<(() => void) | null>(null);
  const end = (reason: HoldEnd) => {
    stopWindowWatch.current?.();
    stopWindowWatch.current = null;
    hold.release(reason);
    setPhase("idle");
  };
  // Disabling mid-hold (dosing paused, another pump started) must stop the action now, not at
  // maxSeconds: the end handlers below stay attached too, but this does not wait for the finger.
  useLayoutEffect(() => {
    if (disabledReason) end("disabled");
  }, [disabledReason, hold]); // `end` only closes over `hold`.
  useEffect(() => {
    const blur = () => end("blur");
    const visibility = () => document.visibilityState === "hidden" && end("visibilitychange");
    window.addEventListener("blur", blur);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      window.removeEventListener("blur", blur);
      document.removeEventListener("visibilitychange", visibility);
      stopWindowWatch.current?.();
      hold.release("unmount");
    };
  }, [hold]); // `end` only closes over `hold`.

  const start = () => {
    hold.press();
    if (mode === "hold-to-confirm") setPhase("holding");
  };
  const status =
    phase === "running" ? "Running · let go to stop" : phase === "holding" ? "Keep holding…" : null;

  const disabled = !!disabledReason;
  return (
    <span className="hold-button-wrap">
      <button
        type="button"
        className="hold-button"
        data-mode={mode}
        data-state={disabled ? "disabled" : phase}
        aria-disabled={disabled ? "true" : undefined}
        aria-describedby={disabled ? reasonId : undefined}
        aria-pressed={mode === "while-held" && !disabled ? phase === "running" : undefined}
        style={{ "--confirm-ms": `${confirmMs}ms` } as CSSProperties}
        onPointerDown={(e) => {
          if (disabled) return;
          if (!isRealPress({ type: "pointerdown", isTrusted: e.nativeEvent.isTrusted, button: e.button, isPrimary: e.isPrimary }))
            return;
          try {
            e.currentTarget.setPointerCapture(e.pointerId);
          } catch {
            // Without capture, a finger lifted outside the button never reaches it: watch the window.
            stopWindowWatch.current?.();
            stopWindowWatch.current = endOnWindowRelease(window, e.pointerId, end);
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
          if (!disabled && isRealPress({ type: "keydown", isTrusted: e.nativeEvent.isTrusted, key: e.key, repeat: e.repeat }))
            start();
        }}
        onKeyUp={(e) => {
          if (e.key !== " ") return;
          e.preventDefault();
          end("keyup");
        }}
      >
        {mode === "hold-to-confirm" && !disabled && <span className="hold-button-fill" aria-hidden="true" />}
        <span>{label}</span>
        <span className="sr-only">{srLabel}</span>
        {status && !disabled && <span className="hold-button-status">{status}</span>}
      </button>
      {disabled && (
        <span className="hold-button-reason" id={reasonId}>
          {disabledReason}
        </span>
      )}
    </span>
  );
}