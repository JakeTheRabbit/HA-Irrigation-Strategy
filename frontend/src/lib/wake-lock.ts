import { useEffect } from "react";

/** Whether this browser can keep the screen on. */
export function wakeLockSupported(nav: Navigator | undefined): boolean {
  return !!nav && "wakeLock" in nav && !!nav.wakeLock;
}

type Sentinel = { released: boolean; release(): Promise<void> };

/** One screen lock, asked for again whenever `acquire` runs and none is held. Only one request is
 * in flight at a time, and a lock granted after `dispose` is released at once. */
export function createWakeLock(lock: { request(type: "screen"): Promise<Sentinel> }, visible: () => boolean) {
  let held: Sentinel | null = null;
  let pending = false;
  let done = false;
  return {
    acquire() {
      if (done || pending || !visible() || (held && !held.released)) return;
      pending = true;
      lock.request("screen").then(
        (sentinel) => {
          pending = false;
          if (done) void sentinel.release().catch(() => {});
          else held = sentinel;
        },
        () => {
          // Refused (battery saver, no user gesture yet): the screen just follows its own timeout.
          pending = false;
        },
      );
    },
    dispose() {
      done = true;
      void held?.release().catch(() => {});
    },
  };
}

/** Keeps the screen on while `active`. The browser drops the lock when the page is hidden, so it
 * is asked for again when the page shows. Does nothing where unsupported or refused. */
export function useWakeLock(active: boolean): { supported: boolean } {
  const supported = wakeLockSupported(typeof navigator === "undefined" ? undefined : navigator);
  useEffect(() => {
    if (!active || !supported) return;
    const wake = createWakeLock(navigator.wakeLock, () => document.visibilityState === "visible");
    const acquire = () => wake.acquire();
    acquire();
    document.addEventListener("visibilitychange", acquire);
    return () => {
      document.removeEventListener("visibilitychange", acquire);
      wake.dispose();
    };
  }, [active, supported]);
  return { supported };
}
