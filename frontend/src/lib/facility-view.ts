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
import { zoneProbes, type Probe, type ProbeHealth } from "./probes";

/** A physical substrate sensor: its moisture and EC probes paired by entity id (sensor.f1_z1_front_vwc
 * and sensor.f1_z1_front_ec are one sensor), with the worse of their two healths. */
export interface ZoneSensor {
  key: string;
  name: string;
  vwc: Probe | null;
  ec: Probe | null;
  health: ProbeHealth;
  text: string;
}
const HEALTH_RANK: Record<ProbeHealth, number> = {
  "no-reading": 0,
  "out-of-range": 1,
  stale: 2,
  stuck: 3,
  "left-out": 4,
  "not-counted": 5,
  ok: 6,
};
const KIND_SUFFIX = /[_ ](vwc|moisture|water_content|wc|ec|pwec|pw_ec|pore_ec|porewater_ec|bulk_ec|conductivity)$/i;
export function zoneSensors(probes: readonly Probe[]): ZoneSensor[] {
  const groups = new Map<string, ZoneSensor>();
  for (const probe of probes) {
    const key = probe.id.replace(/^sensor\./, "").replace(KIND_SUFFIX, "");
    const name = probe.name.replace(/\s*(VWC|moisture|water content|pore EC|pwEC|EC|conductivity)\s*$/i, "").trim() || key;
    const group = groups.get(key) ?? { key, name, vwc: null, ec: null, health: "ok" as ProbeHealth, text: "" };
    group[probe.kind] = probe;
    if (HEALTH_RANK[probe.health] < HEALTH_RANK[group.health]) {
      group.health = probe.health;
      group.text = probe.text;
    }
    groups.set(key, group);
  }
  // Probes whose ids do not share a stem but whose names do (one sensor's moisture and EC
  // entities named alike) are still one sensor.
  const byName = new Map<string, ZoneSensor>();
  for (const group of groups.values()) {
    const same = byName.get(group.name);
    if (same && !(same.vwc && group.vwc) && !(same.ec && group.ec)) {
      same.vwc ??= group.vwc;
      same.ec ??= group.ec;
      if (HEALTH_RANK[group.health] < HEALTH_RANK[same.health]) {
        same.health = group.health;
        same.text = group.text;
      }
    } else byName.set(group.name + (same ? `#${group.key}` : ""), group);
  }
  return [...byName.values()];
}

/** Where a zone stands with the automation, the most limiting first. */
export type ZoneMode = "room-off" | "offline" | "paused" | "watering-off" | "watering" | "automated";
export const ZONE_MODE: Record<ZoneMode, string> = {
  "room-off": "Room off",
  offline: "Offline",
  paused: "Paused",
  "watering-off": "Watering off",
  watering: "Watering now",
  automated: "Automated",
};

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
  /** Water delivered to the zone today, in litres. */
  waterL: number | null;
  mode: ZoneMode;
  sensors: ZoneSensor[];
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
          waterL: water.zoneL,
          mode: (!view.roomActive
            ? "room-off"
            : zone.stale
              ? "offline"
              : zone.enabled === false
                ? "paused"
                : view.engine.enabled === false
                  ? "watering-off"
                  : zone.valveOn === true
                    ? "watering"
                    : "automated") as ZoneMode,
          sensors: zoneSensors(zoneProbes(zone, states, now)),
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
