# System overview

The integration owns rooms, zone metadata, mappings, number/select entities, the native sidebar and persistent grow plans. The controller app owns the decision loop and actuator calls. The pure crop-steering-engine package provides testable phase decisions.

The frontend reads HA state and Recorder history. Its setup and strategy actions use response-bearing services with explicit room IDs and revision checks. A saved draft does not change active irrigation. At a local lights-on boundary, an armed plan supplies one versioned, expiring snapshot of effective per-zone parameters. The controller validates that snapshot and retains a durable required-plan latch once a plan takes control.

P0 waits for morning dryback, P1 ramps toward the moisture target, P2 maintains moisture with EC-sensitive thresholds, and P3 ends scheduled irrigation with emergency-floor rescue behavior. Controller dryback is a relative percentage of the detected peak; VWC itself is an absolute percentage and measured drying rate is percentage points/hour.

P1 ends in one of three ways. At the target it gives one more shot, and ends once a shot no longer raises the settled reading by the rise P1 needs. Under the target it ends as stalled after two ramp shots in a row (`p1_stall_shots`) that each raise the settled reading by less than that rise: the slab takes no more today. The zone then re-waters for the rest of that grow-day its usual P2 drop under what it reached, never over its set re-water point, and that ends at the next lights-on. A stall is never read while the probe is in doubt (a table not draining, CS-310; water bypassing the probe, CS-710; a reading that does not move): the ramp then runs on. Otherwise P1 ends at its maximum shots. There is no time-based exit. With the Claude Haiku brain and the `ramp` judge on, the judge is asked at the first ramp shot that does not rise, and can hand over one shot sooner than the rules.

The live loop applies source-water, sensor, enable/interlock, volume and duration gates before hardware sequencing. Readback failures latch shared equipment out. Local tests exercise these branches with fake HA; production hardware behavior still requires site verification.

From 3.18 the integration also keeps one event journal for the site (`<config>/crop_steering/journal.db`): shots, holds, phase changes, alerts, doses, AI actions and setting changes from both the integration and the controller. The Timeline, Explorer, Changes and the alerts inbox read it. Watering never depends on it: if it fails, the controller keeps watering ([history and changes](features/history-and-changes.md)). The site-wide stores (supply, alert rules, presets) and the per-room stores (timer programs, display, calibration) are each saved against a revision, so a save that crossed another one is refused rather than lost.

## How a decision is made

1. Each minute, the controller reads the probes of each zone.
2. It compares the readings with your targets. It finds the phase of each zone and decides if a shot is necessary. These are the rules of the controller.
3. When a decision needs judgement, the controller can ask the AI assistant a question in the background. Examples: "Is the substrate full?" and "Is this probe stuck?".
4. The controller sends the facts with the question, for example "VWC increased 3.1 points after the 10:40 shot". It does not wait for the answer.
5. Code compares each answer with hard limits. These limits are the **envelope**. When the envelope accepts the answer, the controller does the action. When the envelope refuses it, nothing changes, and the log records the reason.
6. Later, code measures the result of the action. The dashboard shows a tick or a cross. The AI assistant sees its own record the next time.

See [repository map](REPOSITORY_MAP.md), [installation](INSTALL.md), [grow plans](GROW_PLANS.md) and [validated feature matrix](FEATURE_MATRIX.md).
