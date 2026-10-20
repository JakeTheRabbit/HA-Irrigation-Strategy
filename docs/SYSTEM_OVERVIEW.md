# System overview

The integration owns rooms, zone metadata, mappings, number/select entities, the native sidebar and persistent grow plans. The controller app owns the decision loop and actuator calls. The pure crop-steering-engine package provides testable phase decisions.

The frontend reads HA state and Recorder history. Its setup and strategy actions use response-bearing services with explicit room IDs and revision checks. A saved draft does not change active irrigation. At a local lights-on boundary, an armed plan supplies one versioned, expiring snapshot of effective per-zone parameters. The controller validates that snapshot and retains a durable required-plan latch once a plan takes control.

P0 waits for morning dryback, P1 ramps toward the moisture target, P2 maintains moisture with EC-sensitive thresholds, and P3 ends scheduled irrigation with emergency-floor rescue behavior. Controller dryback is a relative percentage of the detected peak; VWC itself is an absolute percentage and measured drying rate is percentage points/hour.

P1 ends in one of three ways. At the target it gives one more shot, and ends once a shot no longer raises the settled reading by the rise P1 needs. Under the target it ends as stalled after two ramp shots in a row (`p1_stall_shots`) that each raise the settled reading by less than that rise: the slab takes no more today. The zone then re-waters for the rest of that grow-day its usual P2 drop under what it reached, never over its set re-water point, and that ends at the next lights-on. A stall is never read while the probe is in doubt (a table not draining, CS-310; water bypassing the probe, CS-710; a reading that does not move): the ramp then runs on. Otherwise P1 ends at its maximum shots. There is no time-based exit. With the Claude Haiku brain and the `ramp` judge on, the judge is asked at the first ramp shot that does not rise, and can hand over one shot sooner than the rules.

The live loop applies source-water, sensor, enable/interlock, volume and duration gates before hardware sequencing. Readback failures latch shared equipment out. Local tests exercise these branches with fake HA; production hardware behavior still requires site verification.

See [repository map](REPOSITORY_MAP.md), [installation](INSTALL.md), [grow plans](GROW_PLANS.md) and [validated feature matrix](FEATURE_MATRIX.md).
