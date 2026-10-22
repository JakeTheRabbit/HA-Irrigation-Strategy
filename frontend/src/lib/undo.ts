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

/** Puts back the changes these Journal events record, newest first (event ids are ULIDs, so they
 * sort by time). Stops at the first refusal and throws its words: the ones before it are back,
 * that one and the older ones are not. Resolves only when the controller read every value back. */
export async function revertEvents(controller: Pick<Controller, "operator">, eventIds: string[]): Promise<void> {
  for (const eventId of [...eventIds].sort().reverse()) {
    const outcome = await callV2<HistoryRevertResult>(controller, "history_revert", { event_id: eventId });
    if (outcome.kind === "missing") throw new Error("Undo needs Crop Steering 3.18 or newer. Nothing was changed.");
    if (outcome.kind === "error") throw new Error(outcome.message);
    if (outcome.readback.status !== "verified")
      throw new Error("The controller did not confirm the previous value. Reload and check it before trying again.");
  }
}
