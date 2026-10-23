import type { StatusBeat, StatusEntity, SystemStatus } from "../parity-types";

/** system_status_get for the demo (`?demo=1`), over the demo's own entities: Room A plays F2, Room B
 * plays F1. As in parity-demo/status.ts, Room B zone 2's back probes stopped reporting 3 h ago (the
 * open CS-102), so they are silent and their week's uptime is short. Room B's controller missed one
 * beat 50 min ago. */
const iso = (ms: number) => new Date(ms).toISOString();

export function demoSystemStatus(now: number): SystemStatus {
  const rooms = [
    { room_id: "room:", ids: "demo_", alerts: 0, readback: 1200 },
    { room_id: "room:room_b_", ids: "demo_room_b_", alerts: 1, readback: 1400 },
  ].map(({ room_id, ids, alerts, readback }) => {
    const roomB = room_id === "room:room_b_";
    const row = (
      kind: StatusEntity["kind"],
      entity_id: string,
      name: string,
      zone: number | null,
      ageS: number,
      extra: Partial<StatusEntity> = {},
    ): StatusEntity => ({
      entity_id,
      name,
      kind,
      zone,
      last_seen: iso(now - ageS * 1000),
      last_change: iso(now - ageS * 1000),
      ok: true,
      uptime_7d_pct: 100,
      ...extra,
    });
    const entities: StatusEntity[] = [];
    for (const kind of ["vwc", "ec"] as const)
      for (const zone of [1, 2, 3])
        for (const side of ["front", "back"]) {
          const silent = roomB && zone === 2 && side === "back";
          entities.push(
            row(
              kind === "vwc" ? "probe_vwc" : "probe_ec",
              `sensor.${ids}z${zone}_${side}_${kind}`,
              `Zone ${zone} ${side} ${kind === "vwc" ? "VWC" : "EC"}`,
              zone,
              silent ? 3 * 3600 : 4 + zone,
              silent ? { ok: false, uptime_7d_pct: 91.38392857142857 } : zone === 3 && side === "back" ? { uptime_7d_pct: 99.9 } : {},
            ),
          );
        }
    for (const zone of [1, 2, 3])
      entities.push(row("valve", `switch.${ids}valve_${zone}`, `Zone ${zone} valve`, zone, 600 + zone * 360));
    entities.push(row("pump", `switch.${ids}pump`, "Feed pump", null, 300));
    entities.push(row("feed_probe", `sensor.${ids}tank_ec`, "Feed EC", null, 5, { uptime_7d_pct: 98.7 }));
    entities.push(row("feed_probe", `sensor.${ids}tank_ph`, "Feed pH", null, 5, { uptime_7d_pct: 99.9 }));
    entities.push(row("tank", `sensor.${ids}tank_level`, "Tank level", null, 30));
    entities.push(row("tank", `sensor.${ids}tank_temperature`, "Feed temperature", null, 5));
    const beats: StatusBeat[] = [];
    // The backend's ring holds the last 120 beats (2 h); the page shows the last hour.
    for (let i = 119; i >= 0; i--) {
      const at = now - 18_000 - i * 60_000;
      if (roomB && i === 50) beats.push({ at: iso(at), missed: true, readback_ms: null, gap_s: 140 });
      else beats.push({ at: iso(at), missed: false, readback_ms: readback });
    }
    const ok = entities.filter((e) => e.ok).length;
    return {
      room_id,
      pct_online: (ok / entities.length) * 100,
      alerts_open: alerts,
      entities,
      groups: [...new Set(entities.map((e) => e.kind))].map((kind) => ({
        kind,
        entities: entities.filter((e) => e.kind === kind),
      })),
      heartbeat: {
        last_beat: iso(now - 18_000),
        age_s: 18,
        controller: "running" as const,
        beats,
        interval_s: 60,
      },
    };
  });
  const every = rooms.flatMap((room) => room.entities);
  return {
    controller: "running",
    addon_version: "3.18.0",
    pct_online: (every.filter((e) => e.ok).length / every.length) * 100,
    ha_version: "2026.10.1",
    ai: { model: "claude-haiku-4-5", calls_today: 42, daily_budget: 200, pct_used: 21 },
    card_version: "3.18.0",
    rooms,
  };
}
