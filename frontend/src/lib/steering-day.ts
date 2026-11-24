import { useEffect, useState } from "react";
import { phaseId } from "./day-lanes";
import {
  growDay,
  phaseBands,
  readings,
  valveShots,
  type GrowDay,
  type PhaseBand,
  type Reading,
  type Shot,
  type Span,
  type TimelineRows,
} from "./day-timeline";
import { numeric } from "./model";
import { probeGaps } from "./hmi";
import type { Controller, Room, Zone } from "./types";

const H = 3_600_000;

/** One zone's grow-day so far: its recorded VWC and pore EC, its shots (valve open) and its phases. */
export interface ZoneDay {
  vwc: Reading[];
  ec: Reading[];
  shots: Shot[];
  phases: PhaseBand[];
}
/** A room's steering day: the drawn window (two hours before lights-on to two after lights-off),
 * the photoperiod, and each zone's day; `zones` is null until the recorder answers. */
export interface RoomDay {
  span: Span;
  day: GrowDay;
  zones: Map<number, ZoneDay> | null;
}

const lightsDay = (controller: Controller, prefix: string, now: number) =>
  growDay(
    numeric(controller.states[`number.crop_steering_${prefix}lights_on_hour`]),
    numeric(controller.states[`number.crop_steering_${prefix}lights_off_hour`]),
    now,
    controller.timeZone,
  );

const idsOf = (room: Room, zones: Zone[], states: Controller["states"]) =>
  zones.flatMap((zone) => [
    ...(zone.vwc.entityId ? [zone.vwc.entityId] : []),
    ...(zone.ec.entityId ? [zone.ec.entityId] : []),
    ...(zone.valveEntity ? [zone.valveEntity] : []),
    ...(states[phaseId(room.prefix, zone.id)] ? [phaseId(room.prefix, zone.id)] : []),
  ]);

/** Each room's steering day, keyed by room id, re-read about every five minutes. A room without a
 * usable photoperiod is left out. */
export function useSteeringDays(
  controller: Controller,
  rooms: { room: Room; zones: Zone[] }[],
): Map<string, RoomDay> {
  const now = Date.now();
  const tick = Math.floor((controller.lastUpdated ?? 0) / 300_000);
  const plan = rooms.flatMap(({ room, zones }) => {
    const day = lightsDay(controller, room.prefix, now);
    if (!day) return [];
    const span = { start: day.start - 2 * H, end: Math.min(day.end, day.lightsOff + 2 * H) };
    return [{ room, zones, day, span, ids: idsOf(room, zones, controller.states) }];
  });
  const key = plan.map((p) => [p.room.id, p.span.start, ...p.ids].join(" ")).join("|");
  const [read, setRead] = useState<{ key: string; rows: Map<string, TimelineRows> } | null>(null);
  const ready = controller.connection === "live" || controller.connection === "demo";
  useEffect(() => {
    if (!ready || !plan.length) return;
    let current = true;
    Promise.all(
      plan.map((p) =>
        p.ids.length
          ? controller
              .timeline({ entityIds: p.ids, attributeIds: [], start: p.span.start, end: Date.now(), allRooms: true })
              .catch(() => ({}) as TimelineRows)
          : Promise.resolve({} as TimelineRows),
      ),
    ).then((all) => {
      if (current) setRead({ key, rows: new Map(plan.map((p, i) => [p.room.id, all[i]])) });
    });
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ready, tick]);
  const rowsFor = read?.key === key ? read.rows : null;
  return new Map(
    plan.map((p) => {
      const rows = rowsFor?.get(p.room.id);
      const to = Math.min(now, p.span.end);
      const zones = rows
        ? new Map(
            p.zones.map((zone): [number, ZoneDay] => {
              const rawVwc = readings(zone.vwc.entityId ? rows[zone.vwc.entityId] : [], p.span.start, to);
              const vwc = probeGaps(rawVwc).clean;
              if (zone.vwc.value !== null && zone.vwc.value > 1 && (!vwc.length || vwc.at(-1)!.time < now - 60_000))
                vwc.push({ time: now, value: zone.vwc.value });
              const rawEc = readings(zone.ec.entityId ? rows[zone.ec.entityId] : [], p.span.start, to);
              const ec = probeGaps(rawEc, 0).clean;
              if (zone.ec.value !== null && zone.ec.value > 0 && (!ec.length || ec.at(-1)!.time < now - 60_000))
                ec.push({ time: now, value: zone.ec.value });
              return [
                zone.id,
                {
                  vwc,
                  ec,
                  shots: valveShots(zone.valveEntity ? rows[zone.valveEntity] : [], [], zone.id, p.span.start, to),
                  phases: phaseBands(rows[phaseId(p.room.prefix, zone.id)], p.span.start, to),
                },
              ];
            }),
          )
        : null;
      return [p.room.id, { span: p.span, day: p.day, zones }];
    }),
  );
}

/** The room's phases for its rail: the steered zone that has moved furthest through the day speaks
 * for the room, its last phase carried on to lights-off. */
export function roomPhases(zones: Map<number, ZoneDay> | null, day: GrowDay, now: number): PhaseBand[] {
  if (!zones) return [];
  const best = [...zones.values()].reduce<PhaseBand[]>(
    (most, zone) => (zone.phases.length > most.length ? zone.phases : most),
    [],
  );
  const bands = best.map((band) => ({ ...band }));
  const last = bands.at(-1);
  if (last && last.end >= now - 10 * 60_000 && last.phase !== "P3") last.end = Math.max(last.end, day.lightsOff);
  return bands;
}
