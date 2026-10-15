# Dryback planner and Jev line steering: delivery roadmap

**Spec:** [docs/superpowers/specs/2026-10-02-dryback-planner-jev-steering-design.md](../specs/2026-10-02-dryback-planner-jev-steering-design.md), approved by the owner on 2 Oct 2026, including the amendment that Jev is used maximally.

The spec is delivered as seven steps. Steps 1 and 2 have full implementation plans (below). Each later plan is written once the plan before it has merged into `testing`, against the code as it then is: every later plan builds on names the earlier ones create, and on what their soak shows. This page fixes those names now, so the plans agree.

## Delivery

One change, one branch, one pull request, into `testing`. Classes and soaks follow [docs/RELEASING.md](../../RELEASING.md): a C3 candidate soaks 7 days on staging with every fault drill and a seeded upgrade fixture, and a candidate carries at most one C2 or C3 change.

| # | Plan | Class | Needs | What goes live |
| --- | --- | --- | --- | --- |
| 1 | [Remember nights and plateaus](2026-10-02-dryback-01-remember-nights.md) | C3 (state file) | nothing | Every zone records its daily plateau and each night's landing. The activity feed shows the morning record. No watering decision changes. |
| 2 | [Jev availability](2026-10-02-dryback-02-jev-availability.md) | C3 (add-on options) | nothing | Both routes to Jev (TypeSafe, then Cloudflare), retries, stale questions dropped, re-asks when Jev is unsure, the stricter gate after a bad run, a 5000-call budget with a push at 80 %. Applies to today's judges. |
| 3 | P1 plateau | C3 | 1, 2 | Engine input `plateau_reached`; `plateau.py`; the per-zone `line_steering` switch and the `p1_max_minutes` and `plateau_ceiling` numbers; the Steer judge's P1 variant sizes and spaces the ramp shots and calls the plateau. Switched zones only. |
| 4a | The line, Steer, the P2 end and the night | C3 | 1, 2, 3 | `line.py`, `tracker.py`, `p2_end.py`, `night.py`; engine inputs `p2_end_at`, `final_shot_pct`, `night_correction_pct` and the machine-gun guard; the Steer judge's day, P2-end and night variants; Dawn, Ramp, Salt, Dusk and Night not asked on switched zones; Setpoints retired there; each zone publishes its line, P2-end plan, last landing, clean-night streak and Jev's score. |
| 4b | Dashboard: the line and the previous run | C1 | 4a | The line layer and a P2-end marker on the day chart, using the layer toggles from #29, and Jev's calls on the Jev layer. **The previous run stays on the chart:** yesterday's actual VWC and pore EC, with yesterday's line and where it landed, drawn on the same clock as the compare layer (#28 draws it even when the room was off), so each day reads against the last. |
| 5 | Jev's daily and weekly jobs | C3 | 4a | The `plan`, `report` and `review` judges, and a stage proposal on the Stage judge. |
| 6 | F2 zone order | operations | 4a | Zone 1 first, then zone 3; zone 2 once the Probe judge trusts its probe. Switch flips, no code. |
| 7 | Room conditions (stage 2) | C3 | 4a | The environment entities in the room descriptor, the deliberate change to the guard in `tests/test_translations.py:141-158`, and Jev's ±20 % night-rate scale. |

Plans 1 and 2 are independent. Plan 1 goes first: it changes no decision, and every day it soaks is a recorded night that plan 4a's P2-end menu reads.

## Shared names

### State, from plan 1 (per zone in `/data/state.json`)

- `plateau_hist`: a list, newest last, at most 14 entries: `{"date", "value", "how", "shots"}`. `date` is the grow day (ISO), `value` the VWC P1 reached (the zone's `peak` when P1 handed over to P2), `how` what ended P1 (the engine's reason, "Jev's ramp judge: ...", or "set by hand"). Plan 3 adds `"rule"` and `"ec_turned"`; old entries lack them, so readers use `.get()`.
- `night_hist`: a list, newest last, at most 14 entries: `{"date", "plateau", "off_at", "off_vwc", "on_at", "on_vwc", "first_at", "landing", "night_rate", "p0_drop", "dryback_pct", "night_shots"}`. `date` is the grow day of the morning; `landing` the VWC just before the day's first shot (Athena p.39); `night_rate` points an hour from lights-off to lights-on, or to the first shot before lights-on; `night_shots` every shot between lights-off and the first shot. Unknown numbers are `null`. Plan 4a adds `"target"`, `"clean"` and `"net_fired"`.
- `night`: the night being measured, or `null`.
- `addons/f2_control/f2_control/zone_history.py`: `KEEP`, `fresh()`, `restore(saved)`, `plateau(st, *, day, value, how, shots)`, `phase_changed(st, was, new, *, day, how)`, `lights_off(st, vwc, now, day)`, `lights_on(st, vwc, now)`, `shot(st, *, vwc_before, now, day, first)`, `night_words(record)`.
- `Controller._record_phase(room, zone, st, was, new, now, how)`: called wherever P1 can hand over to P2 (the engine, a Jev judge's `advance`, the operator's Set Phase). The dead-probe time transitions only ever move to P3 or P0.

The spec's state list also names a "bench-until" field. The 2 Oct amendment removed the bench (Jev keeps steering on the stricter gate), and plan 2 reads the gate from the ledger, so there is no such field.

### Jev runtime, from plan 2

- `jev/client.py`: `NO_REQUESTS`, `NOT_JSON`, `NO_ANSWERS`; `retryable(error)`; `Route(name, fn, account, token, gateway=None)`; `Routes(routes, tries=3, window_s=60.0, sleep=time.sleep, clock=time.monotonic)`, a transport whose usage carries `route`, `failover` and `retries`; `Asker(..., daily_budget=5000, warn_pct=80, max_wait_s=300.0)` with `note(stat)` and `take_warning()`, and daily stats `retries`, `failovers`, `reasks` and `warned` (plus `route`, the last route that answered).
- `jev/ledger.py`: `Ledger.strict(judge, room, zone, after=3, clear=2)`.
- `jev/brain.py`: `Brain(..., reask_max=2, unsure_below=0.7, strict_after=3, strict_prob=0.8)`; `JudgeState.reask_due` and `JudgeState.reasks`; `Brain.events`, a list of `("strict", room, zone, judge)`; `Brain.strict`, `{(room, zone, judge): bool}`.
- `jev/judges/base.py`: `Judge.more_evidence(ctx, verdicts)`. Plan 4a's Steer judge overrides it with the last 3 days, the sibling zones and the doctrine excerpt.
- `jev_bridge.build()` stores `brain.routes`, the route names in the order they are tried.
- Add-on options: `jev_daily_calls` (default 5000), `jev_budget_warn_pct` (80), `jev_retries` (3), `jev_reask_max` (2), `jev_unsure_below` (0.7), `jev_strict_after` (3), `jev_strict_prob` (0.8).
- Error codes: CS-706 (Jev has used most of today's calls) and CS-707 (Jev is on the stricter gate for a zone), both in the `jev` notification kind. Later plans number from CS-708.

### Engine and integration, from plans 3 and 4a

- Every new engine input is neutral by default, and a golden test proves that with every one at its default each decision equals today's.
  - Plan 3: `ZoneSnapshot.plateau_reached: bool = False`.
  - Plan 4a: the P2 end (`p2_end_at` and `final_shot_pct`), `night_correction_pct`, and the machine-gun guard (a minimum gap and an hourly cap on `ZoneParams`, with a `shots_last_hour` snapshot field). Plan 4a fixes their types against `core.py` as it then is.
  - Each new `Reason` kind (plan 3: `p1_plateau`; plan 4a: `p2_final` and `p3_correction`) is added to `CAP_EXEMPT` (`core.py:38`), and the agreed exempt set pinned in `crop-steering-engine/tests/test_day_structure.py:45-47` is changed on purpose in the same commit.
- Integration (plan 3): `switch.crop_steering_{prefix}zone_{n}_line_steering` (off by default), `number.crop_steering_{prefix}zone_{n}_p1_max_minutes` (150) and `number.crop_steering_{prefix}zone_{n}_plateau_ceiling` (90), each with a `tests_ha/` test.
- Jev judges: `steer` (plan 3: the P1 variant; plan 4a: the day, P2-end and night variants), and `plan`, `report` and `review` (plan 5).

## Live checks per step

- **Plan 1:** the morning after it is installed, the activity feed shows a line "Zn night: landed ..." for each zone, and the add-on log shows each zone's plateau when its ramp hands over.
- **Plan 2:** `sensor.crop_steering_jev` shows `routes`, `retries_today`, `failovers_today`, `reasks_today`, `daily_budget` and `strict`. F2's options keep `jev_daily_calls: 2000` until the owner raises it to 5000 in the app's options, and the Cloudflare route exists only once `cf_account_id` and `cf_api_token` are set there (F2 runs on the TypeSafe key alone today). Until the box's integration is updated too (it was still 3.6.0 on 30 Sep), the notification router does not know CS-706 and CS-707 and files them under Setup and settings.
