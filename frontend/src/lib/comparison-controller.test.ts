import { readFileSync } from "node:fs";
import { afterEach, expect, it, vi } from "vitest";
import { RunDemo } from "./comparison-demo";
import { createDemo } from "./demo";
import { HaClient } from "./client";
import { ControllerStore } from "./use-controller";
import { buildRoom, discoverRooms } from "./model";
import { buildSetpointPreview } from "./setpoint-preview";
import type { RunsDocument } from "./comparison-types";
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
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("starts each room with no fabricated runs and captures actual demo targets/lights/plants", () => {
  const states = createDemo(),
    demo = new RunDemo(() => states);
  for (const room of discoverRooms(states)) {
    expect(demo.call("runs_get", { room_id: room.id }).runs).toEqual([]);
    const result = demo.call("runs_save", {
      room_id: room.id,
      expected_revision: 0,
      record: { name: "Real registration", start_date: "2026-05-01", end_date: "2026-08-01" },
    });
    const view = buildRoom(states, room),
      preview = buildSetpointPreview(view, states, view.zones[0].id, {});
    expect(result.runs[0].lights).toEqual({
      on: preview.draft.lightsOn,
      off: preview.draft.lightsOff,
    });
    const backend = readFileSync(
      new URL("../../../custom_components/crop_steering/strategy_model.py", import.meta.url),
      "utf8",
    );
    const schema = backend.match(
      /REQUIRED_PARAMETERS = \(([\s\S]*?)\)\r?\nPARAMETERS = REQUIRED_PARAMETERS \+ \(([\s\S]*?)\)/,
    )!;
    const allowed = new Set(
      [...`${schema[1]} ${schema[2]}`.matchAll(/"([a-z0-9_]+)"/g)].map((match) => match[1]),
    );
    const parameters = result.runs[0].zones[0].parameters;
    expect(parameters).toEqual(
      Object.fromEntries(
        Object.entries(preview.draft.parameters).filter(([key]) => allowed.has(key)),
      ),
    );
    for (const key of [
      "plant_count",
      "substrate_volume",
      "drippers_per_plant",
      "dripper_flow_rate",
      "max_shot_duration",
    ])
      expect(parameters).not.toHaveProperty(key);
    const invalid = structuredClone(result.runs);
    invalid[0].zones[0].parameters.plant_count = 36;
    expect(() =>
      demo.call("runs_import", { room_id: room.id, expected_revision: 1, runs: invalid }),
    ).toThrow(/Invalid run zone reference/);
    const imported = demo.call("runs_import", {
      room_id: room.id,
      expected_revision: 1,
      runs: result.runs,
    });
    expect(imported.runs).toEqual(result.runs);
    expect(result.runs[0].zones[0].plant_count).toBe(preview.fields.plant_count.value);
    expect(result.runs[0].zones[0].parameters.p1_initial_shot_size).toBeGreaterThan(0);
  }
});
it("authorizes archived registered sensors, rejects other rooms and cancels on room change", async () => {
  browser();
  const states = createDemo();
  vi.spyOn(HaClient.prototype, "states").mockResolvedValue(states);
  const historical = "sensor.crop_steering_vwc_zone_23",
    roomId = discoverRooms(states)[0].id;
  const doc = {
    schema_version: 1,
    room_id: roomId,
    revision: 1,
    time_zone: "UTC",
    runs: [
      {
        id: "old",
        room_id: roomId,
        archived: true,
        zones: [{ zone_id: 23, vwc_sensor: historical, ec_sensor: null }],
      },
    ],
  } as RunsDocument;
  const operator = vi.spyOn(HaClient.prototype, "operator").mockResolvedValue(doc);
  let capturedSignal: AbortSignal | undefined;
  let finish!: (value: unknown) => void;
  const history = vi.spyOn(HaClient.prototype, "historyWindow").mockImplementation((args) => {
    capturedSignal = args.signal;
    return new Promise((resolve) => {
      finish = resolve as typeof finish;
    });
  });
  const store = new ControllerStore(false);
  await store.connect("http://example.test", "test");
  store.changeRoom(roomId);
  const args = {
    entityIds: [historical],
    start: "2026-08-01T00:00:00Z",
    end: "2026-08-02T00:00:00Z",
    timeZone: "UTC",
  };
  await store.operator("runs_get");
  const pending = store.historyWindow(args);
  const outcome = expect(pending).rejects.toThrow(/cancelled/);
  expect(operator).toHaveBeenCalledWith("runs_get", { room_id: roomId });
  expect(history).toHaveBeenCalledTimes(1);
  store.changeRoom(store.getSnapshot().rooms.find((room) => room.id !== roomId)!.id);
  expect(capturedSignal?.aborted).toBe(true);
  finish({ start: args.start, end: args.end, series: [], warnings: [] });
  await outcome;
  // A forged response from the previous room never extends the new room's whitelist.
  await expect(store.historyWindow(args)).rejects.toThrow(/room-scoped/);
  expect(history).toHaveBeenCalledTimes(1);
  store.disconnect();
});
it("metadata operations never call a hardware service or refresh entity states", async () => {
  browser();
  const states = createDemo();
  const getStates = vi.spyOn(HaClient.prototype, "states").mockResolvedValue(states);
  const store = new ControllerStore(false);
  await store.connect("http://example.test", "test");
  const roomId = store.getSnapshot().roomId;
  const doc = {
    schema_version: 1,
    room_id: roomId,
    revision: 1,
    time_zone: "UTC",
    runs: [],
    error: null,
    max_runs: 100,
  } as RunsDocument;
  vi.spyOn(HaClient.prototype, "operator").mockResolvedValue(doc);
  const hardware = vi.spyOn(HaClient.prototype, "service");
  getStates.mockClear();
  await store.operator("runs_save", {
    record: { name: "A", start_date: "2026-08-01", end_date: null },
    expected_revision: 0,
    room_id: "room:forged_",
  });
  expect(HaClient.prototype.operator).toHaveBeenCalledWith(
    "runs_save",
    expect.objectContaining({ room_id: roomId }),
  );
  expect(hardware).not.toHaveBeenCalled();
  expect(getStates).not.toHaveBeenCalled();
  store.disconnect();
});
