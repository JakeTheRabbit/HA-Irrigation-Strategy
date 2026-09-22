import { afterEach, describe, expect, it, vi } from "vitest";
import {
  applyEntityUpdate,
  compressedRows,
  liveHistory,
  watchedEntities,
  whileVisible,
  type EntityUpdate,
  type PageEvents,
} from "./live";
import { historySpan, mergeSeries } from "./sensor-context";
import { ControllerStore } from "./use-controller";
import { createDemo } from "./demo";
import type { EntityState, States } from "./types";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const T = 1_790_000_000; // epoch seconds
const iso = (seconds: number) => new Date(seconds * 1000).toISOString();
const entity = (
  entity_id: string,
  state: string,
  attributes: Record<string, unknown> = {},
): EntityState => ({
  entity_id,
  state,
  attributes,
  last_changed: iso(T),
  last_updated: iso(T),
});
const states = (...entities: EntityState[]): States =>
  Object.fromEntries(entities.map((item) => [item.entity_id, item]));

describe("subscribe_entities reducer", () => {
  it("adds entities, taking last_updated from last_changed when Home Assistant leaves it out", () => {
    const next = applyEntityUpdate(
      {},
      {
        a: {
          "sensor.a": { s: "1", a: { unit_of_measurement: "%" }, lc: T },
          "sensor.b": { s: "2", a: {}, lc: T, lu: T + 5 },
        },
      },
    );
    expect(next["sensor.a"]).toEqual({
      entity_id: "sensor.a",
      state: "1",
      attributes: { unit_of_measurement: "%" },
      last_changed: iso(T),
      last_updated: iso(T),
    });
    expect(next["sensor.b"].last_updated).toBe(iso(T + 5));
  });
  it("applies a change without touching what it does not name", () => {
    const before = states(entity("sensor.a", "1", { keep: 1, gone: 2, edit: 3 }));
    const next = applyEntityUpdate(before, {
      c: {
        "sensor.a": { "+": { s: "2", lc: T + 60, a: { edit: 4, added: 5 } }, "-": { a: ["gone"] } },
      },
    });
    expect(next["sensor.a"]).toEqual({
      entity_id: "sensor.a",
      state: "2",
      attributes: { keep: 1, edit: 4, added: 5 },
      last_changed: iso(T + 60),
      last_updated: iso(T + 60),
    });
    // Pure: the snapshot it was given is unchanged.
    expect(before["sensor.a"]).toEqual(entity("sensor.a", "1", { keep: 1, gone: 2, edit: 3 }));
  });
  it("moves only last_updated for an attribute-only change", () => {
    const next = applyEntityUpdate(states(entity("sensor.beat", "healthy", { last_beat: "a" })), {
      c: { "sensor.beat": { "+": { lu: T + 60, a: { last_beat: "b" } } } },
    });
    expect(next["sensor.beat"]).toMatchObject({
      state: "healthy",
      attributes: { last_beat: "b" },
      last_changed: iso(T),
      last_updated: iso(T + 60),
    });
  });
  it("removes entities, ignores changes to unknown ones, and returns the same object for no-ops", () => {
    const before = states(entity("sensor.a", "1"), entity("sensor.b", "2"));
    expect(Object.keys(applyEntityUpdate(before, { r: ["sensor.a"] }))).toEqual(["sensor.b"]);
    const update: EntityUpdate = { c: { "sensor.unknown": { "+": { s: "9" } } }, r: ["sensor.x"] };
    expect(applyEntityUpdate(before, update)).toBe(before);
  });
});

describe("watched entities", () => {
  const home = () =>
    states(
      entity("sensor.crop_steering_engine_config", "ready", {
        prefix: "",
        num_zones: 2,
        enable_flag: "input_boolean.f2_control_enabled",
        pump: "switch.pump",
        valves: { 1: "switch.valve_1", 2: "switch.valve_2" },
        water_level_sensor: "sensor.tank_level",
        zone_names: { 1: "Front" },
        feed_ec_sensor: "sensor.not_created_yet",
      }),
      entity("sensor.crop_steering_f1_engine_config", "ready", { prefix: "f1_", num_zones: 1 }),
      entity("sensor.crop_steering_f1_ai_heartbeat", "healthy", {
        enable_flag: "switch.custom_flag",
      }),
      entity("number.crop_steering_zone_1_p1_target_vwc", "60"),
      ...[
        "input_boolean.f2_control_enabled",
        "switch.pump",
        "switch.valve_1",
        "switch.valve_2",
        "sensor.tank_level",
        "switch.custom_flag",
        "light.kitchen",
        "sensor.outdoor_temperature",
      ].map((id) => entity(id, "on")),
    );
  it("covers the crop-steering entities and what the rooms point at, and nothing else", () => {
    const ids = watchedEntities(home());
    for (const id of [
      "sensor.crop_steering_engine_config",
      "number.crop_steering_zone_1_p1_target_vwc",
      "input_boolean.f2_control_enabled",
      "switch.pump",
      "switch.valve_2",
      "sensor.tank_level",
      "switch.custom_flag",
    ])
      expect(ids).toContain(id);
    for (const id of ["light.kitchen", "sensor.outdoor_temperature", "sensor.not_created_yet"])
      expect(ids).not.toContain(id);
    expect(ids.every((id) => /^[a-z_]+\.[a-z0-9_]+$/.test(id))).toBe(true);
  });
  it("includes the controller's sensors before the controller has posted them", () => {
    // After a Home Assistant restart with the controller stopped, these do not exist yet.
    const ids = watchedEntities(home());
    for (const id of [
      "sensor.crop_steering_ai_heartbeat",
      "sensor.crop_steering_current_decision",
      "sensor.crop_steering_zone_2_phase",
      "sensor.crop_steering_zone_2_status",
      "sensor.crop_steering_f1_ai_heartbeat",
      "sensor.crop_steering_f1_zone_1_last_irrigation_app",
    ])
      expect(ids).toContain(id);
    expect(ids).not.toContain("sensor.crop_steering_f1_zone_2_phase");
  });
  it("is empty without crop-steering entities, so nothing subscribes to all of Home Assistant", () => {
    expect(watchedEntities(states(entity("light.kitchen", "on")))).toEqual([]);
  });
});

describe("standalone polling pauses while the page is hidden", () => {
  function page() {
    const handlers = new Map<string, () => void>();
    const events: PageEvents & { hide: boolean; fire(event: string): void; count(): number } = {
      hide: false,
      hidden: () => events.hide,
      on(event, handler) {
        handlers.set(event, handler);
        return () => handlers.delete(event);
      },
      fire: (event) => handlers.get(event)?.(),
      count: () => handlers.size,
    };
    return events;
  }
  it("polls on schedule only while visible and at once when shown again", () => {
    vi.useFakeTimers();
    const run = vi.fn();
    const events = page();
    const stop = whileVisible(run, 30_000, events);
    vi.advanceTimersByTime(30_000);
    expect(run).toHaveBeenCalledTimes(1);
    events.hide = true;
    vi.advanceTimersByTime(120_000);
    events.fire("visibilitychange");
    expect(run).toHaveBeenCalledTimes(1);
    events.hide = false;
    events.fire("visibilitychange");
    expect(run).toHaveBeenCalledTimes(2);
    // Showing a tab also focuses it, and focus comes and goes: one refresh per ten seconds.
    events.fire("focus");
    vi.advanceTimersByTime(9_000);
    events.fire("focus");
    expect(run).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(1_000);
    events.fire("focus");
    expect(run).toHaveBeenCalledTimes(3);
    stop();
    expect(events.count()).toBe(0);
    vi.advanceTimersByTime(300_000);
    expect(run).toHaveBeenCalledTimes(3);
  });
});

describe("inside Home Assistant", () => {
  const VWC = "sensor.crop_steering_vwc_zone_1";
  const TARGET = "number.crop_steering_zone_1_p1_target_vwc";
  function homeAssistant() {
    const ha: States = { ...createDemo(), "light.kitchen": entity("light.kitchen", "on") };
    const calls: string[] = [];
    const listeners = new Map<string, () => void>();
    let push: ((update: EntityUpdate) => void) | undefined;
    const connection = {
      connected: true,
      subscribeMessage: vi.fn(async (callback: (update: EntityUpdate) => void) => {
        push = callback;
        return vi.fn();
      }),
      sendMessagePromise: vi.fn(
        async (_message: Record<string, unknown>): Promise<unknown> => ({}),
      ),
      addEventListener: (event: string, callback: () => void) => listeners.set(event, callback),
      removeEventListener: (event: string) => listeners.delete(event),
    };
    const session = {
      connection,
      callApi: vi.fn(async (method: string, path: string) => {
        calls.push(`${method} ${path}`);
        if (path === "states") return Object.values(ha);
        if (path.startsWith("history/period/")) return [];
        return ha[decodeURIComponent(path.slice("states/".length))];
      }),
      callService: vi.fn(
        async (_domain: string, _service: string, data: Record<string, unknown>) => {
          const id = String(data.entity_id);
          ha[id] = { ...ha[id], state: String(data.value), last_updated: new Date().toISOString() };
        },
      ),
    };
    const view: Record<string, unknown> = {
      location: {
        origin: "http://ha.test",
        hostname: "ha.test",
        href: "http://ha.test/",
        search: "",
      },
      history: { replaceState: vi.fn() },
      document: {
        querySelector: (selector: string) =>
          selector === "home-assistant" ? { hass: session } : null,
      },
    };
    view.parent = view;
    vi.stubGlobal("window", view);
    const storage = new Map<string, string>();
    vi.stubGlobal("sessionStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    });
    return {
      ha,
      calls,
      connection,
      session,
      push: (update: EntityUpdate) => push!(update),
      fire: (event: string) => listeners.get(event)?.(),
      fullFetches: () => calls.filter((call) => call === "GET states").length,
    };
  }
  async function started() {
    vi.useFakeTimers();
    const home = homeAssistant();
    const store = new ControllerStore(false);
    store.start();
    await vi.advanceTimersByTimeAsync(0);
    return { home, store };
  }
  it("downloads everything once, then subscribes to what it reads", async () => {
    const { home, store } = await started();
    expect(home.fullFetches()).toBe(1);
    expect(store.getSnapshot().connection).toBe("live");
    const [, message] = home.connection.subscribeMessage.mock.calls[0] as unknown as [
      unknown,
      { type: string; entity_ids: string[] },
    ];
    expect(message.type).toBe("subscribe_entities");
    expect(message.entity_ids).toContain(VWC);
    expect(message.entity_ids).toContain("switch.demo_valve_1");
    expect(message.entity_ids).not.toContain("light.kitchen");
    // Ten minutes later: no more full downloads.
    await vi.advanceTimersByTimeAsync(600_000);
    expect(home.fullFetches()).toBe(1);
    store.stop();
  });
  it("shows live changes after one short batch", async () => {
    const { home, store } = await started();
    const before = store.getSnapshot();
    home.push({ c: { [VWC]: { "+": { s: "61.5", lu: Date.now() / 1000 } } } });
    home.push({
      c: { "sensor.crop_steering_ec_zone_1": { "+": { s: "3.3", lu: Date.now() / 1000 } } },
    });
    expect(store.getSnapshot()).toBe(before);
    await vi.advanceTimersByTimeAsync(250);
    expect(store.getSnapshot().room.zones[0].vwc.value).toBe(61.5);
    expect(store.getSnapshot().room.zones[0].ec.value).toBe(3.3);
    store.stop();
    // After stop nothing from the old subscription lands.
    home.push({ c: { [VWC]: { "+": { s: "10" } } } });
    await vi.advanceTimersByTimeAsync(250);
    expect(store.getSnapshot().states[VWC].state).toBe("61.5");
  });
  it("writes by reading back only the written entity", async () => {
    const { home, store } = await started();
    home.calls.length = 0;
    const result = await store.getSnapshot().write([{ entityId: TARGET, value: 65 }]);
    expect(result).toEqual({ applied: [TARGET], failed: [] });
    expect(home.calls).toEqual([`GET states/${TARGET}`, `GET states/${TARGET}`]);
    expect(home.session.callService).toHaveBeenCalledWith("number", "set_value", {
      entity_id: TARGET,
      value: 65,
    });
    expect(store.getSnapshot().states[TARGET].state).toBe("65");
    store.stop();
  });
  it("resynchronises after Home Assistant reconnects, and says when the socket stays down", async () => {
    const { home, store } = await started();
    home.connection.connected = false;
    await vi.advanceTimersByTimeAsync(30_000);
    expect(store.getSnapshot().connection).toBe("live");
    await vi.advanceTimersByTimeAsync(30_000);
    expect(store.getSnapshot().connection).toBe("offline");
    home.connection.connected = true;
    home.fire("ready");
    await vi.advanceTimersByTimeAsync(0);
    expect(home.fullFetches()).toBe(2);
    expect(home.connection.subscribeMessage).toHaveBeenCalledTimes(2);
    expect(store.getSnapshot().connection).toBe("live");
    store.stop();
  });
  it("falls back to polling when Home Assistant refuses the subscription", async () => {
    vi.useFakeTimers();
    const home = homeAssistant();
    home.connection.subscribeMessage.mockRejectedValue(new Error("unknown command"));
    const store = new ControllerStore(false);
    store.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(home.fullFetches()).toBe(1);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(home.fullFetches()).toBe(2);
    store.stop();
  });
  const DECISION = "sensor.crop_steering_current_decision";
  const VALVE = "switch.demo_valve_1";
  it("loads a grow day once over the websocket, attributes only for the decision", async () => {
    const { home, store } = await started();
    const start = Date.now() - 3_600_000,
      end = Date.now();
    home.connection.sendMessagePromise.mockImplementation(async (message) =>
      message.no_attributes
        ? {
            [VALVE]: [
              { s: "off", lu: start / 1000 },
              { s: "on", lu: start / 1000 + 60 },
            ],
          }
        : { [DECISION]: [{ s: "Holding", a: { fired: [], blocked: [] }, lu: start / 1000 }] },
    );
    home.calls.length = 0;
    const rows = await store
      .getSnapshot()
      .timeline({ entityIds: [VALVE, VWC], attributeIds: [DECISION], start, end });
    expect(rows[VALVE]).toEqual([
      { state: "off", time: start },
      { state: "on", time: start + 60_000 },
    ]);
    expect(rows[DECISION]).toEqual([
      { state: "Holding", time: start, attributes: { fired: [], blocked: [] } },
    ]);
    const common = {
      type: "history/history_during_period",
      start_time: new Date(start).toISOString(),
      end_time: new Date(end).toISOString(),
      include_start_time_state: true,
    };
    expect(home.connection.sendMessagePromise.mock.calls.map(([message]) => message)).toEqual([
      {
        ...common,
        entity_ids: [VALVE, VWC],
        significant_changes_only: true,
        minimal_response: true,
        no_attributes: true,
      },
      {
        ...common,
        entity_ids: [DECISION],
        significant_changes_only: false,
        minimal_response: false,
        no_attributes: false,
      },
    ]);
    // Nothing went over REST, and nothing polls afterwards.
    await vi.advanceTimersByTimeAsync(600_000);
    expect(home.calls).toEqual([]);
    expect(home.connection.sendMessagePromise).toHaveBeenCalledTimes(2);
    store.stop();
  });
  it("reads a grow day over REST when the connection cannot send commands", async () => {
    const { home, store } = await started();
    delete (home.connection as { sendMessagePromise?: unknown }).sendMessagePromise;
    home.calls.length = 0;
    const start = Date.now() - 3_600_000;
    await store
      .getSnapshot()
      .timeline({ entityIds: [VALVE], attributeIds: [DECISION], start, end: Date.now() });
    expect(home.calls).toHaveLength(2);
    expect(home.calls[0]).toMatch(/^GET history\/period\/.*minimal_response=&no_attributes=$/);
    expect(home.calls[1]).toMatch(/^GET history\/period\/.*significant_changes_only=0$/);
    store.stop();
  });
  it("keeps a grow day to the selected room and one day", async () => {
    const { store } = await started();
    const start = Date.now() - 3_600_000,
      end = Date.now();
    const timeline = store.getSnapshot().timeline;
    for (const id of ["light.kitchen", "number.crop_steering_f1_zone_1_p1_target_vwc"])
      await expect(timeline({ entityIds: [id], attributeIds: [], start, end })).rejects.toThrow(
        "History is limited to entities in the selected room.",
      );
    await expect(
      timeline({ entityIds: [VALVE], attributeIds: [], start: end - 30 * 3_600_000, end }),
    ).rejects.toThrow("at most one grow-day");
    store.stop();
  });
});

describe("recorder rows over the websocket", () => {
  it("reads the compressed form: lu on every row, lc only where it differs, sorted", () => {
    expect(
      compressedRows(
        {
          "sensor.a": [
            { s: "P1", lu: 1_790_000_060 },
            { s: "P0", lu: 1_790_000_000, lc: 1_789_999_000 },
            { s: "junk" },
          ],
          "sensor.b": "not rows",
        },
        false,
      ),
    ).toEqual({
      "sensor.a": [
        { state: "P0", time: 1_790_000_000_000 },
        { state: "P1", time: 1_790_000_060_000 },
      ],
    });
    expect(() => compressedRows(null, false)).toThrow("invalid history");
  });
  it("gives up on a history request Home Assistant never answers", async () => {
    vi.useFakeTimers();
    const connection = {
      subscribeMessage: vi.fn(),
      sendMessagePromise: () => new Promise<never>(() => {}),
    };
    const request = { entityIds: ["sensor.a"], attributeIds: [], start: 0, end: 1 };
    const pending = liveHistory(connection, request, 30_000);
    const failed = expect(pending).rejects.toThrow("did not return the day's history");
    await vi.advanceTimersByTimeAsync(30_000);
    await failed;
  });
});

describe("recorded history after the first load", () => {
  const point = (minute: number, value: number) => ({
    time: new Date(Date.UTC(2026, 8, 23, 0, minute)).toISOString(),
    value,
  });
  const at = (minute: number) => Date.UTC(2026, 8, 23, 0, minute);
  it("asks for the window once, then only for the minutes since", () => {
    expect(historySpan(72, null, at(0))).toBe(72);
    expect(historySpan(72, at(0), at(1)) * 60).toBeCloseTo(3);
    expect(historySpan(24, at(0), at(0) + 30 * 3_600_000)).toBe(24);
  });
  it("replaces the overlap with the new slice and drops a repeated first reading", () => {
    const held = [
      { entityId: "sensor.v", label: "V", points: [point(1, 50), point(5, 49), point(8, 48)] },
    ];
    // The slice starts at minute 7 with the value held then (49), then records a change.
    const recent = [{ entityId: "sensor.v", label: "V", points: [point(7, 49), point(9, 47)] }];
    expect(mergeSeries(held, recent, at(0))[0].points).toEqual([
      point(1, 50),
      point(5, 49),
      point(9, 47),
    ]);
    // A slice that starts on a different value keeps it; readings before `since` go.
    const moved = [{ entityId: "sensor.v", label: "V", points: [point(7, 46)] }];
    expect(mergeSeries(held, moved, at(2))[0].points).toEqual([point(5, 49), point(7, 46)]);
    // No new readings: the window stays as loaded.
    expect(mergeSeries(held, [], at(0))[0].points).toEqual(held[0].points);
  });
});
