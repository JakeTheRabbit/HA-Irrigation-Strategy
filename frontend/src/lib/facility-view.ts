import { zoneAttention, type AttentionReason, type ZoneFacts } from "./attention";
import { readJev, jevIds, parseJevSetpoints, type JevStage } from "./jev";
import { buildRoom, numeric, readable, roomStatus } from "./model";
import { reservoirView, type ReservoirView } from "./reservoir";
import { buildSetpointPreview } from "./setpoint-preview";
import { stockTanks, stockState, type StockState, type StockTankReading } from "./dosing";
import { tankTelemetry } from "./tank-telemetry";
import { eventTimes } from "./timeline";
import type { Controller, EntityState, LogEvent, Metric, States, Zone } from "./types";
import { dailyWater } from "./water-delivery";
import { roomPlants } from "./water-view";
import { climateReadings, rootZoneSensor, type ClimateReading } from "./zone-extras";

/** Why a zone's reading is not usable: the controller's rule is a fresh, readable number. */
export function readingIssue(metric: Metric, states: States): string | null {
  if (metric.value !== null) return null;
  const entity = metric.entityId ? states[metric.entityId] : undefined;
  if (!entity) return "not mapped";
  if (!readable(entity) || numeric(entity) === null) return "not reporting";
  return "not reporting lately";
}
/** The probes a zone's combined reading leaves out (the integration's fused sensor attributes), but
 * not those the zone's setup chose not to count. */
export function excludedProbes(entity: EntityState | undefined, kind: "vwc" | "ec") {
  const excluded = entity?.attributes.excluded;
  return excluded && typeof excluded === "object" && !Array.isArray(excluded)
    ? Object.entries(excluded as Record<string, unknown>)
        .filter(([, reason]) => reason !== "not counted")
        .map(([probe, reason]) => ({
          probe,
          reason: typeof reason === "string" && reason ? reason : "left out",
          kind,
        }))
    : [];
}
/** A shot in P3 is a rescue: the controller waters overnight only below the rescue floor. */
export const isRescue = (event: LogEvent) =>
  event.zoneId !== undefined &&
  event.type === "water" &&
  /\bP3\b|rescue|emergency/i.test(event.message);

const finite = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

/** One zone at a glance: its moisture against today's peak and its targets, its pore EC against the
 * stage's band, its root-zone temperature, and whatever needs the grower. */
export interface FacilityZone {
  zone: Zone;
  /** Today's highest moisture since lights-on and how far the zone has dried back from it, in VWC
   * points (the controller's dryback sensor); null where the controller does not report it. */
  peak: number | null;
  drybackPoints: number | null;
  /** The zone's saved targets: the rescue floor, the re-water point and the peak target. */
  rescue: number | null;
  rewater: number | null;
  target: number | null;
  rootTemp: number | null;
  rootUnit: string;
  mlPerPlant: number | null;
  attention: AttentionReason[];
}
export interface FacilityRoom {
  room: Controller["rooms"][number];
  view: ReturnType<typeof buildRoom>;
  status: ReturnType<typeof roomStatus>;
  stage: JevStage | null;
  climate: ClimateReading[];
  zones: FacilityZone[];
  tank: ReturnType<typeof tankTelemetry>;
  reservoir: ReservoirView;
  stock: (StockTankReading & { state: StockState })[];
  /** Water delivered today across the zones that report it, and per plant over the zones that also
   * know their plant count. */
  waterL: number | null;
  litresPerPlant: number | null;
}

/** Every room read from the one live snapshot, for any room (not only the selected one): nothing
 * here fetches history or calls the controller. The not-watered rule needs today's readings and so
 * stays on the room's own page. */
export function facilityView(
  controller: Controller,
  format: { clock: (time: number) => string; number: (value: number, digits?: number) => string; perPlant: (ml: number) => string },
  now = Date.now(),
): FacilityRoom[] {
  const { states } = controller;
  return controller.rooms.map((room) => {
    const view = buildRoom(states, room);
    const scoped = { ...controller, room: view, roomId: room.id };
    const prefix = room.prefix;
    const stage = readJev(states, prefix).room?.stage ?? null;
    const plants = roomPlants(scoped);
    let waterL: number | null = null;
    let plantL = 0;
    let plantCount = 0;
    const zones = view.zones.map((zone) => {
      const saved = buildSetpointPreview(view, states, zone.id, {}).saved.parameters;
      const water = dailyWater(zone, plants[zone.id] ?? null);
      if (water.zoneL !== null) {
        waterL = (waterL ?? 0) + water.zoneL;
        const count = plants[zone.id];
        if (count !== null && count !== undefined && count > 0) {
          plantL += water.zoneL;
          plantCount += count;
        }
      }
      const dryback = states[`sensor.crop_steering_${prefix}zone_${zone.id}_dryback_app`];
      const rootId = rootZoneSensor(states, room, zone.id);
      const stopped =
        !view.roomActive || zone.stale || view.engine.enabled === false || zone.enabled === false;
      const facts: ZoneFacts = {
        id: zone.id,
        name: zone.name,
        phase: zone.phase,
        vwc: zone.vwc.value,
        ec: zone.ec.value,
        vwcIssue: readingIssue(zone.vwc, states),
        ecIssue: readingIssue(zone.ec, states),
        excluded: [
          ...excludedProbes(zone.vwc.entityId ? states[zone.vwc.entityId] : undefined, "vwc"),
          ...excludedProbes(zone.ec.entityId ? states[zone.ec.entityId] : undefined, "ec"),
        ],
        mlPerPlant: water.mlPerPlant,
        rewater: saved.p2_vwc_threshold ?? null,
        readings: [],
        lastShot: zone.lastIrrigation.timestamp ? Date.parse(zone.lastIrrigation.timestamp) : null,
        jevPausedUntil:
          parseJevSetpoints(states[jevIds(prefix).zone(zone.id)])?.pausedUntil ?? null,
        watering: !stopped,
      };
      return {
        facts,
        item: {
          zone,
          peak: finite(dryback?.attributes.peak_vwc),
          drybackPoints: finite(dryback?.attributes.dryback_points),
          rescue: saved.p3_emergency_vwc_threshold ?? null,
          rewater: saved.p2_vwc_threshold ?? null,
          target: saved.p1_target_vwc ?? null,
          rootTemp: rootId ? numeric(states[rootId]) : null,
          rootUnit: rootId ? String(states[rootId]?.attributes.unit_of_measurement || "°C") : "°C",
          mlPerPlant: water.mlPerPlant,
          attention: [] as AttentionReason[],
        } satisfies FacilityZone,
      };
    });
    const times = eventTimes(view.events, now);
    const rescues = view.events.flatMap((event, index) => {
      const time = isRescue(event) ? times[index] : null;
      return time === null ? [] : [{ zoneId: event.zoneId!, time }];
    });
    const attention = zoneAttention({
      now,
      zones: zones.map((z) => z.facts),
      poreEc: stage?.poreEc ?? null,
      notices: view.alerts,
      rescues,
      format,
    });
    for (const z of zones) z.item.attention = attention.get(z.item.zone.id) ?? [];
    return {
      room,
      view,
      status: roomStatus(states, room, now),
      stage,
      climate: climateReadings(states, room),
      zones: zones.map((z) => z.item),
      tank: tankTelemetry(states, room, now),
      reservoir: reservoirView(states, prefix),
      stock: stockTanks(states, prefix).map((tank) => ({ ...tank, state: stockState(tank) })),
      waterL,
      litresPerPlant: plantCount > 0 ? plantL / plantCount : null,
    };
  });
}
