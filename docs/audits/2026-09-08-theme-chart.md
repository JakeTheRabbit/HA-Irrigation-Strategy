# Home Assistant theme and combined curves

Date: 2026-09-08

## Delivered

- `frontend/src/lib/ha-theme.ts` resolves Follow Home Assistant/system, Light and Dark preferences. Follow is the default for a new device; existing explicit preferences remain intact.
- Same-origin embedding reads the inherited variables from the actual iframe element and HA ancestors. Palette, text, cards, borders, sidebar, input fill, radius, shadows and font family follow the active host theme. Mutation observation and a one-second read-only fallback detect changes inside HA shadow roots. Already-loaded Roboto font faces can be reused without a runtime CDN.
- Cross-origin or standalone views use a system light/dark fallback. Dark fallback matches the supplied screenshot’s `#111111` canvas, `#1c1c1c` cards, neutral greys and cyan accent. Explicit overrides stop copying parent palette variables. The light standalone accent uses a darker cyan for readable small controls.
- Existing shadcn controls remain accessible and now use the native palette and density. Settings exposes all three appearance choices and explains whether Home Assistant, the system or an explicit override is active.
- Recorded history combines discovered zone VWC and EC sensor histories on independent percent and mS/cm axes. Solid/dashed curves distinguish the quantities, zone chips show/hide both series together, and missing history or an empty selection is explained. No data-adapter API changes or fake live history were introduced.

## Daily planning curve

`PlanningCurve` is exported from `frontend/src/components/planning-curve.tsx` with `{ parameters: Record<string, number>, lightsOn: number, lightsOff: number, onChange?: (key: string, value: number) => void }`.

The component draws a P0–P3 setpoint schematic for the currently supplied zone/day parameters. It is separate from recorded history and labeled Planning illustration. VWC and EC use explicit independent axes. Dryback matches authoritative engine behavior: `(peak − VWC) / peak × 100`. The planning reference is supplied field capacity or the supplied P1 target, disclosed as an illustration rather than a measured peak. A 70% reference and 20% of-peak drop gives 56% VWC. An intervening percentage-point interpretation from draft documentation was rejected after the controller adapter worker verified the actual engine calculation; regression tests preserve relative arithmetic. EC targets are drawn only for supplied phases. Nominal shot guides/bands use a disclosed full-retention assumption and do not claim actual retained volume, irrigation timing, sensor response or yield.

Phase widths use supplied P0 maximum wait, maximum P1 shot count and shot interval where available. Missing timing inputs use disclosed layout windows; they are never described as predicted controller transitions. Incompatible phase windows and a dryback target below the emergency floor are called out.

Targets support pointer dragging, keyboard Arrow/Home/End controls on accessible slider handles, and exact numeric controls. Edits call the parent’s local-plan callback only. Controller application remains the parent’s reviewed write workflow.

## Evidence

- Inspected the supplied HA screenshot and the classic curve implementation at `www/f2-classic.html`, formerly lines 4101–4183. The old physical/salt/yield simulation was not copied into this schematic.
- Confirmed native font/text conventions against Home Assistant’s primary frontend source: https://raw.githubusercontent.com/home-assistant/frontend/dev/src/resources/styles.ts.
- Theme resolution: 5 focused Vitest tests passed, including inheritance, override isolation and system fallback. Tests were added before implementation and first failed on the missing module.
- Planning model: 6 focused Vitest tests passed, including target reactivity, no fabricated missing values, overnight clock handling, relative-reference disclosure and contradictory floor settings. Tests were added before implementation and first failed on the missing module.
- Browser: combined chart rendered six lines for three zones; hiding one removed both corresponding lines; hiding all exposed an explicit empty-selection state. 390 px viewport fit passed.
- Browser: same-origin fixture inherited HA custom colors and changed from dark to light after a parent theme mutation. No browser exceptions. Dark overview axe WCAG A/AA scan returned zero violations.
- Browser: planning pointer drag, keyboard adjustment, exact EC editing and reactive SVG paths passed. Desktop planning axe WCAG A/AA scan returned zero violations; 390 px fit passed.
- Screenshots: `output/playwright/ha-native-dark-chart.png`, `ha-native-mobile-chart.png`, `planning-curve-desktop.png`, `planning-curve-mobile.png`.
- Full TypeScript was passing before parent navigation integrated new in-progress pages. Latest check is blocked only by the parent-owned pending `@/pages/setup` module. Final integrated type/build and workflow verification belong to the parent after those pages land.

No production HA writes, deployments, remote publication or commits were performed.

## Final integration evidence

Roboto is now bundled as an actual local Latin WOFF2, not only a family declaration. Complete OFL copyright/license text is embedded as non-executable metadata in the minified single-file artifact; both the font data URI and license text were verified. Browser font-face inspection confirmed Roboto loaded.

The authoritative controller worker confirmed relative dryback arithmetic. The final curve retains `reference × (1 − dryback/100)` and labels the setting `% of peak drop`; six regression tests pass. P3 has no scheduled EC target in the canonical contract, so the missing-target warning intentionally excludes P3.

Full TypeScript and all 16 focused theme, planning and hydraulic tests passed. Light-theme small accent text now uses a stronger foreground against tinted surfaces while preserving the inherited HA brand-color variable and the dark palette.
