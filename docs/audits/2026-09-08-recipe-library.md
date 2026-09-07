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
