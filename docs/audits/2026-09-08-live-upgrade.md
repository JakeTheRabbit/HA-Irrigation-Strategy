# Live upgrade verification — 8 September 2026

## Installation exercised

An existing Home Assistant OS installation with two Crop Steering rooms and six zones was upgraded in place. Home Assistant Core remained 2026.8.3; unrelated integrations and apps were not upgraded.

The upgrade used the existing HACS repository and Supervisor app identity. Private backups include the prior integration, exact controller image, persistent state and configuration. Engines were paused while software was replaced. A Supervisor app backup captured persistent state before the new controller's first start. Backup contents and credentials are not published.

The initial 2.13.0 integration upgrade exposed a concurrent sidebar-registration race: the default room loaded while the second room failed setup. A deterministic regression reproduced the error. Integration 2.13.1 serialized registration and passed independent review, 191 integration tests (one Windows capability skip) and live restart verification. Both room entries then loaded successfully.

A browser check also found both room choices displayed the generic sensor name. Integration 2.13.2 and controller 0.12.1 bundle the corrected room-name precedence. Stable room IDs, irrigation logic and state format are unchanged by that display correction.

## Preserved configuration and runtime

- All **302 existing numeric entities** retain exactly the same values. Two additional duration defaults are additive.
- All **147 other captured controls** retain their states after restoring the maintenance pause, including F1 enabled and the default/F2 engine disabled.
- Both configuration entries retain their data and options; equipment/probe mappings and live pot/plant/dripper values are unchanged.
- Controller options are identical to the pre-upgrade options.
- All six zones retain their shot counts, delivered-volume counters, last-shot and daily-reset timestamps, phase and EC learned-state values across the first controller start.
- The running controller, strategy runtime and decision-core sources match the published package after line-ending normalization.

Recorded history remains available in the combined VWC/EC view. The planner seeds six draft profiles from current parameters; all 18 values in each profile match its live catalog. Both endpoints start equal to preserve the existing setup. Review and differentiate endpoints before expecting the balance slider to change targets. No recipe was armed during commissioning.

## Live checks

Both room entries load. Both controller heartbeats are healthy, advertise strategy snapshot version 1 and acknowledge the current setup revision with no pending setup, strategy error or hardware fault. Mapped probes report numeric values. The native HA sidebar workspace displays recorded history, current targets, the combined planning curve and the day/week schedule.

F1's previously enabled state was restored after maintenance; the default/F2 engine remains off as before. Existing values were retained through the upgrade.

## Publication and branches

Both GitHub repositories have only `main`. The primary repository's 21 original local/remote refs were audited; the dedicated controller repository's historical feature branch was also reviewed. Public remote tips have archive tags; local-only/private history stays in private backups. The unique trainer is retained with provenance in the repository archive. All five reviewed open issues (#37–41) were resolved by the published release.

The README includes current overview, planning, setup and mobile screenshots. The [public demo](https://jaketherabbit.github.io/HA-Irrigation-Strategy/dashboard.html?demo=1) uses isolated sample data and was exercised in a browser.

## Limits

This verifies an upgrade of an existing installation. First installation on a blank HA system remains untested. Room creation/removal and mapping mutations have automated flow/API/browser coverage; live mappings were read and preserved. No physical equipment exercise, measured-flow calibration, manual setpoint change or new recipe activation was triggered. A complete lights-on recipe handoff and physical water delivery remain separate commissioning tasks. Weekly litres are controller estimates.

Automated release validation and installation workflows pass. Dependency review could not inspect a dependency graph because that GitHub API capability is unavailable for this repository; the optional job's green status does not establish a completed dependency security review.
