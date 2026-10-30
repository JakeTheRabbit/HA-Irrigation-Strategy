import { describe, expect, test } from "vitest";
import type { OpenAlert } from "./open-alerts";
import type { StatusEntity, SystemStatus } from "./parity-types";
import {
  CARD,
  ageTone,
  healthSentence,
  heartbeatHour,
  placeAlert,
  readbackText,
  rowLabel,
  rowWords,
  seenText,
  statusFromEntities,
} from "./system-status";
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
      "System health 94%: 34 of 35 devices online, controller running, 3 open alerts, each shown below where it happens.",
    );
    expect(healthSentence({ ...status, controller: "stale" }, [alert("CS-102", 2)])).toBe(
      "System health 94%: 34 of 35 devices online, controller not reporting, 1 open alert, shown below where it happens.",
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

  test("only the AI service codes sit on Software; a zone's 7xx sits on its probe or valve", () => {
    for (const code of ["CS-706", "CS-708", "CS-709", "CS-609", "CS-610"])
      expect(placeAlert(alert(code, null), rows), code).toBe(CARD.software);
    // No water at the zone, unusual water, possible bypass: the zone's valve.
    expect(placeAlert(alert("CS-701", 2), rows)).toBe("switch.f1_z2_valve");
    expect(placeAlert(alert("CS-702", 2), rows)).toBe("switch.f1_z2_valve");
    expect(placeAlert(alert("CS-710", 2), rows)).toBe("switch.f1_z2_valve");
    // Probe fault, probe set aside, zone off its arc: the zone's probe (the silent one first).
    expect(placeAlert(alert("CS-703", 2), rows)).toBe("sensor.f1_z2_back_vwc");
    expect(placeAlert(alert("CS-704", 2), rows)).toBe("sensor.f1_z2_back_vwc");
    expect(placeAlert(alert("CS-705", 2), rows)).toBe("sensor.f1_z2_back_vwc");
    // No zone, or another 7xx about the room: the room header.
    expect(placeAlert(alert("CS-701", null), rows)).toBeNull();
    expect(placeAlert(alert("CS-713", null), rows)).toBeNull();
    expect(placeAlert(alert("CS-711", 2), rows)).toBeNull();
    // Lights dimmed is about the room, not the tank.
    expect(placeAlert(alert("CS-810", null), rows)).toBeNull();
    expect(placeAlert(alert("CS-811", null), rows)).toBeNull();
    expect(placeAlert(alert("CS-809", null), rows)).toBe(CARD.tank);
  });

  test("the alert's own entity wins when the backend names a mapped one", () => {
    expect(placeAlert(alert("CS-102", 2, { entityId: "sensor.f1_z2_front_vwc" }), rows)).toBe(
      "sensor.f1_z2_front_vwc",
    );
    // An entity this page does not show: placed by its code.
    expect(placeAlert(alert("CS-102", 2, { entityId: "sensor.other" }), rows)).toBe("sensor.f1_z2_back_vwc");
  });
});

describe("placeAlert moisture codes", () => {
  test("CS-101 and CS-103 sit on a moisture probe, not on a silent EC probe", () => {
    const rows = [
      { entity_id: "sensor.f1_z2_front_vwc", kind: "probe_vwc", zone: 2, ok: true },
      { entity_id: "sensor.f1_z2_front_ec", kind: "probe_ec", zone: 2, ok: false },
    ];
    expect(placeAlert(alert("CS-101", 2), rows)).toBe("sensor.f1_z2_front_vwc");
    expect(placeAlert(alert("CS-103", 2), rows)).toBe("sensor.f1_z2_front_vwc");
    // A silent-probe code still prefers the silent probe of any kind.
    expect(placeAlert(alert("CS-102", 2), rows)).toBe("sensor.f1_z2_front_ec");
  });
});

describe("seenText", () => {
  const TZ = "Pacific/Auckland";
  const row = (kind: StatusEntity["kind"]) => ({
    entity_id: `x.${kind}`,
    kind,
    last_seen: iso(NOW - 4_000),
    last_change: iso(NOW - 600_000),
  });

  test("a flow meter is a sensor: it reads its last report, not a switch time", () => {
    expect(seenText(row("flow_meter"), undefined, TZ, NOW)).toBe("4 s ago");
    expect(seenText(row("probe_vwc"), undefined, TZ, NOW)).toBe("4 s ago");
  });

  test("a valve reads open now or the time it switched", () => {
    expect(seenText(row("valve"), "on", TZ, NOW)).toBe("open now");
    expect(seenText(row("pump"), "on", TZ, NOW)).toBe("running");
    expect(seenText(row("valve"), "off", TZ, NOW)).toMatch(/^switched \d\d:\d\d/);
  });
});

describe("readbackText", () => {
  test("rounds the read-back time to a tenth of a second", () => {
    expect(readbackText(1234)).toBe("1.2 s");
    expect(readbackText(1200)).toBe("1.2 s");
    expect(readbackText(2000)).toBe("2 s");
    expect(readbackText(85)).toBe("85 ms");
  });
});

describe("ageTone", () => {
  test("ageTone ignores age for actuators", () => {
    const old = iso(NOW - 2 * 86_400_000);
    expect(ageTone({ kind: "valve", last_seen: old, ok: true }, NOW)).toBe("ok");
    expect(ageTone({ kind: "pump", last_seen: old, ok: true }, NOW)).toBe("ok");
    expect(ageTone({ kind: "valve", last_seen: iso(NOW), ok: false }, NOW)).toBe("bad");
  });

  test("probes turn orange after 120 s; red only when the backend calls them silent", () => {
    const probe = (ageS: number, ok = true) => ({ kind: "probe_vwc", last_seen: iso(NOW - ageS * 1000), ok });
    expect(ageTone(probe(120), NOW)).toBe("ok");
    expect(ageTone(probe(121), NOW)).toBe("warn");
    // A 10-min-rhythm probe the backend counts online is never red.
    expect(ageTone(probe(25 * 60), NOW)).toBe("warn");
    expect(ageTone(probe(4, false), NOW)).toBe("bad");
    expect(ageTone({ kind: "feed_probe", last_seen: null, ok: true }, NOW)).toBe("warn");
  });
});

describe("rowWords", () => {
  test("screen-reader words follow the backend's ok, not the age alone", () => {
    expect(rowWords("probe_vwc", true, "ok")).toBe("online");
    expect(rowWords("probe_vwc", true, "warn")).toBe("online, last report over 2 min ago");
    expect(rowWords("probe_vwc", false, "bad")).toBe("silent");
    expect(rowWords("valve", false, "bad")).toBe("not available");
  });
});

describe("rowLabel", () => {
  const row = (name: string, extra: Partial<StatusEntity> = {}) => ({ ...entity(1, true), name, ...extra });
  test("the room name leads, never twice, and an entity id is never a name", () => {
    expect(rowLabel(row("Zone 2 back VWC"), "F1")).toBe("F1 Zone 2 back VWC");
    expect(rowLabel(row("F1 Zone 2 back VWC"), "F1")).toBe("F1 Zone 2 back VWC");
    // The backend falls back to the entity id when there is no friendly name.
    expect(rowLabel(row("sensor.probe_1", { zone: 2 }), "F1")).toBe("F1 Zone 2 moisture probe");
    expect(rowLabel(row("switch.f1_pump", { entity_id: "switch.f1_pump", kind: "pump", zone: null }), "F1")).toBe("F1 pump");
  });
});

describe("heartbeatHour", () => {
  const beat = (ageS: number, missed = false, gap_s?: number) => ({
    at: iso(NOW - ageS * 1000),
    missed,
    readback_ms: null,
    ...(gap_s === undefined ? {} : { gap_s }),
  });
  /** A beat every minute from `from` to `to` minutes ago. */
  const minutes = (from: number, to: number) => Array.from({ length: from - to + 1 }, (_, i) => beat((from - i) * 60));
  test("a 25-min outage counts every beat it missed and draws them as one wide bar", () => {
    // Beats at -40 and -39 min, a 1500 s gap marker at -38 min, beats again every minute from -14 min.
    const beats = [beat(40 * 60), beat(39 * 60), beat(38 * 60, true, 1500), ...minutes(14, 1)];
    const hour = heartbeatHour(beats, 60, NOW);
    expect(hour.missed).toBe(24);
    expect(hour.received).toBe(16);
    expect(hour.strip.map((b) => b.weight)).toEqual([1, 1, 24, ...Array(14).fill(1)]);
  });
  test("only the missed beats inside the hour count", () => {
    // The gap began 70 min ago and lasted 25 min: 15 of its 24 missed beats fall in the hour.
    const beats = [beat(70 * 60), beat(69 * 60, true, 1500), ...minutes(45, 1)];
    const hour = heartbeatHour(beats, 60, NOW);
    expect(hour.missed).toBe(15);
    expect(hour.received).toBe(45);
  });
  test("a marker without gap_s is one missed beat", () => {
    expect(heartbeatHour([beat(120), beat(60, true)], 60, NOW).missed).toBe(1);
  });
  test("a controller silent since its last beat counts the beats it has missed since", () => {
    // Beats every minute until 40 min ago, then nothing: the backend has no marker yet.
    const beats = minutes(60, 40);
    const hour = heartbeatHour(beats, 60, NOW);
    expect(hour.received).toBe(21);
    expect(hour.missed).toBe(39);
    expect(hour.strip.at(-1)).toMatchObject({ missed: true, weight: 39 });
    expect(hour.spanMin).toBeNull();
  });
  test("a trailing gap under two intervals is not missed", () => {
    const hour = heartbeatHour([beat(150), beat(90)], 60, NOW);
    expect(hour.missed).toBe(0);
    expect(hour.strip.every((b) => !b.missed)).toBe(true);
  });
  test("a record that starts inside the hour says how many minutes it covers", () => {
    // Home Assistant restarted 12 min ago: the ring holds beats from then only.
    const beats = minutes(12, 1);
    const hour = heartbeatHour(beats, 60, NOW);
    expect(hour.spanMin).toBe(12);
    expect(hour.missed).toBe(0);
    expect(heartbeatHour([], 60, NOW).spanMin).toBe(0);
  });
});

describe("healthSentence per room", () => {
  test("a stale room is named even while another runs", () => {
    const beat = (controller: "running" | "stale" | "absent") => ({ last_beat: null, age_s: null, controller, beats: [], interval_s: 60 });
    const status: SystemStatus = {
      controller: "running",
      addon_version: null,
      pct_online: 100,
      ha_version: null,
      ai: null,
      card_version: null,
      rooms: [
        { room_id: "room:", pct_online: 100, alerts_open: 0, entities: [entity(1, true)], groups: [], heartbeat: beat("running") },
        { room_id: "room:f1_", pct_online: 100, alerts_open: 0, entities: [entity(2, true)], groups: [], heartbeat: beat("stale") },
      ],
    };
    expect(healthSentence(status, [])).toBe(
      "System health 100%: 2 of 2 devices online, controller not reporting in 1 of 2 rooms, no open alerts.",
    );
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
      "System health 66.7%: 4 of 6 devices online, controller running, no open alerts.",
    );
  });

  test("a heartbeat older than 10 min is not running", () => {
    const stale = { ...states, ...put("sensor.crop_steering_ai_heartbeat", "alive", 11 * 60_000) };
    expect(statusFromEntities(stale, [{ id: "room:", name: "F2", prefix: "" }], NOW).controller).toBe("stale");
    const { ["sensor.crop_steering_ai_heartbeat"]: _gone, ...none } = states;
    expect(statusFromEntities(none, [{ id: "room:", name: "F2", prefix: "" }], NOW).controller).toBe("absent");
  });
});
