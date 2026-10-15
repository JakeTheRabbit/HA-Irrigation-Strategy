import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { number, ReviewDialog } from "@/components/dashboard";
import { overlayLabel, overlayText, type Overlay, type OverlayDocument } from "@/lib/overlays";
import type { Controller } from "@/lib/types";
import "./overlay-row.css";

/** The room's AI overlays, read again after each Keep or Undo. An integration without overlays
 * reads as none. */
export function useOverlays(controller: Controller) {
  const [doc, setDoc] = useState<OverlayDocument | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setDoc(null);
    if (!controller.roomId) return;
    controller
      .operator<OverlayDocument>("overlay_get")
      .then((value) => {
        if (!cancelled) setDoc(value);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [controller.roomId, controller.operator, version]);
  return { doc, reload: useCallback(() => setVersion((value) => value + 1), []) };
}

/** Settings the AI changed that go back by themselves: "Set by AI 22:48 · goes back at lights-on ·
 * Keep / Undo". Keep and Undo each go through the same Review as any other change. */
export function OverlayRows({
  controller,
  overlays,
  reload,
}: {
  controller: Controller;
  overlays: Overlay[];
  reload: () => void;
}) {
  const [review, setReview] = useState<{ overlay: Overlay; keep: boolean } | null>(null);
  if (!overlays.length) return null;
  const unit = (overlay: Overlay) => {
    const value = controller.states[overlay.entity_id]?.attributes.unit_of_measurement;
    return typeof value === "string" ? (value === "%" ? "%" : ` ${value}`) : "";
  };
  const value = (overlay: Overlay, of: number) => `${number(of, 2)}${unit(overlay)}`;
  const now = Date.now();
  const off = controller.admin === false;
  const shown = review?.overlay;
  return (
    <>
      <ul className="overlay-rows" aria-label="Settings the AI changed that go back by themselves">
        {overlays.map((overlay) => (
          <li key={overlay.entity_id} data-overlay={overlay.entity_id}>
            <span>
              <strong>{overlayLabel(overlay)}</strong> {value(overlay, overlay.old)} →{" "}
              <b>{value(overlay, overlay.new)}</b>
              <small>{overlayText(overlay, now)}</small>
            </span>
            <span className="overlay-actions">
              <Button
                variant="outline"
                size="sm"
                disabled={off}
                title={off ? "Needs a Home Assistant administrator" : undefined}
                onClick={() => setReview({ overlay, keep: true })}
              >
                Keep
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={off}
                title={off ? "Needs a Home Assistant administrator" : undefined}
                onClick={() => setReview({ overlay, keep: false })}
              >
                Undo
              </Button>
            </span>
          </li>
        ))}
      </ul>
      <ReviewDialog
        open={!!review}
        onOpenChange={(open) => {
          if (!open) setReview(null);
        }}
        controller={controller}
        title={review?.keep ? "Keep the AI's change?" : "Undo the AI's change?"}
        items={
          shown
            ? [
                {
                  change: {
                    entityId: shown.entity_id,
                    value: review.keep ? shown.new : shown.old,
                  },
                  label: overlayLabel(shown),
                  before: `${value(shown, shown.new)} (AI)`,
                  after: `${value(shown, review.keep ? shown.new : shown.old)} (yours)`,
                },
              ]
            : []
        }
        note={
          review?.keep
            ? "It stays at the AI's value as your own and no longer goes back at lights-on."
            : "Your own value goes back now instead of at lights-on."
        }
        run={async () => {
          if (!review) return;
          await controller.operator(review.keep ? "overlay_keep" : "overlay_undo", {
            entity_id: review.overlay.entity_id,
          });
        }}
        onApplied={reload}
      />
    </>
  );
}
