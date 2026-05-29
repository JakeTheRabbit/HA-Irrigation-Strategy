# F2 Migration — `migrate/main-consolidation` Plan & Verification

Consolidates **all of `origin/main` (RootSense v3.0-dev)** with the **lean branch's
proven engine fixes** (the v2 per-zone P0 dryback fix + the live session fixes), targeting
the F2 facility. Branch: `migrate/main-consolidation` (off `origin/main`).

**Hard gate:** nothing deploys to F2 hardware until the operator approves the cutover (§7).
The live crop runs on the deployed lean engine throughout; this branch is offline prep.

---

## 1. What was merged

3-way merge of `main` (lean+session, "theirs") into `origin/main` ("ours"). Lean deleted
**zero** files vs the merge-base, so all 39 of main's commits of additions came in clean.
Conflicts were isolated to **8 files**; 6 auto/clean-resolved, 2 hand-resolved:

| File | Resolution |
|---|---|
| `appdaemon/apps/apps.yaml` | **kept F2 config** (veg_main_pump, f2_row1-3, espoe mainline, source-water gate, emergency_vwc 10). Discarded main's 6-table foreign-facility config. |
| `base_async_app.py` | union — lean's hardened `set_state` (zero-state stringify, None-skip, REST fallback) **+** main's logging shims (`debug/info/warning/error`, `_check_ha_entity_state`). |
| `sensor.py` | main's tested/`calculations.py` version **+** ported lean's `_zone_number` regex fix. |
| `select.py` | union — main's native `zone_N_phase_override` (Auto/P0–P3) **+** lean's `zone_N_steering_mode` (engine reads it). |
| `number.py` | **union** — kept lean's engine-read entity names + per-zone bulk set + source-water numbers (history preserved) **+** added main's 4 new RootSense numbers (intent slider, veg/gen P0 dryback-drop sliders, climate grow-day offset). |
| `phase_state_machine.py`, `switch.py` | auto-merged clean. |
| `master_crop_steering_app.py` | **engine union, in progress** — see §3. |

---

## 2. Parity checklist (Step 4) — nothing dropped

All present on the branch (verified via `git ls-tree` post-merge):

- **RootSense pillars** (`appdaemon/apps/crop_steering/intelligence/`): `root_zone`,
  `adaptive_irrigation`, `agronomic`, `orchestration`, `anomaly`, `base`, `bus`, `store`.
- **ClimateSense suite** (`intelligence/climate/`): `sensing`, `timeline`, `lights`,
  `leaf_vpd`, `anomaly`, `hardware` (+`hardware_f1.yaml`), and `control/` {`app`, `actions`,
  `coordinator`, `watchdog`, `hvac`, `co2`, `dehumidifier`, `humidifier`, `exhaust`}.
- **LLM report-builder**: `intelligence/llm/report_builder.py`.
- **Integration extras** (main-only): `button.py`, `calculations.py`, `env_parser.py`.
- **packages/**: `irrigation/{00_core,10_mapping,20_model,30_irrigation,40_environment,50_alerts_watchdogs}.yaml`, `rootsense/00_recorder.yaml`.
- **recipes**: `config/recipes/athena_f1_default.yaml`.
- **dashboards**: `dashboards/` + `dashboards/legacyag/` (5 tabs).
- **docs/**, **tests/** (`test_calculations.py` + `tests/intelligence/`, 28+39 tests), **www/** guides.
- **62 py files** total (vs lean's 17) — full feature set retained.

**Gating note:** every RootSense/ClimateSense pillar self-gates behind
`switch.crop_steering_intelligence_*_enabled`, **default OFF**, and pillars never touch
hardware directly (propose via `custom_shot` → orchestrator gates → execute). So they ship
**present-but-dormant**; enabling climate control is a SEPARATE gated cutover (§7).

---

## 3. Engine reconciliation (Step 3) — `master_crop_steering_app.py`

main's master app was **not** "untouched in v3" — it carries 9 independent bug-fix commits
the lean branch lacks. Lean carries 7 commits main lacks. They fixed overlapping areas →
38 conflict hunks, resolved as a **union**:

- **Keep main's:** adaptive per-zone VWC ceiling (`zone_vwc_capacity`), sensor failover,
  outlier-rejection of valid VWC, bogus-P3-on-restart guard, queue-flood fix, zones 5&6
  fixes, "block P3 while in emergency VWC" guard, **max-shots→P2 exit** (this is the fix for
  the live "stuck in P1 unwatered" bug).
- **Keep lean's:** authoritative per-zone P0 dryback exit (`p0_dryback_drop_percent`,
  prefix-correct), monotonic peak tracking + persistence, source-water pH/EC gate, manual
  phase pin, 3h pre-lights-off P3 gate, ML `.get()` guards, analytics flattening.
- **Prefix sweep:** main has a systematic missing-`crop_steering_` bug on entity reads
  (`number.dripper_flow_rate`, `number.vegetative_dryback_target`, `number.p2_vwc_threshold`,
  `number.p0_dryback_drop_percent`, …) → all corrected to `number.crop_steering_*`.
- **Port live patches:** shot-size→duration conversion (main has it, fix its prefix) and the
  new human-readable activity feed (`sensor.crop_steering_activity_log`).

**Status:** ~8 hunks hand-resolved, remainder in automated resolution following the above
pattern; **full diff under human review before commit**. Gate: 0 conflict markers + AST
parse + 28 calc / 39 intelligence tests pass.

---

## 4. Entity-ID continuity (Step 5)

Because `number.py` was unioned to **retain the lean entity names the engine reads**, the
previously-flagged renames do **not** orphan history:

- **Preserved (history intact):** all sensors (VWC/EC/phase/dryback/water-usage), all 8
  existing switches, all existing number setpoints incl. the per-zone bulk set, all selects.
- **Additive (new, safe):** RootSense `steering_intent`, `veg/gen_p0_dryback_drop_pct`,
  `climate_grow_day_offset`; 12 `intelligence_*_enabled` switches; `zone_N_phase_override`
  select; `button.crop_steering_zone_N_trigger_shot`.
- **Residual:** main's *abbreviated* legacy names (`veg_dryback_target` etc.) were NOT added
  as duplicates (the full lean names are retained). If any legacyag dashboard references the
  abbreviated names it will show "unavailable" until reconciled — cosmetic, non-blocking.

**Decision still needed from operator:** none required for continuity (union preserved it).
Optional cleanup post-cutover: collapse the duplicate dryback-target naming once the engine
is confirmed stable.

---

## 5. Known engine flaws to fix before/at cutover (surfaced live)

1. **Daily volume cap blocks EMERGENCY rescue.** `_execute_irrigation_shot` checks
   `daily_volume_limit` before honoring shot_type; a too-low daily cap prevented rescuing a
   plant below its P3 emergency floor (observed live on F2). FIX: emergency shots must bypass
   the daily cap. (Live mitigated by raising caps; engine fix pending in this branch.)
2. **Blocked shots logged "completed"** — fixed (now logs blocked vs watered distinctly).
3. **Field-capacity vs P1 target sanity** — a P1 target above field capacity makes a zone
   unsatisfiable; clamp target < FC (live mitigated by setpoint).

---

## 6. Pre-cutover verification (Step 6) — all BEFORE hardware

- `ruff check . && black --check .` on the integration; AST-parse the engine.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/` (28 + 39).
- HA config check (`/api/config/core/check_config`) with the branch's `custom_components`.
- Load AppDaemon engine with `system_enabled` OFF (firing disabled); confirm: all configured
  F2 entity reads resolve (no default-fallbacks in log), phase sensors publish, no tracebacks,
  watchdog/fail-safe handlers load, no duplicate/competing automations.
- Dry-run one decision cycle in sim and confirm computed shot durations + phase logic match
  expectation, with NO valve actuation.

---

## 7. Staged cutover plan + rollback

**When:** during P3 / lights-off, automation paused (`switch.crop_steering_system_enabled`
OFF). **Pre:** snapshot HA; record current deployed engine SHA; confirm the lean engine
backup files are on the box (`*.bak-pre-*`).

1. Disarm: `system_enabled` OFF; confirm all valves/pump/main OFF.
2. Deploy branch `custom_components/crop_steering/` → `/config/custom_components/`; reload
   custom components (or HA restart). Verify entities resolve.
3. Deploy branch `appdaemon/apps/crop_steering/` (engine + intelligence/, pillars **not** wired
   in `apps.yaml` yet — irrigation engine only). Keep the F2 `apps.yaml` hardware block.
4. Restart AppDaemon; watch the activity feed + log for one full clean P0→P1→P2→P3 cycle with
   firing still disabled.
5. Arm: `system_enabled` ON. Monitor first real cycle on the activity card.
6. (Later, separate gate) enable RootSense substrate pillars (default-OFF switches), validate;
   then — only with explicit approval + verified F2 climate entity mapping — wire ClimateSense.

**Rollback (any step):** disarm; restore the lean engine from `*.bak-pre-*` on the box (or
redeploy `origin/crop-steering-v2`); restart AppDaemon; re-arm. Integration rollback: redeploy
lean `custom_components`. The lean tree is unchanged on `origin/crop-steering-v2`.

---

*Live crop is on the deployed lean engine + today's hotfixes (shot-duration conversion, daily
caps raised, activity feed) throughout. This branch does not touch F2 until §7 is approved.*
