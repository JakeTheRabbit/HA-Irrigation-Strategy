import { useEffect, useRef, useState, type ReactNode, type Ref } from "react";
import { Check, TriangleAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { NeedsIntegration } from "@/components/needs-integration";
import type { V2Outcome } from "@/lib/parity-api";
import { clock } from "@/lib/time";
import type { WriteResult } from "@/lib/types";
import { useNarrow } from "@/lib/use-narrow";
import "./review-apply.css";

/** One pending edit: what it was, what it becomes, and how to take just this one back out of the
 * draft. A v2 save's `applied[]` entry is this row when its `key` is the row's `key` (else `id`) and
 * its `target` is the row's `target` (any target when the row names none). A row without `undo`
 * cannot be taken out on its own (a copy writes whole sections). */
export interface ReviewRow {
  id: string;
  key?: string;
  target?: string;
  label: string;
  before: string;
  after: string;
  note?: string;
  undo?(): void;
}
/** What an apply did. `ok` only when the controller read every value back as written.
 * `unconfirmed`: nothing says which values took, so the receipt claims none of them. */
export interface ApplyReceipt {
  at: number;
  ok: boolean;
  unconfirmed?: boolean;
  failed: { id: string; holds: string }[];
  /** Rows written but not read back (a 3.17 write, row by row): they may have taken, so the
   * receipt names them without saying what the controller holds. */
  notConfirmed?: string[];
  /** What the apply left out on purpose, each with why (a copy's missing settings). */
  notCopied?: string[];
  summary: string;
  by?: string;
  eventIds: string[];
}
type Refusal = Extract<V2Outcome<unknown>, { kind: "error" | "missing" }>;

const line = (row: ReviewRow) => `${row.label} ${row.before} → ${row.after}`;
const summaryOf = (rows: ReviewRow[], failed: Set<string>) =>
  rows
    .filter((row) => !failed.has(row.id))
    .map(line)
    .join(" · ");

/** A write the controller may have taken but did not read back (client.ts `applyChanges`): it is
 * not a refusal, so nothing says what the controller holds. */
const UNCONFIRMED = /did not confirm|unconfirmed/i;

/** A 3.17 write (`controller.write`, which reads each entity back, row by row). Rows read back are
 * written; a row not read back is named as not confirmed; "still holds" is only for a definite
 * refusal. The receipt is green only when every row was read back. */
export function receiptFromWrite(
  result: WriteResult,
  rows: ReviewRow[],
  rowOf: (entityId: string) => string,
  holds: (entityId: string) => string,
  now: number,
): ApplyReceipt {
  const unsure = result.failed.filter((f) => UNCONFIRMED.test(f.reason));
  const failed = result.failed
    .filter((f) => !unsure.includes(f))
    .map((f) => ({ id: rowOf(f.entityId), holds: holds(f.entityId) }));
  const notConfirmed = unsure.map((f) => rowOf(f.entityId));
  return {
    at: now,
    ok: !failed.length && !notConfirmed.length,
    failed,
    ...(notConfirmed.length ? { notConfirmed } : {}),
    summary: summaryOf(rows, new Set([...failed.map((f) => f.id), ...notConfirmed])),
    eventIds: [],
  };
}

type Applied = { target: string; key: string; readback: "verified" | "refused" };
const matches = (row: ReviewRow, a: Applied) =>
  (row.key ?? row.id) === a.key && (row.target === undefined || row.target === a.target);

/** A v2 save. A row the controller refused keeps its old value. A read-back that is not verified,
 * or a refusal that matches no row, fails every row unconfirmed: nothing then says which took. */
export function receiptFromV2(outcome: V2Outcome<{ applied?: Applied[] }>, rows: ReviewRow[], now: number): ApplyReceipt {
  const refused = outcome.kind === "ok" ? (outcome.data?.applied ?? []).filter((a) => a.readback === "refused") : [];
  if (
    outcome.kind !== "ok" ||
    outcome.readback.status !== "verified" ||
    refused.some((a) => !rows.some((row) => matches(row, a)))
  )
    return {
      at: now,
      ok: false,
      unconfirmed: true,
      failed: rows.map((r) => ({ id: r.id, holds: r.before })),
      summary: "",
      eventIds: outcome.kind === "ok" ? outcome.eventIds : [],
    };
  const failed = rows.filter((row) => refused.some((a) => matches(row, a)));
  const ids = new Set(failed.map((r) => r.id));
  return {
    at: now,
    ok: !failed.length,
    failed: failed.map((r) => ({ id: r.id, holds: r.before })),
    summary: summaryOf(rows, ids),
    eventIds: outcome.eventIds,
  };
}

export interface ReviewApplyProps {
  rows: ReviewRow[];
  layout: "bar" | "panel";
  summary?: ReactNode;
  discardLabel?: string;
  /** The Apply button's own words ("Copy 3 changes to F1"); "Apply n changes" without. */
  applyLabel?: string;
  checks?: { ok: boolean | "warn"; text: string }[];
  consequence?: ReactNode;
  apply(): Promise<ApplyReceipt | Refusal>;
  onDiscard(): void;
  last?: ApplyReceipt | null;
  onReload?(): void;
  timeZone: string;
  /** Writes back the previous values of an applied receipt (`revertEvents`, or a 3.17 re-write).
   * Without it the receipt offers no Undo. */
  undo?(receipt: ApplyReceipt): Promise<void>;
}
export type ApplyState =
  | { phase: "idle" }
  | { phase: "sending" }
  | { phase: "done"; result: ApplyReceipt | Refusal }
  | { phase: "undoing"; receipt: ApplyReceipt }
  | { phase: "undone"; at: number }
  /** `reverted`: how many of the receipt's changes were put back before the undo stopped. */
  | { phase: "undo-failed"; receipt: ApplyReceipt; message: string; reverted: number };

const notCopiedText = (r: ApplyReceipt) => (r.notCopied?.length ? `Not copied: ${r.notCopied.join("; ")}.` : "");
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const isReceipt = (r: ApplyReceipt | Refusal): r is ApplyReceipt => "ok" in r;

/** Apply: sending, then done with what came back. A throw (socket closed, timeout) may still have
 * landed, so it is an unconfirmed receipt: it claims neither a write nor a refusal. */
export async function runApply(
  apply: ReviewApplyProps["apply"],
  set: (state: ApplyState) => void,
  now: () => number = Date.now,
): Promise<ApplyReceipt | Refusal> {
  set({ phase: "sending" });
  let result: ApplyReceipt | Refusal;
  try {
    result = await apply();
  } catch (error) {
    result = { at: now(), ok: false, unconfirmed: true, failed: [], summary: "", eventIds: [] };
  }
  set({ phase: "done", result });
  return result;
}
/** Undo: undoing, then undone, or undo-failed with how many were put back (`UndoError.reverted`,
 * else 0). */
export async function runUndo(
  undo: NonNullable<ReviewApplyProps["undo"]>,
  receipt: ApplyReceipt,
  set: (state: ApplyState) => void,
  now: () => number = Date.now,
): Promise<void> {
  set({ phase: "undoing", receipt });
  try {
    await undo(receipt);
    set({ phase: "undone", at: now() });
  } catch (error) {
    const reverted = (error as { reverted?: unknown } | null)?.reverted;
    set({
      phase: "undo-failed",
      receipt,
      reverted: typeof reverted === "number" ? reverted : 0,
      message: error instanceof Error && error.message ? error.message : "Undo failed.",
    });
  }
}
/** A written and read-back apply closes the phone sheet and puts focus back on its trigger,
 * before the page empties the draft and both unmount. True when it closed the sheet. */
export function closeSheetAfter(
  result: ApplyReceipt | Refusal,
  sheet: Pick<HTMLDialogElement, "close"> | null,
  trigger: Pick<HTMLElement, "focus"> | null,
): boolean {
  if (!isReceipt(result) || !result.ok) return false;
  sheet?.close();
  trigger?.focus();
  return true;
}
/** Once the sheet has closed and the inline view is back, focus moves to the read-back receipt so
 * a screen reader lands on the outcome. True when the pending focus is done. */
export function focusReceiptAfterSheet(
  pending: boolean,
  inSheet: boolean,
  receipt: Pick<HTMLElement, "focus"> | null,
): boolean {
  if (!pending || inSheet) return false;
  receipt?.focus();
  return true;
}

/** Pending edits, their checks, one Apply, and what the controller read back. On a phone the bar
 * is one "Review n changes" button that opens a bottom sheet. 720 px is the app's phone breakpoint
 * (bottom bar); the shared hook's default is History Explorer's 640 px. */
export function ReviewApply(props: ReviewApplyProps) {
  const [state, setState] = useState<ApplyState>({ phase: "idle" });
  const narrow = useNarrow(720);
  const sheet = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const receipt = useRef<HTMLDivElement>(null);
  const [focusReceipt, setFocusReceipt] = useState(false);
  const run = async () => {
    if (closeSheetAfter(await runApply(props.apply, setState), sheet.current, trigger.current)) setFocusReceipt(true);
  };
  const undo = (receipt: ApplyReceipt) => void runUndo(props.undo!, receipt, setState);
  const inSheet = narrow && props.layout === "bar" && props.rows.length > 0;
  useEffect(() => {
    if (focusReceiptAfterSheet(focusReceipt, inSheet, receipt.current)) setFocusReceipt(false);
  }, [focusReceipt, inSheet]);
  const view = (
    <ReviewApplyView
      {...props}
      state={state}
      onApply={run}
      onUndo={props.undo ? undo : undefined}
      inSheet={inSheet}
      receiptRef={receipt}
    />
  );
  if (!inSheet) return view;
  return (
    <>
      <Button ref={trigger} className="review-apply-open" aria-haspopup="dialog" onClick={() => sheet.current?.showModal()}>
        Review {plural(props.rows.length, "change")}
      </Button>
      <dialog ref={sheet} className="review-apply-sheet" aria-label="Review and apply">
        <Button variant="ghost" size="sm" className="review-apply-close" onClick={() => sheet.current?.close()}>
          Close
        </Button>
        {view}
      </dialog>
    </>
  );
}

/** The markup for one state; exported for tests and the story page. */
export function ReviewApplyView(
  props: ReviewApplyProps & {
    state: ApplyState;
    onApply?(): void;
    onUndo?(receipt: ApplyReceipt): void;
    /** Inside the phone sheet, which carries the name already. */
    inSheet?: boolean;
    receiptRef?: Ref<HTMLDivElement>;
  },
) {
  const { rows, layout, state, timeZone } = props;
  const n = rows.length;
  const busy = state.phase === "sending" || state.phase === "undoing";
  const blocked = props.checks?.some((c) => c.ok === false) ?? false;
  const labelOf = (id: string) => rows.find((r) => r.id === id)?.label ?? id;

  const applyButton = n ? (
    blocked ? (
      <span className="review-apply-blocked">Fix the red check to apply</span>
    ) : (
      <Button onClick={props.onApply} disabled={busy} className={state.phase === "sending" ? "is-sending" : undefined}>
        {state.phase === "sending" ? "Sending…" : (props.applyLabel ?? `Apply ${plural(n, "change")}`)}
      </Button>
    )
  ) : null;
  const discardButton = n ? (
    <Button variant="outline" onClick={props.onDiscard} disabled={busy}>
      {props.discardLabel ?? "Discard edits"}
    </Button>
  ) : null;

  const list = n ? (
    <ul className="review-apply-rows">
      {rows.map((row) => (
        <li key={row.id}>
          <span className="review-apply-label">{row.label}</span>
          <span className="review-apply-diff">
            <s>{row.before}</s> → <b>{row.after}</b>
          </span>
          {row.note && <span className="review-apply-note">{row.note}</span>}
          {row.undo && (
            <Button variant="link" size="sm" onClick={row.undo} disabled={busy} aria-label={`Undo ${row.label}`}>
              Undo
            </Button>
          )}
        </li>
      ))}
    </ul>
  ) : null;

  const checks = props.checks?.length ? (
    <ul className="review-apply-checks" aria-label="Checks">
      {props.checks.map((c) => (
        <li key={c.text} className={c.ok === true ? "is-ok" : c.ok === "warn" ? "is-warn" : "is-bad"}>
          {c.ok === true ? <Check aria-hidden /> : c.ok === "warn" ? <TriangleAlert aria-hidden /> : <X aria-hidden />}
          <span>{c.text}</span>
        </li>
      ))}
    </ul>
  ) : null;

  let applied = false;
  const status = statusOf();
  function statusOf(): ReactNode {
    if (state.phase === "undone")
      return (
        <div role="status" className="review-apply-receipt">
          <b>Previous values written back {clock(state.at, timeZone)}</b>
        </div>
      );
    const result =
      state.phase === "done" ? state.result : state.phase === "undoing" || state.phase === "undo-failed" ? state.receipt : props.last;
    if (!result) return null;
    // Part of an undo went through: the receipt no longer says what the controller holds.
    if (state.phase === "undo-failed" && state.reverted > 0)
      return (
        <div role="alert" className="review-apply-error">
          <span>{state.message}</span>
          {props.onReload && (
            <Button variant="outline" size="sm" onClick={props.onReload}>
              Reload
            </Button>
          )}
        </div>
      );
    if (!isReceipt(result)) {
      if (result.kind === "missing") return <NeedsIntegration feature="Applying these changes" compact />;
      const known = result.code === "stale_revision" || result.code === "forbidden" || result.code === "guard_refused";
      const text =
        result.code === "stale_revision"
          ? "Someone else changed this since you started editing. Reload their version and reapply your edits."
          : result.code === "forbidden"
            ? "Only a Home Assistant administrator can change this."
            : result.code === "guard_refused"
              ? `The controller refused: ${result.message}`
              : "The controller refused this change.";
      return (
        <div role="alert" className="review-apply-error">
          <span>{text}</span>
          {!known && <small className="review-apply-detail">Code: {result.code}</small>}
          {result.code === "stale_revision" && props.onReload ? (
            <Button variant="outline" size="sm" onClick={props.onReload}>
              Reload
            </Button>
          ) : result.code !== "forbidden" && result.code !== "guard_refused" && n ? (
            <Button variant="outline" size="sm" onClick={props.onApply} disabled={busy}>
              Try again
            </Button>
          ) : null}
        </div>
      );
    }
    if (!result.ok) {
      if (result.unconfirmed)
        return (
          <div role="alert" className="review-apply-error">
            <span>The controller did not confirm the values. Reload and check before trying again.</span>
            {props.onReload ? (
              <Button variant="outline" size="sm" onClick={props.onReload}>
                Reload
              </Button>
            ) : n ? (
              <Button variant="outline" size="sm" onClick={props.onApply} disabled={busy}>
                Try again
              </Button>
            ) : null}
          </div>
        );
      const holds =
        result.failed.length === 0
          ? ""
          : result.failed.length === 1
            ? `Controller still holds ${result.failed[0].holds}.`
            : result.failed.map((f) => `${labelOf(f.id)} is still ${f.holds}.`).join(" ");
      const unsure = result.notConfirmed?.length
        ? `The controller did not confirm: ${result.notConfirmed.map(labelOf).join(", ")}.`
        : "";
      const left = notCopiedText(result);
      return (
        <div role="alert" className="review-apply-error">
          <span>
            {[
              holds,
              unsure,
              result.summary
                ? `${result.summary}: written and read back.`
                : unsure
                  ? ""
                  : "Nothing else was changed.",
              left,
            ]
              .filter(Boolean)
              .join(" ")}
          </span>
          {n ? (
            <Button variant="outline" size="sm" onClick={props.onApply} disabled={busy}>
              Try again
            </Button>
          ) : null}
        </div>
      );
    }
    applied = true;
    return (
      <div role="status" className="review-apply-receipt" tabIndex={-1} ref={props.receiptRef}>
        <span className="review-apply-tick" aria-hidden>
          <Check />
        </span>
        <span className="review-apply-receipt-text">
          <b>Written and read back {clock(result.at, timeZone)}</b>
          {result.summary && <span>{result.summary}</span>}
          {result.notCopied?.length ? <span className="review-apply-not-copied">{notCopiedText(result)}</span> : null}
          <small>Controller confirmed every value{result.by ? ` · by ${result.by}` : ""}</small>
        </span>
        {props.undo ? (
          <Button
            variant="outline"
            size="sm"
            onClick={() => props.onUndo?.(result)}
            disabled={busy}
            className={state.phase === "undoing" ? "is-sending" : undefined}
          >
            {state.phase === "undoing" ? "Sending…" : "Undo: write back the previous values"}
          </Button>
        ) : null}
        {state.phase === "undo-failed" && <span role="alert" className="review-apply-error-text">{state.message}</span>}
      </div>
    );
  }

  if (layout === "panel")
    return (
      <section className="review-apply is-panel" aria-label={props.inSheet ? undefined : "Review and apply"} data-pending={n || undefined}>
        <h2>Review &amp; apply</h2>
        {props.summary ??
          (n ? (
            <span className="review-apply-sub">{plural(n, "unsaved change")}, not active until applied</span>
          ) : (
            <span className="review-apply-sub">No unsaved changes.</span>
          ))}
        {list}
        {checks}
        {applyButton}
        {discardButton}
        {status}
        {props.consequence && <p className="review-apply-consequence">{props.consequence}</p>}
      </section>
    );
  return (
    <section className="review-apply is-bar" aria-label={props.inSheet ? undefined : "Review and apply"} data-pending={n || undefined}>
      <div className="review-apply-main">
        <div className="review-apply-head">
          <b>{props.summary ?? (n ? `${plural(n, "change")} · Review & apply` : "No pending changes")}</b>
          {discardButton}
          {applyButton}
        </div>
        {list}
        {checks}
        {props.consequence && <p className="review-apply-consequence">{props.consequence}</p>}
      </div>
      {status && (
        <div className="review-apply-last">
          {applied && <span className="review-apply-kicker">Last applied</span>}
          {status}
        </div>
      )}
    </section>
  );
}
