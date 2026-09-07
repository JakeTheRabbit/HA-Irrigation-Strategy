# Repository map

| Path | Responsibility |
| --- | --- |
| frontend/src | React, TypeScript and shadcn UI source; theme, adapter, planning and setup screens |
| frontend/scripts | Single-file packaging and reproducible browser verification |
| custom_components/crop_steering | HA config flow, entities, setup/strategy APIs, storage and sidebar registration |
| addons/f2_control | Companion controller app, hardware coordinator, runtime validation and tests |
| crop-steering-engine | Pure decision core and its tests; vendored copy must remain identical |
| www/dashboard.html | Generated static web application |
| custom_components/crop_steering/www/dashboard.html | Identical generated application served by the integration |
| addons/f2_control/www/public/dashboard.html | Identical generated application served through ingress |
| tests | Integration and repository contract tests |
| docs | Current install, operation, architecture and validation evidence |
| archive/2026-09-08 | Superseded dashboards, documentation and tools with original paths/hashes |
| docs/TESTING.md / docs/ENTITIES.md | Development checks and entity reference |
| img | Current screenshots; superseded captures are archived |
| repository.yaml | HA app repository discovery metadata |
| scripts/prepare_addon_release.py | Reviewed tracked-file packaging for the existing dedicated controller repository |

Edit source in frontend/src and run the build; do not hand-edit generated dashboards. Small old-name HTML files are intentional compatibility redirects. Runtime entity IDs, room prefixes and the f2_control app slug remain stable; friendly names can change without breaking references.

The integration owns plan/configuration storage. The controller reads one atomic, versioned strategy snapshot, validates freshness and runs the pure decision core before its hardware IO sequence. Configuration revision and controller acknowledgement are distinct so the UI cannot mistake a saved mapping for a running configuration.

Historical files in archive are not shipped as active dashboards or installation configuration. They can contain outdated claims and facility examples. The root formerly named config.yaml was archived as configuration.legacy.yaml to prevent Supervisor's recursive app scan from treating it as an app manifest.

Historical facility dashboards, packages, deploy YAML, environment templates, generated Lovelace sample and disabled workflows are in archive/2026-09-08. They are not needed for installation. The portable Lovelace generator remains in scripts/build_lovelace.py.
