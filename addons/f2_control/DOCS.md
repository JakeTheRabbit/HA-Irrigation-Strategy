# Crop Steering Controller (Jev)

This companion app runs the P0–P3 irrigation decision loop, sequences mapped pump/valve entities, and asks Jev for the judgement calls. Install the Crop Steering integration first; it owns room configuration, sensor mapping and grow-plan storage.

## Install and configure

Follow the [installation guide](https://github.com/JakeTheRabbit/HA-Crop-Steering-Jev/blob/main/docs/INSTALL.md). After installing this app, review Configuration, start it, and open the integration's **Crop Steering** sidebar page. The ingress dashboard is also available. Both serve the same native workspace. Without the Supervisor (Home Assistant Container or Core), run this controller as a container instead: see [Home Assistant Container or Core](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/INSTALL.md#home-assistant-container-or-core).

Use **Equipment › Setup** for mapping and per-zone sizing. Keep engines off while commissioning. Fresh installations create engine controls; existing mapped enable flags are preserved. The legacy default-room helper may still be input_boolean.f2_control_enabled. The room descriptor/heartbeat identifies the actual flag; do not create a second one blindly.

## Jev

Jev is an AI decision model the controller asks when a decision needs judgement rather than a fixed number: when the morning ramp starts and when it is done, whether a probe is telling the truth, whether a shot landed, why pore EC moved, when the day's watering stops, why one zone drinks differently, which alerts deserve a phone push, and, with the room's **Auto setpoints** switch on, whether tomorrow's P2 shots should be a notch smaller or bigger or start a notch later or sooner. The same switch lets this app's own learner keep each zone's P1 target and field capacity at the peak the zone has shown it can reach, at most 2 points higher a day and only after the day's ramp reached the target; Jev never moves those. Code checks every answer against hard limits first. Jev never switches equipment, never stops a safety action, and nothing waits for it. Without a key this app is the plain engine.

- `typesafe_api_key`: a TypeSafe API key (`apikey_...`). Tried first when set.
- `cf_account_id` and `cf_api_token`, with `cf_gateway_id` optional: or Jev through Cloudflare Workers AI (with a TypeSafe key as well, Cloudflare is the second route). Without a TypeSafe key, these start Jev only on an install that has run Jev before (a `jev_` file in the app's data folder). The token needs the **Workers AI** permission: dash.cloudflare.com, My Profile, API Tokens, Create Token, Workers AI template.
- `jev_enabled`: off runs the plain engine even with a key set.
- `jev_judges`: the judges that may act, `all` or a list such as `dawn,ramp,salt,dusk,probe,shot,night,zones,stage,setpoints,alerts`.
- `jev_daily_calls`: the day's call budget across rooms (5000); `jev_budget_warn_pct` raises CS-706 at 80 % of it.
- `jev_retries`, `jev_reask_max`, `jev_unsure_below`, `jev_strict_after`, `jev_strict_prob`: how hard the app tries to reach Jev (3 tries per route), how often it asks again when Jev is unsure (twice, under 0.7), and when a judge goes on the stricter gate (3 bad calls in a row; then it needs 0.8 and an agreeing second look).
- `jev_flower_start`: each room's first day of 12/12, as a date or an input_datetime, for every room or as `room=value` pairs, so Jev knows today's stage.
- `jev_flower_days`: the cultivar's flowering length (56).

Restart the app after changing them. Every decision shows on the dashboard: **Today**, each zone's page, and **History › Timeline**. The [README](https://github.com/JakeTheRabbit/HA-Crop-Steering-Jev#readme) explains it all in plain words; [JEV.md](https://github.com/JakeTheRabbit/HA-Crop-Steering-Jev/blob/main/docs/JEV.md) has every judge and limit.

## Plans and operation

**Plan › Schedule** supports per-zone day/week schedules and explicit vegetative/generative profiles. Saving is draft-only; arming makes a plan eligible at the next local lights-on boundary. It does not enable the engine. Active plans supply atomic versioned targets. Missing or expired required plans hold irrigation, including after restart.

The controller retains source-water/interlock gates, duration/daily-volume caps and hardware state readback. Shared-hardware faults latch until implicated engines and hardware are off. State readback is not proof of physical delivery; verify sensors and actual flow on site.

## Visible targets and water

**Plan › Targets** shows saved and draft targets beside the selected phase, on a graph that also draws the zone's recorded VWC and pore EC and the projected day. **History › Compare runs** overlays retained readings with daily target illustrations or earlier runs aligned by grow age. Stored references are timestamped; Recorder retention determines the available historical data.

Water cards distinguish total substrate capacity from all-plant zone litres and average mL per plant. The runtime calculator includes whole-second timing, the minimum shot and duration cap. Phase estimates also disclose engine parameter limits. New delivery counters use configured flow captured per shot and elapsed runtime, including partial aborts; historical totals are preserved.

## Updating

Update the integration and this app together: both carry the same version number, and the dashboard sidebar shows both, as reported by the running parts. Use **Update** or **Rebuild** to include new Python code; restarting an old image does not rebuild it. Preserve persistent data and export plans before upgrades. See the installation guide for rollback instructions.

The display name is Crop Steering Controller (Jev). The existing f2_control slug remains stable for upgrade compatibility. Local browser/unit checks do not constitute a live HA installation test.
