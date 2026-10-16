# Moving a room from the first AI edition

This is for a room whose integration and controller app came from the `HA-Crop-Steering-Jev`
repository (the first AI edition, up to 3.11.1). That line stops at 3.11.1 and carries on here, in
`HA-Irrigation-Strategy`. A room on the first AI edition keeps running as it is; this page is how to bring
it across once, without losing its phase, counters, learned values, dosing record or the AI assistant's
record.

**When.** Move a production room only to a stable release **3.12.0 or later** of this repository (the
current release is 3.13.0).
An older release puts an older controller on top of a 3.11 state file. A staging room can follow `#testing`.

## Why it is a move and not an update

The Supervisor names an app after the repository address it was installed from:

| Repository address | App id |
| --- | --- |
| `https://github.com/JakeTheRabbit/HA-Crop-Steering-Jev` | `e031e6d4_f2_control` |
| `https://github.com/JakeTheRabbit/HA-Irrigation-Strategy` | `6db5faba_f2_control` |
| `https://github.com/JakeTheRabbit/HA-Irrigation-Strategy#testing` | `1d36ddd9_f2_control` |

So the controller from this repository is a **different app with an empty data folder**, and its
options start at their defaults. The integration does not change identity: its domain
(`crop_steering`), config entry, entity ids and dashboard stay; only the HACS repository its files come
from changes.

## Steps

These are for Home Assistant OS and Supervised installs, and follow the same shape as
[moving a controller installed from f2-control](INSTALL.md#moving-a-controller-installed-from-f2-control).

1. **Back up.** Take a Supervisor backup of the old app (it holds its data folder) and a full Home
   Assistant backup. Write down every `number.`, `select.` and `switch.crop_steering_*` state (Developer
   tools, States, filter on `crop_steering`), so step 7 can compare against it.
2. **Install the new app, but do not start it.** Add `https://github.com/JakeTheRabbit/HA-Irrigation-Strategy`
   to the app store (`...#testing` for a staging room), install the **Crop Steering Controller** app from
   it, and leave it stopped with Start on boot and Watchdog off.
3. **Copy every option.** Copy the old app's Configuration into the new one, every option, including
   `enable_flag` and the `jev_*` fields. The new app's form shows the `jev_*` tuning options under their new
   `ai_*` names; the old names still load (docs/AI_ASSISTANT.md, "Old option names"), so you can set them in
   YAML mode (the Configuration tab's menu, Edit in YAML). The old route's `typesafe_api_key` and `cf_*`
   fields are not used any more: copy them only to keep the record of what the old app used.
4. **Make the room safe.** Turn each room's kill switch off: the one its health card names (its engine
   switch, or the `input_boolean` helper on older rooms). Wait until the pump, main line and valves read
   OFF. Stop the old app and turn off its Start on boot and Watchdog.
5. **Copy the data folder.** From an SSH terminal with Docker access, set `NEW` to the app id the room is
   moving to (the table above) and `SUP` to the Supervisor's data folder on the host (`/mnt/data/supervisor`
   on Home Assistant OS, `/usr/share/hassio` on a Supervised install), then run:

   ```sh
   NEW=6db5faba_f2_control   # 1d36ddd9_f2_control for a staging room on #testing
   SUP=/mnt/data/supervisor  # /usr/share/hassio on a Supervised install
   docker run --rm -e NEW="$NEW" -v "$SUP":/s alpine sh -c '
     for d in /s/apps/data /s/addons/data; do [ -d "$d/e031e6d4_f2_control" ] && break; done
     [ -d "$d/e031e6d4_f2_control" ] || { echo "no data folder for e031e6d4_f2_control"; exit 1; }
     [ -d "$d/$NEW" ] || { echo "no $d/$NEW: install the new app first"; exit 1; }
     cd "$d/e031e6d4_f2_control" || exit 1
     for f in state.json dosing_state.json jev_usage.json jev_ledger.jsonl jev_journal.jsonl jev_setpoints.json; do
       if [ -e "$f" ]; then cp -p "$f" "$d/$NEW/" || exit 1; fi
     done
     ls -l "$d/$NEW"'
   ```

   The command finds the app data folder under either name the Supervisor has used (`apps/data`, or
   `addons/data` on older Supervisors) and copies only the files that exist; it never touches the old
   folder. Do **not** copy `instance_id`: the new app makes its own, so the duplicate-controller guard can
   tell the two apps apart. `state.json` holds each zone's phase, today's counters, the accepted setup revision and what
   Auto Setpoints has learned. `dosing_state.json` holds the dosing record, including anything a dose or
   batch left switched on. The `jev_*` files are the AI assistant's day count, ledger, journal and
   setpoint memory. The first AI route is removed in this repository: with `brain_provider` at its default
   `auto`, a room whose copied files show that route ran there (any one `jev_*` file, or a TypeSafe key in
   the copied options) moves to Claude when `anthropic_api_key` has a key, and runs on the rules when it
   does not. To be sure, set `brain_provider: claude_haiku` and add an Anthropic key in step 3.
6. **Switch the integration's HACS source.** In HACS, first remove the `HA-Crop-Steering-Jev` repository
   (HACS may delete `custom_components/crop_steering` as it does; Home Assistant keeps running the loaded
   integration until it restarts). Then add `https://github.com/JakeTheRabbit/HA-Irrigation-Strategy` as a
   custom repository (type Integration) and **Download** the same version the new app runs, which writes
   `custom_components/crop_steering` afresh. Removing first means only one HACS repository ever provides
   the integration. Restart Home Assistant once. The config entry and entities are untouched (same
   domain); check that Settings, Devices & services shows the integration loaded at the new version.
7. **Start the new app.** In its log check: the version on the `Crop Steering Controller <version> starting` line
   (older controllers wrote `f2-control <version> starting`);
   `room '<room>' setup revision N adopted with verified OFF hardware` for each room, and no "setup change
   waiting, not watering" notice; and the brain lines: `brain: claude_haiku, model ...` with the judges
   (every judge, `ramp` included) when the room has an Anthropic key, or `brain: rules (...)` when it has
   none. A room that the old route ran also logs one line that the first AI route was removed, and gets a
   CS-712 card. The brain panel (the room's AI assistant tile) says the same. Check a fresh heartbeat, and that each zone's phase and today's
   counters are the ones the old app left. Compare every state against step 1: nothing the operator set
   may have moved.
8. Turn the kill switches back on, turn on the new app's Start on boot and Watchdog, and run a **catch
   test**: run a shot, catch what one dripper delivers and compare it with the zone's dripper flow
   (the calculator is in Equipment › Setup › Water & calibration). Only that proves water is delivered.
9. After a full photoperiod, uninstall the old app. Two controllers on one room are two things opening
   the same valves, which is why step 4 stops the old app before the new one starts. The newer app also
   holds when it sees the other one's beat.

## Going back

Until step 9 the old app and its data folder are untouched. To go back: turn the kill switches off, stop
the new app and turn off its Start on boot, remove `HA-Irrigation-Strategy` from HACS, add
`HA-Crop-Steering-Jev` back and download 3.11.1 from it, restart Home Assistant, then start the old app.
Its data folder is as it was at step 4, so its counters carry on from there. If the integration does not
load on 3.11.1 (a newer release can save its settings in a form 3.11.1 cannot read), restore the full Home
Assistant backup from step 1 instead.
