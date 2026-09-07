# User-authored recipe library and duration compatibility

Integration 2.15.0 / controller 0.13.1, 8 September 2026.

## Changes

- The browser library starts empty and stores up to 20 user-authored recipes per room, separately for live and demo. Notes and optional source URLs are user-provided metadata, not publisher approval.
- Save, preview, import/export and confirmed removal operate locally. Loading keeps current zone IDs/start dates, validates the recipe against supported plan schema and current parameter limits, and requires acknowledgement before replacing an unsaved draft. Active/armed plans cannot accept a loaded draft.
- Storage errors, stale-tab writes and malformed data are visible. Corrupt contents are retained and can be downloaded for recovery. Library entries are not a shared HA database or backup.
- Cryptographic UUID creation works on HTTP LAN origins without `crypto.randomUUID`.
- The controller and water calculator accept the legacy same-room `maximum_shot_duration` entity when canonical `max_shot_duration` is absent. Canonical values take precedence. Invalid selected caps hold actuation. Both absent retains the controller's existing 900-second fallback, while the calculator explicitly lacks a configured cap. The existing HA reader cannot distinguish a missing response from every transport failure; this inherited limitation was not expanded into a new transport API.

## Verification

162 frontend unit tests, 222 integration/repository tests and 114 actual-controller tests pass; one existing optional integration test is skipped. The unchanged pure decision core retains its 54 passing tests. TypeScript, production packaging, Ruff, Black and YAML checks pass.

Browser suites cover the existing operator workflows and the new library lifecycle, HTTP-style crypto availability, current-date preservation, dirty-draft replacement, room isolation, confirmed removal, JSON import/export, corrupt-storage retention and mobile accessibility. Independent review found and corrected profile identifier/count mismatches with the backend; expanded import validation covers supported parameter keys, complete endpoints, ordering and step alignment.

The standalone demo and README use screenshots from isolated sample data. Publisher links and access limitations are documented in [Recipe library](../RECIPE_LIBRARY.md). No guide-derived numerical recipes were generated and no live plan was armed.

## Published and installed

Release commit `6129d7d5337329cdb7812437c5b927aac60ff74e` passed GitHub Validate, Installation Workflow, Release packaging and Pages deployment. The public demo returned HTTP200 and matched the packaged dashboard byte-for-byte after line-ending normalization.

The existing two-room, six-zone installation was updated in place through HACS and Supervisor. Integration 2.15.0 and controller 0.13.1 loaded successfully. Backups were taken before stopping the controller; all mapped pumps, mainlines and valves read OFF. Controller options and both integration entries' data/options were preserved. All 303 numeric settings and 397 captured controls matched after restoring the original engine states: F1 enabled, default/F2 disabled. Both heartbeat sensors reported healthy without hardware or strategy faults. Retained shot counters, volume, last-shot/reset records and controller state matched the stopped-state snapshot.

Installed controller Python, decision core and both dashboard copies matched published source. In the native HA sidebar, the previous unavailable duration now reads the existing 900-second cap and produces effective runtime water estimates. The Recipe library opens with its empty state and local save/import controls. The current saved grow plan remains at its original draft revision; the user's separate unsaved browser draft was exported and its tab retained. Run metadata remains empty for both rooms.

This was a software upgrade/readback test. No physical irrigation test, new recipe activation or source-guide preset installation was performed.
