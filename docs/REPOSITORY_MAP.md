# Repository map

| Path | Responsibility |
| --- | --- |
| frontend/src | React, TypeScript and shadcn UI source; theme, adapter, planning and setup screens |
| frontend/scripts | Single-file packaging and reproducible browser verification |
| mcp-server | Optional local stdio MCP connector, scoped HA configuration tools and protocol tests |
| custom_components/crop_steering | HA config flow, entities, setup/strategy/run APIs, storage and sidebar registration |
| addons/f2_control | Companion controller app, hardware coordinator, runtime validation and tests |
| crop-steering-engine | Pure decision core and its tests; vendored copy must remain identical |
| www/dashboard.html | Generated static web application |
| custom_components/crop_steering/www/dashboard.html | Identical generated application served by the integration |
| addons/f2_control/www/public/dashboard.html | Identical generated application served through ingress |
| tests | Integration and repository contract tests |
| docs | Install, operation, architecture and release process |
| `archive/2026-09-08/released-workspace` (tag) | Superseded dashboards, documentation and tools, at their original paths under archive/2026-09-08 |
| docs/TESTING.md / docs/ENTITIES.md | Development checks and entity reference |
| docs/error-codes.json | The one list of error codes (CS-101 …); docs/ERROR_CODES.md is written from it by scripts/render_error_codes.py, and the dashboard's Help & tools page imports it |
| img | Screenshots used by the README and docs |
| repository.yaml | HA app repository discovery metadata; the controller app is installed from this repository only |

Edit source in frontend/src and run the build; do not hand-edit generated dashboards. Small old-name HTML files are intentional compatibility redirects. Runtime entity IDs, room prefixes and the f2_control app slug remain stable; friendly names can change without breaking references.

The integration owns plan/configuration storage and per-room run metadata. Run records retain dates, stable zone/sensor IDs and timestamped reference targets; sensor readings stay in HA Recorder, with bounded authenticated history retrieval. Comparison and runtime calculators do not call actuator services.

 The controller reads one atomic, versioned strategy snapshot, validates freshness and runs the pure decision core before its hardware IO sequence. Configuration revision and controller acknowledgement are distinct so the UI cannot mistake a saved mapping for a running configuration.
