import { describe, expect, it, vi } from "vitest";
import { PAGES, sectionOf } from "./routes";
import { TOUR_STOPS, onTourStart, startTour } from "./tour";

vi.stubGlobal("window", new EventTarget());

describe("the first-run tour", () => {
  it("has five stops, each on a real page of a different menu entry", () => {
    expect(TOUR_STOPS).toHaveLength(5);
    for (const stop of TOUR_STOPS) expect(PAGES).toContain(stop.page);
    expect(new Set(TOUR_STOPS.map((stop) => sectionOf(stop.page))).size).toBe(5);
  });
  it("starts on Today and ends on Help, which says where to take it again", () => {
    expect(TOUR_STOPS[0].page).toBe("today");
    expect(TOUR_STOPS.at(-1)!.page).toBe("help");
    expect(TOUR_STOPS.at(-1)!.text).toMatch(/this tour again/);
  });
  it("speaks a grower's words, never the engine's", () => {
    for (const stop of TOUR_STOPS)
      expect(stop.title + " " + stop.text).not.toMatch(/p[0-3]_|_threshold|\bvwc\b|pwec|enter p/i);
  });
  it("starts only when something starts it, and stops listening when asked", () => {
    const start = vi.fn();
    const stop = onTourStart(start);
    expect(start).not.toHaveBeenCalled();
    startTour();
    expect(start).toHaveBeenCalledTimes(1);
    stop();
    startTour();
    expect(start).toHaveBeenCalledTimes(1);
  });
});
