# Remember Nights and Plateaus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every zone keeps a record of its daily plateau and of each night from lights-off to the next morning's first shot, in the state file, so the later plans can plan the P2 end from real nights. No watering decision changes.

**Architecture:** A new pure module, `zone_history.py`, owns three per-zone state keys (`plateau_hist`, `night_hist`, `night`). The controller calls it at the lights edges in `_loop_room`, wherever P1 hands over to P2 (the engine, Jev's Ramp judge, the operator's Set Phase select) and in `_advance_shot_counters` for the day's first shot. The keys are seeded, restored and written by the existing `_fresh_zone`, `_apply_saved_zone` and `_serialize_zone`.

**Tech Stack:** Python 3.12 add-on (CI also runs 3.11), pytest, the add-on test doubles (`fake_ha.FakeHA`, a pinned `Clock`), the real-Home-Assistant tier (`tests_ha/`, its `controller_for` fixture).

**Spec:** [docs/superpowers/specs/2026-10-02-dryback-planner-jev-steering-design.md](../specs/2026-10-02-dryback-planner-jev-steering-design.md): "Architecture and invariants" (State), "P3 and the night watch" (the morning record) and "Delivery and verification" step 1. Shared names: [the roadmap](2026-10-02-dryback-00-roadmap.md).

## Global Constraints

- One change, one branch, one pull request, into `testing`. Never open a pull request into `main`, never push to `testing` or `main`, never merge a pull request, never promote a release.
- Class C3 (the state file). Not reviewable without a `tests_ha/` test that fails without the change, and a seeded snapshot of an old install in `tests_ha/fixtures/` proving it still loads and nothing moves (docs/RELEASING.md, "The gate").
- A feature branch never touches a version field or a changelog. The release pull request carries them.
- State, from the spec: "per zone, read with `.get()` and seeded in `_fresh_zone`". "An old state file loads unchanged, proven by a seeded fixture."
- Stored values keep full precision. Only text for people (the activity line, the log) is rounded.
- `decide()`, its inputs and the vendored engine are untouched: this step only records.
- Lint and format: `ruff check .` everywhere; `black --check custom_components/ tests/` (88 columns) covers the root `tests/` folder.
- Docs prose: no em or en dashes.

## Review Focus

1. **The app restarts between lights-off and the first shot.** The open night must come back from the state file and still close into a record the next morning. Pinned by `test_a_restart_in_the_night_keeps_the_open_night` (Task 3).
2. **The probe is unreadable at lights-off or lights-on.** The night still opens, so its shots are counted, and the missing number is recorded as unknown: never a crash, never a made-up rate. Pinned by `test_a_missing_reading_leaves_that_number_unknown` (Task 1) and `test_a_probe_out_at_lights_off_still_opens_the_night` (Task 3).
3. **A day on which P1 never handed over** (the room was off, or lights-off came first). Tonight must not borrow yesterday's plateau, and a night that never reached a first shot is dropped at the next lights-off, not merged into it. Pinned by `test_yesterdays_plateau_is_not_used_for_tonight` and `test_a_night_that_never_reached_a_first_shot_is_dropped_at_the_next_lights_off` (Task 1).
4. **The operator restarts the ramp by hand.** A second hand-over on the same grow day replaces the first plateau, and the second "first shot" finds no open night and records nothing. Pinned by `test_a_second_hand_over_the_same_day_replaces_the_first` and `test_a_first_shot_with_no_night_open_records_nothing` (Task 1).
5. **A damaged history, or one written by a newer version.** Junk entries are dropped on load, good ones kept, and the load never fails. Pinned by `test_restore_keeps_good_entries_and_the_newest_14` (Task 1) and `test_the_history_survives_a_restart_and_junk_in_it_is_dropped` (Task 2).

## Before you start

Branch from the tip of `testing`, in a worktree of your own:

```bash
git fetch origin
git worktree add ../jev-dryback-01 -b feat/dryback-01-remember-nights origin/testing
cd ../jev-dryback-01
```

Line numbers below are from 3.8.0 (`d3e2e19`, the tip of `testing` on 2 Oct 2026). Find each edit by the code it quotes, not by the number.

Test commands, from the repo root:

- add-on suite: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests -q`
- root suite: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q`
- everything CI runs: `bash tests/run_ci.sh`

## File Structure

| File | Change | Responsibility |
| --- | --- | --- |
| `addons/f2_control/f2_control/zone_history.py` | create | The record: plateau and night entries, the open night, restore. Pure. |
| `addons/f2_control/tests/test_zone_history.py` | create | The record's own tests, on zone 1's real numbers. |
| `addons/f2_control/f2_control/controller.py` | modify | Import; seed, restore and write the keys; `_record_phase`; the lights edges; the hand-overs; the first shot. |
| `addons/f2_control/f2_control/jev_bridge.py` | modify | `advance()` records a hand-over Jev made. |
| `addons/f2_control/tests/test_zone_history_runtime.py` | create | The hooks inside the real controller. |
| `tests/test_state_migration.py` | modify | An old file loads with the history empty; the history survives a restart. |
| `tests_ha/fixtures/state_3_8_0_mid_grow.json` | create | What 3.8.0 saved for the 2.17-wizard room mid-grow. |
| `tests_ha/test_upgrade_in_place.py` | modify | The 3.8.0 file loads in a real Home Assistant and nothing moves. |

---

### Task 1: The record

**Files:**
- Create: `addons/f2_control/f2_control/zone_history.py`
- Test: `addons/f2_control/tests/test_zone_history.py`

**Interfaces:**
- Consumes: nothing.
- Produces, for Tasks 2 and 3 and for later plans:
  - `KEEP = 14`
  - `fresh() -> dict`: `{"plateau_hist": [], "night_hist": [], "night": None}`
  - `restore(saved: dict) -> dict`: the same three keys from a saved zone dict, junk dropped
  - `plateau(st, *, day: str, value, how: str, shots) -> dict | None`
  - `phase_changed(st, was: str, new: str, *, day: str, how: str) -> dict | None`: the plateau entry when `was == "P1" and new == "P2"`, else None
  - `lights_off(st, vwc: float | None, now: datetime, day: str) -> None`
  - `lights_on(st, vwc: float | None, now: datetime) -> None`
  - `shot(st, *, vwc_before: float | None, now: datetime, day: str, first: bool) -> dict | None`: the closed night record when `first`, else None
  - `night_words(record: dict) -> str`
  - A plateau entry: `{"date", "value", "how", "shots"}`. A night record: `{"date", "plateau", "off_at", "off_vwc", "on_at", "on_vwc", "first_at", "landing", "night_rate", "p0_drop", "dryback_pct", "night_shots"}`. Times are ISO strings to the second.

- [ ] **Step 1: Write the failing tests**

Create `addons/f2_control/tests/test_zone_history.py`:

```python
"""zone_history.py: each zone's plateaus and nights, the dryback planner's record. The numbers are zone 1's: the
explainer's planned night (36.0 plateau, 32.78 at lights-off, 25.58 at lights-on, first shot from 25.18), and the
real night of 30 Sep 2026, which dried to the 20.7 floor and fired a rescue at 08:59."""
from datetime import datetime

import pytest

import zone_history as H


def _zone(**over):
    st = {"phase": "P2", "peak": 0.0, "shots": 0, **H.fresh()}
    st.update(over)
    return st


def test_a_fresh_zone_and_an_old_file_have_no_history():
    assert H.fresh() == {"plateau_hist": [], "night_hist": [], "night": None}
    assert H.restore({}) == H.fresh()
    junk = {"plateau_hist": "junk", "night_hist": [1, {"no": "date"}], "night": {"off_vwc": 3}}
    assert H.restore(junk) == H.fresh()


def test_restore_keeps_good_entries_and_the_newest_14():
    saved = {
        "plateau_hist": [{"date": f"2026-09-{d:02d}", "value": 30.0 + d, "how": "x", "shots": 6} for d in range(1, 21)],
        "night": {"off_at": "2026-09-30T22:00:00", "off_vwc": 30.81},
    }
    out = H.restore(saved)
    assert [e["date"] for e in out["plateau_hist"]] == [f"2026-09-{d:02d}" for d in range(7, 21)]
    assert out["night"]["off_vwc"] == 30.81 and out["night"]["shots"] == 0 and out["night"]["on_at"] is None


def test_p1_handing_over_records_the_days_plateau():
    st = _zone(phase="P1", peak=36.0, shots=6)
    entry = H.phase_changed(st, "P1", "P2", day="2026-10-01", how="P1 recovered 36>=36 EC ok 4.6")
    assert entry == {"date": "2026-10-01", "value": 36.0, "how": "P1 recovered 36>=36 EC ok 4.6", "shots": 6}
    assert st["plateau_hist"] == [entry]


def test_a_second_hand_over_the_same_day_replaces_the_first():
    st = _zone(peak=35.2, shots=4)
    H.phase_changed(st, "P1", "P2", day="2026-10-01", how="set by hand")
    st.update(peak=36.1, shots=6)
    H.phase_changed(st, "P1", "P2", day="2026-10-01", how="Jev's ramp judge: ramp done")
    assert [(e["value"], e["how"]) for e in st["plateau_hist"]] == [(36.1, "Jev's ramp judge: ramp done")]


def test_only_p1_to_p2_is_a_plateau():
    st = _zone(peak=36.0, shots=6)
    for was, new in (("P0", "P1"), ("P2", "P3"), ("P1", "P3"), ("P3", "P0"), ("P1", "P0")):
        assert H.phase_changed(st, was, new, day="2026-10-01", how="x") is None
    assert H.phase_changed(_zone(peak=0.0), "P1", "P2", day="2026-10-01", how="x") is None
    assert st["plateau_hist"] == []


def test_a_clean_night_from_lights_off_to_the_first_shot():
    st = _zone(plateau_hist=[{"date": "2026-10-01", "value": 36.0, "how": "x", "shots": 6}])
    H.lights_off(st, 32.78, datetime(2026, 10, 1, 22, 0), "2026-10-01")
    H.lights_on(st, 25.58, datetime(2026, 10, 2, 10, 0))
    rec = H.shot(st, vwc_before=25.18, now=datetime(2026, 10, 2, 10, 30), day="2026-10-02", first=True)
    assert st["night"] is None and st["night_hist"] == [rec]
    assert (rec["date"], rec["plateau"], rec["landing"], rec["night_shots"]) == ("2026-10-02", 36.0, 25.18, 0)
    assert (rec["off_at"], rec["on_at"], rec["first_at"]) == (
        "2026-10-01T22:00:00", "2026-10-02T10:00:00", "2026-10-02T10:30:00")
    assert rec["night_rate"] == pytest.approx(0.6) and rec["p0_drop"] == pytest.approx(0.4)
    assert rec["dryback_pct"] == pytest.approx((36.0 - 25.18) / 36.0 * 100.0)
    assert H.night_words(rec) == "night: landed 25.18 (30.1 % under 36.00), 0.60 pts/h, P0 drop 0.40"


def test_30_sep_the_nights_rate_stops_at_the_rescue_shot():
    st = _zone(plateau_hist=[{"date": "2026-09-30", "value": 35.0, "how": "x", "shots": 8}])
    H.lights_off(st, 30.81, datetime(2026, 9, 30, 22, 0), "2026-09-30")
    assert H.shot(st, vwc_before=20.7, now=datetime(2026, 10, 1, 8, 59), day="2026-09-30", first=False) is None
    H.lights_on(st, 24.12, datetime(2026, 10, 1, 10, 0))
    rec = H.shot(st, vwc_before=24.12, now=datetime(2026, 10, 1, 10, 2), day="2026-10-01", first=True)
    assert rec["night_rate"] == pytest.approx((30.81 - 20.7) / (10 + 59 / 60))  # 0.92 an hour, down to the rescue
    assert rec["night_shots"] == 1 and rec["p0_drop"] == pytest.approx(0.0)
    assert rec["dryback_pct"] == pytest.approx((35.0 - 24.12) / 35.0 * 100.0)
    assert H.night_words(rec).endswith(", 1 night shot(s)")


def test_a_shot_after_lights_on_spoils_only_the_p0_drop():
    st = _zone()
    H.lights_off(st, 32.78, datetime(2026, 10, 1, 22, 0), "2026-10-01")
    H.lights_on(st, 25.58, datetime(2026, 10, 2, 10, 0))
    H.shot(st, vwc_before=25.4, now=datetime(2026, 10, 2, 10, 10), day="2026-10-02", first=False)  # a P0 shot
    rec = H.shot(st, vwc_before=26.0, now=datetime(2026, 10, 2, 10, 40), day="2026-10-02", first=True)
    assert rec["night_rate"] == pytest.approx(0.6)  # lights-off to lights-on: the night itself had no shot
    assert rec["p0_drop"] is None and rec["night_shots"] == 1
    assert rec["plateau"] is None and rec["dryback_pct"] is None  # no plateau was recorded on 1 Oct


def test_a_night_that_never_reached_a_first_shot_is_dropped_at_the_next_lights_off():
    st = _zone()
    H.lights_off(st, 32.78, datetime(2026, 10, 1, 22, 0), "2026-10-01")
    H.lights_on(st, 25.58, datetime(2026, 10, 2, 10, 0))  # the zone was off all day: no ramp
    H.lights_off(st, 30.0, datetime(2026, 10, 2, 22, 0), "2026-10-02")
    assert st["night"]["off_at"] == "2026-10-02T22:00:00" and st["night"]["on_at"] is None
    assert st["night_hist"] == []


def test_a_missing_reading_leaves_that_number_unknown():
    st = _zone()
    H.lights_off(st, None, datetime(2026, 10, 1, 22, 0), "2026-10-01")  # the probe was unreadable
    H.lights_on(st, 25.58, datetime(2026, 10, 2, 10, 0))
    rec = H.shot(st, vwc_before=25.18, now=datetime(2026, 10, 2, 10, 30), day="2026-10-02", first=True)
    assert rec["night_rate"] is None and rec["p0_drop"] == pytest.approx(0.4)
    assert "unknown pts/h" in H.night_words(rec)


def test_a_first_shot_with_no_night_open_records_nothing():
    st = _zone()
    assert H.shot(st, vwc_before=25.18, now=datetime(2026, 10, 2, 10, 30), day="2026-10-02", first=True) is None
    assert st["night_hist"] == []


def test_yesterdays_plateau_is_not_used_for_tonight():
    st = _zone(plateau_hist=[{"date": "2026-09-30", "value": 36.0, "how": "x", "shots": 6}])
    H.lights_off(st, 31.0, datetime(2026, 10, 1, 22, 0), "2026-10-01")  # P1 never handed over on 1 Oct
    assert st["night"]["plateau"] is None


def test_the_lists_keep_the_newest_14():
    st = _zone(peak=36.0, shots=6)
    for d in range(1, 21):
        H.phase_changed(st, "P1", "P2", day=f"2026-09-{d:02d}", how="x")
    assert len(st["plateau_hist"]) == H.KEEP == 14 and st["plateau_hist"][0]["date"] == "2026-09-07"
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests/test_zone_history.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'zone_history'`.

- [ ] **Step 3: Write the module**

Create `addons/f2_control/f2_control/zone_history.py`:

```python
"""Each zone's own record of its plateaus and its nights, for the dryback planner
(docs/superpowers/specs/2026-10-02-dryback-planner-jev-steering-design.md). Pure: it reads and writes the zone's
state dict and nothing else.

- plateau_hist: one entry per grow day whose P1 handed over to P2: the VWC it reached, how P1 ended, and after how
  many shots. A second hand-over on the same grow day replaces the first.
- night_hist: one entry per morning: the night from lights-off to the day's first shot, where Athena measures the
  landing (p.39), with the night's drying rate and the P0 drop.
- night: the night being measured now, from the lights-off reading until the day's first shot closes it.

Both lists keep the newest KEEP entries. A state file from before this module has none of the three keys and loads
with them empty. Stored values keep full precision; only night_words() rounds, for people to read.
"""
from __future__ import annotations

from datetime import datetime

KEEP = 14


def fresh():
    return {"plateau_hist": [], "night_hist": [], "night": None}


def _night(off_at, off_vwc, plateau):
    return {"off_at": off_at, "off_vwc": off_vwc, "plateau": plateau, "on_at": None, "on_vwc": None,
            "on_shots": 0, "shots": 0, "end_at": None, "end_vwc": None}


def restore(saved):
    """The three keys from a saved zone dict, dropping anything malformed instead of failing the load."""
    out = fresh()
    for key in ("plateau_hist", "night_hist"):
        items = saved.get(key)
        if isinstance(items, list):
            out[key] = [dict(x) for x in items if isinstance(x, dict) and isinstance(x.get("date"), str)][-KEEP:]
    night = saved.get("night")
    if isinstance(night, dict) and isinstance(night.get("off_at"), str):
        out["night"] = {**_night(night["off_at"], None, None), **night}
    return out


def _iso(t):
    return t.isoformat(timespec="seconds")


def _hours(start, end):
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 3600.0


def plateau(st, *, day, value, how, shots):
    """Record the grow day's plateau. Nothing is recorded (None) without a usable value."""
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    entry = {"date": day, "value": float(value), "how": str(how)[:80], "shots": int(shots or 0)}
    kept = [e for e in st.get("plateau_hist") or [] if e.get("date") != day]
    st["plateau_hist"] = (kept + [entry])[-KEEP:]
    return entry


def phase_changed(st, was, new, *, day, how):
    """A phase change by anyone (the engine, a Jev judge, the operator). P1 handing over to P2 is the day's plateau:
    the highest VWC since lights-on, which the controller keeps in `peak`."""
    if was == "P1" and new == "P2":
        return plateau(st, day=day, value=st.get("peak"), how=how, shots=st.get("shots"))
    return None


def lights_off(st, vwc, now, day):
    """The lights went off: tonight is measured from this reading. A night still open (no first shot came) is
    dropped. `day` is the grow day that is ending: its plateau, when P1 found one, is what the landing is measured
    from, never an older day's."""
    last = (st.get("plateau_hist") or [None])[-1]
    st["night"] = _night(_iso(now), vwc, last["value"] if last and last.get("date") == day else None)


def lights_on(st, vwc, now):
    """The lights came on: the night's last reading, and the shots so far, so a shot in P0 can be told apart."""
    n = st.get("night")
    if n is not None and n["on_at"] is None:
        n["on_at"], n["on_vwc"], n["on_shots"] = _iso(now), vwc, n["shots"]


def shot(st, *, vwc_before, now, day, first):
    """A shot was delivered. The day's first shot (`first`) closes the night: the VWC just before it is the landing,
    and the record goes into night_hist. Any other shot while a night is open is counted; the night's rate is
    measured up to the first one that came before lights-on. Returns the closed record, or None."""
    n = st.get("night")
    if n is None:
        return None
    if not first:
        if n["on_at"] is None and n["end_at"] is None:
            n["end_at"], n["end_vwc"] = _iso(now), vwc_before
        n["shots"] += 1
        return None
    st["night"] = None
    record = _close(n, vwc_before, now, day)
    kept = [e for e in st.get("night_hist") or [] if e.get("date") != day]
    st["night_hist"] = (kept + [record])[-KEEP:]
    return record


def _close(n, landing, now, day):
    end_at, end_vwc = (n["end_at"], n["end_vwc"]) if n["end_at"] else (n["on_at"], n["on_vwc"])
    rate = None
    if n["off_vwc"] is not None and end_vwc is not None and end_at is not None:
        hours = _hours(n["off_at"], end_at)
        if hours > 0:
            rate = (n["off_vwc"] - end_vwc) / hours
    drop = None
    if n["on_vwc"] is not None and landing is not None and n["shots"] == n["on_shots"]:
        drop = n["on_vwc"] - landing
    top = n["plateau"]
    dryback = (top - landing) / top * 100.0 if top and landing is not None else None
    return {"date": day, "plateau": top, "off_at": n["off_at"], "off_vwc": n["off_vwc"], "on_at": n["on_at"],
            "on_vwc": n["on_vwc"], "first_at": _iso(now), "landing": landing, "night_rate": rate,
            "p0_drop": drop, "dryback_pct": dryback, "night_shots": n["shots"]}


def night_words(r):
    """The morning record in one line, for the activity feed and the log."""
    def num(v):
        return "unknown" if v is None else f"{v:.2f}"

    words = f"night: landed {num(r['landing'])}"
    if r["dryback_pct"] is not None:
        words += f" ({r['dryback_pct']:.1f} % under {r['plateau']:.2f})"
    words += f", {num(r['night_rate'])} pts/h, P0 drop {num(r['p0_drop'])}"
    if r["night_shots"]:
        words += f", {r['night_shots']} night shot(s)"
    return words
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests/test_zone_history.py -q`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add addons/f2_control/f2_control/zone_history.py addons/f2_control/tests/test_zone_history.py
git commit -m "Add the zone history record: plateaus and nights" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Keep the history in the state file

**Files:**
- Modify: `addons/f2_control/f2_control/controller.py` (imports at 33-37; `_fresh_zone` 814-838; `_apply_saved_zone` 840-904; `_serialize_zone` 1231-1258)
- Test: `tests/test_state_migration.py`

**Interfaces:**
- Consumes: `zone_history.fresh()`, `zone_history.restore(saved)` (Task 1).
- Produces: every zone dict in `room.state` holds `plateau_hist`, `night_hist` and `night`, after a fresh start, a load of any older file, or a load of this version's file; `_save_state()` writes them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state_migration.py` (it already imports `json` and defines `_make`):

```python
def test_an_old_file_without_history_loads_with_it_empty(tmp_path):
    """3.8.0 kept no plateau or night history: its file loads as it was, history empty."""
    p = tmp_path / "state.json"
    p.write_text(
        json.dumps({"default": {"1": {"phase": "P2", "peak": 36.1, "shots": 9}}}),
        encoding="utf-8",
    )
    c = _make([1], p)
    c._load_state()
    st = c.rooms[0].state[1]
    assert (st["phase"], st["peak"], st["shots"]) == ("P2", 36.1, 9)
    assert (st["plateau_hist"], st["night_hist"], st["night"]) == ([], [], None)


def test_the_history_survives_a_restart_and_junk_in_it_is_dropped(tmp_path):
    p = tmp_path / "state.json"
    c = _make([1], p)
    c._load_state()
    plateau = {"date": "2026-10-01", "value": 36.0, "how": "P1 recovered", "shots": 6}
    night = {
        "off_at": "2026-10-01T22:00:00",
        "off_vwc": 32.78,
        "plateau": 36.0,
        "on_at": None,
        "on_vwc": None,
        "on_shots": 0,
        "shots": 0,
        "end_at": None,
        "end_vwc": None,
    }
    c.rooms[0].state[1].update(plateau_hist=[plateau, "junk"], night=night)
    c._save_state()
    c2 = _make([1], p)
    c2._load_state()
    st = c2.rooms[0].state[1]
    assert st["plateau_hist"] == [plateau] and st["night_hist"] == []
    assert st["night"] == night
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_state_migration.py -q -k history`
Expected: 2 failed, `KeyError: 'plateau_hist'`.

- [ ] **Step 3: Seed, restore and write the keys**

In `addons/f2_control/f2_control/controller.py`, import the module with its neighbours:

```python
import auto_setpoints
import dosing_runner
import zone_history
import jev_bridge
```

In `_fresh_zone`, add the keys after `"learn"`:

```python
            "water_history_legacy_excluded_l": 0.0,
            "learn": auto_setpoints.fresh(),
            **zone_history.fresh(),
        }
```

At the end of `_apply_saved_zone`, restore them before returning:

```python
        try:
            excluded = float(d.get("water_history_legacy_excluded_l", 0.0))
            if math.isfinite(excluded) and excluded >= 0:
                s["water_history_legacy_excluded_l"] = excluded
        except (TypeError, ValueError):
            pass
        s.update(zone_history.restore(d))
        return s
```

At the end of the dict `_serialize_zone` returns, write them:

```python
            "last_daily_reset": ldr.isoformat() if isinstance(ldr, date) else None,
            "plateau_hist": s.get("plateau_hist") or [],
            "night_hist": s.get("night_hist") or [],
            "night": s.get("night"),
        }
```

- [ ] **Step 4: Run the state tests**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_state_migration.py -q`
Expected: all pass, the two new ones included.

Run: `black --check tests/test_state_migration.py`
Expected: `1 file would be left unchanged.` (If not, run `black tests/test_state_migration.py` and check the diff is only layout.)

- [ ] **Step 5: Commit**

```bash
git add addons/f2_control/f2_control/controller.py tests/test_state_migration.py
git commit -m "Keep each zone's plateau and night history in the state file" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Record at the lights edges, every hand-over and the first shot

**Files:**
- Modify: `addons/f2_control/f2_control/controller.py` (`_advance_shot_counters` 2757-2781 and a new `_record_phase` after it; `_apply_phase_request` 3765-3790; `_loop_room` 3873-3893 and its phase-change block 3936-3946)
- Modify: `addons/f2_control/f2_control/jev_bridge.py` (`advance()` 266-277)
- Test: `addons/f2_control/tests/test_zone_history_runtime.py`

**Interfaces:**
- Consumes: `zone_history.lights_off`, `zone_history.lights_on`, `zone_history.shot`, `zone_history.phase_changed`, `zone_history.night_words` (Task 1); the persisted keys (Task 2).
- Produces: `Controller._record_phase(room, zone, st, was, new, now, how) -> None`, called wherever P1 can hand over to P2. Each zone's `night` opens at lights-off, reads lights-on, and closes into `night_hist` at the day's first shot, which also adds an activity line `HH:MM Zn night: landed ...`.

- [ ] **Step 1: Write the failing tests**

Create `addons/f2_control/tests/test_zone_history_runtime.py`:

```python
"""The plateau and night history inside the real controller: the lights edges, each way P1 hands over (the engine,
Jev's Ramp judge, the operator), the day's first shot, and an app restart in the night."""
from datetime import date, datetime, timedelta, timezone

import pytest

import controller
import fake_ha
import jev_bridge
import jev_kit as K
from jev.envelope import Directive


class Clock(datetime):
    """The controller's wall clock, pinned by the test."""

    instant = None

    @classmethod
    def now(cls, tz=None):
        return cls.instant.replace(tzinfo=tz) if tz else cls.instant


@pytest.fixture
def rig(monkeypatch, tmp_path):
    """A two-zone room, lights 10:00-22:00, armed, on 23 Sep 2026 at 11:00."""
    Clock.instant = Clock(2026, 9, 23, 11, 0)
    monkeypatch.setattr(controller, "datetime", Clock)
    fake = fake_ha.FakeHA()
    options = {
        "num_zones": 2,
        "hardware": {"pump": "switch.p", "mainline": "switch.m", "valves": {"1": "switch.v1", "2": "switch.v2"}},
        "enable_flag": "input_boolean.kill",
    }
    monkeypatch.setattr(controller, "load_options", lambda: options)
    for name in ("ha_get", "ha_call", "ha_get_all", "ha_set"):
        monkeypatch.setattr(controller, name, getattr(fake, name))
    with monkeypatch.context() as setup:
        setup.setattr(controller.Controller, "_read_state_file", lambda self: {})
        c = controller.Controller()
    c._state_path = str(tmp_path / "state.json")
    for eid in ("input_boolean.kill", "switch.crop_steering_system_enabled",
                "switch.crop_steering_auto_irrigation_enabled",
                "switch.crop_steering_zone_1_enabled", "switch.crop_steering_zone_2_enabled"):
        fake.set_state(eid, "on")
    for eid in ("switch.p", "switch.m", "switch.v1", "switch.v2"):
        fake.set_state(eid, "off")
    seconds = {"now": 0.0}
    monkeypatch.setattr(controller.time, "monotonic", lambda: seconds["now"])
    monkeypatch.setattr(controller.time, "sleep", lambda dt: seconds.__setitem__("now", seconds["now"] + dt))
    return c, fake, c.rooms[0]


def _loop(c, fake, room, at, vwc1, vwc2=61.0):
    """One pass at `at` with fresh readings. Every reading here is above the default re-water threshold (45) and
    emergency floor (40), so nothing fires; `vwc1=None` is an unreadable zone 1 probe."""
    Clock.instant = at
    stamp = Clock.now(timezone.utc).isoformat()
    for zone, vwc in ((1, vwc1), (2, vwc2)):
        value = "unavailable" if vwc is None else str(vwc)
        fake.set_state(f"sensor.crop_steering_vwc_zone_{zone}", value, last_updated=stamp)
        fake.set_state(f"sensor.crop_steering_ec_zone_{zone}", "4.5", last_updated=stamp)
    return c._loop_room(room, at)


def test_lights_off_opens_the_night_lights_on_reads_it_and_the_first_shot_closes_it(rig):
    c, fake, room = rig
    st = room.state[1]
    st.update(phase="P2", peak=61.0, last_daily_reset=date(2026, 9, 23),
              plateau_hist=[{"date": "2026-09-23", "value": 61.0, "how": "P1 recovered", "shots": 6}])
    room._was_lights_on = True
    _loop(c, fake, room, Clock(2026, 9, 23, 22, 0), 58.4)
    assert st["night"]["off_vwc"] == 58.4 and st["night"]["plateau"] == 61.0
    _loop(c, fake, room, Clock(2026, 9, 24, 10, 0), 51.2)
    assert st["night"]["on_vwc"] == 51.2
    Clock.instant = Clock(2026, 9, 24, 10, 30)
    st.update(phase="P1", shots=0, last_vwc=50.8)  # the ramp's first shot, from 50.8
    c._advance_shot_counters(room, 1, 3.0)
    rec = st["night_hist"][-1]
    assert (rec["date"], rec["landing"], rec["night_shots"]) == ("2026-09-24", 50.8, 0)
    assert rec["night_rate"] == pytest.approx(0.6) and rec["p0_drop"] == pytest.approx(0.4)
    assert st["night"] is None
    assert any("Z1 night: landed 50.80" in line for line in c._activity)


def test_a_restart_in_the_night_keeps_the_open_night(rig):
    c, fake, room = rig
    room.state[1].update(phase="P2", last_daily_reset=date(2026, 9, 23))
    room._was_lights_on = True
    _loop(c, fake, room, Clock(2026, 9, 23, 22, 0), 58.4)
    c._load_state()  # the app restarted at 03:00: the zones come back from the file
    room._was_lights_on = None  # and the new process has not seen the lights yet
    _loop(c, fake, room, Clock(2026, 9, 24, 3, 0), 54.0)
    _loop(c, fake, room, Clock(2026, 9, 24, 10, 0), 51.2)
    night = room.state[1]["night"]
    assert night["off_vwc"] == 58.4 and night["on_vwc"] == 51.2


def test_a_probe_out_at_lights_off_still_opens_the_night(rig):
    c, fake, room = rig
    room.state[1].update(phase="P2", last_daily_reset=date(2026, 9, 23))
    room._was_lights_on = True
    _loop(c, fake, room, Clock(2026, 9, 23, 22, 0), None)
    night = room.state[1]["night"]
    assert night is not None and night["off_vwc"] is None and night["off_at"] == "2026-09-23T22:00:00"


def test_the_engine_handing_p1_over_records_the_plateau(rig):
    c, fake, room = rig
    now = Clock.now()
    room.state[1].update(phase="P1", shots=6, last_shot=now - timedelta(minutes=16), last_daily_reset=now.date(),
                         ec_settled=4.5, ec_settled_at=now - timedelta(hours=2))
    _loop(c, fake, room, now, 61.0)
    st = room.state[1]
    assert st["phase"] == "P2"
    [entry] = st["plateau_hist"]
    assert (entry["date"], entry["value"], entry["shots"]) == ("2026-09-23", 61.0, 6)
    assert entry["how"].startswith("P1 recovered 61>=60")


def test_jevs_ramp_judge_handing_over_records_the_plateau(rig):
    c, fake, room = rig
    now = Clock.now()
    st = room.state[1]
    st.update(phase="P1", peak=36.1, shots=5)
    d = Directive("ramp", "advance", "P2", "ramp done: block_is_full (hand over p=0.84)", now + timedelta(minutes=45))
    jev_bridge.advance(c, room, 1, K.snap(phase="P1", vwc=36.0), d, now)
    assert st["phase"] == "P2"
    assert st["plateau_hist"] == [{"date": "2026-09-23", "value": 36.1, "shots": 5,
                                   "how": "Jev's ramp judge: ramp done: block_is_full (hand over p=0.84)"}]


def test_a_hand_over_set_by_hand_records_the_plateau(rig):
    c, fake, room = rig
    st = room.state[1]
    st.update(phase="P1", peak=44.0, shots=4)
    fake.set_state("select.crop_steering_zone_1_set_phase", "P2")
    c._apply_phase_request(room, 1, st, Clock.now())
    assert st["phase"] == "P2"
    assert st["plateau_hist"] == [{"date": "2026-09-23", "value": 44.0, "how": "set by hand", "shots": 4}]
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests/test_zone_history_runtime.py -q`
Expected: 6 failed. The night tests fail on `night` being `None` (`TypeError: 'NoneType' object is not subscriptable`, or the `is not None` assertion): nothing opens a night yet. The hand-over tests fail on an empty `plateau_hist` (`ValueError: not enough values to unpack`, or `assert [] == [...]`).

- [ ] **Step 3: Record the day's first shot, and add `_record_phase`**

In `_advance_shot_counters`, between the learner's line and the shot count (`day` is already set at the top of the method):

```python
        auto_setpoints.shot(st["learn"], st.get("phase"), size_pct, st.get("last_vwc"), now.timestamp())
        # the day's first shot closes the night: the VWC it started from is what the zone landed on
        record = zone_history.shot(st, vwc_before=st.get("last_vwc"), now=now, day=day,
                              first=st.get("phase") == "P1" and st["shots"] == 0)
        if record is not None:
            words = zone_history.night_words(record)
            tag = "" if room.prefix == "" else f"{room.slug} "
            self._activity.insert(0, f"{now.strftime('%H:%M')} {tag}Z{zone} {words}"[:120])
            log(f"[{room.slug}] Z{zone} {words}")
        st["shots"] += 1
```

Directly after `_advance_shot_counters` (before the `# ---------- hardware` comment), add:

```python
    def _record_phase(self, room, zone, st, was, new, now, how):
        """Keep the zone's history on a phase change by anyone (the engine, a Jev judge, the operator's Set Phase):
        P1 handing over to P2 is the day's plateau."""
        entry = zone_history.phase_changed(st, was, new, day=self._grow_day_start(room, now).isoformat(), how=how)
        if entry is not None:
            log(f"[{room.slug}] Z{zone} plateau {entry['value']:.2f} after {entry['shots']} shots: {entry['how']}")
```

- [ ] **Step 4: Call `_record_phase` wherever P1 can hand over**

In `_apply_phase_request` (the operator's Set Phase select):

```python
        was = st["phase"]
        if wanted == was:
            return
        self._record_phase(room, zone, st, was, wanted, now, "set by hand")
        if wanted == "P0":
            st["peak"] = 0.0
```

In `_loop_room`'s phase-change block (the engine's own move), after the push is queued:

```python
            if new_phase != st["phase"]:
                # decide()'s reason leads with why the phase moved ("lights-off -> P3 | ..."): the push says it.
                self._notify_event("phase", room, zone, st["phase"], new_phase, str(reason).split(" | ")[0])
                self._record_phase(room, zone, st, st["phase"], new_phase, now, str(reason).split(" | ")[0])
                if new_phase == "P0":
```

In `addons/f2_control/f2_control/jev_bridge.py`, `advance()` (a judge's move):

```python
    st = room.state[zone]
    was, st["phase"] = st["phase"], d.value
    c._record_phase(room, zone, st, was, d.value, now, f"Jev's {d.judge} judge: {d.why}")
    st["last_phase_change"] = now
```

- [ ] **Step 5: Take the night's readings at the lights edges**

In `_loop_room`, next to `lights_just_on`:

```python
        lights_just_on = lights_on and was_off
        lights_just_off = room._was_lights_on is True and not lights_on
        snaps, decisions, healthy, blind, params = {}, {}, [], [], {}
```

In the zone loop, right after the snapshot is taken:

```python
            snap, p = self._snapshot(room, zone, now, lights_on, lights_just_on)
            params[zone] = p
            if lights_just_off or lights_just_on:  # the night's two readings (zone_history.py); kept across a restart
                vwc = snap.vwc if snap is not None else None
                if lights_just_off:
                    zone_history.lights_off(st, vwc, now, self._grow_day_start(room, now).isoformat())
                else:
                    zone_history.lights_on(st, vwc, now)
                self._save_state()
```

`room._was_lights_on` is `None` until a process has seen one pass, so neither edge fires on the first pass after a start.

- [ ] **Step 6: Run the new tests, then the whole add-on suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests/test_zone_history_runtime.py addons/f2_control/tests/test_zone_history.py -q`
Expected: `19 passed`.

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest addons/f2_control/tests -q`
Expected: everything passes. A failure in an existing test means a hook changed behaviour: the hooks only write the three new keys, one log line and one activity line, so read the failure before touching any test.

- [ ] **Step 7: Commit**

```bash
git add addons/f2_control/f2_control/controller.py addons/f2_control/f2_control/jev_bridge.py addons/f2_control/tests/test_zone_history_runtime.py
git commit -m "Record each zone's plateau at the hand-over and its night at the first shot" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: A seeded 3.8.0 state file in a real Home Assistant

**Files:**
- Create: `tests_ha/fixtures/state_3_8_0_mid_grow.json`
- Modify: `tests_ha/test_upgrade_in_place.py` (imports at 12-24; one new test after `test_the_controller_carries_straight_on_after_the_upgrade_without_a_disarm_cycle`)

**Interfaces:**
- Consumes: `_upgrade`, `KILL` and `fixture` already in `test_upgrade_in_place.py`; the `controller_for` fixture (`tests_ha/conftest.py:71`), whose `saved_state` is written to `F2_STATE_PATH` before the controller starts.
- Produces: the C3 proof that a box upgraded from 3.8.0 keeps every zone exactly as it was.

- [ ] **Step 1: Add the seeded snapshot**

Create `tests_ha/fixtures/state_3_8_0_mid_grow.json`. It is what 3.8.0's own `_serialize_zone` wrote for the 2.17-wizard room (`entry_2_17_wizard.json`), with the setup fingerprint that room adopts:

```json
{
 "_about": "What controller 3.8.0 saved in /data/state.json for the 2.17-wizard room (entry_2_17_wizard.json) mid-grow on 1 Oct 2026: zone 1 in P2 after its ramp, zone 2 still ramping, the rate EWMAs learned, and the setup fingerprint it adopted. Written by 3.8.0's own _serialize_zone. It has no plateau or night history: 3.8.0 kept none.",
 "state": {
  "default": {
   "1": {
    "phase": "P2",
    "peak": 36.1,
    "shots": 9,
    "daily_vol": 63.0,
    "water_history": [
     {"grow_day": "2026-09-30", "litres": 58.5, "complete": true},
     {"grow_day": "2026-10-01", "litres": 63.0, "complete": false}
    ],
    "water_history_legacy_excluded_l": 0.0,
    "learn": {
     "peak_adj": 0.0,
     "jev": {"day": null, "nudged": [], "asked": null, "last": null, "changed": null},
     "peak": 36.0,
     "gain": 0.62,
     "day_rate": 0.87,
     "night_rate": 0.45,
     "day_n": 6,
     "night_n": 6,
     "day_acc": [0.0, 0],
     "night_acc": [0.0, 0],
     "hold_days": 0,
     "day": "2026-10-01",
     "ramp_start": null,
     "ramp": [],
     "pending": null,
     "outcome": "plateau",
     "stalled_at": null,
     "last_change": "2026-09-30 p1_target_vwc 41 -> 36",
     "prev_peak": null,
     "prev_hold": 0,
     "veto": null
    },
    "ec_smooth": 4.62,
    "ec_settled": 4.7,
    "ec_settled_at": "2026-10-01T15:40:00",
    "ec_offset": 1.5,
    "ec_integral": 0.4,
    "ec_prev_err": 0.2,
    "last_shot": "2026-10-01T15:28:00",
    "last_shot_is_anchor": false,
    "last_phase_change": "2026-10-01T12:10:00",
    "last_ec_steer": "2026-10-01T15:30:00",
    "last_daily_reset": "2026-10-01"
   },
   "2": {
    "phase": "P1",
    "peak": 44.2,
    "shots": 3,
    "daily_vol": 21.0,
    "water_history": [
     {"grow_day": "2026-10-01", "litres": 21.0, "complete": false}
    ],
    "water_history_legacy_excluded_l": 0.0,
    "learn": {
     "peak_adj": 0.0,
     "jev": {"day": null, "nudged": [], "asked": null, "last": null, "changed": null},
     "peak": null,
     "gain": null,
     "day_rate": 0.52,
     "night_rate": 0.31,
     "day_n": 4,
     "night_n": 4,
     "day_acc": [0.0, 0],
     "night_acc": [0.0, 0],
     "hold_days": 0,
     "day": "2026-10-01",
     "ramp_start": null,
     "ramp": [],
     "pending": null,
     "outcome": "pending",
     "stalled_at": null,
     "last_change": "",
     "prev_peak": null,
     "prev_hold": 0,
     "veto": null
    },
    "ec_smooth": 3.9,
    "ec_settled": null,
    "ec_settled_at": null,
    "ec_offset": 0.0,
    "ec_integral": 0.0,
    "ec_prev_err": 0.0,
    "last_shot": "2026-10-01T11:10:00",
    "last_shot_is_anchor": false,
    "last_phase_change": "2026-10-01T10:30:00",
    "last_ec_steer": null,
    "last_daily_reset": "2026-10-01"
   },
   "_room_active": true,
   "_setup": {
    "revision": 4,
    "fingerprint": "{\"active\": true, \"enable_flag\": \"switch.crop_steering_engine_enabled\", \"feed_ec_sensor\": \"sensor.feed_ec\", \"feed_ph_sensor\": \"sensor.feed_ph\", \"mainline\": \"switch.main_line\", \"pump\": \"switch.main_pump\", \"valves\": {\"1\": \"switch.row_1_valve\", \"2\": \"switch.row_2_valve\"}, \"zones\": [1, 2]}"
   }
  }
 }
}
```

- [ ] **Step 2: Write the failing test**

In `tests_ha/test_upgrade_in_place.py`, add to the imports:

```python
import json
import os
from pathlib import Path
```

(`json` is already imported; add `os` and `Path`.) Then add, after `test_the_controller_carries_straight_on_after_the_upgrade_without_a_disarm_cycle`:

```python
async def test_a_3_8_0_state_file_loads_with_its_history_empty_and_nothing_moves(
    hass, controller_for
):
    """3.8.0 kept no plateau or night history (tests_ha/fixtures/state_3_8_0_mid_grow.json).
    The new controller loads that file exactly as it was, starts the history empty, and writing
    it back changes nothing else."""
    await _upgrade(hass, "entry_2_17_wizard.json")
    seed = fixture("state_3_8_0_mid_grow.json")["state"]
    hass.states.async_set(KILL, "on")

    c, _fake, _clock = controller_for({"enable_flag": KILL}, saved_state=seed)
    room = c.rooms[0]

    assert room._setup_pending is None, room._setup_pending
    for zone in (1, 2):
        st, old = room.state[zone], seed["default"][str(zone)]
        assert (st["phase"], st["peak"], st["shots"], st["daily_vol"]) == (
            old["phase"],
            old["peak"],
            old["shots"],
            old["daily_vol"],
        )
        assert st["learn"]["night_rate"] == old["learn"]["night_rate"]
        assert (st["plateau_hist"], st["night_hist"], st["night"]) == ([], [], None)
    assert c._save_state()
    saved = json.loads(Path(os.environ["F2_STATE_PATH"]).read_text(encoding="utf-8"))
    for zone in ("1", "2"):
        written = dict(saved["default"][zone])
        kept = (written.pop("plateau_hist"), written.pop("night_hist"), written.pop("night"))
        assert kept == ([], [], None)
        assert written == seed["default"][zone]
```

- [ ] **Step 3: Run it**

Home Assistant's test harness needs Linux and Python 3.14.2 or later. Run it in WSL. WSL shares one memory cap with Docker Desktop, where AiGrow runs live: check `wsl -d Ubuntu -- free -g` first, and with under 3 GB available skip to the CI route below. Create the virtualenv once (install uv in WSL first if `which uv` finds nothing):

```bash
wsl -d Ubuntu -- bash -lc 'cd /mnt/c/Github/jev-dryback-01 && uv venv --python 3.14 ~/ha-venv && uv pip install --python ~/ha-venv/bin/python -r requirements-test-ha.txt'
```

Then:

```bash
wsl -d Ubuntu -- bash -lc 'cd /mnt/c/Github/jev-dryback-01 && ~/ha-venv/bin/python -m pytest tests_ha/test_upgrade_in_place.py -q'
```

Expected: every test passes. To see the new test fail without this plan's change, run it on `origin/testing` with only the fixture and the test added: it fails with `KeyError: 'plateau_hist'`.

If WSL is not available, push the branch and read the "real Home Assistant" job of the `Validate` run. Do not report this tier as passing without seeing it pass.

- [ ] **Step 4: Commit**

```bash
git add tests_ha/fixtures/state_3_8_0_mid_grow.json tests_ha/test_upgrade_in_place.py
git commit -m "Prove a 3.8.0 state file loads with the history empty and nothing moving" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The whole branch, and the pull request

**Files:** none changed.

- [ ] **Step 1: Run everything CI runs**

Run: `bash tests/run_ci.sh`
Expected: `ALL CHECKS PASSED`. With the real-Home-Assistant tier run separately in WSL (Task 4), `bash tests/run_ci.sh --allow-skip` must end `PARTIAL: real Home Assistant tier skipped` with no other failure.

- [ ] **Step 2: Push the branch and open the pull request into `testing`**

```bash
git push -u origin feat/dryback-01-remember-nights
gh pr create --repo JakeTheRabbit/HA-Crop-Steering-Jev --base testing --head feat/dryback-01-remember-nights \
  --title "Remember each zone's plateau and nights (dryback planner, step 1)" --body-file pr-body.md
```

`pr-body.md` (write it outside the repository, for example in your scratch directory, and pass its path):

```markdown
Step 1 of the dryback planner: docs/superpowers/plans/2026-10-02-dryback-00-roadmap.md.

Each zone now keeps, in the state file:
- its plateau each day: the VWC P1 reached when it handed over to P2, how P1 ended, and after how many shots (the engine, Jev's Ramp judge, or Set Phase by hand);
- each night: the lights-off and lights-on readings, the landing at the day's first shot, the night's drying rate (to lights-on, or to the first shot before it), the P0 drop, and every shot before the first.

The morning record shows as one activity line per zone, "Zn night: landed ...". No watering decision changes: `decide()` and its inputs are untouched.

**Class: C3** (the state file). Seeded snapshot: `tests_ha/fixtures/state_3_8_0_mid_grow.json`, loaded by `tests_ha/test_upgrade_in_place.py::test_a_3_8_0_state_file_loads_with_its_history_empty_and_nothing_moves`, which fails without this change.

Rollback: 3.8.0 reads zones through an allowlist, so it ignores the three new keys and writes its file without them. The history is lost on a rollback; nothing else is.

Soak checks (7 days on staging):
- every morning, one "night: landed ..." line per zone in the activity feed, with a rate and a P0 drop;
- after a restart in the night, the next morning's line is still there;
- the rollback rehearsal above.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

- [ ] **Step 3: Leave it for the owner**

Do not merge. Report the pull request's address and its CI result.
