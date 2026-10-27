# Parity Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 28 mockup screens of the parity work (Status, Irrigation, History, Equipment, Settings, phone) in the React panel on top of the v2 `crop_steering.*` services. This includes a tree menu and the shared pieces: review-and-apply, undo, timeline, sentence builder and live events. Every page must still load on a 3.17 backend.

**Architecture:**
- Shared pieces come first, in this order:
  1. tree menu, routes and per-page stub files;
  2. browser harness;
  3. v2 service client with demo fixtures and missing-service detection;
  4. `crop_steering/subscribe` live feed;
  5. drafts, review-and-apply, undo, time and units;
  6. visual primitives, including the sentence builder and Wake Lock;
  7. `ShotTimeline`, the open-alerts selector and the room tree.
- Pages then replace their stub or extend the existing page.
- Pages hold no business logic. They render service responses and entity states, show the server's own sentences, and send every write through one review-and-apply flow with read-back.

**Tech Stack:** React 19, TypeScript 7, Vite 8 single-file build, Tailwind v4 + shadcn on `radix-ui`, recharts 3, sonner, lucide-react, vitest 5 (node environment, `renderToStaticMarkup`), Playwright + axe for browser checks.

**Spec:**
- `docs/superpowers/specs/2026-10-22-parity-ux.md` (UX, G1–G17, §3 patterns)
- `docs/superpowers/specs/2026-10-22-unified-schema.md` §4–§6
- `docs/superpowers/mockups/*.png` (target design)
- **Backend contract:** `docs/superpowers/plans/2026-10-22-parity-backend.md` at 4dc8f31e. The backend owns every service name and shape; this plan adopts them exactly.
- Preflight: `.superpowers/sdd/2026-10-22-parity-frontend/preflight.md`

## Global Constraints

- **Where to work:** only in `C:\Github\HA-Irrigation-Strategy-parity` on branch `feat/parity-system`. Frontend commands run from `frontend/`. **npm is banned.**
  - Typecheck: `node node_modules/typescript/bin/tsc --noEmit`
  - Tests: `node node_modules/vitest/vitest.mjs run`
  - Build: `node node_modules/vite/bin/vite.js build`
  - Bundle: `node scripts/package.mjs`. **Only Task 31 runs this.**
  - Browser checks: `node scripts/verify-*.mjs`
- **Commits:**
  - Identity: `git -c user.email=123831499+JakeTheRabbit@users.noreply.github.com -c user.name=JakeTheRabbit commit`.
  - Message: conventional (`feat(frontend): …`), ending in a blank line plus `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Each task is one commit, frontend only. Stage only the files the task lists.
- **Generated bundles** (`www/dashboard.html`, `addons/f2_control/www/public/dashboard.html`, `custom_components/crop_steering/www/dashboard.html` and the stubs) are regenerated **once, by Task 31**, after the frontend lanes and the backend plan have merged.
  - No frontend lane commits them.
  - The backend plan's CS-code tasks (12, 17, 26) must commit sources only (`render_error_codes.py` output, `notify_catalog.py`, `docs/error-codes.json`) and **must not** rebuild the bundles. This is listed under Backend asks, item 1.
- **Definition of done for a page task:**
  - tsc is clean and vitest passes.
  - The task's `scripts/verify-parity-<id>.mjs` passes. It covers 1440×1000 and 390×844 at DPR 2, in both `?demo=1` and `?demo=1&backend=3.17`, and its Playwright step lists the interactions it asserts.
  - The harness writes `output/playwright/parity/<id>-compare.json`, holding the screenshot sizes plus every region name the check asserted. The commit body lists the mockup differences that remain.
  - Overflow is checked at document level only. A wide table may scroll inside its own `overflow-x:auto` region.
- **House rules (owner):**
  - Show every fact once per screen.
  - The room tree is the only room or zone picker on desktop.
  - Visuals over number walls.
  - Problems sit in place, on the thing that has them.
  - Use plain grower words and specific button labels.
  - Writes go through review-and-apply, ending in **"Written and read back HH:MM"**.
  - Undo replaces a confirm dialog wherever the change can be reversed.
  - Physical actions use a `HoldButton`, in one of two modes:
    - `while-held`: the action runs only while held (pump prime).
    - `hold-to-confirm`: hold for 1.5 s to start a fixed action (test shot, refill batch).
  - Stop all keeps its existing guard.
  - Phone keeps the bottom bar with 5 sections.
- **Out of scope:** users and roles, tasks, IPM, compliance, climate and lighting control (climate appears as readings only).
- **Older backend:** a v2 service that is missing renders `NeedsIntegration` (heading **"Needs integration 3.18"**) in place of the part that needs it. It never crashes and never throws a page error. `PARITY_MIN_VERSION = "3.18.0"`.
- **The panel never sends `client` or `proposal_token`** on any call. Backend `attribution()` would otherwise record the panel's writes as MCP or AiGrow. Task 3 pins this.
- **Rooms** are addressed as `room_id = "room:" + prefix`. This is already the frontend `RoomView.id` (`lib/model.ts:167`).
- **Desktop menu:** an expandable disclosure tree. On desktop (≥ 721 px) the in-page `.page-tabs` are hidden. On phone (≤ 720 px) the bottom bar keeps 5 sections and the sub-tabs stay inside the page.
- **Units and time:**
  - All formatting goes through the Task 5 display-units store: `formatEc`, `formatTemp`, `formatVolume`, `clock`.
  - That store is filled from the selected room's `display` options (`ec_unit`, `temp_unit`, `volume_unit`, `clock`, backend Task 33). Pages never pass units.
  - Storage stays mS/cm, °C and litres. Formatters never round past source precision.
  - All time maths goes through `lib/time.ts`.
- **Tests:** vitest files sit beside their logic as `src/lib/<name>.test.ts`. Components render with `renderToStaticMarkup`, since there is no jsdom.
- **Existing verify scripts** each have one owner. Only the owner edits the script; any other task runs it read-only. Selector drift outside these owners is fixed in Task 31.

  | Script | Owner task |
  |---|---|
  | `verify-navigation` | 1 |
  | `verify-dashboard` (nav part) | 1 |
  | `verify-dashboard` (header part) | 30 |
  | `verify-ha-shell` | 30 |
  | `verify-irrigation-workspace` | 12 |
  | `verify-recipe-library` | 14 |
  | `verify-tank-status` | 20 |
  | `verify-calibration` | 24 |
  | `verify-ai-instructions` | 28 |
  | `verify-workspace`, `verify-steering-visuals`, `verify-live`, `capture-readme` | 31 |

## Review Focus

1. **A 3.17 backend** (a v2 service is missing). Expected: each new page or section shows "Needs integration 3.18" in place, and v1 content still renders.
   - Pinned by: Task 3 `callV2 maps service_not_found to missing`, plus the `backend=3.17` pass in every verify script.
2. **A non-admin HA user.** Expected:
   - The live feed uses `crop_steering/subscribe`, which signed-in users may call. It polls `journal_query` (per room, by cursor) only when the command is unknown.
   - Writes show "Only a Home Assistant administrator can change this."
   - Pinned by: Task 4 `uses crop_steering/subscribe and polls only on unknown_command`, and Task 5 `forbidden error shows admin copy`.
3. **The read-back disagrees, or only part of a multi-row apply succeeds** (one `copy_config` row `readback:"refused"`, or a `WriteResult.failed` entry). Expected:
   - Each failed row says "Controller still holds {old}. Nothing else was changed." plus **Try again**.
   - The draft is kept, and no success receipt appears.
   - Pinned by: Task 5 `partial apply keeps failed rows in the draft`.
4. **Stale revision** (`stale_revision`, because a second tab or AiGrow wrote first). Expected: "Someone else changed this at HH:MM. Reload their version and reapply your edits." plus **Reload**, and the draft is kept.
   - Pinned by: Task 5 `stale_revision keeps draft and offers reload`.
5. **The connection drops mid-wizard.** Expected:
   - A while-held prime sends `pump_stop` on `pointercancel` or `visibilitychange`.
   - Capture is disabled on a stale reading.
   - An expired calibration session restarts at buffer 1 with plain words.
   - Pinned by: Task 6 `hold releases on visibility hidden`, and Task 24 `stale reading disables Capture` and `expired session restarts from buffer 1`.

## Parallel lanes

Tasks 1–7 are the trunk and run in order. After Task 7 the lanes below run in parallel. The file lists are taken from each task's Files block; a lane may touch only its own files.

| Lane | Tasks | Files (exclusive) |
|---|---|---|
| A Status | 8, 9, 10 | `pages/all-zones.*`, `pages/today.*`, `pages/zone.*`, `lib/facility-view.ts`, `lib/today-room.ts`, `lib/zone-shot-log.ts`, `components/day-timeline.tsx`, `parity-demo/status.ts`, `verify-parity-s1/s2/s3.mjs` |
| B Irrigation | 11, 12, 13, 14 | `pages/watering.*`, `pages/strategy.tsx`, `pages/targets.css`, `lib/strategy-review.ts`, `pages/timers.*`, `lib/timers.ts`, `pages/grow-planner.*`, `components/presets-panel.tsx`, `lib/presets.ts`, `parity-demo/irrigation.ts`, `verify-parity-i1..i4.mjs`, `verify-irrigation-workspace.mjs`, `verify-recipe-library.mjs` |
| C History | 15, 16, 17, 18 | `pages/explorer.*`, `components/history-explorer.tsx`, `lib/history-explorer.ts`, `pages/water-use.*`, `lib/flow-check.ts`, `pages/comparison*.tsx`, `lib/comparison.ts`, `pages/changes.*`, `lib/changes.ts`, `components/setting-history.tsx`, `components/setting-row.tsx`, `parity-demo/history.ts`, `verify-parity-h1..h4.mjs` |
| D Equipment | 19, 20, 21, 22, 23, 24 | `pages/probes.*`, `lib/probes.ts`, `lib/probe-offset.ts`, `pages/dosing.*`, `pages/reservoir.tsx` (deleted), `lib/dosing.ts`, `pages/stock.*`, `lib/stock.ts`, `components/stock-bottle.tsx`, `pages/setup.tsx`, `components/supply-editor.*`, `lib/supply.ts`, `pages/pump-calibration.*`, `lib/pump-calibration.ts`, `pages/feed-calibration.*`, `lib/feed-calibration.ts`, `components/probe-calibration.tsx`, `parity-demo/equipment.ts`, `verify-parity-e1..e6.mjs`, `verify-tank-status.mjs`, `verify-calibration.mjs` |
| E Settings | 25, 26, 27, 28, 29 | `pages/alert-rules.*`, `lib/alert-rules.ts`, `pages/notifications.*`, `lib/notify.ts`, `pages/system.*`, `lib/system-status.ts`, `components/brain.tsx` (AiSettings), `lib/brain.ts`, `pages/settings.*`, `components/display-settings.tsx`, `lib/display.ts`, `parity-demo/settings.ts`, `verify-parity-t1..t5.mjs`, `verify-ai-instructions.mjs` |
| F Shell | 30 | `components/command-palette.*`, `lib/command-palette.ts`, `components/app-header.*`, `App.tsx` (the AppHeader call site only), `verify-parity-shell.mjs`, `verify-dashboard.mjs` (header part), `verify-ha-shell.mjs` |

How the shared parts stay conflict-free:
- **`App.tsx`** is edited by Task 1 (every route, importing each page's own stub file) and by Task 30 (one AppHeader call site). No other task edits it.
- **Demo fixtures:**
  - `lib/parity-demo.ts` and `parity-demo/journal.ts` belong to Task 3.
  - Each lane registers handlers in its own `parity-demo/<lane>.ts`. Task 3's index concatenates them in a fixed order, and a handler with a matching `match()` runs before the Task 3 default.
  - `journal_query` is answered only by Task 3's journal fixture. It generates every kind for the demo rooms and filters by `room_id`, `kinds`, `zones`, `since`, `until` and `cursor`, so no lane overrides it.
- **Task 31** runs last, after every lane and the backend plan.

## Mockup → page map

| # | Mockup | Route | File: action | Delta |
|---|---|---|---|---|
| S1 | 02 | `#/all-zones` | `pages/all-zones.tsx`: extend | Queued line from the room `shot_queued.queue[]`, hollow last-shot dot when `flow_ratio < 0.8`, calibration-due flag, grow-day entities |
| S2 | 03 | `#/today` | `pages/today.tsx`: extend | Today strip (`ShotTimeline strip`), Sensors column, problem in place, duplicate HMI table removed |
| S3 | 04 | `#/zone/N` | `pages/zone.tsx`: extend | Compare Off/Yesterday/Last run, AI suggestion card, shot log |
| I1 | 05 | `#/plan/watering` | stub → `pages/watering.tsx` | Watering timeline, popover, Skip this shot |
| I2 | 06 | `#/plan/targets` | `pages/strategy.tsx`: extend | `ReviewApply` bar, receipt, This afternoon |
| I3 | 07 | `#/plan/timers` | stub → `pages/timers.tsx` | Timer programs, preview, irrigation mode |
| I4 | 08 | `#/plan/schedule` | `pages/grow-planner.tsx`: extend | Controller presets, copy to room |
| H1 | 09 | `#/history/explorer` | `pages/explorer.tsx` (renamed in Task 1 from `timeline.tsx`): extend | Phase and shot lanes, chart notes, compare with last run |
| H2 | 10 | `#/history/water` | `pages/water-use.tsx`: rebuild | Metered vs asked, leak check, water per plant |
| H3 | 11 | `#/history/compare` | `pages/comparison*.tsx`: extend | Run cards, callouts |
| H4 | 12 | `#/history/changes` | stub → `pages/changes.tsx` | Change feed, revert |
| E1 | 13 | `#/equipment/probes` | `pages/probes.tsx`: extend | Offsets, Match handheld, curve, placement |
| E2 | 14 | `#/equipment/dosing` | `pages/dosing.tsx`: extend; `reservoir.tsx` folded in | Plumbing diagram, mix check in place |
| E3 | 15 | `#/equipment/pump-calibration` | stub → `pages/pump-calibration.tsx` | 5-step wizard |
| E4 | 16 | `#/equipment/feed-calibration` | stub → `pages/feed-calibration.tsx` | 5-step wizard, stability ring |
| E5 | 17 | `#/equipment/stock` | `pages/stock.tsx`: extend | Bottles to scale, refill undo |
| E6 | 18 | `#/equipment/setup` | `pages/setup.tsx` + `components/supply-editor.tsx` | Capacity, groups, review panel |
| T1 | 19 | `#/settings/alerts` | stub → `pages/alert-rules.tsx` | Sentence builder, replay, rules list |
| T2 | 20 | `#/settings/notifications` | `pages/notifications.tsx`: extend | Room chips, loud, quiet hours, mutes, bar |
| T3 | 21 | `#/settings/system` | stub → `pages/system.tsx` | Health, software, heartbeat, devices |
| T4 | 22 | `#/settings/ai` | `components/brain.tsx` `AiSettings`: extend | Judges matrix, budget, outcomes |
| T5 | 23 | `#/settings` | `pages/settings.tsx`: extend | Units, landing, wall dashboards |
| P1 | 24 | `#/all-zones` @390 | as S1 | 3-up tiles, feed line |
| P2 | 25 | `#/plan/watering` @390 | as I1 | `ShotTimeline orientation="vertical"` |
| P3 | 26 | `#/zone/N` @390 | as S3 | Swipe charts |
| P4 | 27 | `#/settings/alerts?rule=new` @390 | as T1 | Stacked native selects |
| P5 | 28 | `#/equipment/feed-calibration` @390 | as E4 | Full-screen ring |
| X1 | 29 | — | not a page | — |

Shell: tree menu (Task 1), room tree (Task 7), top bar and palette (Task 30).

These routes stay routable but leave the tree menu:
- `history/grows`: linked as "Manage runs ›" from Compare.
- `history/drivers`
- `settings/features`: linked as "Capabilities ›" from System.
- `help`: linked as "What to do →" from CS codes.
- `today/ai`: opened from the header AI chip.

## Backend contract adopted (backend plan 4dc8f31e)

Every response service is called with `api: 2` and answers with the §5.1 envelope. Names and shapes are copied from the backend plan; the task numbers in brackets are backend tasks.

| Service | Request → `data` | Frontend tasks |
|---|---|---|
| `crop_steering/subscribe` (ws) | `{rooms?, kinds?}` → `{"type":"event","event":Event}` messages [5] | 4 |
| `journal_query` | `{room_id, since, until?, kinds?, zones?, actor?, limit≤500, cursor?}` → `{events, cursor}` [5] | 3, 4, 10, 15, 16, 28 |
| `timeline_get` | `{rooms[], start, end (≤48 h), zones?}` → rooms with `lights`, rows with `blocks {id, kind shot\|held\|queued\|planned\|alert, status done\|planned\|error\|warning, start, end, litres, metered_l, reason, phase, vwc_before, vwc_expected, requested_at, pump_wait_s, source, code, event_id, skippable, expected?}`, `errors{count, markers}`, `pump_load[{t,pct}]` [25] | 7, 9, 11 |
| `timeline_summary` | `{rooms[], days[≤14]}` → `{days:[{date, rooms:[{room_id, shots, failed, warnings, held, queued}]}]}` [25] | 11 |
| `history_changes` | `{room_id?, since, until?, zone?, key?, kinds?}` → `{changes:[{id, room_id, ts, actor, kind, key\|section, scope, old, new, reason, outcome, limits, revertible}]}` [24] | 18, 9 |
| `history_revert` | `{event_id, expected_revision?}` → `{reverted_event_id, new_event_id, readback}` [24] | 5, 18, every Undo |
| `supply_get` / `supply_save` | → `{revision, irrigation_pumps, water_sources, zone_groups, zone_meters, capacity_check{worst_case_lph, max_flow_lph, ok, suggest_max_concurrent}}`; error message prefix `pump_over_capacity:` [11] | 13, 22 |
| `timer_program_set/delete/list/preview`, `timer_skip` | §2.5 program (`type one_off\|recycle\|simple`, `duration_s`, `interval_min`, `frequency_per_day`, `start_at`, `window{kind,from,to}`, `sync_time`, `active`); preview → `{preview:[{zone, at, duration_s}], shots, total_s}`; list → `{programs:[… + next_at, zones_in_timer_mode]}, revision`; skip `{room_id, zone, at, expected_revision}` [14] | 11, 13 |
| `alert_rule_set/delete/test/preview/list`, `alert_ack` | preview `{rule, hours}` → `{summary_sentence, series, fires[{start, fired_at, end}], ignored[{start, end, reason}], count, min, max, sentence}`; list → rules + `{state, last_fired, firing_since, current_value, unit}`; test `send:true` → `delivery[{service, ok, error}]`; push kind `sensors` [16, 27] | 25, 27 |
| `calibration_start/capture/commit/revert` | start → `{session_id, raw_entity_id, temperature_entity_id, dosing_paused, expires_at}`; capture `{session_id, point, force?}` → `{reading, raw, stable, drift, stable_s}`; commit → `{slope_pct, offset, verdict, applied}` [17] | 24 |
| `pump_precheck`, `pump_prime`, `pump_stop`, `pump_calibrate`, `pump_calibration_commit` | precheck → `{ok, blockers[{code, message}]}`; prime `seconds 1..30`; calibrate `seconds 5..120` → `{session_id, outcome}`; `ran_s` via `dosing_get.pumps[i].calibration_session`; commit `{room_id, session_id, measured_ml}` → `{ml_min, previous_ml_min, flow_entity_written}` [19, 20] | 23 |
| `probe_offset_set` | `{room_id, entity_id, expected_revision, offset?\|curve?\|match_handheld?}` → `{offset, corrected_now, fused_before, fused_after}` (writes on call) [21] | 19 |
| `preset_list/save/apply/delete`, `copy_config` | `{diff:[{target,key,old,new}], applied?:[{target,key,readback verified\|refused}]}` [22] | 14 |
| `dashboard_create` / `dashboard_list` | `{template facility_wall\|room_tablet\|dosing_station, rooms[], title?}` → `{url_path, title}`; list → `{dashboards[], templates[]}` [32] | 29 |
| `display_save` keys | `ec_unit`, `temp_unit`, `volume_unit`, `clock`, per room [33] | 5, 29 |
| `notify_get/save/test` | per recipient `quiet_hours{from,to}\|null`, `urgent_high_priority`; room `mutes`; `notify_test {services[]}` → `{results:[{service, sent, error}]}` [34] | 26 |
| `system_status_get` | `{controller, addon_version, ha_version, ai{model, calls_today, budget, pct_used}, card_version, heartbeat{beats[{at, missed, readback_ms}], interval_s}, rooms:[{room_id, pct_online, alerts_open, groups:[{kind, entities:[{entity_id, name, kind, zone, last_seen, last_change, ok, uptime_7d_pct}]}]}]}` [28] | 27 |
| Entities | `sensor.crop_steering_<px>alerts_open` (attr `alerts[{event_id, ts, code, title, zone, rule_id?, acknowledged}]`), `binary_sensor.<px>shot_queued` (per room, attr `queue[{zone, position, requested_at, priority}]`), `sensor.<px>pump_load_pct`, `zone_N_flow_ratio` (0–1), `projection_app` (attr `intents`), `grow_day`, `days_to_harvest`, `stage`, `feed_ph_corrected`/`feed_ec_corrected`, `binary_sensor.<px>calibration_due`, `select.<px>zone_N_irrigation_mode`, `binary_sensor.crop_steering_rule_<id>`, `sensor.crop_steering_system_health` | many |

Not shipped by the backend, so not used: `intent_submit`, `dosing_mode` / `inline_status` (G12) and `scale_hints` (G13).

---

## File structure (new files)

```
frontend/src/
  lib/nav-tree.ts, components/nav-tree.tsx(.css)              Task 1
  pages/{watering,timers,changes,pump-calibration,feed-calibration,alert-rules,system}.tsx  stubs (Task 1)
  lib/parity-types.ts, lib/parity-api.ts, lib/parity-demo.ts,
  lib/parity-demo/journal.ts, lib/test-helpers.ts,
  components/needs-integration.tsx                              Task 3
  lib/events.ts                                                 Task 4
  lib/drafts.ts, lib/undo.ts, lib/time.ts, lib/display-units.ts,
  components/review-apply.tsx(.css)                             Task 5
  components/primitives/{arc-gauge,ring,capacity-bar,step-rail,hold-button,sentence}.tsx,
  lib/wake-lock.ts                                              Task 6
  lib/shot-timeline.ts, components/shot-timeline.tsx(.css), lib/open-alerts.ts   Task 7
frontend/scripts/parity-harness.mjs, verify-parity-*.mjs        Task 2 + page tasks
```

---

### Task 1: Tree menu, new routes and per-page stubs

**Files:**
- Create:
  - `frontend/src/lib/nav-tree.ts`
  - `frontend/src/components/nav-tree.tsx`, `nav-tree.css`
  - `frontend/src/pages/placeholder.tsx`
  - stubs `frontend/src/pages/{watering,timers,changes,pump-calibration,feed-calibration,alert-rules,system}.tsx`
- Rename: `frontend/src/pages/timeline.tsx` → `frontend/src/pages/explorer.tsx` (and its `.css`). The export becomes `Explorer`; the body is unchanged.
- Modify:
  - `frontend/src/lib/routes.ts`
  - `frontend/src/components/page-tabs.tsx`, `page-tabs.css`
  - `frontend/src/App.tsx`: sidebar uses `NavTree`; the render chain imports every stub and `Explorer`; the `Reservoir` import is dropped, since `equipment/feed` becomes a redirect
  - `frontend/scripts/verify-navigation.mjs`
  - `frontend/scripts/verify-dashboard.mjs` (nav selectors and the timeline route only)
- Test: `frontend/src/lib/nav-tree.test.ts`, `frontend/src/lib/routes.test.ts`

**Interfaces:**
- Produces:
  - **Pages.** New `Page` ids: `plan/watering`, `plan/timers`, `history/explorer`, `history/changes`, `equipment/pump-calibration`, `equipment/feed-calibration`, `settings/alerts`, `settings/system`. Removed: `history/timeline` and `equipment/feed`, both now `LEGACY_PAGES` redirects.
  - **Stubs.** Each stub exports its final component name with the props every page gets (`{controller, navigate, onDirtyChange}`) and renders `<Placeholder title=…/>`:
    - `Watering`, `Timers`, `Changes`, `PumpCalibration`, `FeedCalibration`, `AlertRules`, `SystemStatus`.
    - The page tasks overwrite the body and keep the export.
  - **Tree model:**
    - `export interface NavSection { section: Section; label: string; icon: LucideIcon; items: { page: Page; label: string }[] }`
    - `export const NAV_TREE: readonly NavSection[]`
    - `export function readOpenSections(): Set<Section>` and `export function writeOpenSections(open: Set<Section>): void`, using localStorage key `crop-steering.nav-open`, each wrapped in try/catch.
  - **Tree component:** `export function NavTree(props: { page: Page; navigate: (page: Page) => void }): JSX.Element`. Each section button carries `data-nav-section="<section>"`; each link carries `data-nav-page="<page>"`.

**Tree contents.** Order and labels are exact. 20 items: Status 1, Irrigation 4, History 4, Equipment 6, Settings 5.
- Status ▸ All rooms
- Irrigation ▸ Timeline · Current day · Timer programs · Grow plan & presets
- History ▸ Explorer · Water & flow · Compare runs · Changes
- Equipment ▸ Probes & offsets · Feed & dosing · Stock · Pump calibration · Feed pH/EC calibration · Setup: pumps & valves
- Settings ▸ Alert rules · Notifications · System status · AI assistant · Dashboards & display (`settings`)

**Route rules:**
- `TABS` mirrors `NAV_TREE` (phone in-page tabs).
- `SECTION_PAGES`:
  - `plan` → `plan/watering`
  - `history` → `history/explorer`
  - `equipment` → `equipment/probes`
  - `settings` → `settings/alerts`
- `LEGACY_PAGES` adds `history/timeline` → `history/explorer` and `equipment/feed` → `equipment/dosing`. It also repoints `equipment/tank`, `activity`, `log` and `logs`.
- Zone focus (`?zone=`) applies to `plan/targets`, `plan/schedule` and `history/explorer`.

- [ ] **Step 1: Write the failing tests**

```ts
test("tree lists every sub-page once in menu order", () => {
  expect(NAV_TREE.map((s) => s.label)).toEqual(["Status","Irrigation","History","Equipment","Settings"]);
  const pages = NAV_TREE.flatMap((s) => s.items.map((i) => i.page));
  expect(pages).toHaveLength(20);
  expect(new Set(pages).size).toBe(20);
});
test("open state survives a throwing localStorage", () => {
  vi.stubGlobal("localStorage", { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } });
  expect(readOpenSections()).toEqual(new Set());
  expect(() => writeOpenSections(new Set(["plan"]))).not.toThrow();
});
test("current page's section renders open with aria-current", () => {
  const html = renderToStaticMarkup(createElement(NavTree, { page: "history/changes", navigate: () => {} }));
  expect(html).toMatch(/data-nav-section="history"[^>]*aria-expanded="true"|aria-expanded="true"[^>]*data-nav-section="history"/);
  expect(html).toMatch(/data-nav-section="equipment"[^>]*aria-expanded="false"|aria-expanded="false"[^>]*data-nav-section="equipment"/);
  expect(html).toMatch(/data-nav-page="history\/changes"[^>]*aria-current="page"|aria-current="page"[^>]*data-nav-page="history\/changes"/);
});
test("old addresses land on their new homes", () => {
  expect(canonicalHash("#/history/timeline?zone=2")).toBe("#/history/explorer?zone=2");
  expect(parseRoute("#/equipment/feed").route.page).toBe("equipment/dosing");
  expect(parseRoute("#/plan").route.page).toBe("plan/watering");
});
test("every tree page has a component in App's render chain", () => {
  for (const s of NAV_TREE) for (const i of s.items) expect(RENDERED_PAGES).toContain(i.page);
});
```

`RENDERED_PAGES` is a `readonly Page[]` exported from `lib/routes.ts`. `App.tsx` switches on it, so this test catches a page with no component.

- [ ] **Step 2: Run** `node node_modules/vitest/vitest.mjs run src/lib/nav-tree.test.ts src/lib/routes.test.ts` → FAIL.
- [ ] **Step 3: Implement.**
  - Disclosure-nav pattern:
    - each section is a `<button aria-expanded aria-controls>` with a chevron;
    - each item is an `<a href={routeHash}>` link;
    - ↑/↓ move between visible items, Home/End go to the first/last, → opens a section, ← closes it or moves to its button.
  - Open set = the stored set ∪ the current page's section.
  - `RoomTree` stays below the tree.
  - Add `@media (min-width: 721px) { .page-tabs { display: none } }`. The bottom bar keeps 5 sections and targets `SECTION_PAGES`.
- [ ] **Step 4: Convert `verify-navigation.mjs`** to serve `frontend/dist/index.html` on an ephemeral 127.0.0.1 port, instead of `DASHBOARD_URL`. It asserts:
  - the tree;
  - clicking "Changes" sets `aria-current` and `#/history/changes`;
  - after a reload, History is still open;
  - `.page-tabs` is hidden at 1440 px and visible at 390 px;
  - the bottom bar has 5 buttons;
  - axe passes on `nav[aria-label="Main navigation"]`.

  Also update `verify-dashboard.mjs`: its nav selectors, and timeline route `#/history/explorer`.
- [ ] **Step 5: Run** tsc, vitest, then `node node_modules/vite/bin/vite.js build && node scripts/verify-navigation.mjs` → exit 0. Commit `feat(frontend): tree menu with every sub-page`.

### Task 2: Browser harness and mockup compare

**Files:**
- Create: `frontend/scripts/parity-harness.mjs`, `frontend/scripts/verify-parity-harness.mjs`

**Interfaces:**
- Produces: `export async function runParity({ id, route, mockup, phoneMockup?, check }: { id: string; route: string; mockup: string; phoneMockup?: string; check: (page: Page, ctx: { width: number; backend: "3.18" | "3.17"; region(name: string): void }) => Promise<void> }): Promise<void>`

**What `runParity` does:**
- Serves `frontend/dist/index.html` on an ephemeral port.
- Runs every combination of:
  - viewport `[1440×1000, 390×844]` at `deviceScaleFactor: 2`;
  - backend `["3.18","3.17"]`, opening `?demo=1[&backend=3.17]#<route>`.
- During each run it:
  - collects `pageerror`;
  - aborts and records off-origin and `/api/` requests;
  - runs `check`;
  - asserts `document.documentElement.scrollWidth <= innerWidth + 1`;
  - runs axe on `main`, which must report no violations;
  - takes a screenshot.
- Writes `output/playwright/parity/<id>-compare.html` (screenshot beside its mockup) and `<id>-compare.json`, shaped `{id, mockup, shots:[{width, backend, file, w, h}], regions:[names passed to ctx.region]}`.
- Ends by asserting `errors` and `forbidden` are empty.
- Note: the `backend=3.17` pass becomes meaningful at Task 3, which adds the flag.

- [ ] **Step 1:** Write `verify-parity-harness.mjs`. It runs `runParity({id:"harness", route:"/all-zones", mockup:"02-S1-AllRooms.png", phoneMockup:"24-P1-AllRooms.png", check: async (p, c) => { await p.getByRole("navigation",{name:"Main navigation"}).waitFor(); c.region("main navigation"); }})`.
- [ ] **Step 2:** Run it → FAIL (module missing).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Build, then `node scripts/verify-parity-harness.mjs` → exit 0. The JSON lists `"main navigation"`.
- [ ] **Step 5:** Commit `test(frontend): parity browser harness`.

### Task 3: v2 client, missing-service detection, demo fixtures

**Files:**
- Create:
  - `frontend/src/lib/parity-types.ts`
  - `frontend/src/lib/parity-api.ts`
  - `frontend/src/lib/parity-demo.ts`
  - `frontend/src/lib/parity-demo/journal.ts`
  - `frontend/src/lib/test-helpers.ts`
  - `frontend/src/components/needs-integration.tsx`
- Modify:
  - `frontend/src/lib/operator-types.ts` (`OperatorAction |= ParityAction`)
  - `frontend/src/lib/client.ts:189-238` (allowed list += `PARITY_ACTIONS`)
  - `frontend/src/lib/use-controller.ts:494-520`: room-scoped prefixes; read actions are kept out of the `writing` lock: `journal_query`, `timeline_get`, `timeline_summary`, `history_changes`, `supply_get`, `timer_program_list`, `timer_program_preview`, `alert_rule_list`, `alert_rule_preview`, `alert_rule_test` without send, `pump_precheck`, `preset_list`, `dashboard_list`, `system_status_get`
  - `frontend/src/lib/operator-demo.ts` (delegate to `parityDemo`)
  - `frontend/src/lib/demo.ts` (`?backend=3.17`)
- Test: `frontend/src/lib/parity-api.test.ts`

**Interfaces:**
- Produces:
  - `export const PARITY_MIN_VERSION = "3.18.0"`
  - `export const PARITY_ACTIONS = ["journal_query","timeline_get","timeline_summary","history_changes","history_revert","supply_get","supply_save","pump_precheck","pump_prime","pump_stop","pump_calibrate","pump_calibration_commit","calibration_start","calibration_capture","calibration_commit","calibration_revert","probe_offset_set","alert_rule_set","alert_rule_delete","alert_rule_test","alert_rule_preview","alert_rule_list","alert_ack","timer_program_set","timer_program_delete","timer_program_list","timer_program_preview","timer_skip","preset_list","preset_save","preset_apply","preset_delete","copy_config","dashboard_create","dashboard_list","system_status_get"] as const`. These are exactly the backend-shipped services.
  - `export type ParityAction = (typeof PARITY_ACTIONS)[number]`
  - `export type V2Outcome<T> = { kind: "ok"; data: T; revision: number | null; readback: { status: "verified" | "unverified"; at: string | null }; eventIds: string[] } | { kind: "missing" } | { kind: "error"; code: "stale_revision" | "invalid" | "forbidden" | "guard_refused" | "unavailable" | "unknown"; message: string; currentRevision?: number }`
  - `export function isMissingService(error: unknown): boolean`. It matches the `not_found`/`service_not_found` codes, "Service crop_steering.x not found", and client.ts's "needs the updated Crop Steering integration".
  - `export async function callV2<T>(controller: Controller, action: ParityAction | OperatorAction, data: Record<string, unknown>): Promise<V2Outcome<T>>`:
    - Sends `{...data, api: 2}`.
    - A v1-shaped answer (no `api: 2`) counts as `missing`.
    - It strips `client` and `proposal_token` from `data` before sending.
  - `export async function pagedQuery(controller: Controller, q: { room_id: string; since: string; until?: string; kinds?: string[]; zones?: number[] }, max = 5000): Promise<V2Outcome<{ events: CsEvent[] }>>`. Follows `cursor` with `limit: 500` until the cursor is empty or `max` events are read.
  - `export function useParity<T>(controller: Controller, action: ParityAction, data: Record<string, unknown> | null, deps: unknown[]): { state: "loading" | "ready" | "missing" | "error"; data: T | null; error: string | null; reload(): void }`
  - `export function NeedsIntegration(props: { feature: string; compact?: boolean }): JSX.Element`
  - `parity-types.ts`: one interface per row of "Backend contract adopted" (`TimelineGetData`, `TimelineSummary`, `HistoryChange`, `SupplyDoc`, `TimerProgram`, `AlertRule`, `AlertRuleListItem`, `AlertPreview`, `PresetDiff`, `SystemStatus`, `CalibrationSession`, `CaptureResult`, `PumpPrecheck`, `PumpCalibrationResult`, `DashboardList`, `CsEvent`), with exactly the backend field names.
  - `parity-demo.ts`:
    - `export interface DemoHandler { action: ParityAction; match?(data: Record<string, unknown>): boolean; answer(data: Record<string, unknown>, now: number): unknown }`
    - `export function parityDemo(action, data, now): Promise<unknown>`, which tries lane handlers (`import.meta.glob("./parity-demo/*.ts", {eager:true})` → each module's `handlers`, in file-name order), then a Task 3 default for every action.
    - With `?backend=3.17` every parity action rejects with the missing-service error.
  - `parity-demo/journal.ts` (owned by Task 3): a deterministic demo day per room covering `shot.started|completed`, `flow.reconciled`, `phase.changed`, `intent.queued|held`, `alert.raised|cleared`, `target.changed`, `config.changed`, `calibration.committed`, `ai.judgement|outcome` and `stock.refilled`. It answers `journal_query` by filter and cursor.
  - `test-helpers.ts`: `fakeController(overrides: Partial<Controller>): Controller` and `demoController(search: string): Controller`.

**`NeedsIntegration` copy:**
- Heading: **"Needs integration 3.18"**.
- Body: *"{feature} needs Crop Steering 3.18 or newer. Update the integration and the controller app together; the rest of this page keeps working."*
- `compact`: one line, with the body in an `InfoTip`.

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
test("callV2 never sends client or proposal_token", async () => {
  const op = vi.fn().mockResolvedValue({ api: 2, ok: true, data: {} });
  await callV2(fakeController({ operator: op }), "supply_save", { client: "mcp", proposal_token: "t", x: 1 });
  expect(op.mock.calls[0][1]).toEqual({ x: 1, api: 2 });
});
test("pagedQuery follows cursor until empty", async () => { /* 2 pages of 500 then empty -> 1000 events, 3 calls, each with room_id */ });
test("demo with backend=3.17 answers every parity action as missing", async () => {
  for (const a of PARITY_ACTIONS) expect((await callV2(demoController("?demo=1&backend=3.17"), a, {})).kind).toBe("missing");
});
test("demo 3.18 answers every parity action ok", async () => {
  for (const a of PARITY_ACTIONS) expect((await callV2(demoController("?demo=1"), a, {})).kind).toBe("ok");
});
test("journal fixture filters by kinds and pages by cursor", async () => { /* kinds:["shot.completed"] -> only that kind; limit 5 -> cursor set */ });
```

- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement. Fixture numbers follow the mockups (F2 "Flower · bulk" day 38 of 63; F1 "Flower · stretch" day 12; Veg in timer mode) on top of the existing demo rooms.
- [ ] **Step 4:** Run tsc and vitest → PASS.
- [ ] **Step 5:** Commit `feat(frontend): v2 service client with older-backend detection`.

### Task 4: Live event feed

**Files:**
- Create: `frontend/src/lib/events.ts`
- Modify:
  - `frontend/src/lib/use-controller.ts` (start beside `subscribeLive`, line 282)
  - `frontend/src/lib/types.ts:148`
- Test: `frontend/src/lib/events.test.ts`

**Interfaces:**
- Consumes: `LiveConnection.subscribeMessage`, `pagedQuery`, `whileVisible`
- Produces:
  - `export function startEventFeed(opts: { connection: LiveConnection | null; rooms: string[]; poll: (roomId: string, since: string) => Promise<CsEvent[]>; onEvents: (e: CsEvent[]) => void; visible: () => boolean }): () => void`
  - `Controller.recentEvents: readonly CsEvent[]`: a ring of 300 events, newest last, deduped on `id`. **It serves live deltas only.** History views call `pagedQuery` with `kinds` themselves.
  - `export function useCsEvents(controller: Controller, filter: (e: CsEvent) => boolean): CsEvent[]`

**Feed behaviour:**
- Subscribe with `{type:"crop_steering/subscribe", rooms, kinds?}`.
- On `unknown_command` (3.17), or with no connection, poll each room with `pagedQuery {room_id, since: lastTs}` every 30 s while visible.
- If `journal_query` is missing too, stop quietly.

- [ ] **Step 1: Write the failing tests**
  - `uses crop_steering/subscribe and polls only on unknown_command`
  - `dedupes on id`
  - `polls each room with room_id and its own last ts`
  - `does not poll while hidden and resumes when visible`
  - `stops when journal_query is missing`
  - `useCsEvents applies its filter` (via a pure `selectEvents(ring, filter)`)
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS.
- [ ] **Step 5:** Commit `feat(frontend): live crop_steering_event feed with poll fallback`.

### Task 5: Drafts, Review & apply, Undo, time and display units

**Files:**
- Create:
  - `frontend/src/lib/drafts.ts`
  - `frontend/src/lib/undo.ts`
  - `frontend/src/lib/time.ts`
  - `frontend/src/lib/display-units.ts`
  - `frontend/src/components/review-apply.tsx`, `review-apply.css`
- Modify: `frontend/src/App.tsx` (call `useDisplayUnits(controller)` once)

  This is the only `App.tsx` edit outside Tasks 1 and 30. Tasks 1–7 are serial, so it does not conflict.
- Test:
  - `frontend/src/lib/review-apply.test.ts`
  - `frontend/src/lib/time.test.ts`
  - `frontend/src/lib/display-units.test.ts`
  - `frontend/src/lib/drafts.test.ts`

**Interfaces:**
- Consumes: `V2Outcome`, `WriteResult` (`lib/types.ts:139`), `callV2("history_revert")`
- Produces:
  - **Drafts.** `export function useDraft<T>(key: string, saved: T, onDirtyChange?: (dirty: boolean) => void): { draft: T; set(next: T): void; dirty: boolean; discard(): void }`
    - Storage: sessionStorage `crop-steering.draft.<key>` plus `BroadcastChannel("crop-steering-drafts")`, both in try/catch.
    - Pages pass their `onDirtyChange` prop, which is the existing App dirty guard.
  - **Review rows and receipts.**
    - `export interface ReviewRow { id: string; label: string; before: string; after: string; note?: string; undo(): void }`
    - `export interface ApplyReceipt { at: number; ok: boolean; failed: { id: string; holds: string }[]; summary: string; by?: string; eventIds: string[] }`
    - `export function receiptFromWrite(result: WriteResult, rows: ReviewRow[], rowOf: (entityId: string) => string, holds: (entityId: string) => string, now: number): ApplyReceipt`
    - `export function receiptFromV2(outcome: V2Outcome<{ applied?: { target: string; key: string; readback: "verified" | "refused" }[] }>, rows: ReviewRow[], now: number): ApplyReceipt`. Rows whose `applied[].readback === "refused"` become `failed`. `readback.status !== "verified"` marks every row failed, with `holds` = `before`.
  - **`ReviewApply` component.** `export function ReviewApply(props: { rows: ReviewRow[]; layout: "bar" | "panel"; summary?: ReactNode; discardLabel?: string; checks?: { ok: boolean | "warn"; text: string }[]; consequence?: ReactNode; apply(): Promise<ApplyReceipt | Extract<V2Outcome<unknown>, { kind: "error" | "missing" }>>; onDiscard(): void; last?: ApplyReceipt | null; onReload?(): void; timeZone: string }): JSX.Element`
  - **Undo.**
    - `export function offerUndo(opts: { message: string; undo: () => Promise<void> }): void`. A sonner toast, `duration: 10_000`, with action label "Undo".
    - `export function revertEvents(controller: Controller, eventIds: string[]): Promise<void>`. Calls `history_revert` for each id, newest first. This is how every Undo works on 3.18. On 3.17 a page passes its own `undo` that re-writes the stored `before` values.
  - **Time.**
    - `export function clock(ms: number, tz: string): string`, honouring the 24/12 setting in the display-units store.
    - `export function dayKey(ms: number, tz: string): string`
    - `export function startOfDay(ms: number, tz: string): number`
    - `export function lightsWindow(dayStartMs: number, onHHMM: string, offHHMM: string, tz: string): { on: number; off: number }`. Wall-clock rule: it may cross midnight.
  - **Display units.**
    - `export type EcUnit = "mS/cm" | "ppm500" | "ppm700"`, `TempUnit = "C" | "F"`, `VolumeUnit = "L" | "gal"`, `ClockStyle = "24" | "12"`
    - `export function setDisplayUnits(u: Partial<DisplayUnits>): void` and `export function getDisplayUnits(): DisplayUnits`
    - `export function useDisplayUnits(controller: Controller): DisplayUnits`. Reads the selected room's display entity attributes `ec_unit`, `temp_unit`, `volume_unit` and `clock`, falling back to localStorage `crop-steering.units` on 3.17, and writes the store.
    - `export function formatEc(ms: number, sourceDigits: number): string`
    - `export function formatTemp(c: number, sourceDigits: number): string`
    - `export function formatVolume(l: number, sourceDigits: number): string`
    - `export function parseEc(text: string): number | null`

**`ReviewApply` copy:**
- Header: *"{n} change(s) · Review & apply"* with singular/plural (bar), or `summary` when given; or *"Review & apply"* + *"{n} unsaved change(s), not active until applied"* (panel).
- Buttons: **Apply {n} change(s)**, **{discardLabel ?? "Discard edits"}**, a per-row **Undo**.
- In flight: *Sending…* with a dashed underline.
- Receipt: *"Written and read back HH:MM"*, the summary, *"Controller confirmed every value · by {name}"*, and **Undo: write back the previous values**.
- Failure: *"Controller still holds {holds}. Nothing else was changed."* + **Try again**.
- Errors by code:
  - `stale_revision`: *"Someone else changed this at HH:MM. Reload their version and reapply your edits."* + **Reload**
  - `forbidden`: *"Only a Home Assistant administrator can change this."*
  - `guard_refused`: *"The controller refused: {message}"*
  - missing: `NeedsIntegration compact`
- Phone: the bar becomes a "Review {n} change(s)" button that opens a bottom `<dialog>`.

- [ ] **Step 1: Write the failing tests**
  - `receipt says written and read back with zone clock` (Pacific/Auckland, 14:02)
  - `partial apply keeps failed rows in the draft`, covering both the `receiptFromWrite` failed entry and the `receiptFromV2` `readback:"refused"` → `Controller still holds 57%. Nothing else was changed.`, `Try again`, and no receipt
  - `stale_revision keeps draft and offers reload`
  - `forbidden error shows admin copy`
  - `Apply button names the count`: 2 → `Apply 2 changes`; 1 → `Apply 1 change` and `1 change · Review & apply`
  - `discardLabel and summary override the defaults`
  - `useDraft persists to sessionStorage and survives a throwing storage` (pure `draftStore` helpers)
  - `offerUndo calls sonner with a 10 s Undo action` (`vi.mock("sonner")`)
  - `revertEvents calls history_revert newest first`
  - Time:
    - `lightsWindow 06:00–18:00 on 2026-09-27 Pacific/Auckland is 12 h`
    - `lightsWindow 20:00–08:00 from 26 Sep crossing the NZ spring-forward is 11 h of real time` (matches backend Task 1)
    - `clock 14:02 in 24 h and 2:02 pm in 12 h`
  - Units:
    - `formatEc 2.4 → 1200 ppm (500 scale), 1680 ppm (700 scale)`
    - `formatTemp 21.4 C → 70.5 °F`
    - `formatVolume 24.8 L → 6.6 gal`
    - `parseEc(formatEc(2.4, ppm500)) === 2.4`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS.
- [ ] **Step 5:** Commit `feat(frontend): review & apply with read-back, undo, zoned time and display units`.

### Task 6: Visual primitives, sentence builder, Wake Lock

**Files:**
- Create:
  - `frontend/src/components/primitives/{arc-gauge,ring,capacity-bar,step-rail,hold-button,sentence}.tsx`
  - `frontend/src/components/primitives/primitives.css`
  - `frontend/src/lib/wake-lock.ts`
- Test: `frontend/src/lib/primitives.test.ts`

Reuse what exists: `Gauge`, `MiniGauge`, `ZoneSlab`, `FeedTankDrawing`, `StockBottle`, `Sparkline`, `Meter`.

**Interfaces:**
- Produces:
  - **`ArcGauge`.** `ArcGauge({ value, min, max, band: [number, number], tone: "ok" | "warn" | "bad", label: string, unit?: string })`. SVG with `role="img"`, `aria-label`, and `data-angle` (integer degrees).
  - **`HealthRing`.** `HealthRing({ pct, label })`
  - **`StabilityRing`.**
    - `StabilityRing({ value: string, caption: string, state: "settling" | "steady" | "offline", progress: number })`. Animates only under `prefers-reduced-motion: no-preference`.
    - The live reading is announced through `announceThrottle(nowMs)`, which is exported: at most one announcement every 5 s, plus one on reaching "Steady".
  - **`CapacityBar`.** `CapacityBar({ segments: { id: string; label: string; lph: number; tone: string }[]; capacityLph: number; caption: string })`. Overflow is hatched with ▲; `role="img"`, `aria-label={caption}`. Layout only, no verdicts.
  - **`StepRail`.** `StepRail({ steps: { title: string; detail: string }[]; current: number; compact?: boolean })`. Sets `data-current` and moves focus to the step heading.
  - **`HoldButton`.**
    - `HoldButton({ mode: "while-held" | "hold-to-confirm"; label: string; srLabel: string; maxSeconds: number; confirmMs?: number; disabledReason?: string; onStart(): void; onStop?(): void })`
    - The logic is exported as `holdController({mode, maxSeconds, confirmMs = 1500, onStart, onStop})`.
    - `while-held`: `onStart` fires on press, and `onStop` fires on release, on `pointercancel`, on `visibilitychange` (hidden) or at `maxSeconds`.
    - `hold-to-confirm`: `onStart` fires once after `confirmMs` of continuous hold. Releasing earlier cancels it.
    - Uses Pointer Events with `setPointerCapture`. Space works for keyboard users. At least 64 px tall on phone. `navigator.vibrate?.(30)`.
  - **Sentence builder.**
    - `export type SentenceToken = { id: string; kind: "select"; label: string; value: string; options: { value: string; label: string }[]; onChange(v: string): void } | { id: string; kind: "number"; label: string; value: number; unit?: string; min: number; max: number; step: number; onChange(v: number): void } | { id: string; kind: "time"; label: string; value: string; onChange(v: string): void } | { id: string; kind: "static"; label: string; text: string; href?: string }`
    - `export function Sentence({ parts, phone, ariaLabel }: { parts: (string | SentenceToken)[]; phone: boolean; ariaLabel: string }): JSX.Element`
    - On desktop the tokens sit inline as Popover listboxes and inputs. On phone they stack as label + native `<select>`/`<input>`. **Tasks 13 and 25 both use this one component.**
  - **Wake Lock.** `export function useWakeLock(active: boolean): { supported: boolean }`. Re-acquired on `visibilitychange`; a no-op when unsupported.

- [ ] **Step 1: Write the failing tests**
  - `CapacityBar marks overflow with hatch and triangle` (1062 against 900)
  - `ArcGauge data-angle 33 for 62 in 40..160`
  - `HealthRing renders pct and label`
  - `StepRail marks current step` (`data-current="2"`)
  - `announceThrottle allows one announcement per 5 s`
  - `hold releases on visibility hidden` (while-held → `onStop` once)
  - `while-held stops at maxSeconds`
  - `hold-to-confirm fires after 1.5 s and not on a short tap`
  - `HoldButton disabled shows reason`
  - `Sentence renders selects inline on desktop and labelled native selects on phone`
  - `useWakeLock reports unsupported without navigator.wakeLock` (via pure `wakeLockSupported(nav)`)
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS.
- [ ] **Step 5:** Commit `feat(frontend): primitives, shared sentence builder and wake lock`.

### Task 7: ShotTimeline, open alerts, room tree

**Files:**
- Create:
  - `frontend/src/lib/shot-timeline.ts`
  - `frontend/src/components/shot-timeline.tsx`, `shot-timeline.css`
  - `frontend/src/lib/open-alerts.ts`
- Modify: `frontend/src/components/room-tree.tsx`, `frontend/src/lib/facility.ts`
- Test:
  - `frontend/src/lib/shot-timeline.test.ts`
  - `frontend/src/lib/open-alerts.test.ts`
  - `frontend/src/lib/room-tree.test.ts`

**Interfaces:**
- Consumes: `TimelineGetData`, `clock`, `lightsWindow`
- Produces:
  - **Timeline types.**
    - `export type BlockGlyph = "done" | "planned" | "expected" | "failed" | "warning" | "queued"`
    - `export interface TimelineBlock { id: string; glyph: BlockGlyph; start: number; end: number; requestedAt: number | null; pumpWaitS: number | null; litres: number | null; meteredL: number | null; litresPerPlant: number | null; reason: string | null; phase: string | null; vwcBefore: number | null; vwcExpected: number | null; source: string; code: string | null; eventId: string | null; skippable: boolean; zone: number; roomId: string }`
    - `export interface TimelineRow { key: string; roomId: string; zone: number | null; label: string; sublabel: string; blocks: TimelineBlock[]; lights: { on: number; off: number }[]; tone?: "warn" | "bad" }`
  - **Mapping.** `export function toTimelineRows(data: TimelineGetData, plantsByZone: Record<string, number>, rooms: { id: string; name: string; stage: string; day: number | null }[]): TimelineRow[]`. Glyph rules:
    - `expected === true` → `expected`
    - `kind:"planned"` → `planned`
    - `kind:"shot" & status:"done"` → `done`
    - `kind:"held"` or `status:"error"` → `failed`
    - `status:"warning"` or `kind:"alert"` → `warning`
    - `kind:"queued"` → `queued`
  - **Placement and keys.**
    - `export function place(block: TimelineBlock, span: { start: number; end: number }): { offsetPct: number; sizePct: number }`
    - `export function nextFocus(rows: TimelineRow[], current: { row: number; block: number }, key: "ArrowLeft" | "ArrowRight" | "ArrowUp" | "ArrowDown" | "Home", now: number): { row: number; block: number }`
  - **Component.** `export function ShotTimeline(props: { rows: TimelineRow[]; span: { start: number; end: number }; now: number; mode: "full" | "preview" | "strip"; orientation?: "horizontal" | "vertical"; timeZone: string; stale?: boolean; onBlock?(b: TimelineBlock, anchor: HTMLElement): void; focusIds?: string[]; collapsedRooms?: Set<string>; onToggleRoom?(roomId: string): void }): JSX.Element`. `strip` is a mode this plan adds beyond the UX spec's `full|preview`.
  - **Open alerts.**
    - `export interface OpenAlert { eventId: string | null; roomId: string; zone: number | null; code: string | null; title: string; ruleId: string | null; at: number }`
    - `export function openAlerts(controller: Controller): OpenAlert[]`. Reads `sensor.crop_steering_<px>alerts_open` attr `alerts`. On 3.17 it falls back to the existing CS-code attention selector (`lib/attention.ts`).
    - **The room-tree flag, zone problems (Task 8), the timeline failed chip (Task 11) and the System cards (Task 27) all use it.**
  - **`RoomTree` additions.**
    - Prop `pick?: { title: string; selected: Set<string>; onChange(next: Set<string>): void; onDone(): void; onCancel(): void } | null`.
    - On desktop: checkboxes, **Done** / **Cancel** at the foot, and `inert` on `<main>`.
    - Below 721 px: the same tree inside a bottom `<dialog>`.
    - Zone rows show a phase badge, or `T` when `irrigation_mode` is `timer`, plus VWC. Room rows show a state word and a `warn` flag from `openAlerts`.

**ShotTimeline rendering:**
- Layout: a CSS grid with `subgrid` and a 180 px fallback label column. Lights-on is a band; a "Now HH:MM" line marks the present.
- Blocks are `<button>`s labelled with a sentence (*"F2 zone 3, 10:40, 2.4 litres, done."*).
- Keyboard: roving tabindex via `nextFocus`.
- Size: bar height is proportional to litres per plant ("Bar height = water per plant").
- When `stale`, future blocks are hatched.
- Container queries shorten labels below 480 px.
- `vertical` orientation:
  - time runs down and rooms become columns;
  - the track scrolls sideways with snap points;
  - width is proportional to water ("Width = water").

- [ ] **Step 1: Write the failing tests**
  - Glyph mapping:
    - `maps expected:true to expected regardless of source`
    - `maps held and error to failed, alert to warning`
  - Placement and keys:
    - `place clamps blocks crossing the span edge`
    - `queued block keeps requestedAt and pumpWaitS`
    - `nextFocus moves right within a row, down across rows, Home to nearest now`
  - Rendering:
    - `block buttons carry the spoken sentence`
    - `stale hatches only future blocks`
    - `vertical orientation labels width as water`
  - Open alerts and room tree:
    - `openAlerts reads alerts_open and falls back to CS attention on 3.17`
    - `room tree pick mode renders checkboxes and Done`
    - `pick mode on phone renders a dialog`
    - `timer-mode zone shows T badge`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. Build, then `node scripts/verify-navigation.mjs` → passes.
- [ ] **Step 5:** Commit `feat(frontend): ShotTimeline, open-alerts selector, room tree badges and pick mode`.

---

### Task 8: S1 All rooms (+ P1)

**Files:**
- Modify: `frontend/src/pages/all-zones.tsx`, `all-zones.css`, `frontend/src/lib/facility-view.ts:109-147`
- Create: `frontend/src/lib/parity-demo/status.ts`, `frontend/scripts/verify-parity-s1.mjs`
- Test: `frontend/src/lib/all-zones.test.ts`

**Interfaces:**
- Consumes: `facilityView`, `ZoneSlab`, `FeedTankDrawing`, `StockBottle` (unchanged props), `openAlerts`, `formatEc`
- Produces:
  - `FacilityZone` adds:
    - `queued: { position: number } | null`, from the room's `binary_sensor.crop_steering_<px>shot_queued` attr `queue[]`, matched by zone;
    - `flowRatio: number | null`, from `zone_N_flow_ratio`, on the 0–1 scale;
    - `lastShotHollow: boolean`, true when `flowRatio < 0.8`;
    - `problem: string | null`, from `openAlerts`, else the existing reading issue.
  - `FacilityRoom` adds `growDay: { day: number; of: number; daysLeft: number; stage: string } | null`, read from `grow_day`, `days_to_harvest` and `stage`, falling back to today's computation. It also adds `feedCalibrationDue: boolean`.

**Delta to mockup 02 (all copy exact):**
- Header line: *"Day 38 of 63 · 25 days left"*.
- Drink line: *"Drunk today 0.21 L per plant · 24.8 L room"*.
- Zone chips: *Watering now* / *Automated* / *Paused* (hatched).
- Queued zone: *"Waiting for the pump — 2nd in line"*.
- Short-flow zone: *"Last shot: 1.9 of 2.4 L arrived (79%)"*.
- Problems sit on their card.
- FEED TANK line *"pH 5.84 · EC 2.4 · 19.8°"*, with a due flag on the pH.
- STOCK bottles.
- P1: 3-up tiles plus *"Feed 68% · 310 L · pH 5.84 · EC 2.4"* and *"Part B low"*.

- [ ] **Step 1: Write the failing tests**
  - `grow day prefers the room entities`
  - `falls back to computed day when grow entities absent`
  - `queued position comes from the room queue attribute`
  - `flow ratio 0.79 marks last shot hollow and builds the arrived sentence`
  - `problem comes from openAlerts for that zone`
  - `feed calibration due flag from binary_sensor calibration_due`
  - `drink line uses formatVolume`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. Write `verify-parity-s1.mjs` (mockups 02 and 24). It asserts:
  - room headings;
  - each zone card links to `#/zone/N`;
  - the problem text sits inside its zone card;
  - the queued line is on the queued zone;
  - on 3.17, no "Needs integration".

  Regions: header, zone cards, feed tank, stock. Build, run → exit 0, then compare.
- [ ] **Step 5:** Commit `feat(frontend): all rooms shows queue, flow and grow-day in place`.

### Task 9: S2 Room

**Files:**
- Modify: `frontend/src/pages/today.tsx`, `today.css`
- Create: `frontend/src/lib/today-room.ts`, `frontend/scripts/verify-parity-s2.mjs`
- Test: `frontend/src/lib/today-room.test.ts`

**Interfaces:**
- Consumes: `ShotTimeline mode="strip"`, `useParity("timeline_get", {rooms:[roomId], start, end})`, `toTimelineRows`, `zoneSensors`, `openAlerts`, `offerUndo`
- Produces:
  - `export function roomZoneRows(controller: Controller, now: number): { zone: number; drink: { ml: number; median: number }; gauges: GaugeModel[]; sensors: ZoneSensor[]; paused: { by: string | null; at: number; why: string | null } | null }[]`
  - `export function personName(states: States, userId: string | null): string | null`: the `person.*` entity whose `user_id` attribute matches, else `null`.

**Delta to mockup 03:**
- Header: *"F1 Holding · Flower stretch · 120 plants in 3 zones"*, *"Day 12 of 63 · 51 days left · harvest 11 Dec"*, the *"Stretch ends day 21"* marker, *"Water today 12.7 L room · 0.16 L per watered plant"* and *"Lights On 10:00 – 22:00"*.
- Today strip: *Shot done · Planned · Lights on* + **Open full timeline →**. On 3.17 it shows `NeedsIntegration compact feature="Today's watering strip"`.
- Zone rows:
  - gauges *"target …"*;
  - *"+1 mL vs median 160 mL"*;
  - Sensors column;
  - silent-sensor card *"Last heard 11:08. Left out: the zone reads the front sensor only."* + **Check back probe →**.
- Paused zone: *"Paused by Ben at 09:52 (slab change)."*, or *"Paused at 09:52."* when no name is found, + **Resume zone 3**. Resume writes the zone switch and offers Undo, which writes it back.
- Removed: the HMI table duplicate and the "AI assistant changes today" block.

- [ ] **Step 1: Write the failing tests**
  - `paused zone row names who and when`
  - `paused zone without a person shows time only`
  - `drink delta against median is signed`
  - `sensor row carries silent-since text`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-s2.mjs` (route `/today`, mockup 03) asserts:
  - the strip has 3 rows;
  - **Resume zone 3** shows a toast, and **Undo** puts the zone back to Paused;
  - on 3.17 the note sits inside the strip region.
- [ ] **Step 5:** Commit `feat(frontend): room page with today strip and sensors in place`.

### Task 10: S3 Zone (+ P3)

**Files:**
- Modify: `frontend/src/pages/zone.tsx`, `zone.css`, `frontend/src/components/day-timeline.tsx` (the `ZoneDay` component: `compare` prop only)
- Create: `frontend/src/lib/zone-shot-log.ts`, `frontend/scripts/verify-parity-s3.mjs`
- Test: `frontend/src/lib/zone-shot-log.test.ts`

**Interfaces:**
- Consumes:
  - `pagedQuery({room_id, since: lightsOn, kinds:["shot.completed"], zones:[zone]})` on 3.18;
  - on 3.17, the existing `shot_log_app` attribute;
  - `controller.history` (zone VWC series);
  - `runs_get` and `historyWindow` (last run, same day);
  - `OverlayRows`, `overlay_keep`/`overlay_undo`
- Produces:
  - `export function shotLog(events: CsEvent[], zone: number, dayStart: number, plants: number): { at: number; phase: string; mlPerPlant: number; seconds: number; vwcBefore: number | null }[]`
  - `export function vwcAfter(series: { t: number; v: number }[], shotEnd: number, settleMs = 300_000): number | null`. The reading closest to `shotEnd + settle` from the recorder series. **No `vwc_after` field is assumed on the event.**
  - `ZoneDay` prop `compare?: "off" | "yesterday" | "last-run"`

**Delta to mockup 04:**
- Header facts.
- VWC chart with *"Compare with Off · Yesterday · Last run, day 38"*.
- Pore EC chart with an in-place AI suggestion: **Apply** → `overlay_keep` + Undo (`overlay_undo`); **Dismiss**.
- *WHY / NEXT ACTION*.
- *SHOT LOG · TODAY*, rows shaped "13:05 P2 33 mL · 52 s 58.0 → 60.8", with **History →**.
- P3: snap-scrolling charts, *"Swipe: VWC · Pore EC"*.

- [ ] **Step 1: Write the failing tests**
  - `shot log keeps only this zone's completed shots since lights-on, newest first`
  - `shot log converts litres to mL per plant`
  - `vwcAfter picks the reading nearest five minutes after the shot`
  - `vwcAfter returns null without a reading inside 15 min`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-s3.mjs` (route `/zone/2`, mockups 04 and 26) asserts:
  - Compare "Yesterday" adds `[data-series="yesterday"]`;
  - **Apply** shows an Undo toast;
  - the shot log has at least 1 row on both backends;
  - on phone, a swipe moves to the Pore EC chart.
- [ ] **Step 5:** Commit `feat(frontend): zone page compare, in-place AI suggestion, shot log`.

### Task 11: I1 Watering timeline (+ P2)

**Files:**
- Modify: `frontend/src/pages/watering.tsx` (stub → page)
- Create: `frontend/src/pages/watering.css`, `frontend/src/lib/parity-demo/irrigation.ts`, `frontend/scripts/verify-parity-i1.mjs`
- Test: `frontend/src/lib/watering.test.ts`

**Interfaces:**
- Consumes:
  - `ShotTimeline`, `toTimelineRows`, `openAlerts`;
  - `useParity("timeline_get")` (≤ 48 h span);
  - `useParity("timeline_summary", {rooms, days})` for the date strip;
  - `callV2("timer_program_list", {})` for the per-room `revision`, which is reloaded on `stale_revision`;
  - `callV2("timer_skip", {room_id, zone, at, expected_revision})`;
  - `revertEvents` (Undo);
  - `useCsEvents` (`shot.*`, `intent.*`)
- Produces:
  - `export function wateringQuery(hash: string): { date: string; span: 12 | 24 | 48; rooms: string[]; stages: string[]; problemsOnly: boolean; q: string }` and `export function wateringHash(q): string`. Example URL: `#/plan/watering?date=2026-10-22&span=24&rooms=F1,F2&stages=flower&problems=1&q=z3`.
  - `export function defaultSpan(width: number): 12 | 24`
  - `export function dayChip(summary: TimelineSummary, date: string, rooms: string[], today: string): { label: string; tone: "done" | "problem" | "planned" }`. Labels: *"Done"*, *"1 problem"*, *"3 problems"* (failed + warnings), *"Planned"*.

**Layout to mockup 05:**
- Date strip, **Today**, **12 h · 24 h · 48 h**, chips, legend.
- Room rows with *"Lights on 06:00–18:00"*. Choosing a room in the room tree scrolls to that room's row and expands it.
- Popover (Radix):
  - *"Planned · waited 12 min for pump"* (from `pump_wait_s`);
  - the `reason` box;
  - rows *Water* (litres/plant, `litres`, `metered_l`), *VWC* (`vwc_before → vwc_expected`), *Source*;
  - rows whose fields are null are hidden.
  - **Open F2 Zone 3**.
  - **Skip this shot** only when `skippable`; it offers Undo via `revertEvents(eventIds)`.
  - **See what happened** on failed blocks.
- Failed chip *"{n} shots failed ›"* (from `errors.count`) cycles focus through the failed blocks.
- States:
  - Loading: skeletons.
  - Empty: *"No watering planned for this day."* + **Set up a timer**.
  - Error: *"Couldn't load the watering plan. Showing what we had at HH:MM."* + **Try again**.
  - Stale: hatching plus *"Live updates paused — reconnecting"*.
  - Missing: `NeedsIntegration feature="The watering timeline"`.
- Live: a matching event reloads after a 2 s debounce.
- P2: vertical; *"Timeline" / "All rooms · swipe for more"*; **12 h · 24 h**; *"Today, Thu 22 Oct" / "1 failed · 2 warnings"*.

- [ ] **Step 1: Write the failing tests**
  - `wateringQuery round-trips including rooms`
  - `default span is 24 on desktop and 12 on phone`
  - `dayChip counts failed plus warnings from timeline_summary`
  - `problemsOnly keeps rooms with a failed or warning block`
  - `skip uses the revision from timer_program_list`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-i1.mjs` (mockups 05 and 25) asserts:
  - 48 h updates the hash;
  - clicking a planned block opens the popover with "Skip this shot", which shows an Undo toast;
  - ←/→ moves focus between blocks;
  - the failed chip focuses a failed block;
  - on 3.17 the body note shows and the tree still works.
- [ ] **Step 5:** Commit `feat(frontend): irrigation watering timeline`.

### Task 12: I2 Current day

**Files:**
- Modify: `frontend/src/pages/strategy.tsx`, `frontend/src/pages/targets.css`, `frontend/scripts/verify-irrigation-workspace.mjs` (owner)
- Create: `frontend/src/lib/strategy-review.ts`, `frontend/scripts/verify-parity-i2.mjs`
- Test: `frontend/src/lib/strategy-review.test.ts`

**Interfaces:**
- Consumes:
  - `ReviewApply layout="bar"`, `useDraft("targets:<room>:<zone>", saved, onDirtyChange)`;
  - `applyChanges` → `receiptFromWrite`;
  - `revertEvents`, with the 3.17 fallback re-writing `before`;
  - `projection_app` intents (Saved);
  - the existing `buildSetpointPreview` (`lib/setpoint-preview.ts:88`) for With edits.
- Produces:
  - `export function targetRows(drafts: Drafts, states: States, zone: number): ReviewRow[]`. Notes use `setting-words.ts`, for example *"-1.0 pts · P2 waters when VWC falls to this"*.
  - `export function afternoon(saved: ProjectionIntent[], edited: SetpointCurveState, from: number, to: number): { saved: { shots: number; lPerPlant: number }; edited: { shots: number; lPerPlant: number } }`

**Delta to mockup 06:**
- Header with *"Nothing is sent to the controller until you apply"*.
- Handles show *"was 57% · not applied"*.
- *"This afternoon, 14:10–18:00"* compares Saved with With edits.
- `ReviewApply` bar (`discardLabel: "Discard edits"`).
- *LAST APPLIED* receipt with **Undo: write back the previous values**.

- [ ] **Step 1: Write the failing tests**
  - `targetRows lists only changed keys with signed delta note`
  - `afternoon counts saved projection shots and edited preview shots in the window`
  - `undo of last apply restores before values on 3.17` (spy `applyChanges`)
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-i2.mjs` (route `/plan/targets?zone=1`, mockup 06):
  - Press ArrowDown on the re-water handle → `1 change · Review & apply`.
  - **Apply 1 change** → `/Written and read back \d\d:\d\d/`.
  - **Undo: write back the previous values** → the value is restored.

  Then update and run `verify-irrigation-workspace.mjs`, which must pass.
- [ ] **Step 5:** Commit `feat(frontend): current day review & apply bar with read-back receipt`.

### Task 13: I3 Timer programs

**Files:**
- Modify: `frontend/src/pages/timers.tsx` (stub → page)
- Create: `frontend/src/pages/timers.css`, `frontend/src/lib/timers.ts`, `frontend/scripts/verify-parity-i3.mjs`
- Test: `frontend/src/lib/timers.test.ts`

**Interfaces:**
- Consumes:
  - `Sentence` (Task 6), `ShotTimeline mode="preview"`, `CapacityBar`, `ReviewApply`, `revertEvents`;
  - `callV2("timer_program_list" | "timer_program_preview" | "timer_program_set" | "timer_program_delete" | "supply_get")`;
  - `select.crop_steering_<px>zone_N_irrigation_mode` via `controller.write`;
  - the daily-max entity (existing `max_daily_volume` number).
- Produces:
  - `export const TIMER_TYPE_LABEL: Record<TimerProgram["type"], string> = { one_off: "One-off", recycle: "Recycle", simple: "Simple" }`
  - `export function timerTitle(p: TimerProgram, zoneNames: Record<string, string>): string`. These follow mockup 07, which differs from UX G7 (see Deviations):
    - *"Every 30 min for 2 min, 08:00–12:00, Veg zones 1–2"*
    - *"6 times a day for 90 s, while lights are on, Veg zone 2 (clones)"*
    - *"Once at 20:00 for 3 min, Fri 23 Oct, Veg zone 1 (mothers)"*
  - `export function timerTokens(draft: TimerProgram, set: (p: TimerProgram) => void, zones): (string | SentenceToken)[]`
  - `export function consequence(preview: { shots: number; total_s: number; preview: { zone: number; at: string; duration_s: number }[] }, lPerPlantPerSecond: Record<number, number>, dailyMaxL: number | null): string`. Examples:
    - *"8 shots · 16 min · about 1.2 L per plant."*
    - *"12 shots · 24 min · about 1.8 L per plant. Stops after shot 10: daily limit 1.5 L per plant."*
  - `export function fieldErrors(error: string | null): { field: string; message: string }[]`. Maps the server's *"End must be after start"* to the `end` field.

**Layout to mockup 07:**
- Program cards, *"On · next shot tomorrow 08:00"* (from `next_at`), and **New program**.
- Irrigation mode table. Steering is disabled with *"No probe, so steering is not offered."*
- Editor:
  - Type One-off / Recycle / Simple, plus *Zones*, *Amount*, *When* (All day / Lights on / Lights off / Custom → `window.kind`).
  - *Next 24 hours* from `timer_program_preview {room_id, program, hours:24}`. Debounced 250 ms; a draft is never saved to preview.
  - Cards: DAILY MAX PER ZONE, PUMP CAPACITY (from `supply_get.capacity_check` + `CapacityBar`), and SAME SAFETY AS STEERING.
- **Delete program** acts immediately with Undo (`revertEvents`). **Discard edits** and **Save** / **Saved** sit beside it.
- Server validation is shown beside its field, and the preview goes blank.
- Empty: *"No timer yet. Most mother rooms use 2 min every 2 h during lights-on."* + **Use that**.
- On 3.17: the whole page shows `NeedsIntegration feature="Timer programs"`.

- [ ] **Step 1: Write the failing tests**
  - `timerTitle matches the three mockup strings`
  - `type labels map one_off/recycle/simple`
  - `consequence names the daily-limit stop with consistent numbers`
  - `fieldErrors maps End must be after start to end`
  - `timerTokens editing interval_min updates the draft`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-i3.mjs` (mockup 07):
  - Change *Every* to 45 → the preview count changes.
  - **Save** goes through ReviewApply → *Saved*.
  - **Delete program** → Undo restores it.
  - Phone: the tokens are native selects.
  - 3.17: the note shows.
- [ ] **Step 5:** Commit `feat(frontend): timer programs with live preview`.

### Task 14: I4 Grow plan & presets

**Files:**
- Modify: `frontend/src/pages/grow-planner.tsx`, `grow-planner.css`, `frontend/scripts/verify-recipe-library.mjs` (owner; route `#/plan/schedule`)
- Create: `frontend/src/components/presets-panel.tsx`, `frontend/src/lib/presets.ts`, `frontend/scripts/verify-parity-i4.mjs`
- Test: `frontend/src/lib/presets.test.ts`

**Interfaces:**
- Consumes: `callV2("preset_list" | "preset_save" | "copy_config" | "preset_apply")`, `RoomTree pick`, `ReviewApply`, `receiptFromV2`, `revertEvents`, the existing `recipe-library`
- Produces:
  - `export function PresetsPanel(props: { controller: Controller; roomId: string; planName: string }): JSX.Element`
  - `export function diffRows(diff: { target: string; key: string; old: unknown; new: unknown }[], words): ReviewRow[]`

**Delta to mockup 08:**
- *"Armed · running"*; *"Draft · 2 edits, not live yet"* with **Discard draft** / **Arm at lights-on, Fri 06:00** (the existing arm flow).
- *"EXCEPTION · IN DRAFT"* card and **Add exception on day 40**.
- Presets panel:
  - *"Stored on the controller: the same list on every phone and PC"*.
  - Preset cards; **Save F2 plan as a new preset** (`preset_save {name, scope:"all", from:"room:f2_"}`).
  - *Copy "<name>" to room…*: pick mode (a dialog on phone), then a `copy_config {preview:true}` diff, then **Copy {n} changes to F1**.
  - That button applies immediately with read-back, shows a receipt, and offers Undo via `revertEvents`.
- The browser recipe library stays below, under *"On this browser"*. Browser recipes are **not** imported, because `preset_save` captures live values only.
- On 3.17: the panel shows `NeedsIntegration` and the browser library still works.

- [ ] **Step 1: Write the failing tests**
  - `diffRows renders old struck and new`
  - `refused readback row stays failed in the receipt`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-i4.mjs` (mockup 08): pick F1 → diff → **Copy … to F1** → receipt → Undo. Then update the route in `verify-recipe-library.mjs` and run it → passes.
- [ ] **Step 5:** Commit `feat(frontend): controller-stored presets and copy-to-room preview`.

### Task 15: H1 Explorer

**Files:**
- Modify: `frontend/src/pages/explorer.tsx` (renamed in Task 1), `explorer.css`, `frontend/src/components/history-explorer.tsx`, `frontend/src/lib/history-explorer.ts`
- Create: `frontend/src/lib/parity-demo/history.ts`, `frontend/scripts/verify-parity-h1.mjs`
- Test: `frontend/src/lib/history-explorer.test.ts` (extend)

**Interfaces:**
- Consumes:
  - `pagedQuery({room_id, since, until, kinds:["phase.changed","shot.completed","alert.raised","stock.refilled"]})`;
  - `projection_app`, `runs_get`, `historyWindow` (last run, same day), `timelineCsv`
- Produces:
  - `export function phaseLane(events: CsEvent[], span, projection: ProjectionIntent[] | null): { from: number; to: number; phase: string; planned: boolean }[]`
  - `export function chartNotes(events: CsEvent[], series: string[]): { at: number; series: string; text: string }[]`. Examples: *"Zone 2 over the band since 09:40"*, *"Refilled 06:10 · 40% to 74%"*.

**Delta to mockup 09:**
- Range *Today · 7 d · This run · Custom*.
- Series chips.
- PHASE and SHOTS lanes, notes in place, shared crosshair.
- *"Compare with last run (Run 14, same day 38)"*; **Export CSV · {n} series**.
- The setpoint-log section is removed; it lives in Changes.
- On 3.17: the lanes come from the phase entity history and `shot_log_app`, and the notes are hidden.

- [ ] **Step 1: Write the failing tests**
  - `phaseLane splits on phase.changed and marks projection planned`
  - `chartNotes reports band excursion start once`
  - `csv header counts selected series`
  - `7-day range uses pagedQuery` (spy, `kinds` passed)
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-h1.mjs` (route `/history/explorer`, mockup 09) asserts:
  - the Zone 3 VWC chip removes its line;
  - `/Export CSV · \d+ series/`;
  - `#/history/timeline` redirects here;
  - moving the mouse over a chart shows the time pill.
- [ ] **Step 5:** Commit `feat(frontend): history explorer with phase and shot lanes`.

### Task 16: H2 Water & flow

**Files:**
- Modify: `frontend/src/pages/water-use.tsx`
- Create: `frontend/src/pages/water-use.css`, `frontend/src/lib/flow-check.ts`, `frontend/scripts/verify-parity-h2.mjs`
- Test: `frontend/src/lib/flow-check.test.ts`

**Interfaces:**
- Consumes:
  - `pagedQuery({kinds:["flow.reconciled","shot.completed","alert.raised"]})`;
  - `zone_N_flow_ratio`;
  - `supply_get.zone_meters`;
  - `history_long` / `controller.history` on the mapped valve and meter entities (leak lanes);
  - `test_shot` (existing), `ArcGauge`, `HoldButton mode="hold-to-confirm"`
- Produces:
  - `export function zoneFlow(reconciled: CsEvent[], zone: number): { last3Pct: number | null; todayPct: number | null; shots: { at: number; askedL: number; meteredL: number }[]; verdict: "on_target" | "low" | "high" | "no_meter" }`.
    - It reads `flow.reconciled {ratio, commanded_l, metered_l}` as given. The percentages are the mean of `ratio × 100`.
    - The verdict boundaries 0.8 and 1.2 are the same ones the backend uses.
  - `export function leakIncidents(alerts: CsEvent[]): { at: number; title: string; litres: number | null }[]`. Taken from `alert.raised` with code `CS-319`.

**Layout to mockup 10:**
- Header *"Did the water reach the plants?"* + the meter line.
- Per zone: arc gauge; *"98% metered vs asked, last 3 shots"*; asked vs metered bars; 7-day line; chip *On target* / *Blocked line?*.
- Blocked card with **Run 30 s test shot on Zone 2** (hold-to-confirm → `test_shot`) and **Open catch test**. That link goes to the existing catch-test calculator (`components/zone-sizing.tsx`), opened from `#/equipment/setup`.
- *Leak check*: valve-open vs meter-flow lanes from recorder history; *"0.00 L in 14 h 05 min watched"*; 7-day dots from `leakIncidents`.
- *Water per plant* against the room median.
- No meter: *"Add a flow meter to prove water reached the plants."* + **Map a flow meter**.
- On 3.17: the existing WaterUsePanel under `NeedsIntegration feature="Metered flow check"`.

- [ ] **Step 1: Write the failing tests**
  - `zoneFlow last three ratios 0.62 → low and 62%`
  - `zoneFlow without reconciled events → no_meter`
  - `leakIncidents keeps only CS-319`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-h2.mjs` (mockup 10):
  - The blocked card sits inside Zone 2.
  - The gauge `aria-label` contains "62%".
  - A short tap on the test-shot button does nothing; a 1.5 s hold sends `test_shot` (recorded in demo).
  - 3.17: note + the estimate chart.
- [ ] **Step 5:** Commit `feat(frontend): water & flow check, metered vs asked`.

### Task 17: H3 Compare runs

**Files:**
- Modify: `frontend/src/pages/comparison.tsx`, `comparison-views.tsx`, `comparison-week-charts.tsx`, `frontend/src/lib/comparison.ts`
- Create: `frontend/scripts/verify-parity-h3.mjs`
- Test: `frontend/src/lib/comparison.test.ts` (extend)

**Interfaces:**
- Consumes: the existing comparison data and `runs_set_harvest`
- Produces:
  - `export const CALLOUT_FLOOR = { vwc: 0.5, dryback: 0.5, pore_ec: 0.2, water: 0.02 } as const`. Units: VWC pts, dryback pts, mS/cm, L per plant per day.
  - `export function runCallout(metric: keyof typeof CALLOUT_FLOOR, runs: ComparedRun[], stages: Stage[]): { text: string; box: { fromDay: number; toDay: number } } | null`

**Delta to mockup 11:**
- Run cards (*"Harvested 10 Aug · 41.2 kg dry · 515 g/m²"*, **Add harvest result**, *"Manage runs ›"*).
- *"Line runs up by"* (Day of flower / Day of run).
- Four small multiples, each with one callout (*"Run 13 sat 1.7 pts wetter than this run all through stretch."*).

- [ ] **Step 1: Write the failing tests**
  - `runCallout names run, delta at source precision and stage for each metric`
  - `runCallout returns null under each metric's floor`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-h3.mjs` (mockup 11): unticking Run 13 removes its lines and its callouts; **Add harvest result** opens the form.
- [ ] **Step 5:** Commit `feat(frontend): compare runs callouts and harvest cards`.

### Task 18: H4 Changes (+ setting clock popover)

**Files:**
- Modify: `frontend/src/pages/changes.tsx` (stub → page), `frontend/src/components/setting-row.tsx` (clock button)
- Create: `frontend/src/pages/changes.css`, `frontend/src/lib/changes.ts`, `frontend/src/components/setting-history.tsx`, `frontend/scripts/verify-parity-h4.mjs`
- Test: `frontend/src/lib/changes.test.ts`

**Interfaces:**
- Consumes:
  - `callV2("history_changes", {since, until?, kinds?, zone?})`, with no `room_id` for all rooms, or the tree's room;
  - `callV2("history_revert")`, `ReviewApply`, `offerUndo`;
  - `setpoint_log_get` (3.17)
- Produces:
  - `export const ACTOR_CHIP: Record<string, string> = { manual: "You", learner: "Learner", ai: "AI judge", timer: "Timer", plan: "Plan", mcp: "MCP", aigrow: "AiGrow", safety: "Safety", automation: "Automation", system: "Setup", engine: "Engine" }`
    - `manual` reads "You". The backend sends no `user_id`, so another person's manual edit also reads "You" until Backend asks item 3 lands.
  - `export interface ChangeEntry { id: string; at: number; actor: string; chip: string; roomId: string; kind: HistoryChange["kind"]; scope: string; label: string; before: string; after: string; reason: string | null; outcome: string | null; limits: string | null; revertible: boolean; revertLabel: string }`
  - `export function toEntries(changes: HistoryChange[], words): ChangeEntry[]`.
    - `revertLabel` copy: *"Revert to 4.0%"*; a probe left-out row reads *"Put back in reading"*; a calibration row reads *"Restore previous calibration"*.
    - When not `revertible`: *"Plan step. Edit the plan to change it."* for plan rows, else *"This change can't be put back"*.
  - `export function fromSetpointLog(rows): ChangeEntry[]`
  - `export function changesQuery(hash: string): { since: string; until?: string; actor?: string; kind?: string; room?: string; id?: string }`
  - `export function SettingHistory(props: { controller; entityId: string }): JSX.Element`

**Layout to mockup 12:**
- Chips *Made by* / *Kind* with counts; *"9 of 9 changes · last 7 days"*.
- Scope line *"Showing all rooms. Pick a room or zone in the room list to narrow it."*
- Day groups as an `<ol>` with `<time>` elements; each entry has an outcome line and its revert button.
- SELECTED CHANGE panel:
  - was / now, with `limits` (*"learner may move ±15 min"*);
  - WHY;
  - WHAT HAPPENED NEXT;
  - *"Written and read back 08:40:02"*;
  - **Revert to 50 min**, which calls `history_revert` → receipt → Undo (`revertEvents([new_event_id])`).
- URL `#/history/changes?since=&until=&actor=&kind=&room=&id=`.
- An IntersectionObserver loads the next 7 days (`until` = the oldest shown).
- Empty: *"No changes in this period."*
- On 3.17: built from `setpoint_log_get`; the Kind chips other than Setpoint are disabled with compact `NeedsIntegration`; revert re-writes `old` through `applyChanges`.

- [ ] **Step 1: Write the failing tests**
  - `toEntries builds Revert to <old> with unit`
  - `non-revertible plan row has the edit-the-plan line`
  - `actor manual maps to You and ai to AI judge`
  - `changesQuery round-trips actor kind room`
  - `fromSetpointLog gives setpoint entries`
  - `entries group by zoned day`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-h4.mjs` (mockup 12):
  - The *Learner* chip filters the feed and sets `actor=learner`.
  - Choosing an entry fills the panel.
  - **Revert to 4.0%** shows a receipt, then a toast.
  - `#/history/changes?actor=ai` opens filtered.
  - On `#/plan/targets`, the clock button of any `[data-setting-row]` opens the popover. Only the clock button is asserted.
  - 3.17: entries are shown.
- [ ] **Step 5:** Commit `feat(frontend): history changes feed with revert`.

### Task 19: E1 Probes & offsets

**Files:**
- Modify: `frontend/src/pages/probes.tsx`, `probes.css`, `frontend/src/lib/probes.ts`
- Create: `frontend/src/lib/probe-offset.ts`, `frontend/src/lib/parity-demo/equipment.ts`, `frontend/scripts/verify-parity-e1.mjs`
- Test: `frontend/src/lib/probe-offset.test.ts`

**Interfaces:**
- Consumes: `callV2("probe_offset_set")` (writes on call), `setup_read`, `Sparkline`, `revertEvents`
- Produces:
  - `export function handheldOffset(rawPct: number, handheldPct: number): number`. This is the backend's own rule, `handheld − raw`, shown before apply. **Fusion is not recomputed client-side.**
  - `export function curveDisabledReason(probe): string | null`. Returns *"This probe already converts to moisture. A curve only applies to raw readings."*

**Delta to mockup 13:**
- Title and counts.
- Table grouped by room: ZONE VALUE, HEALTH pill, PROBE, LAST 24 H, VWC, EC · TEMP, OFFSET, action.
- Match handheld editor:
  - *"Handheld reading, same spot"* [64.0] %;
  - *"Probe reads 61.0%"*, **+3.0** *"offset, VWC points"*;
  - *"The zone value updates once the controller holds the offset. Fusion re-baselines, so no step alert fires."*;
  - **Apply +3.0 offset to Zone 1 Back** → review & apply.
  - The receipt shows *"F1 Zone 1 value 63.8% → 65.3%"* from the response's `fused_before`/`fused_after`, then *"Written and read back HH:MM"* and Undo (`revertEvents`).
  - *"Raw value kept · logged in History › Changes"*.
- *Substrate curve* card (Rockwool / Coco / Custom; the server's refusal copy is shown as given).
- *Where to put a probe* card (G14) with an in-place warning.
- The feed calibration region **stays** on this page until Task 24 removes it.
- On 3.17: Offset shows "—" and Match handheld shows compact `NeedsIntegration`.

- [ ] **Step 1: Write the failing tests**
  - `handheldOffset 61.0 vs 64.0 is +3.0`
  - `curveDisabledReason for a VWC-native probe`
  - `receipt line uses fused_before and fused_after`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-e1.mjs` (mockup 13):
  - **Match handheld** on F1 Z1 Back → type 64 → "+3.0" → Apply → receipt containing "→" → Undo.
  - **Check placement →** focuses the placement card.
  - The feed calibration region is still present.
  - 3.17: the note shows.
- [ ] **Step 5:** Commit `feat(frontend): probe offsets with match-handheld`.

### Task 20: E2 Feed & dosing

**Files:**
- Modify: `frontend/src/pages/dosing.tsx`, `dosing.css`, `frontend/src/lib/dosing.ts`, `frontend/scripts/verify-tank-status.mjs` (owner; route `#/equipment/dosing`)
- Delete: `frontend/src/pages/reservoir.tsx`. Its tank-minimum guard and `TankStatus` move into the diagram. `App.tsx` stopped importing it in Task 1.
- Create: `frontend/scripts/verify-parity-e2.mjs`
- Test: `frontend/src/lib/dosing.test.ts` (extend)

**Interfaces:**
- Consumes: `dosing_get` / `dosing_request` / `dosing_save`, `stock_get`, `StockBottle`, `PeristalticPump`, `FeedTankDrawing`, the existing mix-check result, `useCsEvents` (`batch.step`), `HoldButton mode="hold-to-confirm"`
- Produces:
  - `export function protections(doc: DosingDocument, states: States): { label: string; ok: boolean }[]`. Labels: *"Read-back on every dose"*, *"Overfill cut 102%"*, *"Minimum 8%"*, *"Mix pump on · 0.42 kW"*, *"Timeout 12 min"*.
  - `export function nextBatch(doc, stock, now): { at: number; litres: number; doses: { name: string; ml: number }[]; steps: { name: string; min: number }[]; stockWarning: string | null }`

**Layout to mockup 14:**
- Title, plumbing diagram, Batch card.
- Mix-check failure card in place:
  - EC and pH band gauges and the explanation.
  - **Top up and re-check**: hold-to-confirm → `dosing_request {action:"batch"}`, the existing fill-mix-check cycle.
  - *"Feed EC probe calibrated 9 days ago · calibrate"*.
  - *Use once anyway* is **not built**: no service releases a held feed (Backend asks, item 5).
- Recipes by week, Next batch, **Calibrate a pump**, **Calibrate feed pH/EC**.

- [ ] **Step 1: Write the failing tests**
  - `protections counts armed of total`
  - `nextBatch warns when stock after batch is below low line`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-e2.mjs` (route `/equipment/dosing`, mockup 14):
  - `#/equipment/feed` lands here.
  - The mix-check card sits inside the diagram.
  - Holding **Top up and re-check** for 1.5 s records `dosing_request`.
  - The calibrate links go to the wizard routes.

  Then update and run `verify-tank-status.mjs`, which must pass.
- [ ] **Step 5:** Commit `feat(frontend): feed & dosing plumbing view with in-place mix check`.

### Task 21: E5 Stock

**Files:**
- Modify: `frontend/src/pages/stock.tsx`, `stock.css`, `frontend/src/lib/stock.ts`, `frontend/src/components/stock-bottle.tsx` (new optional `capacityScale?: number`; the default keeps today's drawing)
- Create: `frontend/scripts/verify-parity-e5.mjs`
- Test: `frontend/src/lib/stock.test.ts` (extend)

**Interfaces:**
- Consumes: `stock_get` / `stock_refill` / `stock_save`, `revertEvents`, recharts
- Produces:
  - `export function stockOutlook(tank, usePerBatchL, batchEveryDays): { batches: number; daysLeft: number; belowLow: boolean }`
  - `export function weeklyUse(history, tz): { week: string; byTank: Record<string, number>; partial: boolean }[]`

**Delta to mockup 17:**
- Bottles drawn to scale.
- *"17 batches · 43 days left"*.
- Below-low card *"Below the low line. Order now: supplier takes about 5 days."*
- **Log refill to 20 L**: applies immediately with Undo. On 3.18 Undo is `revertEvents`; on 3.17 it is `stock_save` with the prior level and `expected_revision`.
- Used per week; Refills.

- [ ] **Step 1: Write the failing tests**
  - `stockOutlook 5.4 L at 0.744 L/batch every 2.5 d → 7 batches, 18 days, belowLow`
  - `weeklyUse marks current week partial`
  - `refill undo on 3.17 saves the prior level with the revision`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-e5.mjs` (mockup 17): **Log refill to 20 L** on Part B → toast → Undo → 5.4 L, on both backends.
- [ ] **Step 5:** Commit `feat(frontend): stock bottles to scale with refill undo`.

### Task 22: E6 Setup: pumps & valves

**Files:**
- Modify: `frontend/src/pages/setup.tsx` (mount `SupplyEditor` first)
- Create: `frontend/src/components/supply-editor.tsx`, `supply-editor.css`, `frontend/src/lib/supply.ts`, `frontend/scripts/verify-parity-e6.mjs`
- Test: `frontend/src/lib/supply.test.ts`

**Interfaces:**
- Consumes:
  - `callV2("supply_get" | "supply_save")`;
  - descriptor `sensor.crop_steering_supply_config` attr `zone_demand_lph`;
  - `setup_read` / `setup_save` (dripper flow per zone);
  - `CapacityBar`, `ReviewApply layout="panel"`
- Produces:
  - `export function supplyChecks(doc: SupplyDoc): { ok: boolean | "warn"; text: string }[]`. Built from `capacity_check` only:
    - *"Pump max flow 900 L/h is in range"*
    - *"Every zone fits the pump on its own"*
    - ⚠ *"Zones 1 + 2 need 118%: shots queue, one after another"*
  - `export function togetherRows(demand: Record<string, number>, maxLph: number, groups: Record<string, string>): { zones: number[]; pct: number; sameGroup: boolean }[]`. This is display layout only: the summed demand over max flow, and whether the zones share a group. Verdict words: *"fits: can run together"*, *"over the pump: will run one after another"*, *"never together: exclusive group A"*.
  - `export function capacityRefusal(message: string): { text: string; suggest: number | null } | null`. Parses `pump_over_capacity:` messages; `suggest` comes from `capacity_check.suggest_max_concurrent`.

**Layout to mockup 18:**
- Pump card, Zone valves and drippers table, *What can run together*.
- Review & apply panel (`discardLabel: "Discard changes"`), checks and footer note.
- Apply runs `supply_save` first, then `setup_save` for dripper-flow rows. Partial failure copy: *"Pump settings were saved. Zone 3 dripper flow was not: controller still holds 3.0 L/h."* + **Try again**.
- A refusal shows *"The pump can't feed 6 zones at once. Set Zones at once to 5 or less."* + **Use 5**.
- Empty: *"Add your pump's output to stop zones starving each other."*
- On 3.17: `NeedsIntegration feature="Pump capacity and exclusive groups"`, and the existing Setup sections below still work.

- [ ] **Step 1: Write the failing tests**
  - `supplyChecks warns over-capacity from capacity_check`
  - `togetherRows sums demand and flags same group`
  - `capacityRefusal parses pump_over_capacity and suggests`
  - `two-write apply reports the setup failure only`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-e6.mjs` (mockup 18): Max flow 900 → 1 change; Zone 3 dripper 4.0 → 2 changes; Apply → receipt; 3.17 → the note plus the room-name field.
- [ ] **Step 5:** Commit `feat(frontend): pump capacity and exclusive groups editor`.

### Task 23: E3 Pump prime & calibrate

**Files:**
- Modify: `frontend/src/pages/pump-calibration.tsx` (stub → page)
- Create: `frontend/src/pages/pump-calibration.css`, `frontend/src/lib/pump-calibration.ts`, `frontend/scripts/verify-parity-e3.mjs`
- Test: `frontend/src/lib/pump-calibration.test.ts`

**Interfaces:**
- Consumes:
  - `StepRail`, `HoldButton mode="while-held"`, `PeristalticPump`, `StockBottle`;
  - `dosing_get` (pumps, `catalog`, `calibration_session`);
  - `callV2("pump_precheck" | "pump_prime" | "pump_stop" | "pump_calibrate" | "pump_calibration_commit")`;
  - `ReviewApply`, `useWakeLock`
- Produces:
  - `export function calibrationDue(lastAt: number | null, everyDays: number, now: number): { days: number | null; due: boolean }`
  - `export function rateSentence(mlMin: number, nominal: number | null): string`. Example: *"300 mL/min — 7% above the catalogue figure."* `ml_min` is the server's.
  - `export function wearNote(history: { at: number; mlMin: number }[]): string | null`. Example: *"Down 12% since March — tubing may be wearing."*
  - `export function runState(session: { ran_s?: number } | null): "waiting" | "ran"`

**Steps (mockup 15):**
- The rail shows 1 *Pick pump* · 2 *Prime* · 3 *30 s run* · 4 *Enter mL* · 5 *Save*. The primary button names the action: **Next: prime Part A**, **Run 30 s**, **Save 300 mL/min**.
1. Pump cards with a due warning; *What this pump doses*; *Pump head*.
2. **Hold to prime**:
   - press → `pump_prime {room_id, pump, seconds: 30}`; release → `pump_stop {room_id, pump}`;
   - the checklist comes from `pump_precheck`, polled every 10 s while on this step;
   - any blocker disables the button and names it (`blockers[].message`);
   - a refused prime shows its `blockers`.
3. *"Put the suction line in a measuring jug with at least 250 ml."* → **Run 30 s** (`pump_calibrate {seconds:30}`), then *"Waiting for the controller to report the run…"* until `dosing_get` shows `calibration_session.ran_s`. `dosing_get` is polled every 2 s.
4. *"How much did it pull?"*, mL.
5. `pump_calibration_commit {room_id, session_id, measured_ml}` → `rateSentence(ml_min, nominal)` and the wear sparkline → receipt.

On 3.17 the page shows `NeedsIntegration feature="Pump prime and calibration"`.

- [ ] **Step 1: Write the failing tests**
  - `rateSentence 300 vs 280 → +7%`
  - `calibrationDue 69 days at every 60 → due`
  - `wearNote down 12% since March`
  - `prime sends pump_stop on release` (holdController + spies)
  - `runState waits until ran_s is reported`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-e3.mjs` (mockup 15):
  - Picking Part B gives "Next: prime Part B".
  - A 2 s mouse hold records `pump_prime` then `pump_stop`.
  - **Run 30 s** shows the waiting line, then step 4.
  - 150 mL → "300 mL/min"; Save → receipt.
- [ ] **Step 5:** Commit `feat(frontend): pump prime and calibrate wizard`.

### Task 24: E4 Feed pH/EC calibration (+ P5)

**Files:**
- Modify:
  - `frontend/src/pages/feed-calibration.tsx` (stub → page)
  - `frontend/src/pages/probes.tsx`: replace the feed calibration region with the link *"Feed pH and EC probes: Calibrate →"*
  - `frontend/scripts/verify-calibration.mjs` (owner): route `#/equipment/feed-calibration?backend=3.17` for the v1 path
- Create: `frontend/src/pages/feed-calibration.css`, `frontend/src/lib/feed-calibration.ts`, `frontend/scripts/verify-parity-e4.mjs`
- Test: `frontend/src/lib/feed-calibration.test.ts`

**Interfaces:**
- Consumes:
  - `StepRail` (`compact` on phone), `StabilityRing`, `useWakeLock`;
  - `callV2("calibration_start" | "calibration_capture" | "calibration_commit" | "calibration_revert")`;
  - `subscribe_entities` on `raw_entity_id` and `temperature_entity_id`;
  - `components/probe-calibration.tsx`, the v1 form, rendered on 3.17;
  - `revertEvents`
- Produces:
  - `export function spanOver(readings: { at: number; value: number }[], windowMs = 30_000): { span: number; mean: number }`
  - `export function looksSteady(r: { span: number; mean: number }, kind: "ph" | "ec"): boolean`. Mirrors the backend rule exactly: pH span < 0.02; EC span < 1 % of the mean. **This is display only; the server's `stable` on capture decides.**
  - `export function verdictWords(slopePct: number, offset: number, kind): { headline: string; health: "healthy" | "clean_soon" | "replace" }`. Examples: *"Probe reads 0.12 pH low. Response 97% — healthy."* / *"Response 86% — clean or replace the probe soon."*
  - `export function captureState(lastReadingAt: number | null, now: number, steady: boolean): { enabled: boolean; label: string; reason: string | null }`
  - `export function sessionStore`: sessionStorage `crop-steering.cal-session` holding `{session_id, expires_at, step}`

**Steps (mockup 16):**
- Rail: Choose probe · Buffer 1 · Buffer 2 · Result · Apply.
- Prepare copy: *"Rinse the probe, dab it dry and stand it in the 7.00 buffer. Leave it still; the reading settles by itself."*
- Live reading (*"pH · buffer 7.00 · 21.3 °C, compensated to 25 °C"*), drift sparkline, *Settling…* / **Steady**, *"Capture unlocks after the reading holds within ±0.01 for 30 s."*
- **Capture 7.00 point · waiting for stable** / **Capture 7.00 point**.
  - A server `stable:false` shows *"Reading still moving — calibration may be off."*, with *Capture anyway* in a secondary menu (sends `force:true`).
- Footer: *"Step 2 of 5 · dosing for F2 paused"* (from `dosing_paused`); **Next: rinse, into 4.00**.
- Apply: proof row *"Now reads 4.01 in pH 4.00 buffer ✓"*, then Undo via `revertEvents`.
- Errors:
  - Offline: the server's refusal text, *"No reading from the feed pH probe for 2 min. Check it's plugged in."*
  - An expired session (`invalid` on capture or commit) shows *"Your last calibration session expired. Start again from buffer 1."* + **Start again**.
- *"Resume calibration"* appears while `expires_at` is in the future.
- P5: full screen, header with ✕, segmented step bar, big ring, *"Waiting for a steady reading"*.

- [ ] **Step 1: Write the failing tests**
  - `spanOver last 30 s`
  - `looksSteady pH 0.02 and EC 1% of mean`
  - `verdictWords 97% healthy, 86% clean soon`
  - `stale reading disables Capture` (`captureState` with a reading 125 s old → disabled, with the probe-offline reason)
  - `expired session restarts from buffer 1`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-e4.mjs` (mockups 16 and 28):
  - The demo feeds a settling then steady reading → Capture enables.
  - Both points → headline → Apply → receipt → Undo.
  - Phone: ✕ returns to Feed & dosing.
  - The Probes page shows the link.

  Then run `verify-calibration.mjs` → passes on the 3.17 path.
- [ ] **Step 5:** Commit `feat(frontend): feed pH/EC calibration wizard with stability ring`.

### Task 25: T1 Alert rules (+ P4)

**Files:**
- Modify: `frontend/src/pages/alert-rules.tsx` (stub → page)
- Create: `frontend/src/pages/alert-rules.css`, `frontend/src/lib/alert-rules.ts`, `frontend/src/lib/parity-demo/settings.ts`, `frontend/scripts/verify-parity-t1.mjs`
- Test: `frontend/src/lib/alert-rules.test.ts`

**Interfaces:**
- Consumes:
  - `Sentence` (Task 6);
  - `callV2("alert_rule_list" | "alert_rule_preview" | "alert_rule_set" | "alert_rule_delete" | "alert_rule_test")`;
  - `notify_get` (phones that get kind `sensors`);
  - `binary_sensor.crop_steering_rule_*` (3.17 list only);
  - recharts, `revertEvents`
- Produces:
  - `export const RULE_SOURCES: { id: AlertRule["source"]; label: (room, zone?) => string; unit: string; needs?: "entity_id" | "tank_id" }[]`. Covers the backend list plus `probe.silence_s` (seconds; shown in minutes as a display conversion) and `stock.litres`.
  - `export function ruleTokens(draft: AlertRule, set, ctx): (string | SentenceToken)[]`. The **Tell** token is `kind:"static"`: the names of phones that receive the *Sensors* kind, linking to `#/settings/notifications`. Backend routes rule pushes as kind `sensors`; see Backend asks, item 4.
  - `export function ruleStatus(item: AlertRuleListItem, now, tz): { text: string; tone: "bad" | "warn" | "muted" }`. Shapes, from `firing_since`, `last_fired`, `current_value` and `active`:
    - *"Firing now · since 12:42"*
    - *"Fired 11:31 today"*
    - *"Last fired Tue 03:40"*
    - *"Never fired"*
    - *"Off since 18 Oct · would fire now (5.4 L)"*
- **Sentences come from the server.** The list row shows `summary_sentence`; the replay line shows `sentence`. No client copy duplicates them.

**Layout to mockup 19:**
- *New rule* intro.
- Sentence builder. On phone, labelled native selects (P4).
- Replay chart from `alert_rule_preview` `series`:
  - `fires` spans are shaded as *would alert*, `ignored` spans as *too short to alert*, with ● at `fired_at`;
  - lights-off is shaded;
  - a draggable dashed threshold (arrows step 0.1 / 1) re-previews after a 250 ms debounce;
  - the result line is the server `sentence`.
- **Send a test push to Ben's phone** → `alert_rule_test {rule, send:true}` → *"Delivered to Ben's phone ✓ · Night phone: not delivered — {error}."*
- **Save rule and start watching**.
- *Your rules* list: summary sentence, `ruleStatus`, **Edit**, and an On switch that applies immediately with Undo (`revertEvents`). Delete applies immediately with Undo.
- `?rule=<id>|new`.
- Source not reporting: *"F2 tank level isn't reporting. This rule can't fire until it does."* (`current_value === null`).
- On 3.17: the builder shows `NeedsIntegration feature="Your own alert rules"`.

- [ ] **Step 1: Write the failing tests**
  - `ruleStatus covers firing, fired today, last fired, never, off-would-fire`
  - `ruleTokens Tell token lists sensors-kind phones and links to notifications`
  - `delivery line names each phone`
  - `probe.silence_s token shows minutes and stores seconds`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-t1.mjs` (mockups 19 and 27):
  - Threshold 40 → the line changes within 1 s; ArrowUp on the threshold moves it by 0.1.
  - Save → a new row appears.
  - Toggle → Undo.
  - Phone selects are native.
- [ ] **Step 5:** Commit `feat(frontend): alert rule builder with yesterday replay`.

### Task 26: T2 Notifications

**Files:**
- Modify: `frontend/src/pages/notifications.tsx`, `notifications.css`, `frontend/src/lib/notify.ts` (parse `quiet_hours`, `urgent_high_priority`, `mutes`; `notify_test {services}` results)
- Create: `frontend/scripts/verify-parity-t2.mjs`
- Test: `frontend/src/lib/notify.test.ts` (extend)

**Interfaces:**
- Consumes: `notify_get` / `notify_save` / `notify_test`, `ReviewApply layout="bar"` with `summary` and `discardLabel: "Discard"`, `useDraft("notify")`, `revertEvents`
- Produces:
  - `NotifyPhone` gains `quietHours: { from: string; to: string } | null` and `loud: boolean` (`urgent_high_priority`). `NotifyConfig.mutes: Record<string, number>` is already present.
  - `export function draftSummary(draft, saved): string`. Example: *"2 changes not applied yet: Sam's phone gets Dosing · Office tablet: F2 only"*.
  - `export function testLine(r: { sent: boolean; error: string | null }, at: number, tz): string`. Example: *"Accepted 13:58"*.

**Delta to mockup 20:**
- Matrix columns, from `kinds` in catalogue order: *Emergency · Hardware · Watering stopped · Sensors · Dosing · Stock · Phases · AI · Setup · Vitals*, plus *Rooms* and *Emergencies loud*.
  - The mockup's *Your rules* column is **not built**: rules route as kind *Sensors* (Backend asks, item 4).
- **Send test** per phone. **Test all** uses `notify_test {services}`.
- *Quiet hours*: per-phone `{from, to}`. The strip shows the union, with lights-on overlaid. Phone chips toggle a phone in or out of the shown window. Server refusal copy is shown as given.
- *Watering stopped and room mutes*: **Unmute F1** and **Mute F2 for 2 h** apply immediately with Undo.
- Bottom bar uses `draftSummary`, **Discard**, **Apply 2 changes**.

- [ ] **Step 1: Write the failing tests**
  - `parse tolerates missing quiet_hours and loud`
  - `draftSummary words each change`
  - `testLine accepted and failed`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-t2.mjs` (mockup 20):
  - Tick Sam's Dosing → the bar sentence appears → Apply → receipt.
  - **Mute F2 for 2 h** → Undo.
  - Set quiet hours 22:00–06:00 on Sam's phone → the strip updates.
- [ ] **Step 5:** Commit `feat(frontend): notifications routing, quiet hours and mutes`.

### Task 27: T3 System status

**Files:**
- Modify: `frontend/src/pages/system.tsx` (stub → page)
- Create: `frontend/src/pages/system.css`, `frontend/src/lib/system-status.ts`, `frontend/scripts/verify-parity-t3.mjs`
- Test: `frontend/src/lib/system-status.test.ts`

**Interfaces:**
- Consumes: `callV2("system_status_get")`, `openAlerts`, `callV2("alert_ack")`, `runningVersions` (3.17), `HealthRing`, `error-codes.ts`
- Produces:
  - `export const KIND_LABEL = { probe_vwc: "Moisture and EC probes", probe_ec: "Moisture and EC probes", probe_temp: "Moisture and EC probes", valve: "Valves", main_line: "Valves", pump: "Pumps", feed_probe: "Tank and feed sensors", tank: "Tank and feed sensors", flow_meter: "Pumps" } as const`. These are display groups over the backend `kind`.
  - `export function healthSentence(s: SystemStatus, alerts: OpenAlert[]): string`. Example: *"System health 94 %: 34 of 35 devices online, controller running, 3 open alerts, each shown below where it happens."*
  - `export function placeAlert(alert: OpenAlert, rows: { entity_id: string; kind: string; zone: number | null }[]): string | null`:
    - CS-1xx → the zone's probe row;
    - CS-3xx flow codes → the zone's valve row;
    - CS-6xx/7xx/8xx → the matching tank, dosing or software card;
    - otherwise `null`, and the alert sits on the room header.
    - When the backend adds `entity_id`, that wins (Backend asks, item 2).
  - `export function ageTone(row: { kind: string; last_seen: string; ok: boolean }, now: number): "ok" | "warn" | "bad"`:
    - probes: orange after 120 s, red after 20 min;
    - actuators: `ok` while the backend says ok.

**Layout to mockup 21:**
- Ring + sentence + *"Checked 14:02:11"*.
- *Software*: controller, integration, *"Loaded as ?v={card_version}"*, Home Assistant `ha_version`, AI `ai.model` + calls, with CS-706 in place.
- *Heartbeat*: one strip from `heartbeat.beats` (missed beats marked), *"Every {interval_s} s · {n} missed in the last hour"*. One strip, because the backend reports one controller heartbeat (Backend asks, item 6).
- *Every mapped device*: groups by `KIND_LABEL`, silent first, each with `last_seen`, a `uptime_7d_pct` bar and %. CS cards sit in place via `placeAlert`, with **What to do →** and **Acknowledge** (`alert_ack {room_id, alert_event_id}`).
- *"Capabilities ›"*.
- On 3.17: the page is built from entities; uptime and heartbeat show "—" with compact `NeedsIntegration`.

- [ ] **Step 1: Write the failing tests**
  - `healthSentence exact for fixture`
  - `placeAlert puts CS-102 on the zone probe row`
  - `ageTone ignores age for actuators`
  - `entity-only fallback counts online from last_updated`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-t3.mjs` (mockup 21):
  - The CS-102 card sits under the F1 Zone 2 back row.
  - **Acknowledge** removes it.
  - **What to do →** opens Help.
  - 3.17 renders.
- [ ] **Step 5:** Commit `feat(frontend): system status with problems on their device`.

### Task 28: T4 AI assistant

**Files:**
- Modify: `frontend/src/components/brain.tsx` (`AiSettings`, `:419`), `frontend/src/lib/brain.ts`, `frontend/scripts/verify-ai-instructions.mjs` (owner)
- Create: `frontend/scripts/verify-parity-t4.mjs`
- Test: `frontend/src/lib/brain.test.ts` (extend)

**Interfaces:**
- Consumes:
  - brain and JEV entities, `brain_*`, `controller.write` (judge switches);
  - `system_status_get.ai` on 3.18, else the JEV entity attributes;
  - `pagedQuery({kinds:["ai.judgement","ai.outcome"]})` on 3.18, else the ledger attribute;
  - `revertEvents`
- Produces:
  - `export function judgeMatrix(states, rooms): { id; name; blurb; power: "act" | "alerts" | "advice"; perRoom: Record<string, { on: boolean; entityId: string | null; note?: string }> }[]`
  - `export function outcomes(events: CsEvent[]): { at; scope; judge; text; result: string; verdict: "worked" | "measuring" | "undone"; band: [number, number]; value: number }[]`

**Delta to mockup 22:**
- Judges table with per-room switches (immediate, with Undo).
- Budget card: `pct_used`, CS-706 in place, *Daily budget US$* with a receipt.
- *Dry run*, model segmented control, cost line.
- *What it did, and what happened*, with **Full ledger in History →** linking to `#/history/changes?actor=ai`.
- The existing prompt editor sits under *"Instructions and permissions"*.

- [ ] **Step 1: Write the failing tests**
  - `judgeMatrix maps per-room switches and notes`
  - `outcomes verdict from ai.outcome`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-t4.mjs` (route `/settings/ai`, mockup 22): toggle *Water channel · F1* → Undo; budget → receipt; the ledger link opens Changes filtered to AI. Then update and run `verify-ai-instructions.mjs` → passes.
- [ ] **Step 5:** Commit `feat(frontend): AI assistant judges matrix, budget and outcomes`.

### Task 29: T5 Dashboards & display

**Files:**
- Modify: `frontend/src/pages/settings.tsx`, `settings.css`, `frontend/src/components/display-settings.tsx`, `frontend/src/lib/display.ts` (`DISPLAY_DEFAULTS` += the four unit keys)
- Create: `frontend/scripts/verify-parity-t5.mjs`
- Test: `frontend/src/lib/display.test.ts` (extend)

**Interfaces:**
- Consumes: `display_get` / `display_save` (`ec_unit`, `temp_unit`, `volume_unit`, `clock`), `formatEc`/`formatTemp`/`formatVolume`/`clock` (Task 5), `landing-view.ts`, `callV2("dashboard_list" | "dashboard_create")`, `useWakeLock`
- Produces: `export function unitExamples(states, room): { ec: string; temp: string; volume: string; clock: string }`. Live examples that use the store formatters.

**Layout to mockup 23:**
- *Units "Shown on every page and phone for this room"*. Units are saved per room through `display_save`, which differs from the mockup's per-user wording (see Deviations).
- Rows: EC, Temperature, Volume, Clock, each with a live example.
- Footnote: *"Display only. Readings stay stored in mS/cm, °C and litres, so switching back shows exactly the same numbers."*
- *Where the app opens* (existing landing preference): *"Saved and read back 13:48"*.
- *Wall and tablet dashboards*: the templates come from `dashboard_list.templates`, and any existing dashboard shows *"Created Tue 16:20 as /{url_path}"* + **Open in Home Assistant** + **Create again**. **Create in Home Assistant** calls `dashboard_create {template, rooms, title?}`.
- *"Keep this screen on while open"*, shown only when Wake Lock is supported.
- *More display options* (`<details>`) holds the HA connection, appearance, display options and sample workspace.
- On 3.17: units are saved in localStorage with *"Saved on this browser only until integration 3.18"*, and the dashboards show `NeedsIntegration`.

- [ ] **Step 1: Write the failing tests**
  - `old display entity reads units as mS/cm, C, L, 24`
  - `unitExamples change after setDisplayUnits`
  - `formatted ppm value parses back to the stored mS/cm` (`parseEc(formatEc(...))`)
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-t5.mjs` (route `/settings`, mockup 23):
  - PPM 500 → the example updates, and `#/all-zones` shows "ppm" (via the Task 5 store).
  - **Create in Home Assistant** (Room tablet) → the created line.
  - 3.17 → the dashboards note.
- [ ] **Step 5:** Commit `feat(frontend): units, landing and wall dashboards`.

### Task 30: Top bar and command palette

**Files:**
- Modify: `frontend/src/components/app-header.tsx`, `app-header.css`, `frontend/src/App.tsx` (pass `roomName` to `AppHeader`), `frontend/scripts/verify-dashboard.mjs` (header part), `frontend/scripts/verify-ha-shell.mjs`
- Create: `frontend/src/components/command-palette.tsx`, `frontend/src/lib/command-palette.ts`, `frontend/scripts/verify-parity-shell.mjs`
- Test: `frontend/src/lib/command-palette.test.ts`

**Interfaces:**
- Consumes: `NAV_TREE`, `controller.rooms`, `routeHash`, `SafetySwitches`
- Produces:
  - `export interface PaletteEntry { label: string; hint: string; hash: string; keywords: string[] }`
  - `export function paletteEntries(controller: Controller): PaletteEntry[]`. Includes the actions *"Calibrate F2 feed pH"*, *"Prime a dosing pump"*, *"New alert rule"* and *"New timer program"*.
  - `export function searchPalette(entries: PaletteEntry[], q: string): PaletteEntry[]`
  - `export function paletteKey(e: { key: string; ctrlKey: boolean; metaKey: boolean; target: EventTarget | null }, panel: Element): "open" | null`. Ctrl/⌘ K inside the panel, or `/` when focus is not in a field.

**Top bar:**
- *"Updated 12 s ago"*, *"● AI acting"*, **Jump to… Ctrl K**, the room name as plain text, *"● Watering on"*, **Stop all**.
- Phone: page title + *"Updated 12 s ago · AI acting"*.
- The palette is a `<dialog>`; focus returns to the opener on close.

- [ ] **Step 1: Write the failing tests**
  - `searchPalette "cal ph" finds Calibrate F2 feed pH first`
  - `entries include every NAV_TREE page and every zone`
  - `paletteKey ignores Ctrl K outside the panel and / inside an input`
- [ ] **Step 2:** Run the tests → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run them → PASS. `verify-parity-shell.mjs`:
  - Ctrl K → "changes" → Enter → `#/history/changes`.
  - Escape returns focus.
  - No room chip buttons at 1440.

  Then update and run `verify-dashboard.mjs` (header part) and `verify-ha-shell.mjs` → pass.
- [ ] **Step 5:** Commit `feat(frontend): top bar with jump-to palette`.

### Task 31: Bundle, full browser suite, CI list

Runs after every lane **and** the backend plan have merged.

**Files:**
- Modify:
  - bundles via `package.mjs`: `www/dashboard.html`, `addons/f2_control/www/public/dashboard.html`, `custom_components/crop_steering/www/dashboard.html` and the stubs
  - `.github/workflows/ci-validate.yml:390-397`: add `verify-navigation`, `verify-parity-harness` and every `verify-parity-*`
  - `frontend/scripts/capture-readme.mjs`
  - selector drift in `verify-workspace.mjs`, `verify-steering-visuals.mjs` and `verify-live.mjs` only

- [ ] **Step 1:** Confirm that `frontend/src/lib/generated/` and `lib/error-codes.ts` carry CS-214, CS-318, CS-319 and CS-612, committed by the backend's `render_error_codes.py` runs. Then run `node node_modules/typescript/bin/tsc --noEmit && node node_modules/vitest/vitest.mjs run` → PASS.
- [ ] **Step 2:** Run `node node_modules/vite/bin/vite.js build && node scripts/package.mjs` → exit 0. Three bundles are written, with no external URL.
- [ ] **Step 3:** Run every browser script:
  - The `verify-parity-*`, `verify-navigation`, `verify-calibration` and `verify-tank-status` scripts serve `dist/` or `www/` themselves.
  - `verify-dashboard`, `verify-live`, `verify-workspace`, `verify-steering-visuals`, `verify-recipe-library` and `verify-ha-shell` read `www/`.
  - `verify-irrigation-workspace` needs the dev server: run `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5178` first.

  Each script exits 0. Fix only drift caused by this plan.
- [ ] **Step 4:** Read every `output/playwright/parity/*-compare.json` and its HTML beside the mockup. List the remaining differences in the commit body as accepted (sample data) or fixed.
- [ ] **Step 5:** Commit `build(frontend): parity bundle and browser checks in CI`.

---

## Deviations from the UX spec (follow the mockups or the backend contract)

1. Health is at Settings › System status, not Equipment › Health (mockup 21).
2. Timers have their own page (I3), as well as the irrigation-mode table (mockup 07).
3. Alert rules have their own tab (mockup 19), not a section of Notifications.
4. Timer sentences use the mockup 07 shapes ("Every 30 min for 2 min, 08:00–12:00, Veg zones 1–2"), not UX G7's "Water for [2 min] every [30 min]…". The field names are the schema's (`one_off|recycle|simple`, `interval_min`).
5. Alert-rule replay and summary sentences are the server's. The mockup's "Would have alerted 2 times yesterday" becomes the backend's "This rule would have fired 2 times yesterday — 05:40, 15:20."
6. The "Tell" token is read-only (phones on the *Sensors* kind). The *Your rules* notifications column and *Use once anyway* are not built until Backend asks items 4 and 5.
7. Units are per room (`display_save`), not per user as mockup 23 says.
8. Mockup 12's chip says "You" for every manual change until history rows carry `user_id`.

## Self-review notes

- **Spec coverage:**
  - G1: Task 22, plus the I1 pump wait and the I3 capacity card.
  - G2: Task 24. G3: Task 23. G4: Tasks 16 and 8.
  - G5: Task 11. G6: Task 25. G7: Task 13. G8: Task 18.
  - G9 and G14: Task 19. G10: Task 14. G11 and G15: Tasks 29 and 5. G16: Task 8. G17: Task 27.
  - G12 and G13 are not shipped by the backend, so not built.
  - §3 patterns: Task 5 (review, undo, units, time), Task 4 (live), Task 7 (alerts in place, ShotTimeline, pick mode), Task 6 (sentence builder, calibration ring, hold buttons), Task 30 (palette).
- **Type consistency:**
  - `ReviewRow`, `ApplyReceipt`, `receiptFromWrite`/`receiptFromV2` and `revertEvents` (Task 5) are used by Tasks 12, 13, 14, 18, 19, 21, 22, 23, 24, 25, 26 and 28.
  - `TimelineBlock`/`TimelineRow` (Task 7) are used by Tasks 9 and 11.
  - `SentenceToken` (Task 6) is used by Tasks 13 and 25.
  - `OpenAlert` (Task 7) is used by Tasks 8, 9, 11 and 27.
  - `pagedQuery` (Task 3) is used by Tasks 4, 10, 15, 16 and 28.
- The preflight resolution map is in `.superpowers/sdd/2026-10-22-parity-frontend/preflight.md` § Resolution.

## Backend asks

What the frontend still needs that backend plan 4dc8f31e does not provide. The fallback in use is in brackets.

1. **Do not rebuild the dashboard bundles** in backend Tasks 12, 17 and 26. Global Constraints line 26 and the "Dashboard rebuild" command currently say to. Commit only the CS-code sources (`docs/error-codes.json`, the `render_error_codes.py` outputs including `frontend/src/lib/generated/*`, `notify_catalog.py`). Frontend Task 31 regenerates the three bundles once, after both plans merge (preflight P27).
2. **`entity_id` on each `alerts_open.alerts[]` item**, so G17's "an open CS alert sits on the entity row it concerns" is exact. [Fallback: `placeAlert` places by code family and zone.]
3. **`user_id` (and display name) on `history_changes` rows**, so "You" means the signed-in user. [Fallback: every `manual` row reads "You".]
4. **Per-rule targets, or a `rules` notify kind.** Rule pushes route as kind `sensors`, so the UX "Tell [phone]" token cannot choose phones, and mockup 20's *Your rules* column has no kind. [Fallback: a read-only Tell token, and no column.]
5. **A service to release a feed hold after a failed mix check, once** (mockup 14 "Use once anyway"). `dosing.check_request` allows `run_anyway` only on `batch`. [Fallback: the button is not built.]
6. **Per-room heartbeat in `system_status_get`.** Mockup 21 shows F2 and F1 controllers; the backend returns one `heartbeat`. [Fallback: one strip.]
7. **A read-only `calibration_status {session_id}`** → `{reading, stable, drift}` that stores nothing, so the Steady indicator uses the server's own verdict before Capture. `calibration_capture` stores the point when stable. [Fallback: the client mirrors the rule for display only, and the server's capture answer decides.]
8. **`probe_offset_set {preview: true}`** returning `fused_before`/`fused_after` without writing, so the review step shows the zone's new value before apply (spec §3). [Fallback: the zone change appears in the receipt after apply, with Undo.]
9. Optional: **`capacity_check.pairs[]`** (zones, pct, verdict), so "What can run together" is the server's verdict rather than display arithmetic. [Fallback: `togetherRows` layout only.]
