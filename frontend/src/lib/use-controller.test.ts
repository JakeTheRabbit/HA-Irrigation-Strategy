import { afterEach, describe, expect, it, vi } from "vitest";
import { ControllerStore, inLitres } from "./use-controller";
import { HaClient, haTimeZone } from "./client";
import { viewerTimeZone } from "./comparison";
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
    expect(states["number.crop_steering_zone_1_p1_target_vwc"].state).toBe("70");
    await store.history([sensorId], 24);
    expect(history).toHaveBeenCalledWith([sensorId], 24, states, expect.any(AbortSignal));
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
    store.changeRoom("room:room_b_");
    pending.resolve({});
    await oldRefresh;
    await Promise.resolve();
    expect(store.getSnapshot().roomId).toBe("room:room_b_");
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
      store.getSnapshot().states["number.crop_steering_room_b_zone_1_p1_target_vwc"].state;
    store.changeRoom("room:room_b_");
    expect(
      store.getSnapshot().states["number.crop_steering_room_b_zone_1_p1_target_vwc"].state,
    ).toBe(originalOther);
    const series = await store.history(["sensor.crop_steering_room_b_vwc_zone_1"], 24);
    expect(series[0].points.length).toBeGreaterThan(0);
    expect((await store.write([{ entityId: field.entityId, value: 71 }])).failed).toHaveLength(1);
    await expect(store.history(["sensor.crop_steering_vwc_zone_1"], 24)).rejects.toThrow(
      /selected room/,
    );
    await store.connect("http://never.test", "ignored");
    expect(fetch).not.toHaveBeenCalled();
  });
  it("reads the room's own tank probes for up to a month, and no other room's", async () => {
    browser();
    const store = new ControllerStore(true);
    const [ec, ph] = await store.history(["sensor.demo_tank_ec", "sensor.demo_tank_ph"], 720);
    expect(ec.points.length).toBeGreaterThan(700);
    expect(ph.points.at(-1)!.value).toBeCloseTo(5.66, 2);
    await expect(store.history(["sensor.demo_room_b_tank_ec"], 24)).rejects.toThrow(
      /selected room/,
    );
    await expect(store.history(["sensor.demo_tank_ec"], 721)).rejects.toThrow(/720 hours/);
    store.changeRoom("room:room_b_");
    expect(
      (await store.history(["sensor.demo_room_b_tank_ph"], 24))[0].points.length,
    ).toBeGreaterThan(0);
  });
  it("reads a long history one day per request and joins the days in order", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.parse("2026-09-24T12:00:00Z"));
    const urls: URL[] = [],
      answered: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input));
      urls.push(url);
      const from = decodeURIComponent(url.pathname.split("/").pop()!);
      // The oldest day answers last, so the days arrive out of order.
      await new Promise((done) => setTimeout(done, (3 - urls.length) * 15));
      answered.push(from);
      // Each day starts with the state then in force; an unavailable row is no reading.
      const rows = [
        { entity_id: "sensor.tank_ec", state: "3.1", last_changed: from },
        { state: "unavailable", last_changed: from },
      ];
      return new Response(JSON.stringify([rows]), { status: 200 });
    });
    const client = new HaClient("http://example.test", "test");
    const [series] = await client.history(["sensor.tank_ec"], 72, {});
    expect(urls).toHaveLength(3);
    expect(answered).not.toEqual([...answered].sort());
    const spans = urls.map((url) => [
      Date.parse(decodeURIComponent(url.pathname.split("/").pop()!)),
      Date.parse(url.searchParams.get("end_time")!),
    ]);
    expect(spans.every(([from, to]) => to - from === 86_400_000)).toBe(true);
    expect(series.points.map((point) => Date.parse(point.time))).toEqual(
      spans.map(([from]) => from).sort((a, b) => a - b),
    );
    await expect(client.history(["sensor.tank_ec"], 721, {})).rejects.toThrow(/720 hours/);
  });
  it("stops asking for more days once one request fails or the read is cancelled", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async () => new Response("{}", { status: 500 }));
    const client = new HaClient("http://example.test", "test");
    await expect(client.history(["sensor.tank_ec"], 720, {})).rejects.toThrow(/\(500\)/);
    expect(fetch.mock.calls.length).toBeLessThanOrEqual(2);
    fetch.mockClear();
    const abort = new AbortController();
    fetch.mockImplementation(async () => {
      abort.abort(); // cancelled while the first day is in flight
      return new Response("[]", { status: 200 });
    });
    await expect(client.history(["sensor.tank_ec"], 720, {}, abort.signal)).rejects.toThrow(
      /cancelled/,
    );
    expect(fetch.mock.calls.length).toBeLessThanOrEqual(2);
  });
  it("ends a long history read when its caller or the room lets go of it", async () => {
    browser();
    vi.spyOn(HaClient.prototype, "states").mockResolvedValue(createDemo());
    const seen: AbortSignal[] = [];
    vi.spyOn(HaClient.prototype, "history").mockImplementation(
      (_ids, _hours, _states, signal) =>
        new Promise((_, reject) => {
          seen.push(signal!);
          signal!.addEventListener("abort", () => reject(new Error("History request cancelled.")));
        }),
    );
    const store = new ControllerStore(false);
    await store.connect("http://example.test", "test");
    const first = store.history(["sensor.demo_tank_ec"], 720);
    store.changeRoom("room:room_b_");
    await expect(first).rejects.toThrow(/cancelled/);
    const caller = new AbortController();
    const second = store.history(["sensor.demo_room_b_tank_ec"], 720, caller.signal);
    caller.abort();
    await expect(second).rejects.toThrow(/cancelled/);
    expect(seen.map((signal) => signal.aborted)).toEqual([true, true]);
    store.disconnect();
  });
  it("times out a pending HA request even if the implementation ignores abort", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
    const client = new HaClient("http://example.test", "test", undefined, 50);
    const pending = expect(client.states()).rejects.toThrow(/timed out/);
    await vi.advanceTimersByTimeAsync(51);
    await pending;
  });
  it("reads a standalone grow day in requests short enough for any URL limit", async () => {
    const urls: URL[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = new URL(String(input));
      urls.push(url);
      const [first] = (url.searchParams.get("filter_entity_id") ?? "").split(",");
      // One entity per request answers; a minimal response leaves later rows without their id.
      const rows = [
        {
          entity_id: first,
          state: "on",
          attributes: { a: 1 },
          last_changed: "2026-09-23T00:01:00Z",
        },
        { state: "off", last_changed: "2026-09-23T00:00:00Z" },
      ];
      return new Response(JSON.stringify([rows]), { status: 200 });
    });
    const client = new HaClient("http://example.test", "test");
    const ids = Array.from({ length: 45 }, (_, index) => `number.crop_steering_x_${index}`);
    const rows = await client.timeline({
      entityIds: ids,
      attributeIds: ["sensor.crop_steering_current_decision"],
      start: Date.parse("2026-09-22T22:00:00Z"),
      end: Date.parse("2026-09-23T01:00:00Z"),
    });
    expect(urls.map((url) => url.searchParams.get("filter_entity_id")!.split(",").length)).toEqual([
      40, 5, 1,
    ]);
    expect(
      urls.every((url) => url.pathname === "/api/history/period/2026-09-22T22:00:00.000Z"),
    ).toBe(true);
    expect(urls[0].searchParams.has("no_attributes")).toBe(true);
    expect(urls[2].searchParams.get("significant_changes_only")).toBe("0");
    expect(rows["number.crop_steering_x_0"]).toEqual([
      { state: "off", time: Date.parse("2026-09-23T00:00:00Z") },
      { state: "on", time: Date.parse("2026-09-23T00:01:00Z") },
    ]);
    expect(rows["sensor.crop_steering_current_decision"][1].attributes).toEqual({ a: 1 });
  });
});

describe("Home Assistant's time zone", () => {
  const elsewhere = () =>
    viewerTimeZone() === "Pacific/Auckland" ? "Europe/Berlin" : "Pacific/Auckland";
  it("is read from the Home Assistant page the dashboard runs in", async () => {
    browser();
    const session = {
      callApi: vi.fn(),
      callService: vi.fn(),
      config: { time_zone: elsewhere() },
    };
    vi.stubGlobal("window", {
      ...window,
      document: {
        querySelector: (name: string) => (name === "home-assistant" ? { hass: session } : null),
      },
    });
    vi.spyOn(HaClient.prototype, "states").mockResolvedValue(createDemo());
    const store = new ControllerStore(false);
    await store.connect("http://example.test", "");
    expect(store.getSnapshot().timeZone).toBe(session.config.time_zone);
    expect(session.callApi).not.toHaveBeenCalled();
    expect(haTimeZone({ time_zone: "Nowhere/Unknown" })).toBe(viewerTimeZone());
    expect(haTimeZone({})).toBe(viewerTimeZone());
  });
  it("is asked of Home Assistant once per connection outside it, with the token", async () => {
    browser();
    const zone = elsewhere();
    let configFails = true;
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (new URL(String(input)).pathname !== "/api/config")
        return new Response(JSON.stringify(Object.values(createDemo())), { status: 200 });
      if (configFails) return new Response("{}", { status: 500 });
      return new Response(JSON.stringify({ time_zone: zone }), { status: 200 });
    });
    const asked = () => fetch.mock.calls.filter(([input]) => String(input).endsWith("/api/config"));
    const store = new ControllerStore(false);
    await store.connect("http://example.test", "test");
    await vi.waitFor(() => expect(asked()).toHaveLength(1));
    // Not answered yet: the viewer's own clock, and the next refresh asks again.
    expect(store.getSnapshot().timeZone).toBe(viewerTimeZone());
    configFails = false;
    await store.refresh();
    await vi.waitFor(() => expect(store.getSnapshot().timeZone).toBe(zone));
    expect(asked()).toHaveLength(2);
    expect(asked()[1][1]?.headers).toMatchObject({ Authorization: "Bearer test" });
    await store.refresh();
    expect(asked()).toHaveLength(2);
    store.disconnect();
  });
  it("is asked with the Home Assistant login a page on its own origin inherits", async () => {
    browser();
    const zone = elsewhere();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) =>
        key === "hassTokens" ? JSON.stringify({ access_token: "inherited" }) : null,
    });
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const body =
        new URL(String(input)).pathname === "/api/config"
          ? { time_zone: zone }
          : Object.values(createDemo());
      return new Response(JSON.stringify(body), { status: 200 });
    });
    const store = new ControllerStore(false);
    const stop = store.start();
    await vi.waitFor(() => expect(store.getSnapshot().timeZone).toBe(zone));
    const [, init] = fetch.mock.calls.find(([input]) => String(input).endsWith("/api/config"))!;
    expect(init?.headers).toMatchObject({ Authorization: "Bearer inherited" });
    stop();
  });
});

describe("recorded water in litres", () => {
  const counter = (unit: string) => ({
    entity_id: "x",
    state: "1",
    attributes: unit ? { unit_of_measurement: unit } : {},
  });
  it("scales each water counter by its own unit and never passes gallons off as litres", () => {
    const samples = {
      "sensor.crop_steering_zone_1_daily_water_app": [{ time: 1, value: 10 }],
      "sensor.crop_steering_zone_1_daily_water_usage": [{ time: 1, value: 2 }],
      "sensor.crop_steering_zone_2_daily_water_usage": [{ time: 1, value: 2 }],
      "sensor.crop_steering_zone_1_irrigation_count_app": [{ time: 1, value: 3 }],
    };
    const out = inLitres(samples, {
      "sensor.crop_steering_zone_1_daily_water_app": counter("L"),
      "sensor.crop_steering_zone_1_daily_water_usage": counter("gal"),
      "sensor.crop_steering_zone_2_daily_water_usage": counter("bushels"),
      "sensor.crop_steering_zone_1_irrigation_count_app": counter(""),
    });
    expect(out["sensor.crop_steering_zone_1_daily_water_app"][0].value).toBe(10);
    expect(out["sensor.crop_steering_zone_1_daily_water_usage"][0].value).toBeCloseTo(7.570823568);
    expect(out["sensor.crop_steering_zone_2_daily_water_usage"]).toEqual([]);
    expect(out["sensor.crop_steering_zone_1_irrigation_count_app"][0].value).toBe(3);
  });
});
