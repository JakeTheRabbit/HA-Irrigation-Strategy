# AI assistant

The AI assistant is optional. It judges the decisions of the controller that need a grower's judgement. The code of the controller keeps control of the pump, the valves, the shot sizes and all the safety limits.

The AI assistant uses Claude from Anthropic, with your own API key. Anthropic bills you for each question. Without the AI assistant, the controller uses its rules, and the rules are always safe.

This page tells how the AI assistant works, which options control it, and what it can change. [INSTALL.md](INSTALL.md#optional-ai-assistant) gives the short procedure to start it.

## How the AI assistant works

1. The controller reads the probes of each zone each minute and decides each shot with its rules.
2. When a decision needs judgement, the controller asks a judge in the background. A judge is one question about one decision. An example is "Is the substrate full?".
3. The control loop never waits for the answer. It uses the last answer that it has, or its rules.
4. Each question has the readings and the settings of the zone, the stage of the day, and the doctrine pack (`doctrine/`). The code calculates the facts. The AI assistant does only the judgement.
5. The controller asks each judge in two phrasings. An answer acts only when the two phrasings agree.
6. The code then admits or refuses the answer against the safety limits. The dashboard shows the answer, the confidence and what the controller did.
7. Later, the code measures the result. The AI assistant sees its own record the next time that it answers.

**What the controller sends.** Each question has the readings and the settings of the zone, and the stage of the day. It also has the room and zone names that you typed. It never sends an entity ID, a key or personal data.

## Start the AI assistant

For the app:

1. Get an API key at console.anthropic.com, under **API keys**.
2. Open **Settings → Apps → Crop Steering Controller → Configuration**.
3. Set `brain_provider` to `claude_haiku`.
4. Put the key in `anthropic_api_key`.
5. Set `anthropic_daily_budget_usd` to the most that you want to spend in one grow-day.
6. Restart the app.

The log then shows `brain: claude_haiku`, the model, the budget, `key set` and the judges. It never shows the key.

For a container, set `F2_OPT_BRAIN_PROVIDER=claude_haiku`. Give the key in `F2_OPT_ANTHROPIC_API_KEY_FILE` (a Docker secret) or in `F2_OPT_ANTHROPIC_API_KEY`. When neither is set, the controller also reads the usual `ANTHROPIC_API_KEY` variable.

For a container with a Docker secret:

1. Put the key in a file next to `docker-compose.yml`, for example `anthropic_key.txt`.
2. Add the file as a Docker secret.
3. Set `F2_OPT_BRAIN_PROVIDER=claude_haiku`.
4. Set `F2_OPT_ANTHROPIC_API_KEY_FILE=/run/secrets/anthropic_key`.
5. Run `docker compose up -d`. The log shows `anthropic_api_key=<set>`.

> **CAUTION:** Set `brain_dry_run` to on for the first grow-days with a new AI assistant. Then read its decisions before you let it act. A judgement that you did not examine can change when the shots start and stop.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `brain_provider` | `auto` | `rules`: no AI assistant. `claude_haiku`: the AI assistant with your Anthropic key. `auto`: rules, except on an install that used the first AI route (below), which moves to Claude. `jev_legacy`: the old name of the first AI route, read the same way. |
| `anthropic_api_key` | empty | Your Anthropic API key. It is a password field. The controller never shows, logs or publishes it. Empty: rules. |
| `anthropic_model` | `claude-haiku-5-5` | Also `claude-sonnet-5-5` or `claude-opus-5-5`. A larger model costs more for each call. With another model name, the controller uses its rules, because it does not know the price. |
| `anthropic_base_url` | empty | The address of an Anthropic-compatible router, for example `http://router.example.local:20128`. Empty: the Anthropic API. |
| `anthropic_daily_budget_usd` | 1.0 (US$1.00) | The AI budget: the most that the AI assistant can spend from one lights-on to the next. The limits are 0 and 1000. With 0, the AI assistant never asks. |
| `brain_dry_run` | off | On: the AI assistant judges, and the log and the dashboard show what it would do. It changes nothing. |
| `ai_judges` | `all` | The judges and tasks that the AI assistant asks: `all`, or a list of names with a comma between each name. |
| `ai_daily_calls` | 5000 | The maximum number of calls in one calendar day, for all rooms together. |
| `ai_budget_warn_pct` | 80 | The share of the daily calls, or of the AI budget, at which the controller raises CS-706. |
| `ai_reask_max` | 2 | The maximum number of second looks, with more evidence, when an answer is unsure. 0: no second look. |
| `ai_unsure_below` | 0.7 | An answer with a probability below this value is unsure. An answer is also unsure when its two phrasings do not agree. |
| `ai_strict_after` | 3 | The number of bad calls in a row by one judge for a zone before the stricter gate (CS-707). |
| `ai_strict_prob` | 0.8 | The minimum probability of each answer that acts on the stricter gate. |
| `stage_arc` | `slab_default` | The stage arc for flower. `slab_default` is the only stage arc in this release. |
| `ai_flower_start` | empty | The first day of 12/12 for each room: a date (YYYY-MM-DD) or an `input_datetime` helper. For more than one room, use `room=value` pairs. Without it, the judges use no stage. |
| `ai_flower_days` | 56 | The flower length of the cultivar. The finish is the last 14 days. |

### Old option names

Before the first AI route was removed, these options started with `jev_` (for example `jev_daily_calls`). An old options file loads unchanged:

- Each old `jev_` tuning option is read as the old name of its `ai_` option. The Supervisor fills in each new option with its default when the app updates, so the controller uses the old value while the new option still has its default. A value that you set in the new option wins.
- `jev_judges` is read only while `ai_judges` is `all`. A list there was written for the first AI route. When every name in it was a judge at that time, the controller reads it as `all`, and the log names once the judges that this adds (for example `ramp`). A list that names a judge that no release had is used as a list. To ask fewer judges, put the list in `ai_judges`.

### The router

With `anthropic_base_url`, the controller sends each question to an Anthropic-compatible router, and not to the Anthropic API. The router must accept the Messages API.

- The controller sends the key in `anthropic_api_key` to the router. Use the key that the router needs.
- With a router, `anthropic_model` can have a router prefix before the model name, for example `cc/claude-haiku-5-5`. The AI budget uses the price of the model after the prefix.
- The address must start with `http://` or `https://`. With another address, the controller uses its rules and the AI assistant panel tells why.
- If the router does not answer, the controller uses its rules.

> **WARNING:** Use only a router that you control. The controller sends your API key to the address in `anthropic_base_url`. A router that another person controls can read and use your key.

### The AI budget

The AI budget limits the cost of one grow-day. A grow-day starts at lights-on. The controller counts the cost of each answer at the price of its model. A question that timed out can still cost money, so the controller counts a high estimate for it.

At `ai_budget_warn_pct` of the budget, the controller raises CS-706. When the budget is spent, the controller raises CS-708 and uses its rules until the next lights-on. The AI assistant panel shows the cost of today and the budget.

The call limit in `ai_daily_calls` also applies. It resets at midnight.

### Dry run

With `brain_dry_run` on, the AI assistant asks each judge and spends the AI budget. The code admits or refuses each answer as usual. An answer that would act is recorded as "would act". The controller then uses its rules for that decision. The alerts from the judges still come through.

## The judges and the tasks

A judge is one question about one decision of one zone. A task is a question about the room. The name in bold is the name on the dashboard. The name in brackets is the name in `ai_judges`.

| Judge | When the controller asks | The question | What the controller can do with the answer |
| --- | --- | --- | --- |
| **Morning start** (`dawn`) | P0, each 10 min | Is the morning dryback large enough to start the ramp? | Start the ramp earlier. Never later than the rules. |
| **Ramp hand-over** (`ramp`) | P1, each 15 min | Is the substrate full, or does the EC increase only because new feed flows past the probe? | Start maintenance earlier. |
| **Pore EC** (`salt`) | P2, each 30 min, only when EC stacking is on | Why did the pore EC change? | Let EC stacking move the re-water point, hold it, or move it back, inside its limits. |
| **Day end** (`dusk`) | The last 3 h before lights-off | Must the shots of today stop now? | Start P3 earlier. Only for a zone with generative steering. |
| **Probe trust** (`probe`) | Each 30 min, after two shots | Is this probe correct, or is it stuck, drifting, out of the block or in the wrong zone? | Set the probe aside. The zone then copies a healthy zone, or uses its timer. |
| **Shot landing** (`shot`) | 20 min after each shot | Did the water get to the zone? | Send alert CS-701 after two misses in sequence. It never adds water. |
| **Night low** (`night`) | Overnight, near the rescue floor | Is the substrate dry, or is the probe defective? | Send alert CS-703. The rescue shot still occurs. |
| **Zone comparison** (`zones`) | When the water of a zone is far from the other zones | Why does this zone get much more or much less water? | Send alert CS-702 with the probable cause. |
| Water channel (`channel`) | With the lights on, a maximum of one time each hour | Does the water flow past the substrate or the probe? | Send alert CS-710, which asks for a catch test. It never adds water. |
| **Stage arc** (`stage`) | One time each grow-day | Are the dryback and the pore EC of the zone correct for the stage of today? | Send advice CS-705. It never changes a setting. |
| **Setpoints** (`setpoints`) | One time each night, only with Auto setpoints on | Must the maintenance shots of tomorrow be smaller or bigger, or start later or sooner? | Move one setting by one step, inside a range around your value. |
| Balance (`balance`) | One time each grow-day, in the last 2 h before lights-off | Must the water of tomorrow move toward the water of the room? | Advice only. The Setpoints judge sees the answer. |
| **Targets** (`targets`) | One time each night, in the first 3 h after lights-off | Which field capacity, peak target, re-water point, rescue floor and dryback target does the zone need? | Write them, only with the `set_targets_from_achievable` power on (see [Powers](#powers)). Off: advice. |
| **Shot sizes** (`shotsize`) | One time each night, in the first 3 h after lights-off | Which ramp and maintenance shot sizes does the zone need? | Write them, only with the `tune_shot_sizes` power on. Off: advice. |

| Task | When the controller asks | What the controller does with the answer |
| --- | --- | --- |
| Feed (`feed`) | One time each grow-day, 1 h after lights-on, in a room with a feed EC sensor | Sends proposal CS-711 when the two questions agree firmly. It never writes a feed, a dose or a setting. |
| Report (`report`) | One time each grow-day, 3 h after lights-off | Publishes the daily report on `sensor.crop_steering_<prefix>brain_report`. |
| Why (`why`) | When an administrator (or an automation) asks with the `crop_steering.brain_ask` action, a maximum of 20 questions for each room each day | Publishes the answer on `sensor.crop_steering_<prefix>brain_answers`. It never changes a setting. |
| Plan (`plan`) | When the room differs from its grow plan, a maximum of 4 times each photoperiod | Selects the suggestion that the plan line shows. When a stale probe holds the plan day, it can apply the targets of the plan day. |

Eight judges can act: `dawn`, `ramp`, `salt`, `dusk`, `probe`, `setpoints`, `targets` and `shotsize`, each only with its power on. The other judges and the tasks give alerts or advice. The plan task can only apply the targets that the grow plan already has for today.

### Make sure that all the judges run

With `ai_judges` set to `all` (the default) or empty, all the judges and all the tasks run. The start line of the log lists them: find `judges` in it. With a list, only the names in the list run, and also `targets` and `shotsize`, whose powers decide whether they act. The controller ignores a name that it does not know.

An old options file can have a `jev_judges` list without the judges that came later, for example `ramp` left out. The controller reads such a list as `all` (see [Old option names](#old-option-names)), so every judge runs after the update.

To stop one action of the AI assistant, turn off its power (see [Powers](#powers)). To stop a judge that has no power, put a list of all the other names in `ai_judges`. The Setpoints judge also needs the **Auto setpoints** switch of the room on.

## When the controller uses its rules

The AI assistant is optional at each level. In each of these conditions, the decision of a judge is the decision of the rules, without change.

| Condition | Effect | How you know |
| --- | --- | --- |
| `brain_provider` is `rules`, or `auto` on an install that never used the first AI route | No AI assistant. | The panel and the log show `Rules.` |
| The options name the first AI route, and `anthropic_api_key` is empty | No AI assistant. | `Rules: no Anthropic key.` and CS-712. |
| `claude_haiku` with no key | No AI assistant. | `Rules: no Anthropic key.` |
| `anthropic_base_url` is not an `http` or `https` address | No AI assistant. | The panel tells you to correct the address or make it blank. |
| `anthropic_model` has no price in this release | No AI assistant. | The panel names the models that you can use. |
| 32-bit ARM (armv7), with no router | No AI assistant, because the device cannot load the Anthropic library. | The panel says that rules are running. |
| A call fails or times out | The controller tries again while the failure can pass, inside 60 s. Then it continues without that answer. | The panel shows the last error. |
| A question waited more than 5 min behind failed calls | The controller does not ask it, because its evidence is old. | — |
| The API refuses the key or the model | No more questions until the controller restarts. | CS-709. |
| The API refuses three requests in sequence | No more questions for 1 h. | CS-709. |
| The AI budget is spent | No more questions until the next lights-on. | CS-708. |
| The calls reach `ai_daily_calls` | No more questions until midnight. | CS-706 first warns you. |
| An answer is not valid, or is unsure after its second looks | No action from that answer. | The live log shows the answer and "no action". |
| A probe of a zone that is on is stale or missing | The controller asks nothing for that room until the probes report. | — |
| A judge is not in `ai_judges` | That judge never runs. | The start line of the log lists the judges. |

While the AI assistant cannot act, the Auto setpoints learner of the controller writes all the setpoints of the zone. The Setpoints judge gets its two settings back only at a lights-on at which the AI assistant can act. Thus a short pause does not change the writer of a setting during a grow-day.

## The safety limits

The code of the controller admits or refuses each answer. The AI assistant cannot change these limits.

- **Hardware:** the sequence of the valves, the main line and the pump, the readbacks, the latches and all the interlocks.
- **Water limits:** the daily minimum, the daily cap, the drown ceiling, the max EC flushes, the rescue shot and the watchdog. The AI assistant can start a phase earlier. It cannot stop one of these limits.
- **Arithmetic:** the shot size, the duration, the litres, the rates, the peaks and the clock.
- **Direction:** an answer can only move a zone forward through its day (P0 → P1 → P2 → P3), and only earlier than the rules. The rules still do all their own phase changes.
- **Morning start:** only after half the dryback target or a quarter of the maximum wait. Never while the probe has not moved for 30 min.
- **Ramp hand-over:** only after the minimum ramp shots, and only with VWC within 3 points of the peak target (or of field capacity, when it is lower). Further under it, only while the ramp stalls: the last ramp shot did not raise the moisture by the rise P1 needs, and the code does not doubt the probe. The rules end a stalled ramp one shot later anyway, so the judge can only make it one shot sooner.
- **Day end:** only in the last 3 h before lights-off, only for a zone with generative steering, and only with VWC at least 3 points above the rescue floor.
- **Probes:** the code sets a probe aside only after two answers in sequence that agree, and evidence from the code. The evidence is two shots with no increase while another zone increased, or a flat reading while water goes in.
- **Setpoints:** see the next section.

## Powers

The owner ticks what the AI assistant may do in each room: one switch per power,
`switch.crop_steering_<prefix>ai_power_<key>`, shown as a checklist on the dashboard's AI assistant page. With a power
off, its judge still asks and its answer is advice in the decision log; the envelope refuses to act on it. A missing
switch (an integration from before the powers) reads as its default, so a room updated in place does what it did.

| Power | Default | What it lets the AI assistant do |
|---|---|---|
| `advance_phase` | on | start the morning ramp or the night dryback early (dawn, dusk) |
| `ramp_control` | on | end the morning ramp (ramp) |
| `set_probe_aside` | on | set a probe aside (probe) |
| `ec_mode` | on | choose the EC steer's mode (salt) |
| `nudge_setpoints` | on | one notch on the maintenance shot size or re-water point (setpoints, its band and notch budget unchanged) |
| `plan_catch_up` | on | apply today's plan day while a stale probe holds it (plan) |
| `set_targets_from_achievable` | off | set a zone's field capacity, peak target, re-water point, rescue floor and dryback target itself (targets) |
| `tune_shot_sizes` | off | set a zone's ramp and maintenance shot sizes itself (shotsize) |

The last two are the owner's full authority. Once a night, in the first 3 h after lights-off (Claude route), the
targets and shot size judges are shown the zone's scorecard (each of the last 5 grow-days against the goal of each
phase, hit or missed and by how much), the AI assistant's own earlier changes with the result it expected and what
followed, and each setting's value and range; they answer with `set_values`: the values they want, each with its
reason, the expected result and a confidence. With the power on, code writes them as given, clamped only to each
setting's own range (a clamp is logged), the ladder from the top when the peak rises and from the bottom when it
falls, read back, and named in the room's setpoint change log with the reason and the expected result. No other
limit of code's applies: the doctrine's goal and rules for the owner's powers (POW-01 to POW-10) are in the cached
system prompt, and the AI assistant is trusted to follow them. While `set_targets_from_achievable` is on and the brain
can act, the Auto setpoints learner and the follower of the highest readings leave the ladder alone. Dry run still
only reports. The watering safety (daily cap, kill switch, valve read-back, feed gate, max-run latch) is unchanged.

The cached system prompt also carries "How this controller works" (`controller_brief.md` in the brain package),
generated from the code by `python -m <brain package>.controller_brief --write`: the phase machine, shot sizing, the gates in order, every setting, what
each AI-writable setting moves downstream, the powers and every error code. A test fails when the code has a phase,
setting, power or error code the brief lacks, or when the brief is not a fresh render.

## Who writes which setpoint

With the **Auto setpoints** switch of a room on and no armed grow plan, each setpoint of a zone has one automatic writer. With the switch off, or with an armed grow plan, neither writer changes a setpoint.

| Setpoint of the zone | Writer | How |
| --- | --- | --- |
| P2 shot size, re-water point | The Setpoints judge | One step of 0.5 each night, inside a range around your value. |
| Peak target, field capacity | The Auto setpoints learner of the controller | The peak target follows the highest VWC of the grow-day before. Field capacity follows the highest VWC of this grow-day or the grow-day before. Each moves 1 point or less each grow-day. |
| Rescue floor | You | The controller never changes it. |

The limits of the Setpoints judge:

- The shot size stays within 1 point of your value, and never goes below 3%.
- The re-water point stays between 2 points below and 1 point above your value. It also stays at least 4 points above the rescue floor and at least 2 points below the peak target and field capacity.
- A setting moves one step (0.5) or less in any 24 h, and two steps (1.0) or less in any 7 days.
- After a move that the code refused, or a move that did not work, no setting moves for 36 h.
- A rescue shot within 30 h after a move puts the old value back. The zone then pauses for 48 h, and the controller raises CS-404.
- When you change a value by hand, your value wins. The range then moves to your new value.

When the Setpoints judge does not run, the learner also writes the re-water point. When field capacity moves by 1 point or more, the re-water point moves by the same number of points. The learner keeps the re-water point at least 3 points above the rescue floor.

Each zone has `sensor.crop_steering_<prefix>zone_N_auto_setpoints`. Its `managed` attribute lists these setpoints, and `managed_by` names the writer of each one.

## The AI assistant and your setpoints

- **Auto setpoints is off until you set it to on.** Use **Turn auto on…** in **Irrigation › Current day**. There is one switch for each room.
- **One time each night**, in the first three hours after lights-off, the Setpoints judge selects one answer. The answers are smaller shots, bigger shots, a later re-water, a sooner re-water, or no change.
- **One small step**: the P2 shot size changes by 0.5%, or the re-water point changes by 0.5 points. A zone gets a maximum of one change each night.
- **The change ends**: at the next lights-on, each change returns to your value. The exception is when the judge moves it again. **Keep** stops the return. **Undo** puts your value back now.

## Stop or limit the AI assistant

| To do this | Do this |
| --- | --- |
| Stop setpoint changes | Use **Turn auto off…** in **Irrigation › Current day**. The values stay until you change them. |
| Change a value that the AI assistant controls | Type your value in **Irrigation › Current day**. It becomes the new centre of the range. |
| Stop one action | Turn off its switch in the AI powers list of the room. To stop a judge that has no power, list the other judges in the app option `ai_judges`. |
| Pause the AI assistant in one room | Set **Pause AI Changes** to 1 h, until lights-on, or 24 h. The rules continue. |
| Stop the AI assistant | Set `brain_provider` to `rules`, then restart the app. |
| Limit the cost | Set `anthropic_daily_budget_usd`. |
| Test it without changes | Set `brain_dry_run` to on. |

## Alerts

| Code | Name |
| --- | --- |
| CS-701 | No water at the zone |
| CS-702 | Unusual water for each plant |
| CS-703 | Overnight probe fault suspected |
| CS-704 | Probe set aside by AI |
| CS-705 | Zone outside stage arc |
| CS-706 | AI call budget almost used |
| CS-707 | Stricter gate for a judge |
| CS-708 | AI budget used |
| CS-709 | AI assistant not available |
| CS-710 | Possible water bypass |
| CS-711 | AI feed change proposal |
| CS-712 | First AI route removed |

The code raises CS-713 (room differs from grow plan) with each brain, also with rules. [ERROR_CODES.md](ERROR_CODES.md) tells what each code means and what to do.

## What the dashboard and Home Assistant show

The dashboard shows the decisions of the AI assistant in each zone’s **Why / next action** panel, on **Irrigation › Current day**, in **History › Explorer**, and on **Equipment › Probes & offsets**. Room-level automation permissions live in **Settings › AI assistant**. A room without the AI assistant shows none of it. The [user guide](USER_GUIDE.md) shows each page.

- `sensor.crop_steering_<prefix>jev`: the AI assistant panel of the room. It shows the brain, the model, the mode (acting or dry run), the calls, the cost and the budget of today, the last error and the judges. It also shows the stage of today.
- `sensor.crop_steering_<prefix>zone_N_jev`: the judges that act on the zone, the setpoint range, and the last answers of each judge with what the code did.
- `sensor.crop_steering_<prefix>jev_log`: the live log. Its `entries` attribute has the last 30 decisions of the room, newest first, with each result.
- `sensor.crop_steering_<prefix>brain_report`: the daily report. Its state is the headline.
- `sensor.crop_steering_<prefix>brain_answers`: the answers to the last questions that a person asked.

The controller keeps these files in its data folder. Their names come from earlier releases, so an old install keeps its record:

- `jev_usage.json`: the calls, the tokens, the cost and the budget window of today. It also names the brain that wrote it.
- `jev_ledger.jsonl`: each answer that acted, what the AI assistant saw, and the result.
- `jev_journal.jsonl`: the last 400 decisions behind the live log.
- `jev_setpoints.json`: the setpoint memory of the Setpoints judge.
- `brain_report.json`: the last daily report of each room.

## The first AI route (removed)

Before 3.12.0, the AI assistant used another model, reached through Cloudflare or TypeSafe. 3.12.0 added Claude, and a later release removed the first route. Claude now asks every judge and task the first route asked, and more.

An install that used the first route loads with no change to its options:

- `brain_provider: jev_legacy`, or `auto` on an install that ran the first route (a `jev_*` file in the data folder, or a TypeSafe key) with its settings still saved, moves to Claude when `anthropic_api_key` has a key, with every judge. Without a key, it uses the rules.
- The controller writes one line in the log at each start and raises CS-712 one time for each release. The old options `cf_account_id`, `cf_api_token`, `cf_gateway_id` and `typesafe_api_key` are not used. You can remove them.
- `jev_enabled` set to off keeps such an install on the rules. `jev_retries` is still the number of tries for each call.
- The ledger, the journal, the setpoint memory and the call count of the day carry on.

To move:

1. Set `brain_provider` to `claude_haiku`.
2. Put your key in `anthropic_api_key`.
3. Remove the old Cloudflare and TypeSafe options.
4. Restart the controller.

[MOVING_FROM_JEV.md](MOVING_FROM_JEV.md) tells how to move a room from the old app of the first AI route to this repository's app.
