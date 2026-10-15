# Notifications: who gets which alerts

Every alert still becomes a Home Assistant notification card, as before. What this adds is **who gets a
phone push for what**: each phone has a row of checkboxes (stock tanks, emergencies, sensors and drift,
phase changes, hardware lockouts, watering stopped, and so on), and a push goes only to the phones whose
row ticks that kind of alert. It also adds the events a person can now subscribe to that were never
alerts: phase changes, Jev's setting changes, and "no watering for a while".

This document is the contract between the three layers. Nothing in it names a site's phones or people.

## Layers

| Layer | Owns | Never does |
|---|---|---|
| Integration | The site's notification setup (one store for the whole site, not per room); the list of phones; the services to read, save, test and send; routing each push to the phones that want it | Push anything nobody ticked (except the fallback below) |
| Controller app | Raising alerts (unchanged) and the new events; handing each push to `crop_steering.notify`; the fallback to its old `notify_service` option | Decide who gets what |
| Dashboard | Settings & help › Notifications: the checkbox grid, each phone's rooms, a test push per phone, the watering-stopped threshold | Call a notify service itself |

## The kinds of alert (the checkboxes)

A code can be in more than one kind (CS-301 is an emergency and a hardware lockout); a phone that ticks
either gets it once.

| Id | Checkbox | What it covers |
|---|---|---|
| `emergency` | Emergencies | Every alert whose severity is critical in docs/error-codes.json (CS-201 to 204, 207, 301, 308, 310, 311, 402, 601, 606, 801) |
| `hardware` | Hardware lockouts | CS-301 to CS-309 (a pump or valve that did not do what it was told, a hardware hold, a shot cut), CS-310 (moisture rising with no water: a table not draining), CS-311 (the sump pump has not run) and CS-701 (water isn't reaching a zone) |
| `sensors` | Sensors and drift | CS-101 to CS-104, CS-603, CS-604, CS-703, CS-704 |
| `watering` | Watering stopped | CS-202 to CS-208, CS-602, and **CS-209** (new: no watering for a while) |
| `phases` | Phase changes | A zone moving P0 → P1 → P2 → P3 (new event, no card) |
| `stock` | Stock tanks | CS-608, CS-807 |
| `dosing` | Dosing | CS-801 to CS-806 |
| `jev` | Jev | CS-501, CS-702, CS-705, CS-706, CS-707, CS-404, and Jev moving a setting (new event, no card) |
| `setup` | Setup and settings | CS-201, CS-401 to CS-405 (except 404), CS-601, CS-605, CS-606, CS-607 |

The mapping lives in one place in the integration (`notify_catalog.py`) and is returned by `notify_get`,
so the page shows exactly what each checkbox covers. A code the catalog does not know goes to
`emergency` when its severity is critical, else to `setup`; a test fails when a code in
docs/error-codes.json is in no kind at all.

## New events

- **Phase change** (`event: "phase"`): the controller sends one when a zone's phase changes, with the room,
  zone, from and to (for example "F2 · Zone 2: P1 → P2, ramp target reached"). No card; a push only.
- **Jev setting change** (`event: "jev_setpoint"`): when Jev moves a zone's P2 shot size or re-water point
  (docs/JEV.md). No card; a push only.
- **CS-209 No watering for a while** (a card and a push): a room that is active, with lights on, has watered
  nothing for `idle_hours` (default 3, set on the page, 1 to 12): no shot fired in any of its zones, whether
  because watering is switched off, a hold, or nothing called for water. Raised once per stretch and again
  every `idle_hours` while it lasts; cleared by the next shot, or once the room leaves the condition
  (lights off, no zone in P1 or P2, the room switched off). A zone in P0 (the morning dry-back) or in
  P3 does not start the clock; the clock runs only while at least one zone is in P1 or P2.

## Configuration (integration store `crop_steering.notify`, one for the site)

```jsonc
{
  "revision": 3,
  "idle_hours": 3,
  "recipients": [
    {
      "service": "notify.mobile_app_pixel_7",   // any notify.* service; the page offers the site's phones first
      "name": "Callum's phone",                   // shown on the page; defaults to the device name
      "user_id": "7f21…",                         // the Home Assistant user the phone belongs to, when known
      "kinds": ["stock", "dosing"],               // ids from the table above
      "rooms": [],                                // room prefixes ("" = the default room, "f1_"); empty = every room
      "urgent_high_priority": true                // emergencies go out as high-priority / time-sensitive pushes
    }
  ]
}
```

A phone is a `notify.mobile_app_*` service. The integration lists them with their device name and the
Home Assistant user that registered the app (the mobile_app config entry's user), so each row shows whose
phone it is. Other notify services (a group, Supernotify) can be added as rows by their service name.

A save checks every row: `service` is `notify.<name>`, each service once, at most 20 rows; a phone added
now must be a notify service Home Assistant has, while one saved before may be away (an app not registered
again since a restart never blocks a save); `kinds` are ids from the table; `rooms` are room prefixes;
`urgent_high_priority` is true when left out; `idle_hours` is 1 to 12. A row an administrator saves
without a `name` or a `user_id` takes them from the phone's mobile_app registration.

`sensor.crop_steering_notify_config` is written by the integration with the first room that loads and
removed with the last (it is not a registry entity): state the revision, attributes `recipients` (how many
rows) and `idle_hours`. While the store can't be read it is `unavailable`, with `error`, and the
controller pushes as with no recipients; Home Assistant's log says so at start-up. A kind a row names that
this version does not know (saved by a newer one, before a rollback) is dropped when the store is read,
not the whole setup.

## Services

| Service | Who | Data | Response |
|---|---|---|---|
| `crop_steering.notify_get` | any signed-in user | none | `{schema_version: 1, config, kinds[{id, name, detail, codes[], events[]}], phones[{service, name, user_id, user_name}], can_edit_all, user_id}` |
| `crop_steering.notify_save` | admin: any row; a non-admin: only rows whose `user_id` is their own (they cannot add or remove rows) | `expected_revision, recipients, idle_hours?` | as `notify_get`, or `error` ("revision", "not allowed: …", a readable message) |
| `crop_steering.notify_test` | admin, or the phone's own user | `service` | `{sent: true}` or `error` |
| `crop_steering.notify` | admin (the controller) | `key, code?, event?, room?, zone?, title, message, urgent?` | `{sent_to[], error}` |

- `notify` works out the push's kinds from `code` (the catalog) or `event`, then sends to every recipient
  that ticks one of them and whose `rooms` is empty or includes `room`, once per service. A push about no
  room in particular (no `room`: the controller's dosing thread, its clock) goes to every recipient that
  ticks one of its kinds. `urgent` (the controller sets it for critical codes) adds the high-priority data
  for a recipient with `urgent_high_priority`: Android
  `{"priority": "high", "channel": "Crop Steering urgent"}`, iOS
  `{"push": {"interruption-level": "time-sensitive"}}`, both in the same `data` (each app ignores the
  other's keys; `data` is sent to mobile_app services only).
  Every push carries `data.tag = key`, so a repeat replaces the earlier one on the phone instead of piling up,
  and the link that opens the Crop Steering panel when it is tapped (`url` for iOS, `clickAction` for
  Android, both `/crop-steering`).
- A failed send to one phone never stops the others; failures are listed in the response and logged. A
  phone that has not answered in 8 s counts as failed.
- With no recipients saved, or a store that can't be read, `notify` sends nothing and says why in `error`
  ("no phone is set up for notifications"). A push nobody ticked answers `{sent_to: [], error: null}`: it
  went to nobody on purpose. The controller falls back only when nothing was sent and `error` says why.
- **An emergency always reaches someone.** An `urgent` push that no row covers for its room goes to every
  row that ticks `emergency`, whatever its rooms (logged as a warning); with no such row at all it answers
  `{sent_to: [], error: "no phone takes emergencies"}`, and the controller pushes it to its
  `notify_service` option.
- `sent_to` lists the phones Home Assistant's notify service accepted the push for. It is not proof of
  delivery: the mobile_app relay's own failures (rate limit, relay errors) are only in Home Assistant's log.
- Who, in detail: `notify_get` answers anyone, as every read in this integration does (`can_edit_all` is
  false without a signed-in administrator); a call with no user (an automation) saves and tests as an
  administrator, as for every service that changes something; a user id Home Assistant does not know may
  neither save nor test. `notify_get` and `notify_save` answer `error` too (null when all is well).
- A non-administrator's save is matched to the stored rows by `service`, in any order. For a row that is
  not theirs, its kinds, rooms and high-priority flag must come back unchanged; for their own, only those
  three change. They may not change `idle_hours`, which is the site's.
- `notify_test` sends at normal priority, with `data.tag = "crop_steering_test"`, and says what the phone's
  row ticks.
- The integration's own Repairs cards (CS-601 to CS-608) go out through `notify` when a card is created,
  with key = its issue id, its room, and the card's own title and text; not when a card still raised is
  updated, or raised again after Home Assistant restarts, and not again within 30 minutes when a card
  clears and comes back (a probe going on and off line), as the controller repeats an alert. The 30 minutes
  start only once a phone has the push: one that reached nobody is pushed again when the card comes back.

## The controller

- `_alert` still creates the card first, exactly as now, and Jev's Alerts judge still decides whether a
  repeat pushes at all (docs/JEV.md). When it pushes:
  - with at least one recipient saved (the integration publishes `sensor.crop_steering_notify_config`,
    state = the revision, attribute `recipients` = the count), it calls `crop_steering.notify` and sends
    nothing itself;
  - with no recipients saved, when that call fails, or when an emergency reached no phone through it, it
    pushes to its `notify_service` option as it always has, so an install that never opens the page
    behaves exactly as before, and a push is never lost. With that option empty too, the controller's log
    says the push went to no phone.
- Phase changes and Jev's setting changes are sent through `crop_steering.notify` only (never the fallback:
  they are not alerts).
- CS-209 is raised by the controller like any alert (key `idle_<room>`), with its code written out.

In detail:

- Jev's Alerts judge is asked whenever a phone could get the push: a recipient saved, or the
  `notify_service` option set (as before). A repeat it holds goes to nobody.
- The controller's loop reads `sensor.crop_steering_notify_config` at most once a minute, so a change on the
  page reaches it within a minute; an alert goes on the last reading and never waits on the read. No sensor
  (an integration from before this) counts as no recipients.
- `urgent` is set for the codes written out in the controller's `CRITICAL_CODES`, which a test keeps equal
  to the critical codes of docs/error-codes.json.
- The call asks for the service's answer and waits up to 12 s, as a push to `notify_service` always could.
  It counts as failed when Home Assistant can't be reached or does not answer in time, answers 4xx or 5xx,
  or answers that nothing was sent with an `error`; a push nobody ticked is not a failure, unless it is an
  emergency (a critical code): that one counts as failed whenever it reached no phone.
- The vitals report (every `notify_min` minutes) is not an alert: it still goes to `notify_service` only.
- Events are queued during a loop and sent after its shots, so a slow Home Assistant never holds one up: one
  push per room and kind (lights-off moves every zone at once), all of them within 10 s
  (`EVENTS_BUDGET_S`). An event that fails, or is left when the time is up, is dropped, never retried and
  never sent to `notify_service`. A zone's phase change on its own is key `phase_<room>_z<zone>`, title
  "F2 · Zone 2: P1 → P2" and message why: the engine's own reason ("lights-off -> P3"), "set by hand",
  "Jev's ramp judge: …", or "lights-off (no moisture reading)" for a zone without a probe. Several in one
  loop are key `phase_<room>`, title "F2: phase changes" and a line per zone ("Zone 1: P2 → P3, lights-off
  -> P3"). Jev's move is key `jev_setpoint_<room>_z<zone>`, title "F2 · Zone 1: Jev changed P2 shot 5% ->
  4.5%" and message the change in words with Jev's answer and probability; several are "F2: settings Jev
  changed", a line per zone.
- An alert raised while hardware may still be on is raised after it is switched off (a pump whose turn_on
  errored, CS-302; a batch's mix pump that did not start, CS-805), as its push can take a while.
- CS-209's clock starts, as far as can be told, after the last loop that saw the room not meeting the
  condition, after today's lights-on, and after the first zone now in P1 or P2 moved there; a shot in any
  zone restarts it. After a restart that is what the saved state says, so a restart does not reset it.
  `idle_hours` is kept inside 1 to 12, and is 3 when the integration publishes none: CS-209 is raised on
  every install. The message says why when it can: watering switched off (the room's engine switch), a hold
  (each zone's reason from the controller's gates), or nothing called for water.

## The page (Settings & help › Notifications)

- A grid: a row per phone (the owner's name and the device), a column per kind with a checkbox, the rooms
  it covers (all, or ticked rooms), high priority for emergencies, and **Send a test**. On a phone the grid
  becomes a card per phone with its checkboxes.
- Each column's heading opens what it covers: its codes with their titles, and its events.
- **Add a phone** (admins): from the site's phones not yet listed, or a notify service by name.
- The watering-stopped threshold: "Tell me when a room has watered nothing for [3] hours with the lights on".
- A non-admin sees every row but can tick only their own phones'; an admin edits everything. Changes are a
  draft until **Save**, with a review of what changes, like the other pages.
- A room of the site with no row ticking `emergency` shows a warning: "Nobody gets emergencies for F1", and
  says where they go instead: every phone that gets emergencies, or the controller app's `notify_service`
  option when none does.
