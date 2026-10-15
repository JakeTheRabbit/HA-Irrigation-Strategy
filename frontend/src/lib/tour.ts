/** The first-run tour: five stops over the real pages, once, right after the setup wizard's Switch
 * on, and again from Help whenever a grower asks. Nothing else starts it, so a room set up before the
 * wizard existed (an upgraded installation) never sees it. */
import type { Page } from "./routes";

export interface TourStop {
  page: Page;
  title: string;
  text: string;
}

export const TOUR_STOPS: readonly TourStop[] = [
  {
    page: "today",
    title: "Today",
    text: "Every zone at a glance: moisture, pore EC, the next shot and anything that needs you. The Watering switch at the top turns watering on, after a review. Open a zone for its day in detail.",
  },
  {
    page: "plan/targets",
    title: "Plan",
    text: "Targets are the moisture and EC each zone steers to, stage by stage. Schedule lays the stages out over the run. Every change is reviewed before it is written.",
  },
  {
    page: "history/timeline",
    title: "History",
    text: "What the controller did and why, shot by shot, with the water used and run-by-run comparisons.",
  },
  {
    page: "equipment/probes",
    title: "Equipment",
    text: "Probes, tank and feed, dosing and stock. A probe that stops reporting shows up here first.",
  },
  {
    page: "help",
    title: "Help",
    text: "What every alert code means and what to do, the words the dashboard uses, What's new, and this tour again.",
  },
];

const EVENT = "crop-steering-tour";

/** Starts the tour from its first stop. */
export function startTour() {
  window.dispatchEvent(new Event(EVENT));
}

/** Calls `start` whenever something starts the tour; returns the unsubscribe. */
export function onTourStart(start: () => void): () => void {
  window.addEventListener(EVENT, start);
  return () => window.removeEventListener(EVENT, start);
}
