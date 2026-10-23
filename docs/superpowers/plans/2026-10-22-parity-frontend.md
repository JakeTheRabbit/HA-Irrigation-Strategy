# Parity Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 28 mockup screens of the parity work (Status, Irrigation, History, Equipment, Settings, phone) in the React panel on top of the v2 `crop_steering.*` services, with a tree menu, shared review-and-apply, undo, timeline and live-event pieces, while every page still loads on a 3.17 backend.

**Architecture:** Shared pieces come first: tree menu and routes, a v2 service client with demo fixtures and missing-service detection, the `crop_steering_event` feed, drafts with review-and-apply and undo, visual primitives and `ShotTimeline`. Pages then extend the existing page where one exists, or add a new file under `frontend/src/pages/`. Pages hold no business logic: they render service responses and entity states, and every write goes through one review-and-apply flow with read-back.

**Tech Stack:** React 19, TypeScript 7, Vite 8 single-file build, Tailwind v4 + shadcn on `radix-ui`, recharts 3, sonner, lucide-react, vitest 5 (node environment, `renderToStaticMarkup`), Playwright + axe for browser checks.

**Spec:**
- `docs/superpowers/specs/2026-10-22-parity-ux.md` (UX, G1–G17, §3 patterns)
- `docs/superpowers/specs/2026-10-22-unified-schema.md` §4–§6 (event schema, services, entities, state machines)
- `docs/superpowers/mockups/*.png` (target design; the `.dc.html` files are their sources)

## Global Constraints

- Work only in `C:\Github\HA-Irrigation-Strategy-parity` on branch `feat/parity-system`. Run all frontend commands from `frontend/`. **npm is banned.**
  - Typecheck: `node node_modules/typescript/bin/tsc --noEmit`
  - Unit tests: `node node_modules/vitest/vitest.mjs run`
  - Build: `node node_modules/vite/bin/vite.js build`
  - Bundle: `node scripts/package.mjs` (writes `www/`, `addons/f2_control/www/public/` and `custom_components/crop_steering/www/`; only Task 31 runs it)
  - Browser checks: `node scripts/verify-*.mjs`
- Commit with `git -c user.email=123831499+JakeTheRabbit@users.noreply.github.com -c user.name=JakeTheRabbit commit`. Use conventional messages (`feat(frontend): …`) ending in a blank line plus `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Each task is one commit, frontend only. The backend layer is a separate plan and separate commits.
- **Definition of done for every page task:**
  - tsc is clean.
  - vitest passes.
  - The task's `scripts/verify-parity-<id>.mjs` passes at 1440×1000 and 390×844, at DPR 2, in both `?demo=1` and `?demo=1&backend=3.17`.
  - The screenshot has been compared against its mockup PNG (see Task 2's harness) and the differences are listed in the commit body.
- **House rules (owner):**
  - Show every fact once per screen.
  - The room tree is the only room/zone picker on desktop.
  - Prefer visuals over number walls (gauges with a shaded band, drawn slabs, tanks and bottles, timelines).
  - Show problems in place, on the thing that has them, never as a separate list.
  - Use plain grower words, and give buttons specific labels ("Apply 2 changes", never "Submit" or a bare "Next").
  - Writes go through review-and-apply ending in **"Written and read back HH:MM"**.
  - Use Undo instead of a confirm dialog wherever the action is reversible. Physical actions use hold-to-run, and Stop all keeps its existing guard.
  - On phone, keep the bottom bar with 5 sections.
- **Out of scope:** users and roles, tasks, IPM, compliance, climate and lighting control. Climate is shown as readings only.
- **Older backend:** a page whose v2 service is missing still renders everything that works on v1. Where the missing part would be, it shows `NeedsIntegration` (heading **"Needs integration 3.18"**). It never crashes and never throws a page error. The minimum version is the constant `PARITY_MIN_VERSION = "3.18.0"`.
- **Desktop menu:** an expandable disclosure tree with every sub-page.
  - Desktop (≥ 721 px): in-page `.page-tabs` are hidden.
  - Phone (≤ 720 px): the bottom bar keeps 5 sections and the sub-tabs stay inside the page.
- **Units:** storage stays mS/cm, °C and litres. One formatter owns every unit label and never rounds past source precision. Tables and conversions are not rounded.
- **Times:** all time maths goes through `lib/time.ts` (epoch ms plus `controller.timeZone`, `Intl.DateTimeFormat`).
- **Generated bundles:** they change only together with their source. Lanes do not commit `www/` bundles; Task 31 regenerates them once.
- **Tests:** vitest files sit next to logic as `src/lib/<name>.test.ts`. Components are rendered with `renderToStaticMarkup(createElement(C, props))`, because there is no jsdom.

## Review Focus

1. **A 3.17 backend (v2 service missing).**
   - Expected: every new page and section shows "Needs integration 3.18" in place, and v1 content still renders.
   - Pinned by: Task 3 `callV2 maps service_not_found to missing`, and by every verify script's `backend=3.17` pass.
2. **A non-admin HA user.**
   - `subscribe_events` for a custom event type is refused to non-admins. Expected: the live feed falls back to polling `journal_query` every 30 s while visible, with no error banner. Writes show "Only a Home Assistant administrator can change this."
   - Pinned by: Task 4 `falls back to polling when subscribe_events is unauthorized`, and Task 5 `forbidden error shows admin copy`.
3. **The read-back disagrees, or only part of a multi-row apply succeeds.**
   - Expected: each failed row says "Controller still holds {old}. Nothing else was changed." plus **Try again**. The draft is kept and no success receipt is shown.
   - Pinned by: Task 5 `partial apply keeps failed rows in the draft`.
4. **A stale revision**, because a second tab or AiGrow wrote first (`stale_revision`).
   - Expected: "Someone else changed this at HH:MM. Reload their version and reapply your edits." plus **Reload**, and the draft is kept.
   - Pinned by: Task 5 `stale_revision keeps draft and offers reload`.
5. **The connection drops mid-wizard** (calibration or pump prime).
   - Expected: no capture is sent on a stale reading, the hold button releases (stop is sent on `pointercancel`/`visibilitychange`), and "Resume calibration" appears within 30 min.
   - Pinned by: Task 23 `hold releases on visibility hidden`, and Task 24 `stale reading disables Capture`.

## Parallel lanes

Tasks 1–7 are the trunk. They run in order, because every page consumes their interfaces. After Task 7, these lanes touch disjoint files and can run at the same time. Each lane rebases on the trunk and commits only its own files.

| Lane | Tasks | Files touched (exclusive) |
|---|---|---|
| A Status | 8, 9, 10 | `pages/all-zones.*`, `pages/today.*`, `pages/zone.*`, `components/zone-slab.tsx`, `components/day-timeline.tsx`, `lib/zone-shot-log.ts` |
| B Irrigation | 11, 12, 13, 14 | `pages/watering.*`, `pages/strategy.tsx`, `pages/timers.*`, `pages/grow-planner.*`, `components/presets-panel.tsx`, `lib/timers.ts` |
| C History | 15, 16, 17, 18 | `pages/explorer.*` (the renamed `timeline.tsx`), `components/history-explorer.tsx`, `pages/water-use.*`, `pages/comparison*.tsx`, `pages/changes.*`, `components/setting-history.tsx`, `lib/changes.ts`, `lib/flow-check.ts` |
| D Equipment | 19, 20, 21, 22, 23, 24 | `pages/probes.*`, `pages/dosing.*`, `pages/reservoir.tsx` (removed), `pages/stock.*`, `pages/setup.tsx`, `components/supply-editor.*`, `pages/pump-calibration.*`, `pages/feed-calibration.*`, `lib/supply.ts`, `lib/feed-calibration.ts`, `lib/probe-offset.ts` |
| E Settings | 25, 26, 27, 28, 29 | `pages/alert-rules.*`, `components/rule-sentence.*`, `pages/notifications.*`, `pages/system.*`, `components/brain.tsx` (AiSettings only), `pages/settings.*`, `components/display-settings.tsx`, `lib/alert-rules.ts`, `lib/system-status.ts`, `lib/units.ts` |
| F Shell polish | 30 | `components/command-palette.*`, `lib/command-palette.ts`, `components/app-header.*` |

The shared files `lib/parity-demo.ts` and `lib/parity-types.ts` are owned by Task 3. A lane that needs a new fixture adds it in its own file, `lib/parity-demo/<lane>.ts`, and Task 3's index spreads every file in that folder (`import.meta.glob("./parity-demo/*.ts", {eager:true})`). Lanes never edit the index. `App.tsx` route wiring was done once in Task 1 with placeholder components, so lanes replace only their placeholder file.

Task 31 runs last, after all lanes merge.

## Mockup → page map

| # | Mockup | Route (hash) | Existing file → action | Delta |
|---|---|---|---|---|
| S1 | 02-S1-AllRooms | `#/all-zones` | `pages/all-zones.tsx` → extend | The cards were redrawn in a4e4a728. Add the queued-shot line, a hollow last-shot dot under 80 % flow, a calibration-due flag on the feed pH, the grow-day/stage entities (G16) and the header bar. |
| S2 | 03-S2-Room | `#/today` (opened from the room tree) | `pages/today.tsx` → extend | Add a "Today" 3-row `ShotTimeline` strip with "Open full timeline →", and zone rows with a Sensors column and the problem in place on the sensor. Remove the duplicate HMI table, so every fact appears once. |
| S3 | 04-S3-Zone | `#/zone/N` | `pages/zone.tsx` → extend | Add "Compare with Off · Yesterday · Last run", a Pore EC chart with the AI suggestion card (Apply/Dismiss), a "Shot log · today" card and expected shots from `projection_app`. |
| I1 | 05-I1-Timeline | `#/plan/watering` | **new** `pages/watering.tsx` | G5 + G1 lane: date strip, 12/24/48 h span, stage chips, block popover, Skip this shot. |
| I2 | 06-I2-CurrentDay | `#/plan/targets` | `pages/strategy.tsx` → extend | Replace `ReviewDialog` with the `ReviewApply` bar (per-row Undo), add the "Last applied" receipt and "This afternoon" consequence from `strategy_preview`, and show "Nothing is sent to the controller until you apply". |
| I3 | 07-I3-Timers | `#/plan/timers` | **new** `pages/timers.tsx` | G7: program list, editor sentence, next-24 h preview strip, irrigation-mode table, daily max / pump capacity / safety cards. |
| I4 | 08-I4-GrowPlan | `#/plan/schedule` | `pages/grow-planner.tsx` → extend | G10: presets come from the controller (`preset_*`) instead of the browser library, plus "Copy … to room" with a `copy_config` preview diff. Label: "Grow plan & presets". |
| H1 | 09-H1-Explorer | `#/history/explorer` (old `#/history/timeline` redirects) | `pages/timeline.tsx` → rename to `pages/explorer.tsx`, extend `components/history-explorer.tsx` | Phase lane, shots lane, problem annotations in place, "Compare with last run" toggle, "Export CSV · N series". The setpoint log moves to Changes. |
| H2 | 10-H2-WaterFlow | `#/history/water` | `pages/water-use.tsx` → rebuild | G4: a per-zone arc gauge of metered vs asked, asked/metered per-shot bars, 7-day trend, leak check, water per plant vs the room median. |
| H3 | 11-H3-Compare | `#/history/compare` | `pages/comparison*.tsx` → extend | Run cards with harvest result / "Add harvest result", four small multiples with one plain-sentence callout each, and "Line runs up by" select. |
| H4 | 12-H4-Changes | `#/history/changes` | **new** `pages/changes.tsx` | G8: feed, chips (Made by, Kind), selected-change panel, revert. The clock popover goes on setting rows. |
| E1 | 13-E1-Probes | `#/equipment/probes` | `pages/probes.tsx` → extend | G9 offset column, inline "Match handheld", substrate curve card, "Where to put a probe" (G14). Feed calibration moves out to E4. |
| E2 | 14-E2-Dosing | `#/equipment/dosing` (old `#/equipment/feed` redirects) | `pages/dosing.tsx` → extend, `pages/reservoir.tsx` folded in and removed | Plumbing diagram (stock → pumps → batch tank → feed pump → zones), the mix-check failure card in place, recipes by week, next batch. |
| E3 | 15-E3-PumpWizard | `#/equipment/pump-calibration` | **new** `pages/pump-calibration.tsx` | G3: 5-step wizard with hold-to-prime and the 30 s run. |
| E4 | 16-E4-FeedCal | `#/equipment/feed-calibration` | **new** `pages/feed-calibration.tsx` (replaces the `components/probe-calibration.tsx` entry point) | G2: 5-step wizard, stability ring, Wake Lock. |
| E5 | 17-E5-Stock | `#/equipment/stock` | `pages/stock.tsx` → extend | Bottles drawn to scale with a low line, batches and days left, "Log refill to N L", used-per-week bars, refills list. |
| E6 | 18-E6-Setup | `#/equipment/setup` | `pages/setup.tsx` → extend with **new** `components/supply-editor.tsx` | G1: pump max flow, max zones at once, dripper table, exclusive groups, "What can run together", a review panel with checks. |
| T1 | 19-T1-AlertRules | `#/settings/alerts` | **new** `pages/alert-rules.tsx` | G6: sentence builder, yesterday replay, test push, "Your rules" list. |
| T2 | 20-T2-Notifications | `#/settings/notifications` | `pages/notifications.tsx` → extend | "Your rules" column, per-phone room chips, Emergencies loud, quiet hours strip, room mutes, the `ReviewApply` bar. |
| T3 | 21-T3-System | `#/settings/system` | **new** `pages/system.tsx` | G17: health ring sentence, software versions, heartbeat bars, every mapped device by kind with open CS alerts in place. |
| T4 | 22-T4-AI | `#/settings/ai` | `components/brain.tsx` `AiSettings` → extend | A judges × rooms matrix, budget bar, Dry run, model segmented control, "What it did, and what happened". |
| T5 | 23-T5-Dashboards | `#/settings` | `pages/settings.tsx` → extend | G15 units (EC, °C/°F, litres/US gal, 24/12 h), "Where the app opens", G11 wall dashboards. HA connection, appearance and display options sit under "More display options". |
| P1 | 24-P1-AllRooms | `#/all-zones` at 390 px | as S1 | 3-up zone tiles, feed line, bottom bar. |
| P2 | 25-P2-Timeline | `#/plan/watering` at 390 px | as I1 | `ShotTimeline orientation="vertical"`, rooms as columns, swipe sideways, 12/24 h. |
| P3 | 26-P3-Zone | `#/zone/N` at 390 px | as S3 | Swipeable VWC / Pore EC charts, gauges, suggestion, next. |
| P4 | 27-P4-Rule | `#/settings/alerts?rule=new` at 390 px | as T1 | Stacked native selects, replay at full width, Send test + Save rule. |
| P5 | 28-P5-Calibrate | `#/equipment/feed-calibration` at 390 px | as E4 | Full-screen ring, segmented step bar, ✕ close. |
| X1 | 29-X1-Schema | — | not a page | — |

The shell (top bar, tree menu, room tree) appears on every mockup and is built in Tasks 1, 7 and 30.

Routes `history/grows`, `history/drivers`, `settings/features`, `help` and `today/ai` stay routable but leave the tree menu:
- Grows is linked from the Compare run cards ("Manage runs ›").
- Capabilities and Help are linked from System ("Capabilities ›") and from every CS-code "What to do →".
- Today/AI is linked from the header "AI acting" chip.

## Contract assumptions (backend gaps — confirm with the backend plan)

The frontend codes against schema §5.2. Where the mockups need more than §5.2 provides, the plan uses the fallback in brackets and records the request here:

1. **No `history_revert`.** [Undo re-writes the stored `before` values through the same service: entity writes through `applyChanges`, store writes through `*_set` with the saved copy.] Request `history_revert({event_id})`.
2. **No `alert_rule_list` or `alert_rule_preview`** (the replay). [The list is read from `binary_sensor.crop_steering_rule_*` attributes. The replay shows `NeedsIntegration`.] Request both. The rule list also needs `last_fired`, `firing_since` and `current_value`. Sources need `probe.silence_s` and `stock.litres`.
3. **No `timer_program_list`, `timer_program_preview` or `timer_skip`.** [Programs are read from `select.*_irrigation_mode` attributes, and the preview comes from `timer_program_set` with `active:false`.] Request all three.
4. **`timeline_get` blocks lack** `litres_metered`, `reason`, `requested_start` (pump wait), `vwc_before`/`vwc_expected`, `phase` and a pump-load series. The date strip also needs per-day problem counts. [The popover hides missing rows, and the date strip calls `timeline_get` once per visible day for 7 days.] Request these fields plus `timeline_summary({rooms, days})`.
5. **`history_changes` lacks** `id`, `kind` (setpoint/plan/recipe/setup/calibration/alerts), `outcome` (the "Too soon to judge…" line), `limits` ("learner may move ±15 min"), an `until` param, and multi-room. [The client loops rooms and merges, and outcome lines are hidden when absent.]
6. **Calibration live state.** `calibration_start` must return `raw_entity_id`, `temperature_entity_id` and `dosing_paused: true`. Live drift is computed client-side from `subscribe_entities`, while the server-side `stable` flag gates Capture.
7. **Pumps.**
   - There is no `pump_stop`, so hold-to-prime needs it.
   - The `seconds≤120` cap disagrees with the UX's 30 s cap; the client sends ≤ 30.
   - Interlock blockers need a pre-check (`pump_prime` with `dry_run:true` returning `blockers[]`).
8. **`system_status_get` lacks** per-entity `kind`, `name`, `uptime_7d_pct` and `last_change`, plus heartbeat history (`beats[]` with missed flag and read-back latency), the HA version, the AI model/calls/budget, and the dashboard card version seen.
9. **Notifications.** `notify_get`'s quiet hours, room mute until, "Emergencies loud" and per-target test results need confirming against `notify_api.py`. [Missing keys hide their control.]
10. **`dashboard_create`** needs a template id (`facility_wall|room_tablet|dosing_station`) and a list of previously created dashboards (`dashboard_list`).
11. **`display_save`** needs `volume_unit` and `clock` beside `ec_unit` and `temp_unit`.
12. **Event subscription for non-admins.** HA allows `subscribe_events` only for allowlisted event types. Request a websocket command `crop_steering/subscribe` (any signed-in user, filtered by room). [The client tries `subscribe_events`, then falls back to polling.]

---

## File structure (new files)

```
frontend/src/
  lib/nav-tree.ts            tree menu model + open-state storage
  components/nav-tree.tsx    disclosure-nav tree (desktop sidebar)
  lib/parity-types.ts        v2 envelope + response types for every new service
  lib/parity-api.ts          callV2 / useParity / isMissingService / PARITY_MIN_VERSION
  lib/parity-demo.ts         demo answers for every v2 action (+ parity-demo/<lane>.ts)
  components/needs-integration.tsx
  lib/events.ts              crop_steering_event feed (subscribe, poll fallback, hook)
  lib/drafts.ts              sessionStorage + BroadcastChannel drafts
  lib/undo.ts                10 s sonner Undo toast
  components/review-apply.tsx  bar/panel + applied receipt
  lib/time.ts                zoned clock maths and formatting
  components/primitives/{arc-gauge,ring,capacity-bar,step-rail,hold-button}.tsx
  lib/shot-timeline.ts       pure layout + v2→row mapping
  components/shot-timeline.tsx (+ .css)
  pages/{watering,timers,changes,pump-calibration,feed-calibration,alert-rules,system}.tsx (+ .css)
  components/{supply-editor,rule-sentence,setting-history,presets-panel,command-palette}.tsx
  lib/{timers,changes,flow-check,supply,feed-calibration,probe-offset,alert-rules,system-status,command-palette,zone-shot-log}.ts
frontend/scripts/
  parity-harness.mjs         shared browser harness + mockup compare
  verify-parity-<id>.mjs     one per page task
```

---

### Task 1: Tree menu and new routes

Replaces the 3.17.0 five-button nav. Every later page has a route and a placeholder from here on.

**Files:**
- Create: `frontend/src/lib/nav-tree.ts`, `frontend/src/components/nav-tree.tsx`, `frontend/src/components/nav-tree.css`, `frontend/src/pages/placeholder.tsx`
- Modify: `frontend/src/lib/routes.ts` (Page union, PAGES, LEGACY_PAGES, SECTION_PAGES, zone-focus list), `frontend/src/components/page-tabs.tsx` (TABS, labels), `frontend/src/components/page-tabs.css` (hide at ≥ 721 px), `frontend/src/App.tsx:70-76,230-330` (sidebar uses `NavTree`, render chain adds new pages), `frontend/scripts/verify-navigation.mjs`, `frontend/scripts/verify-dashboard.mjs` (nav selectors only)
- Test: `frontend/src/lib/nav-tree.test.ts`, `frontend/src/lib/routes.test.ts`

**Interfaces:**
- Produces:
  - New `Page` ids: `"plan/watering" | "plan/timers" | "history/explorer" | "history/changes" | "equipment/pump-calibration" | "equipment/feed-calibration" | "settings/alerts" | "settings/system"`. Removed: `"history/timeline"` and `"equipment/feed"` (both now LEGACY redirects).
  - `export interface NavSection { section: Section; label: string; icon: LucideIcon; items: { page: Page; label: string }[] }`
  - `export const NAV_TREE: readonly NavSection[]`
  - `export function readOpenSections(): Set<Section>` and `export function writeOpenSections(open: Set<Section>): void` (key `crop-steering.nav-open`, try/catch)
  - `export function NavTree(props: { page: Page; navigate: (page: Page) => void }): JSX.Element`
  - `export function Placeholder(props: { title: string }): JSX.Element`, which later tasks replace

**Routes and labels:**
- `NAV_TREE` order and labels are exactly:
  - Status ▸ All rooms (`all-zones`)
  - Irrigation ▸ Timeline (`plan/watering`), Current day (`plan/targets`), Timer programs (`plan/timers`), Grow plan & presets (`plan/schedule`)
  - History ▸ Explorer (`history/explorer`), Water & flow (`history/water`), Compare runs (`history/compare`), Changes (`history/changes`)
  - Equipment ▸ Probes & offsets (`equipment/probes`), Feed & dosing (`equipment/dosing`), Stock (`equipment/stock`), Pump calibration (`equipment/pump-calibration`), Feed pH/EC calibration (`equipment/feed-calibration`), Setup: pumps & valves (`equipment/setup`)
  - Settings ▸ Alert rules (`settings/alerts`), Notifications (`settings/notifications`), System status (`settings/system`), AI assistant (`settings/ai`), Dashboards & display (`settings`)
- `TABS` (phone in-page tabs) mirrors `NAV_TREE` items per section.
- `SECTION_PAGES`: `plan → plan/watering`, `history → history/explorer`, `equipment → equipment/probes`, `settings → settings/alerts`.
- `LEGACY_PAGES` adds `"history/timeline": "history/explorer"` and `"equipment/feed": "equipment/dosing"`. It repoints `"equipment/tank"` and `activity` / `log` / `logs` to their new homes.
- Zone focus (`?zone=`) applies to `plan/targets`, `plan/schedule` and `history/explorer`.

- [ ] **Step 1: Write the failing tests**

```ts
// nav-tree.test.ts
test("tree lists every sub-page once in menu order", () => {
  expect(NAV_TREE.map((s) => s.label)).toEqual(["Status","Irrigation","History","Equipment","Settings"]);
  expect(NAV_TREE.flatMap((s) => s.items.map((i) => i.page))).toHaveLength(20);
  expect(new Set(NAV_TREE.flatMap((s) => s.items.map((i) => i.page))).size).toBe(20);
});
test("open state survives a throwing localStorage", () => {
  vi.stubGlobal("localStorage", { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } });
  expect(readOpenSections()).toEqual(new Set());
  expect(() => writeOpenSections(new Set(["plan"]))).not.toThrow();
});
test("current page's section renders open with aria-current", () => {
  const html = renderToStaticMarkup(createElement(NavTree, { page: "history/changes", navigate: () => {} }));
  expect(html).toMatch(/aria-expanded="true"[^>]*>[^<]*History/);
  expect(html).toMatch(/aria-current="page"[^>]*>Changes/);
  expect(html).toMatch(/aria-expanded="false"[^>]*>[^<]*Equipment/);
});
// routes.test.ts additions
test("old addresses land on their new homes", () => {
  expect(canonicalHash("#/history/timeline?zone=2")).toBe("#/history/explorer?zone=2");
  expect(parseRoute("#/equipment/feed").route.page).toBe("equipment/dosing");
  expect(parseRoute("#/settings/alerts").route.page).toBe("settings/alerts");
  expect(parseRoute("#/plan").route.page).toBe("plan/watering");
});
```

- [ ] **Step 2: Run** `node node_modules/vitest/vitest.mjs run src/lib/nav-tree.test.ts src/lib/routes.test.ts` → FAIL (`NAV_TREE` not exported).

- [ ] **Step 3: Implement**
  - Follow the disclosure-nav pattern: each section is a `<button aria-expanded aria-controls>` with a chevron, and its items are `<a href={routeHash}>` links (`aria-current="page"` on the current one).
  - Keyboard: ↑/↓ move focus across visible items, Home/End go to the first/last item, → opens a section, and ← closes it or moves focus to the section's button.
  - Open state = stored set ∪ the current page's section.
  - The ROOMS `RoomTree` stays below it, unchanged.
  - Add `@media (min-width: 721px) { .page-tabs { display: none } }`. Phone keeps the bottom bar (`App.tsx:486`) on 5 sections, and its target is `SECTION_PAGES`.
  - In `App.tsx`, each new page renders `<Placeholder title=…/>`, and `pageLabel` reads `NAV_TREE`.

- [ ] **Step 4: Run** tsc, then vitest → PASS. Update `verify-navigation.mjs` so it:
  - asserts the tree;
  - checks that clicking "Changes" sets `aria-current` and hash `#/history/changes`;
  - checks that after a reload the History section stays open;
  - checks that `.page-tabs` is hidden at 1440 px and visible at 390 px;
  - checks that the bottom bar has 5 buttons;
  - runs axe with no violations on `nav[aria-label="Main navigation"]`.

  Then change only the nav selectors in `verify-dashboard.mjs`.

- [ ] **Step 5: Run** `node node_modules/vite/bin/vite.js build && node scripts/verify-navigation.mjs` → exit 0. Commit as `feat(frontend): tree menu with every sub-page`.

### Task 2: Browser harness and mockup compare

**Files:**
- Create: `frontend/scripts/parity-harness.mjs`
- Test: `frontend/scripts/verify-parity-harness.mjs` (a smoke test of the harness itself)

**Interfaces:**
- Produces: `export async function runParity({ id, route, mockup, phoneMockup?, check }: { id: string; route: string; mockup: string; phoneMockup?: string; check: (page: Page, ctx: { width: number; backend: "3.18" | "3.17" }) => Promise<void> }): Promise<void>`

**What `runParity` does:**
1. Serve `frontend/dist/index.html` (not `www/`, so lanes never touch bundles) on an ephemeral 127.0.0.1 port.
2. For each width in `[1440×1000, 390×844]` at `deviceScaleFactor: 2`, and for each backend in `["3.18","3.17"]`:
   - open `?demo=1${backend==="3.17"?"&backend=3.17":""}#${route}`;
   - collect `pageerror`;
   - abort and record any off-origin or `/api/` request;
   - run `check`;
   - assert there is no horizontal overflow;
   - run axe on `main` (no violations);
   - screenshot to `output/playwright/parity/<id>-<width>-<backend>.png`.
3. Write `output/playwright/parity/<id>-compare.html`, which shows the 1440 screenshot beside `docs/superpowers/mockups/<mockup>` (and the 390 one beside `phoneMockup`).
4. At the end, assert `errors` and `forbidden` are both `[]`.

**Mockup compare (manual):** the implementer opens both images (`Read` tool) and lists every region that differs in layout, copy or visual form in the commit body. Sample numbers may differ; structure, copy and visuals may not.

- [ ] **Step 1:** Write `verify-parity-harness.mjs`. It calls `runParity({id:"harness", route:"/all-zones", mockup:"02-S1-AllRooms.png", phoneMockup:"24-P1-AllRooms.png", check: async (p) => { await p.getByRole("navigation",{name:"Main navigation"}).waitFor(); }})`.
- [ ] **Step 2:** Run it → FAIL (module not found).
- [ ] **Step 3:** Implement the harness as above.
- [ ] **Step 4:** Build, then run `node scripts/verify-parity-harness.mjs` → exit 0, and the four screenshots and the compare HTML exist.
- [ ] **Step 5:** Commit as `test(frontend): parity browser harness`.

### Task 3: v2 service client, missing-service detection, demo fixtures

**Files:**
- Create: `frontend/src/lib/parity-types.ts`, `frontend/src/lib/parity-api.ts`, `frontend/src/lib/parity-demo.ts`, `frontend/src/lib/parity-demo/.gitkeep`, `frontend/src/components/needs-integration.tsx`
- Modify:
  - `frontend/src/lib/operator-types.ts`: add `ParityAction` to `OperatorAction`.
  - `frontend/src/lib/client.ts:189-238`: the allowed list += `PARITY_ACTIONS`.
  - `frontend/src/lib/use-controller.ts:494-520`: room-scoped prefixes, and read-only actions excluded from the `writing` lock.
  - `frontend/src/lib/operator-demo.ts`: delegate `ParityAction`s to `parityDemo`.
  - `frontend/src/lib/demo.ts`: `?backend=3.17` flag.
- Test: `frontend/src/lib/parity-api.test.ts`

**Interfaces:**
- Produces:
  - `export const PARITY_MIN_VERSION = "3.18.0"`
  - `export const PARITY_ACTIONS = ["journal_query","timeline_get","history_changes","intent_submit","supply_get","supply_save","pump_prime","pump_stop","pump_calibrate","pump_calibration_commit","calibration_start","calibration_capture","calibration_commit","calibration_revert","probe_offset_set","alert_rule_set","alert_rule_delete","alert_rule_test","alert_rule_preview","alert_rule_list","alert_ack","timer_program_set","timer_program_delete","timer_program_list","timer_skip","preset_list","preset_save","preset_apply","preset_delete","copy_config","dashboard_create","dashboard_list","system_status_get","history_revert"] as const`
  - `export type ParityAction = (typeof PARITY_ACTIONS)[number]`. Actions in Contract assumptions items 1–3, 7 and 10 are included so the client is ready; until the backend ships them they resolve to `missing`.
  - `export type V2Outcome<T> = { kind: "ok"; data: T; revision: number | null; readback: { status: "verified" | "unverified"; at: string | null }; eventIds: string[] } | { kind: "missing" } | { kind: "error"; code: "stale_revision" | "invalid" | "forbidden" | "guard_refused" | "unavailable" | "unknown"; message: string; currentRevision?: number }`
  - `export function isMissingService(error: unknown): boolean`. It matches HA `not_found` / `service_not_found` codes, "Service crop_steering.x not found", and client.ts's "needs the updated Crop Steering integration".
  - `export async function callV2<T>(controller: Controller, action: ParityAction | OperatorAction, data: Record<string, unknown>): Promise<V2Outcome<T>>`. It always sends `api: 2`. If an existing (v1) service answers without `api: 2`, that is `missing`.
  - `export function useParity<T>(controller: Controller, action: ParityAction, data: Record<string, unknown> | null, deps: unknown[]): { state: "loading" | "ready" | "missing" | "error"; data: T | null; error: string | null; reload(): void }`. A `null` data value skips the call.
  - `export function NeedsIntegration(props: { feature: string; compact?: boolean }): JSX.Element`
  - `parity-types.ts`: one exported interface per §5.2 response `data` (`TimelineGetData`, `HistoryChange`, `SupplyDoc`, `TimerProgram`, `AlertRule`, `AlertPreview`, `PresetDiff`, `SystemStatus`, `CalibrationSession`, `PumpCalibrationResult`, `CsEvent` from §4), using exactly the schema field names. Gap fields from Contract assumptions are optional (`?`).

**`NeedsIntegration` copy:**
- Heading **"Needs integration 3.18"**.
- Body: *"{feature} needs Crop Steering 3.18 or newer. Update the integration and the controller app together; the rest of this page keeps working."*
- `compact` renders one line: *"Needs integration 3.18"*, with the body in an `InfoTip`.

- [ ] **Step 1: Write the failing tests**

```ts
test("callV2 maps service_not_found to missing", async () => {
  const c = fakeController({ operator: () => Promise.reject(Object.assign(new Error("Service crop_steering.timeline_get not found."), { code: "not_found" })) });
  expect(await callV2(c, "timeline_get", {})).toEqual({ kind: "missing" });
});
test("callV2 maps a v1-shaped answer to missing", async () => {
  const c = fakeController({ operator: () => Promise.resolve({ revision: 3, zones: [] }) });
  expect((await callV2(c, "setup_read", {})).kind).toBe("missing");
});
test("callV2 unwraps the v2 envelope", async () => {
  const c = fakeController({ operator: () => Promise.resolve({ api: 2, ok: true, revision: 42, readback: { status: "verified", at: "2026-10-22T14:02:00+13:00" }, event_ids: ["e1"], data: { x: 1 } }) });
  expect(await callV2(c, "supply_get", {})).toEqual({ kind: "ok", data: { x: 1 }, revision: 42, readback: { status: "verified", at: "2026-10-22T14:02:00+13:00" }, eventIds: ["e1"] });
});
test("callV2 keeps stale_revision and current revision", async () => {
  const c = fakeController({ operator: () => Promise.resolve({ api: 2, ok: false, error: { code: "stale_revision", message: "m", current_revision: 43 } }) });
  expect(await callV2(c, "supply_save", {})).toMatchObject({ kind: "error", code: "stale_revision", currentRevision: 43 });
});
test("demo with backend=3.17 answers every parity action as missing", async () => {
  for (const a of PARITY_ACTIONS) expect((await callV2(demoController("?demo=1&backend=3.17"), a, {})).kind).toBe("missing");
});
test("demo 3.18 answers every parity action ok", async () => {
  for (const a of PARITY_ACTIONS) expect((await callV2(demoController("?demo=1"), a, {})).kind).toBe("ok");
});
```

- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
  - `parityDemo(action, data, now)` returns envelopes built from the demo rooms (F2 "Flower · bulk", day 38 of 63; F1 "Flower · stretch", day 12; and the existing demo room ids).
  - Fixture numbers follow the mockups where the existing demo room gives no value.
  - The index spreads `import.meta.glob("./parity-demo/*.ts", { eager: true })`, where each module exports `answers: Partial<Record<ParityAction, DemoAnswer>>`.
- [ ] **Step 4:** Run tsc and vitest → PASS.
- [ ] **Step 5:** Commit as `feat(frontend): v2 service client with older-backend detection`.

### Task 4: Live `crop_steering_event` feed

**Files:**
- Create: `frontend/src/lib/events.ts`
- Modify: `frontend/src/lib/use-controller.ts` (start/stop the feed beside `subscribeLive`, line 282), `frontend/src/lib/types.ts:148` (Controller additions)
- Test: `frontend/src/lib/events.test.ts`

**Interfaces:**
- Consumes: `LiveConnection.subscribeMessage` (`lib/live.ts:9`), `callV2(…, "journal_query", …)`, `whileVisible` (`lib/live.ts`)
- Produces:
  - `export function startEventFeed(opts: { connection: LiveConnection | null; poll: (since: string) => Promise<CsEvent[]>; onEvents: (e: CsEvent[]) => void; visible: () => boolean }): () => void`
  - `Controller.recentEvents: readonly CsEvent[]` (a ring of 300, newest last, deduped on `id`)
  - `export function useCsEvents(controller: Controller, filter: (e: CsEvent) => boolean): CsEvent[]`
- Feed behaviour:
  - It tries `{type:"subscribe_events", event_type:"crop_steering_event"}`.
  - On `unauthorized`, or with no connection, it polls `journal_query {since:lastTs, limit:200}` every 30 s while visible.
  - If `journal_query` is missing, it stops quietly. Pages then use their own reads.

- [ ] **Step 1: Write the failing tests**
  - `subscribes to crop_steering_event and dedupes on id`: two messages with the same id → `onEvents` sees one.
  - `falls back to polling when subscribe_events is unauthorized`: the fake connection rejects with `{code:"unauthorized"}`; fake timers at 30 s → `poll` called with the last `ts`.
  - `does not poll while hidden`.
  - `stops polling when journal_query is missing`: `poll` throws a missing-service error → no second call.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement as specified.
- [ ] **Step 4:** Run → PASS. tsc is clean.
- [ ] **Step 5:** Commit as `feat(frontend): live crop_steering_event feed with poll fallback`.

### Task 5: Drafts, Review & apply, Undo, time helpers

**Files:**
- Create: `frontend/src/lib/drafts.ts`, `frontend/src/lib/undo.ts`, `frontend/src/lib/time.ts`, `frontend/src/components/review-apply.tsx`, `frontend/src/components/review-apply.css`
- Test: `frontend/src/lib/review-apply.test.ts`, `frontend/src/lib/time.test.ts`

**Interfaces:**
- Produces:
  - `export function useDraft<T>(key: string, saved: T): { draft: T; set(next: T): void; dirty: boolean; discard(): void }`. It uses sessionStorage key `crop-steering.draft.<key>` and `BroadcastChannel("crop-steering-drafts")`, both in try/catch. It calls the page's `onDirtyChange` through the existing App dirty guard.
  - `export interface ReviewRow { id: string; label: string; before: string; after: string; note?: string; undo(): void }`
  - `export interface ApplyReceipt { at: number; ok: boolean; failed: { id: string; holds: string }[]; summary: string; by?: string }`
  - `export function ReviewApply(props: { rows: ReviewRow[]; layout: "bar" | "panel"; checks?: { ok: boolean | "warn"; text: string }[]; consequence?: ReactNode; apply(): Promise<ApplyReceipt | V2Outcome<unknown>>; onDiscard(): void; last?: ApplyReceipt | null; onUndoLast?(): Promise<void>; timeZone: string }): JSX.Element`
  - `export function receiptFrom(outcome: V2Outcome<unknown>, rows: ReviewRow[], now: number): ApplyReceipt`
  - `export function offerUndo(opts: { message: string; undo: () => Promise<void> }): void`, which is sonner `toast(message, { duration: 10_000, action: { label: "Undo", onClick } })`
  - `export function clock(ms: number, tz: string, h12 = false): string` ("14:02")
  - `export function dayKey(ms: number, tz: string): string` ("2026-10-22")
  - `export function startOfDay(ms: number, tz: string): number`
  - `export function lightsWindow(dayStartMs: number, onHHMM: string, offHHMM: string, tz: string): { on: number; off: number }`, which is DST-safe and wraps past midnight

**Copy:**
- Header: *"{n} changes · Review & apply"* (bar) or *"Review & apply"* + *"{n} unsaved changes, not active until applied"* (panel).
- Buttons: **Apply {n} changes**, **Discard edits**, a per-row **Undo**.
- In flight: the row says *Sending…* with a dashed underline.
- Success: the receipt *"Written and read back HH:MM"*, the summary line, then *"Controller confirmed every value · by {name}"* and the button **Undo: write back the previous values**.
- Failure, per row: *"Controller still holds {holds}. Nothing else was changed."* + **Try again**.
- `stale_revision`: *"Someone else changed this at HH:MM. Reload their version and reapply your edits."* + **Reload**.
- `forbidden`: *"Only a Home Assistant administrator can change this."*
- `guard_refused`: *"The controller refused: {message}"*.
- Missing: `NeedsIntegration` compact.

- [ ] **Step 1: Write the failing tests**
  - `receipt says written and read back with zone clock`: `receiptFrom(ok verified at 14:02 Pacific/Auckland)` → `ok:true`, and `renderToStaticMarkup` contains `Written and read back 14:02`.
  - `partial apply keeps failed rows in the draft`: the outcome is ok with `readback.status:"unverified"` and failed `[{id:"rewater",holds:"57%"}]` → the markup contains `Controller still holds 57%. Nothing else was changed.` and `Try again`, and there is no "Written and read back".
  - `stale_revision keeps draft and offers reload` → `Reload`.
  - `forbidden error shows admin copy`.
  - `Apply button names the count`: 2 rows → `Apply 2 changes`; 1 row → `Apply 1 change` and the header `1 change · Review & apply` (singular).
  - `time`: `clock(Date.UTC(2026,9,22,1,2), "Pacific/Auckland")` → `"14:02"`. `lightsWindow` across the NZ DST change on 2026-09-27 has a duration of exactly 12 h.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
  - `bar` is a sticky footer card (I2, T2).
  - `panel` is a right-column card (E6).
  - Phone: `bar` becomes a bottom `<dialog>` opened from a "Review {n} changes" button.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit as `feat(frontend): review & apply with read-back, undo toast, zoned time`.

### Task 6: Visual primitives

**Files:**
- Create: `frontend/src/components/primitives/{arc-gauge,ring,capacity-bar,step-rail,hold-button}.tsx` + `primitives.css`
- Test: `frontend/src/lib/primitives.test.ts`

Reuse what exists: `Gauge`, `MiniGauge`, `ZoneSlab`, `FeedTankDrawing`, `StockBottle`, `Sparkline` and `Meter`. Do not duplicate them.

**Interfaces:**
- Produces:
  - `ArcGauge({ value, min, max, band: [number, number], tone: "ok" | "warn" | "bad", label: string, unit?: string })`, an SVG semicircle with a shaded band and needle, `role="img"`, `aria-label` = label + value. Used in H2 and T5 room tablet.
  - `HealthRing({ pct, label })`, a conic ring with the number inside. Used in T3.
  - `StabilityRing({ value: string, caption: string, state: "settling" | "steady" | "offline", progress: number })`. It animates only under `prefers-reduced-motion: no-preference`, and the reading is `aria-live="polite"`, throttled to one announcement per 5 s. Used in E4 and P5.
  - `CapacityBar({ segments: { id: string; label: string; lph: number; tone: string }[]; capacityLph: number; caption: string })`. Overflow is hatched with ▲, never colour alone, and `role="img"` with `aria-label={caption}`. Used in E6 and I3.
  - `StepRail({ steps: { title: string; detail: string }[]; current: number; compact?: boolean })`. `compact` is the phone segmented bar. Focus moves to the step heading on change. Used in E3 and E4.
  - `HoldButton({ label: string; srLabel: string; maxSeconds: number; disabledReason?: string; onStart(): void; onStop(): void })`. It uses Pointer Events with `setPointerCapture`, stops on `pointerup` / `pointercancel` / `visibilitychange` (hidden), holds Space on keyboard, has a 64 px minimum height on phone and a countdown ring, and calls `navigator.vibrate?.(30)`.

- [ ] **Step 1: Write the failing tests**
  - `CapacityBar marks overflow with hatch and triangle`: segments totalling 1062 against 900 → the markup has `data-over` and `▲`.
  - `ArcGauge puts needle angle proportional to value`: value 62 in 40..160 → `data-angle="33"` (degrees from left, rounded to an int for the attribute only).
  - `HoldButton disabled shows reason`.
  - `hold releases on visibility hidden`: dispatch the handlers directly (export `holdController(onStart,onStop,max)` from `hold-button.tsx` for the logic test) → `onStop` called once.
  - `HoldButton stops at maxSeconds`: fake timers at 30 s → `onStop`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit as `feat(frontend): arc gauge, rings, capacity bar, step rail, hold button`.

### Task 7: ShotTimeline and the room tree upgrade

**Files:**
- Create: `frontend/src/lib/shot-timeline.ts`, `frontend/src/components/shot-timeline.tsx`, `frontend/src/components/shot-timeline.css`
- Modify: `frontend/src/components/room-tree.tsx` (phase badge, flags, pick mode), `frontend/src/lib/facility.ts`
- Test: `frontend/src/lib/shot-timeline.test.ts`, `frontend/src/lib/room-tree.test.ts`

**Interfaces:**
- Consumes: `TimelineGetData` (Task 3), `clock` / `lightsWindow` (Task 5)
- Produces:
  - `export type BlockGlyph = "done" | "planned" | "expected" | "failed" | "warning" | "queued"`
  - `export interface TimelineBlock { id: string; glyph: BlockGlyph; start: number; end: number; requestedStart?: number; litresPerPlant: number | null; source: string; code: string | null; label: string; zone: number; roomId: string }`
  - `export interface TimelineRow { key: string; roomId: string; zone: number | null; label: string; sublabel: string; blocks: TimelineBlock[]; lights: { on: number; off: number }[]; tone?: "warn" | "bad" }`
  - `export function toTimelineRows(data: TimelineGetData, plantsByZone: Record<string, number>, rooms: { id: string; name: string; stage: string; day: number | null }[]): TimelineRow[]`, which maps schema `kind`/`status` → glyph:
    - `shot+done` → done
    - `planned` → planned, or `expected` when `source==="engine"`
    - `held` or `status:error` → failed
    - `status:warning` → warning
    - `queued` → queued
  - `export function place(block: TimelineBlock, span: { start: number; end: number }): { offsetPct: number; sizePct: number }`
  - `export function ShotTimeline(props: { rows: TimelineRow[]; span: { start: number; end: number }; now: number; mode: "full" | "preview" | "strip"; orientation?: "horizontal" | "vertical"; timeZone: string; onBlock?(b: TimelineBlock, anchor: HTMLElement): void; focusIds?: string[]; collapsedRooms?: Set<string>; onToggleRoom?(roomId: string): void }): JSX.Element`
  - `RoomTree` props add `pick?: { title: string; selected: Set<string>; onChange(next: Set<string>): void; onDone(): void; onCancel(): void } | null`. In pick mode, checkboxes replace links, **Done** and **Cancel** sit at the foot, and the page sets `inert` on `<main>`.
  - Each zone row shows a phase badge (`P0`–`P3`, or `T` for timer mode from `select.*_irrigation_mode`) and VWC. Each room row shows its state word (Watering, Holding, Timers, Feed held), plus a `warn` flag when the room has an open alert.

**ShotTimeline rendering:**
- A CSS grid. The label column and the time track use `subgrid` (with a fixed 180 px label width fallback).
- Blocks are `<button>`s with a sentence label, e.g. *"F2 zone 3, 10:40, 2.4 litres, done."*
- Roving tabindex: ←/→ move between blocks, ↑/↓ move between rows, and Home jumps to the block nearest now.
- Lights-on is a background band, and the now line is labelled "Now HH:MM".
- Height ∝ litres per plant (the legend reads "Bar height = water per plant").
- `strip` mode shows only rows and the axis (S2).
- Under 480 px, container queries shorten labels to the zone number.
- `orientation="vertical"` (P2):
  - time runs down;
  - rooms become columns with zone sub-columns;
  - the track has `overflow-x: auto` and `scroll-snap-type: x mandatory`;
  - blocks get width ∝ water;
  - the label is "Width = water".

- [ ] **Step 1: Write the failing tests**
  - `maps held to failed and engine planned to expected`.
  - `place clamps blocks crossing the span edge` (start before the span → `offsetPct` 0, `sizePct` trimmed).
  - `queued block keeps requestedStart for the connector`.
  - `block buttons carry the spoken sentence` (render → `aria-label="F2 zone 3, 10:40, 2.4 litres, done."`).
  - `vertical orientation labels width as water`.
  - `room tree pick mode renders checkboxes and Done`.
  - `timer-mode zone shows T badge`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. Build, then run `node scripts/verify-navigation.mjs` → still passes (tree markup changed).
- [ ] **Step 5:** Commit as `feat(frontend): shared ShotTimeline; room tree phase badges, flags and pick mode`.

---

### Task 8: S1 All rooms (+ P1)

**Files:**
- Modify: `frontend/src/pages/all-zones.tsx`, `frontend/src/pages/all-zones.css`, `frontend/src/lib/facility-view.ts:109-147`
- Create: `frontend/scripts/verify-parity-s1.mjs`
- Test: `frontend/src/lib/all-zones.test.ts`

**Interfaces:**
- Consumes: `facilityView`, `ZoneSlab`, `FeedTankDrawing`, `StockBottle`, `NeedsIntegration`
- Produces: `FacilityZone` adds `queued: { position: number } | null`, `flowRatio: number | null`, `lastShotHollow: boolean`. `FacilityRoom` adds `growDay: { day: number; of: number; daysLeft: number; stage: string } | null`, read from `sensor.crop_steering_<px>grow_day`, `_days_to_harvest` and `_stage`, falling back to today's client computation.

**Delta to mockup 02:**
- Room header: *"Day 38 of 63 · 25 days left"*, the plan progress bar, *"Drunk today 0.21 L per plant · 24.8 L room"*, then Air/RH/VPD as readings.
- Zone card status chip: *"Watering now"*, *"Automated"* or *"Paused"* (hatched card).
- A queued shot shows *"Waiting for the pump — 2nd in line"* with an hourglass.
- Under 80 % flow, the card shows *"Last shot: 1.9 of 2.4 L arrived (79%)"* and the hollow dot.
- The problem shows in place on the card (*"Pore EC 6.6 is over the 4.5–6.0 band"*).
- The right column has FEED TANK (with *"pH 5.84 · EC 2.4 · 19.8°"*) and STOCK bottles. The feed pH value carries the calibration-due flag.
- P1 at 390 px: zone tiles 3-up and a one-line feed row (*"Feed 68% · 310 L · pH 5.84 · EC 2.4"* + *"Part B low"*).

- [ ] **Step 1: Write the failing tests**
  - `grow day prefers the room entities`.
  - `falls back to computed day when grow entities absent`.
  - `queued zone gets position from binary_sensor shot_queued attrs`.
  - `flow ratio under 0.8 marks last shot hollow`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement the facility-view additions and the card markup.
- [ ] **Step 4:** Run tsc and vitest → PASS. Write `verify-parity-s1.mjs`: `runParity({id:"s1", route:"/all-zones", mockup:"02-S1-AllRooms.png", phoneMockup:"24-P1-AllRooms.png"})`. It asserts:
  - the room headings exist;
  - each zone card links to `#/zone/N`;
  - the problem text sits inside its zone card (locator chain);
  - nothing renders "Needs integration" on 3.17 (S1 uses entities only; missing entities hide their lines).

  Build and run it → exit 0. Compare against the mockup.
- [ ] **Step 5:** Commit as `feat(frontend): all rooms shows queue, flow and grow-day in place`.

### Task 9: S2 Room

**Files:**
- Modify: `frontend/src/pages/today.tsx`, `frontend/src/pages/today.css`
- Create: `frontend/scripts/verify-parity-s2.mjs`
- Test: `frontend/src/lib/today-room.test.ts`

**Interfaces:**
- Consumes: `ShotTimeline mode="strip"`, `useParity(…,"timeline_get",{rooms:[roomId],start,end})`, `toTimelineRows`, `zoneSensors` (`facility-view.ts:17`)
- Produces: `export function roomZoneRows(controller: Controller, now: number): { zone: number; drink: { ml: number; median: number }; gauges: GaugeModel[]; sensors: ZoneSensor[]; paused: { by: string; at: number; why: string } | null }[]`, in `lib/today-room.ts`

**Delta to mockup 03:**
- Header: *"F1 Holding · Flower stretch · 120 plants in 3 zones"* and *"Day 12 of 63 · 51 days left · harvest 11 Dec"*, the bar with a *"Stretch ends day 21"* marker, *"Water today 12.7 L room · 0.16 L per watered plant"*, and *"Lights On 10:00 – 22:00"*.
- Today strip: legend *Shot done · Planned · Lights on*, plus **Open full timeline →** (`#/plan/watering`).
- On 3.17 the strip area shows `NeedsIntegration compact feature="Today's watering strip"`.
- Zone rows:
  - slab drawing;
  - VWC / Overnight dryback / Pore EC gauges with *"target …"*;
  - *"Water per plant vs room median"* and *"+1 mL vs median 160 mL"*;
  - a Sensors column with a silent-sensor card (*"Last heard 11:08. Left out: the zone reads the front sensor only."* + **Check back probe →** to `#/equipment/probes`);
  - for a paused zone, *"Paused by Ben at 09:52 (slab change)."* + **Resume zone 3**, which writes the zone switch with an Undo toast.
- Remove the existing HMI table/cards duplicate and the "AI assistant changes today" block (these now live in Changes; the header AI chip stays).

- [ ] **Step 1: Write the failing tests**
  - `paused zone row names who and when`, from the switch's `last_changed` + `context.user_id` → name.
  - `drink delta against median is signed`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests → PASS. `verify-parity-s2.mjs` (route `/today`, mockup 03) asserts:
  - the strip has 3 rows;
  - **Resume zone 3** gives a toast with **Undo**, and clicking Undo returns the zone to Paused;
  - on 3.17 the "Needs integration 3.18" note is inside the strip region.

  Then compare against the mockup.
- [ ] **Step 5:** Commit as `feat(frontend): room page with today strip and sensors in place`.

### Task 10: S3 Zone (+ P3)

**Files:**
- Modify: `frontend/src/pages/zone.tsx`, `frontend/src/pages/zone.css`, `frontend/src/components/day-timeline.tsx` (compare-series prop only)
- Create: `frontend/src/lib/zone-shot-log.ts`, `frontend/scripts/verify-parity-s3.mjs`
- Test: `frontend/src/lib/zone-shot-log.test.ts`

**Interfaces:**
- Consumes: `useCsEvents` (`shot.completed` for this zone), `callV2("journal_query")`, the existing `ZoneDay`, `OverlayRows`, `brain_ask`
- Produces:
  - `export function shotLog(events: CsEvent[], zone: number, dayStart: number): { at: number; phase: string; ml: number; seconds: number; vwcBefore: number | null; vwcAfter: number | null }[]`
  - `ZoneDay` prop `compare?: "off" | "yesterday" | "last-run"`

**Delta to mockup 04:**
- Header: *"F2 / Zone 2"*, the phase chip, *"Automated"*, and *"Day 38 of 63 · 40 plants · 1 sensor · 7.9 L today (198 mL per plant)"*.
- VWC chart: phase-shaded bands, shot dots, the expected dashed line, *"shot below 58%"*, and the *"Compare with Off · Yesterday · Last run, day 38"* segmented control.
- Pore EC chart with its target band.
- When an AI overlay proposal exists, show the suggestion card in place under the EC chart: *"AI assistant suggests: Dilute next 2 shots (EC 1.6)…"* with **Apply** (runs `overlay_keep` → Undo toast) and **Dismiss**.
- Right column: the slab drawing with its caption, gauges, *WHY / NEXT ACTION* (existing `zone-why`), and *SHOT LOG · TODAY* with **History →**.
- The shot log uses `journal_query`. On 3.17 it falls back to the existing `shot_log_app` attribute.
- P3 at 390 px: charts in a horizontal snap scroller with dots ("Swipe: VWC · Pore EC").

- [ ] **Step 1: Write the failing tests**
  - `shot log keeps only this zone's completed shots since lights-on, newest first`.
  - `shot log converts litres to mL per plant using plants`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-s3.mjs` (route `/zone/2`, mockups 04 and 26) asserts:
  - Compare "Yesterday" adds a second series (`[data-series="yesterday"]`);
  - suggestion **Apply** shows an Undo toast;
  - the shot log has ≥ 1 row on both backends.

  Then compare against the mockups.
- [ ] **Step 5:** Commit as `feat(frontend): zone page compare, in-place AI suggestion, shot log`.

### Task 11: I1 Watering timeline (+ P2)

**Files:**
- Create: `frontend/src/pages/watering.tsx`, `frontend/src/pages/watering.css`, `frontend/src/lib/parity-demo/watering.ts`, `frontend/scripts/verify-parity-i1.mjs`
- Modify: `frontend/src/App.tsx` (replace the placeholder only)
- Test: `frontend/src/lib/watering.test.ts`

**Interfaces:**
- Consumes: `ShotTimeline`, `toTimelineRows`, `useParity("timeline_get")`, `callV2("timer_skip")`, `offerUndo`, `RoomTree` selection (the controller room)
- Produces: `export function wateringQuery(hash: string): { date: string; span: 12 | 24 | 48; stages: string[]; problemsOnly: boolean; q: string }` and `export function wateringHash(q): string` (URL state: `#/plan/watering?date=2026-10-22&span=24&stages=flower,veg&problems=1&q=z3`)

**Layout to mockup 05:**
- Date strip of 7 day chips with *"Done"*, *"1 problem"*, *"3 problems"* or *"Planned"*, plus ‹ › and **Today**.
- Segmented control **12 h · 24 h · 48 h**.
- Chips: *Flower rooms*, *Veg room*, *Problems only*.
- Legend: *Done · Planned · Failed · Warning · Waiting for pump · Lights on · Bar height = water per plant*.
- Rows grouped by room with a disclosure, *"Lights on 06:00–18:00"* bands, and zone sublabels *"Steering · P2"* / *"Paused"*.
- Selecting a room in the room tree scrolls to its row and expands it.
- Block popover (Radix popover; anchor positioning where supported):
  - room/zone/day, then the time range;
  - a status pill, e.g. *"Planned · waited 12 min for pump"*;
  - the reason box;
  - rows *Water / VWC / Source*;
  - **Open F2 Zone 3**, plus **Skip this shot** on future timer blocks (calls `timer_skip` → Undo toast; on 3.17 the button is replaced with compact `NeedsIntegration`), plus **See what happened** on failed blocks (`#/history/explorer` at that minute).
- Failed blocks: a toolbar chip *"{n} shots failed ›"* cycles focus through them, and red ticks appear on the axis.
- States:
  - Loading: row skeletons.
  - Empty: *"No watering planned for this day."* plus **Set up a timer** (timer zones only).
  - Error: *"Couldn't load the watering plan. Showing what we had at HH:MM."* + **Try again**.
  - Stale: future blocks hatched, *"Live updates paused — reconnecting"*.
  - Missing: full-page body `NeedsIntegration feature="The watering timeline"`.
- Live: a `useCsEvents` `shot.*` / `intent.*` event for a visible room triggers a 2 s debounced reload.
- P2 at 390 px: vertical orientation; the header becomes *"Timeline"* / *"All rooms · swipe for more"* with **12 h · 24 h**; the date line reads *"Today, Thu 22 Oct"* / *"1 failed · 2 warnings"*.

- [ ] **Step 1: Write the failing tests**
  - `wateringQuery round-trips`.
  - `default span is 24 on desktop and 12 on phone` (pure function `defaultSpan(width)`).
  - `problem count per day counts failed and warning blocks`.
  - `problemsOnly keeps rooms with a failed or warning block`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-i1.mjs` (mockups 05 and 25) asserts:
  - clicking 48 h updates the hash (`span=48`);
  - clicking a planned block opens the popover with "Skip this shot";
  - Skip gives an Undo toast;
  - ←/→ moves focus between blocks;
  - on 3.17 the body shows "Needs integration 3.18" and the tree still works.

  Then compare against the mockups.
- [ ] **Step 5:** Commit as `feat(frontend): irrigation watering timeline`.

### Task 12: I2 Current day

**Files:**
- Modify: `frontend/src/pages/strategy.tsx`, `frontend/src/pages/targets.css`
- Create: `frontend/scripts/verify-parity-i2.mjs`
- Test: `frontend/src/lib/strategy-review.test.ts`

**Interfaces:**
- Consumes: `ReviewApply layout="bar"`, `useDraft("targets:<room>:<zone>")`, the existing `Drafts`, `applyChanges` (`client.ts:393`), `strategy_preview`, `offerUndo`
- Produces: `export function targetRows(drafts: Drafts, states: States, zone: number): ReviewRow[]`, with notes copy from `setting-words.ts`. The I2 example: *"-1.0 pts · P2 waters when VWC falls to this"*.

**Delta to mockup 06:**
- Header: *"F2 · Zone 1 [P2] Today's targets · Thu 22 Oct · flower day 38 of 63 · lights 06:00–18:00"*, and on the right *"Nothing is sent to the controller until you apply"*.
- The existing PlanningCurve handles show *"was 57% · not applied"*.
- Steering card with 5 presets (existing).
- *"This afternoon, 14:10–18:00"*: *Saved* vs *With edits* shot glyphs + litres per plant, plus the consequence sentence from `strategy_preview`.
- Bottom `ReviewApply` bar with **Discard edits** / **Apply {n} changes**, and a *LAST APPLIED* receipt with **Undo: write back the previous values**.
- `ReviewDialog` is no longer used on this page; other users of `ReviewDialog` stay unchanged.

- [ ] **Step 1: Write the failing tests**
  - `targetRows lists only changed keys with signed delta note`.
  - `undo of last apply restores before values`: a spy `applyChanges` receives the previous values.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-i2.mjs` (route `/plan/targets?zone=1`, mockup 06): drag/arrow the re-water handle, then:
  - the bar shows "1 change · Review & apply";
  - **Apply 1 change** gives a receipt matching `/Written and read back \d\d:\d\d/`;
  - **Undo: write back the previous values** restores the value.

  Then run the existing `node scripts/verify-irrigation-workspace.mjs` and `verify-steering-visuals.mjs` → still pass.
- [ ] **Step 5:** Commit as `feat(frontend): current day review & apply bar with read-back receipt`.

### Task 13: I3 Timer programs

**Files:**
- Create: `frontend/src/pages/timers.tsx`, `frontend/src/pages/timers.css`, `frontend/src/lib/timers.ts`, `frontend/src/lib/parity-demo/timers.ts`, `frontend/scripts/verify-parity-i3.mjs`
- Test: `frontend/src/lib/timers.test.ts`

**Interfaces:**
- Consumes:
  - `ShotTimeline mode="preview"`, `CapacityBar`, `ReviewApply`, `offerUndo`;
  - `callV2("timer_program_list" | "timer_program_set" | "timer_program_delete")`;
  - `select.crop_steering_<px>zone_N_irrigation_mode` through `controller.write`.
- Produces:
  - `export type TimerKind = "every" | "once" | "spread"`, labelled One-off = once, Recycle = every, Simple = spread.
  - `export function timerSentence(p: TimerProgram, zoneNames: Record<string, string>): string` (exact shapes below).
  - `export function validateTimer(p: TimerProgram): { field: string; message: string }[]`
  - `export function localPreview(p: TimerProgram, from: number, tz: string, lights: { on: number; off: number }): TimelineBlock[]` (used only when the server preview is missing)
  - `export function consequence(blocks: TimelineBlock[], dailyMaxMin: number): string`

**Sentence shapes** (from spec G7 and mockup 07):
- *"Every 30 min for 2 min, 08:00–12:00, Veg zones 1–2"*
- *"6 times a day for 90 s, while lights are on, Veg zone 2 (clones)"*
- *"Once at 20:00 for 3 min, Fri 23 Oct, Veg zone 1 (mothers)"*

**Layout to mockup 07:**
- Left:
  - *Programs* "for zones without probes", **New program**, and cards showing the sentence + *"On · next shot tomorrow 08:00"* / *"Draft · not running"*.
  - *Irrigation mode* "who waters each zone": a Steering/Timer/Off segmented control per zone. Steering is disabled with *"No probe, so steering is not offered."*
- Right editor:
  - *"PROGRAM 1 · RUNNING"* + the sentence;
  - Type (One-off · Recycle · Simple + explanation);
  - Zones ("Only zones set to Timer are listed");
  - Amount steppers *Run for / Every / From / To*;
  - When (All day · Lights on · Lights off · Custom);
  - *Next 24 hours* preview with *"16 shots · 32 min of watering · first tomorrow 08:00"* and *"Same strip as Irrigation › Timeline"*;
  - cards *DAILY MAX PER ZONE* / *PUMP CAPACITY* / *SAME SAFETY AS STEERING* (✓ Stop all / room stop, ✓ Source-water pH/EC check, ✓ Feed tank level guard);
  - footer **Delete program** (immediate + Undo toast, never a confirm), **Discard edits**, and **Save** / **Saved**.
- Validation as you type: *"End must be after start"* beside the field, and the preview blanks.
- Empty: *"No timer yet. Most mother rooms use 2 min every 2 h during lights-on."* + **Use that**.
- On 3.17: the irrigation-mode select may be absent → the whole page is `NeedsIntegration feature="Timer programs"`.

- [ ] **Step 1: Write the failing tests**
  - `timerSentence every/once/spread match the three exact strings`.
  - `validateTimer rejects end before start with "End must be after start"`.
  - `localPreview every 30 min for 2 min 08:00–12:00 gives 8 blocks`.
  - `consequence names the daily-limit stop`: *"8 shots · 16 min · about 1.9 L per plant. Stops after shot 6: daily limit 1.5 L per plant."*
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-i3.mjs` (mockup 07):
  - change *Every* to 45 → the preview count changes and the editor shows the unsaved dot;
  - **Save** goes through ReviewApply → *Saved*;
  - **Delete program** gives an Undo toast, and Undo restores the card;
  - on 3.17, "Needs integration 3.18".

  Then compare against the mockup.
- [ ] **Step 5:** Commit as `feat(frontend): timer programs with live preview`.

### Task 14: I4 Grow plan & presets

**Files:**
- Modify: `frontend/src/pages/grow-planner.tsx`, `frontend/src/pages/grow-planner.css`
- Create: `frontend/src/components/presets-panel.tsx`, `frontend/src/lib/parity-demo/presets.ts`, `frontend/scripts/verify-parity-i4.mjs`
- Test: `frontend/src/lib/presets.test.ts`

**Interfaces:**
- Consumes: `callV2("preset_list" | "preset_save" | "preset_apply" | "copy_config")`, `RoomTree pick`, `ReviewApply`, the existing `recipe-library` (localStorage)
- Produces:
  - `export function PresetsPanel(props: { controller: Controller; roomId: string; planName: string }): JSX.Element`
  - `export async function importBrowserPresets(controller, recipes: RecipeLibraryItem[]): Promise<number>`, a one-time `preset_save` per browser recipe on first load, recorded in localStorage `crop-steering.presets-imported`.

**Delta to mockup 08:**
- Header pill *"Armed · running"*, plus a draft box *"Draft · 2 edits, not live yet"* with **Discard draft** / **Arm at lights-on, Fri 06:00** (existing arm flow, renamed copy).
- Exception diamonds and the *COMING UP* day card are existing; add the *"EXCEPTION · IN DRAFT"* dashed card and **Add exception on day 40**.
- Presets panel:
  - *"Stored on the controller: the same list on every phone and PC"*;
  - cards with *"Running in F2 · 4 stages · 3 exceptions"* / *"Not in use · …"*;
  - **Save F2 plan as a new preset**;
  - *Copy "<name>" to room…* with room buttons (room-tree pick mode on desktop, a bottom sheet on phone);
  - the diff list from `copy_config {preview:true}` (strikethrough old → new);
  - **Copy {n} changes to F1 as a draft**.
- On 3.17: the panel shows `NeedsIntegration` and the existing browser recipe library stays available below it.

- [ ] **Step 1: Write the failing tests**
  - `importBrowserPresets saves each recipe once and marks imported`.
  - `copy diff rows render old struck and new`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-i4.mjs` (route `/plan/schedule`, mockup 08):
  - pick F1 → a diff with ≥ 1 row;
  - **Copy … as a draft** gives a receipt.

  Then run `node scripts/verify-recipe-library.mjs` → passes (update its route to `#/plan/schedule` if it still uses `#/grow-plan`, the legacy redirect).
- [ ] **Step 5:** Commit as `feat(frontend): controller-stored presets and copy-to-room preview`.

### Task 15: H1 Explorer

**Files:**
- Rename: `frontend/src/pages/timeline.tsx` → `frontend/src/pages/explorer.tsx` (+ css)
- Modify: `frontend/src/components/history-explorer.tsx`, `frontend/src/lib/history-explorer.ts`
- Create: `frontend/scripts/verify-parity-h1.mjs`
- Test: `frontend/src/lib/history-explorer.test.ts` (extend)

**Interfaces:**
- Consumes: `useCsEvents` / `journal_query` (`phase.changed`, `shot.completed`, `alert.raised`, `stock.refilled`), `runs_get`, `timelineCsv`
- Produces:
  - `export function phaseLane(events: CsEvent[], span, projection?: unknown): { from: number; to: number; phase: string; planned: boolean }[]`
  - `export function chartNotes(events: CsEvent[], series: string[]): { at: number; series: string; text: string }[]`, giving e.g. *"Zone 2 over the band since 09:40"* and *"Refilled 06:10 · 40% to 74%"*.

**Delta to mockup 09:**
- Range: *Today · 7 d · This run · Custom*, plus *"Thu 22 Oct, 00:00 to now"*.
- Series chips per zone (VWC / Pore EC / Root temp), Feed (pH / EC), Tank (Level).
- PHASE lane (planned segments faded), SHOTS lane, and stacked charts with a target band and the in-place note.
- A shared crosshair (*"Move across the charts to read every line at that moment"*) with a time pill.
- Future time is hatched.
- Header toggle *"Compare with last run (Run 14, same day 38)"* and **Export CSV · {n} series**.
- The setpoint-log section is removed, because it lives in Changes. DayLanes, the event log, OnThisDay and AskWhy stay below the charts.
- On 3.17: the phase and shots lanes come from the existing `phase` entity history and shot_log; notes are hidden.

- [ ] **Step 1: Write the failing tests**
  - `phaseLane splits on phase.changed and marks future planned`.
  - `chartNotes reports band excursion start once`.
  - `csv header counts selected series`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-h1.mjs` (route `/history/explorer`, mockup 09):
  - toggling the Zone 3 VWC chip removes its line;
  - the Export button text matches `/Export CSV · \d+ series/`;
  - the old `#/history/timeline` lands here.

  Then `verify-dashboard.mjs` timeline selectors → still pass (update their route).
- [ ] **Step 5:** Commit as `feat(frontend): history explorer with phase and shot lanes`.

### Task 16: H2 Water & flow

**Files:**
- Modify: `frontend/src/pages/water-use.tsx`, `frontend/src/components/water-use.tsx` (kept as the Estimated series)
- Create: `frontend/src/lib/flow-check.ts`, `frontend/src/pages/water-use.css`, `frontend/scripts/verify-parity-h2.mjs`
- Test: `frontend/src/lib/flow-check.test.ts`

**Interfaces:**
- Consumes: `ArcGauge`, `journal_query` (`shot.completed` with `commanded_l` / `metered_l`, `flow.reconciled`), `sensor.crop_steering_<px>zone_N_flow_ratio`, `test_shot` (existing)
- Produces:
  - `export function zoneFlow(events: CsEvent[], zone: number): { last3Pct: number | null; todayPct: number | null; shots: { at: number; askedL: number; meteredL: number | null }[]; verdict: "on_target" | "blocked" | "over" | "no_meter" }`. The verdict is `blocked` if `last3Pct < 80`, and `over` if `> 120`.
  - `export function leakCheck(events: CsEvent[], dayStart: number): { watchedMs: number; leakedL: number; incidents: { at: number; litres: number; minutes: number; note: string }[] }`

**Layout to mockup 10:**
- Header: *"Did the water reach the plants?"*, plus the meter line *"F2 main-line meter · 450 pulses per litre · last pulse 14:00"*.
- Per-zone card:
  - an arc gauge 40–160 %;
  - *"98% metered vs asked, last 3 shots"* / *"Today 98% · 8.3 of 8.5 L"*;
  - asked vs metered bars per shot;
  - a 7-day line (*steady* / *fell today*);
  - a status chip (*On target* / *Blocked line?*);
  - the blocked card with **Run 30 s test shot on Zone 2** (hold-to-run `HoldButton`) and **Open catch test** (`#/equipment/setup?step=catch`).
- *Leak check*: valve-open vs meter-flow lanes, *"0.00 L in 14 h 05 min watched"*, and a 7-day dots row with the incident sentence.
- *Water per plant*: bars against the room median with the in-place explanation.
- No meter: *"Add a flow meter to prove water reached the plants."* + **Map a flow meter** (`#/equipment/setup`).
- On 3.17: the page shows the existing WaterUsePanel (the estimate) with `NeedsIntegration feature="Metered flow check"` above it.

- [ ] **Step 1: Write the failing tests**
  - `zoneFlow last three shots 62% → blocked`.
  - `zoneFlow without metered_l → no_meter`.
  - `leakCheck counts meter rise with no valve open`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-h2.mjs` (mockup 10):
  - the blocked card sits inside the Zone 2 card;
  - the gauge has an `aria-label` containing "62%";
  - on 3.17, "Needs integration 3.18" plus the estimate chart.

  Then run `node scripts/verify-workspace.mjs` water assertions → still pass.
- [ ] **Step 5:** Commit as `feat(frontend): water & flow check, metered vs asked`.

### Task 17: H3 Compare runs

**Files:**
- Modify: `frontend/src/pages/comparison.tsx`, `frontend/src/pages/comparison-views.tsx`, `frontend/src/pages/comparison-week-charts.tsx`
- Create: `frontend/scripts/verify-parity-h3.mjs`
- Test: `frontend/src/lib/comparison.test.ts` (extend)

**Interfaces:**
- Consumes: existing comparison data (`runs_get`, `dailyRanges`, `grow_days_get`), `runs_set_harvest`
- Produces: `export function runCallout(metric: "vwc" | "dryback" | "pore_ec" | "water", runs: ComparedRun[], stages: Stage[]): { text: string; box: { fromDay: number; toDay: number } } | null` (pure; picks the largest sustained stage difference)

**Delta to mockup 11:**
- Run cards with checkboxes:
  - *"Run 15 · this run · flipped 15 Sep · Growing · harvest due Mon 16 Nov (day 63)"*;
  - *"Harvested 10 Aug · 41.2 kg dry · 515 g/m²"*;
  - **Add harvest result**, an inline form (existing harvest entry);
  - a link *"Manage runs ›"* (`#/history/grows`).
- *"Line runs up by"* select: Day of flower, Day of run.
- Four small multiples (VWC daily mean, Overnight dryback, Pore EC daily mean, Water per plant), each with a plan-target band, a stage axis, a today line, and one callout box + sentence, e.g. *"Run 13 sat 1.7 pts wetter than this run all through stretch."*
- On 3.17 everything works (v1 services).

- [ ] **Step 1: Write the failing tests**
  - `runCallout names the run, metric delta to source precision and stage`.
  - `runCallout returns null when runs differ by less than noise` (≤ 0.3 pts).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-h3.mjs` (mockup 11):
  - unticking Run 13 removes its lines and the callouts that mention it;
  - **Add harvest result** opens the inline form.

  Then `verify-steering-visuals.mjs` comparison checks → pass.
- [ ] **Step 5:** Commit as `feat(frontend): compare runs callouts and harvest cards`.

### Task 18: H4 Changes (+ setting clock popover)

**Files:**
- Create: `frontend/src/pages/changes.tsx`, `frontend/src/pages/changes.css`, `frontend/src/lib/changes.ts`, `frontend/src/components/setting-history.tsx`, `frontend/src/lib/parity-demo/changes.ts`, `frontend/scripts/verify-parity-h4.mjs`
- Modify: `frontend/src/components/setting-row.tsx` (clock button only)
- Test: `frontend/src/lib/changes.test.ts`

**Interfaces:**
- Consumes: `callV2("history_changes")` per room (merged), `setpoint_log_get` (3.17 fallback via `lib/setpoint-log.ts`), `ReviewApply`, `applyChanges`, `history_revert` (when present)
- Produces:
  - `export type ChangeKind = "setpoint" | "plan" | "recipe" | "setup" | "calibration" | "alerts"`
  - `export interface ChangeEntry { id: string; at: number; actor: "you" | "learner" | "ai" | "timer" | "mcp" | "aigrow" | "setup" | "safety"; roomId: string; scope: string; label: string; before: string; after: string; reason: string | null; outcome: { text: string; good: boolean | null } | null; revertLabel: string; revert: ReviewRow[] | null }`
  - `export function toEntries(changes: HistoryChange[], rooms, me: string | null): ChangeEntry[]`
  - `export function fromSetpointLog(rows): ChangeEntry[]`
  - `export function SettingHistory(props: { controller; entityId: string }): JSX.Element` (popover: last 5 changes + **See all changes**)

**Layout to mockup 12:**
- Chips: *Made by* (You · Learner · AI judge · Timer · MCP · AiGrow, with counts) and *Kind* (Setpoint · Plan · Recipe · Setup · Calibration, with counts); *"9 of 9 changes · last 7 days"*.
- Scope line *"Showing all rooms. Pick a room or zone in the room list to narrow it."*; the room tree narrows it.
- Day groups *"TODAY · THU 22 OCT"*. Each entry is an `<ol>` item with `<time datetime>`: time, actor pill, scope, bold label, ~~old~~ → new, the reason, the outcome line with ↗, and a revert button with specific copy: *"Revert to 4.0%"*, *"Put back in reading"*, *"Restore previous calibration"*.
- Plan-step entries show *"Plan step. Edit the plan to change it."* instead of a button.
- *SELECTED CHANGE* panel:
  - actor and time, title, scope;
  - a was/now slider with the limit (*"learner may move ±15 min"*);
  - *WHY*;
  - *WHAT HAPPENED NEXT* bars;
  - *"Written and read back 08:40:02"*;
  - **Revert to 50 min** (runs ReviewApply, then an Undo toast).
- URL: `#/history/changes?since=…&id=…`.
- Load more: an IntersectionObserver fetches the next 7 days.
- Empty: *"No changes in this period."*
- On 3.17: built from `setpoint_log_get` (setpoints only). The Kind chips other than Setpoint are disabled with compact `NeedsIntegration`.

- [ ] **Step 1: Write the failing tests**
  - `toEntries maps actor and builds Revert to <old> label with unit`.
  - `plan entries have no revert`.
  - `fromSetpointLog gives setpoint entries with you/learner actors`.
  - `entries group by zoned day`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-h4.mjs` (mockup 12):
  - the *Learner* chip filters to 2 entries;
  - selecting an entry fills the panel and updates the `id=` hash;
  - **Revert to 4.0%** shows a receipt and then an Undo toast;
  - a setting row's clock button on `#/plan/targets` opens the popover;
  - on 3.17, entries are present and the kind chips are disabled.

  Then compare against the mockup.
- [ ] **Step 5:** Commit as `feat(frontend): history changes feed with revert`.

### Task 19: E1 Probes & offsets

**Files:**
- Modify: `frontend/src/pages/probes.tsx`, `frontend/src/pages/probes.css`, `frontend/src/lib/probes.ts`
- Create: `frontend/src/lib/probe-offset.ts`, `frontend/scripts/verify-parity-e1.mjs`
- Test: `frontend/src/lib/probe-offset.test.ts`

**Interfaces:**
- Consumes: `callV2("probe_offset_set")` (`match_handheld` preview, then apply), `setup_read` (curve, mapping), `Sparkline`
- Produces:
  - `export function offsetPreview(rawPct: number, handheldPct: number, zoneProbes: { id: string; value: number; counted: boolean }[], probeId: string): { offset: number; zoneBefore: number; zoneAfter: number; spreadBefore: number; spreadAfter: number }`
  - `export function curveDisabledReason(probe): string | null`, which returns *"This probe already converts to moisture. A curve only applies to raw readings."*

**Delta to mockup 13:**
- Title *"Probes & offsets"*, *"9 probes · 7 in zone values · raw readings always kept"*.
- A table grouped by room (*"2 of 3 probes healthy"*). Columns: ZONE VALUE (mini gauge + *"1 probe"* / *"spread 5.6 points"* / *"1 of 2 probes used"*), HEALTH pill (OK / Stuck 4 h / Silent 3 h / Out of range + *"left out of zone"*), PROBE (*"ch 1 · TEROS 12"*), LAST 24 H sparkline, VWC, EC · TEMP, OFFSET, and an action:
  - **Match handheld**;
  - *"Only probe here, still used"*;
  - *"Check cable"*;
  - **Check placement →**.
- The inline Match-handheld editor:
  - *"Handheld reading, same spot"* [64.0] %;
  - *"Probe reads 61.0%"*, **+3.0** *"offset, VWC points"*;
  - *"F1 Zone 1 value 63.8% → 65.3% · spread 5.6 → 2.6"* with a before/after bar;
  - *"Grey = now, blue = after. Fusion re-baselines, so no step alert fires."*;
  - **Apply +3.0 offset to Zone 1 Back**, **Cancel**;
  - *"Raw value kept · logged in History › Changes"*.
- *Substrate curve · F1* card: Rockwool · Coco · Custom, the curve chart, and *"Rockwool in use since 02 Sep · written and read back"*.
- *Where to put a probe* (G14) card: an in-place warning for the out-of-range probe, the slab cross-section SVG, and 4 bullet rules.
- The feed-probe calibration region moves to E4. Leave a one-line link: *"Feed pH and EC probes: Calibrate →"*.
- On 3.17: the Offset column shows "—" and Match handheld is replaced by compact `NeedsIntegration`.

- [ ] **Step 1: Write the failing tests**
  - `offsetPreview 61.0 vs 64.0 → +3.0 and zone 63.8→65.3 spread 5.6→2.6` (the mockup fixture).
  - `curveDisabledReason for a VWC-native probe`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-e1.mjs` (mockup 13):
  - **Match handheld** on F1 Z1 Back → type 64 → the preview reads "+3.0" → Apply → receipt;
  - **Check placement →** focuses the placement card;
  - 3.17 note.

  Then update `verify-calibration.mjs` so it opens `#/equipment/feed-calibration` (done in Task 24); here only assert the probes link.
- [ ] **Step 5:** Commit as `feat(frontend): probe offsets with match-handheld preview`.

### Task 20: E2 Feed & dosing

**Files:**
- Modify: `frontend/src/pages/dosing.tsx`, `frontend/src/pages/dosing.css`
- Delete: `frontend/src/pages/reservoir.tsx` (move its tank-minimum guard and `TankStatus` into the diagram)
- Modify: `frontend/src/App.tsx` (drop the Reservoir import only)
- Create: `frontend/scripts/verify-parity-e2.mjs`
- Test: `frontend/src/lib/dosing.test.ts` (extend)

**Interfaces:**
- Consumes: `dosing_get` / `dosing_request` / `dosing_save`, `stock_get`, `StockBottle`, `PeristalticPump`, `FeedTankDrawing`, the existing mix-check result, `useCsEvents` (`batch.step`)
- Produces:
  - `export function protections(doc: DosingDocument, states: States): { label: string; ok: boolean }[]`, labels: *"Read-back on every dose"*, *"Overfill cut 102%"*, *"Minimum 8%"*, *"Mix pump on · 0.42 kW"*, *"Timeout 12 min"*
  - `export function nextBatch(doc, stock, now): { at: number; litres: number; doses: { name: string; ml: number }[]; steps: { name: string; min: number }[]; stockWarning: string | null }`

**Layout to mockup 14:**
- Title *"Feed & dosing · F2"*, *"Batch tank, 4 dosing pumps, 3 zones · protections armed 5 of 5"*.
- Diagram:
  - stock bottles with *"298 mL/min · idle"* → pump glyphs;
  - water-in box (*"RO · EC 0.02 · 16.4 °C · 2.1 bar"*) → fill valve (*"Closed · 13:56"*);
  - the batch tank with %, litres, EC and pH;
  - the feed pump → zone boxes (*"Held · Next shot 14:20 waits for feed"*).
- The Batch card shows per-pump mL and the target line.
- Mix check failure in place, beside the tank: *"Mix check failed 14:06"*, EC and pH gauges with a band, the explanation, **Top up 22 L, re-check**, **Use once anyway** (hold-to-run, because it moves water), and *"Feed EC probe calibrated 9 days ago · calibrate"*.
- *Feed recipes by flower week* with week chips and *This week*.
- *Next batch* with the steps bar and the stock warning, plus **Calibrate a pump** and **Calibrate feed pH/EC** (links to E3 and E4).
- On 3.17 everything works (v1). Zone *Held* uses existing hold reasons.

- [ ] **Step 1: Write the failing tests**
  - `protections counts armed of total`.
  - `nextBatch warns when stock after batch is below low line` (*"Part B after this batch: 4.7 L, 6 batches left"*).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-e2.mjs` (route `/equipment/dosing`, mockup 14):
  - the old `#/equipment/feed` lands here;
  - the mix-check card sits inside the diagram region;
  - the calibrate links go to the wizard routes.

  Then `node scripts/verify-tank-status.mjs` → pass (update its route).
- [ ] **Step 5:** Commit as `feat(frontend): feed & dosing plumbing view with in-place mix check`.

### Task 21: E5 Stock

**Files:**
- Modify: `frontend/src/pages/stock.tsx`, `frontend/src/pages/stock.css`, `frontend/src/components/stock-bottle.tsx` (`scale` to litres capacity)
- Create: `frontend/scripts/verify-parity-e5.mjs`
- Test: `frontend/src/lib/stock.test.ts` (extend)

**Interfaces:**
- Consumes: `stock_get` / `stock_refill`, `offerUndo`, recharts bar chart
- Produces: `export function stockOutlook(tank, usePerBatchL, batchEveryDays): { batches: number; daysLeft: number; belowLow: boolean }` and `export function weeklyUse(history, tz): { week: string; byTank: Record<string, number>; partial: boolean }[]`

**Delta to mockup 17:**
- *"Stock tanks · F2 — Drawn to scale · one batch every 2.5 days at current use"*.
- Bottles with height ∝ capacity and a *low 6 L* dashed line; *"12.9 L of 20 L"*; *"17 batches · 43 days left"*.
- A below-low bottle gets its card tinted with *"Below the low line. Order now: supplier takes about 5 days."*
- **Log refill to 20 L** (immediate + Undo toast; primary-coloured on the low bottle).
- *Used per week* grouped bars (this week faded) with the note.
- *Refills* list and the footer note about how the level is computed.

- [ ] **Step 1: Write the failing tests**
  - `stockOutlook 5.4 L at 0.744 L/batch every 2.5 d → 7 batches, 18 days, belowLow`.
  - `weeklyUse marks current week partial`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-e5.mjs` (mockup 17): **Log refill to 20 L** on Part B → the toast, then Undo → back to 5.4 L.
- [ ] **Step 5:** Commit as `feat(frontend): stock bottles to scale with refill undo`.

### Task 22: E6 Setup: pumps & valves

**Files:**
- Create: `frontend/src/components/supply-editor.tsx`, `frontend/src/components/supply-editor.css`, `frontend/src/lib/supply.ts`, `frontend/src/lib/parity-demo/supply.ts`, `frontend/scripts/verify-parity-e6.mjs`
- Modify: `frontend/src/pages/setup.tsx` (mount `SupplyEditor` first; the rest of Setup stays below and is reachable via `?step=`)
- Test: `frontend/src/lib/supply.test.ts`

**Interfaces:**
- Consumes: `callV2("supply_get" | "supply_save")`, `setup_read` (zones, plants, drippers), `CapacityBar`, `ReviewApply layout="panel"`
- Produces:
  - `export function zoneFlowLph(zone: { plants: number; drippersPerPlant: number; dripperLph: number }): number`
  - `export function pairs(zones: { id: number; lph: number; group: string | null }[], pumpLph: number, maxAtOnce: number): { zones: number[]; pct: number; verdict: "fits" | "queues" | "exclusive" }[]`
  - `export function supplyChecks(doc: SupplyDoc, zones): { ok: boolean | "warn"; text: string }[]`

**Layout to mockup 18:**
- *"Setup: pumps & valves · F2 — 1 feed pump, 3 zone valves"*.
- Pump card:
  - *Max flow* [900] L/h, *"was 1000"*;
  - *Max zones at once* 1 · 2 · 3;
  - *"Worst pair allowed to start together"* capacity bar;
  - *"Zones 1 + 2 together = 118% of pump: will run one after another"*.
- *Zone valves and drippers* table: drippers (*"66 plants × 2"*), dripper flow input, zone flow, share-of-pump bar, and an exclusive group None/A/B.
- *What can run together* rows with pct and verdict.
- The Review & apply panel lists changes and CHECKS (*"Pump max flow 900 L/h is in range"*, *"Every zone fits the pump on its own"*, ⚠ *"Zones 1 + 2 need 118%: shots queue, one after another, about 4 min apart"*, *"Exclusive groups respected by the shot queue"*), with **Apply 2 changes** / **Discard changes**, and the footer note about the *"Shot delayed: pump capacity"* alert.
- Apply is disabled with *"The pump can't feed 6 zones at once. Set Zones at once to 5 or less."* + **Use 5**. The server code `pump_over_capacity` maps to the same copy.
- Empty: *"Add your pump's output to stop zones starving each other."*
- On 3.17: the editor shows `NeedsIntegration feature="Pump capacity and exclusive groups"`, and the existing Setup sections render below as today.

- [ ] **Step 1: Write the failing tests**
  - `zoneFlowLph 66 plants × 2 × 4.0 = 528`.
  - `pairs 528+536 vs 900 → 118% queues`.
  - `exclusive group pair verdict wins over pct`.
  - `supplyChecks warns over-capacity with exact sentence`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-e6.mjs` (mockup 18):
  - set Max flow 900 → the panel shows 1 change;
  - set Zone 3 dripper 4.0 → 2 changes;
  - Apply → receipt;
  - on 3.17, the note plus the existing room-name field still present.

  Then `verify-workspace.mjs` setup checks → pass.
- [ ] **Step 5:** Commit as `feat(frontend): pump capacity and exclusive groups editor`.

### Task 23: E3 Pump prime & calibrate

**Files:**
- Create: `frontend/src/pages/pump-calibration.tsx`, `frontend/src/pages/pump-calibration.css`, `frontend/src/lib/pump-calibration.ts`, `frontend/src/lib/parity-demo/pumps.ts`, `frontend/scripts/verify-parity-e3.mjs`
- Test: `frontend/src/lib/pump-calibration.test.ts`

**Interfaces:**
- Consumes: `StepRail`, `HoldButton`, `PeristalticPump`, `StockBottle`, `dosing_get` (pumps, catalogue, calibration dates), `callV2("pump_prime" | "pump_stop" | "pump_calibrate" | "pump_calibration_commit")`, `ReviewApply`
- Produces:
  - `export function calibrationDue(lastAt: number | null, everyDays: number, now: number): { days: number | null; due: boolean }`
  - `export function measuredRate(ml: number, seconds: number, nominal: number): { mlMin: number; vsNominalPct: number; sentence: string }`, e.g. *"300 mL/min — 7% above the catalogue figure."*
  - `export function wearNote(history: { at: number; mlMin: number }[]): string | null`, e.g. *"Down 12% since March — tubing may be wearing."*

**Steps (mockup 15):** the rail shows 1 *Pick pump* · 2 *Prime* (hold to fill the line) · 3 *30 s run* (into a cup) · 4 *Enter mL* (from the cup) · 5 *Save* (write + read back). Footer: **Back**, *"Step N of 5"*, and a named primary button: **Next: prime Part A**, **Run 30 s**, **Save 300 mL/min**.
1. Pump cards show *"Calibrated 30 Sep · 298 mL/min / 22 days ago"*, or a due warning *"69 days ago · due, every 60 days"*. *What this pump doses* is Nutrient · pH up · pH down · Additive, with the lockout note. *Pump head, peristaltic* is 320 · 160 · 64 · 600 mL/min. The picture on the right is drawn.
2. **Hold to prime** (max 30 s) under the interlock checklist (*Mix pump off ✓ · Room dosing paused ✓ · Tank not filling ✓*). Any ✗ disables the button and names the blocker.
3. *"Put the suction line in a measuring jug with at least 250 ml."* → **Run 30 s** (`pump_calibrate`, a countdown ring).
4. *"How much did it pull?"* — `inputmode="decimal"`, mL.
5. The result sentence + wear sparkline (hidden under 360 px) → Review & apply → receipt.

On 3.17 the page is `NeedsIntegration feature="Pump prime and calibration"`, with a link to Feed & dosing.

- [ ] **Step 1: Write the failing tests**
  - `measuredRate 150 mL in 30 s vs 280 nominal → 300 mL/min, +7%`.
  - `calibrationDue 69 days at every 60 → due`.
  - `wearNote down 12% since March`.
  - `prime sends pump_stop on release` (`HoldButton` logic with a spy).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Step 2 calls `pump_prime {seconds: min(held, 30)}` on start and `pump_stop` on stop.
- [ ] **Step 4:** Run → PASS. `verify-parity-e3.mjs` (mockup 15):
  - pick Part B → the primary button reads "Next: prime Part B";
  - mouse-down 2 s on **Hold to prime**, then mouse-up → the demo records `pump_prime` then `pump_stop`;
  - enter 150 → *"300 mL/min"*;
  - Save → receipt.
- [ ] **Step 5:** Commit as `feat(frontend): pump prime and calibrate wizard`.

### Task 24: E4 Feed pH/EC calibration (+ P5)

**Files:**
- Create: `frontend/src/pages/feed-calibration.tsx`, `frontend/src/pages/feed-calibration.css`, `frontend/src/lib/feed-calibration.ts`, `frontend/src/lib/parity-demo/calibration.ts`, `frontend/scripts/verify-parity-e4.mjs`
- Modify: `frontend/scripts/verify-calibration.mjs` (route `#/equipment/feed-calibration`; the v1 two-point manual path stays as the 3.17 fallback)
- Test: `frontend/src/lib/feed-calibration.test.ts`

**Interfaces:**
- Consumes:
  - `StepRail` (compact on phone), `StabilityRing`;
  - `callV2("calibration_start" | "calibration_capture" | "calibration_commit" | "calibration_revert")`;
  - `subscribe_entities` live raw reading (from `raw_entity_id`);
  - the existing `components/probe-calibration.tsx` (3.17 fallback, rendered unchanged);
  - `offerUndo` → `calibration_revert`.
- Produces:
  - `export function drift(readings: { at: number; value: number }[], windowMs = 30_000): number`
  - `export function stability(drift: number, kind: "ph" | "ec"): "settling" | "steady"` (steady below 0.02 pH / 0.01 mS per 30 s)
  - `export function verdictWords(slopePct: number, offset: number, kind): { headline: string; health: "healthy" | "clean_soon" | "replace" }`, e.g. *"Probe reads 0.12 pH low. Response 97% — healthy."* / *"Response 86% — clean or replace the probe soon."*
  - `export function useWakeLock(active: boolean): void`

**Steps (mockup 16):** 1 *Choose probe* · 2 *Buffer 1* (7.00 / 1.413 mS) · 3 *Buffer 2* (4.00 / 2.77 mS) · 4 *Result* (slope and offset) · 5 *Apply* (raw vs corrected).
- Prepare copy: *"Rinse the probe, dab it dry and stand it in the 7.00 buffer. Leave it still; the reading settles by itself."*
- Live reading: *"pH · buffer 7.00 · 21.3 °C, compensated to 25 °C"*, a drift sparkline, and *Settling…* / **Steady**, with *"Capture unlocks after the reading holds within ±0.01 for 30 s."*
- The button **Capture 7.00 point · waiting for stable** becomes **Capture 7.00 point** when steady. *Capture anyway* sits in a secondary menu with *"Reading still moving — calibration may be off."*
- Footer: *"Step 2 of 5 · dosing for F2 paused"*, **Next: rinse, into 4.00**.
- Apply has a proof row *"Now reads 4.01 in pH 4.00 buffer ✓"*.
- Offline: *"No reading from the feed pH probe for 2 min. Check it's plugged in."*, and Capture is disabled.
- Leaving mid-wizard shows *"Resume calibration"* for 30 min (session id in sessionStorage).
- P5 (390 px): full-screen; the header *"Calibrate F2 feed pH" / "Equipment · step 2 of 5 · dosing paused"* with ✕; a segmented step bar; the big ring; the primary button *"Waiting for a steady reading"*.
- On 3.17: the old two-point form renders under `NeedsIntegration compact`.

- [ ] **Step 1: Write the failing tests**
  - `drift over last 30 s`.
  - `stability ph threshold 0.02`.
  - `verdictWords 97% healthy, 86% clean soon`.
  - `stale reading disables Capture`: the reading is older than 2 engine loops → `captureState(...)` gives `{enabled:false, reason:"No reading from the feed pH probe for 2 min. Check it's plugged in."}`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Wake Lock is re-acquired on `visibilitychange` and skipped when unsupported.
- [ ] **Step 4:** Run → PASS. `verify-parity-e4.mjs` (mockups 16 and 28):
  - the demo feeds a settling then steady reading → Capture enables;
  - capture both points → the result headline → Apply → receipt → the Undo toast;
  - at 390 px the ✕ returns to Feed & dosing.

  Then `node scripts/verify-calibration.mjs` with `?backend=3.17` → the old flow passes.
- [ ] **Step 5:** Commit as `feat(frontend): feed pH/EC calibration wizard with stability ring`.

### Task 25: T1 Alert rules (+ P4)

**Files:**
- Create: `frontend/src/pages/alert-rules.tsx`, `frontend/src/pages/alert-rules.css`, `frontend/src/components/rule-sentence.tsx`, `frontend/src/lib/alert-rules.ts`, `frontend/src/lib/parity-demo/alerts.ts`, `frontend/scripts/verify-parity-t1.mjs`
- Test: `frontend/src/lib/alert-rules.test.ts`

**Interfaces:**
- Consumes: `callV2("alert_rule_list" | "alert_rule_set" | "alert_rule_delete" | "alert_rule_test" | "alert_rule_preview")`, `notify_get` (targets), `binary_sensor.crop_steering_rule_*` (3.17-safe list fallback), recharts
- Produces:
  - `export const RULE_SOURCES: { id: AlertRule["source"]; label: (room, zone?) => string; unit: string }[]` (schema §2.9 list)
  - `export function ruleSentence(rule: AlertRule, names): string`, e.g. *"Tell Night crew when F2 Zone 2 pore EC is above 6.0 mS/cm for 120 min, while lights are on."*
  - `export function previewSentence(p: AlertPreview): string`. The three shapes:
    - *"Would have alerted 2 times yesterday"* + detail *"05:40 (under 30 % for 40 min) · 15:20 (under 30 % for 40 min) · 1 shorter dip ignored"*
    - *"It wouldn't have fired in the last 24 h. Lowest was 41%."*
    - over 10: *"That's 14 messages a day. Try a longer wait or a lower threshold."*
  - `export function ruleStatus(rule, state): { text: string; tone }`: *"Firing now · since 12:42"*, *"Fired 11:31 today"*, *"Last fired Tue 03:40"*, *"Never fired"*, *"Off since 18 Oct · would fire now (5.4 L)"*.
  - `RuleSentence({ rule, onChange, targets, sources, phone: boolean })`. Desktop uses inline token selects in the sentence; phone uses stacked labelled native selects (P4).

**Layout to mockup 19:**
- *New rule* intro copy, then the sentence builder: *Tell [Ben's phone] when [F2 Zone 1 moisture] is [below] [30] % for [10] min [at any time].*
- Replay: *"Yesterday, as this rule would have seen it"* with the source caption, would-alert spans shaded, ● markers labelled with times, a draggable dashed threshold (arrow keys step 0.1 / 1), lights-off shading, and the legend *would alert · too short to alert · your threshold*. Recompute is debounced 250 ms.
- **Send a test push to Ben's phone** (per-target result line); **Save rule and start watching**.
- *Your rules* "5 rules · 4 on", *"Each rule is also binary_sensor.crop_steering_rule_… in Home Assistant"*. Rows: sentence (bold tokens), status, **Edit**, and an On switch (an immediate write + Undo toast). Delete in the editor is immediate + Undo.
- `?rule=<id>|new` URL. P4 header *"New alert rule" / "Settings · Alert rules"* with **All rules**.
- On 3.17: the list comes from rule binary sensors if any exist, and the builder and replay show `NeedsIntegration feature="Your own alert rules"`.

- [ ] **Step 1: Write the failing tests**
  - `ruleSentence matches the Night crew example exactly`.
  - `previewSentence 2 fires, 0 fires with lowest, 14 fires warning`.
  - `ruleStatus off-but-would-fire`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-t1.mjs` (mockups 19 and 27):
  - change the threshold to 40 → the result line changes within 1 s;
  - ArrowUp on the threshold line moves it by 0.1;
  - **Save rule and start watching** → the new row appears;
  - the toggle off → Undo;
  - at 390 px the selects are native `<select>`.
- [ ] **Step 5:** Commit as `feat(frontend): alert rule builder with yesterday replay`.

### Task 26: T2 Notifications

**Files:**
- Modify: `frontend/src/pages/notifications.tsx`, `frontend/src/pages/notifications.css`, `frontend/src/lib/notify.ts` (parse optional `quiet_hours`, `mutes`, `loud`, `last_test`)
- Create: `frontend/scripts/verify-parity-t2.mjs`
- Test: `frontend/src/lib/notify.test.ts` (extend)

**Interfaces:**
- Consumes: `notify_get` / `notify_save` / `notify_test`, `ReviewApply layout="bar"`, `useDraft("notify")`
- Produces: `NotifyConfig` gains optional `quiet_hours?: { from: string; to: string; phones: string[] }`, `mutes?: Record<string, number>`, and `NotifyPhone.loud?: boolean`, `last_test?: { at: number; ok: boolean; detail: string }`. A missing key hides its control. There is a kind column `rules` labelled *"Your rules"*.

**Delta to mockup 20:**
- The matrix columns are exactly: *Emergency · Hardware · Watering stopped · Sensors · Dosing · Stock · Phases · AI · Setup · Vitals · Your rules · Rooms · Emergencies loud*.
- Each phone row: name and entity, **Send test** + the result (*"Accepted 13:58"*, *"Never tested"*, *"Failed 13:40 · 1 of 3 phones did not answer in 8 s"*), and room chips with *every room* / *"F2 only"*.
- *Quiet hours* with time inputs, phone chips, a 24 h strip with lights-on overlay, and the explanation sentence.
- *Watering stopped and room mutes*: *"Count watering as stopped after [3] h with no shot, lights on"*, mute rows with **Unmute F1** / **Mute F2 for 2 h** (immediate + Undo).
- The bottom bar *"2 changes not applied yet: Sam's phone gets Dosing · Office tablet: F2 only"* with **Discard** / **Apply 2 changes**.
- On 3.17: works with the existing keys; quiet hours, mutes and loud are hidden when absent.

- [ ] **Step 1: Write the failing tests**
  - `parse tolerates missing quiet_hours`.
  - `draft summary sentence lists each change in words`.
  - `rules column only when kinds include rules`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-t2.mjs` (mockup 20):
  - tick Sam's Dosing → the bar shows the sentence → Apply → receipt;
  - **Mute F2 for 2 h** → Undo.

  Then `verify-workspace.mjs` notification checks → pass.
- [ ] **Step 5:** Commit as `feat(frontend): notifications routing, quiet hours and mutes`.

### Task 27: T3 System status

**Files:**
- Create: `frontend/src/pages/system.tsx`, `frontend/src/pages/system.css`, `frontend/src/lib/system-status.ts`, `frontend/src/lib/parity-demo/system.ts`, `frontend/scripts/verify-parity-t3.mjs`
- Test: `frontend/src/lib/system-status.test.ts`

**Interfaces:**
- Consumes: `callV2("system_status_get")`, `sensor.crop_steering_system_health`, `runningVersions` (`model.ts:243`), the JEV/brain entities, `error-codes.ts`, `HealthRing`
- Produces:
  - `export function healthSentence(s: SystemStatus): string`, e.g. *"System health 94 %: 34 of 35 devices online, both controllers beating, 3 open alerts, each shown below where it happens."*
  - `export function groupDevices(s: SystemStatus): { kind: "probes" | "valves" | "pumps" | "tank" | "dosing" | "climate"; label: string; online: number; total: number; uptimePct: number | null; rows: { name; entityId; lastSeen: number; ok: boolean; uptimePct: number | null; alert: { code: string; text: string } | null }[] }[]`, with silent rows first
  - `export function ageTone(lastSeen: number, loopS: number, now: number): "ok" | "warn" | "bad"` (orange after 2 loop intervals, red after 20 min)
  - One shared 30 s ticker drives all relative times.

**Layout to mockup 21:**
- Ring + sentence + *"Checked 14:02:11"*.
- *Software*: Controller app, Integration (*"Up to date · matches the controller"*), Dashboard cards (*"Loaded as ?v=3171…"*), Home Assistant, AI assistant with a CS-706 card in place.
- *Heartbeat*: bars per controller with a missed beat marked.
- *Every mapped device* grouped: Moisture and EC probes / Valves / Pumps / Tank and feed sensors / Dosing / Room climate (readings only). Each row: last seen, a 7-day bar, %. CS cards sit in place under their row (*"CS-102 Probe with no reading… What to do →"* to `#/help?code=CS-102`).
- A link *"Capabilities ›"* (`#/settings/features`).
- On 3.17: built from entities only (versions, heartbeat entity, mapped entities from the descriptor with `last_updated`); uptime and heartbeat history show "—" plus compact `NeedsIntegration`.

- [ ] **Step 1: Write the failing tests**
  - `healthSentence exact for fixture`.
  - `groupDevices puts silent first and attaches CS alert to its entity`.
  - `ageTone thresholds`.
  - `entity-only fallback counts online from last_updated`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-t3.mjs` (mockup 21): the CS-102 card is inside the F1 Zone 2 back row's group, "What to do" links to help, and on 3.17 the page renders with versions.
- [ ] **Step 5:** Commit as `feat(frontend): system status with problems on their device`.

### Task 28: T4 AI assistant

**Files:**
- Modify: `frontend/src/components/brain.tsx` (`AiSettings` only, `:419`), `frontend/src/lib/brain.ts`
- Create: `frontend/scripts/verify-parity-t4.mjs`
- Test: `frontend/src/lib/brain.test.ts` (extend)

**Interfaces:**
- Consumes: existing brain/JEV entities and `brain_*` services, `controller.write` for judge switches, `useCsEvents` (`ai.judgement`, `ai.outcome`), `journal_query` (3.18), the existing ledger attribute (3.17)
- Produces:
  - `export function judgeMatrix(states, rooms): { id; name; blurb; power: "act" | "alerts" | "advice"; perRoom: Record<string, { on: boolean; entityId: string | null; note?: string }> }[]`. A `note` covers e.g. *"stacking off"*.
  - `export function outcomes(entries): { at; scope; judge; text; result: string; verdict: "worked" | "measuring" | "undone"; band: [number, number]; value: number }[]`

**Delta to mockup 22:**
- *Judges "25 of 27 on · F2 and F1"* with the explainer, and a table of Judge / Can it act? (*Can act* / *Alerts* / *Advice*) / one switch per room. Each switch is an immediate write + Undo toast.
- *Budget today* *"$0.82 of $1.00"*: bar, warning line, CS-706 in place, *Daily budget US$* input with a receipt.
- *Dry run* switch; model segmented control *Haiku 5.5 · Sonnet 5.5 · Opus 5.5*; the cost line.
- *What it did, and what happened*: entries with a verdict pill and band bar, plus **Full ledger in History →** (`#/history/changes?actor=ai`).
- The existing prompt editor and permitted AI actions stay below under *"Instructions and permissions"*.
- On 3.17 everything is v1, so the outcomes come from the ledger attribute.

- [ ] **Step 1: Write the failing tests**
  - `judgeMatrix maps per-room switches and notes`.
  - `outcomes verdict from ai.outcome`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-t4.mjs` (route `/settings/ai`, mockup 22): toggle *Water channel · F1* → Undo; budget input → receipt. Then `node scripts/verify-ai-instructions.mjs` → passes.
- [ ] **Step 5:** Commit as `feat(frontend): AI assistant judges matrix, budget and outcomes`.

### Task 29: T5 Dashboards & display

**Files:**
- Modify: `frontend/src/pages/settings.tsx`, `frontend/src/pages/settings.css`, `frontend/src/components/display-settings.tsx`, `frontend/src/lib/units.ts`, `frontend/src/lib/display.ts`
- Create: `frontend/scripts/verify-parity-t5.mjs`
- Test: `frontend/src/lib/units.test.ts` (extend), `frontend/src/lib/display.test.ts` (extend)

**Interfaces:**
- Consumes: `display_get` / `display_save`, `landing-view.ts`, `callV2("dashboard_create" | "dashboard_list")`, `useWakeLock` (Task 24)
- Produces:
  - `export type EcUnit = "mS/cm" | "ppm500" | "ppm700"`, `TempUnit = "C" | "F"`, `VolumeUnit = "L" | "gal"`, `ClockStyle = "24" | "12"`
  - `export function formatEc(ms: number, unit: EcUnit, sourceDigits: number): string`
  - `export function formatTemp(c: number, unit: TempUnit, sourceDigits: number): string`
  - `export function formatVolume(l: number, unit: VolumeUnit, sourceDigits: number): string`
  - `export function useUnits(controller): { ec; temp; volume; clock }`, consumed by every page via the existing formatter call sites. Only this task changes the call sites in `lib/`; pages that land earlier pick it up through the formatter.

**Layout to mockup 23:**
- *Units "Shown on every page and phone for this Home Assistant user"*: EC (mS/cm · PPM 500 · PPM 700), Temperature (°C · °F), Volume (Litres · US gallons), Clock (24 h · 12 h). Each has a live example on the right (*"Feed EC 2.4 mS/cm · pore EC 5.2 mS/cm"*), and the footnote *"Display only. Readings stay stored in mS/cm, °C and litres, so switching back shows exactly the same numbers."*
- *Where the app opens*: computer / phone selects, *"Saved and read back 13:48"*.
- *Wall and tablet dashboards*: three live thumbnail cards (Facility wall, Room tablet, Dosing station) with room chips and **Create in Home Assistant** / **Create again**. After creating: *"Created Tue 16:20 as /crop-wall · cards ?v=3171 · showing on the TV in the corridor"* + **Open in Home Assistant**.
- *"Keep this screen on while open"* toggle (hidden when Wake Lock is unsupported).
- Existing HA connection, appearance, display options and sample workspace sit under a `<details>` *"More display options"*.
- On 3.17: units for EC and temperature save if `display_save` accepts them, else they are stored in localStorage with the note *"Saved on this browser only until integration 3.18"*. Dashboards show `NeedsIntegration`.

- [ ] **Step 1: Write the failing tests**
  - `formatEc 2.4 mS/cm → 1200 ppm500, 1680 ppm700, no extra decimals`.
  - `formatTemp 21.4 C → 70.5 F` (source precision 1).
  - `formatVolume 24.8 L → 6.6 gal`.
  - `round-trip mS/cm unchanged after switching back`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-t5.mjs` (route `/settings`, mockup 23):
  - PPM 500 → the example updates and `#/all-zones` shows "ppm";
  - **Create in Home Assistant** (Room tablet) → the created line;
  - on 3.17 the dashboards note shows.
- [ ] **Step 5:** Commit as `feat(frontend): units, landing and wall dashboards`.

### Task 30: Top bar and command palette

**Files:**
- Modify: `frontend/src/components/app-header.tsx`, `frontend/src/components/app-header.css`
- Create: `frontend/src/components/command-palette.tsx`, `frontend/src/lib/command-palette.ts`, `frontend/scripts/verify-parity-shell.mjs`
- Test: `frontend/src/lib/command-palette.test.ts`

**Interfaces:**
- Consumes: `NAV_TREE`, `controller.rooms`, `routeHash`, `SafetySwitches` (existing Watering on / Stop all)
- Produces:
  - `export interface PaletteEntry { label: string; hint: string; hash: string; keywords: string[] }`
  - `export function paletteEntries(controller: Controller): PaletteEntry[]` (pages, rooms, zones, and the actions *"Calibrate F2 feed pH"*, *"Prime a dosing pump"*, *"New alert rule"*, *"New timer program"*)
  - `export function searchPalette(entries: PaletteEntry[], q: string): PaletteEntry[]` (prefix > word-start > substring)

**Top bar (all desktop mockups):**
- *"Updated 12 s ago"*, *"● AI acting"* chip, **Jump to… Ctrl K**, the current room name as plain text (no room chips; the room tree is the picker), *"● Watering on"*, **Stop all**.
- Phone: the header shows the page title and *"Updated 12 s ago · AI acting"*.
- The palette is a `<dialog>`.
  - Ctrl K is bound only while focus is inside the panel; `/` is the fallback.
  - Every result navigates by hash.
- The sidebar footer reads *"Integration 3.17.1 · Controller 3.17.1"* (existing).

- [ ] **Step 1: Write the failing tests**
  - `searchPalette "cal ph" finds Calibrate F2 feed pH first`.
  - `entries include every NAV_TREE page and every zone`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS. `verify-parity-shell.mjs`:
  - Ctrl K → type "changes" → Enter → `#/history/changes`;
  - Escape closes the palette and focus returns;
  - at 1440 the header has no room chip buttons.

  Then `verify-dashboard.mjs` and `verify-ha-shell.mjs` header selectors → pass (update the room-chip assertions to the room tree).
- [ ] **Step 5:** Commit as `feat(frontend): top bar with jump-to palette`.

### Task 31: Bundle, full browser suite, CI list

**Files:**
- Modify: `www/dashboard.html`, `addons/f2_control/www/public/dashboard.html`, `custom_components/crop_steering/www/dashboard.html` (+ legacy stubs) via `package.mjs`; `.github/workflows/ci-validate.yml:390-397` (add `verify-navigation`, `verify-parity-*`); `frontend/scripts/capture-readme.mjs` (new pages)

- [ ] **Step 1:** Run `node node_modules/typescript/bin/tsc --noEmit && node node_modules/vitest/vitest.mjs run` → all PASS.
- [ ] **Step 2:** Run `node node_modules/vite/bin/vite.js build && node scripts/package.mjs` → exit 0, three bundles written, and no external URL in the output.
- [ ] **Step 3:** Run every `node scripts/verify-*.mjs` (existing and `verify-parity-*`) → each exits 0. Fix only selector drift caused by this plan.
- [ ] **Step 4:** Open each `output/playwright/parity/*-compare.html` beside its mockup. Every remaining difference is listed in the commit body as accepted (sample data) or fixed.
- [ ] **Step 5:** Commit as `build(frontend): parity bundle and browser checks in CI`.

---

## Self-review notes

- **Spec coverage.** G-items and where they land:
  - G1: Task 22, plus the I1 pump wait and the I3 capacity card.
  - G2: Task 24. G3: Task 23. G4: Tasks 16 and 8.
  - G5: Task 11. G6: Task 25. G7: Task 13. G8: Task 18.
  - G9 and G14: Task 19. G10: Task 14. G11 and G15: Task 29.
  - G12 (inline injection) is deferred, as the spec says ("waits until a skid is on the bench"). E2 keeps a *Mixing method* row only when `select.*_dosing_mode` exists.
  - G13 (scale hint in the wizard mapping step) is not drawn in any mockup and its `scale_hints[]` contract is unconfirmed. It is a follow-up in `components/setup-wizard.tsx`.
  - G16: Task 8. G17: Task 27.
  - §3 patterns: review & apply (Task 5), undo (Task 5), live (Task 4), alert in place (Tasks 7/8/11/27), ShotTimeline (Task 7), rule builder (Task 25), calibration wizard (Tasks 23/24), pick mode (Task 7), command palette (Task 30), `lib/time.ts` (Task 5).
- **Deviation from the UX spec, following the mockups:**
  - Health lives at Settings › System status, not Equipment › Health.
  - Timers are their own page (I3) as well as having an irrigation-mode row, rather than only an inline per-zone card.
  - Alert rules are their own tab rather than a section of Notifications.
