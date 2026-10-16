import { phaseBands, valveShots, type PhaseBand, type Span, type TimelineRows } from "./day-timeline";
import { descriptor } from "./model";
import type { RoomView, States } from "./types";

/** History › Timeline lanes (Settings › Display): one row per mapped device with its on and off
 * through the grow day, or one row per zone with its phases and shots, on one lights-on axis. */
export interface Lane {
  key: string;
  label: string;
  /** The device's on spans, or the zone's shots. */
  on: Span[];
  /** Zones only: the zone's phases. */
  phases: PhaseBand[];
}

const ON = new Set(["on", "open", "opening"]);

/** The spans a device was on between `from` and `to`, from its recorded states. */
export function onSpans(rows: TimelineRows[string] = [], from: number, to: number): Span[] {
  const spans: Span[] = [];
  rows.forEach((row, index) => {
    const start = Math.max(row.time, from),
      end = Math.min(rows[index + 1]?.time ?? to, to);
    if (!ON.has(row.state) || end <= start) return;
    const last = spans.at(-1);
    if (last && last.end === start) last.end = end;
    else spans.push({ start, end });
  });
  return spans;
}

/** The room's mapped devices, in the order water flows, then the lights: what gets an equipment
 * lane. A device the room does not map gets none. */
export function laneDevices(states: States, room: RoomView): { id: string; label: string }[] {
  const map = descriptor(states, room.room)?.attributes ?? {};
  const one = (key: string, label: string) =>
    typeof map[key] === "string" && map[key] ? [{ id: String(map[key]), label }] : [];
  return [
    ...one("light_entity", "Lights"),
    ...one("tank_fill_entity", "Tank fill"),
    ...one("pump", "Pump"),
    ...one("mainline", "Main line"),
    ...room.zones.flatMap((zone) =>
      zone.valveEntity ? [{ id: zone.valveEntity, label: `${zone.name} valve` }] : [],
    ),
  ];
}

export const phaseId = (prefix: string, zone: number) =>
  `sensor.crop_steering_${prefix}zone_${zone}_phase`;

export function equipmentLanes(
  devices: { id: string; label: string }[],
  rows: TimelineRows,
  span: Span,
): Lane[] {
  return devices.map((device) => ({
    key: device.id,
    label: device.label,
    on: onSpans(rows[device.id], span.start, span.end),
    phases: [],
  }));
}

export function zoneLanes(room: RoomView, rows: TimelineRows, span: Span): Lane[] {
  return room.zones.map((zone) => ({
    key: `zone-${zone.id}`,
    label: zone.name,
    on: valveShots(
      zone.valveEntity ? rows[zone.valveEntity] : [],
      [],
      zone.id,
      span.start,
      span.end,
    ),
    phases: phaseBands(rows[phaseId(room.room.prefix, zone.id)], span.start, span.end),
  }));
}
