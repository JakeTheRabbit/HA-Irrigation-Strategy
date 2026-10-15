# Crop Steering Controller

The controller (the Crop Steering Controller app) runs the decisions of the four phases (P0 to P3), and it drives the mapped pump and valve entities in sequence. It can also ask an optional AI assistant to judge some of its decisions. Install the Crop Steering integration first. The integration keeps the setup of each room, the sensor map and the grow plans.

## Install and configure

Follow the [installation guide](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/INSTALL.md). After you install the add-on, examine its Configuration tab. Then start the add-on and open the **Crop Steering** page in the sidebar. The add-on also shows the same dashboard through ingress. Without the Supervisor (Home Assistant Container or Core), run the controller as a container: see [Home Assistant Container or Core](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/INSTALL.md#home-assistant-container-or-core).

Use **Equipment › Setup** to map the hardware and to set the size of each zone. Keep the kill switch of each room off while you commission the room. A new installation makes the kill switch entities. An existing mapped kill switch stays as it is. The kill switch of the old default room can be `input_boolean.f2_control_enabled`. The room descriptor and the heartbeat of the controller show the kill switch in use. Do not make a second kill switch before you examine them.

## AI assistant

The AI assistant is optional. Without it, the controller decides with its own rules, and these rules always stay inside the safety limits. To start the AI assistant:

1. Set `brain_provider` to `claude_haiku`.
2. Put your own Anthropic API key in `anthropic_api_key`. This is a password field: the controller does not show the key, write it to the log or publish it. The dashboard only shows whether a key is set.
3. Restart the controller.

The options of the AI assistant:

- `anthropic_model`: `claude-haiku-5-5` (default), `claude-sonnet-5-5` or `claude-opus-5-5`. Any other model makes the controller use its own rules, because this release does not know the price of that model.
- `anthropic_base_url`: the address of an Anthropic-compatible router, for example `http://router.example.local:20128`. Blank (the default): the controller calls the Anthropic API directly. With an address, the controller sends each call, and your key, to that address, so use only a router that you control. With a router, `anthropic_model` can also have a router prefix, for example `cc/claude-haiku-5-5`; the AI budget uses the price of the model after the prefix. If the router does not answer, the controller uses its own rules for that decision. The log shows the address of the router, never the key.
- `anthropic_daily_budget_usd`: the AI budget, the maximum money that the AI assistant can spend from one lights-on to the next (default US$1.00). When it spends this amount, the controller raises CS-708 and uses its own rules until the next lights-on. A call that timed out or lost its connection can still cost money, so the controller counts a high estimate for it.
- `brain_dry_run`: the AI assistant judges, and the log shows what it would do, but it changes nothing.
- A daily report: 3 h after lights-off, the AI assistant writes a report of the grow-day that ended, in plain words. The report gives the water, the VWC and the pore EC of each zone, what changed, and what to examine the next day. It is on `sensor.crop_steering_<prefix>brain_report`. The report is one call each grow-day, from the AI budget. It only advises.
- `stage_arc`: the stage arc for flower that the AI assistant uses after you set `jev_flower_start` (`slab_default`).
- In a room with a `feed_ec_sensor`, the feed task examines the feed one time each grow-day, 1 h after lights-on. It can propose a change on a CS-711 card. It never changes the feed or the dosing: a person decides.
- When the AI assistant fails, the controller runs exactly as on rules, and the Auto setpoints learner continues. Examples are no key, a refused key, no answer from Anthropic, a refused question and an AI budget that is spent. The AI assistant panel on the dashboard shows the reason.
- The AI assistant sends readings and settings to Anthropic, and the room and zone names that you typed. It never sends an entity ID, a key or personal data. On 32-bit ARM (armv7), the AI assistant is not available: the controller uses rules and shows that.

`brain_provider` has the default `auto`. With `auto`, an install that already uses a retired Jev route keeps that route, and all other installs use rules. `auto` never selects Claude. `rules` always means rules.

### Judges

A judge is one question that the AI assistant answers about one decision of the controller. The controller examines each answer against hard limits first. A judge never switches equipment and never stops a safety action, and no shot waits for a judge. `jev_judges` sets which judges and tasks the AI assistant asks: `all` (default), or a list of names with a comma between each name. The controller ignores a name that it does not know.

- `dawn`: in P0, has the morning dryback gone far enough to start the ramp? It can only start the ramp (P1) sooner.
- `ramp`: in P1, is the ramp complete? It can only start maintenance (P2) sooner, after the minimum ramp shots.
- `salt`: in P2, why is pore EC at its current value? It selects the mode of the EC steer (steer, hold or decay), inside the limits of the EC steer.
- `dusk`: in P2, when must the shots of the grow-day stop? It can only start the overnight dryback (P3) sooner, in the last 3 h before lights-off. The rescue shot still fires.
- `night`: in P3, does VWC fall toward the rescue floor because the slab dries, or because of the probe? It only advises, with CS-703, and it never stops a rescue shot.
- `probe`: does the probe of this zone give true readings? It can set the probe aside (CS-704), but only after two answers in a row that agree and a check of the shots by the controller.
- `shot`: did the water of a shot get to the zone? It only advises. When two shots in a row did not get to the zone, it raises CS-701.
- `zones`: why does one zone get a different quantity of water from the other zones? It only advises, with CS-702.
- `channel`: does the water go past the substrate or the probe, or do the plants drink less? It only advises, with CS-710, and it never adds water.
- `stage`: does this zone follow the stage arc for today's day of flower? It only advises, with CS-705. It works only with a flower start in `jev_flower_start`.
- `setpoints`: what one change to the maintenance shots of the zone is best for tomorrow? It can move the maintenance shot size or the re-water point by one notch each grow-day. It acts only while the Auto setpoints switch of the room is on and no grow plan controls the room. A rescue shot within 30 h after a change puts the old value back.
- `balance`: late in P2, must this zone move toward the water for each plant of the room? It only advises the setpoints judge of that night.
- `feed`: must the feed of the room change? It only advises a person, with CS-711.
- `report`: the daily report above.
- `why`: the answers to the "why" questions that you ask on the dashboard.
- `plan`: what does the most important difference between the grow plan and the room mean? It selects the suggestion that the dashboard shows. The controller raises CS-713 for the difference.

`balance`, `feed`, `report`, `why` and `plan` work only with `claude_haiku`. The same Auto setpoints switch also lets the learner of the controller move the peak target and the field capacity of each zone toward the highest VWC that the zone gets. Each of the two moves 1 point or less each grow-day. The judges never move these two values.

### Retired Jev routes

Jev is the retired AI model of the AI assistant. An install that has a Jev route keeps it (`brain_provider: auto` or `jev_legacy`). These routes get no new features, and the controller shows a CS-712 card one time for each release. A new install uses the AI assistant above.

- `typesafe_api_key`: a TypeSafe API key (`apikey_...`). The controller tries it first when it is set.
- `cf_account_id` and `cf_api_token`, with `cf_gateway_id` (optional): Jev through Cloudflare Workers AI. With a TypeSafe key, Cloudflare is the second route. Without a TypeSafe key, these options start Jev only in two cases. One is an install that used Jev before (a `jev_` file in the data folder of the controller). The other is `brain_provider: jev_legacy`. The token needs the **Workers AI** permission: dash.cloudflare.com, My Profile, API Tokens, Create Token, Workers AI template.
- `jev_enabled`: off makes the controller use rules, also when a key is set.
- `jev_daily_calls`: the maximum number of calls in one day, for all rooms together (5000). `jev_budget_warn_pct` raises CS-706 at 80% of it.
- `jev_retries`, `jev_reask_max`, `jev_unsure_below`, `jev_strict_after` and `jev_strict_prob` set these values:
  - The number of tries for each route (3).
  - How many times the AI assistant asks again when an answer is unsure (2, below 0.7).
  - When a judge goes on the stricter gate (after 3 bad calls in a row). On that gate, an answer needs 0.8 and the same sure call two times in a row.
- `jev_flower_start`: the first day of 12/12 for each room, as a date or an input_datetime. Give one value for all rooms, or `room=value` pairs. The judges then know the stage of flower.
- `jev_flower_days`: the length of flower of the cultivar (56).

Restart the controller after a change to these options. The dashboard shows each decision: on **Today**, on the page of each zone, and on **History › Timeline**. The [README](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy#readme) gives a plain-words description. [JEV.md](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/main/docs/JEV.md) gives each judge and each limit.

## Plans and operation

On **Plan › Schedule**, you can set a schedule for each zone by day or by week, and vegetative or generative profiles. When you save a plan, it is a draft only. When you arm a plan, the plan can start at the next local lights-on. An armed plan does not set the kill switch to on. An active plan supplies its targets as one versioned set. When a necessary plan is missing or expired, the controller holds the shots, also after a restart.

The controller keeps the source-water gate, the hold entities, the limits on shot time and daily water, and the readback of the hardware state. A fault on shared hardware stays latched until the kill switch of each room that it affects and the hardware are off. The readback of a state does not prove that water got to the plants. Examine the sensors and the real flow in the room.

## Visible targets and water

**Plan › Targets** shows the saved targets and the draft targets next to the selected phase. The graph also shows the recorded VWC and pore EC of the zone and the forecast for the day. **History › Compare runs** shows the recorded readings over the daily targets, or over earlier runs at the same grow age. The stored references have a timestamp. The Recorder retention sets how much history is available.

The water cards show the total substrate volume, the litres of all plants of the zone, and the average mL for each plant. The runtime calculator uses whole seconds, the minimum shot and the maximum shot time. The phase estimates also show the limits of the controller settings. New delivery counters use the configured flow at each shot and the real run time, also for a shot that stopped early. The controller keeps the historical totals.

## Updating

Update the integration and the add-on together. They have the same version number, and the dashboard sidebar shows the version of each running part. Use **Update** or **Rebuild** to get the new Python code. A restart of an old image does not rebuild it. Keep the persistent data, and export the plans before an upgrade. The installation guide gives the steps to go back to an earlier version.

The display name is Crop Steering Controller. The slug stays `f2_control` so that an upgrade in place works. A local browser test or unit test is not a test of a live Home Assistant installation.
