import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildRoom, discoverRooms, leadingNotices, roomStatus } from "./model";
import { ageText, ageTone, parseControllerTime, readHeartbeat } from "./controller-health";
import { createDemo, demoBeat } from "./demo";
import type { EntityState, Notice, States } from "./types";

const NOW = Date.parse("2026-09-23T02:00:00Z");
const ago = (ms: number) => new Date(NOW - ms).toISOString();
const entity = (
  entity_id: string,
  state: string,
  attributes: Record<string, unknown> = {},
  last_updated = ago(30_000),
): EntityState => ({ entity_id, state, attributes, last_updated });
const HEARTBEAT = "sensor.crop_steering_ai_heartbeat";
const DECISION = "sensor.crop_steering_current_decision";
/** A healthy two-zone default room: controller reporting, engine on, probes fresh, both in P2. */
function fixture(extra: EntityState[] = []): States {
  const entries = [
    entity("sensor.crop_steering_engine_config", "ready", {
      prefix: "",
      slug: "",
      num_zones: 2,
      enable_flag: "input_boolean.f2_control_enabled",
    }),
    entity("input_boolean.f2_control_enabled", "on"),
    entity(HEARTBEAT, "healthy", { enable_flag: "input_boolean.f2_control_enabled" }),
    entity("sensor.crop_steering_app_status", "safe_idle"),
    entity(DECISION, "Holding — all zones in band", { fired: [], blocked: [] }),
    ...[1, 2].flatMap((zone) => [
      entity(`sensor.crop_steering_vwc_zone_${zone}`, "55"),
      entity(`sensor.crop_steering_ec_zone_${zone}`, "3"),
      entity(`sensor.crop_steering_zone_${zone}_phase`, "P2", { reason: "in band" }),
      entity(`sensor.crop_steering_zone_${zone}_status`, "Optimal", { reason: "in band" }),
    ]),
    ...extra,
  ];
  return Object.fromEntries(entries.map((item) => [item.entity_id, item]));
}
const view = (states: States) => buildRoom(states, discoverRooms(states)[0]);
const status = (states: States) => roomStatus(states, discoverRooms(states)[0], NOW);

beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(NOW);
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("controller heartbeat", () => {
  it("is healthy while the controller reports, and raises nothing", () => {
    const room = view(fixture());
    expect(room.alerts).toEqual([]);
    expect(room.zones.map((zone) => zone.stale)).toEqual([false, false]);
  });
  it("raises a critical notice and marks zones stale when the heartbeat is missing", () => {
    const states = fixture();
    delete states[HEARTBEAT];
    const room = view(states);
    expect(room.alerts[0]).toMatchObject({
      id: "room:-controller",
      severity: "critical",
      title: "Controller not running",
    });
    expect(room.alerts[0].detail).toMatch(/sensor\.crop_steering_ai_heartbeat is missing/);
    expect(room.zones.map((zone) => zone.stale)).toEqual([true, true]);
    // Only an active room: an off room is empty and raises nothing but stuck hardware.
    states["switch.crop_steering_room_active"] = entity("switch.crop_steering_room_active", "off");
    expect(view(states).alerts).toEqual([]);
    expect(view(states).zones.every((zone) => !zone.stale && zone.status === "Room off")).toBe(
      true,
    );
  });
  it.each([
    ["no time at all", { ...entity(HEARTBEAT, "healthy"), last_updated: undefined }],
    [
      "an unparseable beat",
      { ...entity(HEARTBEAT, "healthy", { last_beat: "yesterday" }), last_updated: "garbage" },
    ],
    ["an unavailable entity", entity(HEARTBEAT, "unavailable")],
  ])("treats a heartbeat with %s as not running", (_, heartbeat) => {
    const room = view(fixture([heartbeat as EntityState]));
    expect(room.alerts[0]).toMatchObject({ severity: "critical", title: "Controller not running" });
    expect(room.zones[0].stale).toBe(true);
  });
  it("raises the notice once the beat is older than ten minutes, the integration's own limit", () => {
    // 25 Sep 2026: three shots in a row held a running controller's loop for 8.2 minutes.
    const fresh = view(fixture([entity(HEARTBEAT, "healthy", {}, ago(9 * 60_000))]));
    expect(fresh.alerts).toEqual([]);
    const stale = view(fixture([entity(HEARTBEAT, "healthy", {}, ago(11 * 60_000))]));
    expect(stale.alerts[0].severity).toBe("critical");
    expect(stale.alerts[0].detail).toMatch(/last reported 11 min ago/);
    expect(stale.zones.every((zone) => zone.stale)).toBe(true);
  });
  describe("while a quiet controller has a zone valve open", () => {
    const VALVE = "switch.zone_1_valve";
    const quiet = (opened: number, extra: EntityState[] = []) =>
      fixture([
        entity("sensor.crop_steering_engine_config", "ready", {
          prefix: "",
          slug: "",
          num_zones: 2,
          enable_flag: "input_boolean.f2_control_enabled",
          valves: { "1": VALVE, "2": "switch.zone_2_valve" },
        }),
        entity(HEARTBEAT, "healthy", { enable_flag: "input_boolean.f2_control_enabled" }, ago(12 * 60_000)),
        { ...entity(VALVE, "on", {}, ago(opened)), last_changed: ago(opened) },
        entity("switch.zone_2_valve", "off"),
        ...extra,
      ]);
    it("says a shot is running, not that the controller is not running", () => {
      const states = quiet(3 * 60_000);
      expect(view(states).alerts).toEqual([
        expect.objectContaining({ severity: "info", title: "Watering" }),
      ]);
      expect(view(states).alerts[0].detail).toMatch(/^Zone 1's valve is open: .*12 min ago/);
      expect(status(states)).toMatchObject({ tone: "watering", text: "Watering" });
    });
    it("calls a valve open longer than the room's maximum shot what it is: not a shot", () => {
      // The controller's fallback cap is 900 s: a controller that stopped mid-shot left it open.
      const states = quiet(16 * 60_000);
      expect(view(states).alerts[0]).toMatchObject({
        severity: "critical",
        title: "Controller not running",
      });
      expect(status(states)).toMatchObject({ tone: "stale", text: "Data 12 min old" });
      // The room's own cap decides, when it has one.
      const longer = quiet(16 * 60_000, [entity("number.crop_steering_max_shot_duration", "1800")]);
      expect(view(longer).alerts[0].title).toBe("Watering");
    });
    it("reads a valve that is closed, or a controller that is fresh, as nothing special", () => {
      const closed = quiet(3 * 60_000, [entity(VALVE, "off")]);
      expect(view(closed).alerts[0].title).toBe("Controller not running");
      const fresh = quiet(3 * 60_000, [entity(HEARTBEAT, "healthy", {}, ago(60_000))]);
      expect(view(fresh).alerts).toEqual([]);
    });
  });
  it("falls back to the controller's naive local last_beat when Home Assistant gives no time", () => {
    const local = (ms: number) => {
      const at = new Date(NOW - ms);
      const pad = (value: number) => String(value).padStart(2, "0");
      return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}.123456`;
    };
    const beat = (ms: number) =>
      readHeartbeat(
        { ...entity(HEARTBEAT, "healthy", { last_beat: local(ms) }), last_updated: undefined },
        NOW,
      );
    expect(beat(60_000)).toMatchObject({ health: "fresh", at: NOW - 60_000 + 123 });
    expect(beat(11 * 60_000).health).toBe("stale");
    // Home Assistant's own update time wins: it is UTC, so a browser in another zone agrees.
    expect(
      readHeartbeat(entity(HEARTBEAT, "healthy", { last_beat: local(3_600_000) }), NOW).health,
    ).toBe("fresh");
  });
  it("parses naive and offset controller times and rejects anything else", () => {
    expect(parseControllerTime("2026-09-23T14:00:00+12:00")).toBe(NOW);
    expect(parseControllerTime("2026-09-23T02:00:00.5Z")).toBe(NOW + 500);
    expect(parseControllerTime("2026-09-23T14:00:00")).toBe(
      new Date(2026, 8, 23, 14, 0, 0).getTime(),
    );
    for (const value of [undefined, 42, "", "14:00", "2026-09-23 14:00:00", "not a date"])
      expect(parseControllerTime(value)).toBeNull();
  });
  it("colours data age amber after two minutes and red after ten", () => {
    expect(ageTone(119_000)).toBe("fresh");
    expect(ageTone(121_000)).toBe("amber");
    expect(ageTone(601_000)).toBe("red");
    expect(ageTone(null)).toBe("red");
    expect([30_000, 90_000, 14 * 60_000, 3 * 3_600_000, 3 * 86_400_000].map(ageText)).toEqual([
      "<1 min",
      "1 min",
      "14 min",
      "3 h",
      "3 d",
    ]);
  });
});

describe("notices", () => {
  const notice = (id: string, severity: Notice["severity"]): Notice => ({
    id,
    severity,
    title: id,
    detail: "",
  });
  it("orders critical before warning before info, even after an info notice was added first", () => {
    const states = fixture([
      entity("sensor.crop_steering_strategy_plan", "active", {
        enabled: true,
        snapshot_version: 1,
        room_id: "room:",
        updated_at: ago(60_000),
        valid_until: new Date(NOW + 300_000).toISOString(),
        zones: [],
      }),
    ]);
    delete states[HEARTBEAT];
    states["sensor.crop_steering_vwc_zone_2"].state = "unavailable";
    expect(view(states).alerts.map((alert) => [alert.severity, alert.title])).toEqual([
      ["critical", "Controller not running"],
      ["warning", "Zone 2: sensor data unavailable"],
      ["info", "Grow plan controls this room"],
    ]);
  });
  it("never drops a critical notice from the short list", () => {
    const alerts = [
      ...["a", "b", "c", "d"].map((id) => notice(id, "critical")),
      notice("e", "warning"),
      notice("f", "info"),
    ];
    expect(leadingNotices(alerts).map((item) => item.id)).toEqual(["a", "b", "c", "d"]);
    const mixed = [notice("a", "critical"), ...["b", "c", "d"].map((id) => notice(id, "warning"))];
    expect(leadingNotices(mixed).map((item) => item.id)).toEqual(["a", "b", "c"]);
  });
  it("collapses zones with the identical problem into one room notice", () => {
    const states = fixture([
      entity("sensor.crop_steering_engine_config", "ready", {
        prefix: "",
        slug: "",
        num_zones: 3,
        enable_flag: "input_boolean.f2_control_enabled",
      }),
    ]);
    // Zone 3 has no probes at all; zones 1 and 2 lose theirs.
    for (const zone of [1, 2])
      for (const metric of ["vwc", "ec"])
        delete states[`sensor.crop_steering_${metric}_zone_${zone}`];
    const room = view(states);
    expect(room.alerts).toHaveLength(1);
    expect(room.alerts[0]).toMatchObject({
      id: "zones-1-2-3-sensors",
      title: "Zone 1, Zone 2 and Zone 3: sensor data unavailable",
      severity: "warning",
    });
    expect(room.alerts[0].zoneId).toBeUndefined();
    // A different problem stays its own notice, still pointing at its zone.
    states["sensor.crop_steering_ec_zone_3"] = entity("sensor.crop_steering_ec_zone_3", "3");
    states["sensor.crop_steering_vwc_zone_3"] = entity("sensor.crop_steering_vwc_zone_3", "55");
    states["sensor.crop_steering_zone_3_status"] = entity(
      "sensor.crop_steering_zone_3_status",
      "Blocked: manual override",
      { reason: "P2 top-up" },
    );
    expect(view(states).alerts.map((alert) => [alert.title, alert.zoneId])).toEqual([
      ["Zone 3 needs attention", 3],
      ["Zone 1 and Zone 2: sensor data unavailable", undefined],
    ]);
  });
});

describe("zone status text", () => {
  const integration = (zone: number, state: string) =>
    entity(`sensor.crop_steering_zone_${zone}_status`, state, { friendly_name: "Zone Status" });
  it("keeps the controller's own label", () => {
    expect(view(fixture()).zones[0].status).toBe("Optimal");
  });
  it("shows the controller's phase-aware label while the integration's is on the sensor", () => {
    const states = fixture([
      integration(1, "Dry - Needs Water"),
      integration(2, "Dry - Needs Water"),
      entity(DECISION, "Z1 P2 top-up", {
        fired: ["Z1 P2 top-up (VWC 51 < 52)"],
        blocked: ["Z2 P2 manual override"],
      }),
    ]);
    expect(view(states).zones.map((zone) => zone.status)).toEqual([
      "Topping up",
      "Blocked: manual override",
    ]);
    states["sensor.crop_steering_zone_1_phase"].attributes.reason = "COPY Z2 (VWC probe dead)";
    states[DECISION].attributes = { fired: [], blocked: [] };
    expect(view(states).zones.map((zone) => zone.status)).toEqual([
      "Probe dead — copying",
      "Optimal",
    ]);
  });
  it("never shows the fixed-threshold 'Dry - Needs Water' during P3, live or not", () => {
    const states = fixture([integration(1, "Dry - Needs Water")]);
    states["sensor.crop_steering_zone_1_phase"].state = "P3";
    expect(view(states).zones[0].status).toBe("Overnight dryback");
    delete states[HEARTBEAT];
    expect(view(states).zones[0]).toMatchObject({ status: "Overnight dryback", stale: true });
  });
  it("shows the last reported status, marked stale, when the controller is not reporting", () => {
    const states = fixture([integration(1, "Dry - Needs Water")]);
    delete states[HEARTBEAT];
    expect(view(states).zones[0]).toMatchObject({ status: "Dry - Needs Water", stale: true });
  });
});

describe("room status line", () => {
  it("says Watering with the shots this cycle fired", () => {
    const states = fixture([
      entity(DECISION, "Z1 P2 top-up", { fired: ["Z1 P2 top-up", "Z2 P2 top-up"], blocked: [] }),
    ]);
    expect(status(states)).toMatchObject({
      tone: "watering",
      text: "Watering",
      detail: "Z1 P2 top-up · Z2 P2 top-up",
      reportedAt: NOW - 30_000,
    });
  });
  it("says Holding with the reason", () => {
    expect(status(fixture())).toMatchObject({
      tone: "holding",
      text: "Holding",
      detail: "all zones in band",
    });
    const blocked = fixture([
      entity(DECISION, "Z2 P2 manual override", { fired: [], blocked: ["Z2 P2 manual override"] }),
    ]);
    expect(status(blocked)).toMatchObject({ tone: "holding", detail: "Z2 P2 manual override" });
  });
  it.each([
    [
      "the engine switch is off",
      [entity("input_boolean.f2_control_enabled", "off")],
      /engine switch is off\. Turn it on/,
    ],
    [
      "setup is waiting to be adopted",
      [
        entity(HEARTBEAT, "healthy", {
          setup_pending:
            "Setup changed; disarm current and requested engine flags and verify hardware OFF",
        }),
      ],
      /^Setup changed; disarm .* verify hardware OFF\. Turn the engine off, wait up to 5 minutes .* then turn it back on\.$/,
    ],
    [
      "the setup is invalid",
      [entity(HEARTBEAT, "healthy", { setup_pending: "Invalid setup descriptor: bad valve" })],
      /^Invalid setup descriptor: bad valve\. Correct the room in Rooms & setup\.$/,
    ],
    [
      "hardware is stuck",
      [entity(HEARTBEAT, "healthy", { hardware_fault: "Valve 2 did not close" })],
      /^Hardware fault: Valve 2 did not close\. Disarm the engine/,
    ],
    [
      "the grow plan is held",
      [entity(HEARTBEAT, "healthy", { strategy_error: "Strategy snapshot is stale" })],
      /^Grow plan hold: Strategy snapshot is stale\./,
    ],
    [
      "a fail-closed gate holds",
      [
        entity("sensor.crop_steering_app_status", "error"),
        entity(DECISION, "Z1 P2 source-water EC dead >30min — holding (fail-closed)", {
          fired: [],
          blocked: ["Z1 P2 source-water EC dead >30min — holding (fail-closed)"],
        }),
      ],
      /fail-closed/,
    ],
  ])("says Not watering and what to do when %s", (_, extra, detail) => {
    const line = status(fixture(extra));
    expect(line).toMatchObject({ tone: "stopped", text: "Not watering" });
    expect(line.detail).toMatch(detail);
  });
  it("says the controller is not running when its heartbeat is missing", () => {
    const states = fixture();
    delete states[HEARTBEAT];
    expect(status(states)).toMatchObject({
      tone: "stopped",
      text: "Not watering",
      detail: "The controller is not running. Start the controller app and check its log.",
      reportedAt: null,
    });
  });
  it("says how old the data is once the controller stops reporting", () => {
    const states = fixture([entity(HEARTBEAT, "healthy", {}, ago(14 * 60_000))]);
    expect(status(states)).toMatchObject({
      tone: "stale",
      text: "Data 14 min old",
      reportedAt: NOW - 14 * 60_000,
    });
  });
  it("says Room off for a room with nothing growing", () => {
    const states = fixture([entity("switch.crop_steering_room_active", "off")]);
    expect(status(states)).toMatchObject({ tone: "off", text: "Room off" });
  });
  it("shows the demo controller running in both rooms, and keeps it running", () => {
    const later = NOW + 30 * 60_000;
    const states = demoBeat(createDemo(NOW), later);
    const [f2, f1] = discoverRooms(states).map((room) => roomStatus(states, room, later));
    expect([f2.text, f1.text]).toEqual(["Watering", "Holding"]);
    vi.spyOn(Date, "now").mockReturnValue(later);
    for (const room of discoverRooms(states))
      expect(buildRoom(states, room).alerts.map((alert) => alert.title)).not.toContain(
        "Controller not running",
      );
  });
});
