# Operator dashboard design

Date: 2026-09-07

## Outcome and scope
Replace the confusing primary operator experience with a React and shadcn/ui dashboard. User explicitly requested execution of full review, system analysis and GUI refactor and delegated reversible design decisions. Preserve original specialized workflows in f2-classic.html and clearly identify their scope and limitations. Keep existing URLs and generic Home Assistant installations working; ship a compiled self-contained f2.html, with no runtime CDN requirement.

## Design
Use a calm light dashboard by default, an optional dark theme, a persistent 232 px sidebar, a room selector above task navigation, and a compact connection/status header. Main content is left aligned, maximum width 1440 px. Palette: canvas #f8faf9, surface #ffffff, text #172b24, muted #63736b, primary #167352, warning #a65f0a. Use system Segoe UI for legibility, tabular numerals for measurements, 14 px body / 28 px page headings. Green denotes current selection and successful operation, amber denotes actions needed. No decoration without a task purpose.

Overview answers: is the room connected, what needs attention, how are zones doing, and what happened recently? Zones supports search and individual detail. Irrigation strategy groups editable parameters by daily phase and zone, labels VWC and dryback units, keeps drafts local until explicit review and apply, and reports partial failures. Activity filters real recorded events and exports CSV. Sensors exposes availability and recent reporting. Settings covers connection, theme, room-scoped controller enable/pause, and maintenance tools. Help explains concepts and maps older tools to clear jobs.

## Architecture and invariants
Source lives in frontend/. shadcn/ui components are checked in; Vite compiles JS/CSS into one HTML artifact. frontend/src/lib/types.ts defines the interface between UI and controller adapter. The adapter alone owns HA transport, room discovery, state normalization, and writes. UI components never construct entity IDs. All room IDs are resolved from entities present in the response; F1 legacy aliases are explicit and cannot fall through to F2. Missing or unavailable values display unavailable, never zero. Demo mode is explicit or GitHub Pages only, and never a live-error fallback. Demo writes mutate only in-memory fixtures.

Authentication uses an available HA session or an explicitly entered token kept only for the current tab session. Requests have bounded timeouts. Writes are allowed only to existing validated configuration entities. Readback must match before a write is reported applied. Numerical limits come from HA attributes; invalid/blank values are rejected. Changes are reviewed with room and zone names and before/after values. Polling must not erase drafts. Room changes and refreshes cannot apply stale responses. No direct valve or pump actions are added. The old manual-shot events and phase pins are not verified commands for the add-on. Cross-room recipe services are not used.

## Delivery and verification
The original f2.html is preserved as f2-classic.html. Primary f2.html and landing pages lead to the new dashboard; specialist pages get consistent return navigation. Package assets into addon web root without publishing or touching HA. Test state normalization, room isolation, configuration bounds, demo isolation, failures and stale responses. Browser checks cover every primary page, zone detail, reviewed edit, room changes, filters, dark theme, 390 px mobile, keyboard access, disconnected/auth-failure states and absence of runtime CDN dependencies. Run existing offline engine/integration tests. Audit findings are recorded with severity, source references and disposition.
