import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import type { Page } from "@/lib/routes";
import { TOUR_STOPS, onTourStart } from "@/lib/tour";
import "./tour.css";

/** The tour's card, pinned to the bottom of the window over the real page it is about. It opens
 * each stop's page as it gets there and never blocks the page under it. */
export function Tour({ navigate }: { navigate: (page: Page) => void }) {
  const [at, setAt] = useState<number | null>(null);
  useEffect(() => onTourStart(() => setAt(0)), []);
  const stop = at === null ? null : TOUR_STOPS[at];
  useEffect(() => {
    if (stop) navigate(stop.page);
    // Only on reaching a stop: `navigate` is a new function on every render of the app.
  }, [stop]);
  if (!stop || at === null) return null;
  const last = at === TOUR_STOPS.length - 1;
  return (
    <section className="tour" role="dialog" aria-modal="false" aria-labelledby="tour-title">
      <p className="tour-count muted">
        Stop {at + 1} of {TOUR_STOPS.length}
      </p>
      <h2 id="tour-title">{stop.title}</h2>
      <p>{stop.text}</p>
      <div className="tour-actions">
        <Button variant="ghost" onClick={() => setAt(null)}>
          End tour
        </Button>
        {at > 0 && (
          <Button variant="outline" onClick={() => setAt(at - 1)}>
            Back
          </Button>
        )}
        <Button onClick={() => setAt(last ? null : at + 1)}>{last ? "Done" : "Next"}</Button>
      </div>
    </section>
  );
}
