import { useEffect, useRef, useState } from "react";

/** Unapplied edits, kept per tab in sessionStorage so a reload or a page change does not lose
 * them, and shared with this browser's other tabs over a BroadcastChannel. Storage that is
 * disabled or full only loses the copy: the draft still works on the page. */
export const DRAFT_PREFIX = "crop-steering.draft.";
const CHANNEL = "crop-steering-drafts";

export const isSameDraft = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export function draftStore(storage: () => Storage | null | undefined) {
  return {
    read<T>(key: string): T | undefined {
      try {
        const text = storage()?.getItem(DRAFT_PREFIX + key);
        return text == null ? undefined : (JSON.parse(text) as T);
      } catch {
        return undefined;
      }
    },
    write(key: string, value: unknown) {
      try {
        storage()?.setItem(DRAFT_PREFIX + key, JSON.stringify(value));
      } catch {
        /* Kept on the page only. */
      }
    },
    clear(key: string) {
      try {
        storage()?.removeItem(DRAFT_PREFIX + key);
      } catch {
        /* Nothing kept. */
      }
    },
    /** Clears every draft whose key starts with `prefix`; returns the keys cleared. */
    clearAll(prefix: string): string[] {
      try {
        const store = storage();
        if (!store) return [];
        const keys: string[] = [];
        for (let i = 0; i < store.length; i++) {
          const name = store.key(i);
          if (name?.startsWith(DRAFT_PREFIX + prefix)) keys.push(name.slice(DRAFT_PREFIX.length));
        }
        for (const key of keys) store.removeItem(DRAFT_PREFIX + key);
        return keys;
      } catch {
        return [];
      }
    },
  };
}

const session = draftStore(() => sessionStorage);

/** Discards this tab's drafts under `prefix` (e.g. "targets:", every Current day zone) and tells
 * the other tabs: the app's discard and room switch, so a reload never brings them back. */
export function discardDrafts(prefix: string) {
  for (const key of session.clearAll(prefix)) publishDraft(key, undefined);
}

/** How a page's own draft and the stored copy meet, from their JSON: `store` the page's edit,
 * `restore` the stored one (a reload, or another tab's edit), or `none`. On the first run for a key
 * (`lastLocal` null) the page's own draft wins over a stored copy; with none, the copy comes back. */
export function draftSync(
  first: boolean,
  local: string,
  lastLocal: string | null,
  kept: string,
): "store" | "restore" | "none" {
  const empty = (json: string) => json === "{}";
  if (first) return !empty(local) ? (local === kept ? "none" : "store") : empty(kept) ? "none" : "restore";
  if (local !== lastLocal) return local === kept ? "none" : "store";
  return kept === local ? "none" : "restore";
}

/** Tells this browser's other tabs the draft under `key` (undefined: discarded). */
export function publishDraft(key: string, value: unknown) {
  try {
    const channel = new BroadcastChannel(CHANNEL);
    channel.postMessage({ key, value });
    channel.close();
  } catch {
    /* No other tabs to tell. */
  }
}
/** Hears the other tabs' drafts under `key`; returns the unsubscribe. */
export function subscribeDrafts(key: string, onValue: (value: unknown) => void): () => void {
  let channel: BroadcastChannel | null = null;
  try {
    channel = new BroadcastChannel(CHANNEL);
    channel.onmessage = (event: MessageEvent<{ key: string; value?: unknown }>) => {
      if (event.data?.key === key) onValue(event.data.value);
    };
  } catch {
    /* This tab only. */
  }
  return () => channel?.close();
}

/** The draft of `saved` under `key`: `saved` itself until something is set. Pages pass their
 * `onDirtyChange` (the app's leave-page guard). */
export function useDraft<T>(
  key: string,
  saved: T,
  onDirtyChange?: (dirty: boolean) => void,
): { draft: T; set(next: T): void; dirty: boolean; discard(): void } {
  const [held, setHeld] = useState<{ key: string; value: T | undefined }>(() => ({ key, value: session.read<T>(key) }));
  const value = held.key === key ? held.value : session.read<T>(key);
  if (held.key !== key) setHeld({ key, value });
  const dirty = value !== undefined && !isSameDraft(value, saved);

  useEffect(() => subscribeDrafts(key, (next) => setHeld({ key, value: next as T | undefined })), [key]);

  const report = useRef(onDirtyChange);
  report.current = onDirtyChange;
  useEffect(() => report.current?.(dirty), [dirty]);
  useEffect(() => () => report.current?.(false), []);

  const store = (next: T | undefined) => {
    if (next === undefined) session.clear(key);
    else session.write(key, next);
    setHeld({ key, value: next });
    publishDraft(key, next);
  };
  return {
    draft: value ?? saved,
    dirty,
    set: (next) => store(isSameDraft(next, saved) ? undefined : next),
    discard: () => store(undefined),
  };
}
