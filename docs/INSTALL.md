# Installation, upgrade and rollback

[Try the isolated demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1) · [Complete user guide](USER_GUIDE.md) · [Tested features and limits](FEATURE_MATRIX.md)

## What gets installed

| Component                 | Where it runs                                                       | Purpose                                                                                                                                |
| ------------------------- | ------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| Crop Steering integration | Home Assistant custom integration                                   | Room/zone configuration, entities, stored plans, reviewed APIs and the native sidebar workspace.                                       |
| Crop Steering Controller  | One existing/new Supervisor app, or a separately managed controller | Reads the configuration and sensors, makes irrigation decisions and sequences equipment.                                               |
| Optional MCP server       | Your LLM client's local machine, over stdio                         | Reads scoped information and supports explicitly reviewed setup/draft-plan proposals. It is not required for the dashboard/controller. |

Install the integration and controller together. HACS, the HA integration config flow and the Supervisor app store are separate steps. The guided links open those screens; they cannot pair devices, prove flow or bypass HA confirmations.

## Requirements

- Home Assistant 2024.10 or newer. Python requirements follow your HA version; HA 2024.10 requires Python 3.12.
- HACS for the guided integration download, or access to copy a custom integration manually.
- Home Assistant OS/Supervised with the app store for the guided controller install. Container/Core users must run the companion controller separately; a true one-click controller install is not available there.
- An HA administrator account for Rooms & setup and its configuration services.
- Existing HA entities for the actual pump and zone valves, fresh VWC/EC probes, feed-water probes and any configured interlocks. This integration maps entities; it does not provision sensor firmware or pair devices.

Install the integration and the controller app at the same version: from 2.21.0 both carry one version number, and each release names the pair in the [changelog](../CHANGELOG.md). The public demo uses isolated synthetic data; its sample plans and records are not installation settings.

## Guided installation

1. [Open this repository in HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=JakeTheRabbit&repository=HA-Irrigation-Strategy&category=integration). Download the integration and restart HA. If HACS is absent, install HACS first or use the manual path below.
2. [Start the Crop Steering config flow](https://my.home-assistant.io/redirect/config_flow_start/?domain=crop_steering). Select manual setup for a new installation. Enter a room name and initial zone count. Existing environment-import installations remain supported.
3. [Add the app repository](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJakeTheRabbit%2FHA-Irrigation-Strategy). In the app store, install **Crop Steering Controller**. Keep the affected engine enable flags OFF, review the app options, then start the app so it can publish its heartbeat and discover configuration. Supervisor supplies the internal HA token; do not paste a token into a repository file.
4. Open **Crop Steering** in the HA sidebar. The integration serves its bundled dashboard automatically; no manual dashboard YAML or custom Lovelace card installation is required. The controller's ingress can also serve the same dashboard. In supported HA shells, use the workspace's **Home Assistant** or house button to reopen the temporarily collapsed HA sidebar; see [sidebar behavior](HA_SIDEBAR.md).
5. In **Rooms & setup**, select or add a room. Name its zones. Search HA entities by friendly name or ID and check their units/current states while mapping valves, VWC probes, EC probes and room equipment. Multiple probes can be selected per zone. Every zone needs its valve. Under **Shared room hardware**, say how the room is plumbed: a tent with one smart plug or solenoid is *Zone valves only* and maps that switch as the zone's valve and nothing else; a room where water only flows while a pump runs is *A pump, then zone valves* and must have the pump chosen. The switches have to match the answer, and the controller holds a room whose switches stop matching rather than watering it with no pump.
6. Enter substrate litres **per plant**, plant count, drippers per plant and each dripper's L/hour. Catch-test actual output using **Insights → Calibration**. The calculator proposes a value; it does not write it automatically.
7. Choose **Review configuration**, then **Save configuration**. Setup validates entity domains, moisture/EC units, duplicate valve assignments, revision conflicts and readable OFF states of the affected engine/equipment. A saved configuration and controller acknowledgement are shown separately; wait for **Mapping acknowledged** instead of assuming a save has already reached the controller.

Steps 2 and 3 can be done in either order from integration 2.19.2 with controller 0.16.2. A controller started before any room exists waits, invents no zones, and picks the room up by itself within a minute of setup finishing; no restart is needed. On earlier versions that order produced errors for zones that did not exist and a Repairs card asking for a kill-switch helper: **do not create that helper**, update instead.

See the [step-by-step mapping workflow](USER_GUIDE.md#set-up-rooms-zones-and-sensors) for field meanings, revision conflicts and controller adoption.

Room and zone removal means archive. Archived IDs remain reserved, so restoring or adding a zone cannot silently point an old recipe at different hardware. Changing names preserves entity identity. The default room retains its legacy IDs.

## Verify the installation

With engines still off, confirm each room loads in the sidebar, the selected room has a current controller heartbeat, mappings show **Mapping acknowledged**, and **Sensors** shows the intended entities/units. Open **Irrigation plan → Today** and verify the existing values. An upgrade should retain each room's current values, zone identities and plant/dripper sizing.

Open **Overview** and a zone detail panel. A missing optional tank mapping may remain **Not mapped**; a missing required control sensor or controller acknowledgement needs resolution before commissioning. **Last irrigation** is an event record and may legitimately be absent on a new installation. Do not generate a physical shot just to fill that display.

The documented live evidence covers an in-place upgrade of an existing two-room installation. A completely blank installation, physical delivery and a complete live plan-boundary handoff remain separate commissioning checks. The [feature matrix](FEATURE_MATRIX.md) identifies those limits.

## Before enabling irrigation

In **Sensors**, verify that mapped values are available, fresh and in the expected units. Distinguish pore/substrate EC from feed-water EC. Set room lights-on/off hours and review the zone's water limits, shot sizes and emergency floor. Check controller heartbeat and any holds. Validate pump/valve physical operation and delivered water on site before enabling an engine. HA state readback alone does not prove water flow.

Start with a reviewed manual configuration, or create a draft in **Irrigation plan → Schedule**, preview it, save it and arm it. A plan becomes eligible at the next lights-on boundary. Arming does not switch on the engine. An unsupported/old controller cannot activate a plan.

## Manual integration install

Copy the entire `custom_components/crop_steering` directory into HA's `/config/custom_components/crop_steering` and restart HA. Include its `www/dashboard.html` file. Then follow steps 2-7 above. Do not copy this repository wholesale into `/config`; historical facility examples are not your configuration.

Developers build the dashboard using `npm ci --prefix frontend` then `npm run build --prefix frontend`. Packaging generates identical self-contained HTML in the integration, controller and web distribution folders. Compiled HTML is a deliverable, not the editing source.

## Upgrading an existing installation

Update an existing controller in place from this repository. The old `JakeTheRabbit/f2-control` mirror no longer receives releases; a controller installed from it moves once, as described in [Moving a controller installed from f2-control](#moving-a-controller-installed-from-f2-control). Never run two controllers against one room: each app has its own identity and runtime data, and both would drive the same pump and valves.

1. Back up HA, the controller's persistent data and existing setpoints. Export grow plans if available. Record which engines are enabled.
2. Turn the affected engines off and wait for the pump, mainline and valves to be OFF. Stop the existing controller while replacing software.
3. Refresh your existing app repository and update that controller in place to **0.16.2**. After updating from 0.13.x, turn the engine kill switch off and on once so the controller can accept and save the current setup; later restarts resume by themselves. A restart alone does not rebuild an old image. Do not install a second copy or enable automatic startup during the upgrade.
4. Download integration **2.19.2** through HACS and restart HA. Confirm every Crop Steering room finishes loading. Version 2.13.1 fixed the concurrent sidebar-registration error discovered with two rooms during the live upgrade.
5. Start the controller with engines still off. Verify its version, fresh heartbeat, both room descriptors, sensor readings, setup acknowledgement and grow-plan capability. Compare current setpoints and pot/dripper sizing with the backup.
6. Restore the engines' previous enabled states after these checks. An upgrade does not require arming a recipe or replacing existing values with defaults.

If an update is missing from the app store, refresh the repository information first. Use Update for published versions or Rebuild for a local source installation. HACS and the app store update separate components.

### Moving a controller installed from f2-control

The controller used to be mirrored to `JakeTheRabbit/f2-control`. That mirror is retired; this repository is the only source. Supervisor names an app after the repository it came from (`4d457e60_f2_control` from the mirror, `6db5faba_f2_control` from here), so the move is a one-time reinstall that carries the runtime state across:

1. Add this repository to the app store and install **Crop Steering Controller** from it. Do not start it.
2. Copy the old app's Configuration into the new app: every option, including the Cloudflare fields.
3. Turn every engine kill switch off and wait until the pump, mainline and valves read OFF.
4. Stop the old app and turn off its Start on boot and Watchdog.
5. Copy `state.json` from the old app's data folder to the new one. It holds each zone's phase, today's counters, the accepted setup revision and what Auto Setpoints has learned; without it the controller starts learning again and waits for setup to be accepted. On HA OS, from an SSH terminal with Docker access: `docker run --rm -v /mnt/data/supervisor/apps/data:/d alpine cp -p /d/4d457e60_f2_control/state.json /d/6db5faba_f2_control/state.json` (older Supervisor versions use `addons/data`).
6. Start the new app, turn on its Start on boot and Watchdog, and check its log, version, heartbeat and setup acceptance before turning the engines back on.
7. After a day of normal running, uninstall the old app and remove the `f2-control` repository.

The existing app slug `f2_control` and entity IDs are deliberately stable. Existing environment mapping remains supported. Older dashboard bookmarks retain room context and redirect to the new routes. After upgrade, verify the room descriptor and controller heartbeat, setup acknowledgement and plan capability before enabling control.

## Optional tank display mappings

In **Rooms & setup → Shared room hardware**, map tank fill level to a percentage sensor, tank EC to mS/cm or dS/m, tank pH to pH, and tank temperature to a temperature sensor. These tank-quality display mappings do not enable feed-water safety gates. Choose a fill valve or binary sensor for filling status and a timestamp sensor or full date-and-time helper for **Last recorded tank fill**. Use an actual recorded fill event; an automation trigger time or sensor `last_changed` is not proof of filling. Shared tanks can be explicitly mapped to more than one room. The [tank mapping table](USER_GUIDE.md#tank-and-pump-display) lists the exact labels and configuration keys. A recorded fill can be operator-confirmed or float-confirmed according to its producer; it is not proof that dosing finished. Filling status must represent the fill valve or a genuine fill-active signal, not a mode-enable or dosing-lock helper.

Save setup with the affected engines and irrigation equipment off, then verify the readings in **Overview** before restoring the previous engine state. Missing mappings remain labelled; an unavailable pump is never displayed as off. Existing controllers must be updated to publish irrigation timestamps with a timezone offset.

## Optional LLM / MCP connection

Normal installation does not require an LLM. The optional MCP package requires Node.js 22 or newer and a client that can launch a local stdio process. To connect one, follow [MCP.md](MCP.md) on the client machine after the HA integration is reachable. The documented server uses local stdio with locally configured `HA_URL` and `HA_TOKEN`. It is read-only by default. Setup changes or draft-plan saves require `CROP_STEERING_ALLOW_WRITES=true`, followed by exact proposal review. `preview_setup`/`preview_plan` produce a short-lived, single-use token; `apply_proposal` accepts only that token and its matching room/revision, then reads back the result. Follow the server guide for client configuration and validation evidence.

This is separate from broad third-party HA MCP connectors. It does not expose arbitrary services, engine enabling, valve commands or grow-plan activation. Verify actual HA responses and setup acknowledgement after an approved configuration change.

## Restore a prior version

Turn affected engines off and confirm physical equipment is off. Restore the prior integration/controller versions and their matching persistent-state backup. An active grow plan uses a durable required-plan latch: do not downgrade the controller while expecting it to understand a newer active plan. Disarm and verify the boundary handoff to manual targets first, or restore a complete known-good backup with engines off.

## If the sidebar or setup is missing

Restart HA after installing the integration. Check integration logs and that `custom_components/crop_steering/www/dashboard.html` exists. Missing workspace services mean the integration is older than the dashboard. Unsupported activation means the controller has not published the new capability heartbeat. Refresh the page after upgrading both components.

The installation links follow the official [Home Assistant app repository format](https://developers.home-assistant.io/docs/apps/repository/) and [configuration flow mechanism](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/). Home Assistant's [frontend theme configuration](https://www.home-assistant.io/integrations/frontend/) supplies inherited theme colors.
