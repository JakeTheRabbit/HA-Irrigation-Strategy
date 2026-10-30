import { toast } from "sonner";
import { callV2 } from "./parity-api";
import type { HistoryRevertResult } from "./parity-types";
import type { Controller } from "./types";

/** A 10 s toast with an Undo action, in place of a confirm dialog for a reversible change. A
 * refused undo says why in an error toast; it never reads as undone. */
export function offerUndo(opts: { message: string; undo: () => Promise<void> }): void {
  toast(opts.message, {
    duration: 10_000,
    action: {
      label: "Undo",
      onClick: () => {
        opts.undo().catch((error: unknown) =>
          toast.error(error instanceof Error && error.message ? error.message : "Undo failed. Nothing was changed."),
        );
      },
    },
  });
}

/** An undo that stopped part way: `reverted` of `total` changes are back. The message starts
 * "{k} of {n} put back:" once any are. */
export class UndoError extends Error {
  constructor(
    message: string,
    readonly reverted: number,
    readonly total: number,
  ) {
    super(message);
    this.name = "UndoError";
  }
}

/** Puts back the changes these Journal events record, newest first (event ids are ULIDs, so they
 * sort by time). Stops at the first refusal and throws an `UndoError` with its words and how many
 * were put back before it. Resolves, with each put-back's answer, only when the controller read every
 * value back. */
export async function revertEvents(
  controller: Pick<Controller, "operator">,
  eventIds: string[],
): Promise<HistoryRevertResult[]> {
  const ids = [...eventIds].sort().reverse();
  const stop = (reason: string, reverted: number): never => {
    throw new UndoError(reverted ? `${reverted} of ${ids.length} put back: ${reason}` : reason, reverted, ids.length);
  };
  const results: HistoryRevertResult[] = [];
  for (const [reverted, eventId] of ids.entries()) {
    const outcome = await callV2<HistoryRevertResult>(controller, "history_revert", { event_id: eventId });
    if (outcome.kind === "missing")
      stop(`Undo needs Crop Steering 3.18 or newer.${reverted ? "" : " Nothing was changed."}`, reverted);
    else if (outcome.kind === "error") stop(outcome.message, reverted);
    else if (outcome.readback.status !== "verified")
      stop("The controller did not confirm the previous value. Reload and check it before trying again.", reverted);
    else results.push(outcome.data);
  }
  return results;
}
