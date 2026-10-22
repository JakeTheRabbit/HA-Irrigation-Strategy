"""Task 15: the controller runs timer programs and honours each zone's `irrigation_mode` select (steering / timer /
off), the timeline's skips, and publishes projection_app.

- R2: the select is read each pass. A readable mode is the zone's last-known mode, saved in state.json; anything else
  (unknown, unavailable, absent) uses the last-known mode, and steering only when no mode was ever seen.
- R3: a timer zone keeps the safety fires (controller.TIMER_KEEPS); an off zone gets nothing at all.
- A skip never touches the keep-set. Instants are compared in UTC.
- projection_app is written after the pass, each program on its own; it never stops watering."""
from datetime import datetime, timedelta, timezone

import pytest

import controller
from crop_steering_engine import ULID_RE, Reason
from test_pump_queue import _Wall, _build, _events, _pass, _valves

pytestmark = pytest.mark.usefixtures("settings_built_in")

KILL = "input_boolean.kill"
V1, V2 = "switch.v1", "switch.v2"
TIMERS = "sensor.crop_steering_timers_config"
PROJECTION = "sensor.crop_steering_projection_app"
IDLE = Reason("P2 waiting VWC 40.0 >= 39.0", kind="idle")
TOPUP = Reason("P2 top-up VWC 40.0 < 45.0", kind="p2_topup")
RESCUE = Reason("P3 emergency VWC 41.0 < 42.0", kind="p3_emergency", cap_exempt=True)
FLOOR = Reason("MIN-DAILY floor 0.0<1.0 of 2.0L", kind="min_daily")
PROGRAM = {"id": "P1", "name": "Mothers AM", "type": "recycle", "zones": [1], "duration_s": 20.0,
           "interval_min": 30.0, "window": {"kind": "all"}, "active": True}


def _mode(zone):
    return f"select.crop_steering_zone_{zone}_irrigation_mode"


@pytest.fixture
def rig(monkeypatch, tmp_path):
    return _build(monkeypatch, tmp_path)


@pytest.fixture
def engine(monkeypatch):
    """decide() for zone N (VWC 39 + N): what the dict says, idle when it says nothing."""
    reasons = {}

    def decide(snap, p):
        reason = reasons.get(round(snap.vwc) - 39, IDLE)
        return snap.phase, p.p2_threshold, reason.kind != "idle", 2.0, reason

    monkeypatch.setattr(controller, "decide", decide)
    return reasons


def _timers(fake, programs=(PROGRAM,), skips=()):
    fake.set_state(TIMERS, "1", {"room_id": "room:", "revision": 1, "programs": [dict(p) for p in programs],
                                 "skips": [dict(s) for s in skips]})


def _at(hour, minute=0):
    """The pinned wall clock at hour:minute today."""
    _Wall.current = _Wall(2026, 10, 22, hour, minute)
    return _Wall.current


def _fresh(fake, zones=2):
    for zone in range(1, zones + 1):  # the probes read now (a reading an hour old is stale)
        fake.set_state(f"sensor.crop_steering_vwc_zone_{zone}", str(39 + zone))
        fake.set_state(f"sensor.crop_steering_ec_zone_{zone}", "3")


def _pass_at(c, fake, hour, minute=0):
    _at(hour, minute)
    _fresh(fake)
    _pass(c)


def _started(c, zone=None):
    return [e for e in _events(c, "shot.started") if zone is None or e["zone"] == zone]


def _refused(c):
    return _events(c, "intent.refused")


# ------------------------------------------------------------------------------------------ R2: the zone's mode
def test_no_select_ever_seen_means_steering_exactly_as_before(rig, engine, monkeypatch, tmp_path):
    """No select and no timers_config: the same calls, writes and journal as with the new steps taken out."""
    engine[1] = TOPUP
    c, fake = rig
    _pass(c)
    assert _valves(fake) == [("turn_on", V1), ("turn_off", V1)]
    assert PROJECTION not in {e for e, _s, _a in fake.writes}
    assert "_irrigation_mode" not in (c._read_state_file().get("default") or {})

    monkeypatch.setattr(controller.Controller, "_apply_modes", lambda self, *a: None)
    monkeypatch.setattr(controller.Controller, "_publish_projection", lambda self, room, now: None)
    base, base_fake = _build(monkeypatch, tmp_path / "base")
    _pass(base)

    def kinds(ctl):
        return [(e["kind"], e["zone"], e["source"]["actor"]) for e in ctl.journal.pending()]

    def writes(f):  # each controller has its own instance id, and its brain its own start on the real clock
        own = ("controller_instance", "fallback_since")
        return [(e, s, {k: v for k, v in (a or {}).items() if k not in own}) for e, s, a in f.writes]

    assert base_fake.calls == fake.calls
    assert writes(base_fake) == writes(fake)
    assert kinds(base) == kinds(c)


def test_an_off_zone_stays_off_when_the_select_goes_unavailable(rig, engine):
    engine[1] = TOPUP
    c, fake = rig
    fake.set_state(_mode(1), "off")
    _pass(c)
    assert _valves(fake) == []
    for unreadable in ("unavailable", "unknown", "", "Steering"):  # anything outside the three modes
        fake.set_state(_mode(1), unreadable)
        _pass_at(c, fake, 12, 5)
        assert _valves(fake) == [], unreadable
    assert c._read_state_file()["default"]["_irrigation_mode"] == {"1": "off"}


def test_an_off_zone_stays_off_across_a_controller_restart_with_ha_down(monkeypatch, tmp_path, engine):
    engine[1] = TOPUP
    c, fake = _build(monkeypatch, tmp_path)
    fake.set_state(_mode(1), "off")
    _pass(c)
    assert _valves(fake) == []
    again, fake2 = _build(monkeypatch, tmp_path)  # the same state.json, a Home Assistant without the select
    fake2.set_state(_mode(1), "unavailable")
    _pass(again)
    assert _valves(fake2) == []
    assert again.rooms[0]._irrigation_mode == {"1": "off"}


def test_a_select_back_at_steering_waters_again(rig, engine):
    engine[1] = TOPUP
    c, fake = rig
    fake.set_state(_mode(1), "off")
    _pass(c)
    fake.set_state(_mode(1), "steering")
    _pass_at(c, fake, 12, 5)
    assert _valves(fake) == [("turn_on", V1), ("turn_off", V1)]


# ------------------------------------------------------------------------------------------------ timer programs
def test_timer_zone_fires_at_each_slot_and_stops_at_the_daily_max(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake)
    _pass_at(c, fake, 12, 0)  # the first pass only starts the clock: the 12:00 slot is not owed
    _pass_at(c, fake, 12, 10)
    assert _started(c) == []
    _pass_at(c, fake, 12, 30)
    _pass_at(c, fake, 13, 0)
    shots = _started(c)
    assert [e["zone"] for e in shots] == [1, 1]
    for event in shots:
        assert event["source"]["actor"] == "timer" and event["source"]["program_id"] == "P1"
        assert event["data"]["duration_s"] == 20 and event["data"]["kind"] == "timer"
    c.rooms[0].state[1]["daily_vol"] = 10_000.0  # the day's budget spent
    _pass_at(c, fake, 13, 30)
    assert len(_started(c)) == 2
    held = [e for e in _events(c, "intent.held") if e["data"].get("guard") == "daily_cap"]
    assert held and held[-1]["source"]["actor"] == "timer"
    assert held[-1]["data"]["reason"].startswith("BLOCK daily-cap")


def test_a_timer_shot_waits_its_turn_as_a_timer(rig, engine):
    assert controller.shot_priority(controller._timer_reason(PROGRAM, 20.0)) == "timer"
    assert "timer" in controller.PLAN_HOLD_EXEMPT


def test_the_engine_top_up_of_a_timer_zone_is_dropped(rig, engine):
    engine[1] = TOPUP
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake, programs=())
    _pass(c)
    assert _valves(fake) == []


def test_timer_zone_still_gets_a_p3_rescue(rig, engine):
    engine[1] = RESCUE
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake, programs=())
    _pass(c)
    assert _valves(fake) == [("turn_on", V1), ("turn_off", V1)]
    assert _started(c)[0]["source"]["actor"] == "engine"


def test_timer_zone_keeps_the_min_daily_floor(rig, engine):
    engine[1] = FLOOR
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _pass(c)
    assert _valves(fake) == [("turn_on", V1), ("turn_off", V1)]


@pytest.mark.parametrize("kind", sorted(controller.TIMER_KEEPS))
def test_every_kind_of_the_timer_keep_set_fires_in_timer_mode(rig, engine, kind):
    engine[1] = Reason(f"a {kind} shot", kind=kind)
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _pass(c)
    assert _valves(fake) == [("turn_on", V1), ("turn_off", V1)]


def test_the_timer_keep_set_is_the_rescues_the_floor_and_a_rescue_copy():
    assert controller.TIMER_KEEPS == {"p3_emergency", "watchdog", "min_daily", "blind_copy_rescue"}
    assert "blind_fallback" not in controller.TIMER_KEEPS  # a steering estimate, not a rescue


def test_a_blind_fallback_is_not_given_in_timer_mode(rig, engine):
    engine[1] = Reason("FALLBACK schedule (no live probe)", kind="blind_fallback")
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _pass(c)
    assert _valves(fake) == []


@pytest.mark.parametrize("reason", [TOPUP, RESCUE, FLOOR, Reason("a copy", kind="blind_copy_rescue")])
def test_off_zone_gets_nothing_not_even_rescue(rig, engine, reason):
    engine[1] = reason
    c, fake = rig
    fake.set_state(_mode(1), "off")
    _timers(fake, programs=[{**PROGRAM, "interval_min": 1.0}])
    _pass_at(c, fake, 12, 0)
    _pass_at(c, fake, 12, 5)
    assert _valves(fake) == [] and _started(c) == []


def test_a_restart_does_not_owe_missed_timer_shots(monkeypatch, tmp_path, engine):
    c, fake = _build(monkeypatch, tmp_path)
    fake.set_state(_mode(1), "timer")
    _timers(fake)
    _pass_at(c, fake, 12, 0)
    again, fake2 = _build(monkeypatch, tmp_path)  # down over the 12:30 slot
    fake2.set_state(_mode(1), "timer")
    _timers(fake2)
    _pass_at(again, fake2, 12, 45)
    assert _valves(fake2) == []
    _pass_at(again, fake2, 13, 0)
    assert _valves(fake2) == [("turn_on", V1), ("turn_off", V1)]


def test_kill_switch_holds_a_timer_shot(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake)
    _pass_at(c, fake, 12, 0)
    fake.set_state(KILL, "off")
    _pass_at(c, fake, 12, 30)
    assert _valves(fake) == []
    held, = [e for e in _events(c, "intent.held") if e["zone"] == 1]
    assert held["source"]["actor"] == "timer" and held["data"]["guard"] == "kill_switch"
    assert held["source"]["program_id"] == "P1"


# --------------------------------------------------------------------------------------------------------- skips
def _slot(hour, minute):
    return _Wall(2026, 10, 22, hour, minute).astimezone()


def test_a_skipped_timer_slot_does_not_fire(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    slot = _slot(12, 30)
    _timers(fake, skips=[{"zone": 1, "at": slot.isoformat(), "until": (slot + timedelta(minutes=15)).isoformat()}])
    _pass_at(c, fake, 12, 0)
    _pass_at(c, fake, 12, 30)
    assert _valves(fake) == []
    refused, = _refused(c)
    assert refused["zone"] == 1 and refused["outcome"] == "refused"
    assert refused["source"]["actor"] == "timer" and refused["source"]["program_id"] == "P1"
    assert refused["data"]["guard"] == "skipped" and refused["data"]["reason"].startswith("skipped by ")
    _pass_at(c, fake, 13, 0)  # the next slot runs
    assert _valves(fake) == [("turn_on", V1), ("turn_off", V1)]


def test_a_skip_drops_the_next_engine_top_up_but_never_a_rescue_or_floor(rig, engine):
    c, fake = rig
    since = _slot(12, 0)
    _timers(fake, programs=(), skips=[{"zone": 1, "at": since.isoformat(),
                                       "until": (since + timedelta(minutes=15)).isoformat()}])
    for reason in (RESCUE, FLOOR, Reason("a copy", kind="blind_copy_rescue")):
        engine[1] = reason
        _pass_at(c, fake, 12, 1)
    assert len(_started(c)) == 3 and _refused(c) == []
    engine[1] = TOPUP
    _pass_at(c, fake, 12, 2)
    assert len(_started(c)) == 3
    refused, = _refused(c)
    assert refused["source"]["actor"] == "engine" and refused["data"]["guard"] == "skipped"
    _pass_at(c, fake, 12, 3)  # the skip was used up: the next top-up runs
    assert len(_started(c)) == 4


def test_a_skip_outside_its_window_drops_nothing(rig, engine):
    engine[1] = TOPUP
    c, fake = rig
    since = _slot(12, 30)
    _timers(fake, programs=(), skips=[{"zone": 1, "at": since.isoformat(),
                                       "until": (since + timedelta(minutes=15)).isoformat()}])
    _pass_at(c, fake, 12, 0)
    assert len(_started(c)) == 1 and _refused(c) == []


@pytest.mark.parametrize("offset", [timedelta(hours=13), timedelta(0), timedelta(hours=-5)])
def test_skip_matching_is_by_instant_not_offset_text(rig, engine, offset):
    """The same instant written as +13:00, as Z and as -05:00 skips the same slot."""
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    slot = _slot(12, 30).astimezone(timezone(offset))
    text = slot.isoformat().replace("+00:00", "Z")
    _timers(fake, skips=[{"zone": 1, "at": text, "until": (slot + timedelta(minutes=15)).isoformat()}])
    _pass_at(c, fake, 12, 0)
    _pass_at(c, fake, 12, 30)
    assert _valves(fake) == [] and len(_refused(c)) == 1


# ---------------------------------------------------------------------------------------------------- projection
def _projection(fake):
    written = [a for e, _s, a in fake.writes if e == PROJECTION]
    return written[-1]["intents"] if written else None


def test_projection_app_lists_the_next_24_h_of_timer_shots(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake)
    _pass_at(c, fake, 12, 10)
    timer = [i for i in _projection(fake) if i["source"] == "timer"]
    assert len(timer) == 48  # every 30 min, 12:30 today to 12:00 tomorrow
    first = timer[0]
    assert first["zone"] == 1 and first["program_id"] == "P1" and first["duration_s"] == 20.0
    assert first["expected"] is False and ULID_RE.match(first["id"])
    assert controller._aware(first["at"]) == _slot(12, 30)
    _pass_at(c, fake, 12, 11)
    assert [i["id"] for i in _projection(fake) if i["source"] == "timer"][0] == first["id"]  # stable


def test_projection_app_carries_the_engine_estimate_of_a_steering_zone(rig, engine):
    c, fake = rig
    _timers(fake, programs=())
    fake.set_state("number.crop_steering_p2_time_between_shots", "30")  # a P2 top-up waits 30 min: a time to show
    _pass(c)
    estimates = [i for i in _projection(fake) if i["source"] == "engine"]
    assert estimates and all(i["expected"] is True and i["zone"] in (1, 2) for i in estimates)
    assert all("program_id" not in i for i in estimates)


def test_a_program_that_cannot_be_projected_stops_neither_the_others_nor_the_watering(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    fake.set_state(_mode(2), "timer")
    bad = {**PROGRAM, "id": "BAD", "zones": [1], "type": "nonsense"}
    good = {**PROGRAM, "id": "P2", "zones": [2]}
    _timers(fake, programs=(bad, good))
    _pass_at(c, fake, 12, 0)
    _pass_at(c, fake, 12, 30)
    assert _valves(fake) == [("turn_on", V2), ("turn_off", V2)]
    assert {i["program_id"] for i in _projection(fake) if i["source"] == "timer"} == {"P2"}


def test_a_projection_that_fails_never_stops_watering(rig, engine, monkeypatch):
    engine[1] = TOPUP
    c, fake = rig
    _timers(fake, programs=())

    def boom(*_a, **_k):
        raise RuntimeError("projection")

    monkeypatch.setattr(controller, "derived_id", boom)
    _pass(c)
    assert _valves(fake) == [("turn_on", V1), ("turn_off", V1)]


def test_projection_is_written_after_the_last_pump_closes(rig, engine, monkeypatch):
    engine[1] = TOPUP
    c, fake = rig
    _timers(fake, programs=())
    order = []
    real_call, real_set = controller.ha_call, controller.ha_set
    monkeypatch.setattr(controller, "ha_call", lambda d, s, **k: (
        order.append((d, s, k.get("entity_id"))), real_call(d, s, **k))[1])
    monkeypatch.setattr(controller, "ha_set", lambda e, s, a=None, timeout=None: (
        order.append(("set", e)), real_set(e, s, a, timeout))[1])
    _pass(c)
    assert order.index(("set", PROJECTION)) > order.index(("switch", "turn_off", V1))


# ------------------------------------------------------------------------------- review round 1 (Task 15 rulings)
@pytest.mark.parametrize("kept", [RESCUE, FLOOR])
def test_a_rescue_or_floor_wins_over_a_due_timer_slot_and_the_slot_follows(rig, engine, kept):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake)
    _pass_at(c, fake, 12, 0)
    engine[1] = kept
    _pass_at(c, fake, 12, 30)  # the 12:30 slot is due and so is the safety shot: the safety shot goes first
    first, = _started(c)
    assert first["source"]["actor"] == "engine" and first["data"]["kind"] == kept.kind
    engine[1] = IDLE
    _pass_at(c, fake, 12, 31)  # the slot was kept owed, not dropped
    second = _started(c)[1]
    assert second["source"]["actor"] == "timer" and second["source"]["program_id"] == "P1"
    _pass_at(c, fake, 12, 32)  # and it is owed once only
    assert len(_started(c)) == 2


def test_an_owed_slot_is_replaced_by_a_later_one_never_given_twice(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake)
    _pass_at(c, fake, 12, 0)
    engine[1] = RESCUE
    _pass_at(c, fake, 12, 30)
    _pass_at(c, fake, 13, 0)  # still a rescue: the 13:00 slot replaces the owed 12:30 one
    engine[1] = IDLE
    _pass_at(c, fake, 13, 1)
    _pass_at(c, fake, 13, 2)
    assert [e["source"]["actor"] for e in _started(c)] == ["engine", "engine", "timer"]


def test_an_owed_slot_is_dropped_when_the_zone_leaves_timer_mode(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake)
    _pass_at(c, fake, 12, 0)
    engine[1] = RESCUE
    _pass_at(c, fake, 12, 30)
    engine[1] = IDLE
    fake.set_state(_mode(1), "steering")
    _pass_at(c, fake, 12, 31)
    fake.set_state(_mode(1), "timer")
    _pass_at(c, fake, 12, 32)
    assert [e["source"]["actor"] for e in _started(c)] == ["engine"]


def test_a_skip_names_who_asked_for_it(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    slot = _slot(12, 30)
    _timers(fake, skips=[{"zone": 1, "at": slot.isoformat(), "until": (slot + timedelta(minutes=15)).isoformat(),
                          "by": {"actor": "manual", "user_id": "ben"}}])
    _pass_at(c, fake, 12, 0)
    _pass_at(c, fake, 12, 30)
    refused, = _refused(c)
    assert refused["data"]["reason"] == "skipped by ben"


def test_a_timer_shot_is_not_a_learner_input(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake)
    st = c.rooms[0].state[1]
    _pass_at(c, fake, 12, 0)
    st["last_vwc"] = 40.0
    st["learn"]["pending"] = {"t": _Wall(2026, 10, 22, 12, 29).timestamp(), "pre": 38.0, "pct": 2.0, "ramp": True}  # an engine ramp shot settling
    ramp = len(st["learn"]["ramp"])
    _pass_at(c, fake, 12, 30)
    assert _started(c)[0]["source"]["actor"] == "timer"
    # the engine shot is settled on the reading before the timer water, as shot() settles it; the timer shot
    # itself is never recorded
    assert st["learn"]["pending"] is None
    assert len(st["learn"]["ramp"]) == ramp + 1 and st["learn"]["ramp"][-1]["rise"] == 2.0
    engine[1] = RESCUE
    st["last_vwc"] = 40.0
    _pass_at(c, fake, 12, 35)
    assert st["learn"]["pending"] is not None  # an engine shot still is


def test_a_test_shot_on_an_off_zone_runs_as_the_operators(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "off")
    button = "button.crop_steering_zone_1_test_shot"
    fake.set_state(button, "2026-10-22T11:00:00+00:00")  # the first state seen is a starting point, not a press
    _pass_at(c, fake, 12, 0)
    fake.set_state(button, _Wall.current.astimezone().isoformat())
    _pass_at(c, fake, 12, 0)
    assert _valves(fake) == [("turn_on", V1), ("turn_off", V1)]
    assert _started(c)[0]["source"]["actor"] == "manual"


def test_the_projection_follows_the_nz_spring_forward(rig, engine, monkeypatch):
    """A daily 08:00 slot the day the clocks go forward (27 Sep 2026, 02:00 NZST -> 03:00 NZDT) is 08:00 NZDT:
    19:00 UTC, not the 20:00 UTC a fixed +12:00 gives."""
    monkeypatch.setenv("TZ", "Pacific/Auckland")
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake, programs=[{**PROGRAM, "interval_min": 1440.0, "sync_time": "08:00"}])
    _Wall.current = _Wall(2026, 9, 26, 12, 0)  # NZST, +12:00
    _fresh(fake)
    _pass(c)
    timer = [i for i in _projection(fake) if i["source"] == "timer"]
    assert [controller._aware(i["at"]) for i in timer] == [
        controller.datetime(2026, 9, 26, 19, 0, tzinfo=timezone.utc)]
    assert timer[0]["at"].endswith("+00:00")  # each slot in UTC


# ------------------------------------------------------------------------------- review round 2 (Task 15 fixes)
def test_a_test_shot_in_the_pass_of_a_due_slot_keeps_the_slot_owed(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake)
    button = "button.crop_steering_zone_1_test_shot"
    fake.set_state(button, "2026-10-22T11:00:00+00:00")  # the first state seen is a starting point
    _pass_at(c, fake, 12, 0)
    _at(12, 30)
    fake.set_state(button, _Wall.current.astimezone().isoformat())
    _pass_at(c, fake, 12, 30)  # the slot and the press in one pass: the press takes the turn
    _pass_at(c, fake, 12, 31)
    assert [e["source"]["actor"] for e in _started(c)] == ["manual", "timer"]


def test_an_owed_slot_expires_15_min_after_its_time(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake)
    _pass_at(c, fake, 12, 0)
    engine[1] = RESCUE
    _pass_at(c, fake, 12, 30)
    _pass_at(c, fake, 12, 40)  # still owed
    assert _events(c, "intent.refused") == []
    engine[1] = IDLE
    _pass_at(c, fake, 12, 46)  # 16 min after its time: never given late
    assert [e["source"]["actor"] for e in _started(c)] == ["engine", "engine"]
    expired, = _refused(c)
    assert expired["data"]["guard"] == "expired" and expired["source"]["actor"] == "timer"
    assert expired["source"]["program_id"] == "P1" and expired["zone"] == 1


def test_an_owed_slot_expires_when_its_window_ends(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake, programs=[{**PROGRAM, "window": {"kind": "custom", "from": "08:00", "to": "12:40"}}])
    _pass_at(c, fake, 12, 0)
    engine[1] = RESCUE
    _pass_at(c, fake, 12, 30)  # the window's last slot, owed behind the rescue
    engine[1] = IDLE
    _pass_at(c, fake, 12, 41)  # inside 15 min, but its window ended at 12:40
    assert [e["source"]["actor"] for e in _started(c)] == ["engine"]
    expired, = _refused(c)
    assert expired["data"]["guard"] == "expired"


def test_an_owed_slots_15_min_are_real_minutes_across_a_dst_change(rig):
    """Task 15 carry: the grace is counted in UTC. NZ daylight time ends 2027-04-04 03:00 -> 02:00: a slot at the first
    02:50 is 15 real minutes old at the second 02:05, though the wall clock went back 45 min. A window's end stays a
    wall-clock time: on 2026-09-27 (02:00 -> 03:00) a window to 03:00 ends 10 real minutes after a 01:50 slot."""
    from zoneinfo import ZoneInfo

    from crop_steering_engine.timers import PlannedIntent

    c, _fake = rig
    room, nz = c.rooms[0], ZoneInfo("Pacific/Auckland")
    slot = PlannedIntent("P1", 1, datetime(2027, 4, 4, 2, 50, tzinfo=nz), 20.0)  # fold 0: NZDT, 13:50 UTC
    expiry = c._slot_expiry(room, slot, PROGRAM)
    assert expiry == datetime(2027, 4, 3, 14, 5, tzinfo=timezone.utc)
    assert datetime(2027, 4, 4, 2, 6, fold=1, tzinfo=nz) >= expiry  # 16 real minutes: expired
    assert not datetime(2027, 4, 4, 2, 4, fold=1, tzinfo=nz) >= expiry  # 14 real minutes: still owed
    window = {**PROGRAM, "window": {"kind": "custom", "from": "01:00", "to": "03:00"}}
    spring = PlannedIntent("P1", 1, datetime(2026, 9, 27, 1, 50, tzinfo=nz), 20.0)  # NZST, 13:50 UTC
    assert c._slot_expiry(room, spring, window) == datetime(2026, 9, 26, 14, 0, tzinfo=timezone.utc)
    assert c._slot_expiry(room, spring, PROGRAM) == datetime(2026, 9, 26, 14, 5, tzinfo=timezone.utc)


def test_a_queued_timer_shot_names_its_program(rig, engine):
    from test_pump_queue import _supply

    c, fake = rig
    engine[1] = TOPUP
    fake.set_state(_mode(2), "timer")
    _timers(fake, programs=[{**PROGRAM, "id": "P2", "zones": [2]}])
    _supply(fake)
    _pass_at(c, fake, 12, 0)
    _pass_at(c, fake, 12, 30)
    queued = [e for e in _events(c, "intent.queued") if e["zone"] == 2]
    assert queued and queued[-1]["source"]["program_id"] == "P2" and queued[-1]["data"]["priority"] == "timer"


def test_two_programs_on_one_zone_at_one_instant_get_two_ids(rig, engine):
    c, fake = rig
    fake.set_state(_mode(1), "timer")
    _timers(fake, programs=[PROGRAM, {**PROGRAM, "id": "P9"}])
    _pass_at(c, fake, 12, 10)
    first = [i for i in _projection(fake) if i["source"] == "timer"][:2]
    assert first[0]["at"] == first[1]["at"] and first[0]["id"] != first[1]["id"]
