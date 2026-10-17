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
- Home Assistant OS/Supervised with the app store for the guided controller install. Container/Core users run the controller as a Docker container instead; see [Home Assistant Container or Core](#home-assistant-container-or-core).
- An HA administrator account for Rooms & setup and its configuration services.
- Existing HA entities for the actual pump and zone valves, fresh VWC/EC probes, feed-water probes and any configured interlocks. This integration maps entities; it does not provision sensor firmware or pair devices.

Install the integration and the controller app at the same version: from 2.21.0 both carry one version number, and each release names the pair in the [changelog](../CHANGELOG.md). The public demo uses isolated synthetic data; its sample plans and records are not installation settings.

## Guided installation

1. [Open this repository in HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=JakeTheRabbit&repository=HA-Irrigation-Strategy&category=integration). Download the integration and restart HA. If HACS is absent, install HACS first or use the manual path below.
2. [Start the Crop Steering config flow](https://my.home-assistant.io/redirect/config_flow_start/?domain=crop_steering). Select manual setup for a new installation. Enter a room name and initial zone count. Existing environment-import installations remain supported.
3. [Add the app repository](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FJakeTheRabbit%2FHA-Irrigation-Strategy). In the app store, install **Crop Steering Controller**. Keep the affected engine enable flags OFF, review the app options, then start the app so it can publish its heartbeat and discover configuration. From then on it starts with the host (**Start on boot** is on unless you turn it off); turn on **Watchdog** as well, so Supervisor restarts it if it stops. Supervisor supplies the internal HA token; do not paste a token into a repository file.
4. Open **Crop Steering** in the HA sidebar. The integration serves its bundled dashboard automatically; no manual dashboard YAML or custom Lovelace card installation is required. The controller's ingress can also serve the same dashboard. In supported HA shells, use the workspace's **Home Assistant** or house button to reopen the temporarily collapsed HA sidebar; see [sidebar behavior](HA_SIDEBAR.md).
5. In **Rooms & setup**, select or add a room. Name its zones. Search HA entities by friendly name or ID and check their units/current states while mapping valves, VWC probes, EC probes and room equipment. Multiple probes can be selected per zone. Every zone needs its valve. Under **Shared room hardware**, say how the room is plumbed: a tent with one smart plug or solenoid is *Zone valves only* and maps that switch as the zone's valve and nothing else; a room where water only flows while a pump runs is *A pump, then zone valves* and must have the pump chosen. The switches have to match the answer, and the controller holds a room whose switches stop matching rather than watering it with no pump.
6. Enter substrate litres **per plant**, plant count, drippers per plant and each dripper's L/hour. Catch-test actual output using **Insights → Calibration**. The calculator proposes a value; it does not write it automatically.
7. Choose **Review configuration**, then **Save configuration**. Setup validates entity domains, moisture/EC units, duplicate valve assignments, revision conflicts and readable OFF states of the affected engine/equipment. A saved configuration and controller acknowledgement are shown separately; wait for **Mapping acknowledged** instead of assuming a save has already reached the controller.

Steps 2 and 3 can be done in either order. A controller started before any room exists waits, invents no zones, and picks the room up by itself within a minute of setup finishing; no restart is needed. On earlier versions that order produced errors for zones that did not exist and a Repairs card asking for a kill-switch helper: **do not create that helper**, update instead.

See the [step-by-step mapping workflow](USER_GUIDE.md#setup) for field meanings, revision conflicts and controller adoption.

Room and zone removal means archive. Archived IDs remain reserved, so restoring or adding a zone cannot silently point an old recipe at different hardware. Changing names preserves entity identity. The default room retains its legacy IDs.

## Verify the installation

With engines still off, confirm each room loads in the sidebar, the selected room has a current controller heartbeat, mappings show **Mapping acknowledged**, and **Equipment › Probes** shows the intended entities/units. Open **Irrigation → Current day** and verify the existing values. An upgrade should retain each room's current values, zone identities and plant/dripper sizing.

Open **Overview** and a zone detail panel. A missing optional tank mapping may remain **Not mapped**; a missing required control sensor or controller acknowledgement needs resolution before commissioning. **Last irrigation** is an event record and may legitimately be absent on a new installation. Do not generate a physical shot just to fill that display.

The documented live evidence covers an in-place upgrade of an existing two-room installation. A completely blank installation, physical delivery and a complete live plan-boundary handoff remain separate commissioning checks. The [feature matrix](FEATURE_MATRIX.md) identifies those limits.

## Before enabling irrigation

In **Sensors**, verify that mapped values are available, fresh and in the expected units. Distinguish pore/substrate EC from feed-water EC. Set room lights-on/off hours and review the zone's water limits, shot sizes and emergency floor. Check controller heartbeat and any holds. Validate pump/valve physical operation and delivered water on site before enabling an engine. HA state readback alone does not prove water flow.

Start with a reviewed manual configuration, or create a draft in **Irrigation → Calendar**, preview it, save it and arm it. A plan becomes eligible at the next lights-on boundary. Arming does not switch on the engine. An unsupported/old controller cannot activate a plan.

## Home Assistant Container or Core

Without the Supervisor there is no app store, so the controller runs as its own Docker container, from the published image `ghcr.io/jaketherabbit/crop-steering-controller`. It is the same controller, built from the same Dockerfile, as the app. The integration, the sidebar dashboard and setup are exactly as above.

**You need:** Docker with Compose v2 on an amd64 or arm64 machine that can reach Home Assistant over the network, this repository's [`docker-compose.yml`](../docker-compose.yml) (the file alone is enough), and a Home Assistant **administrator** account, because the controller publishes its status entities and only administrators may. The image is published for amd64 and arm64 only; on armv7, check out the release tag of your integration and replace the compose file's `image:` line with `build: {context: addons/f2_control}`.

1. Install the integration and add a room (steps 1, 2 and 4-7 of the guided installation). Leave every room's watering off.
2. In Home Assistant, sign in as an administrator, open your profile → **Security** → **Long-lived access tokens** → **Create token**. Name it "Crop Steering controller" and copy it.
3. Next to `docker-compose.yml`, create `ha_token.txt` holding only the token, and a `.env` file holding `CONTROLLER_VERSION=` the version of the integration you installed (exactly as HACS shows it; the controller and the integration carry one version number, and compose refuses to start without it) and `HA_URL=` Home Assistant's own address on your network, for example `HA_URL=http://<home-assistant-ip>:8123` (`/api` is added for you). Use its IP address: a `.local` name rarely resolves inside a container, and the log then says the host name does not resolve. Use the address and port Home Assistant itself listens on, not a reverse proxy, a tunnel or a public address: a proxy can refuse requests Home Assistant would accept, and the controller has to treat a refusal as a bad token (see **Wrong token and IP bans**). Both files stay out of version control. The token is read from the file as a Docker secret, because anyone who can run `docker inspect` can read an environment variable.
4. Run `docker compose up -d`. The compose file's `restart: unless-stopped` starts the controller again whenever Docker starts, as **Start on boot** does for the app; keep it, or a host restart leaves your rooms unwatered until someone starts the controller.
5. Check `docker compose logs -f crop-steering-controller`. You should see `runtime: container`, `base: http://…/api`, `token: HA_TOKEN_FILE`, a `timezone:` line matching Home Assistant, and no `HTTP 401`. If Home Assistant rejects the token, or the token's user is not an administrator, the controller says so in the log before it touches anything, and then **waits without sending anything more**: it never retries a token Home Assistant has refused, so it cannot get this machine banned. (The one exception is a shot or dose the last run left unfinished; see **Wrong token and IP bans**.) Put the right token in `ha_token.txt` and it starts again by itself within 30 seconds; if it does not (an editor that saves a new file in its place leaves the container seeing the old one), run `docker compose restart`. If you changed `.env` instead, run `docker compose up -d`: a restart alone keeps the old environment.
6. Continue at [Verify the installation](#verify-the-installation): fresh heartbeat, **Mapping acknowledged**, sensors in the expected units.

**Never run the container and the app against the same room**: both would drive the same pump and valves. Moving from the app to a container (for example, leaving HA OS): turn watering off, take a backup of the app (**Settings → System → Backups**), then **stop and uninstall the app first**. Uninstalling deletes the app's data folder. Copying its files into the container's volume is optional, as the container starts safely without them: to keep its counters, take `state.json`, plus `dosing_state.json` and `jev_*` files if present, from the backup. Recreate any non-default app options as `F2_OPT_<OPTION>` lines in the compose file, or copy the app's `options.json` into the volume too (the app wrote it, so it passes the container's checks as it is).

**Time zone.** By default the controller follows Home Assistant's time zone. If it cannot read that zone from Home Assistant within 5 minutes it stops with `could not read Home Assistant's time zone` rather than run on UTC; set `TZ` in `.env` to fix it. If you set `TZ`, it must be a real zone name (for example `Europe/Berlin`), or the controller stops with `not a time zone`, and it must match Home Assistant's; otherwise lights on and off, dryback and the daily reset all shift, and you get alert CS-405. If you later change Home Assistant's time zone, restart the controller.

**Wrong token and IP bans.** Every request Home Assistant refuses counts as a failed login: Home Assistant shows a "Login attempt failed" notification, and if IP banning is on (`ip_ban_enabled` with a `login_attempts_threshold`), enough of them ban the machine the controller runs on, which then blocks it even with the right token. The controller sends at most one refused request each time its container starts (apart from the checks described below), so only repeated restarts with a bad token add up. If the log says Home Assistant refuses this machine (`HTTP 403`), it is banned: remove its address from `ip_bans.yaml` in Home Assistant's configuration folder and restart Home Assistant, then restart the controller. If Home Assistant starts refusing the token while a shot or a dose is running, the controller still sends the off for what it turned on before it waits. The same goes for a start that finds a shot or a dose left unfinished by the last run (the machine lost power mid-shot, for example): it does not just wait. While anything like that is not confirmed off, it asks again once a minute for 10 minutes and then every 15 minutes, and carries on by itself as soon as Home Assistant accepts it again, closing what was left open; each refused question counts as one more failed login. If the token works but its user is not an administrator, it uses that token to close what was left open, then waits.

**The dashboard** is the **Crop Steering** entry in Home Assistant's sidebar, served by the integration. The container opens no port. Its port 8420 is a copy of the same page files, with no data of its own and no login, and is off unless `F2_SERVE_UI=1`; don't publish it beyond `127.0.0.1`.

**Stopping and updating.** `docker compose stop` or `down` send the controller SIGTERM. It closes the shot in flight and switches off what dosing has running before it exits, within at most 75 seconds (`F2_STOP_BUDGET_S`) inside the 90 s `stop_grace_period`. Whatever Home Assistant was too slow to confirm OFF is recorded and switched off again on the next start. Keep `stop_grace_period` at least 5 seconds above the budget, and don't use `docker kill`. Started some other way (`docker run`, a NAS's Docker manager), the container gets Docker's 10 s stop timeout unless you give it one: use `--stop-timeout 90`, or set `F2_STOP_BUDGET_S` to 5 seconds under the timeout you have. To update, update the integration through HACS and restart Home Assistant, set `CONTROLLER_VERSION` in `.env` to its new version, then run `docker compose pull` and `docker compose up -d`. Each release's notes name the image's `@sha256` digest, if you would rather pin the exact bytes than the version tag. State in the volume is read by older and newer versions alike.

**Options.** Every app option has an environment form, `F2_OPT_<OPTION NAME IN CAPITALS>`, for example `F2_OPT_NOTIFY_SERVICE=notify.mobile_app_phone`. Lists are comma-separated. A secret can come from a file with `_FILE`, for example `F2_OPT_CF_API_TOKEN_FILE=/run/secrets/cf_api_token`; the log shows secrets only as `<set>` or `<unset>`. An `options.json` in the data volume is read too, and an environment variable wins over it. A value that can't be read stops the controller with the variable's or option's name in the log, and so does an `options.json` that is not valid JSON or holds a value of the wrong type (a list written as one string, `"hold_entities": "input_boolean.flush"` instead of `["input_boolean.flush"]`, for example). It never silently falls back to defaults. Options the controller does not know are named in the log and ignored.

## Manual integration install

Copy the entire `custom_components/crop_steering` directory into HA's `/config/custom_components/crop_steering` and restart HA. Include its `www/dashboard.html` file. Then follow steps 2-7 above. Do not copy this repository wholesale into `/config`; historical facility examples are not your configuration.

Developers build the dashboard using `npm ci --prefix frontend` then `npm run build --prefix frontend`. Packaging generates identical self-contained HTML in the integration, controller and web distribution folders. Compiled HTML is a deliverable, not the editing source.

## Upgrading an existing installation

Update an existing controller in place from this repository. The old `JakeTheRabbit/f2-control` mirror no longer receives releases; a controller installed from it moves once, as described in [Moving a controller installed from f2-control](#moving-a-controller-installed-from-f2-control). A room on the first AI edition (the `HA-Crop-Steering-Jev` repository) also moves once: see [Moving a room from the first AI edition](MOVING_FROM_JEV.md). Never run two controllers against one room: each app has its own identity and runtime data, and both would drive the same pump and valves. A controller that sees another controller's heartbeat on its room holds that room, watering and dosing nothing in it (CS-609), but a controller from before that check never holds, so stopping the other one first stays the rule.

1. Back up HA, the controller's persistent data and existing setpoints. Export grow plans if available. Record which engines are enabled.
2. Turn the affected engines off and wait for the pump, mainline and valves to be OFF. Stop the existing controller while replacing software.
3. Refresh your existing app repository and update that controller in place to the release's version. After updating from 0.13.x, turn the engine kill switch off and on once so the controller can accept and save the current setup; later restarts resume by themselves. A restart alone does not rebuild an old image. Do not install a second copy. The controller starts with the host unless its **Start on boot** was turned off, so a host restart during the upgrade starts it; with the engines off (step 2) it waters nothing.
4. Download the same version of the integration through HACS and restart HA. Confirm every Crop Steering room finishes loading.
5. Start the controller with engines still off. Verify its version, fresh heartbeat, both room descriptors, sensor readings, setup acknowledgement and grow-plan capability. Compare current setpoints and pot/dripper sizing with the backup.
6. Restore the engines' previous enabled states after these checks. An upgrade does not require arming a recipe or replacing existing values with defaults.

If an update is missing from the app store, refresh the repository information first. Use Update for published versions or Rebuild for a local source installation. HACS and the app store update separate components.

A room first set up from a `crop_steering.env` file keeps loading and running on what its entry stored; the file is no longer read. Setup no longer imports one and Configure no longer reloads one. To set up another room, or to rebuild one, keep the old file open as a checklist and pick the same switches and probes in the setup wizard, which checks units, valves and the pump before it saves.

### Moving a room's kill switch

Each room has one kill switch: the switch that must be ON before anything in it is watered. The controller names it on the room's heartbeat, and the sidebar and Settings → Repairs name the same switch. An update never moves it; moving it is your decision.

- A room made by the setup wizard stops on its own **Engine Enabled** switch (`switch.crop_steering_engine_enabled`, or `switch.crop_steering_<room>_engine_enabled` for a named room). A fresh installation needs no helper.
- A room from before the setup wizard stops on the entity the controller app's `enable_flag` option names, `input_boolean.f2_control_enabled` unless that option was changed.

To move a room, first turn its current kill switch OFF and wait until the pump, main line and valves read OFF. Then:

- On a room with **no saved setup** (an installation from before the wizard), set the app's `enable_flag` option to the new switch and restart the app.
- On a room **whose setup has been saved** (every room made by the wizard), the setup names the kill switch. Once the controller has taken that setup on, the app's `enable_flag` option no longer decides it, so setting the option alone changes nothing. A new kill switch has to come with a new setup revision, which the controller takes on only while the old and the new switch both read OFF.

If Repairs reports the kill switch missing (CS-601), the card names the switch the room really stops on. Whenever the running controller reports a kill switch other than the room's Engine Enabled switch, Repairs shows a card of its own (CS-610) saying that turning Engine Enabled OFF does not stop water in that room, and naming the switch that does.

### Moving a controller installed from f2-control

The controller used to be mirrored to `JakeTheRabbit/f2-control`. That mirror is retired; this repository is the only source. Supervisor names an app after the repository it came from (`4d457e60_f2_control` from the mirror, `6db5faba_f2_control` from here), so the move is a one-time reinstall that carries the runtime state across:

1. Add this repository to the app store and install **Crop Steering Controller** from it. Do not start it, and turn its **Start on boot** off for now: it is on by default, and a host restart before step 6 would otherwise start both apps.
2. Copy the old app's Configuration into the new app: every option.
3. Turn every engine kill switch off and wait until the pump, mainline and valves read OFF.
4. Stop the old app and turn off its Start on boot and Watchdog.
5. Copy `state.json` from the old app's data folder to the new one. It holds each zone's phase, today's counters, the accepted setup revision and what Auto Setpoints has learned; without it the controller starts learning again and waits for setup to be accepted. On HA OS, from an SSH terminal with Docker access: `docker run --rm -v /mnt/data/supervisor/apps/data:/d alpine cp -p /d/4d457e60_f2_control/state.json /d/6db5faba_f2_control/state.json` (older Supervisor versions use `addons/data`).
6. Start the new app, turn on its Start on boot and Watchdog, and check its log, version, heartbeat and setup acceptance before turning the engines back on.
7. After a day of normal running, uninstall the old app and remove the `f2-control` repository.

The existing app slug `f2_control` and entity IDs are deliberately stable. Existing environment mapping remains supported. Older dashboard bookmarks retain room context and redirect to the new routes. After upgrade, verify the room descriptor and controller heartbeat, setup acknowledgement and plan capability before enabling control.

## Optional tank display mappings

In **Rooms & setup → Shared room hardware**, map tank fill level to a percentage sensor, tank EC to mS/cm or dS/m, tank pH to pH, and tank temperature to a temperature sensor. These tank-quality display mappings do not enable feed-water safety gates. Choose a fill valve or binary sensor for filling status and a timestamp sensor or full date-and-time helper for **Last recorded tank fill**. Use an actual recorded fill event; an automation trigger time or sensor `last_changed` is not proof of filling. Shared tanks can be explicitly mapped to more than one room. The [tank mapping table](USER_GUIDE.md#tank-and-feed) lists the exact labels and configuration keys. A recorded fill can be operator-confirmed or float-confirmed according to its producer; it is not proof that dosing finished. Filling status must represent the fill valve or a genuine fill-active signal, not a mode-enable or dosing-lock helper.

Save setup with the affected engines and irrigation equipment off, then verify the readings in **Overview** before restoring the previous engine state. Missing mappings remain labelled; an unavailable pump is never displayed as off. Existing controllers must be updated to publish irrigation timestamps with a timezone offset.

## Optional AI assistant

The controller runs on its own rules unless you turn the AI assistant on. It needs your own Anthropic API key
(console.anthropic.com, **API keys**), which is billed to you; `anthropic_daily_budget_usd` (US$1.00 by default)
caps what it spends between one lights-on and the next, and the engine runs on its own rules once it is spent.

- **App (Home Assistant OS or Supervised):** in the app's **Configuration**, set `brain_provider` to
  `claude_haiku` and paste the key into `anthropic_api_key`, then restart the app. The log shows
  `brain: claude_haiku, model claude-haiku-5-5, budget US$1.00 until lights-on, key set`, never the key.
- **Container:** put the key in a file next to `docker-compose.yml`, for example `anthropic_key.txt`, add it as
  a Docker secret and set `F2_OPT_BRAIN_PROVIDER=claude_haiku` and
  `F2_OPT_ANTHROPIC_API_KEY_FILE=/run/secrets/anthropic_key`. `F2_OPT_ANTHROPIC_API_KEY` or the usual
  `ANTHROPIC_API_KEY` work too, but anyone who can run `docker inspect` can read an environment variable. Run
  `docker compose up -d`; the log shows `anthropic_api_key=<set>`. Building by hand on a 32-bit ARM machine,
  pass `--build-arg BUILD_ARCH=armv7`: the image then has no Anthropic SDK and runs rules.

**What is sent.** Each question carries the zone's readings, its settings, the day's stage and the room and zone
names you typed. Never an entity id, a key or personal data. The brain's answers only act through the
controller's own limits, and every failure runs the engine exactly as on rules. While any switched-on zone's
moisture reading is stale or missing, nothing is asked for that room until the probes report again. The AI
assistant tile on the dashboard says which brain runs and why.

### The removed first AI route

The first AI route (through Cloudflare or TypeSafe) is removed. An install that used it loads with no option
changed: `brain_provider: jev_legacy`, or `auto` where that route ran, moves to Claude with every judge when
`anthropic_api_key` has a key, and uses rules when it does not. It gets a CS-712 card once a release, and the
old Cloudflare and TypeSafe options are not used. To move on, set `brain_provider: claude_haiku` and an
Anthropic key; to turn the brain off, set `brain_provider: rules`.

## Optional LLM / MCP connection

Normal installation does not require an LLM. The optional MCP package requires Node.js 22 or newer and a client that can launch a local stdio process. To connect one, follow [MCP.md](MCP.md) on the client machine after the HA integration is reachable. The documented server uses local stdio with locally configured `HA_URL` and `HA_TOKEN`. It is read-only by default. Setup changes or draft-plan saves require `CROP_STEERING_ALLOW_WRITES=true`, followed by exact proposal review. `preview_setup`/`preview_plan` produce a short-lived, single-use token; `apply_proposal` accepts only that token and its matching room/revision, then reads back the result. Follow the server guide for client configuration and validation evidence.

This is separate from broad third-party HA MCP connectors. It does not expose arbitrary services, engine enabling, valve commands or grow-plan activation. Verify actual HA responses and setup acknowledgement after an approved configuration change.

## Restore a prior version

Turn affected engines off and confirm physical equipment is off. Restore the prior integration/controller versions and their matching persistent-state backup. An active grow plan uses a durable required-plan latch: do not downgrade the controller while expecting it to understand a newer active plan. Disarm and verify the boundary handoff to manual targets first, or restore a complete known-good backup with engines off.

## If the sidebar or setup is missing

Restart HA after installing the integration. Check integration logs and that `custom_components/crop_steering/www/dashboard.html` exists. Missing workspace services mean the integration is older than the dashboard. Unsupported activation means the controller has not published the new capability heartbeat. Refresh the page after upgrading both components.

The installation links follow the official [Home Assistant app repository format](https://developers.home-assistant.io/docs/apps/repository/) and [configuration flow mechanism](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/). Home Assistant's [frontend theme configuration](https://www.home-assistant.io/integrations/frontend/) supplies inherited theme colors.
