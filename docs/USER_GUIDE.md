# User guide

Use **Overview** to check a room and **Irrigation plan** for **Today** and **Schedule**. Today shows the current zone targets; Schedule edits the dated plan. Select the room before editing; zone numbers belong to that room.

Existing `#/strategy` and `#/grow-plan` bookmarks open **Irrigation plan → Today** and **Schedule**.

New installation? Start with [Install, upgrade and rollback](INSTALL.md). To try the interface without connecting equipment, open the [interactive demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1).

## What each action changes

| Action                        | Where the change goes                                                  |
| ----------------------------- | ---------------------------------------------------------------------- |
| Edit manual fields/graph      | Local draft until reviewed and applied.                                |
| Apply reviewed manual changes | Existing HA setpoint entities; inspect readback.                       |
| Review & save a grow plan     | HA's stored draft plan; separate from arming.                          |
| Arm plan                      | Requests the eligible boundary activation; does not enable the engine. |
| Save a library recipe         | This browser/site/room library; no HA write.                           |
| Save a run record             | Run metadata and its captured reference; no irrigation activation.     |
| Save configuration            | HA room/zone setup; wait for controller acknowledgement.               |

## Try the demo

The demo is an isolated software demonstration. Its readings, history, example plans and run records are synthetic; they are not a recommended configuration or evidence from a real grow. A demo tab cannot connect to live Home Assistant.

1. Open **Overview** and switch rooms. Inspect today's grow-day timeline, the zone states and the tank.
2. Open **Irrigation plan → Today**, select a zone and choose **P3**. Edit its emergency floor and compare the moving draft line with the saved reference. Use the review dialog to inspect changes.
3. Open **Irrigation plan → Schedule**. Select a zone and day/week, inspect its endpoint profile and change the steering balance. Compare the schedule and curve.
4. Expand **Recipe library** to inspect **Demo • steady schedule** or **Demo • week-by-week changes**, or save your own copy. Samples are added only when that demo room has no stored library yet. Loading affects a local draft; the normal review/save remains separate.
5. Open **Compare runs**. Select the illustrative current/previous runs and change the history range or target reference. The generated history remains labelled as demo data.
6. Open **Rooms & setup** to try entity search, room/zone names and mapping review. Demo actions do not call your HA server.

A production recipe library starts empty. Demo recipes are interface examples and are stored separately from production libraries. Existing demo libraries, including deliberately empty or corrupt ones, are left unchanged.

Use **Settings → Sample workspace → Reset demo session…** and review the confirmation to restore the sample rooms, readings, run records and planner drafts. This discards unsaved demo work and session changes to runs/room settings. All saved recipe libraries and live connection data are retained; reset does not restore recipes you deliberately removed. Export any session work you want to keep first.

## Read a room

**Overview** is the room now: alerts, today's totals, the grow-day timeline, each zone's state and readings, and the tank. A zone row opens its detail panel. **Zones** adds search, a card layout, water delivered per zone and per plant, and water use over the grow. The latest controller records open beside any page from the top bar.

| Indicator                     | Meaning                                                                                                                                                             |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Room status line              | At the top of every page: watering, holding and why, or not watering and what to do, with the age of the controller's last report.                                  |
| Zone scheduling               | Whether this zone is eligible for scheduling; it does not mean its valve is currently open.                                                                         |
| Controller status and phase   | The controller's reported operating state and P0/P1/P2/P3 phase. Inspect any hold or unavailable status before making changes.                                      |
| Valve on/off                  | The state of this zone's explicitly mapped switch. It does not establish physical flow.                                                                             |
| Last irrigation               | A recorded controller event timestamp, with relative age and date/time. It is not inferred from sensor updates. Missing/invalid timestamps remain **Not reported**. |
| VWC and root-zone EC          | The mapped substrate measurements. Their units and sensor availability matter independently.                                                                        |
| Water delivered this grow-day | On **Zones**: controller-recorded delivery estimates since the room's lights-on boundary.                                                                           |
| Water use                     | On **Zones**: litres per zone today, this week, since the grow start and estimated for the whole grow, with a bar for each grow week.                               |

**Water use** counts grow-days from lights-on to lights-on. It reads Home Assistant's long-term statistics, which Home Assistant keeps indefinitely; opened outside Home Assistant it can only read recorded history, as far back as the recorder keeps it. The grow start is the zone's grow plan start date when the plan is armed or has been saved. Without one it is inferred: the first day with water after at least five grow-days without any. The panel says which. A day Home Assistant did not record is flagged, never counted as zero.

To move a zone to another phase, open it from **Zones** or **Overview** and pick one under **Phase**. After the review, the controller moves it within a minute and carries on from there: lights-off still moves it to P3 and lights-on to P0. Today's water and shot counts stay.

**Settings → Watering** switches the room's engine switch ("Engine Enabled" in Home Assistant on a room made by the setup wizard), and like zone scheduling it asks for a review first. With watering off the controller opens no valve in the room and a shot already running stops within a few seconds; it keeps reading the probes and following the phases. A new room starts with watering off. When a room is not watering, the status line at the top of every page says which switch stopped it and links here when this is the one. Pausing a zone stops a shot already running in it within a few seconds too, and a paused zone gets no water at all, not even a rescue shot. Neither is an emergency stop: use the installation's established physical shutdown procedure for an emergency.

### Tank and pump display

Choose **Map sensors** on the tank panel, or open **Rooms & setup → Shared room hardware**. These are explicit mappings; the dashboard does not guess that a room-temperature or feed-water probe is a tank probe.

| Setup label             | Configuration key         | Select                                                                                                                |
| ----------------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Room pump               | `pump_switch`             | The room pump's actual HA switch. The controller descriptor publishes this as `pump`.                                 |
| Tank fill level (%)     | `water_level_sensor`      | A percentage sensor, 0-100. A litres value is not a percentage.                                                       |
| Tank EC (display)       | `tank_ec_sensor`          | A tank conductivity sensor in mS/cm or dS/m accepted by setup.                                                        |
| Tank pH (display)       | `tank_ph_sensor`          | A pH sensor.                                                                                                          |
| Tank temperature        | `tank_temperature_sensor` | A tank-water temperature sensor in °C, °F or K; its unit is retained.                                                 |
| Tank filling status     | `tank_fill_entity`        | A fill-valve switch or binary sensor whose on/off state represents fill activity.                                     |
| Last recorded tank fill | `tank_last_fill_sensor`   | A timestamp sensor with a dated, timezone-aware state, or an `input_datetime` helper with both date and time enabled. |

**Tank EC (display)** and **Tank pH (display)** only populate the panel. **Feed-water EC** and **Feed-water pH** are separate mappings used by configured control gates. Mapping a tank display does not enable those gates or nutrient dosing.

**Last recorded fill** has the meaning supplied by your existing recording automation: for example, a verified full-float event or an operator's explicit “mark filled” action. A full date/time helper uses its timestamp attribute; a sensor's `last_changed`, an automation's `last_triggered`, a fill-mode enable flag and a dosing interlock are not equivalent to a fill record. The panel does not create a fill-recording automation for you.

Use your own installation's recording source. Some systems record an operator confirmation; others record a full-float event or the end of a fill/dose workflow. The label intentionally says **recorded fill** because those meanings differ. A percentage source may itself be an estimate; drawing it as a tank does not turn it into a measured level. Tank readings and switch reports do not prove dose completion, water quality suitability or physical delivery.

Unmapped inputs show **Not mapped**; invalid readings show **Unavailable**, **Check units** or **Out of range**. An unknown pump is not shown as off and an unknown tank is not drawn empty. When disconnected, the panel identifies retained readings as last received.

## Irrigation plan → Today

When no schedule owns the room, Today lets you edit the current targets using the steps below. An active schedule replaces those controls with its effective read-only targets and graph; fallback manual inputs are hidden. If the required schedule snapshot is missing or stale, those targets remain unavailable rather than being replaced by manual values.

1. Select a room, open **Irrigation plan → Today**, then select a zone. Choose **Room settings** for shared timing/configuration.
2. Use the phase selector to keep the relevant controls beside the whole-day VWC/EC preview. On a narrow screen, expand the preview when needed.
3. Edit a numeric field or a supported graph handle. Both edit the same local draft and respect the HA field's limits and step. The saved reference remains visible for comparison.
4. Check the parameter's name, unit, selected legacy mode, draft line and water estimate. **Show targets for both steering modes** exposes the other mode's stored references when available.
5. Select **Review changes**, inspect every before/after value, then confirm application. Only this application step sends the reviewed values to HA. Readback errors and unapplied values remain visible; do not assume a partially failed batch succeeded.

Room changes can be previewed against a selected zone. A zone-specific value takes precedence over a room fallback where the controller supports it. Missing or invalid inputs remain missing/invalid instead of becoming an invented curve.

When a schedule owns the room, use **Irrigation plan → Schedule** to inspect its dated targets and state. Use the normal disarm/handoff workflow and wait for draft status before returning to editable manual targets in Today. Export or deliberately discard drafts before leaving; a navigation warning is not an automatic backup.

## Irrigation plan → Schedule

The planner schedules user-defined profiles by zone and grow day. The balance slider interpolates between the profile's explicit vegetative and generative endpoints; it does not select a built-in agronomic prescription. Equal endpoints intentionally produce equal targets at every slider position. Pot/dripper sizing affects water estimates, not the suitability of the endpoint values.

1. Open **Irrigation plan → Schedule → Endpoint profiles**. Inspect both endpoints and select the correct **Zone limits**. Duplicate a profile when you need an independent copy. A shared profile affects all schedule blocks referring to it.
2. Open **Schedule & curve**. Select a zone and set **Zone grow start date**. Each zone can have its own start date.
3. Select a day or week in the overview. Assign its **Endpoint profile** and **Steering balance**. Days 1-366 are supported. Range edits preserve surrounding assignments by splitting existing blocks.
4. Inspect **Zone schedule blocks** for coverage. Fill missing days and resolve overlap, parameter or zone-assignment errors.
5. Inspect the selected day's curve and water preview. Graph handles edit the selected profile as described on screen, which can affect its other schedule references.
6. Choose **Review & save** to validate and persist the draft in HA. **Validate preview** checks an unchanged stored draft. **Export** downloads a portable plan; **Reload stored plan** retrieves the stored revision once local edits are saved or discarded.
7. If you intend the controller to use the plan, review **Arm plan** separately. The controller must report support. Activation occurs at the eligible local lights-on boundary; arming does not enable the engine or pump.

An active/armed plan cannot be edited as a draft. **Disarm plan** requests the normal boundary handoff back to manual targets; wait for **draft** status before editing. The UI reports unsupported controllers, stale required snapshots and unfinished handoffs instead of claiming activation succeeded.

Saving, arming and disarming a plan need a Home Assistant administrator login. Any other login can open the plan and its previews, and is refused when it tries to change them.

After adding or archiving zones in setup, use **Update zones from setup** in a draft plan. It preserves existing active-zone schedules, removes archived assignments, and initializes new zones from their current settings. Export the previous plan first if you need those removed assignments.

### Recipe library

A library item is a reusable copy, separate from the HA plan currently controlling the room.

- **Save current as recipe** creates a named browser copy with optional notes/source URL.
- **Import recipe file** accepts the supported plan export format, validates it and lets you name the library copy.
- **Preview recipe** shows its zones, retained current start dates, schedule spans and inspectable profiles. **Load into local draft** requires the exact current active-zone IDs and preserves current start dates. Replacing unsaved planner work requires explicit acknowledgement.
- Loading is unavailable while active, armed, busy or disconnected. It does not save or arm the plan.
- **Export recipe** downloads a copy. **Remove recipe** asks for confirmation and removes only the browser copy.

Libraries are isolated by site, browser, room and demo/live mode. They are not a shared HA database. Limits are 20 recipes per room, 500 KB per plan and 2 MB per library. Export important copies before clearing browser data or moving to another browser. Corrupt data is retained with a recovery-download action; storage denial, quota and stale-tab conflicts are reported rather than silently overwritten. See [Recipe library](RECIPE_LIBRARY.md).

## Understand the graphs and water figures

| View                          | What it shows                                                                                                            | What it does not establish                                                                  |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| Today/Schedule VWC-EC curve   | Configured targets, phase references and supported timing, with local draft changes where applicable.                    | Exact future shot times, uptake, runoff or EC accumulation.                                 |
| Insights history              | Retained HA Recorder measurements on separate VWC and EC axes.                                                           | Measurements from periods Recorder did not retain.                                          |
| Water delivered this grow-day | The controller's recorded estimate from its configured flow and elapsed shot runtime, including accounted partial shots. | Independent meter readings, uniform distribution, plant uptake or external irrigation.      |
| Water use estimate            | Water used so far plus the last 7 full grow-days' average for every grow-day left in the grow plan.                      | A forecast of plant uptake, or a total for a grow whose plan length is unknown.             |
| Average mL per plant          | Zone estimated water divided by configured plant count.                                                                  | A measurement from each emitter.                                                            |
| Total substrate capacity      | Substrate volume per plant multiplied by plant count.                                                                    | Water delivered or water retained.                                                          |
| Runtime/phase water preview   | A conditional calculation from supplied settings, showing requested versus effective runtime and caps.                   | A guaranteed daily total; feedback-dependent maintenance/emergency shot counts are unknown. |

The updated planning curve uses separate axes for VWC (%) and root-zone EC, joining configured references across lights-off and overnight to the next lights-on. VWC joins the daytime reference to the relative dryback endpoint; the P3 emergency floor remains a separate protection reference. Dashed EC interpolates from the last daytime anchor to the next morning anchor. There is no P3 EC setpoint or prediction of the physical EC/salt trajectory. Missing values remain gaps rather than being filled with guessed readings. A graph handle changes configuration in a draft, not physical equipment.

Use **Insights → Calibration** to enter an actual catch-test result and inspect the proposed dripper flow. The calculator does not apply that proposal automatically. Historical estimates are not retroactively corrected when flow settings change. For detailed software semantics, see [Steering and planning](GROW_PLANS.md).

## Compare recorded runs

1. Open **Compare runs** and select the room and zone. Date-range history works without a registered run.
2. In **Run records**, choose **Add run**, enter the actual run name/start date and optional end date, then **Save run record**. This saves metadata and a timestamped reference configuration; it does not arm irrigation.
3. Select the current and, optionally, previous run. Previous readings align by grow age and stop at the same elapsed progress as the current run.
4. Select **Day**, **Week · 7 days**, **Calendar month**, **Run to date**, or **Custom dates**. Check the calendar timezone and requested-through time. Use **Refresh history** to advance the window.
5. Choose a **Target reference**: **Current configured daily plan**, **Saved run daily reference**, or **Current phase reference**. Read its capture/source note before comparing it with recorded measurements.
6. Inspect coverage and missing-data notices. **Export metadata** backs up run definitions and reference snapshots, not Recorder readings. Archive/restore controls retain the registered run's identity.

Saving, archiving and importing run records need a Home Assistant administrator login; any login can view them.

Registering last month's run today captures today's reference configuration. It cannot recover last month's setpoints or expired Recorder data. Editing dates preserves the original capture. Current/saved daily target illustrations are references, not an audit of every historical target. Each room supports up to 100 run records; a completed run covers 1-366 inclusive calendar days.

## Set up rooms, zones and sensors

An HA administrator uses **Rooms & setup**. Pair devices and expose their entities in HA first; this workspace maps existing entities.

1. Choose an existing room or **Add room**. Give it a clear name. Names may change without changing its stable identity.
2. Map **Room pump** and **Mainline valve**, then each active zone's valve. Search by friendly name or exact entity ID; inspect the displayed value/unit before selecting.
3. Select one or more VWC and EC probes per zone. **Clear mapping** removes the selected mapping; **Done** closes the picker. Multiple valid readings are combined by the integration; automatic outlier rejection is not provided.
4. Enter plant count, substrate litres **per plant**, drippers **per plant**, and flow in litres/hour **per dripper**. Review existing values instead of replacing them with generic defaults.
5. Map optional room equipment, tank displays and any feed-water safety probes as separate roles. Explicitly map shared equipment only where appropriate; never reuse a zone valve accidentally.
6. Stop affected engines and verify the implicated irrigation equipment is OFF. **Review configuration** shows the changes and blockers; **Save configuration** persists the setup after backend validation.
7. Wait for controller acknowledgement of the saved setup revision. A saved configuration and an adopted configuration are different states. Then verify **Overview**, **Zones** and **Sensors** before restoring the prior scheduling state.

Zone and room removal archives stable IDs. **Restore zone** or **Restore room** reactivates the same identity after review; archived slots are not silently reused for different hardware. Adding/archiving a zone may require updating a draft grow plan's assignments.

## Connection, appearance and supporting pages

The native HA sidebar normally uses your existing HA session. **Settings → Home Assistant connection** also supports an explicit URL and a long-lived access token for a standalone tab; the token is kept for that tab session and is never put in the URL. A hosted HTTPS page may be unable to access a local HTTP HA server because of browser origin/security rules; use the native sidebar for the normal installation.

Inside a compatible same-origin HA shell, the workspace temporarily collapses HA's sidebar. Use **Home Assistant** at the bottom of the workspace navigation, or the house button labelled **Open Home Assistant menu** in the top bar, to reopen HA's menu. Leaving the workspace restores the prior temporary state; it does not change the saved HA sidebar preference. Standalone and unsupported embeddings keep normal navigation. The hide-and-reopen behavior was verified in the actual HA panel on 2.16.0; see [Home Assistant sidebar](HA_SIDEBAR.md) for compatibility limits.

Choose **Settings → Appearance → Home Assistant / system** to inherit the HA theme when embedded on the same origin, or the device theme in standalone mode. **Light** and **Dark** are explicit overrides. Cross-origin embedding cannot read the host theme.

**Sensors** shows values, units, availability and freshness. **Insights** shows coverage, equipment mappings and the local catch-test calculator. **Activity** lists available controller/state records and supports CSV export; it is not an immutable audit of every physical shot. **Help** explains the interface's metrics and limits.

For an existing timed zone hold, Home Assistant exposes the `crop_steering.set_manual_override` action. The action refuses a signed-in user who is not an administrator (automations can still call it); the switch itself follows Home Assistant's own user permissions. Its timeout defaults to 60 minutes and accepts 1-1440 minutes; specify the intended zone and room slug (omit the room for the legacy default room). Clearing the hold is distinct from enabling zone/room scheduling. Turning its switch on directly creates an indefinite hold. See the action's fields in HA and the [entity reference](ENTITIES.md).

## Connect an LLM with MCP

The optional [MCP connection guide](MCP.md) describes the local stdio server, supported clients, token configuration and exact tools. It is separate from the dashboard and does not need to be enabled for normal use.

The server uses `HA_URL` and `HA_TOKEN` from local configuration and starts read-only. Follow [MCP.md](MCP.md) for installation and your client's stdio command; do not paste the token into a chat message.

| Tools                                       | Purpose                                                                                                                |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `list_rooms`                                | Discover real room IDs before selecting a scope.                                                                       |
| `get_room_configuration`, `get_room_status` | Inspect the selected room's mappings/configuration and current state.                                                  |
| `search_candidate_entities`                 | Find existing HA entities for a proposed mapping.                                                                      |
| `get_room_plan`, `get_room_runs`            | Read the room's stored plan and run records.                                                                           |
| `preview_setup`, `preview_plan`             | Prepare an exact setup change or draft-plan save and return its diff, room, revision, expiry and proposal token.       |
| `apply_proposal`                            | Apply only the previously reviewed proposal using its token, room ID and expected revision, then read back the result. |

A practical first request is: “List my rooms, inspect the selected room's mappings and report unavailable sources. Do not apply changes.” For editing, ask the model to prepare a proposal and show its entire diff before requesting approval.

Application is available only when you deliberately configure `CROP_STEERING_ALLOW_WRITES=true`. Proposals expire after ten minutes and are single-use; changed revisions or an expired proposal require a fresh preview/review. Existing-room setup can update names, mappings and sizing; plan writes save drafts only. Backend validation and equipment-OFF requirements still apply to setup.

Review the exact room, entities and revisions. A model's explanation is not evidence that HA accepted a change: inspect the tool's readback, and for setup wait for controller acknowledgement. Do not treat a failed or uncertain apply as permission to regenerate and apply a different proposal automatically.

The MCP server is not a generic HA actuator interface and does not enable engines, open valves or activate plans. Keep credentials in the local client/server configuration described in that guide, not in prompts, screenshots or repository files. Existing broadly privileged HA MCP integrations are separate products with different permissions.

## When something does not look right

| Symptom                                        | Next step                                                                                                                                                        |
| ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| No rooms or missing workspace services         | Verify the integration loaded, the controller version matches, and the current HA account can access the entities/services. Refresh after upgrading.             |
| Tank **Not mapped**                            | Set that exact optional display mapping. A similarly named feed or ambient probe is not an implicit fallback.                                                    |
| Last irrigation/fill is missing                | Check the event-producing source and its dated timestamp format. A state update time cannot substitute for the event.                                            |
| A reading shows **Check units**                | Inspect the actual HA unit and choose/repair the appropriate entity. Do not relabel an unrelated quantity to pass validation.                                    |
| Setup is saved but adoption is pending         | Inspect heartbeat/setup blockers; keep affected engines off until the controller acknowledges the revision.                                                      |
| Slider appears to do nothing                   | Inspect both selected endpoint columns. Equal endpoints are deliberately equal at every balance.                                                                 |
| Today is read-only                             | Inspect the schedule or connection state. Active schedules show effective read-only targets; use Schedule and the normal boundary handoff before manual editing. |
| Cannot load a recipe                           | Check active-zone IDs, current limits, plan state, connection and explicit replacement acknowledgement.                                                          |
| Comparison is blank                            | Check selected run/zone, recorded sensor IDs, dates, Recorder retention and coverage notices. Registering metadata cannot recreate readings.                     |
| A pause was confirmed but equipment remains on | Pause affects scheduling. Inspect the active shot and use the site's established physical shutdown procedure if necessary.                                       |

For source/test evidence and outstanding commissioning limits, use the [feature matrix](FEATURE_MATRIX.md) and [troubleshooting guide](troubleshooting.md). Software validation does not prove physical delivery or a complete live recipe handoff.
