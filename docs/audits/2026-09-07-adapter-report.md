# Operator dashboard adapter implementation

Scope: offline frontend implementation in `frontend/src/lib/{model,client,demo,use-controller}.ts`, with focused model and lifecycle tests. No production HA access, deploy, hardware action, or credential use occurred.

## Implemented contract

- `useController(): Controller` uses a testable `ControllerStore`. All transport and entity-ID construction stay in the adapter.
- Rooms are discovered from real engine descriptors and validated prefixes/zone counts. Empty discovery stays empty. Named namespaces remain separate; explicit F1 legacy sensor aliases come from `www/f2-classic.html`. Existing unavailable primary telemetry remains unknown instead of quietly switching sources.
- Missing/blank/non-finite/unavailable measurements are `null`. Room aggregates require all zone values; they do not treat unavailable zones as zero. VWC target reflects P1 ramp target, P2 base threshold, or P3 emergency floor; P0 and unknown phases have no implied absolute VWC target. P2 runtime EC adjustments are not represented by the base threshold. Unknown steering mode/phase means no inferred EC target.
- Numeric editors include only current controller parameter families with finite HA-provided bounds and step. Room defaults and zone-specific settings are distinguished. Choices expose discovered room/zone steering modes and their actual options; recipe stages/services are excluded.
- Writes require a fresh full-state preflight, current room membership, readable existing entities, numerical bounds/steps or permitted select options, and fresh matching entity readback. Batches return applied and failed entries separately. Engine/zone configuration switches are allowed; mapped pumps/mainlines/valves are explicitly rejected. No manual-shot events or recipe services exist in this adapter.
- Live REST requests use a 12-second timeout and abort signal. Existing HA parent `callApi`/`callService` sessions are used only for the matching HA origin. Parent calls cannot be physically aborted, so timeout and generation checks discard late results. Explicit connection tokens are held only in tab `sessionStorage` and cleared on disconnect; no new localStorage credentials are written. Existing HA `hassTokens` can be read only for the current origin.
- Polling runs every 30 seconds. Changing room, connection, or disconnecting invalidates older responses and unfinished write batches. Refresh failure preserves the previous snapshot and marks the connection offline; it never becomes demo data.
- Actual HA history comes from `/api/history/period`. No live history points are fabricated; requests are limited to current-room entities. Recorder/auth failures are surfaced.
- Current controller activity feeds share an internal list across rooms. Named-room slug tags are filtered to the selected room; default-room messages exclude known named-room tags. The controller emits only HH:mm, so that time is preserved without inventing a date. These messages describe scheduling/controller activity, not independently confirmed physical watering.
- Hardware fault latch telemetry produces a critical recovery notice. Missing sensor/control data remains explicitly unavailable.
- Demo activates only via `?demo` or `*.github.io`; it has two rooms, three zones each, phase settings, both steering modes, local events/history, and in-memory writes. Demo never instantiates live transport.

## Verification

The first test run failed because adapter modules had not yet been implemented, establishing the initial red test state. Final checks:

```text
npm test -- --run src/lib/model.test.ts src/lib/use-controller.test.ts
2 test files passed, 18 tests passed
npx tsc --noEmit
passed
```

Coverage includes room isolation and legacy aliases, unknown values, phase thresholds, unsupported settings, select option bounds, direct hardware rejection, numeric bounds/step, failed readback, activity room filtering, fault notice, stale response after disconnect/reconnect/room change, retained data after refresh error, demo write/history network isolation, cross-room history rejection, and request timeout.

Limitations: browser-based HA session inheritance and real HA API/Recorder behaviour have not been tested against a live installation. Configuration readback verifies HA entity state, not physical hardware effects. Dashboard browser verification and final packaging belong to the parent task.

## Independent review fixes

Both important findings were reproduced with failing regressions before correction.

- **Room identity:** the empty-prefix room previously shared ID `f2` with a valid named `f2_` room. Every room now uses canonical `room:<prefix>` identity (`room:` for empty prefix; `room:f2_` and `room:default_` for named examples). Colons cannot occur in valid prefixes, so these identities cannot collide. Room selectors, writes, history and persisted URL selections use canonical identities. Explicit legacy URL aliases resolve named prefixes first: `?room=f1` selects `f1_`; `?room=f2` selects the empty-prefix room only if no actual `f2_` room exists. A canonical default link always remains `?room=room%3A`. An explicitly requested missing room never falls back to another room; it displays an unavailable selection and a useful error until the target appears or the operator chooses an available room. Only absence of the room query permits initial first-room selection.
- **Reading freshness:** VWC and EC use `last_updated` with the controller's 20-minute default maximum age. A finite positive `max_sensor_age_s` exposed by the heartbeat overrides the descriptor value, which overrides the default. Missing/invalid update timestamps fail closed; timestamps more than 60 seconds in the future also fail closed, allowing modest clock skew. Stale readings become null and produce a notice explaining the affected reading and age limit; room aggregates also become unavailable. `last_changed` is not used as proof of freshness. Static setpoints, modes, and switches are not aged out. Raw sensor entities remain available for diagnostics; history retains actual recorded historical readings.

Final review verification after formatting:

```text
npm test -- --run src/lib/model.test.ts src/lib/use-controller.test.ts src/lib/review-regressions.test.ts
3 test files passed, 25 tests passed
npx tsc --noEmit
passed
```

New regression coverage includes default/named-F2/named-default identity, canonical and legacy URL routing, missing requested rooms, actual selected-room write/readback and history routing, old and fresh readings, unknown/invalid/future timestamps, custom freshness limits, aggregate unavailability, and old static values retaining their values.
