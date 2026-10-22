# Configure Crop Steering through MCP

The [standalone MCP server](../mcp-server/README.md) lets an assistant inspect Crop Steering and prepare specific configuration changes in an existing Home Assistant installation. It uses local stdio and the official TypeScript MCP SDK. Read tools and previews are available by default; writes are opt-in and limited to reviewed proposals: setup changes, draft plans, timer programs, alert rules, preset applies, copies, probe offsets and the site's supply. No tool runs a pump, opens a valve, submits an irrigation intent or steps a calibration.

## Prerequisites and connection

Install Crop Steering in Home Assistant and create the room in **Rooms & setup** first. The integration must expose response-bearing `crop_steering.setup_read`, `setup_save`, `strategy_get`, `strategy_preview`, `strategy_save`, and `runs_get` services, and for the newer tools the API v2 services listed under [Tools](#tools). Setup services, and the services that save, arm or disarm a plan, change run records or save any of the stores below, require an authenticated Home Assistant administrator. Run this package on a computer that can reach that HA instance.

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
| `HA_TIMEOUT_MS`              | Optional per-request deadline, including response-body reads. Default 10000; allowed range 100-60000.                   |

Home Assistant tokens retain that HA user's privileges; this package's tool allowlist narrows what the connected assistant can request through this process, not what someone possessing the token could do elsewhere. No token is accepted in tool arguments or returned as configuration. The server does not log credentials, HA response bodies or stack traces. It sends stdout only as MCP messages, rejects HTTP redirects, validates normal TLS certificates, and opens no unauthenticated network listener. Use HTTPS when traffic leaves a trusted local network.

[Claude Desktop and generic stdio connection examples](../mcp-server/README.md#claude-desktop) show the host configuration. Local stdio requires a host that can spawn a local process; an HTTP-only connector cannot use the command as a URL. No npm publication or bundled runtime is provided.

## Tools

| Tool                        | Inputs                                                           | Result                                                                                                                                                                       |
| --------------------------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `list_rooms`                | None                                                             | Exact room IDs, setup revisions, names, zone counts, readiness and write-mode status.                                                                                        |
| `get_room_configuration`    | `room_id`                                                        | Explicit hardware mappings and existing zone names, probe lists and hydraulic sizing, plus safety blockers.                                                                  |
| `get_room_status`           | `room_id`, optional `zone_id`                                    | Reported engine, tank/plumbing and zone readings with update timestamps. Missing entities remain null. Defaults to first eight active zones; select another zone explicitly. |
| `search_candidate_entities` | `query` (2-100 characters), optional `domain`, `offset`, `limit` | Matching setup candidates only; at most 50 returned per call. A match is not proof of physical identity.                                                                     |
| `get_room_plan`             | `room_id`                                                        | Draft/active plan state, revision, grower endpoint profiles, schedules, current parameter catalog and active snapshot.                                                       |
| `get_room_runs`             | `room_id`, optional `offset`, `limit`                            | Saved run metadata/reference snapshots; at most ten records. No Recorder measurements.                                                                                       |
| `get_timeline`              | `room_id`, `start` + `end` (optional `zones`), or `days`         | `timeline_get`: shot, held, queued, alert and planned blocks per zone over at most 48 h; or `timeline_summary`: per-day counts for at most 14 days.                          |
| `get_changes`               | `room_id`, `since`, optional `until`, `zone`, `key`, `kinds`     | `history_changes`: who changed what, newest first, at most 2000 rows (`truncated` when cut).                                                                                 |
| `get_events`                | `room_id`, `since`, optional `until`, `kinds`, `zones`, `actor`, `limit` (1-500, default 100), `cursor` | `journal_query`: one page of journal events, oldest first, and the next page's `cursor` (null at the end).                                              |
| `get_alert_rules`           | optional `room_id`                                               | `alert_rule_list`: each rule, its sentence, state, last fired time and current value, and the alert rules revision.                                                         |
| `get_timer_programs`        | `room_id`                                                        | `timer_program_list`: the room's timer programs with their ids and next shot, and the timers revision.                                                                       |
| `get_supply`                | None                                                             | `supply_get`: the site's pumps, water sources, zone groups and meters, the capacity check and warnings. Revision 0 means never saved.                                       |
| `get_system_status`         | None                                                             | `system_status_get`: controller state and version, each room's entities online, open alerts and heartbeat.                                                                 |
| `preview_setup`             | `room_id`, `changes`                                             | Local validation, complete diff and proposed configuration, expected revision, expiring `proposal_token`. No HA write.                                                       |
| `preview_plan`              | `room_id`, complete `plan`                                       | HA-validated draft plan preview, complete diff and expiring proposal token. No save or activation.                                                                           |
| `preview_timer_program`     | `room_id`, `program`, optional `hours`                           | Kind `timer_program`. `preview` is `timer_program_preview` (the shots over the next hours).                                                                                  |
| `preview_alert_rule`        | `room_id`, `rule`, optional `hours`                              | Kind `alert_rule`. `preview` is `alert_rule_preview` (the sentence and a replay over the last hours).                                                                       |
| `preview_preset_apply`      | `room_id`, `preset_id`, optional `zones`                         | Kind `preset_apply`. `preview` is `preset_apply` with `preview: true` (`diff`, `missing`).                                                                                  |
| `preview_copy_config`       | `room_id`, `from` (`room_id`, optional `zone`), `sections`, optional `zones` | Kind `copy_config`. `preview` is `copy_config` with `preview: true` (`diff`, `missing`, `skipped`).                                                             |
| `preview_probe_offset`      | `room_id`, `entity_id`, and `offset`, `curve` or `match_handheld` | Kind `probe_offset`. `preview` is `probe_offset_set` with `preview: true` (the fix, corrected reading, fused before/after).                                                 |
| `preview_supply`            | `irrigation_pumps`, optional `water_sources`, `zone_groups`, `zone_meters` | Kind `supply`, site-wide (`room_id` null). `preview` is `supply_save` with `preview: true` (`diff`, `capacity_check`).                                          |
| `apply_proposal`            | `room_id` (none for `supply`), `expected_revision`, `proposal_token` | Applies only the stored payload, then independently reads it back. Write opt-in and user authorization required.                                                      |

Use `room_id` exactly as returned. The default room is `room:`; a named room uses its complete prefix, for example `room:veg_`. No friendly-name matching or fallback to another room is used. The legacy `sensor.crop_steering_system_engine_config` descriptor is considered only for the default room when the canonical descriptor is absent, and the descriptor's explicit prefix must match.

The read tools from `get_timeline` on ask with `api: 2` (see [API v2 answers](#api-v2-answers-integration-services)) and return the answer's `data`; an `ok: false` answer is a tool error reading `<code>: <message>`. An answer for another room than the one asked is refused. An events page over the output cap says to lower `limit` and read on with the cursor.

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
- `plumbing`: how the room is plumbed, one of `valves_only`, `pump_valves`, `mainline_valves`, `pump_mainline_valves`. `get_room_configuration` returns the declared layout (`""` for a room that has never declared one) and `plumbing_inferred`, what its mapped switches imply.
- Explicit `hardware` mappings supported by Rooms & setup: pump, mainline, waste, lights, source-water probes, ambient probes and dedicated tank telemetry.
- Existing zone `valve`, `vwc_sensors`, `ec_sensors`, `plant_count`, `substrate_volume`, `drippers_per_plant`, and `dripper_flow_rate`.

Once a room has declared its plumbing, Home Assistant refuses a save whose pump or main-line mapping contradicts it, so **change `plumbing` and the mapping together in one proposal**: to take a pump out of a `pump_valves` room, send `{"plumbing": "valves_only", "hardware": {"pump_switch": ""}}`. The preview refuses either half on its own, before issuing a token, and says which switch disagrees. A room that has never declared its plumbing is not held to one, and these tools never declare one on the operator's behalf: only an explicit `plumbing` change does. A declaration can be changed but not withdrawn.

Plant count and drippers per plant must be integers; sizes and flow rates follow the same limits as HA setup. Sensor lists must be unique and contain no more than 32 IDs. Empty strings clear optional mappings. Legacy null mapping values are normalized to empty strings when read; new null values are rejected.

The preview merges only those requested fields into the current room. Room identity, active/archive state, zone IDs and omitted configuration are preserved. It checks input shape, field bounds, candidate existence/domains, probe units and that the declared plumbing agrees with the mapped pump and main line. **The current HA API has no separate setup-validation endpoint:** HA performs its authoritative timestamp, cross-room hardware-conflict and affected-engine/plumbing-OFF validation during `setup_save`. The preview reports current readiness, not a guarantee that applying later will succeed. A tank probe mapping is distinct from a feed probe mapping; selecting the dedicated tank EC/pH keys does not enable source-water gates.

Show the entire returned diff to the user. After authorization, `apply_proposal` receives only the token, room ID and expected revision; it cannot accept a replacement configuration. It checks fresh room identity, revision, mappings and sizing against the reviewed snapshot, then submits the stored payload to HA. HA checks the affected engines and the union of old/new/shared plumbing again. This tool never turns anything off or on to satisfy those requirements.

The result is verified only when an independent read returns the expected incremented revision and configuration. This confirms persisted configuration, not electrical or hydraulic behavior. Other HA clients remain subject to HA's existing concurrency rules; this process cannot make unrelated HA entity edits atomic with setup saves.

Room creation, appending/removing zones, archiving/restoring rooms, enabling engines or zones, and raw live setpoint writes remain in the existing HA/dashboard workflows.

## Draft grow plans

Use `get_room_plan` to obtain the room's existing plan, active zone IDs and parameter catalog. Supply a complete schema-version-1 plan to `preview_plan`. Profiles contain matching vegetative/generative parameter keys; zone schedules use `start_day`, `end_day`, `profile_id`, and a bias from 0 to 100. Use valid YYYY-MM-DD start dates. The MCP schema accepts only supported canonical steering keys and day-based schedules.

The server calls the existing `strategy_preview` service to validate endpoint values, HA bounds/steps, relationships and zone assignments. It stores the exact submitted plan for review. Both preview and apply require draft status; saving cannot replace an armed/active plan. A later status, plan, catalog, or room setup change invalidates the proposal. HA also enforces its revision and draft-state checks when saving.

Saving a draft does not arm or activate it and does not change live manual number entities. Activation/disarm are intentionally absent from the MCP tool surface. The package does not prescribe agronomic targets; the user supplies them and reviews the resulting configuration.

## Timers, alert rules, presets, copies, probe offsets and supply

Each `preview_*` tool below answers `{proposal_token, kind, room_id, expected_revision, diff, preview}` (plus `expires_at`, `writes_enabled` and `proposed_configuration`), where `preview` is the integration's own dry-run answer. Previews call only read services or a write service with `preview: true`, so they work with writes disabled and never send `client` or `proposal_token`. A preview with nothing to change is refused.

| Kind            | Dry run                                | Write                         | `diff`                                                           |
| --------------- | -------------------------------------- | ----------------------------- | ---------------------------------------------------------------- |
| `timer_program` | `timer_program_preview`                | `timer_program_set`           | The stored program (`timer_program_list`) against the proposed one. |
| `alert_rule`    | `alert_rule_preview`                   | `alert_rule_set`              | The stored rule (`alert_rule_list`) against the proposed one.    |
| `preset_apply`  | `preset_apply` with `preview: true`    | `preset_apply`                | HA's rows `{target, key, old, new}`.                             |
| `copy_config`   | `copy_config` with `preview: true`     | `copy_config`                 | HA's rows `{target, key, old, new}`.                             |
| `probe_offset`  | `probe_offset_set` with `preview: true` | `probe_offset_set`           | HA's rows `{path, old, new}`, without the `at`/`by` bookkeeping. |
| `supply`        | `supply_save` with `preview: true`     | `supply_save`                 | HA's rows `{path, old, new}`.                                    |

- A timer program or alert rule without an `id` is new; with one (from `get_timer_programs` or `get_alert_rules`) it replaces that one whole. Left out, a program is active all day; a rule is active all day, `warning`, routed to `sensors`, with no minimum duration. A rule takes the tool's `room_id`.
- A preset or copy writes one room: the room itself, or the listed `zones` of it. A copy may read from another room or zone. HA lists a key it has no entity for, and a timer row it refuses (with its `reason`), in `missing`, never in `diff`. A preview with anything in `missing` is refused, because that apply could never be verified.
- A probe offset given as `match_handheld` is stored as the offset HA worked out, so the apply writes exactly the reviewed offset and curve.
- The supply is site-wide: its proposal has `room_id` null, and `apply_proposal` takes no `room_id` for it. A section left out of the save is kept.

`apply_proposal` sends the stored payload with `client: "mcp"`, the `proposal_token` and `api: 2`, then reads back:

- **Revisioned stores** (`timer_program`, `alert_rule`, `probe_offset`, `supply`): the write names `expected_revision`, and the result counts only when the store reads back at `expected_revision + 1` with every value the proposal set (`timer_program_list` or `alert_rule_list` for the saved id; for a probe offset, `probe_offset_set` in preview again with nothing left to change; for the supply, `supply_get` and `supply_save` in preview again with an empty diff, and the save's own readback `ok`).
- **Entity writes** (`preset_apply`, `copy_config`): no revision is involved, and `expected_revision` is 0. Before writing, the same call is previewed again and must match what was reviewed, or nothing is written. After writing, the result counts only when every `applied[].readback` is `verified` **and** the same call, previewed again, answers an empty `diff` **and** an empty `missing`.
- A `stale_revision` answer is reported as "the revision moved after preview": nothing was saved; preview again. Any other `ok: false` answer (`guard_refused`, `invalid`, `forbidden`, `unavailable`) is reported with its code and message. A refused preset or copy row leaves the others written.

## Proposal lifetime and failures

- Writes are disabled unless the process starts with `CROP_STEERING_ALLOW_WRITES=true`. Restarting after enabling it requires a fresh proposal.
- Up to twenty pending proposals are held only in process memory, each for ten minutes. They are not written to disk and disappear on restart.
- The token is single-use. The server consumes it before fresh-state checks or any write; concurrent/replayed calls cannot submit it twice.
- The token proves which payload was reviewed, not that a person approved it. Keep the MCP host's write-tool approval enabled and authorize only after reading the complete diff.
- If source configuration changed, preview again. If HA reports equipment blockers, resolve them through normal controls, inspect the state, and make a new proposal.
- A timeout or failed readback after submission may mean HA saved the change. There is no automatic write retry or rollback. Read the room/plan and inspect HA before proposing another change.

## API v2 answers (integration services)

Every `crop_steering` service that answers (`SupportsResponse.ONLY` or `OPTIONAL`) takes three optional fields besides its own. They are documented here once, not on each service in `services.yaml`:

- `api`: `1` or `2`. Without it, or with `1`, the service answers exactly as before. `setup_read` keeps `api_version: 1`.
- `client`: `mcp` or `aigrow`, so the journal can attribute the change.
- `proposal_token`: the reviewed proposal a write carries.

With `api: 2`, a caller that asks for the answer (`return_response`) gets `{api: 2, ok: true, room_id, revision, readback: {status, at}, event_ids, data}`. `data` is the v1 answer. `readback.status` is `verified`, `refused` or `none`, and comes only from the service's own read-back. `event_ids` are the journal events the call recorded.

A refusal is `{api: 2, ok: false, error: {code, message, current_revision?}}`, with `data` kept when the service answered rather than raised. The codes are:

- `stale_revision` (with the current revision)
- `invalid`
- `forbidden`
- `guard_refused`: for example, a Stop all that left something on
- `unavailable`

A caller that does not ask for the answer gets the error raised, as in v1, so a refused write never looks like success. The source of truth is `custom_components/crop_steering/api_v2.py`.

## Verification and upstream references

The package uses official `@modelcontextprotocol/server` and `@modelcontextprotocol/client` **2.0.0**, verified from the npm registry on 2026-09-08, with an exact dependency lockfile. The official SDK identifies v2 as the stable release line and provides the local `serveStdio` transport. See the [SDK documentation](https://ts.sdk.modelcontextprotocol.io/v2/), [stdio client handshake documentation](https://ts.sdk.modelcontextprotocol.io/v2/clients/connect), and [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/).

`npm test` compiles strict TypeScript and launches real server subprocesses using the official SDK stdio client. The isolated HTTP mock tests cover initialize, tool listing/calls, all read tools, every preview kind, exact proposal saves and readback (revision + 1, or an empty re-preview diff and `missing` for presets and copies), the service allowlist (no `intent_submit`, `pump_*` or `calibration_*`), disabled writes, strict schemas, room isolation, stale revisions and sizing, HA safety rejections, plan validation/status/bounds, concurrent replay, timeout uncertainty, redirection rejection, credential redaction, response limits, expiry, process restart, legacy descriptor and null mapping compatibility. All test HTTP listeners bind only to loopback and use a dummy token; they do not operate live equipment.

An official SDK client has also initialized this server and called all six read tools against an existing two-room Home Assistant installation, with writes disabled. This establishes live read compatibility; configuration-write and third-party LLM-host verification are separate checks.
