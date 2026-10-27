# UI consolidation verification — 18 October 2026

This branch implements the approved layout A and ownership map, plus an all-room All zones landing page and a browser default-view selector. It includes the pending actionable setup-save error fix from the preceding branch.

## Delivered behavior

- Overview / All zones shows every discovered room, including inactive rooms, and all configured zones from the same controller snapshot. Zone actions select the correct room before opening its details. The page performs no actuator writes or additional per-room history polling.
- Settings / Display / Default view persists the browser landing preference. Explicit bookmarks, notification links and legacy `view` links take precedence. Blocked/invalid storage falls back to All zones.
- Irrigation contains Current day and Calendar contexts, one visible VWC/EC canvas, shared zone selection and retained drafts. Desktop target controls sit beside a sticky graph. The active schedule remains a distinct target owner; saving and arming are separate operations.
- Zone has one operational chart and one expandable explanation. History owns the full explorer, comparisons and recorded-target analysis. Water use has one consolidated table.
- Capabilities is a read-only searchable directory. Existing controls and registry-only controls have canonical destinations. Setup owns zone sizing/catch calibration; room defaults remain distinct. AI permissions, notification policy and equipment controls use their dedicated workspaces.
- Setup compares fresh hydraulic values before saving an old draft. Existing stock configuration omits cached measured level so that a rename cannot undo a more recent draw or refill. Backend safety/revision guards remain authoritative.
- Header watering and stop actions remain scoped to the visibly named selected room. Room in-use is configured in Setup and remains distinct from a watering pause.

## Verification

- 1,103 frontend tests across 84 files passed before final packaging; TypeScript and packaged production build passed.
- The complete compiled dashboard browser suite passed all 64 workflow groups, including desktop accessibility, 390px mobile layouts, default-view persistence, explicit-link precedence, setup reviews, notifications, draft protection and historical comparisons. No browser exceptions or live/external demo requests were observed.
- Repeatable navigation smoke: `DASHBOARD_URL=http://127.0.0.1:5271/dashboard.html node frontend/scripts/verify-navigation.mjs` against the packaged demo. Checks all-room coverage, correct-room details, saved default, explicit links, room-only history, zone dirty warnings, focused navigation after discard, mobile width and no browser errors.
- Repeatable planning smoke: `IRRIGATION_URL=http://127.0.0.1:5270 node frontend/scripts/verify-irrigation-workspace.mjs` against Vite demo. Checks one heading/chart, EC visibility, schedule interpolation redraw, draft retention, shared zone, arming lifecycle and no HA/external requests.
- Packaged legacy entry points were checked in a browser and unit tests: default preference respected; explicit legacy Help link preserved.
- Desktop and mobile screenshots visually inspected; refreshed README images are `img/all-zones.png` and `img/irrigation-workspace.png`.
- Fresh independent review identified three draft/context bugs. All were fixed and the exact workflows passed browser regression checks.
- Additional browser suites passed: live connection fixtures (17 groups), workspace (20), steering visuals (9), recipe library (4), tank status (13), Home Assistant shell (7), and calibration/AI instructions at desktop and phone widths. All use demo data or mocked connections; they do not actuate live hardware.
- Follow-up fixes point run-record links to History / Grows and watering guidance to the header, keep Setup drafts when locating the watering control, publish Irrigation's dirty state synchronously for browser-back protection, and retain the unique full-grow stage guide as a collapsed reference.

## Limits and release state

No live Home Assistant deployment, equipment actuation or hardware soak was performed. Demo strategy activation updates its strategy document without publishing the live engaged-ownership sensor, so the browser demo proves arming lifecycle but not the live engaged-schedule current-day lock; existing model/preview guards and tests remain in place. Existing-form capability links reach the correct owner workspace; fine-grained scrolling is provided for supplemental `config-*` sections.

Versions remain unchanged. This is a feature proposal into `testing`; pushing it does not publish a new HACS/Supervisor update. Production release follows CONTRIBUTING.md and docs/RELEASING.md.
