# Native Crop Steering workspace

User-authorized continuation of the September 7 refactor, including all advanced screens. Implementation is local; no live hardware, HA config, deployment or publication is authorized by this request.

## Accepted architecture

- Follow the active Home Assistant theme through its CSS variables; native dark/light fallbacks for standalone use. A user override remains available.
- Replace every legacy advanced landing screen with a route in one responsive React workspace. Canonical artifact `dashboard.html`; old filenames remain small compatibility redirects. Full legacy implementations move to an indexed archive.
- Main workflows: Overview, Zones, Live settings, Grow plan, Insights, Activity, Sensors, Setup, Settings and Help. No unvalidated yield/potency estimates or unsupported manual-shot buttons.
- Dual-axis recorded VWC/EC charts, independent traces and clear units. Missing recordings remain gaps.
- Continuous 0..100 steering interpolates explicit grower-defined endpoint profiles. Pot size and drippers determine hydraulic delivery calculations, not agronomic target selection.
- Durable versioned per-room grow plans with per-zone start dates and day ranges; week editing maps to day ranges. Draft/save/review/arm with activation at local lights-on boundary and atomic strategy snapshots consumed by the controller. Existing legacy entity IDs and mode controls remain compatible.
- Safe room/zone lifecycle through validated HA response services: stable identifiers, archive/restore, mapping validation, revision checks and physical-OFF prerequisites. Discoverable capabilities prevent false success on old integrations.
- Simplify fresh installation with supported HACS/add-on links, manual UI setup as the default, automatic dashboard registration where supported, and a readiness checklist with searchable sensor mapping.
- Verified feature matrix and installation/upgrade guides replace competing instructions. Archives retain provenance and are not shipped as the live UI.

## Workstreams

1. Theme and combined charts (dashboard_ui): HA theme bridge, responsive appearance, dual axes, checks.
2. Strategy backend (controller_adapter): durable plans, canonical parameter profiles, preview, scheduling, coherent controller overrides, compatibility and isolation tests.
3. Setup backend (independent_review): room/zone lifecycle, mapping validation, native flow improvement, panel registration, revision and OFF guards, compatibility tests.
4. Integrated workspace (primary): response-service client and isolated demo, Grow plan and Setup pages, advanced navigation consolidation, parameter explanations, archive and packaging, documentation and complete browser verification.

## Review and verification ledger

- All workstreams must finish focused tests before independent cross-review. Parent runs integrated frontend/Python checks and mock HA browser workflows.
- No removal of stable HA identifiers or persisted counters. Archive is reversible and uses checked workspace paths.
- Explicitly distinguish source/offline tests, manual/real HA checks not run, and unsupported legacy features in the feature matrix.

## Completed validation

All four workstreams are implemented and independently reviewed. Final local results:225 Python tests,55 frontend unit tests and36 browser workflow groups pass. TypeScript/build, Ruff/Black/YAML, packaging parity and archive/app-discovery checks pass. See docs/audits/2026-09-08-validation.md and docs/FEATURE_MATRIX.md. No live deployment or hardware commissioning was performed.
