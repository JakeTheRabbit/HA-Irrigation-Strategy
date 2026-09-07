import { RunDemo } from "./comparison-demo";
import type {
  OperatorAction,
  StrategyDocument,
  SetupDocument,
  SetupRoom,
  SetupZone,
  GrowPlan,
  ParameterLimit,
  PlanZonePreview,
} from "./operator-types";
import type { States } from "./types";
import { discoverRooms, numeric } from "./model";
import { blockForDay, dateForDay, growDay, interpolate, localDate, planErrors } from "./grow-plan";

const clone = <T>(value: T): T => structuredClone(value);
export class OperatorDemo {
  private runDemo?: RunDemo;
  private plans = new Map<string, StrategyDocument>();
  private rooms: SetupRoom[] | null = null;
  constructor(
    private getStates: () => States,
    private updateStates: (states: States) => void,
  ) {}
  private setup(): SetupDocument {
    const states = this.getStates();
    if (!this.rooms)
      this.rooms = discoverRooms(states).map((room, index) => ({
        entry_id: "demo-entry-" + index,
        revision: 1,
        room_name: room.name,
        prefix: room.prefix,
        slug: room.prefix.replace(/_$/, ""),
        active: true,
        num_zones: 3,
        active_zone_ids: [1, 2, 3],
        zones: [1, 2, 3].map((id) => ({
          id,
          name: "Zone " + id,
          active: true,
          valve: "switch.demo_" + index + "_valve_" + id,
          vwc_sensors: ["sensor.crop_steering_" + room.prefix + "vwc_zone_" + id],
          ec_sensors: ["sensor.crop_steering_" + room.prefix + "ec_zone_" + id],
          plant_count: 36,
          substrate_volume: 6,
          drippers_per_plant: 1,
          dripper_flow_rate: 4,
        })),
        hardware: {
          pump_switch: "switch.demo_" + index + "_pump",
          main_line_switch: "switch.demo_" + index + "_mainline",
        },
        safety: { ready: false, blockers: [] },
      }));
    for (const room of this.rooms) {
      const descriptor = states["sensor.crop_steering_" + room.prefix + "engine_config"];
      const flag = String(descriptor?.attributes.enable_flag || "");
      room.safety = {
        ready: states[flag]?.state === "off",
        blockers:
          states[flag]?.state === "off"
            ? []
            : ["Turn off this room's engine in Settings before changing mappings."],
      };
    }
    const candidates = Object.values(states).map((e) => ({
      entity_id: e.entity_id,
      name: String(e.attributes.friendly_name || e.entity_id),
      domain: e.entity_id.split(".")[0],
      state: e.state,
      unit: String(e.attributes.unit_of_measurement || ""),
    }));
    for (const room of this.rooms)
      for (const entity_id of [
        room.hardware.pump_switch,
        room.hardware.main_line_switch,
        ...room.zones.map((z) => z.valve),
      ]) {
        if (
          typeof entity_id === "string" &&
          entity_id &&
          !candidates.some((c) => c.entity_id === entity_id)
        )
          candidates.push({
            entity_id,
            name: entity_id.replace("switch.demo_", "Demo ").replaceAll("_", " "),
            domain: "switch",
            state: "off",
            unit: "",
          });
      }
    // Spare channels let the isolated setup walkthrough add rooms without live hardware.
    for (let i = 1; i <= 6; i++)
      candidates.push({
        entity_id: "switch.demo_spare_" + i,
        name: "Spare valve " + i + " (demo)",
        domain: "switch",
        state: "off",
        unit: "",
      });
    return clone({
      api_version: 1,
      capabilities: { create: true, save: true, remove: true, stable_zone_ids: true },
      rooms: this.rooms,
      candidates,
      limits: { max_zones: 24 },
    });
  }
  private plan(roomId: string): StrategyDocument {
    const existing = this.plans.get(roomId);
    const room = discoverRooms(this.getStates()).find((r) => r.id === roomId);
    if (!room) throw new Error("Select an available room.");
    const roomSetup = this.setup().rooms.find((r) => r.prefix === room.prefix)!;
    const catalog: StrategyDocument["catalog"] = {};
    const profiles: GrowPlan["profiles"] = [];
    const zones: GrowPlan["zones"] = [];
    for (const zone of roomSetup.zones.filter((z) => z.active)) {
      const limits: Record<string, ParameterLimit> = {};
      const sample: Record<string, [number, number, number, number, string]> = {
        dryback_target: [8, 1, 30, 0.5, "% of peak"],
        p1_target_vwc: [64, 20, 90, 0.5, "%"],
        p2_vwc_threshold: [54, 10, 90, 0.5, "%"],
        p1_initial_shot_size: [6, 0.5, 20, 0.5, "%"],
        p2_shot_size: [4, 0.5, 20, 0.5, "%"],
        p3_emergency_vwc_threshold: [35, 10, 70, 0.5, "%"],
        p3_emergency_shot_size: [3, 0.5, 15, 0.5, "%"],
        ec_target_p0: [3, 0.5, 8, 0.1, "mS/cm"],
        ec_target_p1: [3, 0.5, 8, 0.1, "mS/cm"],
        ec_target_p2: [3, 0.5, 8, 0.1, "mS/cm"],
        p0_maximum_wait_time: [120, 15, 360, 1, "min"],
        p1_time_between_shots: [15, 5, 120, 1, "min"],
        p1_maximum_shots: [8, 1, 30, 1, ""],
      };
      for (const [key, [value, min, max, step, unit]] of Object.entries(sample))
        limits[key] = { value, min, max, step, unit, entity_ids: [] };
      catalog[String(zone.id)] = limits;
      const vegetative = Object.fromEntries(Object.entries(limits).map(([k, v]) => [k, v.value!]));
      const generative = {
        ...vegetative,
        dryback_target: 12,
        p1_target_vwc: 60,
        p2_vwc_threshold: 48,
        ec_target_p0: 3.5,
        ec_target_p1: 3.5,
        ec_target_p2: 4,
        p2_shot_size: 3,
      };
      const id = "zone-" + zone.id;
      profiles.push({ id, name: zone.name + " endpoints", vegetative, generative });
      zones.push({
        zone_id: zone.id,
        start_date: dateForDay(localDate(), -13),
        schedule: [
          { start_day: 1, end_day: 14, profile_id: id, bias: 20 },
          { start_day: 15, end_day: 35, profile_id: id, bias: 70 },
          { start_day: 36, end_day: 63, profile_id: id, bias: 40 },
          { start_day: 64, end_day: 84, profile_id: id, bias: 60 },
        ],
      });
    }
    if (existing) {
      existing.catalog = catalog;
      return existing;
    }
    const result: StrategyDocument = {
      room_id: roomId,
      revision: 1,
      status: "draft",
      plan: { schema_version: 1, profiles, zones },
      active: { grow_day: null, zones: [] },
      error: null,
      capabilities: { strategy_snapshot_version: 1, controller_supported: true },
      catalog,
    };
    this.plans.set(roomId, result);
    return result;
  }
  private preview(doc: StrategyDocument, plan: GrowPlan, date: string): StrategyDocument {
    const room = this.setup().rooms.find((r) => "room:" + r.prefix === doc.room_id);
    const zones: PlanZonePreview[] = plan.zones.map((zone) => {
      const day = growDay(zone.start_date, date),
        block = blockForDay(zone, day);
      const profile = plan.profiles.find((p) => p.id === block?.profile_id);
      const parameters = interpolate(profile, block?.bias ?? 50, doc.catalog[String(zone.zone_id)]);
      const size = room?.zones.find((z) => z.id === zone.zone_id);
      const pot = size?.substrate_volume ?? 6,
        plants = size?.plant_count ?? 36,
        drippers = size?.drippers_per_plant ?? 1,
        flow = size?.dripper_flow_rate ?? 4;
      const zoneFlow = (plants * drippers * flow) / 3600;
      const shots = Object.fromEntries(
        ["p1_initial_shot_size", "p2_shot_size", "p3_emergency_shot_size"].map((k) => {
          const volume = (pot * plants * (parameters[k] ?? 0)) / 100,
            duration = volume / zoneFlow;
          return [
            k,
            { volume_l: volume, duration_s: duration, capped_duration_s: Math.min(duration, 900) },
          ];
        }),
      );
      return {
        zone_id: zone.zone_id,
        day,
        profile_id: block?.profile_id,
        bias: block?.bias,
        parameters,
        hydraulics: {
          substrate_l_per_plant: pot,
          plant_count: plants,
          drippers_per_plant: drippers,
          dripper_flow_lph: flow,
          zone_substrate_l: pot * plants,
          zone_flow_lps: zoneFlow,
          shots,
        },
        errors: block ? [] : ["No plan block on this date."],
      };
    });
    return { ...clone(doc), plan: clone(plan), preview: { date, zones } };
  }
  async call<T>(action: OperatorAction, data: Record<string, unknown>): Promise<T> {
    if (action.startsWith("runs_")) {
      this.runDemo ||= new RunDemo(this.getStates);
      return this.runDemo.call(action, data) as T;
    }
    let result: unknown;
    if (action.startsWith("strategy_")) {
      const doc = this.plan(String(data.room_id));
      if (action === "strategy_get") result = doc;
      if (action === "strategy_preview")
        result = this.preview(
          doc,
          (data.plan as GrowPlan) || doc.plan,
          String(data.date || localDate()),
        );
      if (action === "strategy_save") {
        if (doc.status !== "draft") throw new Error("Disarm the active plan before editing.");
        if (data.expected_revision !== doc.revision)
          throw new Error("Plan changed. Reload before saving.");
        const plan = data.plan as GrowPlan,
          errors = planErrors(plan, doc.catalog);
        if (errors.length) throw new Error(errors.join(" "));
        doc.plan = clone(plan);
        doc.revision++;
        doc.status = "draft";
        result = doc;
      }
      if (action === "strategy_activate") {
        if (doc.status !== "draft") throw new Error("Disarm the plan before arming it again.");
        if (data.expected_revision !== doc.revision) throw new Error("Plan revision changed.");
        const errors = planErrors(doc.plan, doc.catalog);
        if (errors.length) throw new Error(errors.join(" "));
        doc.status = "armed";
        doc.revision++;
        result = doc;
      }
      if (action === "strategy_disarm") {
        doc.status = doc.status === "active" ? "disarming" : "draft";
        doc.revision++;
        result = doc;
      }
    } else {
      const setup = this.setup();
      if (action === "setup_read") result = setup;
      else {
        const room = this.rooms!.find((r) => r.entry_id === data.entry_id);
        if (action !== "setup_create" && (!room || room.revision !== data.expected_revision))
          throw new Error("Room changed. Reload setup.");
        if (room && !room.safety.ready) throw new Error(room.safety.blockers.join(" "));
        if (action === "setup_remove") {
          if (data.confirm_name !== room!.room_name) throw new Error("Enter the exact room name.");
          room!.active = false;
          room!.revision++;
          result = { entry_id: room!.entry_id, archived: true, revision: room!.revision };
        } else {
          const zones = clone(data.zones as SetupZone[]);
          if (!zones?.length || zones.length > 24)
            throw new Error("Configure between 1 and 24 zone slots.");
          const valves = zones.filter((z) => z.active).map((z) => z.valve);
          if (valves.some((v) => !v) || new Set(valves).size !== valves.length)
            throw new Error("Each active zone needs a distinct valve.");
          const otherValves = new Set(
            this.rooms!.filter((r) => r !== room && r.active).flatMap((r) =>
              r.zones.filter((z) => z.active).map((z) => z.valve),
            ),
          );
          if (valves.some((v) => otherValves.has(v)))
            throw new Error("A valve is already mapped to another room.");
          if (!String(data.room_name || "").trim()) throw new Error("Enter a room name.");
          const fresh: SetupRoom = room || {
            entry_id: "demo-entry-" + this.rooms!.length,
            revision: 0,
            room_name: "",
            prefix: "demo" + this.rooms!.length + "_",
            slug: "demo" + this.rooms!.length,
            active: true,
            num_zones: 0,
            active_zone_ids: [],
            zones: [],
            hardware: {},
            safety: { ready: true, blockers: [] },
          };
          Object.assign(fresh, {
            room_name: String(data.room_name).trim(),
            zones,
            hardware: clone(data.hardware as Record<string, string | number>),
            active: data.active !== false,
          });
          fresh.revision++;
          fresh.num_zones = Math.max(...zones.map((z) => z.id));
          fresh.active_zone_ids = zones.filter((z) => z.active).map((z) => z.id);
          if (!room) this.rooms!.push(fresh);
          result = fresh;
        }
        const states = { ...this.getStates() },
          target = room || (result as SetupRoom);
        if (target) {
          const id = "sensor.crop_steering_" + target.prefix + "engine_config";
          const flag = String(
            states[id]?.attributes.enable_flag ||
              "switch.crop_steering_" + target.prefix + "engine_enabled",
          );
          states[id] = {
            entity_id: id,
            state: "ready",
            attributes: {
              ...(states[id]?.attributes || {}),
              prefix: target.prefix,
              slug: target.slug,
              num_zones: target.num_zones,
              active_zone_ids: target.active_zone_ids,
              active: target.active,
              friendly_name: target.room_name + " engine config",
              enable_flag: flag,
              zone_names: Object.fromEntries(target.zones.map((z) => [z.id, z.name])),
            },
            last_updated: new Date().toISOString(),
          };
          if (!states[flag])
            states[flag] = {
              entity_id: flag,
              state: "off",
              attributes: {},
              last_updated: new Date().toISOString(),
            };
          this.updateStates(states);
        }
      }
    }
    if (result === undefined) throw new Error("Unsupported demo action.");
    return clone(result) as T;
  }
}
