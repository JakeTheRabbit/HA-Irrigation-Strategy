# Batch-tank dosing

Crop Steering can make a batch of nutrient solution and dose single pumps into a room's batch tank:
fill the tank, mix it, dose each nutrient in order, mix again and stamp the fill. Each room has its
own dosing page (Equipment › Dosing) for its own tank, so a site with two tanks sees two separate
pages, one per room.

It drives dosing pumps whose firmware times each dose itself: Home Assistant sets a volume, presses
start, and the pump's own board switches the motor off. Crop Steering never switches a dosing motor
on and trusts itself to switch it off; a browser never switches anything.

This document is the contract between the three layers. Everything below is generic: no entity id,
pump name or recipe is assumed.

## Layers

| Layer | Owns | Never does |
|---|---|---|
| Integration | Each room's dosing configuration and its one pending request, in a revisioned store; the services to read, save and request; `sensor.crop_steering_<prefix>dosing_config` for the controller | Switch, press or set any hardware |
| Controller app | Every action: doses, batches, stops, the irrigation hold during a batch and while dosing hardware does not read off, recovery after a restart, alerts CS-801 to CS-807; `sensor.crop_steering_<prefix>dosing` with live status | Act on a dose or batch asked for more than 120 s before, or on a room whose configuration it cannot read; switch a dosing pump's power on |
| Dashboard | Equipment › Dosing: pumps, a dose form, the batch, the recipe, history, and the dosing setup | Write any hardware entity; everything goes through `dosing_request` |

## Configuration (integration store `crop_steering.dosing.<entry_id>`)

```jsonc
{
  "revision": 4,                       // bumped on every save; dosing_save requires expected_revision
  "pumps": [                           // 0..8, in the order the page shows them
    {
      "id": "balance",                 // [a-z0-9_]{1,24}, unique in the room
      "name": "Balance",               // 1..40 chars
      "volume_entity": "number.x",     // number.* | input_number.*   the firmware's dose volume (mL)
      "start_entity": "button.x",      // button.* | input_button.* | script.*   starts the on-device dose
      "dosing_entity": "sensor.x",     // binary_sensor.* (on = dosing) | sensor.* (state starts with dosing_prefix)
      "dosing_prefix": "Dosing",       // sensor type only; default "Dosing"
      "power_entity": "switch.x",      // switch.*   turning it off stops the motor (the stop and the overrun cut)
      "flow_entity": "number.x",       // number.* | input_number.* | sensor.*   calibrated flow, mL/s
      "max_ml": 2000,                  // 1..5000; a request above it is refused
      "restore_volume": true,          // put the volume number back after a single dose (firmware that
                                       // keeps its batch recipe in that number); default true
      "stock_tank": "balance"          // the id of a stock tank in this room's stock store, or null
                                       // (Stock tanks, below)
    }
  ],
  "batch": {
    "fill_valve": "switch.x",          // switch.* | null   null = the batch starts with the tank already filled
    "full_entity": "binary_sensor.x",  // binary_sensor.* | sensor.* | null   required when fill_valve is set
    "full_state": "on",                // the full_entity state that means full; default "on"
    "fill_timeout_min": 20,            // 1..60
    "mix_pump": "switch.x",            // switch.* | null
    "mix_valves": ["switch.x"],        // 0..4 switch.*, opened before the mix pump starts
    "mix_power_sensor": "sensor.x",    // sensor.* (W) | null
    "mix_min_w": 200,                  // 0 = no power check; else the mix pump must draw this within 20 s
                                       // (needs mix_power_sensor)
    "premix_min": 2,                   // 0..30
    "postmix_min": 5,                  // 0..60
    "close_entities": ["switch.x"],    // 0..16 switch.*, switched off before filling (another room's feed path)
    "hold_entity": "input_boolean.x",  // input_boolean.* | null   on for the whole batch, for other automations
    "filled_at_entity": "input_datetime.x", // input_datetime.* | null   stamped with the end time of a finished batch
    "recipe": [                        // dose order = list order; each pump at most once
      {"pump": "balance", "ml": 300, "ml_entity": null} // ml_entity (number.*|input_number.*|sensor.*) is read
                                                        // at batch start and wins over ml; 0 skips the pump
    ]
  },
  "request": null,                     // see Requests
  "updated_at": "2026-09-28T12:00:00+13:00"
}
```

Validation (`dosing.py`, pure): every entity exists and is in its allowed domain; pump ids unique;
recipe pumps exist; a pump appears in the recipe at most once; `full_entity` set whenever
`fill_valve` is; `mix_power_sensor` set whenever `mix_min_w` is above 0 (else the power could not be
checked); no entity is both a dosing pump's `power_entity` and batch hardware; a `mix_pump`,
`mix_valves` or `close_entities` switch may be a room's irrigation pump or main line (the batch
holds that room's watering); a pump's `stock_tank` is one of the room's stock tanks, and a stock
tank is linked to at most one pump. A room with no pumps is valid and does nothing. "Exists" is checked
when a setup is saved; a stored setup read back at start-up is kept although a device has not come
back yet.

## Services

| Service | Who | Data | Response |
|---|---|---|---|
| `crop_steering.dosing_get` | any user | `room_id` | `{schema_version: 1, room_id, config, candidates[], can_edit, error}` |
| `crop_steering.dosing_save` | admin | `room_id, expected_revision, pumps, batch` | the same as `dosing_get`, or `error` |
| `crop_steering.dosing_request` | admin; a `stop`: any signed-in user | `room_id, action ("dose" \| "batch" \| "stop"), pump?, ml?` | `{request, error}` |

- `room_id` is `"room:<prefix>"`, as for the stock services.
- Who: as for every service that changes something, "admin" means a signed-in administrator, and a
  call with no user (an automation) runs as before. A `stop` only switches things off, so whoever
  may look at the room may ask for one: any signed-in user, administrator or not. A user id Home
  Assistant does not know is refused either way.
- `candidates` lists entities of every domain the configuration can use (`number`, `input_number`,
  `button`, `input_button`, `script`, `binary_sensor`, `sensor`, `switch`, `input_boolean`,
  `input_datetime`): `{entity_id, name, domain, state, unit, device_class}`.
- `can_edit` (in `dosing_get`, and in `dosing_save`'s response): the calling user is an
  administrator (`call.context.user_id` → `hass.auth.async_get_user(...).is_admin`; false when
  there is no user).
- A request is **pending** while `request` is set AND its `id` differs from the `handled` attribute
  of `sensor.crop_steering_<prefix>dosing` (read with `hass.states.get`; Status, below) AND it is
  less than 120 s old. The stored request is not cleared by the integration; it simply stops being
  pending (the controller never acts on one older than 120 s).
- `dosing_request` stores one request `{id, action, pump, ml, at, by}` (`id` a uuid4 hex, `by` the
  user's name, null for an automation). A `stop` always replaces what is pending. A `dose` or a
  `batch` returns `error: "busy"` while one is pending, and a `dose` is refused when the pump is
  unknown or `ml` is not in 0 < ml ≤ `max_ml` (`error` then says which). A request does not move
  the revision.
- `dosing_save` returns `error: "busy"` too (the same word) while a request is pending or while
  `sensor.crop_steering_<prefix>dosing` reads `dosing` or `batch` (a dose or a batch runs from the
  setup it started with, which must not change under it),
  `error: "revision"` when `expected_revision` is stale, and an `error` naming the field when the
  setup breaks a rule under Validation; a refused save answers with the stored setup, unchanged. A
  pump saved without an `id` gets one made from its name.

`sensor.crop_steering_<prefix>dosing_config`: state = the revision; attributes `pumps`, `batch`,
`request`. This is what the controller reads (every 2 s).

## Requests and the controller

The controller runs one dosing thread for all rooms. Every 2 s it reads each room's
`dosing_config`. A request is taken once (its `id` is remembered, in `dosing_state.json` so a
restart does not take it again, and published as `handled`). A room whose `dosing_config` can't be
read has no request taken.

- Taken only when it is less than 120 s old. An older one is published as `handled` with the result
  "too old to act on" and does nothing, so a request left while the controller was down never fires
  later. The one exception is a `stop` for a room with a dose or batch running, or with dosing
  hardware that does not read off (Holding, below): it is acted on however old it is.
- `stop`: switches off every pump's `power_entity` in the room (whatever it reads), those of the
  setup the running dose or batch started with as well as the current setup's (a setup saved since
  may name other pumps), and ends a dose or a batch (below). A dose or batch looks for a stop before
  every switch-on and at every step, not only on its 2 s passes. In a room held by hardware that does
  not read off, a stop sends the offs again, and releases the room once everything reads off.
  `power_entity` is the motor's own switch on the firmwares this drives (off = idle), so a stop never
  switches it back on.
- `dose`: one pump, `ml` mL, into the tank as it is.
- `batch`: the batch sequence. Refused while `hold_entity` is already on (something else is
  dosing) or can't be read, or while the room has a latched hardware fault.
- The thread does one thing at a time: while a dose or a batch runs, in any room, a `dose` or a
  `batch` is refused (a `stop` is always acted on), and so is one for a room held by dosing hardware
  that does not read off ("refused: <entity> does not read off yet"). A request refused meanwhile
  keeps its own `handled_result`: the end of the running dose or batch never takes its place.
- One room's error never stops the others: each room is read in its own turn, and a room that fails
  15 passes in a row (30 s) raises CS-806 ("dosing in this room keeps failing").

`handled_result` says what came of the request `handled` names: for a dose "dosing" on start, then
the dose's result ("finished", "ended early", "ran past its time", "not confirmed", "stopped",
"stopped: an error in the controller"; for a pump linked to a stock tank, "not confirmed; nothing
drawn from its stock tank"); for a batch "making a batch", then "finished", "finished; <entity>
could not be stamped" or "stopped: <step>: <reason>"; a refusal "refused: <reason>" (for example
"refused: Bloom is not calibrated (flow 0)" or "refused: a batch is running"); an old request "too
old to act on"; a stop "stopped", or "stopped; <entity> does not read off".

### One dose (`ml` into a pump)

1. Refuse unless the pump's `flow_entity` reads a finite number of at least 0.05 mL/s (a firmware
   that divides by a zero flow runs its motor for ever, and a tiny one would put every time limit
   hours away: "refused: <pump> is not calibrated (flow 0.01)"), `ml` ≤ `max_ml`, the dose's
   expected time `ml / flow` is at most 20 minutes, `dosing_entity` reads, and does not read dosing,
   and `power_entity` does not read on ("refused: <pump> is running by hand": on these firmwares it
   is the motor's own switch).
2. Write the dose to `/data/dosing_state.json` (atomic, file and directory synced) before anything
   moves, with the volume number it is about to change, so even a restart puts it back.
3. Remember the volume number, set it to `ml`, and read it back (within 0.5 mL). A volume that does
   not read back is never started, and a dose is refused when `restore_volume` is on and the volume
   number can't be read (it could not be put back).
4. Press `start_entity` (`button.press`, `input_button.press` or `script.turn_on`), noting the time
   just before. The pump's power is never switched on.
5. Expected time `t = ml / flow`. Wait (reading every second) until the pump has been seen dosing
   and then reads not dosing. Deadline `t × 1.25 + 20 s`, and never more than 21 minutes.
   - It counts as done only when a read saw it dosing, or Home Assistant's recorder shows it dosing
     after the press (a dose too short to catch between two reads; the recorder may take a few
     seconds to have it, and is asked again until `t + 15 s`). A change of state alone is not
     enough: unavailable → idle is a pump that restarted.
   - Read unavailable or unknown at any point after the press (by a read, or in the recorder):
     result "not confirmed", alert **CS-802**.
   - Never seen dosing by `t + 15 s`: result "not confirmed", alert **CS-802**.
   - Done in less than half of `t`: result "ended early", alert **CS-802**; a batch stops.
   - Still dosing at the deadline: switch `power_entity` off, confirm it reads off (re-sent once),
     result "ran past its time", alert **CS-801**.
   - An error in the controller: its power off and read back, result "stopped: an error in the
     controller", alert **CS-806**.
6. Put the volume number back when `restore_volume` is on, once the pump reads idle or its power
   reads off (never while it may still be running: until then it is kept, and tried again every
   30 s), and read it back: when it does not read back, CS-806 says "the volume number of <pump>
   could not be put back to <x> mL".
7. Clear the dose from `dosing_state.json`; publish the result. When its power does not read off
   (after the deadline, a stop or an error), the record is kept instead and the room's watering is
   held until it does (Holding, below).

### A batch

The room's watering is held for the whole batch (`_blocked`: "making a batch"), and so is every
room whose pump, main line or valves are among the batch's `mix_pump`, `mix_valves`,
`fill_valve` or `close_entities`, and every room that shares the batch room's pump or main line
(closing them would otherwise cut that room's shot). The hold is set under the lock a shot starts
under, so a shot in a held room has either started (and the batch waits for it) or never starts.

Before anything moves (before Hold), the batch is checked. It is refused while `hold_entity` is on
or can't be read, while there is a `fill_valve` and `full_entity` can't be read ("refused: the
tank's full sensor can't be read"), and when `mix_min_w` is above 0 with a `mix_pump` but no
`mix_power_sensor`. Every recipe pump's amount and flow are checked too. A recipe entry whose
`ml_entity` is set but reads nothing usable refuses the batch ("refused: the recipe amount for
<pump> can't be read"): it is never replaced by the fixed `ml`. An amount of 0 skips the pump; any
other recipe pump whose flow reads below 0.05 mL/s or nothing refuses the batch too ("refused:
<pump> is not calibrated (flow 0)"), and so do an amount above its `max_ml` and a dose expected to
take more than 20 minutes. The watchdog is set from these doses.

| Step | What happens | Ends the batch (with its code) when |
|---|---|---|
| Hold | `hold_entity` on, read back; wait for any shot in flight in a held room to finish (10 min at most) | the hold does not read on; a shot is still running after 10 min |
| Close | switch off each held room's valves, main line and pump, and `close_entities`; read back | a switch does not read off (CS-806) |
| Fill | skipped when `full_entity` already reads full or there is no `fill_valve`; else open it, read it back on within 10 s, and wait for full; always close it and read back | the fill valve does not read on (**CS-804**, "the fill valve did not open"); `full_entity` reads nothing usable as the fill begins or for 15 s while it fills (**CS-804**, "the full sensor stopped reporting"); not full within `fill_timeout_min` (**CS-804**) |
| Mix | skipped without a `mix_pump`; open `mix_valves` and read them back, start `mix_pump` and read it back on; with `mix_min_w` and a `mix_power_sensor`, wait up to 20 s for the power | a mix valve does not open (CS-806); the pump does not read on or does not draw its power (**CS-805**) |
| Premix | `premix_min` minutes | |
| Dose | each recipe pump in order, as "One dose", with the amounts read before Hold; 0 skips | a dose ends any other way than finished (CS-801/802) |
| Postmix | `postmix_min` minutes | |
| Finish | stop `mix_pump`, close `mix_valves`, read back; stamp `filled_at_entity` (`input_datetime.set_datetime` with the end time as a timestamp); `hold_entity` off, read back | a switch does not read off (CS-806) |

- A `stop` at any point ends the batch: every dosing pump off, the fill valve closed, the mix pump
  off, the mix valves closed, and then `hold_entity` off. The result names the step it stopped in.
  Every other end (a step that fails, the watchdog, an error in the controller) switches off the
  same. A stop is looked for before every switch-on and at every step.
- Every end other than finishing raises **CS-806** with the step and the reason, after its own code.
  When any of that hardware does not read off, `hold_entity` stays on, and the rooms stay held and
  the record kept, until it does (Holding, below).
- A fill time that could not be stamped still finishes the batch, as "finished; <entity> could not
  be stamped", with CS-806 (record the batch by hand for the stock tanks that count by it). A
  `hold_entity` that does not read off at the end holds the rooms like any other switch (Holding).
- The whole batch has a watchdog: the 10-minute wait for a shot + fill timeout + premix + postmix +
  every dose's deadline (each capped at 21 minutes) + 10 min.
- Stamping `filled_at_entity` is what the stock tanks no pump is linked to count batches by, so such
  a stock tank whose per-batch dose points at the same recipe number is drawn down by exactly what
  was dosed. A tank linked to a pump is drawn by the pump's runs (Stock tanks, below).

### Holding: dosing hardware that does not read off

Whatever a dose or a batch switched off, or tried to, and does not read off (a dosing pump's power,
the fill valve, the mix pump, a mix valve, a batch's `hold_entity`) holds watering: the dose's room,
or every room the batch held. `_blocked` then reads "dosing hardware still on: <entity>". The record
in `dosing_state.json` is kept, so a restart holds it again. Every 2 s the controller reads it and
sends the off again to what does not read off; unavailable, unknown or missing never counts as off.
A batch's `hold_entity` is switched off only once the rest reads off. The alert (CS-801 for a dose
past its time, CS-803 after a restart, CS-806 otherwise) names what does not read off and comes
again every 30 minutes; once everything reads off the rooms water again, the record is cleared, and
the same notification says so. A `stop` for the room sends the offs at once, and releases the room if
they read off. A dose or a batch in that room is refused meanwhile.

### After a restart

If `/data/dosing_state.json` holds a dose or a batch in progress, the controller at start-up, before
its first loop, holds the rooms it held (the batch's, or the dose's own), switches off every pump's
`power_entity`, the fill valve, the mix pump and the mix valves of that room, and then treats it as
under Holding: read and sent off again every 2 s until every one reads off (a device that has not
come back after a host boot reads unavailable, and Home Assistant answers turning it off all the
same, so it is never counted as off). Only then does a batch's `hold_entity` go off, and the rooms
water again and the record is cleared. **CS-803** says so once Home Assistant answers: that it was
all switched off, or what still does not read off (and again every 30 minutes). The volume number
the dose changed is put back. A single dose's record never names a batch's `hold_entity`, so neither
a restart nor the way out ever touches it for a dose. It never resumes a dose or a batch.

A `dosing_state.json` that can't be read is kept as `dosing_state.json.bad`, a fresh one is started,
and CS-803 says so; then every room with dosing set up has its current dosing hardware (every pump's
power, the fill valve, the mix pump, the mix valves; never `hold_entity`, which may be someone
else's) switched off and held the same way, as soon as its setup can be read. Every write of the file
is atomic, and the file and its directory are synced.

The dosing thread is watched: the controller's main loop checks it every loop, and one that has died
is started again (whatever it had recorded is held and switched off as after a restart) with CS-806;
one that has not gone round for 10 minutes raises CS-806 (once every 30 minutes).

When the app is stopped (SIGTERM: an update, a restart), the shot in flight is closed first; then no
dosing switch-on starts any more (one already on its way to Home Assistant lands first, 5 s at most),
the dosing thread gets 3 s to switch its own dose's or batch's hardware off, and everything recorded
is switched off again, each off with a 2 s timeout and without waiting to read it back. The record
stays, and a batch's `hold_entity` stays on, for the next start. The app's `timeout: 30`
(`addons/f2_control/config.yaml`) has the Supervisor wait 30 s after SIGTERM, rather than its
default 10, before it kills the container.

### Status: `sensor.crop_steering_<prefix>dosing`

State: `idle` | `dosing` | `batch` | `unavailable` (the room's configuration can't be read).

```jsonc
{
  "pumps": {"balance": {"state": "idle" | "dosing" | "unavailable", "flow_ml_s": 11.06,
                        "target_ml": 25, "started_at": "…", "expected_s": 2.3,
                        "last": {"ml": 25, "at": "…", "result": "finished" | "ended early" | "ran past its time" | "not confirmed" | "stopped"}}},
  "batch": {"step": "idle" | "hold" | "close" | "fill" | "mix" | "premix" | "dose" | "postmix" | "finish",
            "pump": "bloom" | null, "started_at": "…", "step_started_at": "…",
            "steps": [{"step": "fill", "state": "done" | "running" | "skipped" | "failed", "at": "…", "note": "…"}],
            "result": null | "finished" | "stopped: <reason>", "ended_at": null | "…"},
  "handled": "<request id>", "handled_result": "…",
  "history": [{"kind": "dose" | "batch" | "draw", "at": "…", "ended_at": "…", "result": "…",
               "doses": {"balance": 300, "bloom": 1800}, "by": "…"}],  // newest first, 20 kept
  "updated_at": "…"                    // the controller's last publish
}
```

`updated_at` is the time of the controller's last publish, refreshed at least every 60 s even
when nothing changes, so the page can tell a stale controller. It is published on every change as
well; each pump's `flow_ml_s` and `state` are read every 30 s, and whenever the setup's revision
changes while nothing runs, with a 2 s timeout. While a dose or batch runs, that reading, the stock
draws not yet taken, alerts not yet created and volume numbers still to put back wait 30 s between
runs, so they never hold up its watch. When one read of the setup fails while a dose or batch runs
in the room, the status keeps the setup it started with (`dosing` or `batch`, not `unavailable`).
Nothing is published for a room whose integration has no `dosing_config` (one from before dosing).
`dosing_state.json` keeps `handled`, each pump's `last`, the `history` (with a `draw` entry for a
stock draw that was dropped, below), the draws and alerts not yet delivered and the volume numbers
still to put back across a restart.

## Alerts (controller, group CS-8xx "Dosing")

| Code | Title | Watering |
|---|---|---|
| CS-801 | A dosing pump ran past its time and was switched off | carries on (a batch stops), unless its power does not read off: then the room is held until it does |
| CS-802 | A dose could not be confirmed, or ended early | carries on (a batch stops) |
| CS-803 | A dose or batch was interrupted by a restart | the rooms it held stay held until its dosing hardware reads off |
| CS-804 | The batch tank could not be filled | held rooms water again; the fill valve was closed |
| CS-805 | The mixing pump did not start | held rooms water again |
| CS-806 | Dosing was stopped, or needs a check | held rooms water again once the hardware reads off; a dose's pump that does not read off holds its room |
| CS-807 | A dose was not taken off its stock tank | carries on |

Each event (a dose, a batch, a restart) raises its own notification, so a second one within half an
hour is never swallowed by the first, and an alert about hardware that does not read off is updated
on the same card (every 30 minutes, and once it reads off). An alert Home Assistant does not take (it
is down, typically at the moment hardware fails) is kept in `dosing_state.json` and raised again
until it does. Switching a room off does not dismiss its dosing notifications: they are about the
tank. CS-801, CS-803 and CS-806 always push to a phone, whatever Jev's Alerts judge says.

## Stock tanks

A pump may be linked to one of the room's stock tanks (`stock_tank`: the id of a tank in the room's
stock store, `crop_steering.stock.<entry_id>`, or null). A stock tank is linked to at most one pump,
and its level then follows what that pump actually runs, whoever starts it: the controller, a Home
Assistant automation or script pressing the pump's start, a button on the doser, or a hand on its
power switch. The integration watches the pump itself (`stock_api.py`), and that is the only thing
that draws a linked tank:

- **A run.** The pump runs while its `power_entity` reads on (the motor's own switch on these
  firmwares) or its `dosing_entity` reads dosing (a binary sensor on; a sensor whose state starts
  with `dosing_prefix`). Either is enough, because firmwares differ: on a 5.1.x ESPHome peristaltic
  doser, Home Assistant's history shows a dose button pressed by an automation turning the power
  switch on and the status to "Running (Manual)", which the default prefix "Dosing" never matches,
  for 27.13 s, then off and "Stopped" within a few milliseconds of each other. The run ends when
  neither reads running any more: off, idle, unavailable, unknown or gone.
- **What it draws.** When a run ends, the seconds it ran times the pump's `flow_entity` reading
  (mL/s, read as it started, or as it ended when it could not be read then) come off the tank,
  never below 0, with a history entry `{at, source: "pump", draw_ml, key, note}` (the note says
  how long it ran and at what flow) and a new revision. The firmware times a dose from the same
  calibrated flow, so this is the dose it was set to give: on that doser, 27.13 s at 11.0612 mL/s
  is 300.1 mL of the 300 mL its volume number held. It is also what a dose stopped part way, or a
  run by hand, actually moved. A flow that reads nothing usable draws nothing, and the integration
  logs a warning. The run is timed by when Home Assistant saw its states change.
- **Once.** A run is drawn when it ends, under the key `pump:<pump>:<when it started>`, so the
  same run is never drawn twice. A room reloaded in the middle of a run finds the pump running and
  takes the run from when its entity last changed: the whole run, once. When Home Assistant itself
  restarts in the middle of a run, only what it sees once it is back is drawn (a doser that comes
  back still running is drawn from then): what ran while it was down is not seen, and never
  guessed at.
- **The controller's reports.** When a dose ends, the controller still reports what it dosed to
  `crop_steering.stock_draw` (below): "finished" → the requested mL; "ended early", "ran past its
  time" or "stopped" → the requested mL or the seconds from the start press to its end × the flow,
  whichever is less; "not confirmed" → nothing. It sends that with the key `<prefix>:<pump>:<the
  dose's started_at>`, asking for the service's answer (`?return_response`), once the dose or batch
  has ended, and keeps a report not yet taken in `/data/dosing_state.json`, sending it again every
  2 s (every 30 s while a dose or batch runs, each with a 2 s timeout). The integration leaves a
  linked tank in a report as it is, because the pump's run already drew it, and lists it in the
  answer's `linked`. So a dose is counted once whoever reports it, and the controller's own results
  ("not confirmed; nothing drawn from its stock tank") say what it reported, not what the tank
  lost. A report is dropped, kept in the room's history (a `draw` entry) and alerted once
  (**CS-807**) when the answer names its tank as one the room does not have (`skipped`), when Home
  Assistant refuses it (HTTP 4xx: sending it again changes nothing), and when it has not been taken
  24 hours after the dose.
- **Fills and batches by hand.** The stock store's fill-based batch draw (a newer time on the
  room's tank last-fill entity takes each tank's per-batch dose) skips the tanks linked to a pump,
  so a batch that stamps `filled_at_entity` never counts them twice, and a fill that draws no tank
  at all is not logged (a fill entity stamped many times a day would push the pumps' draws out of
  the history). A batch recorded by hand (`crop_steering.stock_record_batch`) skips them the same
  way; its answer lists the linked tanks it skipped (`skipped`).
- `sensor.crop_steering_<prefix>stock_low` gives each entry of its `tanks` attribute an `id`, and a
  `pump`: the id of the pump linked to it, or null.

| Service | Who | Data | Response |
|---|---|---|---|
| `crop_steering.stock_draw` | admin; automations and the controller app (Home Assistant's Supervisor user) too, as for `stock_record_batch` | `room_id, key, draws: {tank_id: ml}, source ("dose" \| "batch"), note?` | the `stock_get` answer, with `counted`, `duplicate`, `skipped` (the tank ids it does not know) and `linked` (its tanks linked to a pump, left to the pump's runs) |

`stock_draw` is idempotent on `key` (the stock document keeps the last 100 keys, those of the
pumps' runs among them). It takes ml / 1000 from each named tank no pump is linked to (never below
0), appends a history entry `{at, source, draw_ml, key}` and commits a new revision, which raises
the low-stock Repairs card (CS-608) as usual. Unknown tank ids are skipped and listed in the
response. It answers only when asked (`SupportsResponse.OPTIONAL`): the controller asks, over REST
(`?return_response`); a call without asking (an older controller) is taken all the same.

## The page (Equipment › Dosing)

For the selected room:

- **The tank**: level, full, EC, pH and temperature from the room's tank mapping, and the batch
  state in one line.
- **Stock**: every stock tank a pump is linked to (`stock_tank`), in pump order: its level, its
  litres, about how many batches or doses it has left, its low mark drawn, and a way to
  Equipment › Stock tanks.
- **Pumps**: a card per pump with a peristaltic-pump drawing (the rotor turns while it doses;
  still under reduced motion), its name, a status pill (Idle, Dosing, Unavailable, Not calibrated),
  its flow in mL/s, its last dose (mL, when, result), and a progress bar during a dose (elapsed
  against expected). Its stock tank, found by the pump's `stock_tank` id in
  `sensor.crop_steering_<prefix>stock_low` (never by name), is drawn as a bottle to scale with its
  level, "x.x L of y L" and about how many batches it has left at the pump's recipe amount (or
  doses at its last dose, when the recipe passes the pump by); amber at or under the tank's low
  mark, red at or under half of it. A pump without one says "No stock tank linked".
- **Dose a pump**: the pump, the mL (up to its `max_ml`), the expected seconds, a review, then the
  request; while it runs, the target, the elapsed time, the estimated mL so far, and **Stop**.
- **Make a batch**: the steps with their state, the recipe (mL per pump, the total, the expected
  time), **Make a batch** through a review, and **Stop** while it runs.
- **History**: the last doses and batches.
- **Dosing setup**: the pumps and the batch hardware, from `dosing_get` candidates, and each
  pump's stock tank from `stock_get` (a tank linked to another pump is not offered), saved with
  `dosing_save`. Admins only; everyone else sees it read-only.

A room without pumps shows what dosing does and **Set up dosing**.
