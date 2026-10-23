# Upgrading to 3.18

**⚠️ THIS IS A MASSIVE UPGRADE. It is fucking huge.** Almost every page of the dashboard is new or
rebuilt: timer programs, presets, alert rules, a new History section, feed and pump calibration, pump
supply sharing, quiet hours and an Upgrade report.

**If you are running this on a live grow, do NOT just click update** unless you have time for a big
configuration session straight after. Watering will not stop, but there is a lot to set up and check.

**Your settings come across as far as they can.** The update keeps every zone watering and dosing
exactly as before, and carries your current settings into the new features wherever it can do that
without guessing. Nothing new that waters or doses is switched on for you.

- **Carried across:** every zone keeps watering by steering; each recipe stage you had edited is
  copied as a preset; a "before 3.18 update" preset of your current settings is saved as a rollback
  point; temperatures in °F if Home Assistant uses °F; every notification recipient; your pH up/down
  pumps keep their role; your earlier setting changes, stock moves, calibrations and dosing records
  are imported into History; a room with no feed EC probe keeps the old 3.0 mS/cm assumption so it
  flushes as before.
- **Needs you:** the irrigation supply (each pump's real flow, how many zones it feeds at once, its
  flow meter: nothing is saved until you save it); the 2-point feed pH and EC probe calibration;
  the solution and a pump calibration for each nutrient pump; ppm instead of mS/cm if that is how
  you work; automations that still use a retired entity; grow-plan recipes saved only in your
  browser (export them). Optional: alert rules, quiet hours, camera, CO2 and light panels, new
  dashboards.
- Each room's **Upgrade report** lists exactly what was carried and what needs you: Crop Steering →
  Settings → System status, and a card in Home Assistant's Settings → Repairs.

**Get your AI to configure it.** Point your AI assistant (Claude, ChatGPT, or any assistant connected
through the Crop Steering MCP server) at the new documentation and have it work through the Upgrade
report with you, one line at a time, asking you before each save:

- This page: one section per Upgrade report line, written so an AI can follow it step by step.
- [Configure Crop Steering through MCP](MCP.md): connect an assistant to your Home Assistant.
- [User guide](USER_GUIDE.md), [AI assistant](AI_ASSISTANT.md) and the
  [Crop Steering Academy](https://jaketherabbit.github.io/HA-Irrigation-Strategy/learn/).

**Order:** update the integration first, restart Home Assistant, then update the controller app.

A tour of the new pages, with pictures, is in the [changelog](../CHANGELOG.md#unreleased).

3.18 is a big upgrade. The update keeps every zone watering and dosing exactly as before, carries your
settings into the new features where it can do that without guessing, and lists the rest in each room's
**Upgrade report** (Crop Steering → Settings → System status, and one card in Settings → Repairs, code CS-616).

This page has one section per line of that report. Each section says what the update did, what it left
for you, and how to set it, written so that you, or an AI assistant you give this page to, can do it
step by step. Nothing below is needed to keep watering as before: each step turns on something new.

**Order.** Update the integration first, restart Home Assistant, then update the controller app.

**For an AI assistant.** Read the report first: `crop_steering.migration_report` with
`room_id` (`room:` for the default room, `room:<prefix>` for a named room, for example `room:f2_`). It
answers `{carried: [...], needs_you: [...]}`, each row `{id, title, status, detail, page, doc}`; `doc`
points at a section below. Work through `needs_you` one row at a time. Every service named here that
changes something needs a Home Assistant administrator and an `expected_revision` read first from its
`*_get` / `*_list` service. Ask the grower before each save; never guess a pump's flow or a probe's
calibration.

## Supply

*Report row `supply.pumps`.* The update found each room's irrigation pump and main line in its setup and
**did not save a supply**. Saving one turns on pump sharing: two rooms on one pump then take turns, and a
zone that needs more water than its pump can give raises CS-214. Until you save, watering is as before.

To set it: Crop Steering → Equipment → Setup: pumps & valves → Supply, or `crop_steering.supply_get` then
`crop_steering.supply_save` with `expected_revision` and `irrigation_pumps`:
`[{entity_id, max_flow_lph, max_concurrent_zones, flow_meter}]`.

- `entity_id`: the pump switch the report names (`hardware.pump_switch` of each room that uses it).
- `max_flow_lph`: the pump's real output in litres per hour. Measure it (a timed bucket at the far zone),
  do not take it from the box. Leave it out (null) if unknown: no capacity check runs.
- `max_concurrent_zones`: how many zones it may feed at once. 1 is the safe default and how it ran before.
- `flow_meter`: a sensor in L/min or L/h on the pump's line, or null. Never a dosing pump's mL/min sensor.

`zone_meters` (`{"room:<prefix>": {"<zone>": "sensor.x"}}`) and `zone_groups` (zones that must never run
together) are optional. `supply_save` with `preview: true` shows the capacity check before saving.

## Irrigation mode

*Report row `irrigation.mode`.* Each zone has a new select,
`select.crop_steering_<prefix>zone_<n>_irrigation_mode`: `steering` (as before), `timer` (runs the room's
timer programs only) or `off`. Every zone starts on `steering`. If the report lists a zone with no mode,
pick `steering` to keep it as it was. Turning a zone off still uses `switch.crop_steering_<prefix>zone_<n>_enabled`,
as before.

## Presets

*Report rows `presets.recipe`, `presets.snapshot`, `presets.recipe_keys`.* Presets save a room's or a zone's
targets, phase timing, water limits and timer programs, and copy them to other rooms or zones. They are
in Crop Steering → Irrigation → Grow plan & presets.

- Each recipe stage you had edited (one that differs from the shipped default) was copied as a preset
  named `<room> – <stage> (from 3.17 recipe)`. The recipe itself is unchanged and still works.
- A preset named `<room> – before 3.18 update` holds the room's own settings as they were at the update.
  It is a point to go back to if you change things and regret it. A zone's own values (a zone tuned
  apart from its room) are not in it: before you change one, save a preset from that zone. If some
  settings could not be read at the update, no preset is saved and the update tries again at the next
  start.

Nothing was applied. To apply one: `crop_steering.preset_list`, then `crop_steering.preset_apply` with
`preset_id`, `to: [{room_id}]` or `[{room_id, zone}]` and `preview: true` first to see the changes.
A recipe key listed under `presets.recipe_keys` has no preset section: set it on the room's settings.

## Alerts

*Report row `alerts.rules`.* Alert rules (Crop Steering → Settings → Alert rules) are new and there are none. Your
irrigation pH and EC limits (`number.crop_steering_<prefix>irrigation_ph_min/max`, `irrigation_ec_min/max`)
still stop watering as before; a rule is only a notification. To add one: `crop_steering.alert_rule_preview`
to see how often it would have fired, then `crop_steering.alert_rule_set`. Optional.

## Units

*Report rows `units.temperature`, `units.ec`, `units.clock`.* Display only: what the dashboard shows,
never what is stored or what the controller uses. Temperatures follow Home Assistant (°F where Home
Assistant uses °F). EC is shown in mS/cm; if you work in ppm, pick the 500 or 700 scale. Set them in
Crop Steering → Settings → Dashboards & display, or `crop_steering.display_get` then `crop_steering.display_save`
with `options: {ec_unit: "ppm500" | "ppm700" | "mS/cm", temp_unit: "C" | "F", clock: 12 | 24}`.

## Quiet hours

*Report rows `notify.recipients`, `notify.quiet_hours`.* Every notification recipient was kept as it was.
Quiet hours are new and off for everyone: emergencies always come through, other alerts wait until the
quiet hours end. Set them per phone in Crop Steering → Settings → Notifications. Optional.

## Feed calibration

*Report rows `calibration.feed_ph`, `calibration.feed_ec`.* Each feed probe reads raw, as before. The
2-point calibration is new: Crop Steering → Equipment → Feed pH/EC calibration, two buffer solutions, and the
correction is applied only when you commit it. While a calibration session is open, dosing and pH
correction wait, and the source-water gate uses the corrected reading once committed. An old calibration
check from before 3.18 is kept as a record and never applied. A person does this at the tank: an AI
assistant can explain it but cannot run it.

## Dosing pumps

*Report rows `dosing.ph_pumps`, `dosing.pump.<id>`.* The dosing setup was not changed. A pH up/down pump
keeps its pH role. Each other pump is listed: pick its solution (nutrient or additive) in Crop Steering →
Equipment → Feed & dosing.

- A pump with a flow sensor (`flow_entity`) doses from that sensor, as before. Its flow sensor always wins
  over a calibrated mL/min, so a pump calibration changes nothing for it.
- A pump without one: run a pump calibration (Equipment → Pump calibration, `pump_calibrate`, then
  `pump_calibration_commit`) so its doses are sized from a measured mL/min. Until then it doses as before.

## Feed EC fallback

*Report row `feed.ec_fallback`.* This room has no feed EC probe and its feed recipe declares no EC. Before
3.18 the controller assumed the feed was 3.0 mS/cm, and that decided its EC flushes and its holds for a
high EC. 3.18 does not invent a feed EC, so the update keeps the old 3.0 for this room, and the controller
says so (CS-907). It stops by itself when either of these is done:

- map a feed EC probe (Crop Steering → Equipment → Setup: pumps & valves, `hardware.feed_ec_sensor`), or
- set the EC of the feed recipe in use (Crop Steering → Equipment → Feed & dosing).

The report checks the probe mapped in Setup. A feed EC probe mapped only in the controller app's options is
used by the controller, which then ignores the kept 3.0: map it in Setup too and this line goes away.

The CS-907 notification is sent (not quiet) once each time the controller starts, for every room on the
kept 3.0, until one of the above is done.

**A change for rooms that do have a feed EC probe.** When the probe is offline for longer than the feed
grace period, 3.17.0 assumed 3.0 mS/cm; 3.18 treats the feed EC as unknown (the recipe's EC if it declares
one), so that room takes no EC flush and no hold for a high EC until the probe reads again. The kept 3.0
is only for rooms with no probe at all.

## New panels

*Report row `panels.new`.* The camera, CO2 and light-level (PPFD, DLI) panels show once their entities are
mapped in Setup. New dashboards (wall, tablet, dosing) are made from Settings → Dashboards & display; the ones you
made yourself are never changed. Optional.

## Retired entities

*Report row `entities.retired`.* An automation or script still uses an entity Crop Steering no longer
reads. Settings → Repairs names each one (CS-614). Remove it from the automation.

## History

*Report row `history.import`.* Your earlier setting changes, stock moves, calibrations and overlays were
added to History (Crop Steering → History → Changes), beside everything recorded from now on. The controller adds its own dosing history and
AI records after it updates.

## Browser recipes

Grow-plan recipes saved "on this browser" before 3.18 stay in that browser. The dashboard offers to export
them as a backup the first time it opens after the update. They are not presets and are never imported
without you.
