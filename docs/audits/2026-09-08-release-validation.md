# Release validation — integration 2.13.0 / controller 0.12.0

## Local checks

On 8 September 2026 the complete integration/controller suite passed 268 tests, with one Windows symlink-capability skip. The pure decision core passed 54 tests. Ruff, Black and YAML validation passed. The tested engine and its vendored copy are identical.

The frontend passed 55 unit tests and a fresh production build. Nine current workspace browser groups passed, including responsive layout, accessibility, day/week planning, sensor mapping, API conflicts and live theme inheritance. The three compiled dashboard copies are identical. The complete browser suite also runs in release CI.

All 37 files moved in this cleanup match their original SHA-256. The unique branch trainer is preserved byte-for-byte with provenance. A local Git bundle preserves all pre-consolidation refs, and remote branch tips have verified public archive tags. Uncommitted rescue pages remain private and untouched.

## Open issue corrections

| Issue | Verified correction |
| --- | --- |
| #37 | Unknown EC remains unknown. Real snapshot-to-decision tests preserve the configured VWC shot, pause EC learning/offsets and expose degraded status. |
| #38 | Controller dryback uses relative peak percentage; predictive timing converts VWC-point rates explicitly. Constants no longer promise nonexistent synchronized aliases. |
| #39 | Sensor fusion rejects nonfinite readings and documents its arithmetic mean. No outlier rejection is claimed. |
| #40 | Timed holds expire, retrigger and restore across graceful restart/reload. Direct switches cancel old deadlines. A renamed entity cannot produce false service success. Independent tests reach the controller's actual override gate. |
| #41 | Seven grow-day delivery estimates survive old-state loading/restart, roll independently of phase resets, include partial aborts, and expose incomplete history. The rolling sensor uses TOTAL rather than TOTAL_INCREASING. |

Additional sensor tests reject NaN/Inf and missing, malformed, stale or excessively future-dated timestamps. A setup regression verifies that renaming a room or remapping it retains the current per-zone plant count, pot volume and dripper settings.

## Evidence limits

These checks use source, packaged browser artifacts and fake HA. Publication and the live upgrade are recorded separately after completion. Physical flow, irrigation outcome and crop response are not established by software checks. Weekly litres remain controller estimates, and ordinary HA RestoreEntity checkpoint behavior limits abrupt-crash recovery.

The state-class correction follows the [Home Assistant sensor contract](https://developers.home-assistant.io/docs/core/entity/sensor/). A rolling seven-day value may decrease as an old day leaves the window; it is not a lifetime water-meter counter.
