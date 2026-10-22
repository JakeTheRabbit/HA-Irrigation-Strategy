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
  /** When it was raised (epoch ms); on 3.17, when the controller last reported. */
  at: number;
}

interface InboxAlert {
  event_id?: string | null;
  ts?: string | null;
  code?: string | null;
  title?: string | null;
  zone?: number | null;
  rule_id?: string | null;
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
          at: alert.ts ? Date.parse(alert.ts) : NaN,
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
          at: controller.lastUpdated ?? NaN,
        })),
      );
  });
}
