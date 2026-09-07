# Configure Crop Steering through MCP

The [standalone MCP server](../mcp-server/README.md) lets an assistant inspect Crop Steering and prepare specific configuration changes in an existing Home Assistant installation. It uses local stdio and the official TypeScript MCP SDK. Read tools and previews are available by default; writes are opt-in and limited to reviewed setup changes or saved draft plans.

## Prerequisites and connection

Install Crop Steering in Home Assistant and create the room in **Rooms & setup** first. The integration must expose response-bearing `crop_steering.setup_read`, `setup_save`, `strategy_get`, `strategy_preview`, `strategy_save`, and `runs_get` services. Setup services require an authenticated Home Assistant administrator. Run this package on a computer that can reach that HA instance.

Install Node.js 22 or newer, then build the server:

```sh
cd mcp-server
npm ci
npm run build
npm test
```

The MCP host launches `node /absolute/path/to/HA-Irrigation-Strategy/mcp-server/dist/index.js`. Provide these values through the host's process environment:

| Variable                     | Meaning                                                                                                                 |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `HA_URL`                     | Required fixed HA origin, such as `http://homeassistant.local:8123`. No path, embedded credentials, query, or fragment. |
| `HA_TOKEN`                   | Required private Home Assistant access token. Use a dedicated HA account/token and keep the host configuration private. |
| `CROP_STEERING_ALLOW_WRITES` | Only the exact string `true` enables proposal application. Omitted, `false`, `1`, or `yes` leave writes disabled.       |
| `HA_TIMEOUT_MS`              | Optional per-request deadline, including response-body reads. Default 10000; allowed range 100–60000.                   |

Home Assistant tokens retain that HA user's privileges; this package's tool allowlist narrows what the connected assistant can request through this process, not what someone possessing the token could do elsewhere. No token is accepted in tool arguments or returned as configuration. The server does not log credentials, HA response bodies or stack traces. It sends stdout only as MCP messages, rejects HTTP redirects, validates normal TLS certificates, and opens no unauthenticated network listener. Use HTTPS when traffic leaves a trusted local network.

[Claude Desktop and generic stdio connection examples](../mcp-server/README.md#claude-desktop) show the host configuration. Local stdio requires a host that can spawn a local process; an HTTP-only connector cannot use the command as a URL. No npm publication or bundled runtime is provided.

## Tools

| Tool                        | Inputs                                                           | Result                                                                                                                                                                       |
| --------------------------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list_rooms`                | None                                                             | Exact room IDs, setup revisions, names, zone counts, readiness and write-mode status.                                                                                        |
| `get_room_configuration`    | `room_id`                                                        | Explicit hardware mappings and existing zone names, probe lists and hydraulic sizing, plus safety blockers.                                                                  |
| `get_room_status`           | `room_id`, optional `zone_id`                                    | Reported engine, tank/plumbing and zone readings with update timestamps. Missing entities remain null. Defaults to first eight active zones; select another zone explicitly. |
| `search_candidate_entities` | `query` (2–100 characters), optional `domain`, `offset`, `limit` | Matching setup candidates only; at most 50 returned per call. A match is not proof of physical identity.                                                                     |
| `get_room_plan`             | `room_id`                                                        | Draft/active plan state, revision, grower endpoint profiles, schedules, current parameter catalog and active snapshot.                                                       |
| `get_room_runs`             | `room_id`, optional `offset`, `limit`                            | Saved run metadata/reference snapshots; at most ten records. No Recorder measurements.                                                                                       |
| `preview_setup`             | `room_id`, `changes`                                             | Local validation, complete diff and proposed configuration, expected revision, expiring `proposal_token`. No HA write.                                                       |
| `preview_plan`              | `room_id`, complete `plan`                                       | HA-validated draft plan preview, complete diff and expiring proposal token. No save or activation.                                                                           |
| `apply_proposal`            | `room_id`, `expected_revision`, `proposal_token`                 | Applies only the stored payload, then independently reads it back. Write opt-in and user authorization required.                                                             |

Use `room_id` exactly as returned. The default room is `room:`; a named room uses its complete prefix, for example `room:veg_`. No friendly-name matching or fallback to another room is used. The legacy `sensor.crop_steering_system_engine_config` descriptor is considered only for the default room when the canonical descriptor is absent, and the descriptor's explicit prefix must match.

HA labels, entity state strings, plan names and run notes are data, not assistant instructions. Tool outputs are capped at 256 KiB; upstream responses at 8 MiB; request bodies at 256 KiB. Large plans may require the dashboard. Candidate discovery requests the existing HA setup response but exposes only the bounded matching fields to the assistant. The server does not fetch the full `/api/states` collection.

## Reviewed room setup

Read the room and relevant candidates before proposing changes. This example changes two sizing fields on existing zone 1:

```json
{
  "room_id": "room:veg_",
  "changes": {
    "zones": [{ "id": 1, "plant_count": 42, "substrate_volume": 6.75 }]
  }
}
```

Call `preview_setup` with that payload. Allowed changes are:

- `room_name` and existing zone `name`.
- Explicit `hardware` mappings supported by Rooms & setup: pump, mainline, waste, lights, source-water probes, ambient probes and dedicated tank telemetry.
- Existing zone `valve`, `vwc_sensors`, `ec_sensors`, `plant_count`, `substrate_volume`, `drippers_per_plant`, and `dripper_flow_rate`.

Plant count and drippers per plant must be integers; sizes and flow rates follow the same limits as HA setup. Sensor lists must be unique and contain no more than 32 IDs. Empty strings clear optional mappings. Legacy null mapping values are normalized to empty strings when read; new null values are rejected.

The preview merges only those requested fields into the current room. Room identity, active/archive state, zone IDs and omitted configuration are preserved. It checks input shape, field bounds, candidate existence/domains and probe units. **The current HA API has no separate setup-validation endpoint:** HA performs its authoritative timestamp, cross-room hardware-conflict and affected-engine/plumbing-OFF validation during `setup_save`. The preview reports current readiness, not a guarantee that applying later will succeed. A tank probe mapping is distinct from a feed probe mapping; selecting the dedicated tank EC/pH keys does not enable source-water gates.

Show the entire returned diff to the user. After authorization, `apply_proposal` receives only the token, room ID and expected revision; it cannot accept a replacement configuration. It checks fresh room identity, revision, mappings and sizing against the reviewed snapshot, then submits the stored payload to HA. HA checks the affected engines and the union of old/new/shared plumbing again. This tool never turns anything off or on to satisfy those requirements.

The result is verified only when an independent read returns the expected incremented revision and configuration. This confirms persisted configuration, not electrical or hydraulic behavior. Other HA clients remain subject to HA's existing concurrency rules; this process cannot make unrelated HA entity edits atomic with setup saves.

Room creation, appending/removing zones, archiving/restoring rooms, enabling engines or zones, and raw live setpoint writes remain in the existing HA/dashboard workflows.

## Draft grow plans

Use `get_room_plan` to obtain the room's existing plan, active zone IDs and parameter catalog. Supply a complete schema-version-1 plan to `preview_plan`. Profiles contain matching vegetative/generative parameter keys; zone schedules use `start_day`, `end_day`, `profile_id`, and a bias from 0 to 100. Use valid YYYY-MM-DD start dates. The MCP schema accepts only supported canonical steering keys and day-based schedules.

The server calls the existing `strategy_preview` service to validate endpoint values, HA bounds/steps, relationships and zone assignments. It stores the exact submitted plan for review. Both preview and apply require draft status; saving cannot replace an armed/active plan. A later status, plan, catalog, or room setup change invalidates the proposal. HA also enforces its revision and draft-state checks when saving.

Saving a draft does not arm or activate it and does not change live manual number entities. Activation/disarm are intentionally absent from the MCP tool surface. The package does not prescribe agronomic targets; the user supplies them and reviews the resulting configuration.

## Proposal lifetime and failures

- Writes are disabled unless the process starts with `CROP_STEERING_ALLOW_WRITES=true`. Restarting after enabling it requires a fresh proposal.
- Up to twenty pending proposals are held only in process memory, each for ten minutes. They are not written to disk and disappear on restart.
- The token is single-use. The server consumes it before fresh-state checks or any write; concurrent/replayed calls cannot submit it twice.
- The token proves which payload was reviewed, not that a person approved it. Keep the MCP host's write-tool approval enabled and authorize only after reading the complete diff.
- If source configuration changed, preview again. If HA reports equipment blockers, resolve them through normal controls, inspect the state, and make a new proposal.
- A timeout or failed readback after submission may mean HA saved the change. There is no automatic write retry or rollback. Read the room/plan and inspect HA before proposing another change.

## Verification and upstream references

The package uses official `@modelcontextprotocol/server` and `@modelcontextprotocol/client` **2.0.0**, verified from the npm registry on 2026-09-08, with an exact dependency lockfile. The official SDK identifies v2 as the stable release line and provides the local `serveStdio` transport. See the [SDK documentation](https://ts.sdk.modelcontextprotocol.io/v2/), [stdio client handshake documentation](https://ts.sdk.modelcontextprotocol.io/v2/clients/connect), and [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/).

`npm test` compiles strict TypeScript and launches real server subprocesses using the official SDK stdio client. The isolated HTTP mock tests cover initialize, tool listing/calls, all read tools, exact proposal saves and readback, disabled writes, strict schemas, room isolation, stale revisions and sizing, HA safety rejections, plan validation/status/bounds, concurrent replay, timeout uncertainty, redirection rejection, credential redaction, response limits, expiry, process restart, legacy descriptor and null mapping compatibility. All test HTTP listeners bind only to loopback and use a dummy token; they do not operate live equipment.

On 8 September 2026, an official SDK client also initialized this server and successfully called all six read tools against an existing two-room Home Assistant installation, with writes disabled. This establishes live read compatibility; configuration-write and third-party LLM-host verification are separate checks.
