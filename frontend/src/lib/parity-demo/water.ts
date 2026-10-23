import type { TimelineRow, TimelineRows } from "../day-timeline";
import { DEMO_MAIN_METER, demoJournal } from "./journal";

/** H2 Water & flow's recorded readings for the demo, from the demo Journal: each zone valve is on
 * from its shot's start to its close, and Room A's main-line meter counts each shot's metered litres
 * as the shot closes, plus yesterday's 0.3 L at 02:18 with every valve shut (the Journal's CS-319). */
const BASE_L = 1520.4;
const LEAK_L = 0.3;

/** Room A's meter readings, in litres, oldest first. */
export function demoMeterRows(now: number): TimelineRow[] {
  const events = demoJournal("room:", now);
  let total = BASE_L;
  const rows: TimelineRow[] = [];
  for (const e of events) {
    const t = Date.parse(e.ts);
    // A reading as each flow starts (the meter still), then the one it ends on.
    if (e.kind === "shot.completed" && typeof e.data.metered_l === "number") total += e.data.metered_l;
    else if (e.kind === "alert.cleared" && e.code === "CS-319") total += LEAK_L;
    else if (e.kind !== "shot.started" && !(e.kind === "alert.raised" && e.code === "CS-319")) continue;
    rows.push({ state: total.toFixed(2), time: t });
  }
  return rows;
}

/** `controller.timeline`'s answer for the leak lanes: `valves` maps each valve to its zone. */
export function demoLeakTimeline(valves: Record<string, number>, meter: string, start: number, end: number, now: number): TimelineRows {
  const until = Math.min(end, now);
  const events = demoJournal("room:", now);
  const out: TimelineRows = {};
  for (const [entity, zone] of Object.entries(valves)) {
    const rows: TimelineRow[] = [{ state: "off", time: start }];
    for (const e of events) {
      const t = Date.parse(e.ts);
      if (e.zone !== zone || t < start || t >= until) continue;
      if (e.kind === "shot.started") rows.push({ state: "on", time: t });
      else if (e.kind === "shot.completed" || e.kind === "shot.aborted") rows.push({ state: "off", time: t });
    }
    out[entity] = rows;
  }
  if (meter === DEMO_MAIN_METER) {
    const all = demoMeterRows(now);
    const before = [...all].reverse().find((row) => row.time < start);
    out[meter] = [
      { state: before?.state ?? BASE_L.toFixed(2), time: start },
      ...all.filter((row) => row.time >= start && row.time < until),
    ];
  }
  return out;
}
