# Dashboard duplication audit and proposed ownership

Pre-implementation source audit of all 20 mounted frontend routes, at local commit 4853f853. This is a design proposal, not a report of deployed changes or a live Home Assistant visual audit. No production files, settings or equipment were changed.

## Recommended layout

Five workspaces: **Today, Irrigation, History, Equipment, Settings**. Keep the existing five-section navigation concept; the current app does not have twenty top-level sidebar entries. Each setting has one editor, and each detailed record has one canonical workspace. Short summaries and critical safety notices may intentionally recur. Links preserve room, zone, run, timezone, date range and comparison baseline.

**A — Room overview (recommended):** readable zone cards, one attention item, compact supply readiness, and one recent-changes feed. **B — Compact console:** the same ownership and information in a table, better for many zones. These are two density choices, not competing application architectures.

## Findings and proposed fixes

### 1. Zone sizing — Remove duplicate editors

Current: Plants, pot volume, drippers and flow appear in Setup, Hardware sizing and Features.

Proposed owner: **Equipment / Rooms & zones**. Resolve room-config versus live-entity persistence before removing editors.

Evidence: [pages/setup.tsx:973](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/setup.tsx#L973).

### 2. Catch test — Merge

Current: Two calibration entry points on Setup.

Proposed owner: **One calibration beside dripper flow**. Keep calculate-only and place-result-in-draft actions.

Evidence: [components/controller-settings.tsx:278](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/components/controller-settings.tsx#L278).

### 3. Units — One preference owner

Current: Pot and flow units appear in Setup and Settings.

Proposed owner: **Settings / Preferences**. Inline unit convenience control may share exactly the same state.

Evidence: [pages/settings.tsx:434](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/settings.tsx#L434).

### 4. Steering mode and phase targets — Remove duplicate editors

Current: Targets and Features both edit phase settings.

Proposed owner: **Irrigation / selected zone and day**. Registry-only phase controls must be moved before Features becomes read-only.

Evidence: [pages/strategy.tsx:429](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/strategy.tsx#L429).

### 5. Automatic setpoints — Remove duplicate switch

Current: Targets, room controls and Features expose the same switch.

Proposed owner: **Irrigation / target source**. Schedule arming and AI permission switches remain separate.

Evidence: [pages/strategy.tsx:290](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/strategy.tsx#L290).

### 6. Physical limits and safety — One editor with overrides

Current: Field capacity, watchdog, daily caps and feed safety limits repeat in setup controls and Features.

Proposed owner: **Equipment / Substrate & safety**. Show defaults versus zone overrides; crop phase targets stay in Irrigation.

Evidence: [components/controller-settings.tsx:51](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/components/controller-settings.tsx#L51).

### 7. Lights schedule — Clarify owner

Current: Target remainder and Features expose lights times; metadata also claims Setup.

Proposed owner: **Irrigation / room lights schedule**. One room-shared schedule, not a copy per zone.

Evidence: [lib/model.ts:318](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/lib/model.ts#L318).

### 8. Watering and room state — Remove routine copies

Current: Header, Settings and Features expose room/watering controls.

Proposed owner: **Header: watering gate and emergency stop; Equipment: room in use**. These are three different actions. Keep critical safety warnings visible everywhere.

Evidence: [components/room-controls.tsx:165](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/components/room-controls.tsx#L165).

### 9. Zone enabled — Single individual editor

Current: Settings bulk controls and Features individual controls overlap.

Proposed owner: **Zone detail: individual enable; room action: reviewed bulk change**. Bulk and individual scope remain explicit.

Evidence: [pages/settings.tsx:267](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/settings.tsx#L267).

### 10. Prediction notifications — Relocate one switch

Current: Next-action notification switch appears in Settings and Features.

Proposed owner: **Settings / Notifications**. Keep recipients, categories and prediction switch together.

Evidence: [pages/settings.tsx:379](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/settings.tsx#L379).

### 11. Water display preference — Remove duplicate preference

Current: Zone/per-plant display preference appears in Settings and Features.

Proposed owner: **Settings / Preferences**. Room-shared notification formatting differs from browser-local unit choices.

Evidence: [pages/settings.tsx:320](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/settings.tsx#L320).

### 12. Sensing and calibration policy — One reviewed editor

Current: Water/VPD, plant stress, shot checks and CWSI repeat in Sensing and Features.

Proposed owner: **Equipment / Sensing**. Preserve distinct calibration types and converge save/review behaviour.

Evidence: [components/sensing.tsx:315](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/components/sensing.tsx#L315).

### 13. Manual hardware visibility — One preference owner

Current: Manual controls enable appears in Display and Features.

Proposed owner: **Settings / Preferences, with administrator restriction**. Exposing actuator controls is a permission-sensitive action.

Evidence: [components/display-settings.tsx:26](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/components/display-settings.tsx#L26).

### 14. Runoff estimation — Remove duplicate editor

Current: Runoff estimator and HVAC calibration appear in Setup and Features.

Proposed owner: **Equipment / Runoff**. Retain all coefficients and consistent review/save.

Evidence: [components/runoff.tsx:55](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/components/runoff.tsx#L55).

### 15. AI permitted actions — Relocate once

Current: Eight action switches are in Today AI and Features.

Proposed owner: **Settings / Automation & AI**. Today AI shows reasons and allowed-action summary only; provider credentials stay in controller configuration.

Evidence: [components/brain.tsx:166](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/components/brain.tsx#L166).

### 16. Stock measured level — Prevent stale overwrite

Current: Operational stock card and tank configuration both edit current level.

Proposed owner: **Stock card: set measured level or record refill**. Configuration owns capacity and low mark; new tanks may set an initial level.

Evidence: [pages/stock.tsx:210](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/stock.tsx#L210).

### 17. Features catch-all — Read-only directory

Current: Features recreates many controls from other pages and contains some otherwise unexposed controls.

Proposed owner: **Searchable capability/status directory with links**. First relocate registry-only controls, including pH auto-correct into Dosing settings.

Evidence: [pages/features.tsx:239](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/features.tsx#L239).

### 18. Zone substrate charts — Merge three presentations

Current: Zone mounts ZoneDay, HistoryExplorer and collapsed RecordedBehaviour.

Proposed owner: **One operational Zone chart; full explorer in History**. History presets replace the third chart, retaining long-term analysis.

Evidence: [pages/zone.tsx:140](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/zone.tsx#L140).

### 19. Zone explanations — Merge three panels

Current: ZoneWhy, BrainOnZone and JevOnZone repeat reasons and decisions.

Proposed owner: **One Why / next action panel**. Distinguish controller hold, proposed AI action and actual applied change.

Evidence: [pages/zone.tsx:149](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/zone.tsx#L149).

### 20. Today AI activity — Merge feeds

Current: Last AI decision, changes today and header status repeat activity.

Proposed owner: **One recent-changes feed linked to History events**. A no-change decision is not logged as an applied adjustment.

Evidence: [pages/today.tsx:271](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/today.tsx#L271).

### 21. Run and growth-stage context — Condense

Current: Today status, RunProgress and BrainCard repeat run/day/stage.

Proposed owner: **One room/run context band**. Show stage elsewhere only when needed to explain an action or mismatch.

Evidence: [pages/today.tsx:336](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/today.tsx#L336).

### 22. Water-use tables — Merge adjacent tables

Current: Water use and water delivery repeat today zone litres.

Proposed owner: **One History / Water table**. Columns: zone total, average per plant, week, grow-to-date; label estimates and plant-count assumptions.

Evidence: [pages/water-use.tsx:16](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/water-use.tsx#L16).

### 23. Next-shot conditions — Merge explanations

Current: Zone reason, Before next shot and timeline repeat hold/phase.

Proposed owner: **Zone Why / next action, expandable conditions**. Phase context in a chart remains useful.

Evidence: [pages/zone.tsx:115](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/zone.tsx#L115).

### 24. Historical comparisons — Consolidate workspace

Current: HistoryExplorer, OnThisDay, Compare and Grows overlap comparison flows.

Proposed owner: **History / comparison views with shared context**. Runs keeps portfolio/harvest records; label last completed grow-day accurately.

Evidence: [components/history-explorer.tsx:241](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/components/history-explorer.tsx#L241).

### 25. Tank summaries — Condense overview

Current: Today summary, abnormal feed line and full reservoir view repeat tank information.

Proposed owner: **Today: compact readiness summary; Equipment: full tank view**. Surface abnormal quality once on Today; tank quality and level history remain complementary views.

Evidence: [pages/today.tsx:367](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/today.tsx#L367).

### 26. Room selector — One global selector

Current: Sidebar and header both allow room selection.

Proposed owner: **Header room selector**. Room, zone, run and date context survive navigation.

Evidence: [components/app-header.tsx:73](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/components/app-header.tsx#L73).

### 27. Event activity — One full event workspace

Current: Header activity, Timeline and chart event lists repeat events.

Proposed owner: **History / Events**. Small recent-event previews and chart markers link to the same event, not separate logs.

Evidence: [components/activity-panel.tsx:49](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/components/activity-panel.tsx#L49).

### 28. Overview versus zone detail — Retain useful summary

Current: Today readings recur in Zone details.

Proposed owner: **Today short summary; Zone adds chart and explanation**. Do not remove glanceable operations data merely because it is also available in detail.

Evidence: [pages/today.tsx:690](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/today.tsx#L690).

### 29. Planning versus observed readings — Retain distinct layers

Current: Targets, Schedule previews and Zone show related curves.

Proposed owner: **One Irrigation planning canvas plus History evidence workspace**. Keep planned, draft, recorded and previous-run lines explicitly labelled; gaps stay gaps.

Evidence: [pages/strategy.tsx:616](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/strategy.tsx#L616).

### 30. Plant stress and drying drivers — Retain complementary analysis

Current: Today stress, Zone detail, daytime VPD response and nighttime drivers look related.

Proposed owner: **Summary on Today; details in Zone / History Drivers**. Daytime response and quiet-night analysis use different evidence windows.

Evidence: [pages/drivers.tsx:31](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/drivers.tsx#L31).

### 31. Save behaviour — Unify interaction, preserve guards

Current: Some settings save on blur, Features stages changes, Setup uses revision-aware review.

Proposed owner: **Consistent draft / review / save with visible scope**. Keep backend revision and safety checks; preserve a draft when pause or validation is required.

Evidence: [pages/setup.tsx:1102](https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/blob/4853f853/frontend/src/pages/setup.tsx#L1102).

## Complete route coverage

| Current route | Proposed destination | Disposition |
|---|---|---|
| `today` | Today | Keep concise room/zone summary. |
| `zone` | Today → zone detail | One chart, one explanation, one individual zone enable. |
| `today/ai` | Today → contextual AI drawer | Read-only reasons; permissions move to Settings. |
| `plan/targets` | Irrigation → current day | Current applied targets and their source; one editor when permitted. |
| `plan/schedule` | Irrigation → calendar | Future recipes/day targets; same canvas, separate schedule lifecycle. |
| `history/timeline` | History → Events | Canonical event log. |
| `history/water` | History → Water | One consolidated delivery table. |
| `history/compare` | History → Compare | Shared comparison context. |
| `history/grows` | History → Runs | Retain run portfolio, harvest and outcomes. |
| `history/drivers` | History → Drivers | Separate daytime and overnight methods. |
| `equipment/probes` | Equipment → Probes | Mapping, health, inclusion and calibration with distinct save semantics. |
| `equipment/stock` | Equipment → Water & nutrients / Stock | Concentrate inventory and refill records. |
| `equipment/feed` | Equipment → Water & nutrients / Feed tank | Feed quality, supply state, level/fill history. |
| `equipment/dosing` | Equipment → Water & nutrients / Dosing | Batch recipe, pumps, stock links, pH auto-correct owner. |
| `equipment/setup` | Equipment → Rooms & zones / safety / sensing | One equipment sizing and calibration owner. |
| `settings` | Settings → Preferences / connection | Remove duplicated operational controls. |
| `settings/features` | Settings → capability directory | Read-only search and deep links, after all orphan controls have owners. |
| `settings/notifications` | Settings → Notifications | All notification policies and recipients. |
| `settings/ai` | Settings → Automation & AI | Instructions and AI permitted actions; not duplicate live targets. |
| `help` | Settings → Help & diagnostics | Preserve install, troubleshooting and user guidance. |

## Boundaries that must survive consolidation

- Feed EC, pore EC and source EC are different measurements. Never collapse them into one value. Tank quality history and tank-level/fill history share a range but remain separate series.
- Delivered litres are controller estimates unless a mapped meter proves otherwise. Per-plant values are averages, not measured uptake. Preserve recorded historical plant counts; do not recalculate old runs using today's count.
- Dryback percent of peak, VWC percentage points and percentage-points/hour must keep explicit units and definitions.
- Room in-use, watering permission, individual zone enable, bulk zone operation and emergency stop are different scopes/actions. Preserve their existing backend guards and clear review text.
- Probe mapping, inclusion/primary choice, probe calibration and dripper catch tests are distinct operations even when colocated.
- Schedule arming, automatic setpoints and AI action permissions are distinct. Active schedule ownership must be shown and enforced; do not enable a second live-target writer.
- Future schedule start dates and run-record dates have different purposes. Old URLs become context-preserving redirects, not silent data migrations.

## Migration and verification before any UI removal

1. Enumerate every Features registry entry and assign a canonical owner, including controls currently exposed only there. Keep the directory read-only only after this inventory passes.
2. Reconcile duplicated persistence paths. Sizing in room configuration versus live number entities needs one authoritative update and readback path, otherwise stale Setup values can overwrite recent edits. Apply the same rule to stock levels and direct/on-blur saves.
3. Reuse shared chart/context components, preserving recorded gaps, timestamps, units, source labels, event IDs and timezone. Never replace historical evidence with schematic predictions.
4. Test schedule ownership/overrides, setup revision conflicts, stale sensors, pause-before-save, missing entities, navigation context, responsive layouts and keyboard access. Critical notices remain visible.
5. Remove redundant presentations only after these checks and user approval; no controller algorithm changes are implied by the navigation refactor.

## Mockup scope and limitations

The standalone preview contains synthetic F2 data and an inactive F1 example. It has no HA connection and sends no equipment commands. A/B layouts, navigation, zone drawer, combined VWC/EC planning reference, P3 emergency-floor nudges, steering slider, setup pause/review, and comparison toggle are interactive. Deeper forms and longer historical ranges are explicitly layout previews. Synthetic curves demonstrate visual feedback, not a validated crop model or recipe recommendation. A saved review preference is local feedback only and does not authorize deployment.
