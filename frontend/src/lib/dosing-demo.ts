import {
  BATCH_STEPS,
  STEP_LABELS,
  dosingConfigId,
  dosingStatusId,
  parseConfig,
  readConfig,
  readStatus,
  recipeRows,
  requestStage,
  setupErrors,
  type DosingConfig,
  type DosingDocument,
  type DosingPump,
  type DosingRequest,
  type DosingRequestResult,
  type DosingStatus,
  type PumpRuntime,
} from "./dosing";
import { numeric } from "./model";
import type { OperatorAction } from "./operator-types";
import type { StockDocument } from "./stock";
import type { EntityState, States } from "./types";
import { createUuid } from "./uuid";

/** The integration's stock services, as the demo's controller calls them. */
export type StockCall = (
  action: "stock_get" | "stock_draw",
  data: Record<string, unknown>,
) => StockDocument;

/** The demo's controller takes a request this long after it is sent (a real one reads every 2 s). */
const TAKE_MS = 600;
const TICK_MS = 250;
/** Demo time: a batch's minutes of mixing pass in seconds, each of its doses in at most 3 s, and a
 * dose asked for by hand in at most 20 s. The page still reads real mL and seconds. It advances on
 * the timer, not on the clock, so it runs as well where the clock stands still. */
const MIX_SPEED = 60;
const BATCH_DOSE_S = 3;
const DOSE_S = 20;
/** How long the demo's other steps take, in ms. */
const STEP_MS = { hold: 500, close: 500, fill: 4000, mix: 1000, finish: 500 };
const CANDIDATE_DOMAINS = [
  "number",
  "input_number",
  "button",
  "input_button",
  "script",
  "binary_sensor",
  "sensor",
  "switch",
  "input_boolean",
  "input_datetime",
];

interface Dose {
  pump: DosingPump;
  ml: number;
  expected: number;
  speed: number;
  elapsed: number;
  /** The volume number before the dose, put back after it. */
  volume: string | null;
  at: string;
  by: string;
  /** What its stock draw is counted under, and whether it is a dose by hand or a batch's. */
  key: string;
  source: "dose" | "batch";
}
interface Batch {
  /** The request's id: each dose's stock draw is counted under it. */
  request: string;
  step: number;
  ms: number;
  /** The recipe's doses, read when the batch was taken. */
  queue: { pump: DosingPump; ml: number }[];
  dose: Dose | null;
  doses: Record<string, number>;
  /** The tank's level when filling started. */
  level: number | null;
  at: string;
  by: string;
}
interface Room {
  prefix: string;
  status: DosingStatus;
  take: { request: DosingRequest; wait: number } | null;
  dose: Dose | null;
  batch: Batch | null;
}
interface Tx {
  get: (id: string | null) => EntityState | undefined;
  /** A new state for an entity the demo has; nothing for one it does not. */
  set: (id: string | null, state: string | number) => void;
  put: (entity: EntityState) => void;
  /** Runs once this change is published: a call to another service sees it. */
  later: (run: () => void) => void;
  now: number;
  stamp: string;
}
const round = (value: number, digits = 1) => Math.round(value * 10 ** digits) / 10 ** digits;
const idle = (flow: number | null): PumpRuntime => ({
  state: "idle",
  flow_ml_s: flow,
  target_ml: null,
  started_at: null,
  expected_s: null,
  last: null,
});

/** The integration's dosing services and the controller's dosing thread, in memory, for the demo:
 * a dose runs for its mL over the pump's flow and finishes, a batch walks its steps, Stop ends
 * either. It moves the demo's own pump, valve and float entities as the real ones would move, and
 * draws what each dose dosed from its pump's stock tank (`stock`: the demo's stock services). */
export class DosingDemo {
  private rooms = new Map<string, Room>();
  private timer: ReturnType<typeof setInterval> | null = null;
  constructor(
    private getStates: () => States,
    private updateStates: (states: States) => void,
    private stock?: StockCall,
  ) {}

  call(
    action: OperatorAction,
    data: Record<string, unknown>,
  ): DosingDocument | DosingRequestResult {
    const roomId = String(data.room_id ?? "");
    const prefix = roomId.startsWith("room:") ? roomId.slice(5) : "";
    const config = this.config(prefix);
    if (action === "dosing_get") return this.document(roomId, config, null);
    if (action === "dosing_save") return this.save(roomId, prefix, config, data);
    if (action === "dosing_request") return this.request(prefix, config, data);
    throw new Error("Unsupported demo action.");
  }

  private config(prefix: string): DosingConfig {
    return readConfig(this.getStates()[dosingConfigId(prefix)]) ?? parseConfig({})!;
  }
  private room(prefix: string): Room {
    let room = this.rooms.get(prefix);
    if (!room) {
      room = {
        prefix,
        status: readStatus(this.getStates()[dosingStatusId(prefix)]) ?? {
          state: "idle",
          pumps: {},
          batch: {
            step: "idle",
            pump: null,
            started_at: null,
            step_started_at: null,
            steps: [],
            result: null,
            ended_at: null,
          },
          handled: null,
          handled_result: null,
          history: [],
          updated_at: null,
        },
        take: null,
        dose: null,
        batch: null,
      };
      this.rooms.set(prefix, room);
    }
    return room;
  }
  private document(roomId: string, config: DosingConfig, error: string | null): DosingDocument {
    const candidates = Object.values(this.getStates())
      .filter((entity) => CANDIDATE_DOMAINS.includes(entity.entity_id.split(".")[0]))
      .map((entity) => ({
        entity_id: entity.entity_id,
        name: String(entity.attributes.friendly_name || entity.entity_id),
        domain: entity.entity_id.split(".")[0],
        state: entity.state,
        unit: String(entity.attributes.unit_of_measurement || ""),
        ...(typeof entity.attributes.device_class === "string"
          ? { device_class: entity.attributes.device_class }
          : {}),
      }));
    // The demo's user is an administrator.
    return structuredClone({
      schema_version: 1,
      room_id: roomId,
      config,
      candidates,
      can_edit: true,
      error,
    });
  }
  /** One change to the demo's states, published once. */
  private transact(run: (tx: Tx) => void) {
    const states = { ...this.getStates() };
    const now = Date.now(),
      stamp = new Date(now).toISOString();
    const later: (() => void)[] = [];
    run({
      now,
      stamp,
      get: (id) => (id ? states[id] : undefined),
      put: (entity) => (states[entity.entity_id] = entity),
      set: (id, state) => {
        const old = id ? states[id] : undefined;
        if (!id || !old) return;
        const next = String(state);
        states[id] = {
          ...old,
          state: next,
          last_changed: next === old.state ? old.last_changed : stamp,
          last_updated: stamp,
        };
      },
      later: (task) => later.push(task),
    });
    this.updateStates(states);
    for (const task of later) task();
  }

  private save(
    roomId: string,
    prefix: string,
    config: DosingConfig,
    data: Record<string, unknown>,
  ): DosingDocument {
    if (data.expected_revision !== config.revision)
      return this.document(roomId, config, "revision");
    if (requestStage(config, this.room(prefix).status, Date.now())?.stage === "waiting")
      return this.document(roomId, config, "busy");
    const saved = parseConfig({
      revision: config.revision + 1,
      pumps: data.pumps,
      batch: data.batch,
      request: config.request,
      updated_at: new Date().toISOString(),
    })!;
    const states = this.getStates();
    // A pump may be linked only to one of the room's stock tanks.
    const tanks = this.stock?.("stock_get", { room_id: roomId }).tanks.map((tank) => tank.id);
    const errors =
      Array.isArray(data.pumps) && saved.pumps.length === data.pumps.length
        ? setupErrors(
            {
              pumps: saved.pumps.map((pump) => ({ ...pump, key: pump.id })),
              batch: saved.batch,
            },
            tanks ?? null,
          )
        : [
            "Each pump needs an id of lowercase letters, digits and underscores, unlike the others.",
          ];
    const batch = saved.batch;
    for (const id of [
      ...saved.pumps.flatMap((pump) => [
        pump.volume_entity,
        pump.start_entity,
        pump.dosing_entity,
        pump.power_entity,
        pump.flow_entity,
      ]),
      batch.fill_valve,
      batch.full_entity,
      batch.mix_pump,
      ...batch.mix_valves,
      batch.mix_power_sensor,
      ...batch.close_entities,
      batch.hold_entity,
      batch.filled_at_entity,
      ...batch.recipe.map((line) => line.ml_entity),
    ])
      if (id && !states[id]) errors.push(`${id} does not exist in Home Assistant.`);
    if (errors.length) return this.document(roomId, config, [...new Set(errors)].join(" "));
    const room = this.room(prefix);
    room.status.pumps = Object.fromEntries(
      saved.pumps.map((pump) => [
        pump.id,
        room.status.pumps[pump.id] ?? idle(numeric(states[pump.flow_entity])),
      ]),
    );
    this.writeConfig(prefix, saved);
    this.transact((tx) => this.publish(tx, room));
    return this.document(roomId, saved, null);
  }
  private writeConfig(prefix: string, config: DosingConfig) {
    const id = dosingConfigId(prefix),
      states = this.getStates(),
      stamp = new Date().toISOString();
    this.updateStates({
      ...states,
      [id]: {
        entity_id: id,
        state: String(config.revision),
        attributes: {
          ...(states[id]?.attributes ?? { friendly_name: "Dosing configuration" }),
          pumps: config.pumps,
          batch: config.batch,
          request: config.request,
          updated_at: config.updated_at,
        },
        last_changed: stamp,
        last_updated: stamp,
      },
    });
  }

  private request(
    prefix: string,
    config: DosingConfig,
    data: Record<string, unknown>,
  ): DosingRequestResult {
    const action = (["dose", "batch", "stop"] as const).find((item) => item === data.action);
    if (!action) return { request: null, error: "The action must be dose, batch or stop." };
    const room = this.room(prefix);
    if (action !== "stop" && requestStage(config, room.status, Date.now())?.stage === "waiting")
      return { request: null, error: "busy" };
    let pump: string | null = null,
      ml: number | null = null;
    if (action === "dose") {
      const found = config.pumps.find((item) => item.id === data.pump);
      if (!found) return { request: null, error: `This room has no pump ${String(data.pump)}.` };
      ml = Number(data.ml);
      if (!(ml > 0 && ml <= found.max_ml))
        return {
          request: null,
          error: `${found.name} doses more than 0 and at most ${found.max_ml} mL.`,
        };
      pump = found.id;
    }
    const request: DosingRequest = {
      id: createUuid().replaceAll("-", ""),
      action,
      pump,
      ml,
      at: new Date().toISOString(),
      by: "Demo",
    };
    this.writeConfig(prefix, { ...config, request });
    room.take = { request, wait: TAKE_MS };
    this.timer ??= setInterval(() => this.tick(), TICK_MS);
    return { request: structuredClone(request), error: null };
  }

  private tick() {
    for (const room of this.rooms.values())
      if (room.take || room.dose || room.batch)
        this.transact((tx) => {
          if (room.take && (room.take.wait -= TICK_MS) <= 0) {
            const { request } = room.take;
            room.take = null;
            this.handle(tx, room, request);
          } else if (room.batch) this.advanceBatch(tx, room);
          else if (room.dose && this.advanceDose(tx, room, room.dose)) {
            this.remember(room, "dose", room.dose, room.dose.ml, "finished", tx.stamp);
            room.dose = null;
          }
          this.publish(tx, room);
        });
    if ([...this.rooms.values()].every((room) => !room.take && !room.dose && !room.batch)) {
      clearInterval(this.timer!);
      this.timer = null;
    }
  }
  private publish(tx: Tx, room: Room) {
    const id = dosingStatusId(room.prefix);
    const old = tx.get(id);
    const { status } = room;
    status.state = room.batch
      ? "batch"
      : Object.values(status.pumps).some((pump) => pump.state === "dosing")
        ? "dosing"
        : "idle";
    status.updated_at = tx.stamp;
    tx.put({
      entity_id: id,
      state: status.state,
      attributes: {
        ...(old?.attributes ?? { friendly_name: "Dosing" }),
        pumps: structuredClone(status.pumps),
        batch: structuredClone(status.batch),
        handled: status.handled,
        handled_result: status.handled_result,
        history: structuredClone(status.history),
        updated_at: status.updated_at,
      },
      last_changed: old?.state === status.state ? old.last_changed : tx.stamp,
      last_updated: tx.stamp,
    });
  }

  /** What the controller does with a request it takes. */
  private handle(tx: Tx, room: Room, request: DosingRequest) {
    const config = readConfig(tx.get(dosingConfigId(room.prefix))) ?? parseConfig({})!;
    const { status } = room;
    status.handled = request.id;
    const refuse = (why: string) => (status.handled_result = `refused: ${why}`);
    if (request.action === "stop") {
      status.handled_result = room.batch || room.dose ? "stopped" : "nothing was running";
      if (room.batch) this.stopBatch(tx, room, config);
      else if (room.dose) {
        const ml = Math.min(room.dose.ml, room.dose.elapsed * (room.dose.ml / room.dose.expected));
        this.endDose(tx, room, room.dose, "stopped", ml);
        this.remember(room, "dose", room.dose, ml, "stopped", tx.stamp);
        room.dose = null;
      }
      return;
    }
    if (room.batch) return refuse("a batch is running");
    if (room.dose) return refuse("a dose is running");
    if (request.action === "dose") {
      const pump = config.pumps.find((item) => item.id === request.pump);
      if (!pump) return refuse("this room has no such pump");
      if (!((numeric(tx.get(pump.flow_entity)) ?? 0) > 0))
        return refuse(`${pump.name} is not calibrated`);
      if (!(request.ml! > 0 && request.ml! <= pump.max_ml))
        return refuse(`${request.ml} mL is more than ${pump.name} doses`);
      room.dose = this.startDose(
        tx,
        room,
        pump,
        request.ml!,
        DOSE_S,
        request.by ?? "Demo",
        request.id,
        "dose",
      );
      status.handled_result = "dosing";
      return;
    }
    if (config.batch.hold_entity && tx.get(config.batch.hold_entity)?.state === "on")
      return refuse("the batch flag is already on");
    // As the controller does: every amount is read before anything moves, and an amount entity
    // that reads nothing refuses the batch rather than falling back to the fixed amount.
    const rows = recipeRows(config, this.getStates());
    const unread = rows.find((row) => row.unreadable);
    if (unread) return refuse(`the recipe amount for ${unread.name} can't be read`);
    room.batch = {
      request: request.id,
      step: -1,
      ms: 0,
      queue: rows.flatMap((row) => {
        const pump = config.pumps.find((item) => item.id === row.pump);
        return pump && !row.skipped ? [{ pump, ml: row.ml }] : [];
      }),
      dose: null,
      doses: {},
      level: null,
      at: tx.stamp,
      by: request.by ?? "Demo",
    };
    status.batch = {
      step: "hold",
      pump: null,
      started_at: tx.stamp,
      step_started_at: tx.stamp,
      steps: [],
      result: null,
      ended_at: null,
    };
    status.handled_result = "making a batch";
    this.enterStep(tx, room, config, 0);
  }

  private startDose(
    tx: Tx,
    room: Room,
    pump: DosingPump,
    ml: number,
    longest: number,
    by: string,
    key: string,
    source: Dose["source"],
  ): Dose {
    const flow = numeric(tx.get(pump.flow_entity)) ?? 1;
    const expected = ml / flow;
    const volume = tx.get(pump.volume_entity)?.state ?? null;
    tx.set(pump.volume_entity, ml);
    tx.set(pump.start_entity, tx.stamp);
    tx.set(
      pump.dosing_entity,
      pump.dosing_entity.startsWith("binary_sensor.") ? "on" : pump.dosing_prefix,
    );
    room.status.pumps[pump.id] = {
      ...(room.status.pumps[pump.id] ?? idle(flow)),
      state: "dosing",
      flow_ml_s: flow,
      target_ml: ml,
      started_at: tx.stamp,
      expected_s: round(expected, 2),
    };
    return {
      pump,
      ml,
      expected,
      speed: Math.max(1, expected / longest),
      elapsed: 0,
      volume: pump.restore_volume ? volume : null,
      at: tx.stamp,
      by,
      key,
      source,
    };
  }
  /** One tick of a dose; true when it has finished. */
  private advanceDose(tx: Tx, room: Room, dose: Dose): boolean {
    dose.elapsed += (TICK_MS / 1000) * dose.speed;
    if (dose.elapsed >= dose.expected) {
      this.endDose(tx, room, dose, "finished", dose.ml);
      return true;
    }
    // Started this long ago on the page's clock, whatever the clock says now.
    room.status.pumps[dose.pump.id].started_at = new Date(
      tx.now - dose.elapsed * 1000,
    ).toISOString();
    return false;
  }
  /** A dose ends: finished (its mL) or stopped (the time it ran at its flow). What it dosed is drawn
   * from its pump's stock tank under the dose's key, once the change is published. */
  private endDose(tx: Tx, room: Room, dose: Dose, result: string, ml: number) {
    const { pump } = dose;
    tx.set(pump.dosing_entity, pump.dosing_entity.startsWith("binary_sensor.") ? "off" : "Idle");
    if (dose.volume !== null) tx.set(pump.volume_entity, dose.volume);
    room.status.pumps[pump.id] = {
      ...room.status.pumps[pump.id],
      state: "idle",
      target_ml: null,
      started_at: null,
      expected_s: null,
      last: { ml: round(ml), at: tx.stamp, result },
    };
    const tank = pump.stock_tank;
    if (tank && ml > 0)
      tx.later(() =>
        this.stock?.("stock_draw", {
          room_id: `room:${room.prefix}`,
          key: dose.key,
          draws: { [tank]: round(ml) },
          source: dose.source,
        }),
      );
  }
  private remember(
    room: Room,
    kind: "dose" | "batch",
    from: { at: string; by: string; pump?: DosingPump },
    ml: number | Record<string, number>,
    result: string,
    stamp: string,
  ) {
    room.status.history = [
      {
        kind,
        at: from.at,
        ended_at: stamp,
        result,
        doses: typeof ml === "number" ? { [from.pump!.id]: round(ml) } : ml,
        by: from.by,
      },
      ...room.status.history,
    ].slice(0, 20);
  }

  private enterStep(tx: Tx, room: Room, config: DosingConfig, index: number) {
    const batch = room.batch!,
      status = room.status.batch,
      settings = config.batch;
    const record = status.steps.at(-1);
    if (record?.state === "running") record.state = "done";
    if (index >= BATCH_STEPS.length) return this.endBatch(tx, room, "finished");
    const step = BATCH_STEPS[index];
    batch.step = index;
    batch.ms = 0;
    status.step = step;
    status.step_started_at = tx.stamp;
    status.pump = null;
    const pass = (note: string) => {
      status.steps.push({ step, state: "skipped", at: tx.stamp, note });
      this.enterStep(tx, room, config, index + 1);
    };
    const descriptor = tx.get(`sensor.crop_steering_${room.prefix}engine_config`)?.attributes;
    const mapped = (key: string) =>
      typeof descriptor?.[key] === "string" ? (descriptor[key] as string) : null;
    if (step === "fill") {
      if (!settings.fill_valve) return pass("no fill valve");
      if (tx.get(settings.full_entity)?.state === settings.full_state)
        return pass("the float read full");
      batch.level = numeric(tx.get(mapped("water_level_sensor")));
      tx.set(settings.fill_valve, "on");
      tx.set(mapped("tank_fill_entity"), "on");
    }
    if (step === "mix") {
      if (!settings.mix_pump && !settings.mix_valves.length) return pass("no mixing pump");
      for (const valve of settings.mix_valves) tx.set(valve, "on");
      tx.set(settings.mix_pump, "on");
      tx.set(settings.mix_power_sensor, 640);
    }
    if (step === "premix" && settings.premix_min <= 0) return pass("0 min");
    if (step === "postmix" && settings.postmix_min <= 0) return pass("0 min");
    if (step === "dose" && !batch.queue.length) return pass("nothing to dose");
    if (step === "hold") tx.set(settings.hold_entity, "on");
    if (step === "close") for (const id of settings.close_entities) tx.set(id, "off");
    if (step === "finish") {
      tx.set(settings.mix_pump, "off");
      for (const valve of settings.mix_valves) tx.set(valve, "off");
      tx.set(settings.mix_power_sensor, 0);
      tx.set(settings.filled_at_entity, tx.stamp);
      tx.set(settings.hold_entity, "off");
    }
    status.steps.push({ step, state: "running", at: tx.stamp, note: null });
  }
  private advanceBatch(tx: Tx, room: Room) {
    const batch = room.batch!;
    const config = readConfig(tx.get(dosingConfigId(room.prefix))) ?? parseConfig({})!;
    const step = BATCH_STEPS[batch.step];
    const settings = config.batch;
    batch.ms += TICK_MS;
    const next = () => this.enterStep(tx, room, config, batch.step + 1);
    if (step === "dose") {
      if (batch.dose && this.advanceDose(tx, room, batch.dose)) {
        batch.doses[batch.dose.pump.id] = batch.dose.ml;
        batch.dose = null;
      }
      if (!batch.dose) {
        const line = batch.queue.shift();
        if (!line) return next();
        // As the controller does: a pump without a flow is never started.
        if (!((numeric(tx.get(line.pump.flow_entity)) ?? 0) > 0)) {
          const record = room.status.batch.steps.at(-1)!;
          record.state = "failed";
          record.note = `${line.pump.name} is not calibrated`;
          this.stopHardware(tx, room, settings);
          return this.endBatch(tx, room, `stopped: ${line.pump.name} is not calibrated`);
        }
        batch.dose = this.startDose(
          tx,
          room,
          line.pump,
          line.ml,
          BATCH_DOSE_S,
          batch.by,
          `${batch.request}:${line.pump.id}`,
          "batch",
        );
        room.status.batch.pump = line.pump.id;
      }
      return;
    }
    if (step === "premix" || step === "postmix") {
      const minutes = step === "premix" ? settings.premix_min : settings.postmix_min;
      room.status.batch.step_started_at = new Date(tx.now - batch.ms * MIX_SPEED).toISOString();
      if (batch.ms * MIX_SPEED >= minutes * 60_000) next();
      return;
    }
    if (step === "fill") {
      const share = Math.min(1, batch.ms / STEP_MS.fill);
      const descriptor = tx.get(`sensor.crop_steering_${room.prefix}engine_config`)?.attributes;
      const level =
        typeof descriptor?.water_level_sensor === "string" ? descriptor.water_level_sensor : null;
      if (batch.level !== null) tx.set(level, round(batch.level + (98 - batch.level) * share));
      if (share < 1) return;
      tx.set(settings.full_entity, settings.full_state);
      tx.set(settings.fill_valve, "off");
      tx.set(
        typeof descriptor?.tank_fill_entity === "string" ? descriptor.tank_fill_entity : null,
        "off",
      );
      return next();
    }
    if (batch.ms >= STEP_MS[step]) next();
  }
  /** The fill valve closed, mixing off, the hold released. */
  private stopHardware(tx: Tx, room: Room, settings: DosingConfig["batch"]) {
    tx.set(settings.fill_valve, "off");
    const descriptor = tx.get(`sensor.crop_steering_${room.prefix}engine_config`)?.attributes;
    tx.set(
      typeof descriptor?.tank_fill_entity === "string" ? descriptor.tank_fill_entity : null,
      "off",
    );
    tx.set(settings.mix_pump, "off");
    for (const valve of settings.mix_valves) tx.set(valve, "off");
    tx.set(settings.mix_power_sensor, 0);
    tx.set(settings.hold_entity, "off");
  }
  /** Stop: every dosing pump off, the fill valve closed, mixing off, the hold released. */
  private stopBatch(tx: Tx, room: Room, config: DosingConfig) {
    const batch = room.batch!;
    const step = BATCH_STEPS[batch.step];
    if (batch.dose) {
      const { dose } = batch;
      const ml = Math.min(dose.ml, dose.elapsed * (dose.ml / dose.expected));
      this.endDose(tx, room, dose, "stopped", ml);
      batch.doses[dose.pump.id] = round(ml);
    }
    this.stopHardware(tx, room, config.batch);
    const record = room.status.batch.steps.at(-1);
    if (record?.state === "running") {
      record.state = "failed";
      record.note = "stopped";
    }
    this.endBatch(tx, room, `stopped: stop requested during ${STEP_LABELS[step].toLowerCase()}`);
  }
  private endBatch(tx: Tx, room: Room, result: string) {
    const batch = room.batch!;
    room.status.batch = {
      ...room.status.batch,
      step: "idle",
      pump: null,
      step_started_at: null,
      result,
      ended_at: tx.stamp,
    };
    this.remember(room, "batch", batch, batch.doses, result, tx.stamp);
    room.batch = null;
  }
}
