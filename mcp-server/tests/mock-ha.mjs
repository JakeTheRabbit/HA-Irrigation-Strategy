import { createServer } from "node:http";
import { once } from "node:events";
import { Client } from "@modelcontextprotocol/client";
import { StdioClientTransport } from "@modelcontextprotocol/client/stdio";
import { fileURLToPath } from "node:url";

export const TOKEN = "mock-secret-DO-NOT-LOG";
const parameters = {
  dryback_target: 20,
  ec_target_p0: 3,
  ec_target_p1: 3,
  ec_target_p2: 3,
  p1_target_vwc: 60,
  p2_vwc_threshold: 40,
  p2_shot_size: 2,
  p1_initial_shot_size: 3,
  p3_emergency_vwc_threshold: 25,
  p3_emergency_shot_size: 2,
};
export const planFixture = () => ({
  schema_version: 1,
  profiles: [
    {
      id: "profile",
      name: "Grower values",
      vegetative: { ...parameters },
      generative: { ...parameters },
    },
  ],
  zones: [
    {
      zone_id: 1,
      start_date: "2026-09-01",
      schedule: [
        { start_day: 1, end_day: 84, profile_id: "profile", bias: 50 },
      ],
    },
  ],
});
// custom_components/crop_steering/plumbing.py: layout -> [pump, main line], `infer`, `problems`.
const LAYOUTS = {
  valves_only: [false, false],
  pump_valves: [true, false],
  mainline_valves: [false, true],
  pump_mainline_valves: [true, true],
};
const inferPlumbing = (hardware) =>
  Object.keys(LAYOUTS).find(
    (layout) =>
      LAYOUTS[layout][0] === Boolean(hardware.pump_switch) &&
      LAYOUTS[layout][1] === Boolean(hardware.main_line_switch),
  );
const plumbingProblem = (layout, hardware) =>
  [
    ["pump_switch", 0, "pump"],
    ["main_line_switch", 1, "main-line valve"],
  ]
    .filter(([key, index]) => Boolean(hardware[key]) !== LAYOUTS[layout][index])
    .map(([, , label]) => `The plumbing for this room disagrees about its ${label}`)
    .join(". ");
// The default room has never declared its plumbing ("": every install from before 2.19.0); Room B
// has, as a pump then zone valves, which is what its mapped switches are.
function room(prefix, name) {
  const hardware = {
    pump_switch: "switch." + prefix + "pump",
    tank_temperature_sensor: "sensor." + prefix + "tank_temp",
  };
  return {
    entry_id: "entry-" + (prefix || "default"),
    prefix,
    slug: prefix || "default",
    room_name: name,
    revision: 4,
    active: true,
    plumbing: prefix ? "pump_valves" : "",
    plumbing_inferred: inferPlumbing(hardware),
    zones: [
      {
        id: 1,
        name: "Zone 1",
        active: true,
        valve: "switch." + prefix + "valve",
        vwc_sensors: ["sensor." + prefix + "vwc"],
        ec_sensors: ["sensor." + prefix + "ec"],
        plant_count: 42,
        substrate_volume: 6.75,
        drippers_per_plant: 1,
        dripper_flow_rate: 4,
      },
    ],
    hardware,
    safety: { ready: true, blockers: [] },
  };
}
export async function mockHa(t) {
  const rooms = [room("", "Default"), room("room_b_", "Room B")];
  const candidates = rooms.flatMap((r) => [
    {
      entity_id: "switch." + r.prefix + "pump",
      name: r.room_name + " pump",
      domain: "switch",
      state: "off",
      unit: "",
    },
    {
      entity_id: "switch." + r.prefix + "valve",
      name: r.room_name + " valve",
      domain: "switch",
      state: "off",
      unit: "",
    },
    {
      entity_id: "switch." + r.prefix + "main_line",
      name: r.room_name + " main line",
      domain: "switch",
      state: "off",
      unit: "",
    },
    {
      entity_id: "sensor." + r.prefix + "vwc",
      name: r.room_name + " VWC",
      domain: "sensor",
      state: "60",
      unit: "%",
    },
    {
      entity_id: "sensor." + r.prefix + "ec",
      name: r.room_name + " EC",
      domain: "sensor",
      state: "3",
      unit: "mS/cm",
    },
    {
      entity_id: "sensor." + r.prefix + "tank_temp",
      name: r.room_name + " tank temp",
      domain: "sensor",
      state: "21",
      unit: "°C",
    },
  ]);
  const plans = Object.fromEntries(
    rooms.map((r) => [
      "room:" + r.prefix,
      {
        room_id: "room:" + r.prefix,
        revision: 7,
        status: "draft",
        plan: planFixture(),
        catalog: {},
        active: { zones: [] },
        error: null,
      },
    ]),
  );
  const calls = [],
    states = new Map();
  for (const r of rooms) {
    states.set(`sensor.crop_steering_${r.prefix}ai_heartbeat`, {
      state: "online",
      attributes: {
        enable_flag: `switch.${r.prefix}engine`,
        last_beat: "2026-09-08T05:00:00+12:00",
        internal_secret: "omit",
      },
    });
    states.set(`switch.${r.prefix}engine`, { state: "off" });
    for (const suffix of [
      "zone_1_phase",
      "vwc_zone_1",
      "ec_zone_1",
      "zone_1_daily_water_app",
    ])
      states.set(`sensor.crop_steering_${r.prefix}${suffix}`, {
        state: suffix.includes("phase") ? "P1" : "5.6",
      });
  }
  // The stores behind the previewed writes (timers_api, site_api, calibration, presets), one room's
  // worth for room:room_b_. A handler throws refusal(code, message) for an ok:false answer.
  const refusal = (code, message, current_revision) =>
    Object.assign(new Error(message), { code, current_revision });
  const stale = (store, body) => {
    if (body.expected_revision !== store.revision)
      throw refusal("stale_revision", "Changed elsewhere. Reload before saving.", store.revision);
  };
  const sectionDiff = (old, now) =>
    Object.keys({ ...old, ...now })
      .filter((key) => JSON.stringify(old[key]) !== JSON.stringify(now[key]))
      .map((path) => ({ path, old: old[path] ?? null, new: now[path] ?? null }));
  const timers = {
    revision: 3,
    programs: [
      {
        id: "t1",
        name: "Morning",
        type: "simple",
        zones: [1],
        duration_s: 60,
        active: true,
        window: { kind: "all" },
        frequency_per_day: 2,
        created_at: "2026-10-01T00:00:00+13:00",
      },
    ],
  };
  const rules = {
    revision: 5,
    rules: [
      {
        id: "r1",
        kind: "threshold",
        room_id: "room:room_b_",
        zones: [1],
        source: "zone.vwc",
        op: "below",
        threshold: 30,
        unit: "%",
        window: { kind: "all" },
        min_duration_s: 0,
        severity: "warning",
        routing: "sensors",
        active: true,
      },
    ],
  };
  const SUPPLY = ["irrigation_pumps", "water_sources", "zone_groups", "zone_meters"];
  const supplyStore = {
    revision: 2,
    irrigation_pumps: [],
    water_sources: [],
    zone_groups: {},
    zone_meters: {},
  };
  const supplyOf = () =>
    Object.fromEntries(SUPPLY.map((key) => [key, supplyStore[key]]));
  const calibration = { revision: 9, offsets: {} };
  // The numbers a preset or a copy writes, by target ("room_id" or "room_id/zone").
  const numbers = {
    "room:room_b_": { p1_target_vwc: 60, p2_shot_size: 2 },
    "room:room_b_/1": { p1_target_vwc: 58, p2_shot_size: 2 },
    "room:/1": { p1_target_vwc: 66, p2_shot_size: 3 },
  };
  const presets = { p1: { p1_target_vwc: 65, p2_shot_size: 2 } };
  const where = (target) =>
    target.room_id + (target.zone ? "/" + target.zone : "");
  // presets.apply: {diff, missing, applied?}. `presetFault`: "sticky" = a write that does not
  // take; "timer" = once written, a (re-)preview names a refused timer row in `missing`;
  // "refuse" = the last row is refused (site_api._rows_refused: ok:false guard_refused, data kept).
  const writeValues = (wanted, to, preview) => {
    const out = { diff: [], missing: [] };
    for (const target of to) {
      const own = numbers[where(target)];
      if (!own) throw refusal("invalid", `Room ${target.room_id} is unknown`);
      for (const [key, value] of Object.entries(wanted))
        if (!(key in own)) out.missing.push({ target, key });
        else if (own[key] !== value)
          out.diff.push({ target, key, old: own[key], new: value });
      if (state.presetFault === "timer" && state.writes > 0)
        out.missing.push({
          target,
          key: "timers",
          reason: "source room has no timer programs",
        });
    }
    if (preview) return out;
    state.writes++;
    const sticky = state.presetFault === "sticky";
    const refused = state.presetFault === "refuse" ? out.diff.at(-1) : null;
    out.applied = out.diff.map((row) => {
      if (row === refused)
        return { target: row.target, key: row.key, readback: "refused", error: "out of bounds" };
      if (!sticky) numbers[where(row.target)][row.key] = row.new;
      return {
        target: row.target,
        key: row.key,
        readback: sticky ? "none" : "verified",
        error: null,
      };
    });
    if (refused)
      throw Object.assign(
        refusal("guard_refused", `Not applied: ${refused.key}: out of bounds`),
        { data: out },
      );
    return out;
  };
  // The services that answer the API v2 envelope (api_v2.wrap): service -> request -> data.
  // `refuse` maps a service to the {code, message} it answers ok:false with.
  const v2 = {
    timer_program_list: (body) => ({
      programs: timers.programs.map((p) => ({
        ...p,
        room_id: body.room_id,
        next_at: null,
        error: null,
      })),
      revision: timers.revision,
      error: null,
    }),
    timer_program_preview: (body) => ({
      preview: [
        {
          zone: body.program.zones[0],
          at: "2026-10-23T06:00:00+13:00",
          duration_s: body.program.duration_s,
        },
      ],
      shots: 1,
      total_s: body.program.duration_s,
    }),
    timer_program_set: (body) => {
      stale(timers, body);
      const program = {
        active: true,
        window: { kind: "all" },
        ...body.program,
        id: body.program.id ?? "t-new",
        updated_at: "2026-10-23T05:00:00+13:00",
      };
      timers.programs = [
        ...timers.programs.filter((p) => p.id !== program.id),
        program,
      ];
      timers.revision++;
      state.saveCount++;
      return { program, revision: timers.revision, preview: [] };
    },
    alert_rule_preview: (body) => ({
      summary_sentence: `Tell when VWC goes ${body.rule.op} ${body.rule.threshold}%.`,
      series: [],
      spans: [],
      ignored_dips: [],
    }),
    alert_rule_set: (body) => {
      stale(rules, body);
      const rule = { unit: "%", ...body.rule, id: body.rule.id ?? "r-new" };
      rules.rules = [...rules.rules.filter((r) => r.id !== rule.id), rule];
      rules.revision++;
      state.saveCount++;
      return {
        rule: { ...rule, summary_sentence: "s" },
        summary_sentence: "s",
        revision: rules.revision,
      };
    },
    supply_save: (body) => {
      stale(supplyStore, body);
      const now = {
        ...supplyOf(),
        ...Object.fromEntries(
          SUPPLY.filter((key) => key in body).map((key) => [key, body[key]]),
        ),
      };
      const diff = sectionDiff(supplyOf(), now);
      if (body.preview) return { diff, capacity_check: [] };
      Object.assign(supplyStore, now, { revision: supplyStore.revision + 1 });
      state.saveCount++;
      return {
        revision: supplyStore.revision,
        ...supplyOf(),
        capacity_check: [],
        warnings: [],
        error: null,
        readback: { status: "ok" },
      };
    },
    probe_offset_set: (body) => {
      if (body.entity_id !== "sensor.room_b_vwc")
        throw refusal("invalid", "That is not a moisture probe of this room");
      if (!body.preview) stale(calibration, body);
      const old = calibration.offsets[body.entity_id] ?? { offset: 0, curve: null };
      const offset =
        "match_handheld" in body
          ? body.match_handheld - 50
          : (body.offset ?? old.offset);
      const curve =
        "curve" in body ? (body.curve === "none" ? null : body.curve) : old.curve;
      const diff = [];
      if (offset !== old.offset)
        diff.push({ path: body.entity_id + ".offset", old: old.offset, new: offset });
      if (curve !== old.curve)
        diff.push({ path: body.entity_id + ".curve", old: old.curve, new: curve });
      diff.push({ path: body.entity_id + ".at", old: null, new: "2026-10-23T05:00:00+13:00" });
      const out = {
        offset,
        curve,
        corrected_now: 50 + offset,
        fused_before: 50,
        fused_after: 50 + offset,
        excluded_after: {},
      };
      if (body.preview)
        return { ...out, preview: true, diff, revision: calibration.revision };
      calibration.offsets[body.entity_id] = { offset, curve };
      calibration.revision++;
      state.saveCount++;
      return { ...out, revision: calibration.revision };
    },
    preset_apply: (body) => {
      if (!presets[body.preset_id])
        throw refusal("invalid", `No preset ${body.preset_id}`);
      return writeValues(presets[body.preset_id], body.to, body.preview);
    },
    copy_config: (body) => {
      const source = numbers[where(body.from)];
      if (!source) throw refusal("invalid", "Unknown source");
      return { ...writeValues(source, body.to, body.preview), skipped: [] };
    },
    journal_query: (body) => ({
      events: [
        { v: 1, id: "01J0000000000000000000000A", kind: "shot.started", room_id: body.room_id },
      ],
      cursor: null,
    }),
    timeline_get: (body) => ({
      rooms: body.rooms.map((room_id) => ({
        room_id,
        lights: [],
        rows: [],
        pump: null,
        pump_rooms: [],
        pump_load: [],
        planned_source: "unavailable",
        added_later: true,
      })),
      errors: { count: 0, markers: [] },
    }),
    timeline_summary: (body) => ({
      days: body.days.map((date) => ({
        date,
        rooms: body.rooms.map((room_id) => ({
          room_id,
          shots: 3,
          failed: 0,
          warnings: 1,
          held: 0,
          queued: 0,
        })),
      })),
    }),
    history_changes: (body) => ({
      changes: [{ event_id: "e1", room_id: body.room_id, key: "p1_target_vwc" }],
    }),
    supply_get: () => ({
      revision: supplyStore.revision,
      ...supplyOf(),
      capacity_check: [],
      warnings: [],
      error: null,
    }),
    system_status_get: () => ({
      controller: "running",
      addon_version: "3.0.0",
      pct_online: 100,
      rooms: [],
      ha_version: "2026.10.0",
      ai: null,
      card_version: null,
    }),
    alert_rule_list: (body) => ({
      rules:
        body.room_id === "room:room_b_"
          ? rules.rules.map((r) => ({ ...r, summary_sentence: "s", state: "armed" }))
          : [{ id: "r1", room_id: body.room_id ?? "room:", state: "armed" }],
      revision: rules.revision,
    }),
  };
  const state = {
    rooms,
    candidates,
    plans,
    calls,
    states,
    v2,
    refuse: {},
    intercept: null,
    saveCount: 0,
    writes: 0,
    presetFault: null,
    timers,
    rules,
    supply: supplyStore,
    calibration,
    numbers,
  };
  const server = createServer(async (req, res) => {
    try {
      const chunks = [];
      for await (const chunk of req) chunks.push(chunk);
      const body = chunks.length
        ? JSON.parse(Buffer.concat(chunks).toString())
        : null;
      calls.push({
        path: req.url,
        method: req.method,
        body,
        authorization: req.headers.authorization,
      });
      const json = (value, status = 200) => {
        res.writeHead(status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(value));
      };
      if (await state.intercept?.(req, res, body, json)) return;
      if (req.headers.authorization !== `Bearer ${TOKEN}`)
        return json({ message: "Unauthorized" }, 401);
      const match = req.url.match(
        /^\/api\/services\/crop_steering\/([a-z_]+)\?return_response$/,
      );
      if (match) {
        let result;
        const action = match[1];
        if (v2[action]) {
          if (body?.api !== 2)
            return json({ message: "This mock answers only api 2" }, 400);
          let refused = state.refuse[action],
            answer,
            kept;
          try {
            if (!refused) answer = v2[action](body);
          } catch (error) {
            if (!error.code) throw error;
            const { code, message, current_revision } = error;
            refused = { code, message };
            if (current_revision !== undefined)
              refused.current_revision = current_revision;
            kept = error.data;
          }
          result = refused
            ? { api: 2, ok: false, error: refused, ...(kept ? { data: kept } : {}) }
            : {
                api: 2,
                ok: true,
                room_id: body.room_id ?? null,
                revision: null,
                readback: { status: "none", at: "2026-10-23T05:00:00+13:00" },
                event_ids: [],
                data: answer,
              };
        } else if (action === "setup_read")
          result = { api_version: 1, rooms, candidates, ignored_secret: TOKEN };
        else if (action === "setup_save") {
          const r = rooms.find((r) => r.entry_id === body.entry_id);
          if (!r || r.revision !== body.expected_revision)
            return json({ message: "Room setup changed; refresh" }, 400);
          if (!r.safety.ready)
            return json({ message: "Pump must be OFF" }, 400);
          // setup_api.prepare_setup: declared, never inferred; absent from the payload keeps
          // what the room already declared; an active room's switches have to agree with it.
          const layout = body.plumbing || r.plumbing || "";
          if (layout && !LAYOUTS[layout])
            return json({ message: "Unknown plumbing layout" }, 400);
          if (layout && body.active && plumbingProblem(layout, body.hardware))
            return json({ message: plumbingProblem(layout, body.hardware) }, 400);
          state.saveCount++;
          Object.assign(r, {
            room_name: body.room_name,
            active: body.active,
            plumbing: layout,
            plumbing_inferred: inferPlumbing(body.hardware),
            hardware: body.hardware,
            zones: body.zones,
            revision: r.revision + 1,
          });
          result = r;
        } else if (action === "strategy_get" || action === "strategy_preview") {
          result = plans[body.room_id];
          if (!result) return json({ message: "Unknown room" }, 400);
          if (action === "strategy_preview") {
            if (body.plan.profiles[0].vegetative.p1_target_vwc > 85)
              return json(
                { message: "Zone 1 p1_target_vwc outside readable HA bounds" },
                400,
              );
            result = {
              ...result,
              preview: {
                date: "2026-09-08",
                zones: [
                  { zone_id: 1, parameters: body.plan.profiles[0].vegetative },
                ],
              },
            };
          }
        } else if (action === "strategy_save") {
          const p = plans[body.room_id];
          if (p.revision !== body.expected_revision || p.status !== "draft")
            return json({ message: "Strategy changed" }, 400);
          p.plan = body.plan;
          p.revision++;
          state.saveCount++;
          result = p;
        } else if (action === "runs_get")
          result = {
            room_id: body.room_id,
            revision: 1,
            time_zone: "Pacific/Auckland",
            runs: Array.from({ length: 12 }, (_, n) => ({
              id: `run-${n}`,
              name: "Run " + n,
              notes: "Reference only",
            })),
            error: null,
          };
        else return json({ message: "Forbidden service" }, 404);
        return json({ changed_states: [], service_response: result });
      }
      if (req.method === "GET" && req.url.startsWith("/api/states/")) {
        const entity = decodeURIComponent(req.url.slice("/api/states/".length));
        const found =
          states.get(entity) ||
          candidates.find((row) => row.entity_id === entity);
        return found
          ? json({
              entity_id: entity,
              last_updated: "2026-09-08T05:00:00+12:00",
              attributes: {},
              ...found,
            })
          : json({ message: "not found" }, 404);
      }
      json({ message: "Unsupported endpoint" }, 404);
    } catch {
      res.writeHead(500);
      res.end("{}");
    }
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  state.url = `http://127.0.0.1:${server.address().port}`;
  t.after(() => {
    server.closeAllConnections();
    return new Promise((resolve) => server.close(resolve));
  });
  return state;
}
export async function stdio(t, ha, env = {}) {
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [fileURLToPath(new URL("../dist/index.js", import.meta.url))],
    env: { HA_URL: ha.url, HA_TOKEN: TOKEN, ...env },
    stderr: "pipe",
  });
  const client = new Client({ name: "crop-steering-test", version: "1.0.0" });
  let stderr = "";
  transport.stderr?.on("data", (chunk) => {
    stderr += chunk;
  });
  await client.connect(transport);
  t.after(async () => {
    await client.close();
    if (stderr.includes(TOKEN))
      throw new Error("Credential appeared on stderr");
  });
  return { client, stderr: () => stderr };
}
export async function call(client, name, args = {}) {
  return client.callTool({ name, arguments: args });
}
export function data(result) {
  if (result.isError) throw new Error(result.content[0].text);
  return result.structuredContent ?? JSON.parse(result.content[0].text);
}
