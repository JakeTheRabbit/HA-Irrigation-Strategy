# Crop Steering Remediation Task List (Phase 1-5)

This checklist tracks the production-hardening work performed for the AppDaemon + Home Assistant Crop Steering stack.

## ✅ Phase 1 — Stack & Dependency Audit

- [x] Verified AppDaemon `apps.yaml` handshake and added explicit optional config blocks (`hardware`, `sensors`, `timing`, `thresholds`).
- [x] Normalized legacy hardware key compatibility (`zone_switches` -> `zone_valves`).
- [x] Added robust zone valve key normalization for int/string key mismatches.
- [x] Audited integration event handshake (`crop_steering_*` events) and aligned runtime listeners.

## ✅ Phase 2 — Code Review & QA Hardening

- [x] Added startup safety sweep to force irrigation hardware OFF on restart.
- [x] Added serialized irrigation execution lock to prevent concurrent run collisions.
- [x] Added explicit preflight conflict checks before irrigation execution.
- [x] Added guaranteed best-effort shutdown in irrigation `finally` cleanup.
- [x] Added runtime watchdog for software/hardware desynchronization detection.
- [x] Added fail-safe emergency stop when all configured VWC sensors are offline while hardware is active.
- [x] Fixed `set_entity_value` usage bugs (`state=` misuse) in runtime sensor publishing paths.

## ✅ Phase 3 — Gap Analysis / Contract Clarity

- [x] Clarified architecture contract in docs: this repo currently uses custom integration service/event handshake as primary GUI/backend bridge.
- [x] Consolidated zone sensor matching logic into one helper for consistent VWC/EC zone selection.

## ✅ Phase 4 — Remediation Plan Outcomes

- [x] Safety-first watchdog and status telemetry implemented.
- [x] Config simplification and normalization completed in runtime loader.
- [x] Additional config sanitation added (non-string/empty sensor IDs filtered before use).

## ✅ Phase 5 — Execution

- [x] Refactored major risk areas in `master_crop_steering_app.py` for modular helpers and safety boundaries.
- [x] Added runtime status telemetry entity (`sensor.crop_steering_app_status`) for dashboard observability.
- [x] Added robust logging around safety events and watchdog actions.

## 🔍 Remaining (Live Environment Validation)

These require an actual Home Assistant + AppDaemon runtime and cannot be fully validated in this CI shell:

- [ ] Validate full irrigation cycle in live HA (P0/P1/P2/P3 transitions).
- [ ] Verify hardware sequencing against real valves/pump entities.
- [ ] Confirm dashboard visibility for status and safety sensors.
- [ ] Run a controlled sensor-outage simulation and verify emergency-stop behavior.

## Deployment Note

Use the generated pull requests from this branch to merge changes to GitHub, then deploy to your HA/AppDaemon instance and run the live checks above.
