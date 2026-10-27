# Parity backend (Journal, GuardChain, new producers, projections, MCP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend half of the unified schema: one per-room Journal fed by the integration and the controller, one ordered GuardChain in front of every actuator, the new producers behind G1–G11, G15 (display units) and G16–G17, the read projections, the API v2 envelope and the MCP read/preview tools. With no new config, watering does exactly what it does today.

**Architecture:** The integration owns an SQLite Journal (`journal.py`) and every new store and service. The controller writes events to an outbox and flushes them through `crop_steering.journal_append`, as it already flushes `grow_day_record`. It reads new config only from published descriptors and entities: `sensor.crop_steering_supply_config`, `sensor.crop_steering_<px>timers_config`, the `zone_N_irrigation_mode` selects and the `*_corrected` sensors. Each one is absent on an old install, and then the old behaviour applies. Pure arithmetic goes into `crop-steering-engine` (`ids`, `timers`, `flow`, `guards`). The integration gets byte-for-byte copies under `generated/`, the same way `defaults.py` is copied today.

**Tech Stack:** Python 3.12 (integration stubs, add-on, engine); Home Assistant 2026.9 on Python 3.14 in Docker (`tests_ha`); stdlib `sqlite3`; TypeScript + zod + `node --test` (mcp-server).

**Spec:** `docs/superpowers/specs/2026-10-22-unified-schema.md` (§2, §4–§7 are the contract). Service contracts per feature: `docs/superpowers/specs/2026-10-22-parity-ux.md`. Backlog: `docs/superpowers/plans/2026-10-22-growlink-aroya-parity.md`.

## Global Constraints

- **Absent means as before** (spec §7). A missing store, descriptor, select, corrected sensor or supply entry reproduces today's behaviour exactly. Default `max_concurrent_zones = 1`, no exclusive groups, `irrigation_mode = steering`.
- **The Journal is never on the watering path** (ruling R5). The controller's only in-pass journal work is a local file append to the outbox. The flush to the integration runs once, after the pass, fire-and-forget with a 1 s timeout, and stops at its first failure. It never runs before or during a shot. An integration-side failure to open or append is logged and nothing else happens.
- Existing entity ids, store keys, `engine_config`/`dosing_config` attribute contracts, `/data/state.json` fields and `crop_steering_setpoint_write` do not change. New things are additive only. A new state field goes into `_fresh_zone` with a safe default and is read with `.get`.
- Existing held reasons stay word-for-word (Task 3 pins them). New guards add new strings and never reword old ones.
- Event schema `v: 1` exactly as spec §4. `source.actor` ∈ `engine|timer|plan|manual|ai|learner|safety|mcp|aigrow|automation|system`. `outcome` ∈ `ok|queued|held|refused|aborted|failed|partial`.
- Event ids are ULIDs: 26 chars matching `^[0-9A-HJKMNP-TV-Z]{26}$`. `seq` is per-room and monotonic, and only the integration assigns it.
- Retention: `shot.*`, `intent.*` and `flow.*` are kept 400 days. Every other kind is kept forever.
- Outbox: `journal_outbox.jsonl` sits next to the state file and holds at most 5000 lines, dropping the oldest. `journal_append` takes at most 50 events per call and is idempotent on `id`.
- Reads need a signed-in user. Writes need an admin (`admin.async_require_admin`). MCP never gets `intent_submit`, `pump_prime`, `pump_calibrate` or the calibration wizard steps.
- Integration dependencies are pure HA, voluptuous and stdlib. The engine stays pure Python. No new pip dependency anywhere.
- Every new response service registers with `SupportsResponse.ONLY` (reads) or `OPTIONAL` (writes), is listed in `services.yaml`, and addresses rooms as `room_id = "room:" + prefix`.
- **New CS codes:** CS-214 "Zone needs more than its pump" (notification, **warning**; ruling R1), CS-318 "Less water than expected" (notification, warning), CS-319 "Water flowing with no zone on" (notification, warning), CS-612 "Feed probe calibration due" (repairs, warning). Each code is reserved in `tests/test_error_codes.py::RESERVED` under branch `feat/parity-system`. Its JSON entry lands in the task that raises it. Then run `python scripts/render_error_codes.py` and put the code in a `notify_catalog.KINDS` kind.
  - **Backend tasks never rebuild the three dashboard bundles** (ruling R11). The frontend plan's Task 31 owns that.
  - Until it lands, `tests/test_error_codes.py::test_no_code_is_defined_twice` fails on the bundle comparison for the new codes. Backend tasks run the error-code tests with `--deselect tests/test_error_codes.py::test_no_code_is_defined_twice` and say so in the commit body.
  - Every other error-code test must pass.
- **No `version:` change, no CHANGELOG or WHATS_NEW release section.** Those belong to a `release/x.y.z` branch.
- **One commit per task** (ruling R10). Every task ends in exactly one commit; the old "one commit per layer" rule is dropped.
- **One zone key format everywhere** (ruling R9): `room_id` is `"room:" + prefix`. A site-wide map keyed by zone nests the existing integration format, the zone number as a string as in `entry.data["zones"]`, under the room id: `{"room:f2_": {"3": value}}`. Single-room services take `room_id` plus an int `zone`. No `room:f2_/zone:3` strings are stored anywhere.
- **`config.changed` carries `{store, section, old, new, diff[]}`** (ruling R8). `old` and `new` are full copies of the changed section, so `history_revert` and `fold_changes` work for every store.
- **Commands** (git-bash on this box). `PY` below means `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$LOCALAPPDATA/Programs/Python/Python312/python3.exe" -m pytest`.
  - Engine: `PYTHONPATH=crop-steering-engine/src PY crop-steering-engine/tests/<file> -q`
  - Add-on: `PY addons/f2_control/tests/<file> -q`
  - Integration stubs: `PY tests/<file> -q`
  - Real HA (Linux, Py 3.14; on Windows use Docker): `docker build -f tests_ha/Dockerfile -t crop-steering-tests-ha . && git ls-files -co --exclude-standard -z | tar --null -T - -cf - | docker run --rm -i crop-steering-tests-ha tests_ha/<file> -q`
  - MCP (npm is banned): `pnpm --dir mcp-server install && node mcp-server/node_modules/typescript/bin/tsc -p mcp-server/tsconfig.json && node --test mcp-server/tests/*.test.mjs`
  - Lint: `"$LOCALAPPDATA/Programs/Python/Python312/python3.exe" -m ruff check . && "$LOCALAPPDATA/Programs/Python/Python312/python3.exe" -m black --check custom_components/ tests/`
  - Full: `bash tests/run_ci.sh --allow-skip`
- **Commit command, used in every "Commit" step:** `git -c user.email=123831499+JakeTheRabbit@users.noreply.github.com -c user.name=JakeTheRabbit commit -m "<subject>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`. Stage only the files the task lists.

## Review Focus

1. **Integration down, hung, or older than this branch.** `journal_append` fails, hangs or is missing, every pass. Expected:
   - the shots are unchanged;
   - the outbox grows to 5000 lines and stops;
   - each pass adds less than 1.5 s.

   Pinned by Task 8 `test_outbox_never_blocks_a_shot_when_the_integration_refuses` and `test_a_hung_integration_adds_under_1_5_s_to_a_pass`.
2. **A zone held every pass for hours** (kill switch off overnight). Expected: one `intent.held` per change of reason, re-emitted at most every 30 min, not 1,440 rows a day. Pinned by Task 8 `test_a_standing_hold_is_journaled_once_per_reason_and_every_30_min`.
3. **A corrected feed sensor that reads `unavailable`, or is missing after an HA restart, while a calibration is applied** (ruling R4). Expected:
   - The controller computes `raw × gain + bias` itself from the calibration it last saw in the descriptor, and never uses the uncorrected raw value.
   - Only a dead raw probe holds, as "source-water pH probe dead…".

   Pinned by Task 18 `test_an_unavailable_corrected_ph_is_computed_from_raw_and_the_calibration` and `test_ha_restart_keeps_the_last_calibration`.
4. **A timer window that crosses midnight, or a DST change day** (lights-off 20:00→04:00). Expected: the shots fall inside the window on the right local day, with none doubled or skipped at the DST hour. Pinned by Task 1 `test_lights_off_window_crosses_midnight` and `test_dst_spring_forward_keeps_interval_on_wall_clock`.
5. **Controller notifications dismissed by direct `persistent_notification.dismiss` calls** (about 10 call sites), which emit no `alert.cleared`. Expected: the inbox closes an alert whose `f2_<key>` notification is gone. Pinned by Task 27 `test_an_alert_whose_notification_is_gone_leaves_the_inbox`.

## Parallel lanes

The tasks in a lane are serial. Lanes on one row share no source file, except the append-only registries in the last row.

| Lane | Tasks | Files owned |
|---|---|---|
| E engine | 1 → 2 | `crop-steering-engine/src/crop_steering_engine/{ids,timers,flow,guards}.py`, vendored copies, `custom_components/crop_steering/generated/{ids,timers,guards}.py`, `tests/test_generated_copies.py` |
| C controller | 3 → 8 → 10 → 12 → 15 → 26 | `addons/f2_control/f2_control/{controller,journal_out,guards}.py`, `gate_report.py`, `tests/fake_ha.py` |
| D dosing/brain | 9 (after 8; it also edits `controller.py`) → 13 (after 12; it also edits `guards.py`) → 20 | `dosing_runner.py`, `brain_bridge.py`, `brain/ledger.py` |
| J journal | 4 → 5 → 6 → 7 → 24 → 25 → 27 | `journal.py`, `journal_api.py`, `changes.py`, `timeline.py`, `alerts_inbox.py`, plus the producer hooks in Task 6 (`setpoint_log`, `setup_api`, `strategy`, `overlays`, `stock_api`, `calibration.py`). Task 6 runs before lane K touches `calibration.py`. |
| S site | 11 → 16 → 22 | `site_store.py`, `site_api.py`, `alert_rules.py`, `binary_sensor.py`, `presets.py` |
| T timers | 14 | `timers_api.py`, `select.py`, `const.py` |
| K calibration (after 6) | 17 → 21 | `calibration.py`, `probe_offsets.py`, `sensor.py` (probe readings) |
| P pumps | 19 | `dosing.py`, `dosing_api.py`, `stock_api.py` (after Task 6) |
| H health/grow | 28 → 29 | `health.py`, `system_status.py`, `strategy.py` (after Task 6) |
| W wall/display | 32, 33 | `dashboards.py`, `display.py` |
| N notify | 34 | `notify_api.py` |
| X envelope | 23 (run last among integration tasks: after 24–29 and 32–34) | `api_v2.py`, every `*_api.py` schema |
| M mcp | 30 → 31 (after 23–25) | `mcp-server/src/*`, `mcp-server/tests/*` |
| **Shared, append-only** | many | `__init__.py` (setup calls and the `Platform` fallback), `services.yaml` (append at EOF), `tests/conftest.py` (Task 16 only), CS-code files (`tests/test_error_codes.py`, `docs/error-codes.json`, `docs/ERROR_CODES.md`, `notify_catalog.py`: Tasks 12, 17, 26; no bundles, ruling R11), `sensor.py` (Tasks 17, 19, 21). Merge these serially. |

Cross-lane dependencies by interface only (no shared file):
- 15 needs 1 and 14's entity contract.
- 12 needs 2 and 11's descriptor contract.
- 18 (lane C, then D) needs 17's sensor contract.
- 20 needs 19's descriptor contract.
- 25 needs 1, 14 and 15's `projection_app`.
- 24 needs 22's `presets.write_numbers`.
- 5 needs 1 (`generated/ids.py`); 4 imports `ULID_RE` from it too.
- 11 needs 2 (`generated/guards.py`).
- 13 needs 10 and runs after 12, because `guards.py` is shared.
- 16 needs 17 (corrected feed sensors) and 26 (`zone_N_flow_ratio`).
- 19 needs 17 (the `calibrating` blocker).
- 25 needs 11 (`zone_demand_lph`).
- 26 needs 11 (meters).
- 28 needs 27 (`alerts_open`).
- 30 and 31 run after 11, 16, 23, 24, 25 and 28.
- 32 (dashboards) and 33 (display) are their own lane.
- 34 (notify) stands alone.

---

### Task 1: Engine `ids` and `timers.project`

**Files:**
- Create: `crop-steering-engine/src/crop_steering_engine/ids.py`, `crop-steering-engine/src/crop_steering_engine/timers.py`
- Copy: both into `addons/f2_control/f2_control/crop_steering_engine/` and into `custom_components/crop_steering/generated/`
- Modify: `crop-steering-engine/src/crop_steering_engine/__init__.py` (export), `tests/test_generated_copies.py`. Today it has one `SOURCE` (defaults.py) and a flat `COPIES`. Restructure it into `PAIRS: list[tuple[Path, Path]]` of (source, copy), covering defaults.py ×2, ids.py ×2 and timers.py ×2. Both existing tests iterate the pairs.
- Test: `crop-steering-engine/tests/test_ids.py`, `crop-steering-engine/tests/test_timers.py`

**Interfaces:**
- Produces:
  - `ids.new_id(now: datetime | None = None, rand: bytes | None = None) -> str`
  - `ids.derived_id(at: datetime, key: str) -> str`. The 48-bit ms timestamp comes from `at`. The 80 bits come from `sha256(key)[:10]`.
  - `ids.ULID_RE`
  - `timers.PlannedIntent(program_id: str, zone: int, at: datetime, duration_s: float)`, a frozen dataclass.
  - `timers.validate(program: dict) -> dict` (normalised; raises `ValueError`)
  - `timers.project(program: dict, lights: tuple[float, float], start: datetime, end: datetime) -> list[PlannedIntent]`. `lights` is `(on_hour, off_hour)` in local hours. `start` and `end` are tz-aware. The result is sorted by `(at, zone)` and covers `start <= at < end`.
- Program shape (spec §2.5): `{id, room_id, name, zones[int], type: one_off|recycle|simple, duration_s, interval_min, frequency_per_day, start_at, window: {kind: all|lights_on|lights_off|custom, from?, to?}, sync_time?, active, revision}`.

- [ ] **Step 1: Write the failing tests**

```python
# test_ids.py
def test_new_id_is_a_26_char_ulid_sorted_by_time():
    a = new_id(datetime(2026,10,22,7,0,tzinfo=UTC), b"\0"*10)
    b = new_id(datetime(2026,10,22,7,0,1,tzinfo=UTC), b"\0"*10)
    assert ULID_RE.fullmatch(a) and a < b
def test_derived_id_is_stable_for_the_same_row():
    at = datetime(2026,1,1,tzinfo=UTC)
    assert derived_id(at, "setpoint_log:x:1") == derived_id(at, "setpoint_log:x:1") != derived_id(at, "setpoint_log:x:2")

# test_timers.py  (NZ = ZoneInfo("Pacific/Auckland"))
def test_recycle_0800_to_1200_every_30_min_is_8_shots():           # G7 accept
    p = {"id":"t","zones":[1],"type":"recycle","duration_s":120,"interval_min":30,
         "window":{"kind":"custom","from":"08:00","to":"12:00"},"active":True}
    got = project(p, (6, 18), datetime(2026,10,22,0,0,tzinfo=NZ), datetime(2026,10,23,0,0,tzinfo=NZ))
    assert [i.at.strftime("%H:%M") for i in got] == ["08:00","08:30","09:00","09:30","10:00","10:30","11:00","11:30"]
    assert {i.duration_s for i in got} == {120}
def test_sync_time_shifts_the_first_recycle_shot(): ...   # sync 08:10 -> first 08:10, last 11:40
def test_simple_spreads_frequency_evenly_over_lights_on(): ...  # lights (6,18), 6/day -> 06:00,08:00,...,16:00
def test_one_off_fires_once_inside_range_and_never_outside(): ...
def test_lights_off_window_crosses_midnight(): ...        # lights (6,18), recycle 120 min -> 18:00,20:00,22:00,00:00,02:00,04:00
def test_dst_spring_forward_keeps_interval_on_wall_clock(): ...  # 2026-09-27 NZ: no shot at nonexistent 02:00, none doubled
def test_inactive_program_projects_nothing(): ...
def test_one_shot_per_zone_per_slot(): ...                 # zones [1,2] -> 2 intents per slot, sorted (at, zone)
@pytest.mark.parametrize("bad,msg", [
  ({"window":{"kind":"custom","from":"08:00","to":"08:00"}}, "End must be after start"),
  ({"duration_s":0}, "duration"), ({"interval_min":0}, "interval"), ({"zones":[]}, "zone"), ({"type":"x"}, "type")])
def test_validate_refuses(bad, msg): ...
```

- [ ] **Step 2: Run them and see them fail.** Run `PYTHONPATH=crop-steering-engine/src PY crop-steering-engine/tests/test_ids.py crop-steering-engine/tests/test_timers.py -q`. Expected: FAIL, `ModuleNotFoundError`.
- [ ] **Step 3: Implement both modules.**
  - `ids` uses Crockford base32 from the stdlib only.
  - `timers.project` walks local days from `start.date()-1` to `end.date()`. It builds each window in local wall time. A window whose `to <= from` crosses midnight. Each slot is `datetime.combine(day, t, tzinfo=tz)` (stdlib `zoneinfo`, no pytz). A nonexistent wall time is skipped when its `astimezone(UTC).astimezone(tz)` round-trip changes the wall clock.
  - recycle: `first = sync_time or window.from`, then step by `interval_min` while `< window.to`.
  - simple: `window_start + i*(len/frequency)`, for `i` in `0..f-1`.
  - one_off: `start_at` (ISO datetime).
- [ ] **Step 4: Copy and run.** Run `cp crop-steering-engine/src/crop_steering_engine/{ids,timers}.py addons/f2_control/f2_control/crop_steering_engine/ && cp crop-steering-engine/src/crop_steering_engine/{ids,timers}.py custom_components/crop_steering/generated/`. Then run the Step 2 command plus `PY tests/test_generated_copies.py -q` and `diff -r --exclude=__pycache__ crop-steering-engine/src/crop_steering_engine addons/f2_control/f2_control/crop_steering_engine`. Expected: PASS, and no diff output.
- [ ] **Step 5: Commit** the engine, vendored copies, generated copies and test. Subject: `feat(engine): ULID ids and pure timer-program projection`.

### Task 2: Engine `flow` and `guards` arithmetic

**Files:**
- Create: `crop-steering-engine/src/crop_steering_engine/{flow,guards}.py`. Vendor both into the add-on, and vendor `guards.py` into `custom_components/crop_steering/generated/guards.py` with a new pair in `tests/test_generated_copies.py` (ruling R9: no hand copy).
- Test: `crop-steering-engine/tests/test_flow.py`, `crop-steering-engine/tests/test_guards_math.py`

**Interfaces:**
- Produces:
  - `flow.to_litres(value: float, unit: str | None) -> float | None`. Accepts `L`, `l`, `m³`, `gal` (US, 3.785411784). Any other unit gives `None`.
  - `flow.reconcile(commanded_l: float, metered_l: float | None) -> dict`. Returns `{"ratio": float|None, "verdict": "ok"|"low"|"high"|"unmetered"}`, with `low` below 0.80 and `high` above 1.20.
  - `flow.LOW = 0.80`, `flow.HIGH = 1.20`
  - `guards.zone_demand_lph(plant_count: int, drippers_per_plant: int, dripper_flow_rate: float) -> float`
  - `guards.capacity_ok(running_lph: list[float], this_lph: float, max_flow_lph: float | None, max_concurrent: int) -> bool`
  - `guards.worst_case_lph(zones: dict[int, float], groups: dict[int, str | None], max_concurrent: int) -> float`. This is the largest sum over any `max_concurrent` zones, with no two from one group.
  - `guards.PRIORITY = {"rescue": 0, "steering": 1, "timer": 2, "manual": 3}`
  - `guards.order(intents: list[dict]) -> list[dict]`. A stable sort by `PRIORITY[i["priority"]]`, then `i["requested_at"]`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_half_the_water_is_low():                      # G4 accept
    assert reconcile(2.4, 1.2) == {"ratio": 0.5, "verdict": "low"}
def test_no_meter_is_unmetered(): assert reconcile(2.4, None)["verdict"] == "unmetered"
def test_ratio_bounds_are_inclusive_ok(): assert reconcile(1.0, 0.8)["verdict"] == reconcile(1.0, 1.2)["verdict"] == "ok"
def test_unknown_unit_is_not_guessed(): assert to_litres(5, "pulses") is None and to_litres(1, "m³") == 1000.0
def test_two_zones_at_60_pct_cannot_share_the_pump():  # G1 accept
    assert capacity_ok([], 600, 1000, 2) and not capacity_ok([600], 600, 1000, 2)
def test_no_flow_limit_still_counts_zones_at_once(): assert capacity_ok([5000], 5000, None, 1) is False and capacity_ok([], 5000, None, 1)
def test_worst_case_respects_groups():
    assert worst_case_lph({1: 500, 2: 500, 3: 300}, {1: "a", 2: "a", 3: None}, 2) == 800
def test_rescue_jumps_the_queue_fifo_within_priority(): ...
```

- [ ] **Step 2: Run them and see them fail.** Run `PYTHONPATH=crop-steering-engine/src PY crop-steering-engine/tests/test_flow.py crop-steering-engine/tests/test_guards_math.py -q`. Expected: FAIL, import error.
- [ ] **Step 3: Implement as specified.** `capacity_ok` refuses when `len(running) + 1 > max_concurrent`. When `max_flow_lph` is not `None`, it also refuses when `sum(running) + this > max_flow_lph`.
- [ ] **Step 4: Vendor and run.** Run `cp` into `addons/f2_control/f2_control/crop_steering_engine/` and `cp .../guards.py custom_components/crop_steering/generated/`. Then run the Step 2 command, `PY tests/test_generated_copies.py -q` and the `diff -r` from Task 1. Expected: PASS.
- [ ] **Step 5: Commit.** Subject: `feat(engine): flow reconciliation and pump-capacity arithmetic`.

### Task 3: Pin today's held reasons word-for-word

**Files:**
- Test: `addons/f2_control/tests/test_held_reasons_pinned.py` (new; uses `test_controller._build`/`_desc`, `fake_ha.FakeHA`)

**Interfaces:**
- Consumes: `Controller._blocked(room, zone, reason=None)`, `Controller._execute_shot(...)`, `Controller._act_zone(...)`.
- Produces: the characterisation suite that Tasks 10, 12 and 15 must keep green.

- [ ] **Step 1: Write the pin tests.** Use one parametrised test per stage, built from small state tweaks on a one-zone room with prefix `""` and `valves={1: "switch.v1"}`. The asserted strings come verbatim from `controller.py`:

```python
PASS_STAGE = [  # (state tweak, expected _blocked(...) result)
  ("archived",        "Room archived in integration setup"),
  ("room_off",        "Room off (nothing growing)"),
  ("batch_running",   "making a batch"),
  ("max_run_latched", "max-run latch: 3 shots in a row cut to the longest allowed shot; fix its Repairs card (CS-312) to water again"),
  ("kill_off",        "Crop Steering Controller disabled (kill switch off)"),
  ("zone_off",        "zone disabled"),
  ("zone_unreadable", "switch.crop_steering_zone_1_enabled unreadable (reads neither on nor off)"),  # the zone switch, not the valve
  ("manual_override", "manual override"),
  ("external_hold",   "external hold (flush)"),
  ("tank_min",        "tank at its minimum (reads 8.0 %)"),
  ("feed_ec_out",     "source-water EC 4.0 out of [0,1]"),
  ("feed_ph_dead",    "source-water pH probe dead >30min — holding (fail-closed)"),
]
@pytest.mark.parametrize("tweak,held", PASS_STAGE)
def test_pass_stage_reason_is_pinned(tweak, held): ...
def test_first_hold_wins_in_todays_order(): ...  # kill_off + zone_off + tank_min -> "Crop Steering Controller disabled (kill switch off)"
PREOPEN = [("inflight", "[default] Z1 shot held: an interrupted shot's hardware is not accounted for yet"),
           ("token_refused", "[default] Z1 shot held: Home Assistant refuses this controller's token"),
           ("batch_running", "[default] Z1 shot held: making a batch")]
@pytest.mark.parametrize("tweak,line", PREOPEN)
def test_preopen_stage_log_is_pinned(tweak, line, capsys): ...
def test_daily_cap_hold_is_pinned(capsys): ...  # log contains "BLOCK daily-cap (0.00 L left)"
```

Read `MAX_RUN_IN_A_ROW` and the `feed_grace_min` default from the module rather than hard-coding them, and build the string with them.

- [ ] **Step 2: Run them.** Run `PY addons/f2_control/tests/test_held_reasons_pinned.py -q`. Expected: PASS on today's code. If a string differs, fix the test to today's text and never the other way round.
- [ ] **Step 3: Commit.** Subject: `test(controller): pin every held reason word for word`.

### Task 4: Journal store (SQLite)

**Files:**
- Create: `custom_components/crop_steering/journal.py`
- Test: `tests/test_journal.py`

**Interfaces:**
- Produces:
  - `KINDS: frozenset[str]` (spec §2.8 list), `ACTORS`, `OUTCOMES`, `SHORT_KINDS = ("shot.", "intent.", "flow.")`, `SHORT_DAYS = 400`
  - `validate_event(ev: dict) -> dict`, which raises `ValueError`. The id check uses `ULID_RE` imported from `.generated.ids` (Task 1), not a second regex.
  - `KINDS` includes `run.saved|archived` and `harvest.recorded` so AiGrow can rely on the enum. Nothing in this plan emits them yet (see Self-review).
  - `class Journal`, all methods synchronous (run in the executor by Task 5):
    - `__init__(self, path: str)`
    - `open(self) -> None`. Creates `events(id TEXT PRIMARY KEY, room_id TEXT, seq INTEGER, ts TEXT, ts_ms INTEGER, kind TEXT, zone INTEGER, actor TEXT, intent_id TEXT, body TEXT, UNIQUE(room_id, seq))`, the indexes `(room_id, ts_ms)`, `(room_id, kind, ts_ms)` and `(intent_id)`, and `meta(key TEXT PRIMARY KEY, value TEXT)`.
    - `append(self, room_id: str, events: list[dict]) -> dict`. Returns `{"accepted": [id], "duplicate": [id], "seq_max": int, "stored": [event]}`.
    - `query(self, room_id: str, since: str, until: str | None = None, kinds: list[str] | None = None, zones: list[int] | None = None, actor: str | None = None, limit: int = 500, cursor: str | None = None, order: str = "asc") -> dict`. Returns `{"events": [...], "cursor": str | None}`.
    - `prune(self, now_ms: int) -> int`
    - `meta_get(self, key) -> str | None`, `meta_set(self, key, value) -> None`
    - `close(self)`

- [ ] **Step 1: Write the failing tests.** Use `tmp_path`, no HA.

```python
def test_append_assigns_per_room_monotonic_seq_and_is_idempotent(tmp_path):
    j = _open(tmp_path); a, b = _ev("shot.completed"), _ev("phase.changed")
    r1 = j.append("room:f2_", [a, b]); r2 = j.append("room:f2_", [a])
    assert r1["accepted"] == [a["id"], b["id"]] and r1["seq_max"] == 2
    assert r2 == {"accepted": [], "duplicate": [a["id"]], "seq_max": 2, "stored": []}
    assert j.append("room:", [_ev("shot.completed")])["seq_max"] == 1   # other room counts alone
def test_query_filters_kind_zone_actor_and_pages_with_cursor(tmp_path): ...  # 7 events, limit 3 -> 3,3,1, cursor None at end
def test_query_orders_by_instant_not_by_offset_text(tmp_path): ...  # "+13:00" vs "Z" timestamps
def test_prune_drops_old_shots_but_keeps_changes_forever(tmp_path): ...  # 401-day-old shot.completed gone, target.changed kept
@pytest.mark.parametrize("bad", [{"v": 2}, {"kind": "nope"}, {"source": {"actor": "robot"}}, {"outcome": "meh"}, {"id": "short"}])
def test_validate_event_refuses(bad): ...
def test_limit_is_capped_at_500(tmp_path): ...
```

- [ ] **Step 2: Run them and see them fail.** Run `PY tests/test_journal.py -q`. Expected: FAIL, import error.
- [ ] **Step 3: Implement `journal.py`.**
  - `check_same_thread=False` with one `threading.Lock`.
  - `ts_ms` is parsed with `datetime.fromisoformat`.
  - `body` is the full event JSON after `seq` is stamped.
  - The cursor is `f"{ts_ms}:{seq}"`.
- [ ] **Step 4: Run them.** Run `PY tests/test_journal.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** Subject: `feat(integration): per-room event journal on SQLite`.

### Task 5: `journal_append`, `journal_query`, the bus event and `emit()`

**Files:**
- Create: `custom_components/crop_steering/journal_api.py`
- Modify: `custom_components/crop_steering/__init__.py` (call `async_setup_journal(hass)` in `async_setup_entry`, after notify; unload with the last room), `services.yaml` (2 entries), `const.py` (`EVENT_JOURNAL = "crop_steering_event"`)
- Test: `tests/test_journal_api.py`, `tests_ha/test_journal_services.py`

**Interfaces:**
- Consumes: `Journal` (Task 4), `ids.new_id` (via `generated/ids.py`, Task 1).
- Produces:
  - `async_setup_journal(hass) -> None`. Puts a site-wide `JournalHub` in `hass.data[DOMAIN]["_journal"]`. The DB path is `hass.config.path("crop_steering", "journal.db")`.
  - `class JournalHub`, with `ok: bool`, `async append(room_id, events) -> dict`, `async query(**kw) -> dict` and `emit(...)` below.
  - `emit(hass, room_id: str, kind: str, *, zone=None, outcome="ok", code=None, actor="system", detail=None, user_id=None, client=None, data=None, correlation=None, readback=None) -> str | None`. Fire-and-forget: it schedules the append and returns the event id, or `None` when the hub is missing or not ok. It never raises.
  - `attribution(hass, call) -> dict`. Returns `{"actor", "user_id", "client", "proposal_token"}` using the setpoint_log rule:
    - `call.data["client"]` of `mcp` or `aigrow` → that actor;
    - a user without a client → `manual`;
    - no user → `automation`.
  - Services:
    - `journal_append {room_id, events[≤50]}`: admin, OPTIONAL response.
    - `journal_query {room_id, since, until?, kinds?, zones?, actor?, limit≤500, cursor?}`: signed-in, ONLY response.
  - Each stored event is re-fired as `hass.bus.async_fire(EVENT_JOURNAL, event)`.
  - Websocket command `crop_steering/subscribe {rooms?: [room_id], kinds?: [str]}`, registered with `websocket_api.async_register_command` in `async_setup_journal`:
    - It needs any signed-in user, because HA's `subscribe_events` refuses non-admins for custom event types.
    - It sends `{"type": "event", "event": <§4 event>}` for each stored event that matches the filter.
    - It unsubscribes on connection close.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_journal_api.py (ha_stubs; FakeServices patched for supports_response as in tests/test_setup_services.py:28)
def test_append_fires_each_new_event_once_on_the_bus(tmp_path): ...  # 2 events + 1 repeat -> 2 bus fires
def test_append_refuses_more_than_50_events(): ...           # HomeAssistantError "at most 50"
def test_a_journal_that_cannot_open_logs_and_emit_is_a_noop(tmp_path, caplog): ...  # path is a directory -> hub.ok False; emit() returns None
def test_attribution_follows_the_setpoint_log_rule(): ...    # client mcp -> mcp; user -> manual; none -> automation
# tests_ha/test_journal_services.py (real HA)
async def test_query_round_trips_what_append_stored(hass): ...  # journal_append then journal_query return_response=True; events[0]["seq"] == 1
async def test_query_needs_a_signed_in_user_and_append_an_admin(hass, hass_read_only_user): ...
async def test_a_non_admin_websocket_subscriber_gets_only_its_rooms_events(hass, hass_ws_client, hass_read_only_access_token): ...  # 2 rooms appended, filter rooms=["room:f2_"] -> 1 message
async def test_subscribe_without_a_user_is_refused(hass, hass_ws_client): ...
```

- [ ] **Step 2: Run them and see them fail.** Run `PY tests/test_journal_api.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `journal_api.py`.** Follow `notify_api.async_setup_notify` (one handler, `async_require_admin`, `ValueError` → `HomeAssistantError`). Every DB call goes through `hass.async_add_executor_job`. Prune once at setup and then daily through `async_track_time_interval`.
- [ ] **Step 4: Run them.** Run `PY tests/test_journal_api.py -q`, then the Docker `tests_ha/test_journal_services.py`. Expected: PASS.
- [ ] **Step 5: Commit.** Subject: `feat(integration): journal_append, journal_query and crop_steering_event`.

### Task 6: Integration-side producers write to the Journal

**Files:**
- Modify:
  - `setpoint_log.py` (`record` → `target.changed`)
  - `setup_api.py` (`save_setup`, `setup_create`, `setup_remove` → `config.changed {store: "setup", section, diff[]}`)
  - `strategy.py` (`save` / `activate` / `disarm` / `_advance` → `plan.saved|armed|disarmed|activated|expired`)
  - `overlays.py` (keep/undo → `target.changed {layer: "overlay"}`)
  - `calibration.py` (`calibration_record` → `calibration.captured {applied: false}`). This task owns `calibration.py` before lane K starts.
  - `stock_api.py` (refill → `stock.refilled`; draw → `stock.drawn`)
- Test: `tests/test_journal_producers.py`, `tests_ha/test_journal_producers.py`

**Interfaces:**
- Consumes: `journal_api.emit`, `journal_api.attribution`.
- Produces these event `data` shapes (spec §4):
  - `target.changed {key, scope: "room"|"zone:N", layer: "base"|"overlay", old, new, expires, reason, expected, entity_id}`. `actor` is mapped from the setpoint_log `who`: `operator→manual`, `home_assistant→automation`, `learner→learner`, `brain→ai`, `safety→safety`.
  - `config.changed {store, section, old, new, diff: [{path, old, new}]}`. `old`/`new` are the whole section before and after (ruling R8).
  - `plan.* {revision, status}`
  - `stock.drawn {tank, ml, source, key}`

- [ ] **Step 1: Write the failing tests.**

```python
def test_a_learner_write_is_journaled_as_learner_with_old_and_new(): ...  # claim who=learner -> actor "learner", data.old/new
def test_an_operator_write_is_manual_with_the_user_id(): ...
def test_an_unchanged_value_journals_nothing(): ...                      # mirrors setpoint_log "no row when old == new"
def test_a_journal_that_is_down_never_stops_a_setpoint_write(): ...      # emit raises inside -> record still stores the row
async def test_setup_save_emits_config_changed_with_the_diff(hass): ...  # tests_ha
async def test_strategy_activate_emits_plan_armed(hass): ...             # tests_ha
```

- [ ] **Step 2: Run them and see them fail.** Run `PY tests/test_journal_producers.py -q`. Expected: FAIL.
- [ ] **Step 3: Add one `emit(...)` call after each successful write.** Wrap each in `try/except Exception: _LOGGER.debug(...)`. `setup_api` computes `diff` from the old and new `setup_room(...)` dicts, flattened to dotted paths.
- [ ] **Step 4: Run them.** Run the stub and Docker tests above plus `PY tests/test_setup.py tests/test_strategy.py tests/test_stock_api.py -q` (no regressions). Expected: PASS.
- [ ] **Step 5: Commit.** Subject: `feat(integration): journal every setpoint, setup, plan, overlay, calibration and stock change`.

### Task 7: Backfill the Journal from the old stores (M2, integration side)

**Files:**
- Modify: `journal.py` (pure importers), `journal_api.py` (run them once per room after setup)
- Test: `tests/test_journal_backfill.py`

**Interfaces:**
- Produces:
  - `import_setpoint_log(room_id, rows) -> list[event]`, `import_stock_history(room_id, rows)`, `import_calibration(room_id, records)`, `import_overlays(room_id, rows)`
  - Ids: `derived_id(at, f"{source}:{room_id}:{row-key}")`. The row key is `entity_id|at|new` for setpoint rows, `key` or `at` for stock, `id` for calibration, and `entity_id|at` for overlays.
  - `meta` key `backfill:<room_id>:v1` = `"done"`.
  - Source stores stay untouched.

- [ ] **Step 1: Write the failing tests.**

```python
def test_backfill_is_idempotent_by_derived_id(tmp_path): ...    # run twice -> second run all duplicate
def test_setpoint_rows_become_target_changed_with_their_writer(): ...  # who "learner" -> actor learner, ts == row["at"]
def test_backfill_runs_once_per_room(tmp_path): ...             # meta flag set; second setup does not re-read stores
```

- [ ] **Step 2: Run them and see them fail.** Run `PY tests/test_journal_backfill.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement the importers.** Trigger them from `async_setup_journal` for each loaded room once its stores exist: `hass.data[DOMAIN]["_setpoint_log"|"_stock"|"_calibration"|"_overlays"][entry_id]`. A missing store is skipped.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit.** Subject: `feat(integration): backfill the journal from setpoint, stock, calibration and overlay history`.

### Task 8: Controller outbox and shot, phase, held and alert events

**Files:**
- Create: `addons/f2_control/f2_control/journal_out.py`
- Modify:
  - `addons/f2_control/f2_control/controller.py`:
    - `__init__`: `self.journal = Outbox(os.path.join(os.path.dirname(self._state_path), "journal_outbox.jsonl"))`
    - `loop_once`: `self._flush_journal()` as the **last** statement, after `_send_events`
    - `_act_zone`, `_execute_shot`, `_record_phase`, `_alert`, `_dismiss`
  - `addons/f2_control/tests/fake_ha.py`: `responses: dict[(domain, service), callable]` consulted by `ha_service_response`, honouring its `timeout` kw
- Test: `addons/f2_control/tests/test_journal_outbox.py`, `addons/f2_control/tests/test_journal_emits.py`

**Interfaces:**
- Consumes: `crop_steering_engine.ids.new_id`, `ha_service_response`.
- Produces:
  - `class Outbox`:
    - `__init__(self, path: str, cap: int = 5000)`
    - `emit(self, room_prefix: str, kind: str, *, zone=None, outcome="ok", code=None, actor="engine", detail=None, program_id=None, data=None, correlation=None, readback=None, durable=False, now: datetime | None = None) -> str`
      - The first argument is the room **prefix** (`""`, `"f2_"`), never the slug. The event's `room_id` is `"room:" + prefix`.
      - `durable=True` fsyncs; it is used only for `shot.started`. Every other emit is a plain buffered append.
    - `pending(self) -> list[dict]`
    - `flush(self, send, batch: int = 50, max_batches: int = 4) -> int`. `send(room_id, events) -> tuple[list[str], list[str]] | None`. A `None` return stops the flush.
  - `Controller._flush_journal(self) -> None`:
    - It calls `ha_service_response("crop_steering", "journal_append", {...}, timeout=1)`.
    - After a failure it skips the next `JOURNAL_BACKOFF_PASSES = 5` passes.
    - It is called only at the end of `loop_once`, never from `_execute_shot`, `_wait_shot` or `_keep_alive`.
  - `Controller._journal_held(self, room, zone, reason: str, *, guard: str | None = None, code: str | None = None, now) -> None`.
    - It dedupes on `(slug, zone, reason)` and re-emits after `HELD_REEMIT_S = 1800`.
    - It is called only from the act loop (`_act_zone` and the pre-open path), never inside `_blocked`. `_blocked` is also used for display (`_publish_waiting_for` gates).
  - `_execute_shot` keeps its existing `steering=True` kw and gains `actor: str = "engine"`, `program_id: str | None = None`, `reason_text: str | None = None` and `requested_at: datetime | None = None`. There is **no** `kind` kw. The shot kind comes from `reason.kind` in `_act_zone`.
  - `client` in `source` is `f"f2_control/{VERSION}"`.
- Event points:
  - `shot.started` is written durably **before** the pump opens. Data: `{phase, kind, reason, size_pct, duration_s, commanded_l, vwc_before, vwc_expected, requested_at, pump_wait_s}`, with a new `correlation.intent_id`.
    - `reason` is the engine `Reason` text, the same words as today's FIRE log line.
    - `vwc_expected` is `vwc_before + snap.p1_expected_rise` **only in P1**, and `None` otherwise. `ZoneSnapshot.p1_expected_rise` is already absolute VWC points for one P1 shot, not a rate.
    - `requested_at` is when this pass decided to fire. `pump_wait_s = started − requested_at`, in seconds.
  - `shot.completed` carries `{elapsed_s, commanded_l, metered_l: None, vwc_before, ec_before}` (spec §4), `readback {status: "verified", entities}`, and the same `correlation.intent_id` as its `shot.started`. Task 26 fills `metered_l`.
  - `shot.aborted` has outcome `aborted` or `failed`, the CS-30x code and the same `intent_id`.
  - `phase.changed {from, to, how}`
  - `alert.raised {key, title}` with `code`, emitted only when `_alert_due` lets it through.
  - `alert.cleared {key}`, from `_dismiss`. The other 12 direct `dismiss` sites are covered by Task 27's reconciliation.
  - `intent.held {reason, guard?, would}`
- `_auto_write` emits nothing. The integration's `setpoint_log` already journals that write as `target.changed` with the claimed writer (Task 6), and a second event would duplicate it.

- [ ] **Step 1: Write the failing tests.**

```python
def test_emit_appends_one_json_line_and_flush_removes_accepted_and_duplicate(tmp_path): ...
def test_outbox_caps_at_5000_dropping_oldest(tmp_path): ...
def test_flush_stops_at_the_first_failed_batch(tmp_path): ...       # send returns None -> 1 call, lines kept
def test_outbox_never_blocks_a_shot_when_the_integration_refuses(): ...  # FakeHA journal_append -> (400, None) every pass; shot still fires, same switch calls as baseline
def test_a_hung_integration_adds_under_1_5_s_to_a_pass(): ...       # journal_append handler sleeps 30 s (honours timeout=1): monotonic delta of loop_once < 1.5 s vs baseline
def test_flush_backs_off_for_5_passes_after_a_failure(): ...
def test_no_flush_happens_between_pass_start_and_the_last_shot(): ...  # FakeHA records call order: every journal_append after the last switch off
def test_shot_started_is_on_disk_before_the_pump_switch_is_called(): ...  # FakeHA hw hook reads outbox file when pump turns on
def test_a_completed_shot_carries_verified_readback_litres_and_the_started_intent_id(): ...
def test_shot_started_carries_reason_phase_vwc_before_and_expected(): ...  # P1: vwc_expected == vwc_before + p1_expected_rise; P2: None; pump_wait_s == 0
def test_a_standing_hold_is_journaled_once_per_reason_and_every_30_min(): ...  # 40 passes, kill switch off -> 2 intent.held
def test_publishing_waiting_for_journals_nothing(): ...
def test_room_id_comes_from_the_prefix_not_the_slug(): ...          # slug "f2", prefix "f2_" -> room_id "room:f2_"
def test_phase_change_and_alert_are_journaled(): ...
def test_old_state_file_without_outbox_still_loads(): ...           # no outbox file -> starts empty
```

- [ ] **Step 2: Run them and see them fail.** Run `PY addons/f2_control/tests/test_journal_outbox.py addons/f2_control/tests/test_journal_emits.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `Outbox` appends with `open(..., "a")`, plus `os.fsync` only when `durable`.
  - `flush` and the cap rewrite go through tmp + `os.replace`.
  - `_flush_journal` groups by `room_id` and reads `accepted`/`duplicate` on status 200.
  - Every emit is wrapped in `try/except Exception` with one log line per run.
- [ ] **Step 4: Run them, then the regressions.** Run the Step 2 tests plus `PY addons/f2_control/tests/test_held_reasons_pinned.py addons/f2_control/tests/test_controller.py addons/f2_control/tests/test_safety_regressions.py addons/f2_control/tests/test_heartbeat_during_shots.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** Subject: `feat(controller): journal outbox for shots, phases, holds and alerts`.

### Task 9: Dosing and brain events, and controller-side backfill

**Files:**
- Modify:
  - `dosing_runner.py`: `_begin`/`_done`/`_skip` → `batch.step`; `_verdict` → `dose.completed`; the failed paths → `batch.failed` with CS-80x
  - `brain/ledger.py`: optional `listener: Callable[[str, dict], None] | None` called from `record` and `resolve`
  - `brain_bridge.py`: wires `ledger.listener` to `c.journal.emit` (`ai.judgement` / `ai.outcome`)
  - `controller.py`: once per room when that room's state block lacks `_journal_backfill: 1`, emit derived-id events for that room's `dosing_state.json` `history` and `jev_ledger.jsonl` rows, then set the flag.
    - The flag lives **inside each room block**, like `_strategy_required`: add it to the keys `_save_state` writes and `_load_room_state` reads.
    - A top-level key would be read back as a room.
    - This task edits `controller.py` (lane C's file), so it runs after Task 8 and before Task 10.
  - `brain_bridge.py` maps the ledger row's `room` (a **slug**) to `room.prefix` before calling `Outbox.emit`.
- Test: `addons/f2_control/tests/test_journal_dosing_brain.py`

**Interfaces:**
- Consumes: `Outbox.emit`, `ids.derived_id`.
- Produces these data shapes:
  - `batch.step {step: hold|close|fill|mix|premix|dose|postmix|finish, state, recipe}` with `correlation.batch_id` = the job id
  - `dose.completed {pump, ml, given_ml, flow_ml_s}`
  - `ai.judgement {judge, label, action, power, evidence}` with `correlation.ledger_id = str(row["id"])` (ledger ids are ints)
  - `ai.outcome {what, good}`
  - Backfill ids are `derived_id(at, f"dosing:{slug}:{at}:{kind}")` and `derived_id(at, f"ledger:{row_id}")`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_every_batch_step_shares_one_batch_id(): ...   # reuse test_dosing_runner fixtures; 8 steps in order
def test_a_dose_journals_given_ml(): ...
def test_a_ledger_record_and_resolve_mirror_as_judgement_and_outcome(): ...
def test_backfill_runs_once_and_ids_are_stable(): ...  # flag saved in the room block; second start emits nothing
def test_backfill_flag_is_not_read_back_as_a_room(): ...  # state.json round trip: rooms == {slug}
def test_a_ledger_row_for_slug_f2_lands_in_room_f2_(): ...
```

- [ ] **Step 2: Run them and see them fail.** Run `PY addons/f2_control/tests/test_journal_dosing_brain.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement the emits next to the existing history writes.** Remove nothing.
- [ ] **Step 4: Run them and the dosing suites.** Run `PY addons/f2_control/tests/test_journal_dosing_brain.py addons/f2_control/tests/test_dosing_runner.py addons/f2_control/tests/test_dosing_safety.py -q`. Expected: PASS.
- [ ] **Step 5: Commit.** Subject: `feat(controller): journal batches, doses and AI judgements; backfill their history`.

### Task 10: GuardChain refactor with identical semantics

**Files:**
- Create: `addons/f2_control/f2_control/guards.py`
- Modify: `controller.py`. `_blocked` iterates `guards.PASS`. The pre-open checks in `_execute_shot` iterate `guards.PREOPEN`. The daily cap in `_act_zone` goes through `guards.SIZED`. Each hold calls `_journal_held(..., guard=g.guard, code=g.code)`.
- Test: `addons/f2_control/tests/test_guard_chain.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Guard: key: str; guard: str; stage: str; code: str | None; check: Callable` where `check(c, room, zone, ctx) -> str | None`.
  - `PASS: tuple[Guard, ...]`, `PREOPEN: tuple[Guard, ...]`, `SIZED: tuple[Guard, ...]`
  - `first(owner, stage: tuple[Guard, ...], room, zone, ctx) -> tuple[Guard, str] | None`.
    - `owner` is whatever the stage's checks need: the `Controller` for PASS, PREOPEN and SIZED, and the `DosingRunner` for Task 13's DOSE stages.
    - Each `check(owner, room, zone, ctx)` reaches the controller as `owner` or as `owner.c`.
  - **PASS has 21 guards**, matching the 21 keys `gate_report.report()` emits today. `feed_ec` and `feed_ph` are two guards, both with guard id `source_water`.
  - `ctx` is `{"reason", "litres", "duration_s", "plan_exempt", "kind"}`.
- **The order is today's order.** Spec ids are mapped onto the `gate_report` keys:

| key (`gate_report`) | guard id | key | guard id |
|---|---|---|---|
| setup | setup_behind | retired | kill_switch |
| archived | kill_switch | zone_on | zone_paused |
| room_on | kill_switch | manual_override | manual_override |
| dosing | dosing_hold | external_holds | external_hold (**not in spec**) |
| plan | plan_hold | waste | waste_closed |
| hardware_fault | hardware_latch | settings | settings_loaded (**not in spec**) |
| max_run | hardware_latch | tank | tank_min |
| valve_mapped | plumbing | feed_ec | source_water |
| plumbing | plumbing | feed_ph | source_water |
| | | online | plumbing |
| switchable | plumbing | | |
| kill_switch | kill_switch | | |

  - PREOPEN: `hardware_latch, auth, inflight, plumbing, plumbing(undrivable), plan_hold, tank_min(short), waste_closed, dosing_hold`
  - SIZED: `daily_cap`

- [ ] **Step 1: Write the failing tests.**

```python
def test_pass_stage_order_matches_a_live_gate_report(): ...  # a room with a valve: [g.key for g in guards.PASS] == list(gate_report.report(c, room, 1, None)) keys, from report()'s inline keys, not a shared constant
def test_preopen_order_is_todays(): assert [g.guard for g in guards.PREOPEN] == ["hardware_latch","auth","inflight","plumbing","plumbing","plan_hold","tank_min","waste_closed","dosing_hold"]
def test_a_held_intent_names_its_guard_and_code(): ...  # tank_min -> intent.held data.guard "tank_min", code "CS-901"
```

- [ ] **Step 2: Run them and see them fail.** Run `PY addons/f2_control/tests/test_guard_chain.py -q`. Expected: FAIL.
- [ ] **Step 3: Move each existing check into a small `check` function that calls the existing helper unchanged**, keeping every side effect (alerts, `_close_waste` actuation, `_max_run_hold` release, the `_shot_lock` around `dosing_hold`). `_blocked` returns `first(...)[1]` or `None`.
- [ ] **Step 4: Run everything in the add-on suite.** Run `PY addons/f2_control/tests -q`. Expected: PASS, including `test_held_reasons_pinned.py` and `test_gate_report.py` unchanged. Those two are the real regression gate; no test here restates them.
  - `gate_report.report()` stays a side-effect-free second reading of the same checks, and the live-order test keeps the two in step.
- [ ] **Step 5: Commit.** Subject: `refactor(controller): one ordered GuardChain for every shot check`.

### Task 11: Site store and `supply_get` / `supply_save`

**Files:**
- Create:
  - `custom_components/crop_steering/site_store.py`: store `crop_steering.site`, version 1, doc `{schema_version: 2, revision, irrigation_pumps, water_sources, zone_groups, zone_meters, presets, alert_rules}`
  - `custom_components/crop_steering/site_api.py`: services, plus the publisher of `sensor.crop_steering_supply_config`
- Modify: `__init__.py`, `services.yaml`
- Test: `tests/test_site_store.py`, `tests_ha/test_supply.py`

**Interfaces:**
- Consumes: `generated/guards.py` (Task 2): `worst_case_lph`, `zone_demand_lph`. No hand copy (ruling R9).
- Produces:
  - `supply_get {} -> {revision, irrigation_pumps, water_sources, zone_groups, zone_meters, capacity_check: {worst_case_lph, max_flow_lph, ok, suggest_max_concurrent, pairs}}`.
    - `pairs` lists one row per unordered pair of active zones on the same pump: `[{zones: [a, b], lph, pct_of_pump, verdict: "together"|"one_after_another"}]`.
    - `zones` are int zone numbers within one room. A cross-room pair carries `{room_id, zone}` objects instead.
    - `lph` is the sum of both zones' demand. `pct_of_pump = lph / max_flow_lph × 100`, unrounded, or `None` without `max_flow_lph`.
    - `verdict` is `one_after_another` when both share an exclusive group, `max_concurrent_zones < 2`, or `lph > max_flow_lph`; otherwise `together`.
  - `supply_save {expected_revision, irrigation_pumps[], water_sources[], zone_groups{"room:f2_": {"3": "a"}}, zone_meters{"room:f2_": {"3": "sensor.f2_meter_3"}}, preview?: bool}`.
    - It answers with the same shape plus `readback`.
    - With `preview: true` it validates and returns `{diff, capacity_check}` and writes nothing. MCP's `preview_supply` uses this.
  - Error `pump_over_capacity` (a `HomeAssistantError` message starting with `pump_over_capacity:`). The v2 envelope maps it to `invalid` and keeps the message (Task 23).
  - `IrrigationPump` = `{entity_id, max_flow_lph?, max_concurrent_zones: int = 1, flow_meter?}`
  - Published state `sensor.crop_steering_supply_config`: state = revision; attrs = `irrigation_pumps`, `zone_groups`, `zone_meters`, and `zone_demand_lph{"room:f2_": {"3": float}}` computed with `generated/guards.zone_demand_lph` from each room's `setup_api.setup_sizing`.
  - `config.changed {store: "site", section: "supply", old, new, diff}`

- [ ] **Step 1: Write the failing tests.**

```python
def test_missing_store_reads_as_no_supply(): ...                  # irrigation_pumps == [], capacity_check.ok True
def test_save_refuses_a_stale_revision(): ...
def test_save_refuses_concurrency_the_pump_cannot_feed(): ...     # 6 zones x 240 L/h, max 1200, concurrent 6 -> "pump_over_capacity: ... Set Zones at once to 5 or less."
def test_groups_lower_the_worst_case(): ...
def test_preview_writes_nothing(): ...
def test_capacity_pairs_say_together_or_one_after_another(): ...  # 1200 L/h pump, concurrent 2: zones 480+480 -> together, pct 80.0; 720+720 -> one_after_another; same group -> one_after_another
async def test_supply_save_publishes_the_descriptor_and_reads_back(hass): ...  # tests_ha
```

- [ ] **Step 2: Run them and see them fail.** Run `PY tests/test_site_store.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Follow `display.py` (store + revision + publish) and `dosing_api` (handler + admin). Zone demand and the worst case come from `generated/guards.py`.
- [ ] **Step 4: Run them.** Run the stub tests and Docker `tests_ha/test_supply.py`. Expected: PASS.
- [ ] **Step 5: Commit.** Subject: `feat(integration): site store with pump capacity, exclusive groups and meters`.

### Task 12: Guards 16–17 and the pump queue (controller)

Ruling R1 and spec §2.7 decide this task: guards 16–17 **queue, never refuse**. With the synchronous controller (see Spec gaps 2), here is what they can and cannot do.

- **They can:**
  - order the zones that fire in one pass, rescue first, with FIFO by `requested_at` inside a priority;
  - journal `intent.queued` and publish who is waiting;
  - warn about a zone that alone needs more than its pump.
- **They cannot:**
  - add concurrency. `max_concurrent_zones > 1` changes nothing at runtime.
  - prevent an overlap. Two valves are never open together today anyway.

  So guard 17 (`exclusive_group`) is recorded only. It is evaluated and shown on `shot_queued`, but it can never change what runs. Its tests assert ordering and events, not "no overlap", which was already true.

**Files:**
- Modify:
  - `addons/f2_control/f2_control/guards.py`: `QUEUE = (pump_capacity, exclusive_group)`. These checks return a `Queued` marker or `None` and **never** a held reason.
  - `controller.py`:
    - Read `sensor.crop_steering_supply_config` once per pass.
    - When the descriptor exists, the act loop visits this pass's firing zones in `crop_steering_engine.guards.order` (priority `rescue` for `RESCUE_KINDS` and `min_daily`, `steering`, `timer`, `manual`). Without it, the loop is today's loop, untouched.
    - Publish `sensor.crop_steering_<px>pump_load_pct` and `binary_sensor.crop_steering_<px>shot_queued` (attrs `queue: [{zone, position, requested_at, priority}]`).
    - `_alert(..., "CS-214", ...)` (warning) when a zone alone needs more than its pump's `max_flow_lph`. That zone **still waters**, rescues included. The alert is also raised when a queued intent has waited longer than `QUEUE_ALERT_S = 600`.
    - CS-214 is not added to `INFO_CODES` or `NOT_WATERING_CODES`.
  - CS-code files (Global Constraints; no bundle rebuild). The `notify_catalog` kind is `hardware`.
- Test: `addons/f2_control/tests/test_pump_queue.py`

**Interfaces:**
- Consumes: Task 11's descriptor attrs, `guards.capacity_ok`, `guards.order`, `guards.zone_demand_lph`.
- Produces:
  - `intent.queued {position, priority, requested_at, guard: "pump_capacity"|"exclusive_group"}`, emitted when a firing zone waits behind another in the same pass.
  - `shot.started.data.pump_wait_s` is the real wait.
  - Alert text: `f"zone {zone} needs {need:.0f} L/h, {pump} gives {max:.0f} L/h; it waters anyway"`, code CS-214.

- [ ] **Step 1: Write the failing tests.**

```python
def test_no_supply_descriptor_means_todays_order_and_no_events(): ...    # switch call sequence equals baseline
def test_two_zones_at_60_pct_take_turns_and_the_second_is_queued(): ...   # G1: intent.queued position 1; zone 2's shot.started after zone 1's completed
def test_a_rescue_runs_before_a_steering_shot_in_the_same_pass(): ...
def test_a_min_daily_floor_shot_is_never_held_by_capacity(): ...
def test_a_zone_bigger_than_its_pump_still_waters_and_warns_cs_214(): ... # switch ON calls happen; alert severity warning
def test_exclusive_group_is_recorded_but_changes_nothing(): ...            # same switch sequence with and without groups
def test_shot_queued_and_pump_load_are_published(): ...
def test_a_queued_shot_records_its_pump_wait(): ...  # second zone's pump_wait_s == first shot's elapsed ± 1 s
```

- [ ] **Step 2: Run them and see them fail.** Run `PY addons/f2_control/tests/test_pump_queue.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement as in Interfaces.**
  - Add the CS-214 entry to `docs/error-codes.json`: `source: notification`, `severity: warning`, title "Zone needs more than its pump", `watering` text "Water continues; the zone takes turns with the others on its pump."
  - Run `python scripts/render_error_codes.py` and add the code to `notify_catalog` kind `hardware`.
- [ ] **Step 4: Run them.** Run `PY addons/f2_control/tests -q` and `PY tests/test_error_codes.py tests/test_notify_catalog.py -q --deselect tests/test_error_codes.py::test_no_code_is_defined_twice`. Expected: PASS.
- [ ] **Step 5: Commit** (one commit: add-on and catalogue). Subject: `feat(controller): pump capacity and exclusive-valve queue, never a hold`. Body notes the deselected bundle test (ruling R11).

### Task 13: Guards 18–19 in the dosing runner

**Files:**
- Modify:
  - `addons/f2_control/f2_control/guards.py` (after Task 12; lane C's file):
    - `DOSE = (calibration_valid, dosing_lockout)` wraps `_uncalibrated` and `_ph_refuse` / `_batch_check` / the hold-entity checks unchanged.
    - `DOSE_RUN = (hardware_latch, inflight, calibration_valid, dosing_lockout)` is for the timed pump runs of Task 20. Its `hardware_latch`/`inflight` checks call `owner.c._hardware_fault_block` and `room.shot_inflight`.
  - `dosing_runner.py`: call `guards.first(DOSE, ...)` where those checks run today, and journal `intent.held` / `intent.refused`
- Test: `addons/f2_control/tests/test_dose_guards.py`

**Interfaces:**
- Consumes: `Guard`, `first(owner=DosingRunner, ...)` (Task 10).
- Produces: `intent.refused {guard: "calibration_valid", reason}` for `"{name} is not calibrated (flow missing)"`, and the same strings as today.

- [ ] **Step 1: Write the failing tests.**

```python
def test_an_uncalibrated_pump_is_refused_with_todays_words_and_journaled(): ...
def test_ph_lockout_refusal_names_dosing_lockout(): ...
```

- [ ] **Step 2: Run them and see them fail.** Then implement the wrappers, then run `PY addons/f2_control/tests/test_dose_guards.py addons/f2_control/tests/test_dosing_runner.py addons/f2_control/tests/test_ph_correct.py -q`. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `refactor(controller): dosing refusals go through the GuardChain`.

### Task 14: Timer programs and the `irrigation_mode` select (integration)

**Files:**
- Create: `custom_components/crop_steering/timers_api.py` (store `crop_steering.timers.<entry_id>`, version 1, doc `{revision, programs}`; publishes `sensor.crop_steering_<px>timers_config`)
- Modify:
  - `const.py`: `IRRIGATION_MODES = ["steering", "timer", "off"]`
  - `select.py`: the per-zone loop adds `SelectEntityDescription(key=f"zone_{n}_irrigation_mode", name=f"Zone {n} Watering by", options=IRRIGATION_MODES, icon="mdi:timer-cog-outline")`
  - `__init__.py`, `services.yaml`
- Test: `tests/test_timers_api.py`, `tests_ha/test_irrigation_mode.py`

**Interfaces:**
- Consumes: `generated/timers.py` (`validate`, `project`).
- Produces:
  - `timer_program_set {room_id, expected_revision, program}` → `{program, revision, preview: [{zone, at, duration_s}] (next 24 h)}`
  - `timer_program_delete {room_id, expected_revision, id}`, a soft delete (`active: false, deleted_at`)
  - `timer_program_preview {room_id, program, hours≤48}` → `{preview: [{zone, at, duration_s}], shots, total_s}`. It validates and projects but writes nothing, and works for a draft with no `id`.
  - `timer_program_list {room_id?}` → `{programs: [program + {next_at, zones_in_timer_mode: [int]}], revision}`. Omitting `room_id` returns every room's programs, each with its `room_id`. Soft-deleted programs are excluded.
  - `timer_skip {room_id, zone, at, expected_revision}` → `{skip: {zone, at, until}, revision}`.
    - It adds `{zone, at, until: at + 15 min, by}` to the store's `skips[]`.
    - Skips expire 24 h after `at` and are pruned on save.
    - One skip covers the planned timer shot **or** the planned engine shot the timeline showed at that time (Task 15).
    - It journals `config.changed {store: "timers", section: "skip"}`.
  - `timers_config` attrs `{revision, programs: [active only], skips: [{zone, at, until}]}`. `at` and `until` are ISO with offset, and consumers compare them as UTC instants, never as strings.
  - Python interface for Task 22: `get_programs(hass, entry_id) -> list[dict]` and `async set_programs(hass, entry_id, programs: list[dict], expected_revision: int, actor: dict) -> dict`.
  - Every save journals `config.changed {store: "timers", section, old, new, diff}`.
  - A zone may belong to at most one active program. Otherwise the error is `"Zone 3 is already in timer 'Mothers AM'"`.
  - `config.changed {store: "timers"}`

- [ ] **Step 1: Write the failing tests.**

```python
def test_set_returns_a_24h_preview_of_8_shots(): ...          # 08:00-12:00 recycle 30 min
def test_start_equal_end_is_refused_with_plain_words(): ...   # "End must be after start"
def test_a_zone_in_two_active_programs_is_refused(): ...
def test_missing_store_publishes_no_programs(): ...
def test_preview_of_a_draft_writes_nothing(): ...           # store revision unchanged
def test_list_without_room_returns_every_room_and_hides_deleted(): ...
def test_skip_is_published_and_expires_after_24h(): ...
async def test_fresh_install_has_select_zone_1_irrigation_mode_reading_steering(hass): ...  # tests_ha
async def test_upgraded_install_gains_the_select_at_steering(hass): ...  # _upgrade(hass, "entry_3_11_1_pumped_room") from test_upgrade_in_place
```

- [ ] **Step 2: Run them and see them fail.** Run `PY tests/test_timers_api.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** Follow `display.py` for the store and publish. The select default is `options[0]` = `steering` (already the class default).
- [ ] **Step 4: Run them.** Run the stub tests, the Docker `tests_ha/test_irrigation_mode.py`, `tests_ha/test_upgrade_in_place.py` and `tests_ha/test_real_flow.py`. Expected: PASS.
- [ ] **Step 5: Commit.** Subject: `feat(integration): timer programs and per-zone Watering by select`.

### Task 15: Controller runs timer programs and honours `irrigation_mode`

**Files:**
- Modify:
  - `controller.py`:
    - **Mode** (ruling R2):
      - Read `select.crop_steering_<px>zone_N_irrigation_mode` each pass.
      - A readable state in `IRRIGATION_MODES` is stored as the zone's last-known mode in the room state block `_irrigation_mode: {"3": "off"}`, saved by `_save_state` and read by `_load_room_state`.
      - When the select is unreadable (`unknown`/`unavailable`, HA restarting) the last-known mode is used.
      - `steering` is used only when no mode was ever seen for that zone (an old install, or an integration without the select).
      - An `off` zone therefore never gets engine water across an HA restart.
    - Read `sensor.crop_steering_<px>timers_config`.
    - In `_loop_room`, for `timer` zones, fire the `PlannedIntent`s with `last_pass < at <= now` through `_blocked` → `_act_zone`, with a synthetic decision whose reason kind is `"timer"` and whose `duration_s` comes from the program.
      - `last_pass` is a new **in-memory** dict `self._timer_last_pass[slug]`, not persisted. After a restart its first value is "now", so no missed slot is owed.
    - In `timer` mode keep the engine fires whose kind is in `safety_ops.RESCUE_KINDS` (`p3_emergency`, `watchdog`) **or** `min_daily`. The P3 emergency and the min-daily floor stay armed (ruling R3, spec §6.1).
    - In `off` mode drop every engine and timer fire.
    - Publish `sensor.crop_steering_<px>projection_app` (attr `intents`): the next 24 h of timer intents plus the engine's `waiting_for` estimate per zone, marked `expected: true`, each with a stable `id` (`derived_id(at, f"{prefix}:{zone}:{source}")`).
  - `PLAN_HOLD_EXEMPT` += `"timer"`
  - Honour `timers_config.skips`, comparing instants in UTC:
    - A timer intent whose `at` equals a skip's `at` for that zone is dropped.
    - The first non-rescue, non-`min_daily` engine fire for that zone with `skip.at <= now < skip.until` is dropped and the skip is consumed. Rescues and the min-daily floor are never skipped.
    - Either case journals `intent.refused {guard: "skipped", reason: "skipped by <by>"}` with `actor` = `timer` or `engine`.
- Test: `addons/f2_control/tests/test_timer_mode.py`

**Interfaces:**
- Consumes: `timers.project` (vendored), Task 14 entity contracts.
- Produces:
  - Timer shots go through the PASS, SIZED, QUEUE and PREOPEN guards (daily cap, tank, source water) via `_execute_shot(..., actor="timer", program_id=...)`.
  - `projection_app` attrs: `{intents: [{id, zone, at, duration_s, source: "timer"|"engine", program_id?, expected: bool}]}`. This is Task 25's only source of planned blocks.

- [ ] **Step 1: Write the failing tests.**

```python
def test_no_select_ever_seen_means_steering_exactly_as_before(): ...
def test_an_off_zone_stays_off_when_the_select_goes_unavailable(): ...   # R2: seen "off", then "unavailable" -> no engine shot
def test_an_off_zone_stays_off_across_a_controller_restart_with_ha_down(): ...  # R2: state.json carries _irrigation_mode; new Controller, select unavailable -> no shot
def test_timer_zone_fires_at_each_slot_and_stops_at_the_daily_max(): ...   # G7 accept: cap after N shots, "BLOCK daily-cap" held
def test_timer_zone_still_gets_a_p3_rescue(): ...                          # R3
def test_timer_zone_keeps_the_min_daily_floor(): ...                       # R3: min_daily reason fires in timer mode
def test_off_zone_gets_nothing_not_even_rescue(): ...
def test_a_restart_does_not_owe_missed_timer_shots(): ...
def test_kill_switch_holds_a_timer_shot(): ...
def test_a_skipped_timer_slot_does_not_fire(): ...
def test_a_skip_drops_the_next_engine_top_up_but_never_a_rescue_or_floor(): ...
def test_skip_matching_is_by_instant_not_offset_text(): ...               # "+13:00" vs "Z" for the same instant
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run `PY addons/f2_control/tests -q`. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(controller): timer programs and Watering by modes`.

### Task 16: Binary-sensor platform and threshold alert rules

**Files:**
- Create:
  - `custom_components/crop_steering/alert_rules.py`: pure `validate_rule`, `summary_sentence`, `step` (the lifecycle machine) and `replay`
  - `custom_components/crop_steering/binary_sensor.py`: `CropSteeringRuleSensor`, one per threshold rule of this room, added and removed on the dispatcher signal `crop_steering_rules_changed`
- Modify:
  - `__init__.py`: `PLATFORMS += [Platform.BINARY_SENSOR]`, and the rule evaluator in `site_api.py` subscribes to source entities
  - `tests/conftest.py` (stub `Platform`, around line 27) and the fallback `Platform` class in `custom_components/crop_steering/__init__.py` (around line 25): add `BINARY_SENSOR`. `tests/ha_stubs.py` has no `Platform`.
  - `site_api.py`: services `alert_rule_set`, `alert_rule_delete`, `alert_rule_test`, `alert_rule_preview`, `alert_rule_list`
  - `services.yaml`
- Test: `tests/test_alert_rules.py`, `tests_ha/test_alert_rules.py`

**Interfaces:**
- Consumes: site store `alert_rules`, `Notifier.send` (via `hass.data[DOMAIN]["_notify"]`), `journal_api.emit`.
- Produces:
  - AlertRule (spec §2.9), `kind: "threshold"`, with `id` = `new_id()`.
  - Source → entity:
    - `zone.vwc` → `sensor.crop_steering_<px>vwc_zone_N`
    - `zone.ec` → `…ec_zone_N`
    - `zone.temperature` → the zone's `substrate_temperature_sensor`
    - `feed.ph` / `feed.ec` → `sensor.crop_steering_<px>feed_ph_corrected` (Task 17) when a calibration is applied (its `applied` attribute is true), else the descriptor's raw sensor
    - `tank.level` → `sensor.crop_steering_<px>tank_level`
    - `stock.pct` → `level_l / capacity_l × 100` from the stock store
    - `zone.flow_ratio` → `sensor.crop_steering_<px>zone_N_flow_ratio` (× 100; Task 26)
    - `controller.heartbeat` → the age in seconds of `sensor.crop_steering_<px>ai_heartbeat`, evaluated every 60 s
    - `probe.silence_s` → for one mapped probe (`rule.entity_id`, required for this source), the seconds since its `last_reported`. Evaluated every 60 s; `unavailable` counts as silent since its last numeric report.
    - `stock.litres` → the tank's `level_l` from the stock store (`rule.tank_id` required)
  - `step(state: dict, value: float | None, now: datetime, rule: dict, lights: tuple[float, float], muted: bool) -> tuple[dict, str | None]`. States are `draft|armed|pending|firing|acknowledged|muted`. The event returned is `"raised"`, `"cleared"` or `None`.
  - `replay(samples: list[tuple[datetime, float]], rule, lights) -> dict`. Returns `{fires: [iso], count, min, max, sentence}`. The sentences are:
    - `"This rule would have fired 3 times yesterday — 06:12, 11:40, 19:05."`
    - `"It wouldn't have fired in the last 24 h. Lowest was 41%."`
    - over 10: `"That's 14 messages a day. Try a longer wait or a lower threshold."`
  - `alert_rule_test {id | rule, hours=24, send=false}`. Returns `{summary_sentence, replay}`. With `send: true` it adds `delivery: [{service, ok, error}]`. Samples come from the recorder (`recorder.history.get_significant_states` through `recorder.get_instance(hass).async_add_executor_job`).
  - `alert_rule_preview {rule, hours=24}` (draft rule, no write, no send) → `{summary_sentence, series: [[iso, value]], fires: [{start, fired_at, end}], ignored: [{start, end, reason: "shorter than min_duration"|"outside window"|"muted"}], count, min, max, sentence}`. The series is downsampled to ≤ 1440 points. `replay()` returns all of these fields, so `alert_rule_test` carries them too.
  - `alert_rule_list {room_id?}` → `{rules: [AlertRule + {state, last_fired, firing_since, current_value, unit}]}`. It is open to any signed-in user, and omitting `room_id` returns every room's rules.
    - `last_fired` comes from the newest `alert.raised` in the Journal for that `rule_id`.
    - `firing_since` is set while the rule state is `firing|acknowledged`.
    - `current_value` is the source's value now, in canonical units.
  - Entities: `binary_sensor.crop_steering_rule_<id>` (on while `firing|acknowledged`).
  - Events: `alert.raised {rule_id, value, threshold, title}` and `alert.cleared`. Push key `rule_<id>`, routed with the rule's own `routing` kind (spec §2.9), default `sensors`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_a_1_min_spike_does_not_fire_a_2_min_rule(): ...         # G6 accept
def test_a_3_min_breach_fires_once_and_clears_when_back(): ...
def test_outside_its_window_a_breach_is_ignored(): ...
def test_muted_room_holds_non_emergency_rules(): ...
def test_replay_counts_yesterdays_fires_and_says_so(): ...
def test_replay_warns_when_noisy(): ...
def test_climate_sources_are_refused(): ...                      # source "room.vpd" -> ValueError
def test_replay_reports_fire_spans_and_ignored_dips(): ...       # 1-min dip -> ignored "shorter than min_duration"; 3-min -> fires[0].fired_at = start + 2 min
def test_probe_silence_rule_fires_after_its_minutes(): ...       # last_reported 11 min ago, threshold 600 s above -> raised
def test_stock_litres_rule_reads_the_stock_store(): ...
def test_list_carries_last_fired_firing_since_and_current_value(): ...
def test_summary_sentence(): assert summary_sentence(rule) == "Tell when F2 tank level stays below 30% for 10 min during lights-on."
async def test_rule_entity_appears_and_turns_on_after_min_duration(hass, freezer): ...  # tests_ha
async def test_old_install_without_rules_loads_with_no_binary_sensors(hass): ...       # tests_ha upgrade
```

- [ ] **Step 2: Run them and see them fail.** Run `PY tests/test_alert_rules.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** The rule state lives in memory and re-arms on restart (a firing rule re-raises after `min_duration_s`).
- [ ] **Step 4: Run them.** Run the stub tests and the Docker `tests_ha/test_alert_rules.py` and `tests_ha/test_upgrade_in_place.py`. Expected: PASS.
- [ ] **Step 5: Commit.** Subject: `feat(integration): threshold alert rules with replay against yesterday`.

### Task 17: Feed pH/EC calibration wizard, applied corrections and due

**Files:**
- Modify: `custom_components/crop_steering/calibration.py`:
  - sessions are in-memory, with a 30 min idle expiry
  - New records gain `applied`, `committed_by`, `due_days = 30`, `superseded_by`. A record from before the upgrade has no `due_days` key. It never goes due and raises no CS-612 until the probe's next calibration (ruling R6).
  - `correct()` (pure)
  - `sensor.py`: two real `SensorEntity` + `RestoreEntity` classes, `CropSteeringFeedCorrectedSensor` (`feed_ph_corrected`, `feed_ec_corrected`, one pair per room, ruling R4).
    - State: the corrected value, or `unknown` when nothing is applied.
    - Attrs: `source`, `applied`, `slope_pct`, `offset`, `gain`, `bias`, `calibrated_at`.
    - They update on the raw sensor's state changes and on the dispatcher signal `crop_steering_calibration_changed_<entry_id>`, and restore their last state at startup.
  - The `engine_config` descriptor gains the attribute `feed_calibration: {ph?: {gain, bias, calibrated_at}, ec?: {...}}`, present only for applied calibrations.
    - `gain = 100 / slope_pct` and `bias = anchor − (anchor + offset) × gain`, so `raw × gain + bias` equals `correct()`.
    - It is not part of the setup fingerprint, so publishing it triggers no adoption hold.
  - `binary_sensor.crop_steering_<px>calibration_due` (attr `probes`) is published via `async_set`.
  - Repairs card `calibration_due_<slug>` with CS-612
- Modify: `strings.json`, `translations/en.json` (issue `calibration_due`), `services.yaml`, the CS-code files
- Test: `tests/test_calibration_wizard.py`, `tests_ha/test_calibration_wizard.py`

**Interfaces:**
- Produces:
  - `correct(raw: float, slope_pct: float, offset: float, anchor: float) -> float` = `anchor + (raw − anchor − offset) / (slope_pct / 100)`
  - `stable(samples: list[tuple[float, float]], kind: str, window_s: int = 30) -> tuple[bool, float]`. For pH: span < 0.02. For EC: span < 1 % of the mean. Returns `(stable, drift)`.
  - Services:
    - `calibration_start {room_id, probe, solutions?}` → `{session_id, raw_entity_id, temperature_entity_id, dosing_paused: true, expires_at}`. Solutions default to `[7.0, 4.0]` for pH and `[1.413, 2.77]` for EC.
      - `raw_entity_id` is the descriptor's `feed_<q>_sensor`.
      - `temperature_entity_id` is the room's `tank_temperature_sensor`, or `None`.
      - While any session of the room is open, the dosing descriptor `sensor.crop_steering_<px>dosing_config` carries the new attribute `calibrating: {probe, session_id, until}`. Task 18 makes the runner hold batches and pH correction on it.
      - Commit, revert, abandon or the 30 min expiry clears it. It refuses when the probe has not reported for 120 s: `"No reading from the feed pH probe for 2 min. Check it's plugged in."`
    - `calibration_capture {session_id, point: 0|1, force?: bool}` → `{reading, raw, stable, drift, stable_s}`. An unsteady reading without `force` → `stable: false` and no point is stored.
    - `calibration_status {session_id}` → `{reading, raw, stable, drift, stable_s, points_captured, expires_at}`.
      - It is read-only, open to signed-in users, and never stores a point.
      - It does not reset the 30 min idle expiry.
      - An unknown or expired session → `invalid` with `"Calibration session expired. Start again."`
    - `calibration_commit {session_id}` → `{slope_pct, offset, verdict, applied}`. A verdict of `fail` is kept with `applied: false` and returns `ok:false` with code `invalid`.
    - `calibration_revert {room_id, probe}` re-applies the previous applied record, or none.
  - `calibration_record` keeps `applied: false`.
  - Events: `calibration.started|captured|committed|reverted`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_known_offset_corrects_within_005_ph(): ...        # G2 accept: readings 7.12/4.12 -> corrected(4.12) within 4.00±0.05
def test_unsteady_reading_is_not_captured_without_force(): ...
def test_status_reports_stability_and_never_stores_a_point(): ...   # 3 status calls -> points_captured stays 0; store revision unchanged
def test_a_failed_verdict_is_kept_but_never_applied(): ...
def test_revert_restores_the_raw_value(): ...              # corrected sensor reads unknown, applied false; feed_calibration attr gone
def test_gain_bias_reproduce_correct(): ...                # raw*gain+bias == correct(raw, slope, offset, anchor) to 1e-9
def test_a_record_from_before_the_upgrade_never_goes_due(): ...  # R6: no due_days key, 400 days old -> no CS-612
def test_due_after_30_days_raises_cs_612(): ...
def test_idle_session_expires_after_30_min(): ...       # and the dosing descriptor's calibrating attribute is gone
def test_start_returns_raw_and_temperature_entities_and_pauses_dosing(): ...
async def test_commit_publishes_corrected_sensor_and_reads_back(hass): ...  # tests_ha
async def test_corrected_sensor_restores_after_restart(hass): ...           # tests_ha: mock_restore_cache
async def test_upgrade_keeps_old_calibration_records_without_a_repairs_card(hass): ...  # tests_ha
```

- [ ] **Step 2: Run them and see them fail.** Then implement. Add CS-612 (`source: repairs`, `severity: warning`, kind `sensors`) with its Repairs card and render (no bundle rebuild). Then run `PY tests/test_calibration.py tests/test_calibration_wizard.py tests/test_error_codes.py tests/test_notify_catalog.py -q --deselect tests/test_error_codes.py::test_no_code_is_defined_twice` and the Docker tests. Expected: PASS.
- [ ] **Step 3: Commit** (one commit). Subject: `feat(integration): feed probe calibration wizard applied as corrected sensors`.

### Task 18: Controller and runner read corrected feed values

**Files:**
- Modify:
  - `controller.py` (`_read_feed_ph`, `_read_feed_ec`)
  - `dosing_runner.py`:
    - `_ph_reading` and `_judge_mix` read the corrected entity
    - `_config()` reads the `calibrating` attribute
    - batch and pH correction start is held with `"feed probe calibration in progress"` (guard `dosing_lockout`); a single manual dose is still allowed
- Test: `addons/f2_control/tests/test_corrected_feed.py`

**Interfaces:**
- Consumes: Task 17's sensor and `engine_config.feed_calibration` contract.
- Produces: `Controller._feed_value(room, quantity: "ph"|"ec") -> tuple[float | None, str]` (value, entity read). Ruling R4:
  - `room._feed_calibration` is the descriptor's `feed_calibration`.
    - It is persisted in the room state block `_feed_calibration`, so it survives an HA restart.
    - It is replaced only by a descriptor that is readable.
    - A readable descriptor without the attribute clears it.
  - **No applied calibration for `q`:** read the raw sensor, as today.
  - **Applied, and the corrected sensor is numeric with `source == room.feed_<q>_sensor`:** use it.
  - **Applied, but the corrected sensor is unavailable, missing or for another source:** compute `raw × gain + bias` from the raw sensor. A dead raw sensor means `None`, which takes the existing dead-probe path (fail-closed after grace).
  - The raw value is **never** used uncorrected while a calibration is applied.

- [ ] **Step 1: Write the failing tests.**

```python
def test_no_calibration_reads_raw_as_before(): ...
def test_applied_correction_moves_the_source_water_gate(): ...      # raw 5.4 out of [5.5,6.5], corrected 5.6 -> no hold
def test_an_unavailable_corrected_ph_is_computed_from_raw_and_the_calibration(): ...  # corrected unavailable, raw 5.4, gain/bias -> 5.6 -> no hold
def test_applied_calibration_with_a_dead_raw_probe_holds_like_a_dead_probe(): ...  # "source-water pH probe dead >30min — holding (fail-closed)"
def test_ha_restart_keeps_the_last_calibration(): ...               # descriptor unreadable, state block has _feed_calibration -> computed, not raw
def test_mix_check_and_ph_autocorrect_use_the_corrected_value(): ...
def test_a_corrected_sensor_for_another_probe_is_computed_not_trusted(): ...  # source mismatch -> raw*gain+bias
def test_an_open_calibration_session_holds_batches_and_ph_correct(): ...
def test_no_calibrating_attribute_means_dosing_as_before(): ...
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run `PY addons/f2_control/tests -q`. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(controller): source-water gate, mix check and pH correct read the calibrated feed probes`.

### Task 19: Pump catalogue, prime and calibrate services (integration)

**Files:**
- Modify:
  - `dosing.py`:
    - `_pump` accepts `model {catalog_id, dial}`, `solution_type` (`nutrient|ph_up|ph_down|additive`, mirrored to `ph_role` for the ph types), `calibrated_ml_min`, `calibrations[≤30]` and `primed_at`
    - `PUMP_CATALOG = {"hea_a3": {...}, "hea_p1": {...}, "hea_p2": {...}, "hea_h4": {...}, "peristaltic": None, "other": None}`, each a dial → ml/min table taken from the manufacturer sheet
    - `ACTIONS += ("prime", "calibrate", "stop_pump")`
  - `dosing_api.py`: services `pump_prime`, `pump_calibrate` and `pump_calibration_commit`; `dosing_get` adds `catalog`
  - `stock_api.py`: `_draw_run` skips a run that overlaps an open calibrate request for that pump
  - `sensor.py`: `sensor.crop_steering_<px>dosing_pump_<id>_ml_min` and `_last_calibrated`, published via `async_set` from the dosing store
- Test: `tests/test_pump_calibration.py`, `tests_ha/test_pump_calibration.py`

**Interfaces:**
- Produces:
  - `pump_precheck {room_id, pump}` → `{ok: bool, blockers: [{code, message}]}`. It is read-only and open to signed-in users. The codes are:
    - `no_power_entity`
    - `batch_running`
    - `mix_pump_on`
    - `tank_filling`
    - `calibrating` (a probe session is open)
    - `controller_offline` (heartbeat older than 10 min)

    They are read from the dosing status sensor, the batch hardware states and the heartbeat. The messages are the UX checklist words, for example `"Mix pump is on"`.
  - `pump_prime {room_id, pump, seconds: 1..30}` → `{request_id, outcome: "requested"|"refused", blockers[]}`.
    - It uses the same blockers as `pump_precheck`, so any blocker means `refused`.
    - `seconds > 30` is a schema error. That is the UX cap, an **intentional deviation** from spec §5.2's 120 s (ruling R7, recorded in Spec gaps).
  - `pump_stop {room_id, pump}` → `{request_id}`.
    - It stores a request with action `stop_pump` that pre-empts a pending `prime` or `calibrate` request (the stored request is replaced even while `pending()`).
    - It never touches a running batch or other pumps. The room-wide `dosing_request {action: stop}` is unchanged.
  - `pump_calibrate {room_id, pump, seconds: 5..120}` → `{session_id, outcome}`.
    - `ran_s` arrives later in `dosing_get.pumps[i].calibration_session`.
    - This task owns a state listener on `sensor.crop_steering_<px>dosing`. When its `handled_result` names the session's `request_id`, the listener copies `ran_s` and `result` into the session in the dosing store.
  - `pump_calibration_commit {room_id, session_id, measured_ml}` → `{ml_min, previous_ml_min, flow_entity_written: bool}`. It refuses until `ran_s` is known. `ml_min = measured_ml / ran_s × 60`. When `flow_entity` is a `number`/`input_number`, it also sets it to `ml_min / 60` mL/s and reads it back.
  - Events: `pump.primed`, `pump.calibrated {ml_min, previous_ml_min}`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_30s_and_150ml_gives_300_ml_min(): ...                 # G3 accept (integration half)
def test_commit_before_the_run_is_reported_is_refused(): ...
def test_prime_without_a_power_switch_names_the_blocker(): ...
def test_precheck_lists_every_blocker_and_writes_nothing(): ...
def test_prime_over_30_seconds_is_refused_by_schema(): ...
def test_pump_stop_replaces_a_pending_prime_request(): ...
def test_runner_ran_s_is_copied_into_the_session(): ...           # status sensor handled_result -> session.ran_s; commit then succeeds
def test_old_pump_dicts_load_with_no_catalog_fields(): ...     # back-compat
def test_a_calibration_run_is_not_drawn_from_stock(): ...
def test_flow_entity_number_is_written_and_read_back(): ...
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run `PY tests/test_pump_calibration.py tests/test_dosing.py tests/test_dosing_api.py tests/test_stock_api.py -q` and the Docker test. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(integration): pump catalogue, prime and calibration services`.

### Task 20: Runner executes timed prime and calibrate runs, and uses calibrated flow

**Files:**
- Modify: `dosing_runner.py`. A `stop_pump` request ends a running timed run of that pump within one wait tick (≤ 2 s): power off with read-back, then `result: "stopped"` and the real `ran_s`. New `_run_timed(job)` for the actions `prime`/`calibrate`: `power_entity` on with read-back, wait `seconds` with the abort checks, off with read-back, then report `{request_id, ran_s}` in the status sensor attribute `handled_result`. The flow read falls back to `calibrated_ml_min / 60` when `flow_entity` is unset.
- Test: `addons/f2_control/tests/test_pump_timed_runs.py`

**Interfaces:**
- Consumes: Task 19's request shape in `dosing_config.request`, and `guards.DOSE_RUN` (Task 13).
- Produces: `handled_result: {"id", "action", "pump", "ran_s", "result": "done"|"stopped"|"refused: <why>"|"stuck"}`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_prime_runs_the_power_switch_for_its_seconds_and_reads_it_back_off(): ...
def test_prime_is_refused_while_a_shot_is_in_flight(): ...
def test_a_pump_that_does_not_read_off_latches_and_alerts_cs_801(): ...
def test_next_dose_uses_calibrated_flow_when_no_flow_entity(): ...   # G3 accept (controller half): 300 ml/min -> 5 mL/s
def test_flow_entity_still_wins_over_calibrated_flow(): ...
def test_stop_pump_ends_a_prime_early_and_reports_ran_s(): ...   # stop seen at 4 s of 20 -> power off read back, ran_s ≈ 4
def test_stop_pump_leaves_a_running_batch_alone(): ...
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run `PY addons/f2_control/tests/test_pump_timed_runs.py addons/f2_control/tests/test_dosing_runner.py addons/f2_control/tests/test_dosing_safety.py -q`. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(controller): timed pump prime and calibration runs`.

### Task 21: Probe offsets and curves, including match-handheld

**Files:**
- Create: `custom_components/crop_steering/probe_offsets.py`. Pure: `apply(raw, offset, curve) -> float` and `CURVES = {"rockwool": (a, b, c), "soilless": (a, b, c)}` (Topp-style quadratic coefficients, documented in the module docstring with source).
- Modify:
  - `calibration.py`: store key `probe_user_offsets {entity_id: {offset, curve, at, by}}`, absent → `{}`. It is named apart from fusion's in-memory `_probe_offsets`.
  - service `probe_offset_set`
  - `sensor.py`: the zone's `_probe_readings` applies `apply()` before `fuse_probes`. On an offset change it shifts `self._probe_offsets[pid]` by the same delta, so a later missing-probe pass does not step. It publishes `sensor.<probe_object_id>_corrected` only for probes with an offset or curve.
- Test: `tests/test_probe_offsets.py`, `tests_ha/test_probe_offsets.py`

**Interfaces:**
- Produces:
  - `probe_offset_set {room_id, entity_id, expected_revision, offset? | curve? | match_handheld?, preview?: bool}` → `{offset, corrected_now, fused_before, fused_after}`. With `preview: true` it writes nothing: no store save, no `_probe_offsets` shift, no corrected-sensor publish and no event. It returns `{offset, corrected_now, fused_before, fused_after, diff}`, so `match_handheld` previews as `{offset: 3.0, corrected_now: 52.0}`.
  - `match_handheld` sets `offset = handheld − current raw`.
  - A curve on a probe whose unit is already `%` is refused with `"This probe already converts to moisture. A curve only applies to raw readings."`
  - Event `config.changed {store: "calibration", section: "probe_user_offsets", old, new, diff}`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_handheld_52_vs_probe_49_sets_plus_3(): ...              # G9 accept
def test_preview_returns_offset_and_corrected_now_without_writing(): ...  # match_handheld 52 vs 49 preview -> offset 3.0, corrected_now 52.0; store revision, sensors and journal unchanged
def test_fused_value_moves_and_no_probe_alert_attribute_fires(): ...  # fusion["excluded"] unchanged, quality ok
def test_no_offsets_publishes_no_corrected_sensors(): ...
def test_curve_on_a_percent_probe_is_refused(): ...
async def test_offset_survives_restart_and_reads_back(hass): ...  # tests_ha
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run `PY tests/test_probe_offsets.py tests/test_probe_fusion.py tests/test_sensor_weekly_and_fusion.py -q` and the Docker test. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(integration): per-probe offsets and curves applied before fusion`.

### Task 22: Server presets and `copy_config`

**Files:**
- Create: `custom_components/crop_steering/presets.py`. Pure: `capture(values: dict, sections) -> dict` and `diff(current: dict, wanted: dict) -> list[dict]`.
- Modify: `site_api.py` (services), `services.yaml`
- Test: `tests/test_presets.py`, `tests_ha/test_presets.py`

**Interfaces:**
- Consumes: `strategy_model.PARAMETERS`, the `hass.data[DOMAIN]["_numbers"][entry_id]` entities for the read and the readback, and `timers_api.get_programs`/`set_programs` (Task 14) for the `timers` section.
- Produces:
  - Sections: `targets` (PARAMETERS + `p2_mode`), `phase_timing`, `water_limits`, `timers`. `scope` is one of `targets|timers|all`, where `all` is all four sections. There is no `feed` scope; dosing feed recipes stay in `dosing_save`.
  - `async write_numbers(hass, entry_id: str, writes: list[dict], actor: dict) -> list[dict]`. Each write is `{entity_id, key, value}`; each result is `{entity_id, key, old, new, readback: "verified"|"refused"}`. It writes through `number.set_value`, re-reads the state, and journals `target.changed` per write. This is the helper Task 24 consumes (ruling R8).
  - `preset_save {name, scope: targets|timers|all, from: {room_id, zone?: int}, expected_revision}` → preset
  - `preset_list {}`
  - `preset_delete {id, expected_revision}` (soft)
  - `preset_apply {preset_id, to: [{room_id, zone?: int}], preview: bool}` → `{diff: [{target, key, old, new}], applied?: [{target, key, readback: verified|refused}]}`
  - `copy_config {from: {room_id, zone?}, to: [{room_id, zone?}], sections[], preview}` → same shape
  - Writes go through `number.set_value` with read-back. Each one journals `target.changed` with `actor` from `attribution` and `detail: "preset <name>"`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_preview_lists_only_changed_rows(): ...
def test_apply_reads_back_each_target_and_reports_refused_ones(): ...   # one number clamps -> readback "refused"
def test_a_preset_saved_once_is_listed_for_every_client(): ...          # G10 accept
async def test_copy_zone_3_to_zones_1_2_writes_and_reads_back(hass): ...  # tests_ha
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run them. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(integration): server-side presets and copy with preview`.

### Task 32: `dashboard_create` and `dashboard_list` (G11) — run before Task 23

**Files:**
- Create: `custom_components/crop_steering/dashboards.py`. It holds the templates as Python data, plus the services. Created dashboards are tracked in store `crop_steering.dashboards`, version 1, doc `{revision, dashboards: [{url_path, title, template, rooms, created_at, by}]}`.
- Modify: `__init__.py`, `services.yaml`
- Test: `tests/test_dashboards.py`, `tests_ha/test_dashboards.py`

**Interfaces:**
- Produces:
  - `TEMPLATES = ("facility_wall", "room_tablet", "dosing_station")`
  - `render(template: str, rooms: list[dict]) -> dict`, a pure Lovelace config of `views[]` using existing entities only.
  - `dashboard_create {template, rooms[], title?}` → `{url_path, title}`. It is admin only.
    - It creates the dashboard through the Lovelace dashboards collection (`hass.data["lovelace"].dashboards` / `DashboardsCollection.async_create_item`, mode `storage`) and saves the config with `async_save`.
    - `url_path` is `crop-steering-<template>-<n>`.
    - It reads the dashboard back.
    - It refuses an unknown template with `"Unknown dashboard template"`.
  - `dashboard_list {}` → `{dashboards: [{url_path, title, template, rooms, created_at, exists: bool}], templates: [{id, name, description}]}`. `exists` is false when the user deleted it in HA.

- [ ] **Step 1: Write the failing tests.**

```python
def test_each_template_renders_only_entities_the_room_has(): ...
def test_unknown_template_is_refused(): ...
async def test_create_then_list_shows_it_and_ha_serves_it(hass): ...   # tests_ha: lovelace dashboard url_path exists, config views non-empty
async def test_a_dashboard_deleted_in_ha_lists_exists_false(hass): ...
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run `PY tests/test_dashboards.py -q` and the Docker test. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(integration): wall dashboards from templates`.

### Task 33: Display units and clock (G15) — run before Task 23

**Files:**
- Modify: `custom_components/crop_steering/display.py` (`OPTIONS`)
- Test: `tests/test_display_options.py` (extend), `tests_ha/test_display_options.py` (extend)

**Interfaces:**
- Produces new `OPTIONS` entries. Each default is today's display, so an old store reads as before:
  - `ec_unit {default: "mS/cm", choices: ("mS/cm", "ppm500", "ppm700")}`
  - `temp_unit {default: "C", choices: ("C", "F")}`
  - `volume_unit {default: "L", choices: ("L", "gal")}`
  - `clock {default: 24, choices: (12, 24)}` (ints, as spec §2.3)

  Storage and the API stay canonical. These are display-only per room, which is where the existing L/gal toggle lives. This is an **intentional deviation** from spec §2.3's site-level `units` (ruling R7, recorded in Spec gaps).

- [ ] **Step 1: Write the failing tests.**

```python
def test_old_store_reads_units_as_mS_C_L_24(): ...
def test_save_refuses_an_unknown_unit(): ...
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run `PY tests/test_display_options.py -q`. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(integration): EC, temperature, volume and clock display units`.

### Task 34: Notification quiet hours — run before Task 23

`notify_api.py` already has these:
- room mute-until (`mutes`, ≤ 30 days, emergencies still pushed)
- "Emergencies loud" (per-phone `urgent_high_priority`)
- per-phone test results (`notify_test` → `{sent, error}`)

It has no quiet hours. This task adds them.

**Files:**
- Modify: `custom_components/crop_steering/notify_api.py` (`clean_recipient`, `send`, `response`), `services.yaml` (document the new keys)
- Test: `tests/test_notify_quiet_hours.py`

**Interfaces:**
- Produces:
  - Per recipient `quiet_hours: {from: "HH:MM", to: "HH:MM"} | None`. The default is `None`, so an old store keeps no quiet hours. A window may cross midnight, and `from == to` is refused with `"Quiet hours need a start and an end that differ"`.
  - Inside the window a non-urgent push to that phone is put in its digest queue, even when `digest` is off. It is delivered at the window's end. Urgent (critical) pushes always go.
  - `notify_get` rows expose `quiet_hours`.
  - Documented in `services.yaml` and the module docstring: non-critical "not watering" warnings (controller `NOT_WATERING_CODES`, e.g. CS-206, CS-316) are also held during a phone's quiet hours. Only critical codes break through.
  - `notify_test {service}` is unchanged. A new optional `notify_test {services: [..]}` answers `{results: [{service, sent, error}]}` for several phones in one call.

- [ ] **Step 1: Write the failing tests.**

```python
def test_old_recipient_rows_have_no_quiet_hours(): ...
def test_a_warning_inside_quiet_hours_is_held_until_the_end(): ...
def test_an_emergency_inside_quiet_hours_is_pushed(): ...
def test_quiet_hours_crossing_midnight(): ...
def test_test_several_phones_reports_each(): ...
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run `PY tests/test_notify_quiet_hours.py tests/test_notify_api.py tests/test_notify_digest_mute.py -q`. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(integration): per-phone quiet hours and multi-phone test`.

### Task 23: API v2 envelope on every response service

**Files:**
- Create: `custom_components/crop_steering/api_v2.py`
- Modify: every response-service schema and handler in `setup_api.py`, `strategy_api.py`, `run_api.py`, `grow_day_store.py`, `harvest_store.py`, `setpoint_log.py`, `overlays.py`, `calibration.py`, `stock_api.py`, `dosing_api.py`, `display.py`, `notify_api.py`, `journal_api.py`, `site_api.py`, `timers_api.py`, `dashboards.py`, `system_status.py`
- Test: `tests/test_api_v2.py`, `tests_ha/test_api_v2.py`

**Interfaces:**
- Produces:
  - `COMMON = {vol.Optional("api"): vol.In([1, 2]), vol.Optional("client"): vol.In(["mcp", "aigrow"]), vol.Optional("proposal_token"): str}`
  - `def wrap(handler, *, room_of=lambda call, result: ..., revision_of=lambda result: result.get("revision")) -> handler`
  - With `api: 2` the handler answers `{api: 2, ok: true, room_id, revision, readback: {status, at}, event_ids, data}`. Errors are `{api: 2, ok: false, error: {code: stale_revision|invalid|forbidden|guard_refused|unavailable, message, current_revision?}}`.
  - Without `api`, the v1 result is byte-identical. `setup_read` keeps `api_version: 1` in the v1 shape and reports 2 only inside the envelope, so the MCP `z.literal(1)` keeps parsing.
  - `event_ids` are collected from `emit()` calls made during the handler, via a `contextvars.ContextVar`.
  - Error mapping: an `async_require_admin` refusal → `forbidden`; a revision mismatch → `stale_revision`; messages starting `pump_over_capacity:` and every other `ValueError` → `invalid`; a hub or store unavailable → `unavailable`; an `intent.refused` from a guard → `guard_refused`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_without_api_the_answer_is_unchanged(): ...           # each wrapped handler: result == unwrapped result
def test_stale_revision_maps_to_its_code_and_current_revision(): ...
def test_forbidden_maps_from_the_admin_check(): ...
async def test_every_response_service_accepts_api_2(hass): ...  # tests_ha: iterate hass.services.async_services()["crop_steering"], ONLY/OPTIONAL ones, call with api 2 -> "api" == 2
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run `PY tests -q` and the Docker test. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(integration): API v2 envelope on every response service`.

### Task 24: `history_changes` and `history_revert`

**Files:**
- Create: `custom_components/crop_steering/changes.py` (pure fold), `journal_api.py` (services)
- Test: `tests/test_changes.py`, `tests_ha/test_history_changes_upgrade.py`, `tests_ha/test_history_revert.py`

**Interfaces:**
- Consumes: `presets.write_numbers` (Task 22), `timers_api.set_programs` (Task 14), and the store save paths of setup, site and calibration. Every `config.changed` carries `old` (Global Constraints, ruling R8).
- Produces:
  - `fold_changes(events: list[dict], limits: dict[str, dict]) -> list[dict]`. Each item is `{id (= event_id), room_id, ts, actor, kind, key|section, scope, old, new, reason, outcome, limits, revertible}`.
    - `kind` is one of `setpoint|plan|recipe|setup|calibration|alerts`, mapped from `target.changed`, `plan.*`, preset/recipe `detail`, `config.changed{store: setup|site|timers}`, `calibration.*`/`pump.calibrated` and `config.changed{section: alert_rules}`.
    - `outcome` is one plain line for learner/AI changes, read from the matching `ai.outcome`, or else from the `expected` field: `"Too soon to judge — check after the next lights-on."` until the next lights-on, then `"Dryback came back to target."` / `"No change in dryback yet."` from `ai.outcome.good`. It is `None` for other actors.
    - `limits` is `{writer: "learner"|"brain", min, max, step_scope}` for learner/AI rows. `min`/`max` come from `ENGINE_BOUNDS[key]` and `step_scope` from `const.SETPOINT_STEP_SCOPES`; the integration has no access to the add-on's `auto_setpoints` step sizes. It renders as `"learner may move it between 1.0 and 5.0 %"`; `None` otherwise.
    - The newest comes first.
  - `history_changes {room_id?, since, until?, zone?, key?, kinds?}` → `{changes}`. When `room_id` is omitted, every room the user can read is queried and the results merged by `ts`.
    - Every row also carries `user_id` (from `source.user_id`, or `None`) and `user_name`.
    - `user_name` is the HA user's display name from `hass.auth.async_get_user(user_id).name`, cached per call. It falls back to `None` for an unknown or deleted user, or when there is no user.
  - `history_revert {event_id, expected_revision?}` → `{reverted_event_id, new_event_id, readback}`. It is admin only.
    - `target.changed` writes `old` back to the entity with read-back.
    - `config.changed` re-saves the store section's `old` copy with the current revision.
    - Both journal the new change with `actor: "manual"`, `correlation.causation_id = event_id` and `detail: "put back"`.
    - It refuses a row that is not `revertible`: a plan activation, a shot, a calibration that was itself superseded, or a backfilled or legacy row without `old`. The message is `"This change can't be put back"`.
    - A stale value is refused with the code `stale_revision`: the entity no longer holds `new`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_a_learner_nudge_and_a_manual_edit_both_appear_attributed(): ...   # G8 accept
def test_manual_rows_name_the_user_and_automation_rows_do_not(): ...  # user "Ben" -> user_id + user_name "Ben"; deleted user -> user_name None; no user -> both None
def test_rows_carry_id_kind_outcome_and_limits(): ...                       # learner row: kind "setpoint", limits.writer "learner", outcome "Too soon to judge — check after the next lights-on."
def test_until_bounds_the_range_and_no_room_merges_all_rooms(): ...
def test_revert_refuses_when_the_value_moved_since(): ...                   # stale_revision
async def test_revert_writes_the_old_value_back_and_journals_manual_with_causation(hass): ...  # tests_ha: number back to old, new event actor manual, causation_id == event_id
async def test_upgrade_then_backfill_then_history_changes_equals_the_old_setpoint_log(hass): ...  # spec §7 test; seeded snapshot entry_3_11_1_pumped_room + a seeded setpoint_log store
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run them. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(integration): history_changes over the journal, and history_revert`.

### Task 25: `timeline_get`

**Files:**
- Create: `custom_components/crop_steering/timeline.py` (pure fold), `journal_api.py` (service)
- Test: `tests/test_timeline.py`, `tests_ha/test_timeline.py`

**Interfaces:**
- Consumes: the journal query, `sensor.crop_steering_<px>projection_app` (Task 15; the **only** source of planned timer and engine blocks, so nothing is drawn twice), `zone_demand_lph` from the supply descriptor (Task 11), and the room lights hours.
- Produces:
  - `build(rooms: list[dict], events: list[dict], planned: list[dict], start, end) -> dict`, in the spec §5.2 shape.
  - Block kinds are `shot|held|queued|planned|alert`. Statuses are `done|planned|error|warning`.
  - Each block carries:
    - `litres` (commanded)
    - `metered_l` (from `shot.completed.data.metered_l`, joined to `flow.reconciled` on `correlation.intent_id`; `None` when there is no meter)
    - `reason`, `phase`, `vwc_before`, `vwc_expected`, `requested_at`, `pump_wait_s` (all from `shot.started` data, Task 8)
    - `source`, `code`, `event_id`
    - `skippable: bool` (future timer or engine blocks only)
  - Engine-expected blocks have `expected: true`.
  - `errors: {count, markers[]}`.
  - `pump_load: [{t, pct}]` per room, built from the `shot.started`/`completed` windows and `zone_demand_lph`.
  - The span must be ≤ 48 h, or the call fails with `"timeline span is at most 48 h"`.
  - `timeline_get {rooms[], start, end, zones?}`
  - `summarise(events, days) -> list[dict]`
  - `timeline_summary {rooms[], days: [YYYY-MM-DD] (≤ 14)}` → `{days: [{date, rooms: [{room_id, shots, failed, warnings, held, queued}]}]}`, folded over the local day of each room.

- [ ] **Step 1: Write the failing tests.**

```python
def test_completed_shot_is_a_done_block_with_metered_litres(): ...
def test_aborted_shot_is_an_error_block_with_its_code(): ...
def test_planned_blocks_come_from_projection_app_after_now_only(): ...
def test_a_planned_timer_block_is_drawn_once(): ...
def test_engine_expectation_is_marked_expected(): ...
def test_span_over_48h_is_refused(): ...
def test_block_carries_reason_phase_vwc_and_pump_wait(): ...
def test_summary_counts_failed_and_warning_blocks_per_local_day(): ...   # an aborted shot at 23:30 NZ lands on that NZ date
def test_summary_refuses_more_than_14_days(): ...
async def test_two_rooms_48h_round_trip(hass): ...   # tests_ha
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run them. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(integration): timeline_get folds shots, holds and planned timers`.

### Task 26: Flow reconciliation in the controller

**Files:**
- Modify:
  - `controller.py`:
    - read the zone's meter (`zone_meters[zone_id]`, else the pump's `flow_meter`, from the supply descriptor) before the valve opens and after the read-back
    - `flow.reconcile` → `flow.reconciled {ratio, commanded_l, metered_l}` with `correlation.intent_id` = the shot's intent id (no separate `shot_id`); `metered_l` is also put in that shot's `shot.completed` data
    - publish `sensor.crop_steering_<px>zone_N_flow_ratio` (attrs `commanded_l`, `metered_l`, `intent_id`)
    - `_alert(..., "CS-318", ...)` when the verdict is `low`
    - between shots, a meter rise of more than 0.5 L with no shot in flight → `_alert(..., "CS-319", ...)`
  - the CS-code files (no bundle rebuild): `hardware` kind; CS-318 and CS-319 are warning and notification
  - the meter is looked up as `zone_meters["room:<prefix>"][str(zone)]`, else the pump's `flow_meter` (Task 11 key format)
- Test: `addons/f2_control/tests/test_flow_reconcile.py`

**Interfaces:**
- Consumes: `flow.to_litres`, `flow.reconcile` (Task 2), and Task 11's descriptor.
- Produces: the sensor and the events above. With no meter, nothing changes and nothing is published.

- [ ] **Step 1: Write the failing tests.**

```python
def test_no_meter_publishes_nothing(): ...
def test_a_50_pct_shortfall_raises_cs_318_within_one_shot(): ...    # G4 accept
def test_meter_rise_with_every_valve_shut_raises_cs_319(): ...
def test_a_meter_in_unknown_units_is_ignored_and_logged_once(): ...
```

- [ ] **Step 2: Run them and see them fail.** Then implement. Add the codes and render, then run `PY addons/f2_control/tests -q` and `PY tests/test_error_codes.py tests/test_notify_catalog.py -q`. Expected: PASS.
- [ ] **Step 3: Commit** (one commit; run the error-code tests with the `--deselect` from Global Constraints). Subject: `feat(controller): reconcile metered against commanded water per shot`.

### Task 27: Alerts inbox and `alert_ack`

**Files:**
- Create: `custom_components/crop_steering/alerts_inbox.py` (pure fold + publisher)
- Modify: `journal_api.py` (service `alert_ack`; republish on each stored `alert.*` event and every 5 min)
- Test: `tests/test_alerts_inbox.py`

**Interfaces:**
- Produces:
  - `open_alerts(events: list[dict], live_notifications: set[str]) -> list[dict]`. An alert is open when it has an `alert.raised` with no later `cleared`/`acknowledged` for the same `data.key` or `data.rule_id`. A controller alert (actor ≠ `system`) whose `f2_<key>` persistent notification is gone is closed. This covers the 12 direct `persistent_notification.dismiss` sites in `controller.py`.
  - `sensor.crop_steering_<px>alerts_open`: state = count; attr `alerts` = `[{event_id, ts, code, title, zone, entity_id, rule_id?, acknowledged: false}]`. `entity_id` is the entity the alert concerns, or `None`:
    - a threshold rule's source entity (Task 16 source map);
    - a controller alert's `data.entity_id`. Task 8's `alert.raised` adds `entity_id` when `_alert` names a sensor or switch; otherwise it is `None`.
  - `alert_ack {room_id, alert_event_id}` → journals `alert.acknowledged`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_each_open_alert_names_its_entity_or_none(): ...   # rule on tank level -> sensor.crop_steering_f2_tank_level; controller alert without entity -> None
def test_raised_then_cleared_is_not_open(): ...
def test_acknowledged_leaves_the_inbox(): ...
def test_an_alert_whose_notification_is_gone_leaves_the_inbox(): ...
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run them. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(integration): alerts inbox sensor and alert_ack`.

### Task 28: `system_status_get` and `sensor.crop_steering_system_health`

**Files:**
- Create: `custom_components/crop_steering/system_status.py`
- Modify: `__init__.py`, which owns the 5-minute health tick (`async_track_time_interval(..., minutes=5)`): call the publisher there. Also `services.yaml`. `health.py` is unchanged.
- Test: `tests/test_system_status.py`

**Interfaces:**
- Produces:
  - `status(hass, now) -> dict` = `{controller: running|stale|absent, addon_version, rooms: [{room_id, entities: [{entity_id, last_seen, ok}], pct_online, alerts_open}]}`.
  - The entities are the room descriptor's mapped probes, valves, pump, main line and feed sensors.
  - An entity is `ok` when it is not `unknown`/`unavailable`. A probe must also have `last_reported` younger than `max(180 s, 3 × its own median report interval over the last hour)`, so a probe that reports every 5 min is not called silent. Actuators count as ok while available.
  - The controller is `running` when the heartbeat is younger than 10 min (the same rule as `engine_offline`).
  - `addon_version` comes from heartbeat attr `controller_version`.
  - `sensor.crop_steering_system_health`: state = overall `pct_online`; attrs `pct_online`, `silent[]`, `controller`, `addon_version`.
  - The `system_status_get {}` service.
  - Its answer also carries:
    - Per entity:
      - `kind`, one of `probe_vwc|probe_ec|probe_temp|valve|pump|main_line|feed_probe|tank|flow_meter`
      - `name`, the friendly name or else the entity id
      - `zone`, an int or `None`
      - `last_change`
      - `uptime_7d_pct`: the share of the last 7 days not `unknown`/`unavailable`, from `recorder.history.state_changes_during_period`. It is cached for 1 h per entity, and is `None` when the recorder is off.
    - Per room, `groups: [{kind, entities: [...]}]` in that kind order.
    - Per room: `heartbeat: {last_beat, age_s, controller: running|stale|absent, beats: [{at, missed: bool, readback_ms}], interval_s: 60}`, holding the last 120 beats of **that room's** `ai_heartbeat`. The top-level `controller` is the best of the rooms' states. `readback_ms` is not published by today's controller, so it stays `None` until a controller adds it.
      - It comes from an in-memory ring filled by `async_track_state_change_event` on each room's `ai_heartbeat`.
      - A gap above 2 × interval inserts a `missed` beat.
      - `readback_ms` is the heartbeat attribute `readback_ms` when the controller publishes it, else `None`.
    - `ha_version` (`homeassistant.const.__version__`)
    - `ai: {calls_today, daily_budget, pct_used, model}` comes from the attributes `calls_today` and `daily_budget` on `sensor.crop_steering_<px>jev`, published from `Meter` in `addons/f2_control/f2_control/brain/client.py`.
      - `pct_used = calls_today / daily_budget × 100`.
      - `model` is that sensor's `model` attribute if it exists, else `None`.
      - `ai` is `None` when the sensor is absent.
    - `card_version`: the `?v=` of the registered Lovelace resource whose URL contains `crop_steering`, read from `hass.data["lovelace"].resources`; `None` when there is none.

- [ ] **Step 1: Write the failing tests.**

```python
def test_one_silent_probe_drops_pct_online(): ...   # G17 accept: 10 entities, 1 unavailable -> 90
def test_stale_heartbeat_is_stale_controller(): ...
def test_entities_are_grouped_by_kind_with_names(): ...
def test_uptime_7d_from_a_state_history(): ...      # 12 h unavailable in 7 d -> pytest.approx(92.85714285714286), unrounded
def test_a_probe_reporting_every_5_min_is_not_silent(): ...
def test_a_heartbeat_gap_is_a_missed_beat(): ...
def test_each_room_carries_its_own_heartbeat(): ...   # 2 rooms, one stale: rooms[i].heartbeat differs; rooms[i].controller per room
def test_no_brain_no_lovelace_resource_gives_none_not_an_error(): ...
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run them. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(integration): system status service and health sensor`.

### Task 29: Grow summary sensors

**Files:**
- Modify: `strategy.py`. `_publish` also sets these states via `hass.states.async_set`:
  - `sensor.crop_steering_<px>grow_day`: the plan day of the lowest-numbered zone with status `active`
  - `sensor.crop_steering_<px>days_to_harvest`: that zone's last `end_day − day`
  - `sensor.crop_steering_<px>stage`: the active segment's profile `name`, else the `growth_stage` select's state
  - When no plan is active, all three are `unknown`.
- Test: `tests/test_grow_summary.py`

**Interfaces:**
- Produces: `grow_summary(plan: dict, previews: list[dict], fallback_stage: str | None) -> dict`, returning `{grow_day, days_to_harvest, stage}`.

- [ ] **Step 1: Write the failing tests.**

```python
def test_day_38_of_63_is_25_days_to_harvest(): ...   # G16 accept
def test_no_active_plan_is_unknown(): ...
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run `PY tests/test_grow_summary.py tests/test_strategy.py -q`. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(integration): grow day, days to harvest and stage sensors`.

### Task 30: MCP read tools

**Files:**
- Modify:
  - `mcp-server/src/ha.ts`: the `Service` allowlist += `journal_query`, `timeline_get`, `history_changes`, `supply_get`, `system_status_get`, `alert_rule_list`, `timeline_summary`
  - `mcp-server/src/schemas.ts`: zod for each response
  - `mcp-server/src/server.ts`: tools `get_timeline`, `get_changes`, `get_events`, `get_alert_rules` (calls `alert_rule_list` from Task 16), `get_supply`, `get_system_status`
  - `mcp-server/tests/mock-ha.mjs`
- Test: `mcp-server/tests/read_tools.test.mjs`

**Interfaces:**
- Produces: read-only tools with `annotations: {readOnlyHint: true}`. Each validates its input with `roomId` and caps output through the existing `result()`.
- Order: this task runs after Tasks 11, 16, 23, 24, 25 and 28.

- [ ] **Step 1: Write the failing tests.**

```js
test("get_timeline calls timeline_get with api 2 and returns its data", ...)
test("get_events refuses a limit above 500", ...)
test("read tools never call a *_save service", ...)
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run the MCP command. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(mcp): timeline, changes, events, supply, alert rule and status read tools`.

### Task 31: MCP preview tools and `apply_proposal` kinds

**Files:**
- Modify:
  - `mcp-server/src/workspace.ts`: `remember()` kinds `timer_program|alert_rule|preset_apply|copy_config|probe_offset|supply`, and `apply()` dispatch per kind
  - `server.ts`
  - `ha.ts`: the `Service` allowlist adds
    - dry-run reads `timer_program_preview`, `alert_rule_preview`, `timer_program_list`;
    - writes, gated by `CROP_STEERING_ALLOW_WRITES`: `timer_program_set`, `alert_rule_set`, `preset_apply`, `copy_config`, `probe_offset_set`, `supply_save`.
    - `preset_apply`, `copy_config`, `probe_offset_set` and `supply_save` are also called with `preview: true` for the dry runs.
  - `mock-ha.mjs`
- Test: `mcp-server/tests/preview_tools.test.mjs`

**Interfaces:**
- Produces:
  - `preview_timer_program`, `preview_alert_rule`, `preview_preset_apply`, `preview_copy_config`, `preview_probe_offset` and `preview_supply`. Each returns `{proposal_token, kind, room_id, expected_revision, diff, preview}`, where `preview` is the integration's own dry-run answer.
  - `apply_proposal` sends `{..., client: "mcp", proposal_token, api: 2}`, then re-reads.
    - For revisioned stores (`timer_program`, `alert_rule`, `supply`, `probe_offset`) it requires `revision == expected_revision + 1` and a matching digest, as `apply()` does today.
    - For `preset_apply`/`copy_config`, which write entities rather than a revisioned store, it re-runs the same call with `preview: true`. The apply counts only when that preview returns an **empty** diff, meaning every target now holds its new value, and every `applied[].readback` is `verified`.
  - Each preview tool's `preview` is the integration's own dry run: `timer_program_preview`, `alert_rule_preview`, `preset_apply{preview}`, `copy_config{preview}`, `probe_offset_set{preview}`, `supply_save{preview}`.
  - `intent_submit`, `pump_*` and `calibration_*` are absent from the allowlist (asserted by test).

- [ ] **Step 1: Write the failing tests.**

```js
test("preview_supply returns a token and apply writes with client mcp", ...)
test("apply refuses when the revision moved after preview", ...)
test("preset apply is verified by an empty re-preview diff, not a revision", ...)
test("hardware-moving services are not in the allowlist", ...)
```

- [ ] **Step 2: Run them and see them fail.** Then implement, then run the MCP command. Expected: PASS.
- [ ] **Step 3: Commit.** Subject: `feat(mcp): previewed proposals for timers, rules, presets, copy, probe offsets and supply`.

---

## Self-review

- **Spec coverage:**

  | Spec step | Tasks |
  |---|---|
  | M0 | 4, 5 |
  | M1 | 8, 9 (with 6 for the integration-side producers) |
  | M2 | 7, 9 |
  | M3 | 3, 10, 12, 13 |
  | M4 | 11, 14–22, 32–34 |
  | M5 | 23 |
  | M6 | 24–29 (flow in 26) |
  | M8 | 30, 31 |

  The frontend plan's "Contract assumptions" are covered as follows:

  | Item | Where |
  |---|---|
  | 1 `history_revert` | Task 24 |
  | 2 `alert_rule_list`/`alert_rule_preview` + `probe.silence_s`/`stock.litres` | Task 16 |
  | 3 timer list/preview/skip | Tasks 14, 15 |
  | 4 timeline fields + `timeline_summary` | Tasks 8, 12, 25 |
  | 5 `history_changes` fields, `until`, all rooms | Task 24 |
  | 6 `calibration_start` fields + `dosing_paused` | Tasks 17, 18 |
  | 7 `pump_stop`, 30 s cap, `pump_precheck` | Tasks 19, 20 |
  | 8 system status detail | Task 28 |
  | 9 notify | Task 34 (only quiet hours were missing) |
  | 10 dashboards | Task 32 |
  | 11 display units | Task 33 |
  | 12 `crop_steering/subscribe` | Task 5 |

  The journal kinds `run.saved|archived` and `harvest.recorded` are accepted (Task 4) but not yet emitted. Wiring them into `run_api`/`harvest_store` is a follow-up.

  Frontend asks not added, by coordinator ruling: per-rule phone targets or a `rules` notify kind (rules route through the existing kinds via `routing`), and any service that releases a feed held by a failed mix check (a safety bypass).

  Not planned, by scope: M7 (frontend), G12 inline (`dosing_mode`, `inline_status`), G13 `scale_hints`, `intent_submit`, and the `water_sources` behaviour beyond storage.
- **Type consistency:**
  - Every task calls `emit()` / `Outbox.emit` / `attribution()` with the signatures from Tasks 5 and 8.
  - `PlannedIntent` and `project()` from Task 1 are used in 14, 15 and 25.
  - `Guard` and `first()` from Task 10 are used in 12 and 13.
  - `capacity_ok` and `order` from Task 2 are used in 12. `worst_case_lph` is pinned equal in 11.
- **Proportion:** the tasks carry signatures, exact strings and test assertions, with no bodies.

## Spec gaps and decisions taken (from the real code)

1. **Guard order.** Spec §2.7 numbers the guards 1–19, but `_blocked` evaluates them in a different order: setup, archived, room off, dosing, plan, hardware fault, max-run, valve, plumbing, switchable, kill switch, and so on. Some gates have no spec id at all: `external_hold`, `settings_loaded`, and archived/room-off. The plan keeps today's order, so the first held reason never changes, and maps the spec ids onto it (Task 10).
2. **The controller is synchronous**, so at most one shot is ever in flight across all rooms. Because of that, guards 16–17 can only:
   - order the zones that fire in the same pass (rescue and min-daily > steering > timer > manual);
   - journal and publish the queue;
   - warn (CS-214) about a zone that alone exceeds its pump, which still waters (ruling R1).

   They never refuse a shot. Guard 17 (`exclusive_group`) is recorded only and changes nothing that runs. `max_concurrent_zones > 1` cannot add concurrency without a threaded actuator, which no spec step schedules.
3. **Dosing history** lives in the controller's `/data/dosing_state.json`, not in the integration's dosing store. The ledger file is `jev_ledger.jsonl`, not `ledger.jsonl`. So the M2 backfill is split between the integration (Task 7) and the controller outbox (Task 9).
4. **The integration only vendors `defaults.py`.** The shared `ids.py`, `timers.py` and `guards.py` become new `generated/` copies, and `test_generated_copies.py` is restructured into (source, copy) pairs.
5. **There is no `binary_sensor` platform.** It is new in Task 16. The stub `Platform` enums in `tests/conftest.py` and `__init__.py` list only 5 members.
6. **Conflicts between the UX spec and the schema spec.** The schema wins unless noted.

   | Topic | Decision |
   |---|---|
   | G1 supply settings | `supply_save` in the site store, not `setup_save` keys |
   | G2 capture response | returns both shapes, `{reading, raw, stable, drift, stable_s}` |
   | EC stability | 1 % of reading, not 0.01 mS |
   | G3 commit key | `pump_calibration_commit` is keyed by `session_id` |
   | G6 test vs preview | `alert_rule_test` (saved rule, optional `send`); `alert_rule_preview` (draft rule, series + spans + ignored dips); `alert_rule_list` |
   | G7 timer field names | schema names (`type: one_off\|recycle\|simple`, `interval_min`) |
   | `shot_queued` | per room, with a `queue[]` attribute |
   | G15 units | per-room `display_save` keys `ec_unit`/`temp_unit`/`volume_unit`/`clock` (Task 33), not site `units`: an **intentional spec deviation**, ruling R7 |
   | Alert sources | `probe.silence_s` and `stock.litres` are added to the spec §2.9 source enum: a recorded addition, ruling R7 |
   | `zone_meters` in `supply_save` | an additive deviation from spec §5.2, which lists `zone_groups` only |
   | Guard 16 | a zone alone over its pump **waters anyway** and warns (CS-214 warning), ruling R1; spec §2.7 "queue, never refuse" |
   | G8 `history_revert` | not in the schema; added on the frontend's request (Task 24) |
   | Pump prime cap | 30 s (UX), not the spec's 120 s: an **intentional spec deviation**, ruling R7 |
   | Frontend field names | the backend names win: `metered_l` (frontend `litres_metered`), `requested_at` + `pump_wait_s` (frontend `requested_start`), and `probe.silence_s` in seconds, the canonical unit (the coordinator wrote "minutes") |
7. **`API_VERSION` 1 → 2 would break MCP**, because `schemas.ts` has `api_version: z.literal(1)`. The v1 `setup_read` shape keeps 1, and 2 appears only in the envelope.
8. **`pump_calibrate` cannot return `ran_s` synchronously.** The runner picks requests up on its own cadence, so `ran_s` arrives via `dosing_get` and the commit waits for it. Hold-to-prime is a prime of at most 30 s ended early by `pump_stop`. The stop is seen within one runner wait tick (≤ 2 s) once the runner has picked the request up, but the pickup itself waits on the runner's poll cadence.
9. **Dosing pumps dose by volume** (firmware `volume_entity` + `start_entity`). Timed prime and calibrate need a `power_entity`, and a pump without one is refused with blocker `no_power_entity`.
10. **New CS codes beyond the spec's CS-214:** CS-318, CS-319 and CS-612. Each one needs:
    - a `RESERVED` entry;
    - a `notify_catalog` kind;
    - a rebuild of the three dashboard bundles. The frontend lane owns that rebuild (ruling R11); until it lands, backend tasks deselect `test_no_code_is_defined_twice`.

    In addition, a notification code must be raised by `controller._alert` with a literal code, so integration-raised codes must be Repairs cards.
11. **`_auto_write` → `target.changed` would duplicate** the integration's `setpoint_log` row. Only the integration emits `target.changed` (Task 6).
12. **Twelve controller paths dismiss notifications directly** and would never emit `alert.cleared`. The inbox reconciles against live persistent notifications (Task 27).
13. **Guard 18's probe half is vacuous.** A `fail` verdict is never applied, so an applied calibration is never `fail`. Only the pump half bites.
14. **G16: plans carry no harvest date or stage.** `days_to_harvest` uses the last `end_day`, and `stage` uses the profile name, falling back to the `growth_stage` select.
15. **Existing MCP mismatch, not fixed here.** `schemas.ts` accepts only `switch` for pump, main line and valves, while the integration also accepts `input_boolean`/`valve`.
