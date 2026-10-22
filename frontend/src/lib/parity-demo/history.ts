import { demoHistory } from "../demo";
import type { TimelineRequest, TimelineRow, TimelineRows } from "../day-timeline";
import type { States } from "../types";
import { demoJournal, demoJournalVwc, demoLightsOn } from "./journal";

/** The demo's recorded readings for History › Explorer (H1), drawn from the demo Journal's own
 * day so the charts, the PHASE lane and the SHOTS lane agree: the same rooms, shots and phases.
 * - zone VWC rises at each Journal shot (demoJournalVwc);
 * - Room A zone 2's pore EC is over its stage band from 10 min before each "pore_ec_high" alert
 *   for an hour, then back;
 * - the tank level falls 1.3 points per litre the Journal's shots metered and is refilled to 74 %
 *   from 06:05 (its first higher reading 06:10; 235 min before Room A's lights-on, Room B's at the
 *   same offset);
 * - each zone's phase sensor follows the Journal's phase changes (what a 3.17 lane reads);
 * - every other sensor keeps its demo history. */

const MIN = 60_000;
const DAY = 86_400_000;
const STEP = 5 * MIN;
const REFILL_BEFORE_ON = 235 * MIN;
const REFILL_MS = 20 * MIN;
const FULL = 74;
const PER_LITRE = 1.3;

const rows = (points: { time: string; value: number }[], start: number, end: number): TimelineRow[] =>
  points
    .map((p) => ({ state: String(p.value), time: Date.parse(p.time) }))
    .filter((row) => row.time >= start && row.time < end);

/** Room A zone 2's pore EC, lifted over the band around the Journal's pore EC alerts. */
function ecExcursions(roomId: string, zone: number, now: number) {
  return demoJournal(roomId, now)
    .filter((e) => e.kind === "alert.raised" && e.zone === zone && e.data.key === "pore_ec_high")
    .map((e) => Date.parse(e.ts));
}

/** The tank level at `t`: refilled each day at lights-on less 230 min, drawn by metered shots. */
function tankLevel(roomId: string, now: number) {
  const events = demoJournal(roomId, now);
  const shots = events
    .filter((e) => e.kind === "shot.completed")
    .map((e) => ({ t: Date.parse(e.ts), litres: Number(e.data.metered_l) || 0 }));
  const today = demoLightsOn(roomId, now) - REFILL_BEFORE_ON;
  const refills = [today - DAY, today];
  const drawn = (from: number, to: number) =>
    shots.filter((s) => s.t > from && s.t <= to).reduce((sum, s) => sum + s.litres * PER_LITRE, 0);
  return (t: number) => {
    const last = [...refills].reverse().find((r) => r <= t) ?? refills[0] - DAY;
    const level = FULL - drawn(last, t);
    if (t >= last + REFILL_MS) return level;
    // Filling: from what the previous day left to full, over 20 minutes.
    const before = FULL - drawn(last - DAY, last);
    return before + ((FULL - before) * (t - last)) / REFILL_MS;
  };
}

export function demoExplorerTimeline(states: States, request: TimelineRequest, now: number): TimelineRows {
  const end = Math.min(request.end, now);
  const out: TimelineRows = {};
  const hours = Math.min(720, (now - request.start) / 3_600_000 + 0.5);
  for (const id of new Set([...request.entityIds, ...request.attributeIds])) {
    if (!states[id]) continue;
    const phase = /^sensor\.crop_steering_(.*?)zone_(\d+)_phase$/.exec(id);
    if (phase) {
      const changes = demoJournal(`room:${phase[1]}`, now).filter(
        (e) => e.kind === "phase.changed" && (e.zone === null || e.zone === Number(phase[2])),
      );
      const first = changes.find((e) => Date.parse(e.ts) > request.start);
      const held = [...changes].reverse().find((e) => Date.parse(e.ts) <= request.start);
      const at = first ? String(first.data.from) : held ? String(held.data.to) : null;
      out[id] = [
        ...(at ? [{ state: at, time: request.start }] : []),
        ...changes
          .map((e) => ({ state: String(e.data.to), time: Date.parse(e.ts) }))
          .filter((row) => row.time > request.start && row.time < end),
      ];
      continue;
    }
    const tank = /^sensor\.demo_(.*?)tank_level$/.exec(id);
    if (tank) {
      const level = tankLevel(`room:${tank[1]}`, now);
      const list: TimelineRow[] = [];
      for (let t = Math.ceil(request.start / STEP) * STEP; t < end; t += STEP)
        list.push({ state: String(Math.round(level(t))), time: t });
      out[id] = list;
      continue;
    }
    const [series] = demoJournalVwc(demoHistory(states, [id], hours, now), now);
    const ec = /^sensor\.crop_steering_(.*?)ec_zone_(\d+)$/.exec(id);
    const alerts = ec ? ecExcursions(`room:${ec[1]}`, Number(ec[2]), now) : [];
    const lifted = series.points.map((p) => {
      const t = Date.parse(p.time);
      const alert = alerts.find((a) => t >= a - 20 * MIN && t <= a + 60 * MIN);
      if (alert === undefined) return p;
      // Up to 6.5 mS/cm over 10 min, held for an hour, down again over 10 min.
      const share = Math.min(1, (t - (alert - 20 * MIN)) / (10 * MIN), (alert + 60 * MIN - t) / (10 * MIN));
      return { ...p, value: Number((p.value + (6.5 - p.value) * share).toFixed(3)) };
    });
    out[id] = rows(lifted, request.start, end);
  }
  return out;
}
