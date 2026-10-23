import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, TrendingUp } from "lucide-react";
import { Heading } from "@/components/dashboard";
import { NeedsIntegration } from "@/components/needs-integration";
import { runApply, type ApplyReceipt, type ApplyState } from "@/components/review-apply";
import { Button } from "@/components/ui/button";
import {
  CHANGE_KINDS,
  KIND_LABEL,
  changeWords,
  changesHash,
  changesQuery,
  countBy,
  fromSetpointLog,
  groupByDay,
  revertChange,
  toEntries,
  undoRevert,
  type ChangeEntry,
  type ChangesQuery,
  type SetpointLogRow,
} from "@/lib/changes";
import { callV2, type V2Outcome } from "@/lib/parity-api";
import type { HistoryChange } from "@/lib/parity-types";
import { parseTarget } from "@/lib/presets";
import { clock, dayLabel } from "@/lib/time";
import type { Controller } from "@/lib/types";
import { offerUndo } from "@/lib/undo";
import { useNarrow } from "@/lib/use-narrow";
import type { PageProps } from "./placeholder";
import "./changes.css";

const DAY = 86_400_000;
const WEEK = 7 * DAY;
/** `history_changes` answers at most this many rows, the newest (journal_api.MAX_CHANGES). */
const MAX_ROWS = 2000;
type Refusal = Extract<V2Outcome<unknown>, { kind: "error" | "missing" }>;
type Feed =
  | { state: "loading"; backend?: "3.18" | "3.17"; entries: ChangeEntry[] }
  | { state: "ready"; backend: "3.18" | "3.17"; entries: ChangeEntry[]; truncated: boolean }
  | { state: "error"; message: string; entries: ChangeEntry[] };

const readHash = () => changesQuery(typeof window === "undefined" ? "" : window.location.hash);

/** History › Changes (mockup 12): every setting change, who made it, why and how it worked out,
 * by day, filtered by who and what, with the one picked shown beside the list and put back with
 * Undo. All rooms until the room list narrows it; a 3.17 integration reads the selected room's
 * setting log. */
export function Changes({ controller }: PageProps) {
  const [query, setQuery] = useState<ChangesQuery>(readHash);
  // "Last 7 days" counts back from when the page opened.
  const [opened] = useState(() => Date.now());
  const narrow = useNarrow(720);
  const words = useMemo(() => changeWords(controller.states, controller.rooms), [controller.states, controller.rooms]);
  const wordsRef = useRef(words);
  wordsRef.current = words;
  const scope = query.room ? parseTarget(query.room) : null;
  const since = query.since && Number.isFinite(Date.parse(query.since)) ? Date.parse(query.since) : opened - WEEK;
  const until = query.until && Number.isFinite(Date.parse(query.until)) ? Date.parse(query.until) : null;

  const update = useCallback((patch: Partial<ChangesQuery>) => {
    const next = { ...readHash(), ...patch };
    for (const key of Object.keys(patch) as (keyof ChangesQuery)[]) if (!patch[key]) delete next[key];
    next.since ??= "";
    window.history.replaceState(window.history.state, "", changesHash(next));
    setQuery(next);
  }, []);
  // The room list narrows the page by changing the address (App.tsx).
  useEffect(() => {
    const read = () => setQuery(readHash());
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);

  const [feed, setFeed] = useState<Feed>({ state: "loading", entries: [] });
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  useEffect(() => {
    let current = true;
    setFeed((previous) => ({ state: "loading", entries: previous.entries, backend: "backend" in previous ? previous.backend : undefined }));
    void loadChanges(controller, { since, until, scope }, wordsRef.current).then((next) => {
      if (current) setFeed(next);
    });
    return () => {
      current = false;
    };
    // controller.roomId: a 3.17 integration reads the selected room's log.
  }, [since, until, query.room, controller.roomId, tick]);

  const entries = feed.entries;
  const backend = "backend" in feed ? feed.backend : undefined;
  const shown = entries.filter((e) => (!query.actor || e.actor === query.actor) && (!query.kind || e.kind === query.kind));
  const selected = entries.find((e) => e.id === query.id) ?? null;
  const actors = countBy(entries, "actor");
  const kinds = countBy(entries, "kind");
  const days = Math.round(((until ?? opened) - since) / DAY);
  const period = query.since && !Number.isInteger(days / 7) ? `since ${dayLabel(since, controller.timeZone)}` : `last ${days} days`;

  // Putting one change back: its state, by entry. A put-back and its Undo check the states as they
  // are when sent, not when the button was drawn.
  const latest = useRef(controller);
  latest.current = controller;
  const [revert, setRevert] = useState<{ id: string; state: ApplyState } | null>(null);
  const undo = async (entry: ChangeEntry, receipt: ApplyReceipt) => {
    setRevert({ id: entry.id, state: { phase: "undoing", receipt } });
    try {
      await undoRevert(latest.current, latest.current.states, entry, receipt);
      setRevert({ id: entry.id, state: { phase: "undone", at: Date.now() } });
      reload();
    } catch (error) {
      const reverted = (error as { reverted?: unknown } | null)?.reverted;
      setRevert({
        id: entry.id,
        state: {
          phase: "undo-failed",
          receipt,
          reverted: typeof reverted === "number" ? reverted : 0,
          message: error instanceof Error && error.message ? error.message : "Undo failed.",
        },
      });
      throw error;
    }
  };
  const putBack = async (entry: ChangeEntry) => {
    if (query.id !== entry.id) update({ id: entry.id });
    const result = await runApply(
      () => revertChange(latest.current, latest.current.states, entry),
      (state) => setRevert({ id: entry.id, state }),
    );
    if ("ok" in result && result.ok) {
      offerUndo({
        message: `${result.summary}. Written and read back ${clock(result.at, controller.timeZone)}.`,
        undo: () => undo(entry, result),
      });
      reload();
    }
  };

  // Scrolling to the end of the list reads the 7 days before it, while a week still adds some.
  const sentinel = useRef<HTMLDivElement>(null);
  const auto = useRef({ before: -1, on: true });
  const older = useCallback(() => {
    auto.current.before = entries.length;
    update({ since: new Date(since - WEEK).toISOString() });
  }, [entries.length, since, update]);
  useEffect(() => {
    if (feed.state === "ready" && auto.current.before >= 0)
      auto.current = { before: -1, on: feed.entries.length > auto.current.before };
  }, [feed]);
  useEffect(() => {
    const element = sentinel.current;
    if (!element || feed.state !== "ready" || !auto.current.on || typeof IntersectionObserver === "undefined") return;
    let scrolled = false;
    const onScroll = () => (scrolled = true);
    window.addEventListener("scroll", onScroll, { passive: true, once: true });
    const observer = new IntersectionObserver((seen) => {
      if (scrolled && seen.some((s) => s.isIntersecting)) older();
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", onScroll);
    };
  }, [feed.state, older]);

  const scopeName = scope
    ? `${words.room(scope.room_id)}${scope.zone !== undefined ? ` · Zone ${scope.zone}` : ""}`
    : null;
  const panel = (entry: ChangeEntry | null) => (
    <SelectedChange
      controller={controller}
      entry={entry}
      revert={entry && revert?.id === entry.id ? revert.state : { phase: "idle" }}
      onRevert={putBack}
      onUndo={(entry, receipt) => void undo(entry, receipt).catch(() => {})}
      onReload={reload}
    />
  );
  return (
    <>
      <Heading title="Changes" />
      <div className="changes" data-changes-backend={backend}>
        <p className="changes-scope" data-changes-scope>
          {backend === "3.17" ? (
            <>
              Showing <strong>{words.room(controller.roomId)}</strong>: this integration keeps each room's setting log
              apart. Pick another room in the room list to see its changes.
            </>
          ) : scopeName ? (
            <>
              Showing <strong>{scopeName}</strong>.{" "}
              <Button variant="link" size="sm" onClick={() => update({ room: undefined, id: undefined })}>
                Show all rooms
              </Button>
            </>
          ) : (
            <>
              Showing <strong>all rooms</strong>. Pick a room or zone in the room list to narrow it.
            </>
          )}
        </p>
        <div className="changes-filters">
          <div className="changes-chips" role="group" aria-label="Made by">
            <span className="changes-chips-label" aria-hidden="true">
              Made by
            </span>
            {[...actors.keys()].concat(query.actor && !actors.has(query.actor) ? [query.actor] : []).map((actor) => {
              const chip = entries.find((e) => e.actor === actor)?.chip ?? actor;
              return (
                <button
                  key={actor}
                  type="button"
                  className="changes-chip"
                  data-actor={actor}
                  aria-pressed={query.actor === actor}
                  onClick={() => update({ actor: query.actor === actor ? undefined : actor, id: undefined })}
                >
                  <span className="changes-dot" aria-hidden="true" />
                  {chip} <span className="changes-count">{actors.get(actor) ?? 0}</span>
                </button>
              );
            })}
          </div>
          <div className="changes-chips" role="group" aria-label="Kind">
            <span className="changes-chips-label" aria-hidden="true">
              Kind
            </span>
            {CHANGE_KINDS.filter((kind) => backend === "3.17" || kinds.has(kind) || query.kind === kind).map((kind) => {
              const needs = backend === "3.17" && kind !== "setpoint";
              return (
                <button
                  key={kind}
                  type="button"
                  className="changes-chip is-kind"
                  data-kind={kind}
                  aria-pressed={query.kind === kind}
                  disabled={needs}
                  title={needs ? "Needs Crop Steering 3.18 or newer" : undefined}
                  onClick={() => update({ kind: query.kind === kind ? undefined : kind, id: undefined })}
                >
                  {KIND_LABEL[kind]} {!needs && <span className="changes-count">{kinds.get(kind) ?? 0}</span>}
                </button>
              );
            })}
            {backend === "3.17" && <NeedsIntegration feature="Plan, recipe, setup, calibration and alert changes" compact />}
            <span className="changes-total muted" data-count>
              {shown.length} of {entries.length} changes · {period}
            </span>
          </div>
        </div>
        <div className="changes-body">
          <div className="changes-feed" aria-busy={feed.state === "loading"}>
            {feed.state === "error" && (
              <p role="alert" className="changes-error">
                {feed.message}{" "}
                <Button variant="outline" size="sm" onClick={reload}>
                  Try again
                </Button>
              </p>
            )}
            {feed.state === "ready" && feed.truncated && (
              <p className="muted small">Showing the newest {MAX_ROWS} changes of this period.</p>
            )}
            {feed.state !== "error" && !shown.length && feed.state === "ready" && (
              <p className="changes-empty muted" data-changes-empty>
                No changes in this period.
              </p>
            )}
            {groupByDay(shown, controller.timeZone, opened).map((day) => (
              <section key={day.key} className="changes-day" aria-label={day.title}>
                <h2 className="changes-day-title">{day.title}</h2>
                <ol className="changes-list">
                  {day.entries.map((entry) => (
                    <li key={entry.id} className="changes-entry" data-change={entry.id} data-selected={entry.id === selected?.id || undefined}>
                      <button
                        type="button"
                        className="changes-pick"
                        aria-pressed={entry.id === selected?.id}
                        onClick={() => update({ id: entry.id })}
                      >
                        <time dateTime={new Date(entry.at).toISOString()} className="changes-time">
                          {clock(entry.at, controller.timeZone)}
                        </time>
                        <span className="changes-main">
                          <span className="changes-line">
                            <ActorChip entry={entry} />
                            <span className="changes-where">{entry.scope}</span>
                            <strong className="changes-label">{entry.label}</strong>
                            <Diff entry={entry} />
                          </span>
                          {entry.reason && <span className="changes-reason">{entry.reason}</span>}
                          {entry.outcome && (
                            <span className="changes-outcome">
                              <TrendingUp size={14} aria-hidden="true" /> {entry.outcome}
                            </span>
                          )}
                        </span>
                      </button>
                      <RevertButton entry={entry} state={revert?.id === entry.id ? revert.state : undefined} onRevert={putBack} />
                      {narrow && entry.id === selected?.id && panel(entry)}
                    </li>
                  ))}
                </ol>
              </section>
            ))}
            <div ref={sentinel} className="changes-older">
              <Button variant="outline" size="sm" onClick={older} disabled={feed.state === "loading"} data-load-older>
                {feed.state === "loading" ? "Reading…" : `Show the 7 days before ${dayLabel(since, controller.timeZone)}`}
              </Button>
            </div>
          </div>
          {!narrow && panel(selected)}
        </div>
      </div>
    </>
  );
}

/** The change rows of a period: the Journal's on 3.18 (every room, or the picked room or zone), else
 * the selected room's setting log. */
async function loadChanges(
  controller: Controller,
  range: { since: number; until: number | null; scope: { room_id: string; zone?: number } | null },
  words: ReturnType<typeof changeWords>,
): Promise<Feed> {
  const iso = (ms: number) => new Date(ms).toISOString();
  const outcome = await callV2<{ changes: HistoryChange[]; truncated?: boolean }>(controller, "history_changes", {
    since: iso(range.since),
    ...(range.until !== null ? { until: iso(range.until) } : {}),
    ...(range.scope ? { room_id: range.scope.room_id } : {}),
    ...(range.scope?.zone !== undefined ? { zone: range.scope.zone } : {}),
  });
  if (outcome.kind === "ok")
    return { state: "ready", backend: "3.18", entries: toEntries(outcome.data?.changes ?? [], words), truncated: !!outcome.data?.truncated };
  if (outcome.kind === "error") return { state: "error", message: outcome.message, entries: [] };
  try {
    const log = await controller.operator<{ changes?: SetpointLogRow[]; error?: string | null }>("setpoint_log_get", {});
    if (log.error) return { state: "error", message: log.error, entries: [] };
    const entries = fromSetpointLog(log.changes ?? [], controller.roomId, words).filter(
      (e) =>
        e.at >= range.since &&
        (range.until === null || e.at < range.until) &&
        (range.scope?.zone === undefined || range.scope.room_id !== controller.roomId || e.zone === range.scope.zone),
    );
    return { state: "ready", backend: "3.17", entries, truncated: false };
  } catch (error) {
    return { state: "error", message: error instanceof Error ? error.message : "The setting log could not be read.", entries: [] };
  }
}

function ActorChip({ entry }: { entry: ChangeEntry }) {
  return (
    <span className="changes-chip is-static" data-actor={entry.actor}>
      <span className="changes-dot" aria-hidden="true" />
      {entry.chip}
    </span>
  );
}

function Diff({ entry }: { entry: ChangeEntry }) {
  if (!entry.after) return null;
  return (
    <span className="changes-diff">
      {entry.before && (
        <>
          <s>{entry.before}</s>
          <span aria-label="to"> → </span>
        </>
      )}
      <b>{entry.after}</b>
    </span>
  );
}

/** A row's put-back button, or why it has none. */
function RevertButton({
  entry,
  state,
  onRevert,
}: {
  entry: ChangeEntry;
  state?: ApplyState;
  onRevert(entry: ChangeEntry): void;
}) {
  if (!entry.revertible)
    return (
      <span className="changes-no-revert muted small" data-no-revert>
        {entry.revertLabel}
      </span>
    );
  const busy = state?.phase === "sending" || state?.phase === "undoing";
  return (
    <Button variant="outline" size="sm" className="changes-revert" disabled={busy} onClick={() => onRevert(entry)} data-revert={entry.id}>
      {state?.phase === "sending" ? "Sending…" : entry.revertLabel}
    </Button>
  );
}

/** The picked change: who and when, was and now on the setting's range, why, what happened next,
 * and putting it back. */
function SelectedChange({
  controller,
  entry,
  revert,
  onRevert,
  onUndo,
  onReload,
}: {
  controller: Controller;
  entry: ChangeEntry | null;
  revert: ApplyState;
  onRevert(entry: ChangeEntry): void;
  onUndo(entry: ChangeEntry, receipt: ApplyReceipt): void;
  onReload(): void;
}) {
  const tz = controller.timeZone;
  if (!entry)
    return (
      <aside className="changes-panel" aria-labelledby="changes-panel-title" data-selected-change="">
        <h2 id="changes-panel-title" className="changes-kicker">
          Selected change
        </h2>
        <p className="muted">Pick a change to see why it was made and what happened next.</p>
      </aside>
    );
  const busy = revert.phase === "sending" || revert.phase === "undoing";
  return (
    <aside className="changes-panel" aria-labelledby="changes-panel-title" data-selected-change={entry.id}>
      <h2 id="changes-panel-title" className="changes-kicker">
        Selected change
      </h2>
      <p className="changes-panel-who">
        <ActorChip entry={entry} />
        <span>
          {dayLabel(entry.at, tz)} at {clock(entry.at, tz)}
          {entry.user && entry.actor === "manual" ? ` · by ${entry.user}` : ""}
        </span>
      </p>
      <h3 className="changes-panel-title">{entry.label}</h3>
      <p className="muted">
        {entry.scope} · {KIND_LABEL[entry.kind]}
      </p>
      <WasNow controller={controller} entry={entry} />
      <h4 className="changes-kicker">Why</h4>
      <p data-why>{entry.reason ?? "No reason was recorded with this change."}</p>
      <h4 className="changes-kicker">What happened next</h4>
      <p data-next>{entry.outcome ?? "Nothing was measured after this change."}</p>
      <div className="changes-panel-foot">
        <RevertStatus entry={entry} state={revert} timeZone={tz} onUndo={onUndo} onReload={onReload} />
        {entry.revertible ? (
          revert.phase === "done" && "ok" in revert.result && revert.result.ok ? null : (
            <Button className="changes-panel-revert" disabled={busy} onClick={() => onRevert(entry)}>
              {revert.phase === "sending" ? "Sending…" : entry.revertLabel}
            </Button>
          )
        ) : (
          <p className="muted small">{entry.revertLabel}</p>
        )}
      </div>
    </aside>
  );
}

/** Was and now on the setting's own range, where the setting has one. */
function WasNow({ controller, entry }: { controller: Controller; entry: ChangeEntry }) {
  const attributes = entry.entityId ? controller.states[entry.entityId]?.attributes : undefined;
  const min = Number(attributes?.min);
  const max = Number(attributes?.max);
  const was = entry.oldValue;
  const now = entry.newValue;
  const bar =
    typeof was === "number" && typeof now === "number" && Number.isFinite(min) && Number.isFinite(max) && max > min;
  if (!entry.before && !entry.after && !entry.limits) return null;
  const at = (value: number) => `${Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100))}%`;
  return (
    <div className="changes-wasnow">
      {bar && (
        <div className="changes-range" aria-hidden="true">
          <span
            className="changes-range-move"
            style={{ left: at(Math.min(was, now)), width: `calc(${at(Math.max(was, now))} - ${at(Math.min(was, now))})` }}
          />
          <span className="changes-range-was" style={{ left: at(was) }} />
          <span className="changes-range-now" style={{ left: at(now) }} />
        </div>
      )}
      <p className="changes-wasnow-text">
        {entry.before && (
          <span>
            Was <b>{entry.before}</b>
          </span>
        )}
        {entry.after && (
          <span className="changes-now">
            Now <b>{entry.after}</b>
          </span>
        )}
        {entry.limits && <span className="muted changes-limits">{entry.limits}</span>}
      </p>
    </div>
  );
}

/** What putting the change back did: "Written and read back HH:MM" only when the controller read it
 * back. */
function RevertStatus({
  entry,
  state,
  timeZone,
  onUndo,
  onReload,
}: {
  entry: ChangeEntry;
  state: ApplyState;
  timeZone: string;
  onUndo(entry: ChangeEntry, receipt: ApplyReceipt): void;
  onReload(): void;
}) {
  if (state.phase === "undone")
    return (
      <p role="status" className="changes-receipt">
        <Check size={15} aria-hidden="true" /> Previous value written back {clock(state.at, timeZone)}
      </p>
    );
  const result = state.phase === "done" ? state.result : state.phase === "undoing" || state.phase === "undo-failed" ? state.receipt : null;
  if (!result) return null;
  if (!("ok" in result)) return <Refused result={result} onReload={onReload} />;
  if (!result.ok) {
    const text = result.unconfirmed || result.notConfirmed?.length
      ? "The controller did not confirm the value. Reload and check before trying again."
      : `${entry.label} is still ${result.failed[0]?.holds ?? entry.after}.`;
    return (
      <p role="alert" className="changes-error">
        {text}{" "}
        <Button variant="outline" size="sm" onClick={onReload}>
          Reload
        </Button>
      </p>
    );
  }
  return (
    <div role="status" className="changes-receipt" data-receipt>
      <p>
        <Check size={15} aria-hidden="true" /> <b>Written and read back {clock(result.at, timeZone)}</b>
      </p>
      <p className="small">{result.summary}</p>
      {result.undoUnavailable ? (
        <p className="small muted">Undo not available here: the put-back has no change of its own in the history yet.</p>
      ) : (
        <Button variant="outline" size="sm" disabled={state.phase === "undoing"} onClick={() => onUndo(entry, result)}>
          {state.phase === "undoing" ? "Sending…" : "Undo: write back the value it had"}
        </Button>
      )}
      {state.phase === "undo-failed" && (
        <p role="alert" className="changes-error small">
          {state.message}
        </p>
      )}
    </div>
  );
}

function Refused({ result, onReload }: { result: Refusal; onReload(): void }) {
  if (result.kind === "missing") return <NeedsIntegration feature="Putting a change back" compact />;
  const text =
    result.code === "stale_revision"
      ? "This has changed again since. Reload the history and check it before trying again."
      : result.code === "forbidden"
        ? "Only a Home Assistant administrator can put a change back."
        : result.code === "guard_refused"
          ? `The controller refused: ${result.message}`
          : result.message || "The controller refused this.";
  return (
    <p role="alert" className="changes-error">
      {text}{" "}
      {result.code === "stale_revision" && (
        <Button variant="outline" size="sm" onClick={onReload}>
          Reload
        </Button>
      )}
    </p>
  );
}
