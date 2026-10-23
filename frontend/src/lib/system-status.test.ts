import { describe, expect, test } from "vitest";
import type { OpenAlert } from "./open-alerts";
import type { StatusEntity, SystemStatus } from "./parity-types";
import { CARD, ageTone, healthSentence, placeAlert, statusFromEntities } from "./system-status";
import type { States } from "./types";

const NOW = Date.parse("2026-10-23T01:02:11Z");
const iso = (ms: number) => new Date(ms).toISOString();

const entity = (n: number, ok: boolean): StatusEntity => ({
  entity_id: `sensor.probe_${n}`,
  name: `Probe ${n}`,
  kind: "probe_vwc",
  zone: 1,
  last_seen: iso(NOW - 4_000),
  last_change: iso(NOW - 4_000),
  ok,
  uptime_7d_pct: 100,
});

const alert = (code: string, zone: number | null, extra: Partial<OpenAlert> = {}): OpenAlert => ({
  eventId: `e-${code}`,
  roomId: "room:f1_",
  zone,
  code,
  title: code,
  ruleId: null,
  at: NOW,
  ...extra,
});

describe("healthSentence", () => {
  test("healthSentence exact for fixture", () => {
    const rows = Array.from({ length: 35 }, (_, i) => entity(i, i !== 6));
    const status: SystemStatus = {
      controller: "running",
      addon_version: "3.18.0",
      pct_online: 94,
      ha_version: "2026.10.3",
      ai: null,
      card_version: "3180",
      rooms: [
        { room_id: "room:", pct_online: 100, alerts_open: 1, entities: rows.slice(0, 20), groups: [], heartbeat: null as never },
        { room_id: "room:f1_", pct_online: 93, alerts_open: 2, entities: rows.slice(20), groups: [], heartbeat: null as never },
      ],
    };
    expect(healthSentence(status, [alert("CS-102", 2), alert("CS-608", null), alert("CS-706", null)])).toBe(
      "System health 94 %: 34 of 35 devices online, controller running, 3 open alerts, each shown below where it happens.",
    );
    expect(healthSentence({ ...status, controller: "stale" }, [alert("CS-102", 2)])).toBe(
      "System health 94 %: 34 of 35 devices online, controller not reporting, 1 open alert, shown below where it happens.",
    );
    expect(healthSentence({ ...status, controller: "absent", pct_online: null, rooms: [] }, [])).toBe(
      "System health not known: no mapped devices, no controller heartbeat, no open alerts.",
    );
  });
});

describe("placeAlert", () => {
  const rows = [
    { entity_id: "sensor.f1_z2_front_vwc", kind: "probe_vwc", zone: 2, ok: true },
    { entity_id: "sensor.f1_z2_back_vwc", kind: "probe_vwc", zone: 2, ok: false },
    { entity_id: "sensor.f1_z2_front_ec", kind: "probe_ec", zone: 2, ok: true },
    { entity_id: "switch.f1_z2_valve", kind: "valve", zone: 2, ok: true },
    { entity_id: "switch.f1_pump", kind: "pump", zone: null, ok: true },
    { entity_id: "switch.f1_main", kind: "main_line", zone: null, ok: true },
  ];

  test("placeAlert puts CS-102 on the zone probe row", () => {
    // The zone's silent probe, not its first one.
    expect(placeAlert(alert("CS-102", 2), rows)).toBe("sensor.f1_z2_back_vwc");
    // An EC code on the zone's EC probe.
    expect(placeAlert(alert("CS-104", 2), rows)).toBe("sensor.f1_z2_front_ec");
    // A probe code for a zone with no mapped probe sits on the room header.
    expect(placeAlert(alert("CS-102", 3), rows)).toBeNull();
  });

  test("flow codes on the valve, pump and main line; tank, dosing and software on their cards", () => {
    expect(placeAlert(alert("CS-304", 2), rows)).toBe("switch.f1_z2_valve");
    expect(placeAlert(alert("CS-305", 2), rows)).toBe("switch.f1_z2_valve");
    expect(placeAlert(alert("CS-302", null), rows)).toBe("switch.f1_pump");
    expect(placeAlert(alert("CS-303", null), rows)).toBe("switch.f1_main");
    expect(placeAlert(alert("CS-608", null), rows)).toBe(CARD.tank);
    expect(placeAlert(alert("CS-804", null), rows)).toBe(CARD.tank);
    expect(placeAlert(alert("CS-706", null), rows)).toBe(CARD.software);
    expect(placeAlert(alert("CS-602", null), rows)).toBe(CARD.software);
    expect(placeAlert(alert("CS-406", 2), rows)).toBeNull();
    expect(placeAlert(alert("", null, { code: null }), rows)).toBeNull();
  });

  test("the alert's own entity wins when the backend names a mapped one", () => {
    expect(placeAlert(alert("CS-102", 2, { entityId: "sensor.f1_z2_front_vwc" }), rows)).toBe(
      "sensor.f1_z2_front_vwc",
    );
    // An entity this page does not show: placed by its code.
    expect(placeAlert(alert("CS-102", 2, { entityId: "sensor.other" }), rows)).toBe("sensor.f1_z2_back_vwc");
  });
});

describe("ageTone", () => {
  test("ageTone ignores age for actuators", () => {
    const old = iso(NOW - 2 * 86_400_000);
    expect(ageTone({ kind: "valve", last_seen: old, ok: true }, NOW)).toBe("ok");
    expect(ageTone({ kind: "pump", last_seen: old, ok: true }, NOW)).toBe("ok");
    expect(ageTone({ kind: "valve", last_seen: iso(NOW), ok: false }, NOW)).toBe("bad");
  });

  test("probes turn orange after 120 s and red after 20 min", () => {
    const probe = (ageS: number, ok = true) => ({ kind: "probe_vwc", last_seen: iso(NOW - ageS * 1000), ok });
    expect(ageTone(probe(120), NOW)).toBe("ok");
    expect(ageTone(probe(121), NOW)).toBe("warn");
    expect(ageTone(probe(20 * 60), NOW)).toBe("warn");
    expect(ageTone(probe(20 * 60 + 1), NOW)).toBe("bad");
    expect(ageTone(probe(4, false), NOW)).toBe("bad");
    expect(ageTone({ kind: "feed_probe", last_seen: null, ok: true }, NOW)).toBe("bad");
  });
});

describe("statusFromEntities", () => {
  const put = (entity_id: string, state: string, ageMs: number, attributes: Record<string, unknown> = {}) => ({
    [entity_id]: { entity_id, state, attributes, last_updated: iso(NOW - ageMs), last_changed: iso(NOW - ageMs) },
  });
  const states: States = {
    ...put("sensor.crop_steering_engine_config", "ok", 0, {
      prefix: "",
      num_zones: 2,
      valves: { "1": "switch.z1_valve", "2": "switch.z2_valve" },
      pump: "switch.pump",
    }),
    ...put("sensor.crop_steering_vwc_zone_1", "60", 4_000, { used: ["sensor.z1_front", "sensor.z1_back"] }),
    ...put("sensor.crop_steering_vwc_zone_2", "58", 4_000, { used: ["sensor.z2_front"] }),
    ...put("sensor.z1_front", "60.1", 4_000),
    ...put("sensor.z1_back", "59.9", 30 * 60_000),
    ...put("sensor.z2_front", "58", 10_000),
    ...put("switch.z1_valve", "off", 3 * 86_400_000),
    ...put("switch.z2_valve", "unavailable", 0),
    ...put("switch.pump", "off", 86_400_000),
    ...put("sensor.crop_steering_ai_heartbeat", "alive", 30_000, { controller_version: "3.17.1" }),
  };

  test("entity-only fallback counts online from last_updated", () => {
    const status = statusFromEntities(states, [{ id: "room:", name: "F2", prefix: "" }], NOW);
    const room = status.rooms[0];
    const ok = Object.fromEntries(room.entities.map((e) => [e.entity_id, e.ok]));
    // A probe silent 30 min is not online; a valve or pump that has not switched for days is.
    expect(ok).toEqual({
      "sensor.z1_front": true,
      "sensor.z1_back": false,
      "sensor.z2_front": true,
      "switch.z1_valve": true,
      "switch.z2_valve": false,
      "switch.pump": true,
    });
    expect(room.groups.map((g) => g.kind)).toEqual(["probe_vwc", "valve", "pump"]);
    // A switch without a friendly name reads as what it is.
    expect(room.entities.find((e) => e.entity_id === "switch.z1_valve")?.name).toBe("Zone 1 valve");
    expect(room.entities.find((e) => e.entity_id === "switch.pump")?.name).toBe("Pump");
    expect(room.groups[0].entities[1]).toMatchObject({ last_seen: iso(NOW - 30 * 60_000), uptime_7d_pct: null, zone: 1 });
    expect(status.pct_online).toBeCloseTo((4 / 6) * 100, 10);
    expect(status.controller).toBe("running");
    expect(status.addon_version).toBe("3.17.1");
    expect(room.heartbeat.beats).toEqual([]);
    expect(healthSentence(status, [])).toBe(
      "System health 66.7 %: 4 of 6 devices online, controller running, no open alerts.",
    );
  });

  test("a heartbeat older than 10 min is not running", () => {
    const stale = { ...states, ...put("sensor.crop_steering_ai_heartbeat", "alive", 11 * 60_000) };
    expect(statusFromEntities(stale, [{ id: "room:", name: "F2", prefix: "" }], NOW).controller).toBe("stale");
    const { ["sensor.crop_steering_ai_heartbeat"]: _gone, ...none } = states;
    expect(statusFromEntities(none, [{ id: "room:", name: "F2", prefix: "" }], NOW).controller).toBe("absent");
  });
});
