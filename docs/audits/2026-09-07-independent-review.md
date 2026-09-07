# Independent implementation review — 7 September 2026

Scope: uncommitted controller changes against baseline `972ae2be6307258c0a5a219ba1f0f414833beaac`, the supplied controller review diff and regression tests, system audit, and operator dashboard design. Review is offline and read-only except this report. No live HA, hardware, deployment, index, or branch changes. The controller, adapter, UI and final room-navigation corrections have now been reviewed; the original findings below are retained as evidence and their final status is recorded in each verdict.

## Controller verdict: approved after scoped correction

The original Important finding below is resolved in `output/playwright/controller-review-v2.diff`. The corrected implementation retains saved room blocks independently of discovery, gates against orphaned fault entity sets, holds conservatively for malformed orphan mappings, preserves absent room state on save, and restores the fault/counters before a returning owner becomes eligible for recovery. Scoped re-review found no new material gap. Accepted updated evidence: 36 controller tests and 24 compatibility tests passed; unchanged tests were not rerun by this reviewer.

Original findings: one Important; resolved. No Critical or Minor findings identified.

### Important — A temporarily undiscovered room loses its durable shared-hardware hold

Location: `addons/f2_control/f2_control/controller.py:985-993`, supported by `:463-467` and `:529-540`.

Faults are loaded only onto currently discovered `Room` objects, and the new shared-hardware gate iterates only those objects. A named room whose descriptor is temporarily absent during restart/rebuild therefore contributes no hold, even though its fault is present in `state.json`. An available room sharing its recorded pump can irrigate immediately. The next state save serializes only discovered rooms and permanently removes the absent room's fault and counters. Descriptor availability during startup is explicitly a supported condition in `_rediscover`.

Reproduction: construct an in-memory controller with only the default room mapped to `switch.shared_p`; supply saved state containing default counters and a `veg._hardware_fault` with entities `switch.shared_p`, `switch.veg_m`, and `switch.veg_v`. After `_load_state()`, `_hardware_fault_block(default)` returns `None`. This targeted reproduction was executed with Python and no filesystem/state writes or HA calls. The saved fault owner was not disarmed and its hardware was not verified OFF.

Required fix: retain saved room blocks independently of discovery, include all saved fault entity sets in shared-hardware gating, and preserve undiscovered blocks on save. Do not clear an orphaned hold merely because its descriptor/enable flag is absent; wait for safe owner recovery or an explicit validated recovery mechanism. Add a restart/discovery regression that verifies shared hardware stays blocked, independent hardware remains usable, an intervening save preserves the fault and counters, and later discovery restores the owner state.

## Checks and strengths

- Monotonic waiting includes HA polling and valve-open acknowledgement latency; measured duration no longer hides request overrun. Documentation correctly limits claims about physical shutdown and socket deadlines.
- Blind fallback and sibling-copy decisions now check their own zone budget while retaining the live-probe emergency path.
- Normal shutdown and error cleanup check all relevant hardware for definitive OFF and latch failed closure. Present/discovered fault owners and shared rooms require disarmed engine readback before recovery.
- Existing per-zone upgrade fields are retained, and optional fault metadata safely handles malformed values for discovered rooms.
- Accepted implementer evidence: 32 controller tests, 88 integration tests, and 46 pure-engine tests passed; scoped Ruff passed. These unchanged suites were not rerun. The additional missing-descriptor scenario above was independently reproduced.

## Adapter verdict: approved after scoped corrections

Final scoped re-review confirms both original Important findings below are resolved. Canonical identities are now `room:<prefix>` (including `room:` for default), selection/write routing uses those distinct identities, legacy aliases are resolved explicitly, and a missing explicitly requested room remains unselected. VWC/EC freshness uses `last_updated` with a 20-minute default and explicitly exposed age overrides; stale, missing, invalid, and excessively future timestamps produce unavailable readings and notices. Aggregates inherit unknown constituents, static configuration is not expired, and Sensors no longer labels stale fused probes as reporting. The added regression tests cover distinct default/named-F2/default-named rooms, their write isolation, missing requests, and probe timestamp cases. No unchanged test suites were rerun by this reviewer.

Scope: `frontend/src/lib/{model,client,use-controller,types,demo}.ts` and focused tests, adapter implementation report, and related UI integration. Source formatting changed concurrently; the line references below refer to the formatted checkout at review time.

Original findings: two Important; both resolved. No Critical or Minor findings identified.

### Important — Default room identity collides with a valid named F2 room

Location: `frontend/src/lib/model.ts:94`, with selection at `frontend/src/lib/use-controller.ts:45` and `:130`.

Discovery assigns the default empty-prefix room ID `f2`, and also assigns `f2` to a valid named room with prefix `f2_`. The integration permits this name (`config_flow.py` uses `slugify_room` without reserving F2). All subsequent selection and write preflight use ID equality, and the HTML select uses that ID for each option. The named room cannot be selected independently; a selection labelled F2 resolves to the first/default room. This violates generic room identity and undermines room-scoped operator review.

Reproduction executed entirely in memory with the real model module: descriptors for prefix `''`, slug `default` and prefix `f2_`, slug `f2` return `[{id:'f2',prefix:''},{id:'f2',prefix:'f2_'}]`. Fix using a collision-free canonical descriptor/prefix identity and explicitly resolve legacy `?room=f2` URLs rather than making F2 the default room's canonical identity. Cover both rooms together and verify their configuration writes remain independently selectable.

### Important — Stale live VWC/EC values still appear as current measurements

Location: `frontend/src/lib/model.ts:53-59` and `:335-336`, with alert construction at `:396`.

Measurement normalization checks numeric readability but never timestamps. A stale fused probe that HA still exposes as a number is shown in zone readings and room averages without a stale-data warning. The controller treats readings older than 20 minutes as dead in `_read_sensor`, so the UI can present current-looking values while irrigation has switched to blind fallback/copy. Heartbeat freshness is a separate issue and does not establish probe freshness.

Reproduction executed with the real model module: default-room VWC `60` and EC `3`, each with `last_updated='2020-01-01T00:00:00Z'`, yield VWC `60` and `alerts=[]` when the engine flag is readable. Fix with freshness-aware live measurement normalization (keep static configuration values readable), explicit stale/unavailable status, and aggregate values that remain unknown when a constituent measurement is stale. Add tests with an old probe and a fresh controller heartbeat.

### Adapter checks and strengths

- Live/demo clients remain separate, and demo writes stay in memory.
- Validated configuration controls exclude direct mapped hardware and unsupported event/recipe interfaces.
- Numeric bounds/step and select options are checked before dispatch; fresh full-state preflight and matching entity readback limit stale or misleading writes.
- Room/connection generation checks cancel late results, and per-entry batch failures preserve confirmed successes.
- Accepted implementer evidence: 18 focused Vitest tests and six mocked-HA browser groups passed. These tests were not rerun. The two scenarios above were additional in-memory reproductions.

## UI verdict: approved after scoped corrections

Final scoped re-review confirms the original Important specialist-routing finding below is resolved: actual prefixes `''` and `f1_` alone map to classic identifiers, unsupported rooms receive disabled links plus a scope explanation, and legacy view redirects wait for discovered room resolution before using that mapping. The parent's skip-link finding is also corrected: activation prevents the hash route change and focuses the existing main landmark. No remaining Critical or Important findings were identified in these corrected paths.

Scope: `output/playwright/ui-review.txt`, current pages/shared dashboard components, App navigation, and packaging script. Accepted verification evidence: 13 demo browser groups and six mocked-HA groups, all seven routes on desktop and 390 px mobile, and axe checks including mobile review/drawer. No unchanged browser tests were rerun.

Original findings: one additional Important; resolved. The parent also independently reproduced and corrected a keyboard skip-link bug.

### Important — Specialist links silently route unsupported named rooms to default-room controls

Location: `frontend/src/pages/settings.tsx:9-14`, used by Settings and Help, and the preserved target's resolver at `www/f2-classic.html:2265`.

The new helper forwards any discovered `controller.roomId` to the classic interface. That interface supports only `room=f1`; every other room value selects its F2/default identity mapping. For a generic named room such as Veg, opening Advanced tuning or Crop plan & recipes therefore loads another room's live configuration controls. The surrounding UI describes room floor plans and room context without warning of this concrete fallback. The newly fixed canonical room identities must also not be passed blindly into this old resolver.

Required fix: explicitly map only supported current-room prefixes to the classic interface's known room identifiers. Disable unsupported room links with a clear scope explanation, or implement a separately validated safe resolver. Preserve a deliberate route to classic tools with an explicit target if desired. Verify default, F1, and a generic third named room; no third-room action may silently resolve to default.

### UI checks and strengths

- Drafts survive polling, review displays current before/after values, invalid values block review, and confirmed applied entities alone are removed after partial failure.
- Navigation prompts before discarding strategy drafts; unavailable/offline states disable apply controls.
- Engine/zone actions go through the adapter and review dialog; scheduling text avoids promising an instantaneous hardware stop.
- History uses recorded data and explicitly reports unavailable/error cases; activity exports the filtered records without inventing event dates.
- Local packaging copies a defined artifact list, verifies inline script/styles for the primary dashboard, and does not deploy or perform remote mutations.

## Final overall verdict

Approved for the reviewed local implementation. All four Important findings raised in this report are resolved (one controller, two adapter, one specialist-routing issue). The parent's independently identified keyboard skip-link issue is also corrected. This is source/offline approval; no live HA, hardware behavior, or deployment was exercised. Final consolidated checks are recorded in `2026-09-07-final-verification.md`.

The final Minor classic-return navigation issue is resolved. Scoped inspection confirms `www/dashboard-nav.js` now uses a separate canonical primary-dashboard context for classic returns (`f1` to `room:f1_`, default or absent room to `room:`) while preserving legacy identifiers between specialist tools. The packaged copy has the same SHA-256 hash as the source. Accepted parent evidence: the added roundtrip regression passes for classic F2, F1, and absent room queries on an installation containing both default and named F2; all ten mocked-HA browser groups pass. These tests were not rerun by this reviewer.

No unresolved findings remain from this review.
