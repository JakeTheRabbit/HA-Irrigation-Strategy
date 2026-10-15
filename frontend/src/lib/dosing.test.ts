import { afterEach, describe, expect, it, vi } from "vitest";
import {
  STATUS_STALE_MS,
  batchSteps,
  batchTime,
  canEdit,
  controllerReach,
  deviceDosing,
  doseDeadline,
  doseProgress,
  dosingConfigId,
  dosingError,
  dosingStatusId,
  hardwareLabel,
  leftWords,
  newPumpId,
  parseConfig,
  pumpDraw,
  pumpStock,
  pumpView,
  readConfig,
  readStatus,
  recipeRows,
  recipeTotals,
  requestStage,
  resultTone,
  setupChanges,
  setupDraft,
  setupErrors,
  setupPayload,
  stockLeft,
  stockSensorId,
  stockState,
  stockTanks,
  type DosingDocument,
  type DosingRequestResult,
  type DosingStatus,
  type PumpRuntime,
  type SetupDraft,
} from "./dosing";
import { DosingDemo } from "./dosing-demo";
import { createDemo } from "./demo";
import { OperatorDemo } from "./operator-demo";
import { StockDemo } from "./stock-demo";
import type { EntityState, States } from "./types";

const NOW = new Date(2026, 8, 28, 16, 0, 0).getTime();
afterEach(() => {
  vi.useRealTimers();
});
const entity = (
  id: string,
  state: string,
  attributes: Record<string, unknown> = {},
): EntityState => ({
  entity_id: id,
  state,
  attributes,
  last_updated: new Date(NOW).toISOString(),
  last_changed: new Date(NOW).toISOString(),
});
const demo = (prefix = "") => {
  const states = createDemo(NOW);
  return {
    states,
    config: readConfig(states[dosingConfigId(prefix)])!,
    status: readStatus(states[dosingStatusId(prefix)])!,
  };
};
const runtime = (change: Partial<PumpRuntime> = {}): PumpRuntime => ({
  state: "idle",
  flow_ml_s: 10,
  target_ml: null,
  started_at: null,
  expected_s: null,
  last: null,
  ...change,
});

describe("reading the configuration and the controller's status", () => {
  it("reads each demo room's pumps, recipe and batch hardware from the integration's sensor", () => {
    const f2 = demo().config;
    expect(f2.revision).toBe(4);
    expect(f2.pumps.map((pump) => pump.name)).toEqual(["Balance", "Bloom", "Core", "Cleanse"]);
    expect(f2.batch.recipe.map((line) => line.ml)).toEqual([300, 1800, 1080, 200]);
    expect(f2.batch).toMatchObject({
      fill_valve: "switch.demo_tank_fill_valve",
      full_entity: "binary_sensor.demo_tank_full",
      mix_valves: ["switch.demo_recirc_valve"],
      premix_min: 2,
      postmix_min: 5,
    });
    const f1 = demo("f1_").config;
    expect(f1.pumps.map((pump) => pump.name)).toEqual([
      "Grow",
      "Cleanse",
      "Balance",
      "Fade",
      "Core",
      "Bloom",
    ]);
    expect(f1.batch.recipe.map((line) => line.ml)).toEqual([1080, 200, 180, 0, 0, 1800]);
    expect(f1.batch.fill_valve).toBeNull();
  });

  it("keeps what it can of garbled attributes and never throws", () => {
    const config = readConfig(
      entity("sensor.crop_steering_dosing_config", "7", {
        pumps: [
          { id: "ok", name: "  Bloom ", flow_entity: "number.flow", max_ml: "900" },
          { id: "ok", name: "Duplicate" },
          { id: "Bad Id!", name: "Refused" },
          "not a pump",
          { id: "bare" },
        ],
        batch: { mix_valves: ["switch.a", 3, "not an id"], recipe: [{ pump: "ok", ml: -5 }, {}] },
        request: { id: "", action: "dose" },
      }),
    )!;
    expect(config.revision).toBe(7);
    expect(config.pumps.map((pump) => [pump.id, pump.name, pump.max_ml])).toEqual([
      ["ok", "Bloom", 900],
      ["bare", "bare", 0],
    ]);
    expect(config.pumps[1]).toMatchObject({ dosing_prefix: "Dosing", restore_volume: true });
    expect(config.batch.mix_valves).toEqual(["switch.a"]);
    expect(config.batch.recipe).toEqual([{ pump: "ok", ml: 0, ml_entity: null }]);
    expect(config.batch).toMatchObject({
      full_state: "on",
      fill_timeout_min: 20,
      fill_valve: null,
    });
    expect(config.request).toBeNull();
    expect(readConfig(entity("sensor.crop_steering_dosing_config", "unavailable"))).toBeNull();
    expect(readConfig(undefined)).toBeNull();
    expect(parseConfig("nothing")).toBeNull();
    expect(parseConfig({})!.pumps).toEqual([]);
  });

  it("reads the controller's report, dropping what it cannot use", () => {
    const status = readStatus(
      entity("sensor.crop_steering_dosing", "weird", {
        pumps: { a: { state: "dosing", target_ml: "25", last: { ml: 10 } }, b: "x" },
        batch: { step: "fill", steps: [{ step: "fill", state: "running" }, { step: "nap" }] },
        history: [{ kind: "dose", doses: { a: 25, b: "x" } }, { kind: "party" }],
      }),
    )!;
    expect(status.state).toBe("unavailable");
    expect(status.pumps.a).toMatchObject({
      state: "dosing",
      target_ml: 25,
      last: { ml: 10, result: "" },
    });
    expect(status.pumps.b.state).toBe("unavailable");
    expect(status.batch.step).toBe("fill");
    expect(status.batch.steps).toEqual([{ step: "fill", state: "running", at: null, note: null }]);
    expect(status.history).toEqual([
      { kind: "dose", at: null, ended_at: null, result: "", doses: { a: 25 }, by: null },
    ]);
    expect(readStatus(undefined)).toBeNull();
  });
});

describe("a pump's card", () => {
  it("is idle, dosing, not calibrated or unavailable, and a running motor always shows", () => {
    const { states, config, status } = demo("f1_");
    const reach = controllerReach(states, "f1_", status, NOW);
    expect(reach.live).toBe(true);
    const view = (id: string, s: States = states, st: DosingStatus | null = status) =>
      pumpView(
        config.pumps.find((pump) => pump.id === id)!,
        st,
        controllerReach(s, "f1_", st, NOW),
        s,
        NOW,
      );
    expect(view("grow").state).toBe("idle");
    expect(view("fade")).toMatchObject({ state: "uncalibrated", flow: 0 });
    expect(view("fade").reason).toMatch(/reads 0 mL\/s/);
    // The pump reports dosing though the controller says nothing of it.
    const pressed = {
      ...states,
      "binary_sensor.demo_f1_doser_grow_dosing": entity(
        "binary_sensor.demo_f1_doser_grow_dosing",
        "on",
      ),
    };
    expect(view("grow", pressed).state).toBe("dosing");
    const offline = {
      ...states,
      "number.demo_f1_doser_core_flow": entity("number.demo_f1_doser_core_flow", "unavailable"),
    };
    expect(view("core", offline)).toMatchObject({ state: "unavailable" });
    expect(view("core", offline).reason).toMatch(/number\.demo_f1_doser_core_flow is unavailable/);
    // No controller report: nothing can dose, so nothing reads idle.
    const stale = { ...status, updated_at: new Date(NOW - STATUS_STALE_MS - 1_000).toISOString() };
    expect(view("grow", states, stale).state).toBe("unavailable");
    const silent = { ...states };
    delete silent["sensor.crop_steering_f1_ai_heartbeat"];
    expect(view("grow", silent, { ...status, updated_at: null }).state).toBe("unavailable");
    expect(view("grow", states, null).reason).toMatch(/update the controller app/);
  });

  it("goes by the dosing report's time, and by the heartbeat only when it has none", () => {
    const { states, status } = demo();
    expect(status.updated_at).toBe(new Date(NOW - 18_000).toISOString());
    const noBeat = { ...states };
    delete noBeat["sensor.crop_steering_ai_heartbeat"];
    // Refreshed at least every 60 s: fresh for three minutes, whatever the heartbeat says.
    expect(controllerReach(noBeat, "", status, NOW).live).toBe(true);
    const at = (ms: number) => ({ ...status, updated_at: new Date(NOW - ms).toISOString() });
    expect(controllerReach(states, "", at(STATUS_STALE_MS), NOW).live).toBe(true);
    expect(controllerReach(states, "", at(STATUS_STALE_MS + 1_000), NOW)).toEqual({
      live: false,
      reason: "The controller has stopped reporting.",
    });
    // A controller from before it: its heartbeat.
    const old = { ...status, updated_at: null };
    expect(controllerReach(states, "", old, NOW).live).toBe(true);
    expect(controllerReach(noBeat, "", old, NOW).reason).toBe("The controller is not running.");
    // Python's naive local isoformat is read too.
    const naive = new Date(NOW - 30_000);
    const local = `${naive.getFullYear()}-${String(naive.getMonth() + 1).padStart(2, "0")}-${String(naive.getDate()).padStart(2, "0")}T${String(naive.getHours()).padStart(2, "0")}:${String(naive.getMinutes()).padStart(2, "0")}:${String(naive.getSeconds()).padStart(2, "0")}.123456`;
    expect(controllerReach(noBeat, "", { ...status, updated_at: local }, NOW).live).toBe(true);
  });

  it("reads a sensor dosing entity by the state it starts with", () => {
    const pump = {
      ...demo().config.pumps[0],
      dosing_entity: "sensor.doser",
      dosing_prefix: "Dosing",
    };
    expect(deviceDosing(pump, { "sensor.doser": entity("sensor.doser", "Dosing 12 mL") })).toBe(
      true,
    );
    expect(deviceDosing(pump, { "sensor.doser": entity("sensor.doser", "Idle") })).toBe(false);
    expect(deviceDosing(pump, { "sensor.doser": entity("sensor.doser", "unknown") })).toBeNull();
  });

  it("shows a dose's progress as elapsed against expected, with the mL so far", () => {
    const started = new Date(NOW - 10_000).toISOString();
    const running = runtime({
      state: "dosing",
      target_ml: 250,
      expected_s: 25,
      started_at: started,
    });
    expect(doseProgress(running, NOW)).toEqual({
      target: 250,
      elapsed: 10,
      expected: 25,
      share: 0.4,
      ml: 100,
      overdue: false,
    });
    // Past its expected time: full, and overdue; the controller cuts it at 1.25 × + 20 s.
    expect(doseProgress(running, NOW + 20_000)).toMatchObject({ share: 1, ml: 250, overdue: true });
    expect(doseDeadline(25)).toBe(51.25);
    // The controller never lets a dose run past 20 minutes and a minute: nor does the page's clock.
    expect(doseDeadline(5000)).toBe(1260);
    // Expected from the flow when the controller leaves it out; nothing without a target.
    expect(doseProgress({ ...running, expected_s: null }, NOW)!.expected).toBe(25);
    expect(doseProgress({ ...running, target_ml: null }, NOW)).toBeNull();
    expect(doseProgress(runtime(), NOW)).toBeNull();
  });

  it("names the pump's device", () => {
    const pump = demo().config.pumps[0];
    expect(hardwareLabel(pump)).toBe("demo_doser_balance");
    expect(hardwareLabel({ ...pump, volume_entity: "number.other" })).toBe(
      "button.demo_doser_balance_start",
    );
  });
});

describe("a pump's stock tank", () => {
  const sensor = (tanks: unknown[]) => ({
    [stockSensorId("")]: entity(stockSensorId(""), "0", { tanks }),
  });
  const tank = { id: "bloom_a", name: "Bloom A", level_l: 5.4, capacity_l: 20, low_l: 4 };

  it("is the tank the pump's stock_tank names, never one of the same name", () => {
    const { config, states } = demo();
    // Bloom is linked to "Bloom A"; the tank called Bloom is not its.
    const pump = { ...config.pumps[1], stock_tank: "bloom_a" };
    const tanks = stockTanks(
      sensor([
        { ...tank, id: "bloom", name: "Bloom", level_l: 18 },
        tank,
        { name: "Bloom", level_l: 9, capacity_l: 20 }, // an integration from before dosing: no id
        { id: "broken", name: "Broken", level_l: "x", capacity_l: 20 },
      ]),
      "",
    );
    expect(tanks.map((item) => item.id)).toEqual(["bloom", "bloom_a"]);
    const rows = recipeRows(config, states);
    expect(pumpStock(pump, tanks, rows, null)).toEqual({
      id: "bloom_a",
      tank,
      state: stockState(tank),
      left: { count: 3, per: "batch" },
    });
    // The same name is not a link: a pump without a stock tank has none.
    expect(pumpStock({ ...pump, stock_tank: null }, tanks, rows, null)).toBeNull();
    expect(pumpStock({ ...pump, stock_tank: "gone" }, tanks, rows, null)).toEqual({
      id: "gone",
      tank: null,
      state: "ok",
      left: null,
    });
  });

  it("lasts its pump's recipe amount per batch, or its last dose while the recipe passes it by", () => {
    const { config, states } = demo("f1_");
    const rows = recipeRows(config, states);
    const last = (ml: number) => ({ ml, at: null, result: "finished" });
    // In the recipe: batches at its amount, whatever it dosed last.
    expect(pumpDraw("bloom", rows, last(60))).toEqual({ ml: 1800, per: "batch" });
    // Core is in the recipe at 0 mL, Fade not calibrated: doses at the last one, else nothing.
    expect(pumpDraw("core", rows, last(40))).toEqual({ ml: 40, per: "dose" });
    expect(pumpDraw("fade", rows, null)).toBeNull();
    expect(pumpDraw("nope", rows, last(0))).toBeNull();
    // Whole batches, rounded as the integration rounds (0.36 L is 3 doses of 120 mL, not 2.99).
    expect(stockLeft(5.4, { ml: 1800, per: "batch" })).toEqual({ count: 3, per: "batch" });
    expect(stockLeft(0.36, { ml: 120, per: "dose" })).toEqual({ count: 3, per: "dose" });
    expect(stockLeft(1.7, { ml: 1800, per: "batch" })).toEqual({ count: 0, per: "batch" });
    expect(stockLeft(5, null)).toBeNull();
    expect(leftWords({ count: 3, per: "batch" })).toBe("about 3 batches left");
    expect(leftWords({ count: 1, per: "batch" })).toBe("about 1 batch left");
    expect(leftWords({ count: 287, per: "dose" })).toBe("about 287 doses left");
    expect(leftWords({ count: 1, per: "dose" })).toBe("about 1 dose left");
    expect(leftWords({ count: 0, per: "batch" })).toBe("less than one batch left");
    expect(leftWords(null)).toBeNull();
  });

  it("follows the Stock tanks page: amber within half again of the low mark, red at or under it", () => {
    expect(stockState({ level_l: 6.1, low_l: 4 })).toBe("ok");
    expect(stockState({ level_l: 6, low_l: 4 })).toBe("low");
    expect(stockState({ level_l: 4.1, low_l: 4 })).toBe("low");
    expect(stockState({ level_l: 4, low_l: 4 })).toBe("very-low");
    expect(stockState({ level_l: 0, low_l: 4 })).toBe("very-low");
    // No low mark: only an empty tank is red.
    expect(stockState({ level_l: 0.1, low_l: 0 })).toBe("ok");
    expect(stockState({ level_l: 0, low_l: 0 })).toBe("very-low");
  });

  it("reads each demo pump's own tank from the demo's stock sensor", () => {
    const { config, states, status } = demo();
    const tanks = stockTanks(states, "");
    expect(tanks.map((item) => item.name)).toEqual(["Balance", "Bloom", "Core", "Cleanse"]);
    const rows = recipeRows(config, states);
    const stock = (id: string, prefix = "") => {
      const room = prefix ? demo(prefix) : { config, states, status };
      const pump = room.config.pumps.find((item) => item.id === id)!;
      return pumpStock(
        pump,
        stockTanks(room.states, prefix),
        recipeRows(room.config, room.states),
        room.status.pumps[id].last,
      );
    };
    expect(config.pumps.map((pump) => pump.stock_tank)).toEqual([
      "balance",
      "bloom",
      "core",
      "cleanse",
    ]);
    expect(rows).toHaveLength(4);
    expect(stock("bloom")).toMatchObject({ tank: { level_l: 5.4 }, left: { count: 3 } });
    expect(stock("core", "f1_")).toMatchObject({ left: { count: 287, per: "dose" } });
    expect(stock("fade", "f1_")).toMatchObject({ tank: { level_l: 10 }, left: null });
    // The demo starts with nothing at or under its low mark: the Today page has nothing to say
    // about stock (a tank getting low is amber on the pages, not an alert).
    expect(
      ["", "f1_"].flatMap((prefix) =>
        stockTanks(demo(prefix).states, prefix).filter((item) => stockState(item) === "very-low"),
      ),
    ).toEqual([]);
  });
});

describe("the batch", () => {
  it("totals the recipe and its expected time, passing by pumps at 0 mL", () => {
    const { states, config } = demo();
    const rows = recipeRows(config, states);
    expect(recipeTotals(rows).ml).toBe(3380);
    expect(recipeTotals(rows).seconds).toBeCloseTo(
      300 / 11.06 + 1800 / 10.52 + 1080 / 10.88 + 200 / 9.74,
    );
    const time = batchTime(config, rows);
    expect(time.seconds).toBeCloseTo(recipeTotals(rows).seconds! + 7 * 60);
    expect(time.fillMax).toBe(20 * 60);
    const f1 = demo("f1_");
    const f1Rows = recipeRows(f1.config, f1.states);
    expect(f1Rows.filter((row) => row.skipped).map((row) => row.name)).toEqual(["Fade", "Core"]);
    expect(recipeTotals(f1Rows)).toMatchObject({ pumps: 4, ml: 3260 });
    expect(batchTime(f1.config, f1Rows).fillMax).toBe(0);
  });

  it("reads an amount entity at batch start, over the fixed amount", () => {
    const { states, config } = demo();
    config.batch.recipe[0].ml_entity = "number.bloom_today";
    const rows = recipeRows(config, {
      ...states,
      "number.bloom_today": entity("number.bloom_today", "320"),
    });
    expect(rows[0]).toMatchObject({ ml: 320, fromEntity: true, fixed: 300, unreadable: false });
    // An amount entity that reads nothing refuses the batch: never the fixed amount instead.
    for (const reading of [undefined, "unavailable", "unknown", ""]) {
      const unread = recipeRows(config, {
        ...states,
        ...(reading === undefined
          ? {}
          : { "number.bloom_today": entity("number.bloom_today", reading) }),
      });
      expect(unread[0]).toMatchObject({ ml: 0, unreadable: true, skipped: false, seconds: null });
      expect(recipeTotals(unread)).toMatchObject({ pumps: 4, ml: null, seconds: null });
    }
    // No entity: the fixed amount.
    config.batch.recipe[0].ml_entity = null;
    expect(recipeRows(config, states)[0]).toMatchObject({ ml: 300, fromEntity: false });
  });

  it("lists the steps to come, passing by what the room does not have", () => {
    const { states, config } = demo("f1_");
    const steps = batchSteps(config, readStatus(states[dosingStatusId("f1_")]), states);
    expect(steps.map((step) => [step.step, step.state])).toEqual([
      ["hold", "waiting"],
      ["close", "waiting"],
      ["fill", "skipped"],
      ["mix", "waiting"],
      ["premix", "waiting"],
      ["dose", "waiting"],
      ["postmix", "waiting"],
      ["finish", "waiting"],
    ]);
    expect(steps[2].detail).toMatch(/no fill valve/);
    expect(steps[5].detail).toBe("4 pumps in order");
  });

  it("follows a running batch as the controller reports it", () => {
    const { states, config, status } = demo();
    status.batch = {
      ...status.batch,
      step: "dose",
      pump: "bloom",
      steps: [
        { step: "hold", state: "done", at: null, note: null },
        { step: "close", state: "done", at: null, note: null },
        { step: "fill", state: "skipped", at: null, note: "the float read full" },
        { step: "mix", state: "done", at: null, note: null },
        { step: "premix", state: "done", at: null, note: null },
        { step: "dose", state: "running", at: null, note: null },
      ],
    };
    // The batch found the float full: now full says nothing of the plan.
    states["binary_sensor.demo_tank_full"] = entity("binary_sensor.demo_tank_full", "on");
    expect(batchSteps(config, null, states)[2]).toMatchObject({
      state: "skipped",
      detail: "Passed by while the float reads full",
    });
    const steps = batchSteps(config, status, states);
    expect(steps[2].detail).toBe("Until the float reads full, 20 min at most");
    expect(steps.map((step) => step.state)).toEqual([
      "done",
      "done",
      "skipped",
      "done",
      "done",
      "running",
      "waiting",
      "waiting",
    ]);
    expect(steps[5].detail).toBe("Dosing Bloom");
    expect(steps[2].note).toBe("the float read full");
  });
});

describe("requests", () => {
  const request = (at: number) => ({
    id: "abc",
    action: "dose" as const,
    pump: "bloom",
    ml: 25,
    at: new Date(at).toISOString(),
    by: "Ben",
  });
  it("wait for the controller, are taken with its word, or expire after two minutes", () => {
    const { config, status } = demo();
    expect(requestStage(config, status, NOW)).toBeNull();
    config.request = request(NOW - 5_000);
    expect(requestStage(config, status, NOW)?.stage).toBe("waiting");
    expect(requestStage(config, status, NOW + 130_000)?.stage).toBe("expired");
    // Pending while less than 120 s old, as the integration counts it: at 120 s it is not.
    expect(requestStage(config, status, NOW - 5_000 + 119_999)?.stage).toBe("waiting");
    expect(requestStage(config, status, NOW - 5_000 + 120_000)?.stage).toBe("expired");
    // A request whose time cannot be read is not pending.
    expect(
      requestStage({ ...config, request: { ...config.request, at: null } }, status, NOW)?.stage,
    ).toBe("expired");
    status.handled = "abc";
    status.handled_result = "too old to act on";
    expect(requestStage(config, status, NOW)).toMatchObject({
      stage: "taken",
      result: "too old to act on",
    });
  });
  it("are sent by whom dosing_get says can edit, else by a Home Assistant administrator", () => {
    const doc = (can_edit?: boolean) =>
      ({
        schema_version: 1,
        room_id: "room:",
        config: null,
        candidates: [],
        can_edit,
        error: null,
      }) as DosingDocument;
    expect(canEdit(doc(true), false)).toBe(true);
    expect(canEdit(doc(false), true)).toBe(false);
    // An integration from before can_edit: what Home Assistant says of the user, unknown allowed.
    expect(canEdit(doc(), false)).toBe(false);
    expect(canEdit(doc(), null)).toBe(true);
    expect(canEdit(null, true)).toBe(true);
  });
  it("say the integration's refusals in words and colour results", () => {
    expect(dosingError("busy")).toMatch(/still waiting/);
    expect(dosingError("busy", true)).toMatch(/Save once/);
    expect(dosingError("revision")).toMatch(/changed elsewhere/);
    expect(dosingError("Bloom is not a pump")).toBe("Bloom is not a pump");
    expect(
      [
        "finished",
        "stopped: stop requested",
        "ran past its time",
        "not confirmed",
        "too old to act on",
        "ended early",
        "finished; input_datetime.tank could not be stamped",
        "stopped; switch.pump does not read off",
        "not confirmed; nothing drawn from its stock tank",
      ].map(resultTone),
    ).toEqual(["on", "warn", "off", "off", "neutral", "off", "warn", "off", "off"]);
  });
});

describe("the dosing setup", () => {
  const draft = (): SetupDraft => setupDraft(demo().config);
  it("accepts the demo's setup, and says what the integration would refuse", () => {
    expect(setupErrors(draft())).toEqual([]);
    const bad = draft();
    bad.pumps[1].name = "balance";
    bad.pumps[2].start_entity = "switch.not_a_button";
    bad.pumps[3].max_ml = 9000;
    bad.batch.full_entity = null;
    bad.batch.premix_min = 45;
    bad.batch.mix_valves = ["switch.demo_doser_core_power"];
    bad.batch.recipe.push({ pump: "balance", ml: 5, ml_entity: null });
    expect(setupErrors(bad)).toEqual([
      "Two pumps are called balance.",
      "Core: map its start.",
      "Cleanse: the largest dose must be between 1 and 5000 mL.",
      "A fill valve needs the float that says the tank is full.",
      "Mixing before dosing must be between 0 and 30 minutes.",
      "switch.demo_doser_core_power is a dosing pump's power switch; it cannot also be batch hardware.",
      "Balance is in the recipe twice.",
    ]);
  });
  it("links each pump to at most one of the room's stock tanks, and one tank to one pump", () => {
    const tanks = ["balance", "bloom", "core", "cleanse"];
    expect(setupErrors(draft(), tanks)).toEqual([]);
    const next = draft();
    next.pumps[2].stock_tank = "bloom";
    next.pumps[3].stock_tank = "gone";
    expect(setupErrors(next, tanks)).toEqual([
      "Bloom and Core are linked to the same stock tank.",
      "Cleanse: its stock tank is not one of this room's.",
    ]);
    // The room's tanks unknown (stock_get not read): only the pairs are checked.
    expect(setupErrors(next)).toEqual(["Bloom and Core are linked to the same stock tank."]);
    next.pumps[2].stock_tank = null;
    next.pumps[3].stock_tank = null;
    expect(setupErrors(next, tanks)).toEqual([]);
    expect(setupPayload(next).pumps.map((pump) => pump.stock_tank)).toEqual([
      "balance",
      "bloom",
      null,
      null,
    ]);
  });
  it("gives a new pump an id from its name, and the recipe follows it", () => {
    const next = draft();
    next.pumps.push({ ...next.pumps[0], key: "new-1", id: null, name: "Bloom!" });
    next.batch.recipe.push({ pump: "new-1", ml: 40, ml_entity: null });
    const payload = setupPayload(next);
    expect(payload.pumps.at(-1)!.id).toBe("bloom_2");
    expect(payload.batch.recipe.at(-1)).toEqual({ pump: "bloom_2", ml: 40, ml_entity: null });
    expect(newPumpId("  ", new Set())).toBe("pump");
    expect(
      newPumpId("A very long nutrient name indeed", new Set(["a_very_long_nutrient_nam"])),
    ).toBe("a_very_long_nutrient_n_2");
  });
  it("lists every change for the review", () => {
    const { config } = demo();
    const next = draft();
    next.pumps[0].max_ml = 1500;
    next.batch.postmix_min = 8;
    next.batch.recipe[1].ml = 1700;
    next.pumps[3].stock_tank = null;
    const tanks = [{ id: "cleanse", name: "Cleanse 5 L" }];
    expect(setupChanges(config, setupPayload(next), tanks)).toEqual([
      { label: "Balance · Largest dose (mL)", before: "2000", after: "1500" },
      { label: "Cleanse · Stock tank", before: "Cleanse 5 L", after: "none" },
      {
        label: "Recipe",
        before: "Balance 300 mL, Bloom 1800 mL, Core 1080 mL, Cleanse 200 mL",
        after: "Balance 300 mL, Bloom 1700 mL, Core 1080 mL, Cleanse 200 mL",
      },
      { label: "Mix after dosing (min)", before: "5", after: "8" },
    ]);
    expect(setupChanges(config, setupPayload(draft()))).toEqual([]);
  });
});

describe("the demo's dosing services and controller", () => {
  function start(prefix = "") {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    let states = createDemo(NOW);
    const stock = new StockDemo(
      () => states,
      (next) => (states = next),
    );
    const dosing = new DosingDemo(
      () => states,
      (next) => (states = next),
      (action, data) => stock.call(action, data),
    );
    const room = `room:${prefix}`;
    return {
      get states() {
        return states;
      },
      put: (entity: EntityState) => (states = { ...states, [entity.entity_id]: entity }),
      status: () => readStatus(states[dosingStatusId(prefix)])!,
      config: () => readConfig(states[dosingConfigId(prefix)])!,
      get: () => dosing.call("dosing_get", { room_id: room }) as DosingDocument,
      request: (data: Record<string, unknown>) =>
        dosing.call("dosing_request", { room_id: room, ...data }) as DosingRequestResult,
      save: (data: Record<string, unknown>) =>
        dosing.call("dosing_save", { room_id: room, ...data }) as DosingDocument,
      stock: () => stock.call("stock_get", { room_id: room }),
      /** A tank's level as the room's stock sensor says. */
      level: (id: string) => stockTanks(states, prefix).find((tank) => tank.id === id)?.level_l,
    };
  }
  it("answers dosing_get with the room's configuration and the entities it can use", () => {
    const demo = start();
    const doc = demo.get();
    expect(doc).toMatchObject({ schema_version: 1, room_id: "room:", can_edit: true, error: null });
    expect(doc.config!.pumps).toHaveLength(4);
    const domains = new Set(doc.candidates.map((candidate) => candidate.domain));
    for (const domain of ["number", "button", "binary_sensor", "switch", "sensor"])
      expect(domains).toContain(domain);
    expect(domains).not.toContain("select");
  });
  it("doses: the request waits, the controller takes it, the pump runs its mL and finishes", () => {
    const demo = start();
    const sent = demo.request({ action: "dose", pump: "balance", ml: 25 });
    expect(sent.error).toBeNull();
    expect(sent.request).toMatchObject({ action: "dose", pump: "balance", ml: 25, by: "Demo" });
    expect(sent.request!.id).toMatch(/^[0-9a-f]{32}$/);
    expect(demo.config().request!.id).toBe(sent.request!.id);
    // A second one is refused while the first waits.
    expect(demo.request({ action: "batch" })).toEqual({ request: null, error: "busy" });
    vi.advanceTimersByTime(1_000);
    expect(demo.status()).toMatchObject({
      state: "dosing",
      handled: sent.request!.id,
      handled_result: "dosing",
    });
    expect(demo.status().pumps.balance).toMatchObject({ state: "dosing", target_ml: 25 });
    expect(demo.states["binary_sensor.demo_doser_balance_dosing"].state).toBe("on");
    expect(demo.states["number.demo_doser_balance_volume"].state).toBe("25");
    vi.advanceTimersByTime(3_000);
    expect(demo.status().state).toBe("idle");
    expect(demo.status().pumps.balance.last).toMatchObject({ ml: 25, result: "finished" });
    expect(demo.status().history[0]).toMatchObject({
      kind: "dose",
      doses: { balance: 25 },
      result: "finished",
    });
    // The firmware's batch recipe is put back in its volume number.
    expect(demo.states["number.demo_doser_balance_volume"].state).toBe("300");
    expect(demo.states["binary_sensor.demo_doser_balance_dosing"].state).toBe("off");
    // What it dosed is drawn from Balance's stock tank, under the request's key, and the stock
    // sensor says so.
    expect(demo.level("balance")).toBe(6.875);
    expect(demo.stock().history[0]).toMatchObject({
      source: "dose",
      key: sent.request!.id,
      draw_ml: { balance: 25 },
    });
    expect(Date.parse(demo.status().updated_at!)).toBeGreaterThan(NOW);
  });
  it("draws a dose stopped part way at the time it ran, and nothing from an unlinked pump", () => {
    const demo = start();
    demo.request({ action: "dose", pump: "bloom", ml: 1800 });
    vi.advanceTimersByTime(3_000);
    expect(demo.status().pumps.bloom.state).toBe("dosing");
    demo.request({ action: "stop" });
    vi.advanceTimersByTime(1_000);
    const last = demo.status().pumps.bloom.last!;
    expect(last.result).toBe("stopped");
    expect(last.ml).toBeGreaterThan(0);
    expect(last.ml).toBeLessThan(1800);
    expect(demo.stock().history[0]).toMatchObject({ source: "dose", draw_ml: { bloom: last.ml } });
    expect(demo.level("bloom")).toBeCloseTo(5.4 - last.ml / 1000, 4);
    // Cleanse unlinked: its dose draws nothing.
    const next = setupDraft(demo.get().config);
    next.pumps[3].stock_tank = null;
    expect(demo.save({ expected_revision: 4, ...setupPayload(next) }).error).toBeNull();
    const before = demo.stock().history.length;
    demo.request({ action: "dose", pump: "cleanse", ml: 10 });
    vi.advanceTimersByTime(5_000);
    expect(demo.status().pumps.cleanse.last).toMatchObject({ ml: 10, result: "finished" });
    expect(demo.stock().history).toHaveLength(before);
    expect(demo.level("cleanse")).toBe(3.9);
  });
  it("refuses a batch whose amount entity reads nothing, before anything moves", () => {
    const demo = start();
    demo.put({
      entity_id: "number.bloom_today",
      state: "unavailable",
      attributes: {},
    });
    const next = setupDraft(demo.get().config);
    next.batch.recipe[1].ml_entity = "number.bloom_today";
    expect(demo.save({ expected_revision: 4, ...setupPayload(next) }).error).toBeNull();
    demo.request({ action: "batch" });
    vi.advanceTimersByTime(1_000);
    expect(demo.status()).toMatchObject({
      state: "idle",
      handled_result: "refused: the recipe amount for Bloom can't be read",
    });
    expect(demo.states["switch.demo_tank_fill_valve"].state).toBe("off");
  });
  it("refuses what the integration refuses", () => {
    const demo = start("f1_");
    expect(demo.request({ action: "dose", pump: "nope", ml: 5 }).error).toMatch(/no pump nope/);
    expect(demo.request({ action: "dose", pump: "grow", ml: 2500 }).error).toMatch(
      /at most 2000 mL/,
    );
    expect(demo.request({ action: "rinse" }).error).toMatch(/dose, batch or stop/);
    // The controller refuses a pump that is not calibrated.
    demo.request({ action: "dose", pump: "fade", ml: 10 });
    vi.advanceTimersByTime(1_000);
    expect(demo.status().handled_result).toBe("refused: Fade is not calibrated");
    expect(demo.status().state).toBe("idle");
  });
  it("makes a batch: fills, mixes, doses the recipe in order and mixes again", () => {
    const demo = start();
    demo.request({ action: "batch" });
    vi.advanceTimersByTime(1_000);
    expect(demo.status().state).toBe("batch");
    vi.advanceTimersByTime(1_500);
    expect(demo.status().batch.step).toBe("fill");
    expect(demo.states["switch.demo_tank_fill_valve"].state).toBe("on");
    vi.advanceTimersByTime(4_500);
    expect(demo.states["binary_sensor.demo_tank_full"].state).toBe("on");
    expect(demo.states["switch.demo_tank_fill_valve"].state).toBe("off");
    expect(demo.states["switch.demo_mix_pump"].state).toBe("on");
    vi.advanceTimersByTime(40_000);
    const status = demo.status();
    expect(status.state).toBe("idle");
    expect(status.batch).toMatchObject({ step: "idle", result: "finished" });
    expect(status.batch.steps.map((step) => [step.step, step.state])).toEqual([
      ["hold", "done"],
      ["close", "done"],
      ["fill", "done"],
      ["mix", "done"],
      ["premix", "done"],
      ["dose", "done"],
      ["postmix", "done"],
      ["finish", "done"],
    ]);
    expect(status.history[0]).toMatchObject({
      kind: "batch",
      result: "finished",
      doses: { balance: 300, bloom: 1800, core: 1080, cleanse: 200 },
    });
    expect(demo.states["switch.demo_mix_pump"].state).toBe("off");
    expect(demo.states["switch.demo_recirc_valve"].state).toBe("off");
    // Each dose drawn from its pump's tank as it finished, one key per dose; Bloom now low.
    const request = demo.config().request!.id;
    expect(
      demo
        .stock()
        .history.slice(0, 4)
        .map((entry) => [entry.source, entry.key, entry.draw_ml]),
    ).toEqual([
      ["batch", `${request}:cleanse`, { cleanse: 200 }],
      ["batch", `${request}:core`, { core: 1080 }],
      ["batch", `${request}:bloom`, { bloom: 1800 }],
      ["batch", `${request}:balance`, { balance: 300 }],
    ]);
    expect(["balance", "bloom", "core", "cleanse"].map(demo.level)).toEqual([6.6, 3.6, 11.82, 3.7]);
    expect(demo.states["sensor.crop_steering_stock_low"].state).toBe("1");
  });
  it("stops a batch where it is, and says in which step", () => {
    const demo = start();
    demo.request({ action: "batch" });
    vi.advanceTimersByTime(3_000);
    expect(demo.status().batch.step).toBe("fill");
    // Stop replaces nothing pending here, and is never refused as busy.
    expect(demo.request({ action: "stop" }).error).toBeNull();
    vi.advanceTimersByTime(1_000);
    const status = demo.status();
    expect(status.batch).toMatchObject({
      step: "idle",
      result: "stopped: stop requested during fill the tank",
    });
    expect(status.batch.steps.at(-1)).toMatchObject({
      step: "fill",
      state: "failed",
      note: "stopped",
    });
    expect(demo.states["switch.demo_tank_fill_valve"].state).toBe("off");
    expect(status.history[0]).toMatchObject({ kind: "batch", result: /^stopped/ });
  });
  it("saves a setup against its revision, and refuses a stale one", () => {
    const demo = start();
    const doc = demo.get();
    const next = setupDraft(doc.config);
    next.batch.postmix_min = 8;
    expect(demo.save({ expected_revision: 3, ...setupPayload(next) }).error).toBe("revision");
    const saved = demo.save({ expected_revision: 4, ...setupPayload(next) });
    expect(saved.error).toBeNull();
    expect(saved.config!.revision).toBe(5);
    expect(demo.config()).toMatchObject({ revision: 5, batch: { postmix_min: 8 } });
    next.pumps[0].flow_entity = "number.no_such_flow";
    expect(demo.save({ expected_revision: 5, ...setupPayload(next) }).error).toMatch(
      /number\.no_such_flow does not exist/,
    );
    // A pump links only to one of the room's stock tanks, and a tank to one pump.
    const linked = setupDraft(demo.get().config);
    linked.pumps[0].stock_tank = "gone";
    expect(demo.save({ expected_revision: 5, ...setupPayload(linked) }).error).toBe(
      "Balance: its stock tank is not one of this room's.",
    );
    linked.pumps[0].stock_tank = "bloom";
    expect(demo.save({ expected_revision: 5, ...setupPayload(linked) }).error).toBe(
      "Balance and Bloom are linked to the same stock tank.",
    );
  });
  it("rewrites the stock sensor when a saved setup links a pump to another tank", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    let states = createDemo(NOW);
    const operator = new OperatorDemo(
      () => states,
      (next) => (states = next),
    );
    const doc = await operator.call<DosingDocument>("dosing_get", { room_id: "room:" });
    const next = setupDraft(doc.config);
    next.pumps[1].stock_tank = null;
    await operator.call("dosing_save", {
      room_id: "room:",
      expected_revision: doc.config!.revision,
      ...setupPayload(next),
    });
    const tanks = states[stockSensorId("")].attributes.tanks as { id: string; pump: string }[];
    expect(tanks.map((tank) => [tank.id, tank.pump])).toEqual([
      ["balance", "balance"],
      ["bloom", null],
      ["core", "core"],
      ["cleanse", "cleanse"],
    ]);
  });
});
