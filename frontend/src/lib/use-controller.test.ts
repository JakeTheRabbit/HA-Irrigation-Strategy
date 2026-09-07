import { afterEach, describe, expect, it, vi } from "vitest";
import { ControllerStore } from "./use-controller";
import { HaClient } from "./client";
import { createDemo } from "./demo";
import type { States } from "./types";

function browser() {
  const storage = new Map<string, string>();
  vi.stubGlobal("sessionStorage", {
    getItem: (key: string) => storage.get(key) || null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
  });
  vi.stubGlobal("window", {
    location: {
      origin: "http://example.test",
      hostname: "example.test",
      href: "http://example.test/",
      search: "",
    },
    history: { replaceState: vi.fn() },
  });
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("controller lifecycle", () => {
  it("routes named f2 selection, writes and history independently of the default room", async () => {
    browser();
    const states = createDemo();
    states["sensor.crop_steering_f2_engine_config"] = {
      entity_id: "sensor.crop_steering_f2_engine_config",
      state: "ready",
      attributes: { prefix: "f2_", slug: "f2", num_zones: 1 },
    };
    const numberId = "number.crop_steering_f2_zone_1_p1_target_vwc";
    const sensorId = "sensor.crop_steering_f2_vwc_zone_1";
    states[numberId] = {
      entity_id: numberId,
      state: "75",
      attributes: { min: 0, max: 100, step: 1 },
    };
    states[sensorId] = {
      entity_id: sensorId,
      state: "60",
      attributes: {},
      last_updated: new Date().toISOString(),
    };
    vi.spyOn(HaClient.prototype, "states").mockResolvedValue(states);
    const service = vi
      .spyOn(HaClient.prototype, "service")
      .mockImplementation(async (_domain, _action, data) => {
        states[String(data.entity_id)].state = String(data.value);
      });
    vi.spyOn(HaClient.prototype, "state").mockImplementation(async (id) => states[id]);
    const history = vi.spyOn(HaClient.prototype, "history").mockResolvedValue([]);
    const store = new ControllerStore(false);
    await store.connect("http://example.test", "test");
    const namedId = store.getSnapshot().rooms.find((room) => room.prefix === "f2_")!.id;
    store.changeRoom(namedId);
    expect(store.getSnapshot().room.room.prefix).toBe("f2_");
    const result = await store.write([{ entityId: numberId, value: 76 }]);
    expect(result.applied).toEqual([numberId]);
    expect(service).toHaveBeenCalledWith("number", "set_value", { entity_id: numberId, value: 76 });
    expect(states["number.crop_steering_zone_1_p1_target_vwc"].state).toBe("64");
    await store.history([sensorId], 24);
    expect(history).toHaveBeenCalledWith([sensorId], 24, states);
    await expect(store.history(["sensor.crop_steering_vwc_zone_1"], 24)).rejects.toThrow(
      /selected room/,
    );
    store.disconnect();
  });
  it("never falls back to default when an explicitly requested room is missing", async () => {
    browser();
    window.location.search = "?room=missing";
    vi.spyOn(HaClient.prototype, "states").mockResolvedValue(createDemo());
    const store = new ControllerStore(false);
    await store.connect("http://example.test", "test");
    expect(store.getSnapshot().rooms).toHaveLength(2);
    expect(store.getSnapshot().roomId).toBe("");
    expect(store.getSnapshot().room.zones).toEqual([]);
    expect(store.getSnapshot().error).toMatch(/requested room.*unavailable/i);
    await expect(store.history(["sensor.crop_steering_vwc_zone_1"], 24)).rejects.toThrow(
      /selected room/,
    );
    store.changeRoom(store.getSnapshot().rooms[0].id);
    expect(store.getSnapshot().room.room.prefix).toBe("");
    store.disconnect();
  });
  it("does not accept an in-flight response after disconnect", async () => {
    browser();
    const pending = deferred<States>();
    vi.spyOn(HaClient.prototype, "states").mockReturnValue(pending.promise);
    const store = new ControllerStore(false);
    const connect = store.connect("http://example.test", "test");
    store.disconnect();
    pending.resolve(createDemo());
    await connect;
    expect(store.getSnapshot().connection).toBe("offline");
    expect(store.getSnapshot().rooms).toEqual([]);
    expect(store.getSnapshot().lastUpdated).toBeNull();
  });
  it("preserves the previous room snapshot when refresh fails and never falls back to demo", async () => {
    browser();
    const read = vi.spyOn(HaClient.prototype, "states").mockResolvedValue(createDemo());
    const store = new ControllerStore(false);
    await store.connect("http://example.test", "test");
    const previous = store.getSnapshot().states;
    read.mockRejectedValue(new Error("network failed"));
    await store.refresh();
    expect(store.getSnapshot().connection).toBe("offline");
    expect(store.getSnapshot().demo).toBe(false);
    expect(store.getSnapshot().states).toBe(previous);
    store.disconnect();
  });
  it("ignores an old configuration response after reconnect", async () => {
    browser();
    const pending = deferred<States>();
    const next = createDemo();
    vi.spyOn(HaClient.prototype, "states")
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValueOnce(next);
    const store = new ControllerStore(false);
    const first = store.connect("http://old.test", "old");
    await store.connect("http://new.test", "new");
    pending.resolve({});
    await first;
    expect(store.getSnapshot().states).toBe(next);
    expect(store.getSnapshot().connection).toBe("live");
    store.disconnect();
  });
  it("ignores a prior-room refresh after switching rooms", async () => {
    browser();
    const states = createDemo();
    const pending = deferred<States>();
    const read = vi.spyOn(HaClient.prototype, "states").mockResolvedValue(states);
    const store = new ControllerStore(false);
    await store.connect("http://example.test", "test");
    read.mockReturnValueOnce(pending.promise).mockResolvedValue(states);
    const oldRefresh = store.refresh();
    store.changeRoom("room:f1_");
    pending.resolve({});
    await oldRefresh;
    await Promise.resolve();
    expect(store.getSnapshot().roomId).toBe("room:f1_");
    expect(store.getSnapshot().rooms).toHaveLength(2);
    store.disconnect();
  });
  it("keeps local demo writes and history isolated from network and other rooms", async () => {
    browser();
    const fetch = vi.spyOn(globalThis, "fetch");
    const store = new ControllerStore(true);
    const field = store
      .getSnapshot()
      .room.settings.find((s) => s.entityId.endsWith("zone_1_p1_target_vwc"))!;
    expect((await store.write([{ entityId: field.entityId, value: 70 }])).applied).toEqual([
      field.entityId,
    ]);
    const originalOther =
      store.getSnapshot().states["number.crop_steering_f1_zone_1_p1_target_vwc"].state;
    store.changeRoom("room:f1_");
    expect(store.getSnapshot().states["number.crop_steering_f1_zone_1_p1_target_vwc"].state).toBe(
      originalOther,
    );
    const series = await store.history(["sensor.crop_steering_f1_vwc_zone_1"], 24);
    expect(series[0].points.length).toBeGreaterThan(0);
    expect((await store.write([{ entityId: field.entityId, value: 71 }])).failed).toHaveLength(1);
    await expect(store.history(["sensor.crop_steering_vwc_zone_1"], 24)).rejects.toThrow(
      /selected room/,
    );
    await store.connect("http://never.test", "ignored");
    expect(fetch).not.toHaveBeenCalled();
  });
  it("times out a pending HA request even if the implementation ignores abort", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
    const client = new HaClient("http://example.test", "test", undefined, 50);
    const pending = expect(client.states()).rejects.toThrow(/timed out/);
    await vi.advanceTimersByTimeAsync(51);
    await pending;
  });
});
