# Crop Steering, Jev edition

This fork of [HA-Irrigation-Strategy](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy) puts
**TypeSafe Jev**, a typed-decision model served through Cloudflare, in charge of every judgement the
crop-steering engine makes, while code keeps charge of everything physical.

The base engine is rules: fixed thresholds that are right most of the time and wrong in the cases
nobody wrote down (a probe channeling, a salt front still passing, a ramp that is done but not by the
numbers). Each fix added another "if". This edition replaces the "ifs" with a judge.

## What "truly insane and amazing" means here

Eight properties. Each one is concrete and checked by a test or a published number.

| # | Property | What it means | How it is checked |
|---|---|---|---|
| 1 | **Jev everywhere a judgement lives** | Every decision the engine makes on ambiguous evidence is asked of Jev: when the morning ramp starts, when it is done, whether a probe is telling the truth, whether a shot landed, why pore EC moved, when the day's watering stops, why one zone drinks differently, which alert is worth waking someone for. Ten judges cover P0, P1, P2 and P3 for every zone. | The coverage map below; one test per judge. |
| 2 | **Code owns physics and safety** | Jev never opens a valve, never sizes a shot, never crosses the daily floor or cap, the drown ceiling or max EC, never stops a rescue shot and never removes the last probe. Every Jev decision is a *directive* that the **envelope** admits or refuses on arithmetic Jev can't do. | Envelope tests for every directive type. |
| 3 | **Never waits** | Jev is asked in the background; the 60-second loop reads the last answer and carries on. A slow, failing or absent Jev leaves the engine exactly as the base engine behaves. | A golden test: with Jev off or erroring, every decision and every switch call equals the base engine's. |
| 4 | **A council, not a coin toss** | Jev's confidence moves with how a question is worded. So every judge asks each question in two independent phrasings in the same call and acts only when both land on answers that lead to the same action, and the calibrated probabilities of those answers add up ("the slab is full" and "the EC left is the feed passing" both mean hand the ramp over). | Council tests: disagreement means no action. |
| 5 | **It remembers and checks itself** | Every verdict and what code did with it goes into a ledger. When the outcome can be measured (EC after a flush call, the ramp after a hand-over, water after a probe was set aside), code measures it and shows Jev its own track record next time. A move that did not work is not repeated blindly. | Ledger tests; the track record in the evidence. |
| 6 | **Code does the maths, Jev does the judging** | Jev cannot do arithmetic and knows no crop-steering doctrine. Code turns the raw series into plain facts ("rose 3.1 points after the 10:40 shot and held", "EC rising 0.4 an hour since the last flush"), and every question carries the owner's own doctrine from his GrowLabs wiki (below). What is certain goes in code; what is judgement goes to Jev. | Evidence tests: no raw series ever reaches Jev; every question carries its doctrine. |
| 7 | **Explains everything** | Every verdict is published in Home Assistant with its answer, its confidence, whether the council agreed, what code did and why. `sensor.crop_steering_<prefix>zone_N_jev` per zone, `sensor.crop_steering_<prefix>jev` per room, and every decision in the dashboard's live log (`sensor.crop_steering_<prefix>jev_log`). | Publish and journal tests. |
| 8 | **Cheap and bounded** | Each judge has a cadence and a trigger, so Jev is asked when there is something to decide. A room of three zones costs cents a day (input $0.042 per million tokens, output free). A daily call budget caps it. | The room sensor shows calls and tokens today. |

## The judges (coverage map)

| Judge | Phase | Asked | Jev decides | Code does with it | Envelope |
|---|---|---|---|---|---|
| **Dawn** | P0 | every 10 min in P0 | start the ramp now / keep drying / the probe isn't moving | brings P1 forward | only after half the dryback target or a quarter of the max wait; never later than the base engine |
| **Ramp** | P1 | every 15 min once a ramp shot is 10 min old | keep ramping / slab is full / the EC left is the feed passing / real salt (all three: hand over; the ramp only refills, salt leaves in maintenance runoff) / the probe is lagging, wait | brings P2 forward | minimum ramp shots in; VWC within 3 points of the ceiling; never past `p1_maximum_shots` (the base engine still ends it there) |
| **Salt** | P2 | every 30 min when EC is settled, only while the room's EC stacking is on (its only action is the EC steer's mode) | salts accumulating / salt front still passing / the feed changed / the probe is suspect / the target can't be reached / in band | chooses the EC steer: steer, hold, or decay the offset | only changes the P2 offset the base engine already steers, inside its clamp |
| **Dusk** | P2 | every 15 min in the last 3 h before lights-off, never for a zone steered vegetative | go to P3 now / one more top-up then P3 / carry on | brings P3 forward | only in the last 3 hours; never for a vegetative zone (the owner's doctrine: it stops late); VWC at least 3 points above the P3 emergency floor; the P3 rescue still fires |
| **Probe** | all | every 30 min once the zone has had two shots | is this probe tracking the substrate; if not, how (stuck, channeling, out of the block, wrong zone, drifting) | sets the zone's probe aside: the zone runs on the existing dead-probe path (copies a healthy sibling, or its timer) | two agreeing verdicts in a row, **and** code-confirmed evidence (two shots with no rise while a sibling rose, or a flat line for an hour with water going in); lasts only while Jev's latest answer (90 min) still says so |
| **Shot** | all | once per shot, 20 min after it ends | landed / landed slowly / reached the probe but moisture didn't rise / didn't reach the zone | tags the shot, feeds the probe judge, raises CS-701 on two misses in a row | never adds water |
| **Night** | P3 | every 20 min within 3 points of the emergency floor | real drying / a probe fault | raises CS-703 | never stops a rescue |
| **Zones** | P1, P2 | hourly with lights on, when a zone's water per plant is under 70 % or over 140 % of the room's median zone (itself included; the other zone in a room of two) | why one zone differs (recipe, plants drinking less, wet spot, delivery fault, water not landing) | raises CS-702 with the likely cause | alert only |
| **Balance** | P2 | once a grow-day, in the last 2 h before lights-off, when a zone's water per plant is outside 85-115 % of the room's median zone and the zones judge has named no hardware cause today; Claude route only | move toward the room with less water / with more water / the difference is intended / it is hardware / keep as is | nothing itself: its answer is shown to tonight's Setpoints judge for the same zone as `room_balance` | advice only: the Setpoints judge stays the one writer of the zone's shot size and re-water threshold |
| **Stage** | P2 | once a grow-day, with lights on, when the flower day is known | is last night's dryback, the settled pore EC, and the stage's move-on signs where the owner's stage arc wants them for today | CS-705 advice; code itself states a steering mode that is not the stage's | advice only: never changes a setting |
| **Alerts** | all | once per alert, again after 6 h | escalate / remind / quiet | whether its repeats push to a phone (every alert is always a card; its first raise always pushes) | pump and valve faults (CS-3xx), lost probes (CS-101 to 103), CS-207, CS-701, CS-703, CS-704, and dosing's CS-801, CS-803 and CS-806 always push |
| **Setpoints** | P3 | once a grow-day, in the first 3 h after lights-off, while the room's **Auto setpoints** switch is on | tomorrow's maintenance watering: smaller shots / bigger shots / re-water later / re-water sooner / keep, from the day's water per plant against the room, the shots and how they held, pore EC against the stage's range (code states which way the EC and the room call for) | one notch on the zone's OWN number: P2 shot size ±0.5 % or P2 re-water threshold ±0.5 points | one notch a grow-day; inside a range around the operator's own value (shot ±1 %, never under 3 %; threshold 2 under to 1 over, 4 above the rescue floor, 2 under the ramp ceiling); an edit by hand always wins and re-centres the range; a P3 rescue shot within 30 h puts the old value back, pauses the zone 48 h and raises CS-404; the base engine's own Auto Setpoints learner never writes these two, and keeps the P1 target and field capacity ([who writes which setpoint](#who-writes-which-setpoint)) |

## The owner's doctrine

Jev knows no crop steering, so every question carries its rules. They are the owner's own GrowLabs wiki pages (root-zone TEROS-12, closed loop, flowering stages, rockwool crop steering, one steering law, slab irrigation strategy, ripening and harvest timing), then Athena's Grow Guide Handbook (metric, Precision Irrigation Strategy, pp. 33-41: first-shot timing, small P1 shots against channeling, the maintenance and EC levers, relative drybacks, the stage table and day climate, runoff targets, probe placement and the runoff check), restated as one-sentence rules with their source in `jev/doctrine.py`: 123 rules (99 from the owner's pages, 24 from Athena's, added 28 Sep 2026) across ramp, dryback, maintenance, EC, probe, stage, ripening, closed loop and slab. The owner's rules come first in every topic, and where the two differ (Athena states drybacks as a share of the peak, the owner's arc in points of true water content) the owner's arc leads. The stage arc is the slab guide the owner chose on 26 Sep 2026 (flower setting days 1-21 generative, bulk 22-42 vegetative, finish the last 14 days); set `jev_flower_start` and every judge sees today's stage and the operator's steering mode.

The live runs drew the line between doctrine for Jev and doctrine for code. Told in the question that a vegetative stage stops late, Jev still called an early stop for a well-watered zone near lights-off (both phrasings, p 0.7): so "a vegetative zone stops late" is an envelope rule. Whether the operator's steering mode matches the stage is arithmetic on the flower day: so the Stage judge's code states it, and Jev judges only what needs judgement.

## The envelope (what code never hands over)

- **Hardware:** valve, main line and pump sequencing, read-backs, fault latches and every interlock.
- **Water limits:** the daily minimum floor, the daily cap, the drown ceiling, max EC flushes, the P3
  emergency rescue, the watchdog. Jev can bring a phase forward; it can never stop one of these firing.
- **Arithmetic:** shot size, duration, litres, rates, peaks and the clock.
- **Direction:** phase directives only ever move a zone *forward* through its day (P0 → P1 → P2 → P3),
  and only earlier than the base engine would; the base engine's own transitions always still happen.
- **Doctrine that is certain:** a zone steered vegetative is never stopped early; pore EC under the stage's range
  calls for less runoff and over it for more (the Setpoints judge is told which way, and judges only whether and
  with which lever).
- **Setpoints:** only the zone's own P2 shot size and re-water threshold, one notch a night, inside a range around
  the operator's value that no string of notches can leave; never a room-level number, a daily limit, a floor or
  a ceiling. 26 Sep 2026 is why: the base engine's learner walked zone 1's shot from 3 % to 1 % (30-second shots
  every 96 seconds) and ratcheted zone 3's targets to 74.5 in four days.
- **Probes:** the last usable probe is never set aside by Jev alone: it takes the council, the code-confirmed
  evidence, and it expires.

## Who writes which setpoint

With a room's **Auto setpoints** switch on and no armed grow plan, each of a zone's own numbers has exactly one
automatic writer. With the switch off, or under a plan, neither writes anything.

| Zone number | Written by | How |
|---|---|---|
| P2 shot size, P2 re-water threshold | Jev's Setpoints judge | One notch a night, inside a range around the operator's value (the Setpoints row above). |
| P1 target, field capacity | The zone's own highest readings (the controller) | The P1 target is the highest reading of the grow-day before, kept at lights-on, with no limit on how far it moves. Field capacity is the higher of today's and the day before's highest readings. When field capacity moves by a point or more, the re-water threshold and the rescue floor move by the same points (the threshold's move re-centres the Setpoints judge's range). Also while the zone waters without its probe. |
| P3 rescue floor | The learner | Only to keep it 3 points under the judge's re-water threshold, when the ladder would otherwise invert. |

The old hourly P2 check is retired: nothing asks it, with or without the Setpoints judge. Each zone's
`sensor.crop_steering_<prefix>zone_N_auto_setpoints` lists these numbers in `managed` and names each one's writer
in `managed_by`.

Two runs of the learner shaped this. From 22 to 26 Sep 2026, writing every target alone, it took zone 3's P1
target from 40.9 to 74.5. From 26 Sep it wrote nothing at all while the judge ran, so nobody wrote the P1
target: after a sump flood on 29 Sep moved zone 2's probe up 15 to 20 points, its target sat at 29.5 under a
probe reading 42 to 44 % at lights-on and P1 never ramped (4 Oct). Since 6 Oct the learner writes neither the P1
target nor field capacity: they follow the zone's own highest readings, as the owner set out, and P1 ends by the
rise rule (core.decide): reach the target, give one more shot, and hand over only when a shot no longer raises
the zone's highest reading by 0.5 points (or at the maximum P1 shots). The ramp judge does not run on F2.

In a room without the judge, the learner also owns the re-water threshold.

## Failing safe

Jev is optional at every level: no TypeSafe key and no Cloudflare credentials, `jev_enabled` off, a judge left out of
`jev_judges`, the daily budget spent, every route down, or an answer that fails to parse: each means that judge's
decisions are the base engine's, unchanged. Jev is reached over every route it has, TypeSafe direct first and then
Cloudflare's `/ai/run`; each is tried up to `jev_retries` times inside 60 seconds while its failure may pass (a busy
or failing server, a timeout), and a refused key moves straight on. A question that waited more than five minutes
behind failing calls is dropped unasked, because its evidence is stale, and an answer is as old as its question.
When an answer that did not act is unsure (under `jev_unsure_below`, or two phrasings that disagree), Jev is asked
again with more evidence, up to `jev_reask_max` times, before the engine decides; the second look is dropped once
the zone leaves the judge's phase or the answer is older than the judge's window. After `jev_strict_after` of a judge's calls in a row did not work out for a zone,
that judge is on the stricter gate there: it acts only when both phrasings agree at `jev_strict_prob` or more and a
second look inside the judge's window gives the same call, until two calls in a row work. Jev keeps judging throughout.

## Configuration

Add-on options (the controller app):

| Option | Default | What it does |
|---|---|---|
| `typesafe_api_key` | empty | A TypeSafe API key (`apikey_...`): Jev straight from TypeSafe (`api.typesafe.ai/v1/systemone`, model `jev-latest`). Tried first when set; Cloudflare, when set too, is the second route. |
| `cf_account_id`, `cf_api_token`, `cf_gateway_id` | empty | Or Jev through Cloudflare Workers AI: the account, a token with Workers AI access, and the AI Gateway (optional). With neither a TypeSafe key nor these, Jev is off. These alone start Jev only on an install that has run it before (one of the `/data/jev_*` files below is there), because an install updated from a line without Jev may have set them just for the Auto Setpoints check. |
| `jev_enabled` | on | Off runs the plain engine even with Cloudflare set. |
| `jev_judges` | all | The judges that may act, e.g. `dawn,ramp,salt,dusk,probe,shot,night,zones,stage,setpoints,balance,alerts` (balance runs on the Claude route only). Setpoints also needs the room's **Auto setpoints** switch on; while it runs, it owns the P2 shot size and re-water threshold, and the base engine's own Auto Setpoints learner the P1 target and field capacity. |
| `jev_daily_calls` | 5000 | The day's call budget across rooms. |
| `jev_budget_warn_pct` | 80 | CS-706 once a day when the calls reach this share of the budget. |
| `jev_retries` | 3 | Tries per route, inside 60 seconds, while a failure may pass. |
| `jev_reask_max` | 2 | Second looks, with more evidence, when Jev is unsure. |
| `jev_unsure_below` | 0.7 | Under this probability, or with phrasings that disagree, an answer is unsure. |
| `jev_strict_after` | 3 | Bad calls in a row before a judge is on the stricter gate for a zone (CS-707). |
| `jev_strict_prob` | 0.8 | How sure an answer must be to act on the stricter gate. |
| `jev_flower_start` | empty | Each room's first day of 12/12: an input_datetime or a date, for every room or as `room=value` pairs, e.g. `default=input_datetime.f2_flip_date, f1=input_datetime.f1_flip_date`. |
| `jev_flower_days` | 56 | The cultivar's flowering length; the finish is its last 14 days. |

## What Jev can raise

Seven codes, in their own group of the error-code list (docs/ERROR_CODES.md): **CS-701** water isn't reaching a
zone, **CS-702** a zone's water per plant is out of line, **CS-703** an overnight low looks like a probe fault,
**CS-704** Jev set a zone's probe aside, **CS-705** a zone is off its stage's arc, **CS-706** Jev has used most of
today's calls, **CS-707** a judge is on the stricter gate for a zone. The controller raises them through one method with each code written
out, so a judge can never raise anything the list does not explain.

## What it shows

The dashboard reads these live. **Today** puts today's stage in the room's line and lists what Jev changed
today. Each zone's page marks every decision above its day chart (filled when code acted) and shows **Jev on
this zone**: the range Jev may use for the P2 shot size and re-water point, and its latest decisions with the
later check of how they worked. **Plan › Targets** puts Jev's range beside the values it manages, and **Plan ›
Schedule** opens with the stage arc. **History › Timeline** lists every decision (the actions by default, all of
them with **All Jev decisions**) with today's calls, tokens and cost, and **Equipment › Probes** says whether Jev
is on. A room without Jev shows none of it. The [README](../README.md#the-dashboard-page-by-page) walks through
each page with screenshots.

- `sensor.crop_steering_<prefix>zone_N_jev`: the judges acting on the zone (or `watching`); `setpoints` (the
  operator's values, Jev's range around them, the current values, the last move and any pause, and whether the
  room's Auto setpoints switch hands them to Jev); and per judge its
  latest verdicts (answer, probability, whether both phrasings agreed), the directive, and why code admitted or
  refused it.
- `sensor.crop_steering_<prefix>jev`: calls and input tokens today, errors and the last error, the judges on, and
  `stage`: today's row of the owner's stage arc as numbers (day of flower, stage, steering, pore EC range, dryback
  points, runoff %), which the dashboard draws on its day chart.
- `sensor.crop_steering_<prefix>jev_log`: the dashboard's live log. Its state is the newest decision in one line;
  `entries` holds the room's last 30, newest first: time, zone, judge, Jev's answer with its probability and
  whether both phrasings agreed, what it asked for, and what code did (`acted`, `refused` with why, `no action`,
  `waiting`), plus each outcome (`worked` or `did not work`, with `of` = the time of the decision it checks and
  the action in words) and each alert-triage call (push or card only).
- `/data/jev_ledger.jsonl`: every directive that acted, what Jev saw, and later how it turned out.
- `/data/jev_journal.jsonl`: every decision behind the live log (the last 400), kept across restarts.
- `/data/jev_usage.json`: today's calls, input tokens and errors, so the count survives a restart.

## Checked against the real Jev

`scripts/brain_live_smoke.py` builds realistic zone situations, runs each judge's own evidence and questions through
Cloudflare and compares the council's verdict (and what the envelope then admits) with what an experienced grower
would say. On 27 September 2026, with the doctrine in every question: 14 of 14, about 3,000 input tokens a
question (cents a day for a room), no errors. The same zone two hours before lights-off was stopped early in
flower setting and left watering in flower bulk; a zone left on generative steering in bulk was flagged.

On 28 September 2026 the Setpoints judge joined: 17 of 17 through TypeSafe. Zone 1's heavy day of 27 Sep (235 % of
the room's water, pore EC 3.05 under the bulk range) became smaller shots, 5 % to 4.5 % (p 0.94); a zone on course
kept its settings (p 0.92); a thirsty zone with EC over the range got bigger shots (p 0.95). Before code stated
which way the EC and the room called for, Jev split zone 1 between smaller (0.45) and bigger shots (0.35): the
direction is doctrine, the lever and the timing are judgement.
