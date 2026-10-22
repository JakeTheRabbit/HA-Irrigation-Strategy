import { useEffect } from "react";

/** Whether this browser can keep the screen on. */
export function wakeLockSupported(nav: Navigator | undefined): boolean {
  return !!nav && "wakeLock" in nav && !!nav.wakeLock;
}

/** Keeps the screen on while `active`. The browser drops the lock when the page is hidden, so it
 * is asked for again when the page shows. Does nothing where unsupported or refused. */
export function useWakeLock(active: boolean): { supported: boolean } {
  const supported = wakeLockSupported(typeof navigator === "undefined" ? undefined : navigator);
  useEffect(() => {
    if (!active || !supported) return;
    let lock: WakeLockSentinel | null = null;
    let done = false;
    const acquire = () => {
      if (document.visibilityState !== "visible" || (lock && !lock.released)) return;
      navigator.wakeLock.request("screen").then(
        (sentinel) => {
          if (done) void sentinel.release();
          else lock = sentinel;
        },
        () => {}, // Refused (battery saver, no user gesture yet): the screen just follows its own timeout.
      );
    };
    acquire();
    document.addEventListener("visibilitychange", acquire);
    return () => {
      done = true;
      document.removeEventListener("visibilitychange", acquire);
      void lock?.release().catch(() => {});
    };
  }, [active, supported]);
  return { supported };
}
