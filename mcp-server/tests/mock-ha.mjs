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
function room(prefix, name) {
  return {
    entry_id: "entry-" + (prefix || "default"),
    prefix,
    slug: prefix || "default",
    room_name: name,
    revision: 4,
    active: true,
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
    hardware: {
      pump_switch: "switch." + prefix + "pump",
      tank_temperature_sensor: "sensor." + prefix + "tank_temp",
    },
    safety: { ready: true, blockers: [] },
  };
}
export async function mockHa(t) {
  const rooms = [room("", "Default"), room("veg_", "Veg")];
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
  const state = {
    rooms,
    candidates,
    plans,
    calls,
    states,
    intercept: null,
    saveCount: 0,
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
        if (action === "setup_read")
          result = { api_version: 1, rooms, candidates, ignored_secret: TOKEN };
        else if (action === "setup_save") {
          const r = rooms.find((r) => r.entry_id === body.entry_id);
          if (!r || r.revision !== body.expected_revision)
            return json({ message: "Room setup changed; refresh" }, 400);
          if (!r.safety.ready)
            return json({ message: "Pump must be OFF" }, 400);
          state.saveCount++;
          Object.assign(r, {
            room_name: body.room_name,
            active: body.active,
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
