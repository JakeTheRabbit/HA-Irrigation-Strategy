import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, TriangleAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { NeedsIntegration } from "@/components/needs-integration";
import type { V2Outcome } from "@/lib/parity-api";
import { clock } from "@/lib/time";
import type { WriteResult } from "@/lib/types";
import "./review-apply.css";

/** One pending edit: what it was, what it becomes, and how to take just this one back out of the
 * draft. `id` is the setting's key, as the v2 `applied[].key` names it. */
export interface ReviewRow {
  id: string;
  label: string;
  before: string;
  after: string;
  note?: string;
  undo(): void;
}
/** What an apply did. `ok` only when the controller read every value back as written. */
export interface ApplyReceipt {
  at: number;
  ok: boolean;
  failed: { id: string; holds: string }[];
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

/** A 3.17 write (`controller.write`, which reads each entity back). */
export function receiptFromWrite(
  result: WriteResult,
  rows: ReviewRow[],
  rowOf: (entityId: string) => string,
  holds: (entityId: string) => string,
  now: number,
): ApplyReceipt {
  const failed = result.failed.map((f) => ({ id: rowOf(f.entityId), holds: holds(f.entityId) }));
  return { at: now, ok: !failed.length, failed, summary: summaryOf(rows, new Set(failed.map((f) => f.id))), eventIds: [] };
}

/** A v2 save. A row the controller refused keeps its old value; a read-back that is not verified
 * fails every row, since nothing confirms what the controller holds. */
export function receiptFromV2(
  outcome: V2Outcome<{ applied?: { target: string; key: string; readback: "verified" | "refused" }[] }>,
  rows: ReviewRow[],
  now: number,
): ApplyReceipt {
  if (outcome.kind !== "ok") return { at: now, ok: false, failed: rows.map((r) => ({ id: r.id, holds: r.before })), summary: "", eventIds: [] };
  const refused = new Set((outcome.data?.applied ?? []).filter((a) => a.readback === "refused").map((a) => a.key));
  const failed =
    outcome.readback.status !== "verified" ? rows : rows.filter((row) => refused.has(row.id));
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
  | { phase: "done"; result: ApplyReceipt | Refusal; at?: number }
  | { phase: "undoing"; receipt: ApplyReceipt }
  | { phase: "undone"; at: number }
  | { phase: "undo-failed"; receipt: ApplyReceipt; message: string };

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;
const isReceipt = (r: ApplyReceipt | Refusal): r is ApplyReceipt => "ok" in r;

function useNarrow() {
  const query = "(max-width: 720px)";
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(query).matches);
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return;
    const change = () => setNarrow(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  return narrow;
}

/** Pending edits, their checks, one Apply, and what the controller read back. On a phone the bar
 * is one "Review n changes" button that opens a bottom sheet. */
export function ReviewApply(props: ReviewApplyProps) {
  const [state, setState] = useState<ApplyState>({ phase: "idle" });
  const narrow = useNarrow();
  const sheet = useRef<HTMLDialogElement>(null);
  const run = async () => {
    setState({ phase: "sending" });
    try {
      setState({ phase: "done", result: await props.apply(), at: Date.now() });
    } catch (error) {
      setState({ phase: "done", result: { kind: "error", code: "unknown", message: error instanceof Error ? error.message : "" }, at: Date.now() });
    }
  };
  const undo = async (receipt: ApplyReceipt) => {
    setState({ phase: "undoing", receipt });
    try {
      await props.undo!(receipt);
      setState({ phase: "undone", at: Date.now() });
    } catch (error) {
      setState({ phase: "undo-failed", receipt, message: error instanceof Error && error.message ? error.message : "Undo failed." });
    }
  };
  const view = <ReviewApplyView {...props} state={state} onApply={run} onUndo={props.undo ? undo : undefined} />;
  if (!narrow || props.layout !== "bar" || !props.rows.length) return view;
  return (
    <>
      <Button className="review-apply-open" onClick={() => sheet.current?.showModal()}>
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
  props: ReviewApplyProps & { state: ApplyState; onApply?(): void; onUndo?(receipt: ApplyReceipt): void },
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
        {state.phase === "sending" ? "Sending…" : `Apply ${plural(n, "change")}`}
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
          <Button variant="link" size="sm" onClick={row.undo} disabled={busy} aria-label={`Undo ${row.label}`}>
            Undo
          </Button>
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
    const at = state.phase === "done" ? (state.at ?? Date.now()) : Date.now();
    if (!isReceipt(result)) {
      if (result.kind === "missing") return <NeedsIntegration feature="Applying these changes" compact />;
      const text =
        result.code === "stale_revision"
          ? `Someone else changed this at ${clock(at, timeZone)}. Reload their version and reapply your edits.`
          : result.code === "forbidden"
            ? "Only a Home Assistant administrator can change this."
            : result.code === "guard_refused"
              ? `The controller refused: ${result.message}`
              : result.message || "Home Assistant did not answer. Nothing was changed.";
      return (
        <div role="alert" className="review-apply-error">
          <span>{text}</span>
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
      const holds =
        result.failed.length === 1
          ? result.failed[0].holds
          : result.failed.map((f) => `${labelOf(f.id)} ${f.holds}`).join(", ");
      return (
        <div role="alert" className="review-apply-error">
          <span>
            Controller still holds {holds}.{" "}
            {result.summary ? `${result.summary}: written and read back.` : "Nothing else was changed."}
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
      <div role="status" className="review-apply-receipt">
        <span className="review-apply-tick" aria-hidden>
          <Check />
        </span>
        <span className="review-apply-receipt-text">
          <b>Written and read back {clock(result.at, timeZone)}</b>
          {result.summary && <span>{result.summary}</span>}
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
      <section className="review-apply is-panel" aria-label="Review and apply" data-pending={n || undefined}>
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
    <section className="review-apply is-bar" aria-label="Review and apply" data-pending={n || undefined}>
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
