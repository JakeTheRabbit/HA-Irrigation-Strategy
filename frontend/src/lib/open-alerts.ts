import { asCode } from "./error-codes";
import { buildRoom } from "./model";
import type { Controller } from "./types";

/** One alert still open in a room: the room tree's flag, a zone's problems, the timeline's failed
 * chip and the System cards all read this one list. */
export interface OpenAlert {
  /** The Journal event that raised it; null for a 3.17 notice. */
  eventId: string | null;
  roomId: string;
  zone: number | null;
  code: string | null;
  title: string;
  ruleId: string | null;
  /** The entity it concerns, where the integration names one (3.18 inbox `entity_id`). */
  entityId?: string | null;
  /** When it was raised (epoch ms); on 3.17, when the controller last reported. Null when
   * unknown: sort with `newestFirst`, which puts those last. */
  at: number | null;
}

/** Newest first; alerts with no known time last. */
export const newestFirst = (a: OpenAlert, b: OpenAlert) =>
  a.at === null ? (b.at === null ? 0 : 1) : b.at === null ? -1 : b.at - a.at;

const instant = (text: string | null | undefined) => {
  const ms = text ? Date.parse(text) : NaN;
  return Number.isNaN(ms) ? null : ms;
};

interface InboxAlert {
  event_id?: string | null;
  ts?: string | null;
  code?: string | null;
  title?: string | null;
  zone?: number | null;
  rule_id?: string | null;
  entity_id?: string | null;
  acknowledged?: boolean;
}

/** Every room's open alerts, each room newest first: the integration's inbox
 * (sensor.crop_steering_<prefix>alerts_open, attr `alerts`, 3.18). Without a readable inbox (3.17,
 * or the Journal down) the room's own warning and critical notices stand in, as the Today
 * attention rule reads them; a notice about several zones counts once per zone. */
export function openAlerts(controller: Controller): OpenAlert[] {
  const { states, rooms } = controller;
  return rooms.flatMap((room): OpenAlert[] => {
    const inbox = states[`sensor.crop_steering_${room.prefix}alerts_open`]?.attributes.alerts;
    if (Array.isArray(inbox))
      return (inbox as InboxAlert[])
        .filter((alert) => alert && alert.acknowledged !== true)
        .map((alert) => ({
          eventId: alert.event_id ?? null,
          roomId: room.id,
          zone: typeof alert.zone === "number" ? alert.zone : null,
          code: alert.code ?? null,
          title: alert.title || alert.code || "Alert",
          ruleId: alert.rule_id ?? null,
          entityId: alert.entity_id ?? null,
          at: instant(alert.ts),
        }));
    return buildRoom(states, room)
      .alerts.filter((notice) => notice.severity !== "info")
      .flatMap((notice) =>
        (notice.zoneIds?.length ? notice.zoneIds : [notice.zoneId ?? null]).map((zone) => ({
          eventId: null,
          roomId: room.id,
          zone,
          code: asCode(notice.title),
          title: notice.title,
          ruleId: null,
          at: controller.lastUpdated ?? null,
        })),
      );
  });
}
