"""The shot checks as one ordered chain (guards.py): PASS is _blocked, PREOPEN is _execute_shot's checks before anything
opens, SIZED is _act_zone's checks once a shot is sized. The refactor that made them a chain changed no behaviour.

test_matches_what_the_controller_did_before_the_chain replays a matrix of holds (each guard alone, the stacked
orders and a few combinations) through _blocked, _execute_shot, _act_zone and loop_once, and compares everything
they do with what the controller did before the chain (guard_chain_golden.json, recorded at a1285c81): the reason,
every Home Assistant read, call and state write in order, the log, the journal and the state left behind. The only
difference allowed is the one the chain adds: intent.held from the pre-open and sized stages names its guard and
its code. Re-record only for a deliberate change: GUARD_CHAIN_RECORD=1 PY addons/f2_control/tests/test_guard_chain.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta

import pytest

import controller
import fake_ha
import gate_report
import guards
import tank_level
from crop_steering_engine import Reason
from test_blind_grace import _Clock as _Wall  # the controller's wall clock, pinned
from test_held_reasons_pinned import (
    FEED_EC,
    FEED_PH,
    FLUSH,
    KILL,
    PREOPEN,
    STAGES,
    TANK_DIST,
    WASTE,
    ZONE_SWITCH,
    _fault,
    _plumbing,
    _room,
    _tank_min,
    _undrivable,
    _waste_open,
)

pytestmark = pytest.mark.usefixtures("settings_built_in")

GOLDEN = os.path.join(os.path.dirname(__file__), "guard_chain_golden.json")
RECORD = os.environ.get("GUARD_CHAIN_RECORD") == "1"


# ------------------------------------------------------------------------------------------- the chain's shape
def test_pass_stage_order_matches_a_live_gate_report():
    c, _fake, room = _room()  # a room with a valve: report() reads every gate
    assert [g.key for g in guards.PASS] == [g["key"] for g in gate_report.report(c, room, 1, None)]


def test_pass_stage_guard_ids():
    assert [(g.key, g.guard) for g in guards.PASS] == [
        ("setup", "setup_behind"), ("archived", "kill_switch"), ("room_on", "kill_switch"),
        ("dosing", "dosing_hold"), ("plan", "plan_hold"), ("hardware_fault", "hardware_latch"),
        ("max_run", "hardware_latch"), ("valve_mapped", "plumbing"), ("plumbing", "plumbing"),
        ("switchable", "plumbing"), ("kill_switch", "kill_switch"), ("retired", "kill_switch"),
        ("zone_on", "zone_paused"), ("manual_override", "manual_override"), ("external_holds", "external_hold"),
        ("waste", "waste_closed"), ("settings", "settings_loaded"), ("tank", "tank_min"),
        ("feed_ec", "source_water"), ("feed_ph", "source_water"), ("online", "plumbing"),
    ]


def test_preopen_order_is_todays():
    assert [g.guard for g in guards.PREOPEN] == [
        "hardware_latch", "auth", "inflight", "plumbing", "plumbing", "plan_hold", "switch_backoff", "tank_min",
        "waste_closed", "dosing_hold",
    ]


def test_sized_order_is_todays():
    assert [g.guard for g in guards.SIZED] == ["shot_sizing", "max_shot", "daily_cap"]


def test_every_guard_names_its_stage():
    for stage, name in ((guards.PASS, "pass"), (guards.PREOPEN, "preopen"), (guards.SIZED, "sized")):
        assert {g.stage for g in stage} == {name}
        assert len({g.key for g in stage}) == len(stage)


def test_first_is_the_first_hold_or_none():
    seen = []

    def check(answer):
        return lambda owner, room, zone, ctx: (seen.append(answer), answer)[1]

    chain = tuple(guards.Guard(k, k, "pass", None, check(a)) for k, a in (("a", None), ("b", "held"), ("c", "x")))
    assert guards.first(None, chain, None, 1, {}) == (chain[1], "held", None)
    assert seen == [None, "held"]  # the chain stops at its first hold
    assert guards.first(None, chain[:1], None, 1, {}) is None


def test_a_check_may_name_its_own_code():
    chain = (guards.Guard("a", "a", "pass", "CS-901", lambda *a: ("held", "CS-902")),)
    assert guards.first(None, chain, None, 1, {}) == (chain[0], "held", "CS-902")
    chain = (guards.Guard("a", "a", "pass", "CS-901", lambda *a: "held"),)
    assert guards.first(None, chain, None, 1, {}) == (chain[0], "held", "CS-901")


def test_a_held_intent_names_its_guard_and_code():
    """A pre-open hold: the tank minimum, as the shot is about to open."""
    c, fake, room = _room()
    _x_tank_short(c, fake, room)
    c._execute_shot(room, 1, 10, 5, flow_lps=10.0, reason_text="P2 top-up")
    held, = [e for e in c.journal.pending() if e["kind"] == "intent.held"]
    assert held["data"]["guard"] == "tank_min" and held["code"] == "CS-901"
    assert held["data"]["reason"].startswith("this 100.0 L shot would take the tank")


def _pass_holds(setup, passes=1):
    """The act loop's fire+block holds (guards.PASS) of a zone that is to fire, over `passes` passes."""
    c, fake, room = _room()
    run = _looping(setup, passes=passes)
    with pytest.MonkeyPatch.context() as mp:
        run(c, fake, room, mp)
    return [e for e in c.journal.pending() if e["kind"] == "intent.held"]


def test_a_pass_hold_names_its_guard_and_code():
    held, = _pass_holds(lambda c, f, r, mp, i: _tank_min(c, f, r, mp))
    assert (held["data"]["guard"], held["code"]) == ("tank_min", "CS-901")
    assert held["data"]["reason"] == "tank at its minimum (reads 8.0 %)"


def test_an_unreadable_tank_level_journals_its_own_code():
    def unread(c, f, r, mp, i):
        _tank_min(c, f, r, mp)
        f.set_state(TANK_DIST, "unavailable")
    held, = _pass_holds(unread)
    assert (held["data"]["guard"], held["code"]) == ("tank_min", "CS-902")


def test_two_holds_under_one_guard_are_two_holds():
    """zone_paused: the zone switch off, then unreadable. Each is journaled; the same one standing is not again."""
    def step(c, f, r, mp, i):
        f.set_state(ZONE_SWITCH, ["off", "off", "unavailable", "unavailable"][i])
    held = _pass_holds(step, passes=4)
    assert [(e["data"]["guard"], e["data"]["reason"]) for e in held] == [
        ("zone_paused", "zone disabled"), ("zone_paused", f"{ZONE_SWITCH} unreadable (reads neither on nor off)")]


def test_a_sized_hold_names_its_guard_and_code():
    c, _fake, room, p = _cap_rig()
    reason = Reason("P2 top-up", kind="p2_topup")
    assert c._act_zone(room, 1, p, None, (True, 10.0, reason), None, True, datetime.now())[0] is False
    held, = [e for e in c.journal.pending() if e["kind"] == "intent.held"]
    assert held["data"]["guard"] == "daily_cap" and held["code"] == "CS-205"


# --------------------------------------------------------------------------------------------- the rigs
def _x_tank_short(c, fake, room):
    room.tank = tank_level.mapping({"tank_distance_sensor": TANK_DIST,
                                    "tank_level": {"full_mm": 100, "empty_mm": 1100}})
    room.tank_reading = (9.0, None)
    room.tank_drawdown = tank_level.fresh()
    room.tank_drawdown["litres_per_pct"] = 40.0


def _cap_rig():
    c, fake, room = _room()
    room.state[1]["daily_vol"] = 1000.0
    p = type("P", (), {"max_daily_volume": 5.0, "watchdog_hours": 0, "p2_threshold": 0})()
    c._zone_flow_lps = lambda room, zone: 0.1
    c._substrate_l = lambda room, zone: 3.0
    c._room_duration_cap = lambda room: 600
    return c, fake, room, p


class _Clock:
    def __init__(self):
        self.seconds = 1000.0

    def sleep(self, seconds):
        self.seconds += seconds

    def monotonic(self):
        return self.seconds


# ------------------------------------------------------------------------------------- the scenario matrix
SCENARIOS = {}


def scenario(name):
    def add(fn):
        SCENARIOS[name] = fn
        return fn
    return add


def _blocked(reason=None):
    return lambda c, fake, room, mp: c._blocked(room, 1, reason)


def _kind(kind):
    return Reason("shot", kind=kind)


# ---- PASS: each hold of the pinned table alone, then all of them stacked and peeled in order
for _name, _apply, _undo, _expect in STAGES:
    def _one(c, fake, room, mp, apply=_apply, undo=_undo):
        apply(c, fake, room, mp)
        first = c._blocked(room, 1)
        undo(c, fake, room)
        return [first, c._blocked(room, 1)]
    SCENARIOS[f"pass/{_name}"] = _one


@scenario("pass/stacked")
def _(c, fake, room, mp):
    stages = [s for s in STAGES if s[0] != "zone_off"]
    for _n, apply, _u, _e in stages:
        apply(c, fake, room, mp)
    seen = []
    for _n, _a, undo, _e in stages:
        seen.append(c._blocked(room, 1))
        undo(c, fake, room)
    return seen + [c._blocked(room, 1)]


@scenario("pass/clear")
def _(c, fake, room, mp):
    return c._blocked(room, 1)


@scenario("pass/kill_zone_tank")
def _(c, fake, room, mp):
    _tank_min(c, fake, room, mp)
    fake.set_state(ZONE_SWITCH, "off")
    fake.set_state(KILL, "off")
    out = [c._blocked(room, 1)]
    fake.set_state(KILL, "on")
    out.append(c._blocked(room, 1))
    fake.set_state(ZONE_SWITCH, "on")
    out.append(c._blocked(room, 1))
    room.tank_reading = None
    fake.set_state(TANK_DIST, "50.0", {"unit_of_measurement": "cm"})
    out.append(c._blocked(room, 1))  # refilled: the tank alerts come down
    return out


# "timer" (Task 15) came after the recording: test_timer_mode.py holds it.
for _k in sorted(controller.PLAN_HOLD_EXEMPT - {"timer"}) + ["p2_topup"]:
    def _plan(c, fake, room, mp, kind=_k):
        room.strategy_snapshot = {"required": True, "error": "plan unreadable"}
        return c._blocked(room, 1, _kind(kind))
    SCENARIOS[f"pass/plan_hold_{_k}"] = _plan


@scenario("pass/plan_zone_paused")
def _(c, fake, room, mp):
    room.strategy_snapshot = {"required": True, "managed": {1}, "zones": {1: {"status": "paused"}}}
    return c._blocked(room, 1)


@scenario("pass/hold_missing")
def _(c, fake, room, mp):
    fake.states.pop(FLUSH)
    return c._blocked(room, 1)


@scenario("pass/hold_unreadable")
def _(c, fake, room, mp):
    fake.set_state(FLUSH, "unavailable")
    return c._blocked(room, 1)


@scenario("pass/tank_unknown")
def _(c, fake, room, mp):
    room.tank = tank_level.mapping({"tank_distance_sensor": TANK_DIST,
                                    "tank_level": {"full_mm": 100, "empty_mm": 1100}})
    fake.set_state(TANK_DIST, "unavailable")
    return c._blocked(room, 1)


def _feed(fake, room, half, reading, lo, hi):
    probe = FEED_EC if half == "ec" else FEED_PH
    setattr(room, f"feed_{half}_sensor", probe)
    fake.set_state(probe, reading, {"unit_of_measurement": "pH" if half == "ph" else "mS/cm"})
    fake.set_state(f"number.crop_steering_irrigation_{half}_min", lo)
    fake.set_state(f"number.crop_steering_irrigation_{half}_max", hi)


for _half in ("ec", "ph"):
    for _kind_name in ("p3_emergency", "p2_topup"):
        for _bypass in ("on", "off"):
            def _dead(c, fake, room, mp, half=_half, kind=_kind_name, bypass=_bypass):
                _feed(fake, room, half, "unavailable", "0.5" if half == "ec" else "5.5", "2" if half == "ec" else "6.5")
                fake.set_state("switch.crop_steering_rescue_past_dead_feed_probe", bypass)
                return [c._blocked(room, 1, _kind(kind)), getattr(room, "_feed_last_good_time", None) is None]
            SCENARIOS[f"pass/feed_{_half}_dead_{_kind_name}_{_bypass}"] = _dead
    for _band in ("unavailable", "absent", "nonsense"):
        def _band_case(c, fake, room, mp, half=_half, band=_band):
            _feed(fake, room, half, "9.9", "1", "3")
            entity = f"number.crop_steering_irrigation_{half}_max"
            if band == "absent":
                del fake.states[entity]
            else:
                fake.set_state(entity, band)
            return c._blocked(room, 1)
        SCENARIOS[f"pass/feed_{_half}_band_{_band}"] = _band_case
    for _reading in ("1.0", "6.0", "9.9", "0.1"):
        def _in_out(c, fake, room, mp, half=_half, reading=_reading):
            _feed(fake, room, half, reading, "0.5" if half == "ec" else "5.5", "2" if half == "ec" else "6.5")
            return c._blocked(room, 1)
        SCENARIOS[f"pass/feed_{_half}_reads_{_reading}"] = _in_out


@scenario("pass/ec_in_grace_then_ph_out")
def _(c, fake, room, mp):
    _feed(fake, room, "ec", "unavailable", "0.5", "2")
    room._feed_last_good_time = controller.datetime.now()
    _feed(fake, room, "ph", "7.0", "5.5", "6.5")
    return c._blocked(room, 1)


@scenario("pass/ec_and_ph_unset_bands")
def _(c, fake, room, mp):
    _feed(fake, room, "ec", "9.0", "0", "0")
    _feed(fake, room, "ph", "9.0", "0", "0")
    return c._blocked(room, 1)


@scenario("pass/waste_variants")
def _(c, fake, room, mp):
    room.waste = WASTE
    rule = "select.crop_steering_waste_valve_rule"
    out = []
    for policy, valve in ((controller.WASTE_CHECK, "unavailable"), (controller.WASTE_CHECK, "off"),
                          ("unavailable", "off"), (controller.WASTE_CLOSE, "on"), ("Off", "on")):
        fake.set_state(rule, policy)
        fake.set_state(WASTE, valve)
        out.append(c._blocked(room, 1))
    room.waste = "light.waste"
    fake.set_state("light.waste", "on")
    fake.set_state(rule, controller.WASTE_CLOSE)
    out.append(c._blocked(room, 1))
    return out + [getattr(room, "_waste_rule_known", None)]


@scenario("pass/waste_rule_absent")
def _(c, fake, room, mp):
    room.waste = WASTE
    fake.set_state(WASTE, "on")
    return c._blocked(room, 1)


@scenario("pass/settings_unread")
def _(c, fake, room, mp):
    mp.setattr(controller, "WATER_SIZING", ("max_daily_volume",))
    return c._blocked(room, 1)


@scenario("pass/max_run_released_by_off")
def _(c, fake, room, mp):
    room.state[1]["max_run_latch"] = {"since": "2026-10-22T10:00:00", "resets": 0}
    room.state[1]["capped_in_a_row"] = 4
    fake.set_state("switch.crop_steering_max_run_latch", "off", {"resets": 0})
    return [c._blocked(room, 1), room.state[1]["max_run_latch"], room.state[1]["capped_in_a_row"]]


@scenario("pass/max_run_released_by_reset")
def _(c, fake, room, mp):
    room.state[1]["max_run_latch"] = {"since": "2026-10-22T10:00:00", "resets": 0}
    fake.set_state("switch.crop_steering_max_run_latch", "on", {"resets": 1})
    return [c._blocked(room, 1), room.state[1]["max_run_latch"]]


@scenario("pass/max_run_unreadable_holds")
def _(c, fake, room, mp):
    room.state[1]["max_run_latch"] = {"since": "2026-10-22T10:00:00", "resets": 0}
    return c._blocked(room, 1)


@scenario("pass/plumbing_alert_and_undrivable_alert")
def _(c, fake, room, mp):
    _plumbing(c, fake, room, mp)
    first = c._blocked(room, 1)
    room.hw.pop("plumbing")
    room.hw["valves"][1] = "light.v1"
    return [first, c._blocked(room, 1)]


@scenario("pass/no_valve_stops_reading")
def _(c, fake, room, mp):
    room.hw["valves"] = {}
    fake.set_state(KILL, "off")
    return c._blocked(room, 1)


@scenario("pass/valve_offline")
def _(c, fake, room, mp):
    fake.set_state("switch.v1", "unavailable")
    fake.set_state("switch.p", "unknown")
    return c._blocked(room, 1)


# ---- PREOPEN: each pinned pre-open hold alone, stacked, and the switch-on backoff (#208) the pinned table lacks
def _shot(c, room, **kw):
    kw.setdefault("flow_lps", 10.0)
    return c._execute_shot(room, 1, 10, 5, reason_text="P2 top-up", **kw)


def _x_backoff(c, fake, room):
    room.state[1]["on_failures"] = {"count": controller.SWITCH_ON_BACKOFF_AFTER, "last": controller.datetime.now().isoformat()}


PREOPEN_ALL = PREOPEN[:6] + [("backoff", _x_backoff, lambda c, f, r: r.state[1].update(on_failures=None), None)] \
    + PREOPEN[6:]

for _name, _apply, _undo, _line in PREOPEN_ALL:
    def _pre(c, fake, room, mp, apply=_apply, undo=_undo):
        apply(c, fake, room)
        first = _shot(c, room)
        undo(c, fake, room)
        return [first, c._busy]
    SCENARIOS[f"preopen/{_name}"] = _pre


@scenario("preopen/stacked")
def _(c, fake, room, mp):
    for _n, apply, _u, _l in PREOPEN_ALL:
        apply(c, fake, room)
    for _n, _a, undo, _l in PREOPEN_ALL:
        _shot(c, room)
        undo(c, fake, room)
    return _shot(c, room)  # all clear: the shot runs


@scenario("preopen/clear_shot")
def _(c, fake, room, mp):
    return _shot(c, room)


@scenario("preopen/backoff_spares_a_test_shot")
def _(c, fake, room, mp):
    _x_backoff(c, fake, room)
    return _shot(c, room, steering=False)


@scenario("preopen/backoff_past_its_retry")
def _(c, fake, room, mp):
    room.state[1]["on_failures"] = {"count": 5, "last": (controller.datetime.now() - timedelta(hours=2)).isoformat()}
    return _shot(c, room)


@scenario("preopen/plan_exempt")
def _(c, fake, room, mp):
    room._strategy_batch_invalid = True
    c.dosing = type("D", (), {"holds": staticmethod(lambda r: "making a batch")})()
    return _shot(c, room, plan_exempt=True)


@scenario("preopen/litres_from_the_substrate")
def _(c, fake, room, mp):
    _x_tank_short(c, fake, room)
    return _shot(c, room, flow_lps=None)


@scenario("preopen/tank_short_passes")
def _(c, fake, room, mp):
    _x_tank_short(c, fake, room)
    room.tank_reading = (60.0, None)
    return _shot(c, room)


@scenario("preopen/waste_closed_for_the_shot")
def _(c, fake, room, mp):
    room.waste = WASTE
    fake.set_state(WASTE, "on")
    fake.set_state("select.crop_steering_waste_valve_rule", controller.WASTE_CLOSE)
    return _shot(c, room)


@scenario("preopen/plumbing_then_undrivable")
def _(c, fake, room, mp):
    _plumbing(c, fake, room, mp)
    _shot(c, room)
    room.hw.pop("plumbing")
    _undrivable(c, fake, room, mp)
    return _shot(c, room)


@scenario("preopen/fault_is_silent")
def _(c, fake, room, mp):
    _fault(c, fake, room, mp)
    controller._GATE.state = "refused"
    return _shot(c, room)


# ---- SIZED: _act_zone once the shot is to fire
def _act(c, room, p, size=10.0, reason=None, block=None, fire=True, snap=None):
    reason = reason if reason is not None else Reason("P2 top-up", kind="p2_topup")
    return c._act_zone(room, 1, p, snap, (fire, size, reason), block, True, controller.datetime.now())


def _sized(setup):
    def run(c, fake, room, mp):
        c2, p = _sized_rig(c, mp)
        return setup(c2, fake, room, p, mp)
    return run


def _sized_rig(c, mp):
    room = c.rooms[0]
    p = type("P", (), {"max_daily_volume": 50.0, "watchdog_hours": 0, "p2_threshold": 0})()
    mp.setattr(c, "_zone_flow_lps", lambda room, zone: 0.1)
    mp.setattr(c, "_substrate_l", lambda room, zone: 3.0)
    mp.setattr(c, "_room_duration_cap", lambda room: 600)
    room.state[1]["daily_vol"] = 0.0
    return c, p


SCENARIOS["sized/fires"] = _sized(lambda c, f, r, p, mp: _act(c, r, p))
SCENARIOS["sized/unsized"] = _sized(
    lambda c, f, r, p, mp: (mp.setattr(c, "_zone_flow_lps", lambda room, zone: 0.0), _act(c, r, p))[1])
SCENARIOS["sized/substrate_nan"] = _sized(
    lambda c, f, r, p, mp: (mp.setattr(c, "_substrate_l", lambda room, zone: float("nan")), _act(c, r, p))[1])
SCENARIOS["sized/cap_unreadable"] = _sized(
    lambda c, f, r, p, mp: (mp.setattr(c, "_room_duration_cap", lambda room: None), _act(c, r, p))[1])
SCENARIOS["sized/cut_to_the_cap"] = _sized(
    lambda c, f, r, p, mp: (mp.setattr(c, "_room_duration_cap", lambda room: 20), _act(c, r, p, size=50.0))[1])
SCENARIOS["sized/daily_cap_holds"] = _sized(
    lambda c, f, r, p, mp: (r.state[1].update(daily_vol=49.9), _act(c, r, p))[1])
SCENARIOS["sized/daily_cap_holds_blind_and_with_a_snapshot"] = _sized(
    lambda c, f, r, p, mp: (r.state[1].update(daily_vol=60.0), _act(c, r, p),
                            _act(c, r, p, snap=type("S", (), {"vwc": 40.0, "minutes_since_shot": 10.0})()))[1:])
SCENARIOS["sized/daily_cap_clips"] = _sized(
    lambda c, f, r, p, mp: (r.state[1].update(daily_vol=48.0), _act(c, r, p))[1])
SCENARIOS["sized/cap_exempt"] = _sized(
    lambda c, f, r, p, mp: (r.state[1].update(daily_vol=60.0),
                            _act(c, r, p, reason=Reason("P3 rescue", kind="p3_emergency", cap_exempt=True)))[1])
SCENARIOS["sized/no_params"] = _sized(
    lambda c, f, r, p, mp: (r.state[1].update(daily_vol=60.0), _act(c, r, None))[1])
def _test_shot_reason():
    reason = Reason("TEST shot 12 s (asked for)", "test_shot")
    reason.seconds = 12
    return reason


SCENARIOS["sized/test_shot"] = _sized(lambda c, f, r, p, mp: _act(c, r, p, reason=_test_shot_reason()))
SCENARIOS["sized/fire_and_block"] = _sized(lambda c, f, r, p, mp: _act(c, r, p, block="zone disabled"))
SCENARIOS["sized/not_fire_daily_cap_text"] = _sized(
    lambda c, f, r, p, mp: _act(c, r, p, fire=False, reason="BLOCK daily-cap 60/50L (blind irrigation budget)"))
SCENARIOS["sized/not_fire_ec_block"] = _sized(
    lambda c, f, r, p, mp: _act(c, r, p, fire=False, reason="BLOCK EC 9.0 > 6.0"))
SCENARIOS["sized/daily_cap_then_unsized_then_fires"] = _sized(
    lambda c, f, r, p, mp: [
        (r.state[1].update(daily_vol=49.9), _act(c, r, p))[1],
        (r.state[1].update(daily_vol=0.0), mp.setattr(c, "_zone_flow_lps", lambda room, zone: 0.0),
         _act(c, r, p))[2],
        (mp.setattr(c, "_zone_flow_lps", lambda room, zone: 0.1), _act(c, r, p))[1],
    ])


# ---- loop_once: the act loop end to end, over passes (the journal's once-per-hold counting included)
NOW = datetime(2026, 10, 22, 12, 0)


def _looping(setup, passes=3, step_s=60):
    def run(c, fake, room, mp):
        reason = Reason("P2 top-up VWC 40.0 < 45.0", kind="p2_topup")
        mp.setattr(controller, "decide", lambda snap, p: (snap.phase, p.p2_threshold, True, 2.0, reason))
        mp.setattr(c.journal, "flush", lambda *a, **k: 0)
        fake.set_state("sensor.crop_steering_vwc_zone_1", "40")
        fake.set_state("sensor.crop_steering_ec_zone_1", "3")
        room.state[1]["phase"] = "P2"
        room.state[1]["last_phase_change"] = NOW - timedelta(hours=1)
        out = []
        for i in range(passes):
            setup(c, fake, room, mp, i)
            _Wall.current = _Wall(2026, 10, 22, 12, 0) + timedelta(seconds=i * step_s)
            c.loop_once(_Wall.current)
            out.append(len([e for e in c.journal.pending() if e["kind"] == "intent.held"]))
        return out
    return run


SCENARIOS["loop/fires"] = _looping(lambda c, f, r, mp, i: None, passes=1)
SCENARIOS["loop/kill_off_40_passes"] = _looping(lambda c, f, r, mp, i: f.set_state(KILL, "off") if i == 0 else None,
                                                passes=40)
SCENARIOS["loop/tank_min_then_refilled"] = _looping(
    lambda c, f, r, mp, i: _tank_min(c, f, r, mp) if i == 0 else (
        f.set_state(TANK_DIST, "20.0", {"unit_of_measurement": "cm"}) if i == 3 else None), passes=5)
SCENARIOS["loop/zone_off_then_unreadable_then_kill"] = _looping(
    lambda c, f, r, mp, i: {1: lambda: f.set_state(ZONE_SWITCH, "off"),
                            2: lambda: f.set_state(ZONE_SWITCH, "unavailable"),
                            3: lambda: (f.set_state(ZONE_SWITCH, "on"), f.set_state(KILL, "off"))}.get(i, lambda: 0)(),
    passes=5)
SCENARIOS["loop/waste_open"] = _looping(lambda c, f, r, mp, i: _waste_open(c, f, r, mp) if i == 0 else None)
SCENARIOS["loop/feed_ec_drifts"] = _looping(
    lambda c, f, r, mp, i: (_feed(f, r, "ec", f"{2.5 + i * 0.1:.1f}", "1", "2")), passes=6, step_s=30)
SCENARIOS["loop/inflight"] = _looping(
    lambda c, f, r, mp, i: setattr(r, "shot_inflight", {"zone": 2, "valve": "switch.v9", "mainline": None,
                                                         "pump": None, "started": "2026-10-22T10:00:00+00:00"}),
    passes=2)
SCENARIOS["loop/daily_cap"] = _looping(
    lambda c, f, r, mp, i: (mp.setattr(c, "_zone_flow_lps", lambda room, zone: 1.0),
                            r.state[1].update(daily_vol=999.0)), passes=3)


# --------------------------------------------------------------------------------------------- observing
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}:\d{2}|Z)?")
_HHMM = re.compile(r"\b\d{1,2}:\d{2}\b")
_TMP = re.compile(r"[A-Za-z]:\\[^\s'\"]*|/tmp/[^\s'\"]*")
_DROP = {"requested_at", "pump_wait_s", "at", "updated", "since", "last", "started", "ts", "controller_instance",
         "write_failures"}  # times, ids, and a process-wide count the rest of the suite moves


def _norm(value):
    if isinstance(value, str):
        return _HHMM.sub("<hh:mm>", _ISO.sub("<ts>", _TMP.sub("<tmp>", value)))
    if isinstance(value, dict):
        return {str(k): _norm(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0])) if k not in _DROP}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_norm(v) for v in value]
        return sorted(items, key=repr) if isinstance(value, (set, frozenset)) else items
    if isinstance(value, float):
        return round(value, 6)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, datetime):
        return "<ts>"
    return _norm(repr(value))


def _journal(c):
    out = []
    for e in c.journal.pending():
        out.append({"kind": e["kind"], "zone": e.get("zone"), "outcome": e.get("outcome"), "code": e.get("code"),
                    "actor": (e.get("source") or {}).get("actor"), "detail": e.get("detail"),
                    "data": e.get("data")})
    return _norm(out)


def _state(c, room):
    st = room.state.get(1) or {}
    keys = ("phase", "daily_vol", "on_failures", "max_run_latch", "capped_in_a_row", "last_shot", "shots_today")
    return _norm({
        "zone": {k: st.get(k) for k in keys},
        "inflight": getattr(room, "shot_inflight", None),
        "fault": getattr(room, "hardware_fault", None),
        "waste_rule_known": getattr(room, "_waste_rule_known", None),
        "tank_reading": getattr(room, "tank_reading", None),
        "tank_round": getattr(room, "tank_round", None),
        "feed_good": [getattr(room, a, None) is not None for a in ("_feed_last_good_time", "_feed_ph_last_good_time")],
        "batch_invalid": getattr(room, "_strategy_batch_invalid", None),
        "busy": c._busy,
        "shot_room": getattr(c, "_shot_room", None) is not None,
        "held_keys": len(c.__dict__.get("_held_journaled", {})),
    })


def _observe(name, capsys, tmp_path):
    with pytest.MonkeyPatch.context() as mp:
        folder = tmp_path / name.replace("/", "-")
        folder.mkdir()
        mp.setenv("F2_STATE_PATH", str(folder / "state.json"))  # its own journal outbox
        mp.setattr(controller, "SETTINGS_WAIT_PASSES", 0)
        mp.setattr(controller, "WATER_SIZING", ())
        mp.setattr(controller, "_GATE", controller._AuthGate())
        clock = _Clock()
        mp.setattr(controller.time, "sleep", clock.sleep)
        mp.setattr(controller.time, "monotonic", clock.monotonic)
        _Wall.current = _Wall(2026, 10, 22, 12, 0)  # lights 10-22: on
        mp.setattr(controller, "datetime", _Wall)
        mp.setattr(fake_ha, "datetime", _Wall)  # the fake's state times on the same clock
        c, fake, room = _room()
        reads, writes = [], []
        # The supply (Task 12) is read once a pass since the recording. None is saved here, so it changes nothing
        # else; test_pump_queue.py holds that read and what follows from it. Likewise each zone's irrigation_mode
        # select and the timer programs (Task 15), absent here: test_timer_mode.py holds them.
        new_reads = (controller.SUPPLY_SENSOR, controller.TIMERS_SENSOR.format(""))
        mp.setattr(controller, "ha_get", lambda e, timeout=8: (
            e in new_reads or e.endswith("_irrigation_mode") or reads.append(e), fake.ha_get(e, timeout))[1])
        # The feed gate's own read of dosing_config `calibrating` (Task 18) goes through its seam, kept apart: every
        # other read of dosing_config was recorded and is compared.
        calibrating = []
        mp.setattr(controller.Controller, "_read_calibrating", lambda self, r: (
            calibrating.append(r.prefix), fake.ha_get(controller.DOSING_CONFIG.format(r.prefix))[:2])[1])
        mp.setattr(controller, "ha_set", lambda e, s, a=None, timeout=None: (
            writes.append((e, s, a)), fake.ha_set(e, s, a, timeout))[1])
        fake.calls.clear()
        capsys.readouterr()
        result = SCENARIOS[name](c, fake, room, mp)
        logs = [line for line in capsys.readouterr().out.splitlines()]
        return {
            "result": _norm(result),
            "reads": reads,
            "calls": _norm(fake.calls),
            "writes": _norm(writes),
            "log": _norm(logs),
            "journal": _journal(c),
            "state": _state(c, room),
        }


def _without_guard(journal):
    """The recorded journal as the chain journals it: an old intent.held never named its guard."""
    out = []
    for e in journal:
        e = dict(e)
        if e["kind"] == "intent.held":
            e["data"] = {k: v for k, v in e["data"].items() if k != "guard"}
        out.append(e)
    return out


def _first_raises(journal):
    """The recorded journal as the controller journals it since P1 M2: a standing alert's repeated raise (same key and
    code, no alert.cleared of the key between) is no longer journaled; its card and push are unchanged."""
    out, open_ = [], {}
    for e in journal:
        key = (e.get("data") or {}).get("key")
        if e["kind"] == "alert.raised" and key:
            if open_.get(key) == e["code"]:
                continue
            open_[key] = e["code"]
        elif e["kind"] == "alert.cleared":
            open_.pop(key, None)
        out.append(e)
    return out


def _held_named(new, old):
    """The pre-open and sized holds name their guard and code; everything else in the journal is as recorded, less a
    standing alert's repeated raises (_first_raises)."""
    old = _first_raises(old)
    assert len(new) == len(old)
    stripped = _without_guard(new)
    for n, o, full in zip(stripped, old, new):
        if n["kind"] == "intent.held" and o["code"] is None and n["code"] is not None:
            assert full["data"].get("guard")  # a code is only ever added with its guard
            n = dict(n, code=None)
        assert n == o


LONG = ("reads", "calls", "writes", "log")  # kept as a count and a digest: the full lists run to megabytes


def _compact(seen):
    out = {}
    for name, parts in seen.items():
        out[name] = dict(parts)
        for part in LONG:
            text = json.dumps(parts[part], sort_keys=True, ensure_ascii=False)
            out[name][part] = {"n": len(parts[part]), "sha256": hashlib.sha256(text.encode()).hexdigest()}
    return out


def test_matches_what_the_controller_did_before_the_chain(capsys, tmp_path):
    seen = {name: _observe(name, capsys, tmp_path) for name in SCENARIOS}
    if os.environ.get("GUARD_CHAIN_FULL"):  # every list in full, to diff two runs by hand
        with open(os.environ["GUARD_CHAIN_FULL"], "w", encoding="utf-8", newline="\n") as fh:
            json.dump(seen, fh, indent=1, sort_keys=True, ensure_ascii=False)
    seen = _compact(seen)
    if RECORD:
        with open(GOLDEN, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(seen, fh, indent=1, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
        pytest.skip(f"recorded {len(seen)} scenarios")
    with open(GOLDEN, encoding="utf-8") as fh:
        golden = json.load(fh)
    assert sorted(seen) == sorted(golden)
    seen = json.loads(json.dumps(seen))  # the same JSON round trip the recording had
    differ = []
    for name in sorted(golden):
        new, old = seen[name], golden[name]
        differ += [f"{name}: {part}" for part in ("result", "reads", "calls", "writes", "log", "state")
                   if new[part] != old[part]]
        try:
            _held_named(new["journal"], old["journal"])
        except AssertionError:
            differ.append(f"{name}: journal")
    assert differ == []

