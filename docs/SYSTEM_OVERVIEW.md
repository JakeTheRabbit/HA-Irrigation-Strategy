# System overview

The integration owns rooms, zone metadata, mappings, number/select entities, the native sidebar and persistent grow plans. The controller app owns the decision loop and actuator calls. The pure crop-steering-engine package provides testable phase decisions.

The frontend reads HA state and Recorder history. Its setup and strategy actions use response-bearing services with explicit room IDs and revision checks. A saved draft does not change active irrigation. At a local lights-on boundary, an armed plan supplies one versioned, expiring snapshot of effective per-zone parameters. The controller validates that snapshot and retains a durable required-plan latch once a plan takes control.

P0 waits for morning dryback, P1 ramps toward the moisture target, P2 maintains moisture with EC-sensitive thresholds, and P3 ends scheduled irrigation with emergency-floor rescue behavior. Controller dryback is a relative percentage of the detected peak; VWC itself is an absolute percentage and measured drying rate is percentage points/hour.

The live loop applies source-water, sensor, enable/interlock, volume and duration gates before hardware sequencing. Readback failures latch shared equipment out. Local tests exercise these branches with fake HA; production hardware behavior still requires site verification.

See [repository map](REPOSITORY_MAP.md), [installation](INSTALL.md), [grow plans](GROW_PLANS.md) and [validated feature matrix](FEATURE_MATRIX.md). The archived overview contains historical facility-specific state and is not current runtime evidence.
